"""荒れ度の検証: 「荒れそうなレースだけ期待値で買う」と「全レースで期待値で買う」の回収率を比べる。

  python scripts/upset_eval.py --cache models/upset_preds.pkl   # 学習して予測を保存し、検証する
  python scripts/upset_eval.py --cache models/upset_preds.pkl --reuse   # 保存した予測で検証だけやり直す
  python scripts/upset_eval.py --walk-forward   # オッズのある全期間で検証(本番の判定はこちら)

ふつう: 学習・検証・テストの分け方は train_eval.py と同じ(直前予想モデル)。テスト期間の予測だけを使う。
--walk-forward: オッズのある期間を半年ごとに区切り、その半年より前のデータだけで学習したモデルで予想する。
  どの期間のオッズでも「答えを見ていない予想」で検証できるので、集めたオッズを全部使える。
結果は reports/upset_eval.json に保存(数字のみ)。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import pickle
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def _tri_probs(T, te, p_ens, s23, stack, extra, rids):
    """3連単120通りの確率(本番の predict.py と同じ: 2着・3着の強さ、枠のボーナス、RaceCond の追加項まで)。"""
    from kyotei.betting import model_tri_probs
    from kyotei.ensemble import align_extra
    W = T.win_matrix(te, p_ens, rids)
    S2, S3 = T.win_matrix(te, s23[0], rids), T.win_matrix(te, s23[1], rids)
    EX = align_extra(extra, rids)
    PM = np.array([model_tri_probs(w, stack.lam2, stack.lam3, a, b, stack.bonus, None if EX is None else (EX[0][i], EX[1][i]))
                   for i, (w, a, b) in enumerate(zip(W, S2, S3))])
    return PM, W


def predictions(log):
    import train_eval as T
    from kyotei import features
    from kyotei.betting import COMBOS, odds_matrix
    from kyotei.data import load_history
    ent, races, odds = load_history()
    df = features.build(ent, races)
    ok = df.groupby("race_id")["finish"].apply(lambda s: (s <= 3).sum() == 3)
    df = df[df["race_id"].isin(ok[ok].index)].reset_index(drop=True)
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    tr, va, te = df[df.date < d1], df[(df.date >= d1) & (df.date < d2)], df[df.date >= d2]
    log(f"test {te.date.min()}〜{te.date.max()} races={te.race_id.nunique()}")
    _, _, stack, p_ens, s23, _, extra = T.run_stage("late", df, races, tr, va, te, {"stages": {}}, log)
    rids = np.sort(te["race_id"].unique())
    PM, W = _tri_probs(T, te, p_ens, s23, stack, extra, rids)
    rc = races.set_index("race_id").reindex(rids)
    good = rc["tri_combo"].isin(COMBOS).values & rc["tri_pay"].notna().values
    O = odds_matrix(odds, rids) if odds is not None else np.full((len(rids), 120), np.nan)
    return {"rids": rids[good], "W": W[good], "PM": PM[good], "O": O[good],
            "y": np.array([COMBOS.index(c) for c in rc["tri_combo"].values[good]]),
            "pay": rc["tri_pay"].values[good].astype(float)}


def predictions_walk_forward(log, min_train_days: int = 270, max_train_days: int | None = None):
    """オッズのあるレースを半年ごとに区切り、それより前のデータだけで学習して予想する(先の情報は使わない)。"""
    import pandas as pd
    import train_eval as T
    from kyotei import features
    from kyotei.betting import COMBOS, odds_matrix
    from kyotei.data import load_history
    ent, races, odds = load_history()
    if odds is None or odds.empty:
        raise SystemExit("オッズがありません")
    df = features.build(ent, races)
    ok = df.groupby("race_id")["finish"].apply(lambda s: (s <= 3).sum() == 3)
    df = df[df["race_id"].isin(ok[ok].index)].reset_index(drop=True)
    cnt = odds[odds["combo"].isin(COMBOS)].groupby("race_id")["odds"].count()
    orids = set(cnt[cnt >= 100].index)
    d = pd.to_datetime(df["date"])
    df["_half"] = d.dt.year.astype(str) + np.where(d.dt.month <= 6, "H1", "H2")
    first = d.min()
    out = {k: [] for k in ("rids", "W", "PM", "O", "y", "pay")}
    folds = []
    for half in sorted(df.loc[df["race_id"].isin(orids), "_half"].unique()):
        te = df[(df["_half"] == half) & df["race_id"].isin(orids)]
        start = te["date"].min()
        past = df[df["date"] < start]
        if max_train_days:  # 手元の動作確認用(メモリ節約)
            past = past[pd.to_datetime(past["date"]) >= pd.Timestamp(start) - pd.Timedelta(days=max_train_days)]
        if (pd.Timestamp(start) - first).days < min_train_days or past.empty:
            log(f"{half}: 学習データが足りないので飛ばす")
            continue
        days = np.sort(past["date"].unique())
        # 重み(アンサンブル)は直前の90日(短ければ2割)で決め、基本モデルはそれより前で学習。
        # 本番は毎週学び直すので、ここでも基本モデルがなるべく新しくなるよう検証用の期間は短めにする
        d1 = days[max(int(len(days) * 0.8), len(days) - 90)]
        tr, va = past[past["date"] < d1], past[past["date"] >= d1]
        log(f"{half}: 学習 〜{tr.date.max()} / 重み {d1}〜{va.date.max()} / 予想 {te.race_id.nunique()}レース")
        # run_stage は (feats, models, stack, p_ens, s23, cond, extra) を返す(2026-10-05 の RaceCond から7つ。5つで受けていて全期間の検証が止まっていた)
        _, _, stack, p_ens, s23, _, extra = T.run_stage("late", df.drop(columns="_half"), races, tr.drop(columns="_half"),
                                                        va.drop(columns="_half"), te.drop(columns="_half"), {"stages": {}}, log)
        rids = np.sort(te["race_id"].unique())
        PM, W = _tri_probs(T, te, p_ens, s23, stack, extra, rids)
        rc = races.set_index("race_id").reindex(rids)
        good = rc["tri_combo"].isin(COMBOS).values & rc["tri_pay"].notna().values
        out["rids"].append(rids[good]); out["W"].append(W[good]); out["PM"].append(PM[good])
        out["O"].append(odds_matrix(odds, rids)[good])
        out["y"].append(np.array([COMBOS.index(c) for c in rc["tri_combo"].values[good]]))
        out["pay"].append(rc["tri_pay"].values[good].astype(float))
        folds.append({"half": half, "train_until": str(tr.date.max()), "races": int(good.sum())})
    res = {k: np.concatenate(v) for k, v in out.items()}
    res["folds"] = folds
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "models/upset_preds.pkl"))
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--walk-forward", action="store_true", help="オッズのある全期間で、その時点より前だけで学習して検証")
    ap.add_argument("--max-train-days", type=int, default=None, help="手元の動作確認用: 学習に使う日数の上限")
    ap.add_argument("--out", default=str(ROOT / "reports/upset_eval.json"))
    a = ap.parse_args()
    t0 = time.time()

    def log(*x):
        print(f"[{time.time()-t0:5.0f}s]", *x, flush=True)
    cache = pathlib.Path(a.cache)
    if a.reuse and cache.exists():
        d = pickle.load(open(cache, "rb"))
    else:
        d = predictions_walk_forward(log, max_train_days=a.max_train_days) if a.walk_forward else predictions(log)
        cache.parent.mkdir(parents=True, exist_ok=True)
        pickle.dump(d, open(cache, "wb"))
        log("saved", cache)
    from kyotei.arashi import study
    folds = d.pop("folds", None)
    res = study(**d, log=log)
    res["mode"] = "walk_forward" if folds is not None else "test_split"
    if folds is not None:
        res["folds"] = folds
    pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    log("wrote", a.out)
    if folds is not None and res.get("ev_detail") and a.out == str(ROOT / "reports/upset_eval.json"):
        # サイトの成績タブ「期待値で買った場合の検証(全期間)」用(暗号化)
        import datetime as dt
        from kyotei.publish import write_json
        write_json(ROOT / "docs/data/ev_check.json", {
            "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
            "folds": folds, **res["ev_detail"]})
        log("wrote docs/data/ev_check.json")


if __name__ == "__main__":
    main()
