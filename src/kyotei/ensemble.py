"""アンサンブル(スタッキング)と評価。

各モデルの log(1着確率) を説明変数にした Plackett-Luce で重みを学習し、
最終的な1着確率を作る。そこから Benter 補正つきで3連単確率を出す。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import PLLogit, race_softmax
from .plackett import PERMS3, fit_discount, pl_trifecta_matrix, trifecta_logprob_batch


class Stacker:
    def fit(self, df: pd.DataFrame, probs: dict[str, np.ndarray]):
        self.names = list(probs)
        d = df[["race_id", "lane", "finish"]].copy()
        for k, p in probs.items():
            d[f"lp_{k}"] = np.log(np.clip(p, 1e-6, 1))
        self.pl = PLLogit([f"lp_{k}" for k in self.names], l2=1e-4).fit(d)
        P, orders = race_matrix(d.assign(p=self.predict(d, probs)))
        self.lam2, self.lam3 = fit_discount(P, orders)
        return self

    def predict(self, df, probs):
        d = df[["race_id", "lane"]].copy()
        for k in self.names:
            d[f"lp_{k}"] = np.log(np.clip(probs[k], 1e-6, 1))
        return self.pl.predict_proba(d)

    def weights(self):
        return dict(zip(self.names, np.round(self.pl.w / self.pl.sd.values, 3)))


def race_matrix(d: pd.DataFrame, col: str = "p"):
    """(n,6) 1着確率行列と、実際の1-2-3着(0始まり)を返す。"""
    d = d.sort_values(["race_id", "lane"])
    P = d.pivot(index="race_id", columns="lane", values=col).reindex(columns=range(1, 7)).fillna(1e-6)
    if "finish" not in d:
        return P.values, None
    F = d.pivot(index="race_id", columns="lane", values="finish").reindex(columns=range(1, 7))
    F = F.loc[P.index]
    orders = np.argsort(F.fillna(99).values, axis=1)[:, :3]
    ok = (F.fillna(99).values <= 3).sum(1) == 3
    return P.values[ok], orders[ok]


def evaluate(d: pd.DataFrame, races: pd.DataFrame, col: str, lam2=1.0, lam3=1.0) -> dict:
    """的中率・対数損失・回収率(払戻金から計算できる戦略)をまとめて出す。"""
    d = d.sort_values(["race_id", "lane"])
    P = d.pivot(index="race_id", columns="lane", values=col).reindex(columns=range(1, 7)).fillna(1e-6)
    F = d.pivot(index="race_id", columns="lane", values="finish").reindex(columns=range(1, 7)).loc[P.index]
    ok = (F.fillna(99).values <= 3).sum(1) == 3
    P, F = P[ok], F[ok]
    rid = P.index.values
    Pv = P.values / P.values.sum(1, keepdims=True)
    orders = np.argsort(F.fillna(99).values, axis=1)[:, :3]
    n = len(Pv)
    r = np.arange(n)
    res = {"races": int(n)}
    res["win_logloss"] = float(-np.log(Pv[r, orders[:, 0]]).mean())
    res["win_hit"] = float((Pv.argmax(1) == orders[:, 0]).mean())
    res["tri_logloss"] = float(-trifecta_logprob_batch(Pv, orders, lam2, lam3).mean())

    rc = races.set_index("race_id").reindex(rid)
    tri_pay = rc["tri_pay"].values.astype(float)
    win_pay = rc["win_pay"].values.astype(float)
    hit1 = hit5 = 0
    pay1 = pay5 = 0.0
    tri_probs_top = np.zeros(n)
    for i in range(n):
        T = pl_trifecta_matrix(Pv[i], lam2, lam3)
        flat = T[PERMS3[:, 0], PERMS3[:, 1], PERMS3[:, 2]]
        top = np.argsort(-flat)[:5]
        a, b, c = orders[i]
        tri_probs_top[i] = flat[top[0]]
        for rank, t in enumerate(top):
            if tuple(PERMS3[t]) == (a, b, c):
                pay5 += tri_pay[i]
                hit5 += 1
                if rank == 0:
                    pay1 += tri_pay[i]
                    hit1 += 1
    res["tri_hit_top1"] = hit1 / n
    res["tri_hit_top5"] = hit5 / n
    res["roi_tri_top1"] = pay1 / (100 * n)
    res["roi_tri_top5"] = pay5 / (500 * n)
    win_hit = Pv.argmax(1) == orders[:, 0]
    res["roi_win_top1"] = float((win_pay * win_hit).sum() / (100 * n))
    # 自信のあるレースだけ買う(本命の確率が上位20%のレース)
    conf = tri_probs_top >= np.quantile(tri_probs_top, 0.8)
    if conf.sum():
        hits = np.zeros(n, bool)
        for i in np.where(conf)[0]:
            T = pl_trifecta_matrix(Pv[i], lam2, lam3)
            hits[i] = np.unravel_index(T.argmax(), T.shape) == tuple(orders[i])
        res["roi_tri_top1_confident"] = float((tri_pay * hits)[conf].sum() / (100 * conf.sum()))
        res["tri_hit_top1_confident"] = float(hits[conf].mean())
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}
