"""集めた「足の評価」が、オッズ(市場)に上乗せして当たりを予測できるかを確かめる。

data/extra(暗号化)を読み、レース結果と確定オッズに突き合わせる。出力は数字の集計だけ(文章は出さない):
reports/extra_eval.json

見ること:
- 記者の直前気配(行き足・回り足・ピット離れ・モーター評価)の記号ごとの1着率・3着内率と、その艇の市場の1着確率の平均
  → 「実際の1着率 ÷ 市場の1着確率」が1から離れていれば、市場がまだ値段に入れていない情報
- オリジナル展示(一周・回り足・直線のタイム)のレース内順位ごとに同じもの
- 選手コメントの言葉の点数(良い言葉 − 悪い言葉)ごとに同じもの
- ロジスティック回帰: 1着 ~ log(市場の1着確率) + 各特徴。係数と、レース単位で引き直した90%区間
"""
from __future__ import annotations

import gzip
import io
import itertools
import json
import os
import pathlib
import re
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "reports/extra_eval.json"
GOOD = r"良い|いい|良さ|良く|強い|強め|上位|出てる|出ている|しっかり|上々|問題ない|乗りやすい|伸びる|伸びて|来てる|仕上が|悪くない|戦える|十分|合って|上向|手応え"
BAD = r"弱い|弱め|足りない|悪い|良くない|下位|劣勢|厳しい|乗りにく|不安|微妙|課題|物足り|ない感じ|今ひとつ|今一つ|イマイチ|劣る|苦しい|重い|伸びない|出ていない|出てない"
ICON = {"icon_circle2": 2, "icon_double": 2, "icon_circle": 1, "icon_triangle": 0, "icon_cross": -1, "icon_x": -1}


def load_all(src: str) -> pd.DataFrame | None:
    from fetch_extra import load
    yms = sorted({p.name.split("_")[1][:6] for p in (ROOT / "data/extra").glob(f"{src}_*.csv.gz.enc")})
    parts = [load(src, ym) for ym in yms]
    parts = [p for p in parts if p is not None]
    return pd.concat(parts, ignore_index=True) if parts else None


def score_text(s) -> float | None:
    if not isinstance(s, str) or not s.strip():
        return None
    neg = len(re.findall(BAD, s))
    pos = len(re.findall(GOOD, s)) - len(re.findall(r"良くない|悪くない", s))  # 「良くない」を良い言葉に数えない
    pos += len(re.findall(r"悪くない", s))
    return float(pos - neg)


def market_win(odds: pd.DataFrame, race_ids) -> pd.DataFrame:
    o = odds[odds["race_id"].isin(set(race_ids))].copy()
    o = o[o["odds"] > 0]
    o["q"] = 1.0 / o["odds"]
    o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
    o["lane"] = o["combo"].str.slice(0, 1).astype(int)
    return o.groupby(["race_id", "lane"])["q"].sum().rename("p_mkt").reset_index()


def ratio_table(df: pd.DataFrame, col: str) -> list[dict]:
    out = []
    for v, g in df.dropna(subset=[col]).groupby(col):
        if len(g) < 20:
            continue
        out.append({"value": v if not isinstance(v, (np.floating, float)) else round(float(v), 3), "n": int(len(g)),
                    "win": round(float(g["win"].mean()), 4), "top3": round(float(g["top3"].mean()), 4),
                    "p_mkt": round(float(g["p_mkt"].mean()), 4) if g["p_mkt"].notna().any() else None,
                    "win_over_mkt": round(float(g["win"].sum() / g["p_mkt"].sum()), 3) if g["p_mkt"].notna().all() and g["p_mkt"].sum() > 0 else None})
    return out


def logit_ci(df: pd.DataFrame, feats: list[str], boot: int = 300) -> dict:
    from sklearn.linear_model import LogisticRegression
    d = df.dropna(subset=["p_mkt"] + feats)
    if len(d) < 300 or d["race_id"].nunique() < 60:
        return {"n": int(len(d)), "note": "まだ少ない"}
    X = np.column_stack([np.log(d["p_mkt"].clip(1e-4))] + [d[f].astype(float) for f in feats])
    y = d["win"].values
    m = LogisticRegression(C=1e3, max_iter=2000).fit(X, y)
    rids = d["race_id"].values
    u = np.unique(rids)
    idx = {r: np.where(rids == r)[0] for r in u}
    rng = np.random.default_rng(0)
    coefs = []
    for _ in range(boot):
        s = np.concatenate([idx[r] for r in rng.choice(u, len(u))])
        try:
            coefs.append(LogisticRegression(C=1e3, max_iter=2000).fit(X[s], y[s]).coef_[0])
        except Exception:  # noqa: BLE001
            pass
    c = np.array(coefs)
    names = ["log_p_mkt"] + feats
    return {"n": int(len(d)), "races": int(len(u)),
            "coef": {n: round(float(v), 3) for n, v in zip(names, m.coef_[0])},
            "ci90": {n: [round(float(np.percentile(c[:, i], 5)), 3), round(float(np.percentile(c[:, i], 95)), 3)] for i, n in enumerate(names)}}


def main():
    nk = load_all("nikkan")
    res = {"sources": {}}
    if nk is None or nk.empty:
        OUT.write_text(json.dumps({"note": "まだデータがありません"}, ensure_ascii=False, indent=1))
        return
    from kyotei.data import load_history
    months = sorted(nk["race_id"].str.slice(0, 6).unique())
    ent, races, odds = load_history(since=months[0])
    e = ent[["race_id", "lane", "finish"]].copy()
    e["race_id"] = e["race_id"].astype(str)
    nk["race_id"] = nk["race_id"].astype(str)
    d = nk.merge(e, on=["race_id", "lane"], how="inner")
    d["win"] = (d["finish"] == 1).astype(int)
    d["top3"] = d["finish"].between(1, 3).astype(int)
    if odds is not None:
        odds["race_id"] = odds["race_id"].astype(str)
        d = d.merge(market_win(odds, d["race_id"].unique()), on=["race_id", "lane"], how="left")
    else:
        d["p_mkt"] = np.nan
    for k in ("k_iki", "k_mawari", "k_pit", "k_motor"):
        d[k + "_v"] = d[k].map(ICON)
    for k in ("o_ex", "o_lap", "o_mawari", "o_straight"):
        d[k + "_rk"] = d.groupby("race_id")[k].rank(method="min")
    d["c_prev_score"] = d["c_prev"].map(score_text)
    d["c_other_score"] = d["c_other"].map(score_text) if "c_other" in d else np.nan
    d["kehai_sum"] = d[["k_iki_v", "k_mawari_v", "k_pit_v", "k_motor_v"]].sum(axis=1, min_count=1)
    d["kehai_rel"] = d["kehai_sum"] - d.groupby("race_id")["kehai_sum"].transform("mean")
    res["sources"]["nikkan"] = {
        "rows": int(len(d)), "races": int(d["race_id"].nunique()), "with_odds": int(d.dropna(subset=["p_mkt"])["race_id"].nunique()),
        "period": [str(d["race_id"].min())[:8], str(d["race_id"].max())[:8]],
        "venues": {str(k): int(v) for k, v in d.groupby("jcd")["race_id"].nunique().items()},
        "icons_seen": {k: d[k].value_counts().to_dict() for k in ("k_iki", "k_mawari", "k_pit", "k_motor")},
        "by": {c: ratio_table(d, c) for c in ("k_iki", "k_mawari", "k_pit", "k_motor", "kehai_sum", "o_ex_rk", "o_lap_rk",
                                               "o_mawari_rk", "o_straight_rk", "c_prev_score")},
        "logit": {
            "kehai": logit_ci(d, ["kehai_rel"]),
            "orig_ex": logit_ci(d, ["o_lap_rk", "o_mawari_rk"]),
            "comment": logit_ci(d.assign(c=d["c_prev_score"].clip(-3, 3)), ["c"]),
        },
    }
    for src in ("comment", "zenken"):
        x = load_all(src)
        res["sources"][src] = {"rows": 0} if x is None else {"rows": int(len(x)), "days": int(x["date"].nunique()),
                                                             "venues": {str(k): int(v) for k, v in x.groupby("jcd").size().items()}}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res["sources"]["nikkan"]["logit"], ensure_ascii=False))


if __name__ == "__main__":
    main()
