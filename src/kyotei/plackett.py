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


def pl_trifecta_matrix(p_win, lam2: float = 1.0, lam3: float = 1.0, s2=None, s3=None, bonus=None, extra=None) -> np.ndarray:
    """6x6x6の3連単確率(同一艇を含む組は0)。

    s2, s3 を渡すと、2着・3着の強さとして p**lam の代わりに使う(着順ごとに重みを変えたアンサンブル用)。
    bonus=(b2, b3a, b3b) を渡すと、2着の強さに b2[1着の枠, 自分の枠]、3着の強さに
    b3a[1着の枠, 自分の枠] + b3b[2着の枠, 自分の枠] を(対数で)足す(1着艇との位置関係で2・3着が変わる分)。
    extra=(E2 (6,6), E3 (6,6,6)) は、このレースだけの追加項(条件付きモデルの log 確率×重み。Stacker.cond_extra)。
    """
    p = _norm(p_win)
    s2 = p ** lam2 if s2 is None else _norm(s2)
    s3 = p ** lam3 if s3 is None else _norm(s3)
    i, j, k = PERMS3[:, 0], PERMS3[:, 1], PERMS3[:, 2]
    out = np.zeros((6, 6, 6))
    if bonus is None and extra is None:
        out[i, j, k] = p[i] * s2[j] / (s2.sum() - s2[i]) * s3[k] / (s3.sum() - s3[i] - s3[j])
        return out / out.sum()
    b2, b3a, b3b = bonus if bonus is not None else (np.zeros((6, 6)), np.zeros((6, 6)), np.zeros((6, 6)))
    e2, e3 = extra if extra is not None else (0.0, 0.0)
    S2 = s2[None, :] * np.exp(b2 + e2)                              # S2[i, j]
    S2[np.arange(6), np.arange(6)] = 0.0
    S3 = s3[None, None, :] * np.exp(b3a[:, None, :] + b3b[None, :, :] + e3)  # S3[i, j, k]
    a6 = np.arange(6)
    S3[a6[:, None], a6[None, :], a6[:, None]] = 0.0  # k == i
    S3[a6[:, None], a6[None, :], a6[None, :]] = 0.0  # k == j
    den2, den3 = S2.sum(1), S3.sum(2)  # 残った艇の強さの合計
    out[i, j, k] = p[i] * S2[i, j] / den2[i] * S3[i, j, k] / den3[i, j]
    return out / out.sum()


def pl_exacta_matrix(p_win, lam2: float = 1.0) -> np.ndarray:
    p = _norm(p_win)
    s2 = p ** lam2
    i, j = PERMS2[:, 0], PERMS2[:, 1]
    out = np.zeros((6, 6))
    out[i, j] = p[i] * s2[j] / (s2.sum() - s2[i])
    return out / out.sum()


def trifecta_logprob_batch(P: np.ndarray, orders: np.ndarray, lam2: float, lam3: float,
                           S2: np.ndarray | None = None, S3: np.ndarray | None = None, bonus=None, extra=None) -> np.ndarray:
    """P: (n,6) 1着確率, orders: (n,3) 実際の1-2-3着(0始まり艇番)。S2, S3: 2着・3着の強さ(省略時 P**lam)。
    extra=(E2 (n,6,6), E3 (n,6,6,6)): レースごとの追加項(pl_trifecta_matrix と同じ)。"""
    n = len(P)
    P = np.clip(P, 1e-9, None)
    P = P / P.sum(1, keepdims=True)
    a, b, c = orders[:, 0], orders[:, 1], orders[:, 2]
    r = np.arange(n)
    s2 = P ** lam2 if S2 is None else np.clip(S2, 1e-12, None)
    s3 = P ** lam3 if S3 is None else np.clip(S3, 1e-12, None)
    lp = np.log(P[r, a])
    if bonus is None and extra is None:
        lp += np.log(s2[r, b]) - np.log(s2.sum(1) - s2[r, a])
        lp += np.log(s3[r, c]) - np.log(s3.sum(1) - s3[r, a] - s3[r, b])
        return lp
    b2, b3a, b3b = bonus if bonus is not None else (np.zeros((6, 6)), np.zeros((6, 6)), np.zeros((6, 6)))
    L2 = np.log(s2) + b2[a]
    L3 = np.log(s3) + b3a[a] + b3b[b]
    if extra is not None:
        E2, E3 = extra
        L2 = L2 + E2[r, a]
        L3 = L3 + E3[r, a, b]
    L2[r, a] = -np.inf
    L3[r, a] = -np.inf
    L3[r, b] = -np.inf
    lp += L2[r, b] - _lse(L2)
    lp += L3[r, c] - _lse(L3)
    return lp


def _lse(x: np.ndarray) -> np.ndarray:
    m = x.max(1, keepdims=True)
    return m[:, 0] + np.log(np.exp(x - m).sum(1))


def fit_discount(P: np.ndarray, orders: np.ndarray) -> tuple[float, float]:
    def nll(x):
        return -trifecta_logprob_batch(P, orders, x[0], x[1]).mean()
    res = minimize(nll, x0=[0.85, 0.75], bounds=[(0.3, 1.5), (0.3, 1.5)], method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])
