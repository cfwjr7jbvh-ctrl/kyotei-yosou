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


def model_tri_probs(p_win: np.ndarray, lam2: float, lam3: float, s2=None, s3=None, bonus=None, extra=None) -> np.ndarray:
    T = pl_trifecta_matrix(p_win, lam2, lam3, s2, s3, bonus, extra)
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
                ev_grid=(1.0, 1.1, 1.2, 1.3, 1.5, 2.0), p_min: float = 0.01, max_bets: int = 5,
                filt=None, extra=None, n_boot: int = 1000, seed: int = 0):
    """各EV閾値で、1点100円ずつ買った場合の成績。払戻は実際の払戻金を使う。

    回収率の90%信頼区間をブートストラップ(レースを重複ありで引き直す)で出す。
    区間の下限が100%を超えていれば「たまたま」ではない可能性が高い。
    """
    rng = np.random.default_rng(seed)
    rows = []
    n = len(P_tri)
    for th in ev_grid:
        cost = np.zeros(n)
        ret = np.zeros(n)
        hits = 0
        for i in range(n):
            if not np.isfinite(O[i]).any():
                continue
            p = P_tri[i] if filt is None else filt.adjust(P_tri[i], O[i], extra[i] if extra is not None else None)
            for s in select_bets(p, O[i], th, p_min, max_bets):
                cost[i] += 100
                if COMBOS.index(s["combo"]) == hit_idx[i]:
                    hits += 1
                    ret[i] += pay[i]
        bets = int(cost.sum() // 100)
        row = {"ev_min": th, "bets": bets, "hit_rate": round(hits / bets, 4) if bets else None,
               "roi": round(ret.sum() / cost.sum(), 4) if bets else None,
               "profit_yen": int(ret.sum() - cost.sum())}
        if bets >= 30:
            idx = rng.integers(0, n, (n_boot, n))
            c, r = cost[idx].sum(1), ret[idx].sum(1)
            roi = r[c > 0] / c[c > 0]
            row["roi_lo90"], row["roi_hi90"] = (round(float(np.quantile(roi, q)), 4) for q in (0.05, 0.95))
        rows.append(row)
    return rows


class BetFilter:
    """「買う/買わない」の判断。高い期待値に見える組ほどモデルが過信していることが多いので、
    実際の的中データから確率を補正し直す(ロジスティック回帰)。

    入力: log(合成確率), log(オッズ), モデルと市場の食い違い, レースの荒れ度(1着確率のエントロピー)
    """

    def _x(self, p, odds, pk, ent):
        lp = np.log(np.clip(p, 1e-6, 1))
        lo = np.log(np.clip(np.nan_to_num(odds, nan=1e4), 1, 1e5))
        dis = lp - np.log(np.clip(pk, 1e-6, 1))
        return np.column_stack([lp, lo, dis, np.full(len(p), ent)])

    def fit(self, PB, O, PK, ENT, y):
        from sklearn.linear_model import LogisticRegression
        X, t = [], []
        for i in range(len(PB)):
            if not np.isfinite(O[i]).any():
                continue
            cand = np.argsort(-(PB[i] * np.nan_to_num(O[i])))[:20]  # 期待値上位の候補で学習
            X.append(self._x(PB[i][cand], O[i][cand], PK[i][cand], ENT[i]))
            t.append((cand == y[i]).astype(int))
        self.m = LogisticRegression(C=1.0, max_iter=1000).fit(np.vstack(X), np.concatenate(t))
        return self

    def adjust(self, p, odds, extra):
        pk, ent = extra
        q = p.copy()
        cand = np.argsort(-(p * np.nan_to_num(odds)))[:20]
        q[cand] = self.m.predict_proba(self._x(p[cand], odds[cand], pk[cand], ent))[:, 1]
        return q


def entropy(w):
    w = np.clip(np.asarray(w, float), 1e-9, 1)
    w = w / w.sum()
    return float(-(w * np.log(w)).sum())
