"""改良案 E1 の検証: 公式コンピュータ予想のフォーカスに入った組は、オッズが下がりすぎて(買われすぎて)いるか。

確定オッズから見た確率(市場確率)と実際の的中を比べる。市場が正しければ「的中数 ÷ 市場確率の合計」は1前後。
フォーカスの組がそれより小さく、そうでない組が1前後なら、フォーカスの組は買われすぎ(期待値を割り引くべき)。
オッズの高さで結果が変わる(大穴ほど買われすぎ)ので、市場確率の大きさで区切って比べる。

  python scripts/pcx_eval.py   # data/odds と data/pcexpect の両方があるレースで集計、reports/pcx_eval.json に保存
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.betting import COMBOS, market_probs, odds_matrix  # noqa: E402

BINS = [0, 0.005, 0.01, 0.02, 0.04, 0.08, 1.0]


def main(n_boot: int = 2000):
    odds = pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in sorted((ROOT / "data/odds").glob("odds3t_*.csv.gz"))])
    pcx = pd.concat([pd.read_csv(p, dtype={"race_id": str, "focus3": str, "marks": str})
                     for p in sorted((ROOT / "data/pcexpect").glob("pcx_*.csv.gz"))])
    races = pd.concat([pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id", "tri_combo", "tri_pay"])
                       for p in sorted((ROOT / "data/history").glob("races_*.csv.gz"))]).drop_duplicates("race_id")
    pcx = pcx[pcx["focus3"].fillna("") != ""]
    rids = sorted(set(pcx["race_id"]) & set(odds["race_id"]) & set(races.loc[races["tri_combo"].isin(COMBOS), "race_id"]))
    out = {"races": len(rids)}
    if len(rids) < 200:
        out["note"] = "オッズとコンピュータ予想の両方があるレースがまだ少ない"
        print(out)
        (ROOT / "reports/pcx_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    O = odds_matrix(odds, rids)
    ok = np.isfinite(O).sum(1) >= 100
    rids = [r for r, k in zip(rids, ok) if k]
    O = O[ok]
    PK = np.array([market_probs(o) for o in O])
    rc = races.set_index("race_id").loc[rids]
    y = np.array([COMBOS.index(c) for c in rc["tri_combo"]])
    pay = rc["tri_pay"].values.astype(float)
    fx = pcx.set_index("race_id").loc[rids, "focus3"].str.split(";")
    F = np.zeros_like(PK, dtype=bool)
    for i, combos in enumerate(fx):
        for c in combos:
            if c in COMBOS:
                F[i, COMBOS.index(c)] = True
    H = np.zeros_like(PK, dtype=bool)
    H[np.arange(len(y)), y] = True
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(y), (n_boot, len(y)))
    rows = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        m = (PK >= lo) & (PK < hi)
        r = {"market_prob": f"{lo:.3f}〜{hi:.3f}"}
        for name, sel in (("focus", m & F), ("other", m & ~F)):
            hits, exp = (H & sel).sum(1), (PK * sel).sum(1)  # レースごと
            if exp.sum() < 1:
                continue
            ratio_b = hits[idx].sum(1) / np.maximum(exp[idx].sum(1), 1e-9)
            r[name] = {"combos": int(sel.sum()), "hits": int(hits.sum()), "expected": round(float(exp.sum()), 1),
                       "ratio": round(float(hits.sum() / exp.sum()), 3),
                       "ratio_ci90": [round(float(np.quantile(ratio_b, q)), 3) for q in (0.05, 0.95)]}
        rows.append(r)
    out["by_market_prob"] = rows
    # フォーカスを全部買う / それ以外を全部買う(1点100円)の回収率
    for name, sel in (("focus", F), ("other", ~F)):
        cost = sel.sum(1) * 100.0
        ret = np.where(sel[np.arange(len(y)), y], pay, 0.0)
        rb = ret[idx].sum(1) / cost[idx].sum(1)
        out[f"roi_all_{name}"] = {"roi": round(float(ret.sum() / cost.sum()), 4),
                                  "ci90": [round(float(np.quantile(rb, q)), 4) for q in (0.05, 0.95)]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (ROOT / "reports/pcx_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
