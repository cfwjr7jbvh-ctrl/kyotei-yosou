"""オッズと組み合わせて「期待値のある買い目」を選ぶ。

- 市場確率: オッズの逆数を正規化したもの(控除率25%を除いた人気の評価)
- 合成確率: p ∝ p_model^a × p_market^b(Benter方式)。a, b は過去データで推定。
  モデル単体より、市場の情報も混ぜた方が確率の精度が上がる。
- 期待値: EV = p × オッズ。EV が閾値を超えた組だけを買う。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .plackett import PERMS3, pl_trifecta_matrix

COMBOS = [f"{a+1}-{b+1}-{c+1}" for a, b, c in PERMS3]


def model_tri_probs(p_win: np.ndarray, lam2: float, lam3: float) -> np.ndarray:
    T = pl_trifecta_matrix(p_win, lam2, lam3)
    return T[PERMS3[:, 0], PERMS3[:, 1], PERMS3[:, 2]]


def market_probs(odds: np.ndarray) -> np.ndarray:
    inv = np.where(np.isfinite(odds) & (odds > 0), 1 / odds, 0.0)
    return inv / inv.sum() if inv.sum() > 0 else np.full(len(odds), 1 / len(odds))


def blend(pm: np.ndarray, pk: np.ndarray, a: float, b: float) -> np.ndarray:
    lg = a * np.log(np.clip(pm, 1e-7, 1)) + b * np.log(np.clip(pk, 1e-7, 1))
    e = np.exp(lg - lg.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def fit_blend(PM: np.ndarray, PK: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """PM, PK: (n,120) モデル/市場の3連単確率, y: 的中組の番号(0..119)。"""
    r = np.arange(len(y))

    def nll(x):
        return -np.log(blend(PM, PK, x[0], x[1])[r, y] + 1e-12).mean()
    res = minimize(nll, [0.5, 0.5], bounds=[(0, 3), (0, 3)], method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])


def select_bets(p: np.ndarray, odds: np.ndarray, ev_min: float = 1.2, p_min: float = 0.01,
                max_bets: int = 5) -> list[dict]:
    ev = p * np.nan_to_num(odds, nan=0)
    idx = [i for i in np.argsort(-ev) if ev[i] >= ev_min and p[i] >= p_min][:max_bets]
    out = []
    for i in idx:
        b = odds[i] - 1
        kelly = max(0.0, (p[i] * odds[i] - 1) / b) if b > 0 else 0.0
        out.append({"combo": COMBOS[i], "prob": round(float(p[i]), 4), "odds": float(odds[i]),
                    "ev": round(float(ev[i]), 2), "kelly_quarter": round(kelly / 4, 4)})
    return out


def odds_matrix(odds_long: pd.DataFrame, race_ids) -> np.ndarray:
    w = odds_long[odds_long["combo"].isin(COMBOS)].pivot(index="race_id", columns="combo", values="odds")
    return w.reindex(index=race_ids, columns=COMBOS).values


def backtest_ev(P_tri: np.ndarray, O: np.ndarray, hit_idx: np.ndarray, pay: np.ndarray,
                ev_grid=(1.0, 1.1, 1.2, 1.3, 1.5, 2.0), p_min: float = 0.01, max_bets: int = 5):
    """各EV閾値で、1点100円ずつ買った場合の成績。払戻は実際の払戻金を使う。"""
    rows = []
    for th in ev_grid:
        bets = hits = 0
        ret = 0.0
        days_ret = []
        for i in range(len(P_tri)):
            if not np.isfinite(O[i]).any():
                continue
            sel = select_bets(P_tri[i], O[i], th, p_min, max_bets)
            for s in sel:
                bets += 1
                if COMBOS.index(s["combo"]) == hit_idx[i]:
                    hits += 1
                    ret += pay[i]
            days_ret.append(len(sel))
        rows.append({"ev_min": th, "bets": bets, "hit_rate": round(hits / bets, 4) if bets else None,
                     "roi": round(ret / (100 * bets), 4) if bets else None,
                     "profit_yen": int(ret - 100 * bets)})
    return rows
