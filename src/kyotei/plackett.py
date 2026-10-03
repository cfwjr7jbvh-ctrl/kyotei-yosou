"""1着確率(または強さ)から2連単・3連単の確率を作る。

単純なPlackett-Luce(Harville)は2着・3着で強い艇を過大評価しがちなので、
Benter流に「2着目以降は強さを lam2, lam3 乗して平らにする」補正を入れる。
lam は過去データで対数尤度が最大になるよう推定する(fit_discount)。
"""
from __future__ import annotations

import itertools

import numpy as np
from scipy.optimize import minimize

PERMS3 = np.array(list(itertools.permutations(range(6), 3)))
PERMS2 = np.array(list(itertools.permutations(range(6), 2)))


def _norm(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-9, None)
    return p / p.sum()


def pl_trifecta_matrix(p_win, lam2: float = 1.0, lam3: float = 1.0) -> np.ndarray:
    """6x6x6の3連単確率(同一艇を含む組は0)。"""
    p = _norm(p_win)
    s2, s3 = p ** lam2, p ** lam3
    i, j, k = PERMS3[:, 0], PERMS3[:, 1], PERMS3[:, 2]
    out = np.zeros((6, 6, 6))
    out[i, j, k] = p[i] * s2[j] / (s2.sum() - s2[i]) * s3[k] / (s3.sum() - s3[i] - s3[j])
    return out / out.sum()


def pl_exacta_matrix(p_win, lam2: float = 1.0) -> np.ndarray:
    p = _norm(p_win)
    s2 = p ** lam2
    i, j = PERMS2[:, 0], PERMS2[:, 1]
    out = np.zeros((6, 6))
    out[i, j] = p[i] * s2[j] / (s2.sum() - s2[i])
    return out / out.sum()


def trifecta_logprob_batch(P: np.ndarray, orders: np.ndarray, lam2: float, lam3: float) -> np.ndarray:
    """P: (n,6) 1着確率, orders: (n,3) 実際の1-2-3着(0始まり艇番)。"""
    n = len(P)
    P = np.clip(P, 1e-9, None)
    P = P / P.sum(1, keepdims=True)
    a, b, c = orders[:, 0], orders[:, 1], orders[:, 2]
    r = np.arange(n)
    s2, s3 = P ** lam2, P ** lam3
    lp = np.log(P[r, a])
    lp += np.log(s2[r, b]) - np.log(s2.sum(1) - s2[r, a])
    lp += np.log(s3[r, c]) - np.log(s3.sum(1) - s3[r, a] - s3[r, b])
    return lp


def fit_discount(P: np.ndarray, orders: np.ndarray) -> tuple[float, float]:
    def nll(x):
        return -trifecta_logprob_batch(P, orders, x[0], x[1]).mean()
    res = minimize(nll, x0=[0.85, 0.75], bounds=[(0.3, 1.5), (0.3, 1.5)], method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])
