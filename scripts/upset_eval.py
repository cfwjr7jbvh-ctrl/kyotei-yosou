"""荒れ度の検証: 「荒れそうなレースだけ期待値で買う」と「全レースで期待値で買う」の回収率を比べる。

  python scripts/upset_eval.py --cache models/upset_preds.pkl   # 学習して予測を保存し、検証する
  python scripts/upset_eval.py --cache models/upset_preds.pkl --reuse   # 保存した予測で検証だけやり直す

学習・検証・テストの分け方は train_eval.py と同じ(直前予想モデル)。テスト期間の予測だけを使う。
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


def predictions(log):
    import train_eval as T
    from kyotei import features
    from kyotei.betting import COMBOS, model_tri_probs, odds_matrix
    from kyotei.data import load_history
    ent, races, odds = load_history()
    df = features.build(ent, races)
    ok = df.groupby("race_id")["finish"].apply(lambda s: (s <= 3).sum() == 3)
    df = df[df["race_id"].isin(ok[ok].index)].reset_index(drop=True)
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    tr, va, te = df[df.date < d1], df[(df.date >= d1) & (df.date < d2)], df[df.date >= d2]
    log(f"test {te.date.min()}〜{te.date.max()} races={te.race_id.nunique()}")
    _, _, stack, p_ens, s23 = T.run_stage("late", df, races, tr, va, te, {"stages": {}}, log)
    rids = np.sort(te["race_id"].unique())
    W = T.win_matrix(te, p_ens, rids)
    S2, S3 = T.win_matrix(te, s23[0], rids), T.win_matrix(te, s23[1], rids)
    PM = np.array([model_tri_probs(w, stack.lam2, stack.lam3, a, b, stack.bonus) for w, a, b in zip(W, S2, S3)])
    rc = races.set_index("race_id").reindex(rids)
    good = rc["tri_combo"].isin(COMBOS).values & rc["tri_pay"].notna().values
    O = odds_matrix(odds, rids) if odds is not None else np.full((len(rids), 120), np.nan)
    return {"rids": rids[good], "W": W[good], "PM": PM[good], "O": O[good],
            "y": np.array([COMBOS.index(c) for c in rc["tri_combo"].values[good]]),
            "pay": rc["tri_pay"].values[good].astype(float)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "models/upset_preds.pkl"))
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "reports/upset_eval.json"))
    a = ap.parse_args()
    t0 = time.time()

    def log(*x):
        print(f"[{time.time()-t0:5.0f}s]", *x, flush=True)
    cache = pathlib.Path(a.cache)
    if a.reuse and cache.exists():
        d = pickle.load(open(cache, "rb"))
    else:
        d = predictions(log)
        cache.parent.mkdir(parents=True, exist_ok=True)
        pickle.dump(d, open(cache, "wb"))
        log("saved", cache)
    from kyotei.arashi import study
    res = study(**d, log=log)
    pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    log("wrote", a.out)


if __name__ == "__main__":
    main()
