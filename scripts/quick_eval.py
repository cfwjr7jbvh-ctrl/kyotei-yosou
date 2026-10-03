"""改良案を手元でざっと比べる(GitHub Actions に出す前のふるい分け用、改良案 F7)。

  python scripts/quick_eval.py save /tmp/a.pkl            # 今のコードで基本モデルを1回だけ学習し、予測を保存
  python scripts/quick_eval.py compare /tmp/a.pkl /tmp/b.pkl  # 2つを同じアンサンブルで比べる

- save: 本番と同じ期間分割(学習60%/検証20%/テスト20%)で、各基本モデルの検証・テストの予測を保存する。
  速さ優先で GBDT は乱数1回、lightgbm が無ければ sklearn(ランキング学習は省略)。
- compare: いま手元にあるコードのアンサンブルで両方を組み直し、テストの各レースの誤差の差を出す。
  差の90%区間(レースを引き直すブートストラップ)が0をまたがなければ、偶然ではない可能性が高い。
  特徴量を変えた案は「変更前のコードで save → 変更後で save → compare」、
  アンサンブルだけ変えた案は「同じ保存ファイルを、変更前後のコードで compare」で比べる。
- データは同じものを使うこと(途中でデータが増えると期間分割がずれる)。compare はテストのレースが一致するか表示する。
"""
from __future__ import annotations

import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import features  # noqa: E402
from kyotei.ensemble import Stacker  # noqa: E402
from kyotei.plackett import trifecta_logprob_batch  # noqa: E402


def save(out: str):
    from kyotei.data import load_history
    from kyotei.models import GBDTWin, available_models
    t0 = time.time()
    GBDTWin.n_seeds = 1
    ent, races, _ = load_history()
    df = features.build(ent, races)
    ok = df.groupby("race_id")["finish"].apply(lambda s: (s <= 3).sum() == 3)
    df = df[df["race_id"].isin(ok[ok].index)].reset_index(drop=True)
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    tr, va, te = df[df.date < d1], df[(df.date >= d1) & (df.date < d2)], df[df.date >= d2]
    print(f"[{time.time()-t0:.0f}s] rows={len(df)} test={te.race_id.nunique()} races ({d2}〜)", flush=True)
    res = {"races": races, "split": (str(d1), str(d2))}
    keep = ["race_id", "lane", "finish", "jcd", "date"] + [c for c in ("race_grade", "course") if c in df]
    for stage in ("early", "late"):
        feats = features.feature_columns(df, stage)
        pv, pt = {}, {}
        for M in available_models():
            m = M(feats).fit(tr)
            pv[M.name], pt[M.name] = m.predict_proba(va), m.predict_proba(te)
        res[stage] = {"feats": feats, "va": va[keep].reset_index(drop=True),
                      "te": te[keep].reset_index(drop=True), "pv": pv, "pt": pt}
        print(f"[{time.time()-t0:.0f}s] {stage}: {len(feats)} features", flush=True)
    pickle.dump(res, open(out, "wb"))
    print("saved", out)


def per_race(res, stage):
    S = res[stage]
    st = Stacker().fit(S["va"], S["pv"])
    te = S["te"][["race_id", "lane", "finish"]].copy()
    te["p"] = st.predict(S["te"], S["pt"])
    if hasattr(st, "strengths"):
        te["s2"], te["s3"] = st.strengths(S["te"], S["pt"])
    te = te.sort_values(["race_id", "lane"])

    def piv(c, fill):
        return te.pivot(index="race_id", columns="lane", values=c).reindex(columns=range(1, 7)).fillna(fill)
    P, F = piv("p", 1e-6), te.pivot(index="race_id", columns="lane", values="finish").reindex(columns=range(1, 7))
    ok = (F.fillna(99).values <= 3).sum(1) == 3
    o = np.argsort(F.fillna(99).values, axis=1)[:, :3][ok]
    Pv = P.values[ok] / P.values[ok].sum(1, keepdims=True)
    S2 = piv("s2", 1e-9).values[ok] if "s2" in te else None
    S3 = piv("s3", 1e-9).values[ok] if "s3" in te else None
    kw = {"bonus": st.bonus} if getattr(st, "bonus", None) is not None else {}
    win = -np.log(Pv[np.arange(len(Pv)), o[:, 0]])
    tri = -trifecta_logprob_batch(Pv, o, st.lam2, st.lam3, S2, S3, **kw)
    return pd.DataFrame({"win": win, "tri": tri}, index=P.index[ok])


def compare(a_path: str, b_path: str, n_boot: int = 1000):
    a, b = pickle.load(open(a_path, "rb")), pickle.load(open(b_path, "rb"))
    if a.get("split") != b.get("split"):
        print("注意: 期間分割が違います(データが違う可能性)", a.get("split"), b.get("split"))
    rng = np.random.default_rng(0)
    for stage in ("early", "late"):
        ra, rb = per_race(a, stage), per_race(b, stage)
        j = ra.join(rb, lsuffix="_a", rsuffix="_b", how="inner")
        print(f"== {stage}: 共通のテスト {len(j)} レース(a {len(ra)}, b {len(rb)})、特徴量 a={len(a[stage]['feats'])} b={len(b[stage]['feats'])}")
        for m in ("win", "tri"):
            d = (j[f"{m}_b"] - j[f"{m}_a"]).values
            boots = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)])
            lo, hi = np.quantile(boots, [0.05, 0.95])
            verdict = "改善" if hi < 0 else "悪化" if lo > 0 else "差なし(偶然の範囲)"
            print(f"  {m}_logloss a={j[f'{m}_a'].mean():.4f} b={j[f'{m}_b'].mean():.4f} 差={d.mean():+.4f} "
                  f"90%区間[{lo:+.4f}, {hi:+.4f}] → {verdict}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "save" and len(sys.argv) == 3:
        save(sys.argv[2])
    elif cmd == "compare" and len(sys.argv) == 4:
        compare(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
