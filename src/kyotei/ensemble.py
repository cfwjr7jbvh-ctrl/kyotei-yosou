"""アンサンブル(スタッキング)と評価。

各モデルの log(1着確率) を説明変数にした多項ロジットで、1着の当たり方に合うよう重みを学習し、
最終的な1着確率を作る。2着・3着は、それぞれ別の重みで「残った艇の中から誰が来るか」を学習する
(1着は単勝モデル、2・3着は3着内モデルが効くなど、着順で頼りになるモデルが違うため)。
さらに2・3着には「1着艇(2着艇)の枠×自分の枠」のボーナスを足す(4号艇がまくると5号艇が続く、など)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .models import PLLogit, _race_tensor, race_softmax
from .plackett import PERMS3, fit_discount, pl_trifecta_matrix, trifecta_logprob_batch


def align_extra(extra, race_ids):
    """(ids, E2, E3) を race_ids の順に並べ替える(無いレースは0=影響なし)。None はそのまま。"""
    if extra is None:
        return None
    ids, E2, E3 = extra
    pos = pd.Series(np.arange(len(ids)), index=ids).reindex(race_ids)
    ok = pos.notna().values
    idx = pos.fillna(0).astype(int).values
    A2 = np.where(ok[:, None, None], E2[idx], 0.0)
    A3 = np.where(ok[:, None, None, None], E3[idx], 0.0)
    return A2, A3


class Stacker:
    def fit(self, df: pd.DataFrame, probs: dict[str, np.ndarray], cond=None):
        """cond=(race_id の配列, L2, L3): 2着・3着の条件付きモデル(models.RaceCond.cond)。あれば重みを学ぶ。"""
        self.names = list(probs)
        d = df[["race_id", "lane", "finish"]].copy()
        for k, p in probs.items():
            d[f"lp_{k}"] = np.log(np.clip(p, 1e-6, 1))
        # 重みは「1着の当たり方」だけで決める。1〜3着まとめて決めると、荒れやすい2・3着に
        # 引っ張られて1着確率まで平らになる(実データで1号艇を約11ポイント過小評価していた)。
        # 2・3着の平らさは、このあと fit_discount の補正(lam2, lam3)で別に合わせる。
        self.pl = PLLogit([f"lp_{k}" for k in self.names], l2=1e-4, top=1).fit(d)
        P, orders = race_matrix(d.assign(p=self.predict(d, probs)))
        self.lam2, self.lam3 = fit_discount(P, orders)  # 古い形式(p**lam)用。今は下の w2, w3 を使う
        # 2着: 1着艇を除いた中から、3着: 1・2着艇を除いた中から選ばれる確率の重み
        zc = [f"_z{i}" for i in range(len(self.names))]
        z = pd.DataFrame(self.pl._prep(d).values, columns=zc, index=d.index)
        z[["race_id", "lane", "finish"]] = d[["race_id", "lane", "finish"]]
        X, mask, fin, uniq, *_ = _race_tensor(z, zc)
        ok = (np.nan_to_num(fin, nan=99) <= 3).sum(1) == 3
        X, mask, fin = X[ok], mask[ok], fin[ok]
        o = np.argsort(np.nan_to_num(fin, nan=99), axis=1)[:, :3]
        r = np.arange(len(X))
        k = X.shape[2]
        C2 = C3 = None
        if cond is not None:  # 条件付きモデルの log P(2着=j | 1着) と log P(3着=k | 1着, 2着) を特徴量に
            A2, A3 = align_extra(cond, uniq[ok])
            C2 = A2[r, o[:, 0]][:, :, None]
            C3 = A3[r, o[:, 0], o[:, 1]][:, :, None]
        # 1着艇(2着艇)との位置関係のボーナス: 「1着の枠×自分の枠」ごとの一定値(例: 4号艇がまくると5号艇が続きやすい)
        lanes = np.arange(6)[None, :]
        E1 = np.zeros((len(X), 6, 36))
        E1[r[:, None], lanes, 6 * o[:, [0]] + lanes] = 1.0
        E2 = np.zeros((len(X), 6, 36))
        E2[r[:, None], lanes, 6 * o[:, [1]] + lanes] = 1.0
        pen2 = np.r_[np.full(k, 1e-4), np.full(36, 1e-3)]
        pen3 = np.r_[np.full(k, 1e-4), np.full(72, 1e-3)]
        avail = mask.copy()
        avail[r, o[:, 0]] = False
        parts2 = [X, E1] + ([C2] if C2 is not None else [])
        th2 = _fit_conditional(np.concatenate(parts2, 2), avail, o[:, 1], np.r_[pen2, [1e-4] * (C2 is not None)])
        avail[r, o[:, 1]] = False
        parts3 = [X, E1, E2] + ([C3] if C3 is not None else [])
        th3 = _fit_conditional(np.concatenate(parts3, 2), avail, o[:, 2], np.r_[pen3, [1e-4] * (C3 is not None)])
        self.w2, self.b2 = th2[:k], th2[k:k + 36].reshape(6, 6)
        self.w3, self.b3a, self.b3b = th3[:k], th3[k:k + 36].reshape(6, 6), th3[k + 36:k + 72].reshape(6, 6)
        self.wc2 = float(th2[k + 36]) if C2 is not None else None
        self.wc3 = float(th3[k + 72]) if C3 is not None else None
        return self

    def cond_extra(self, cond):
        """条件付きモデルの出力に学んだ重みをかけ、3連単確率の追加項 (ids, E2, E3) にする。重みが無ければ None。"""
        if cond is None or getattr(self, "wc2", None) is None:
            return None
        ids, L2, L3 = cond
        return ids, L2 * self.wc2, L3 * self.wc3

    @property
    def bonus(self):
        """3連単確率に渡す (b2, b3a, b3b)。古いモデルでは None。"""
        if getattr(self, "b2", None) is None:
            return None
        return self.b2, self.b3a, self.b3b

    def predict(self, df, probs):
        d = df[["race_id", "lane"]].copy()
        for k in self.names:
            d[f"lp_{k}"] = np.log(np.clip(probs[k], 1e-6, 1))
        return self.pl.predict_proba(d)

    def strengths(self, df, probs):
        """2着・3着の強さ(レース内で合計1)。w2 が無い古いモデルでは Benter 補正(p**lam)と同じ。"""
        p = self.predict(df, probs)
        if getattr(self, "w2", None) is None:
            rid = df["race_id"].values
            return (race_softmax(self.lam2 * np.log(np.clip(p, 1e-9, 1)), rid),
                    race_softmax(self.lam3 * np.log(np.clip(p, 1e-9, 1)), rid))
        d = df[["race_id", "lane"]].copy()
        for k in self.names:
            d[f"lp_{k}"] = np.log(np.clip(probs[k], 1e-6, 1))
        Z = self.pl._prep(d).values
        rid = d["race_id"].values
        return race_softmax(Z @ self.w2, rid), race_softmax(Z @ self.w3, rid)

    def weights(self):
        out = dict(zip(self.names, np.round(self.pl.w / self.pl.sd.values, 3)))
        if getattr(self, "w2", None) is not None:
            sd = self.pl.sd.values
            out.update({f"2nd_{k}": v for k, v in zip(self.names, np.round(self.w2 / sd, 3))})
            out.update({f"3rd_{k}": v for k, v in zip(self.names, np.round(self.w3 / sd, 3))})
        if getattr(self, "wc2", None) is not None:
            out["2nd_race_cond"], out["3rd_race_cond"] = round(self.wc2, 3), round(self.wc3, 3)
        return out


def _fit_conditional(X: np.ndarray, avail: np.ndarray, chosen: np.ndarray, l2=1e-4) -> np.ndarray:
    """条件付きロジット: 残っている艇(avail)の中から chosen が選ばれる確率を最大にする重み。l2 は重みごとに指定可。"""
    n, _, k = X.shape
    r = np.arange(n)

    def f(w):
        u = X @ w
        uu = np.where(avail, u, -np.inf)
        m = uu.max(1, keepdims=True)
        e = np.where(avail, np.exp(uu - m), 0.0)
        Z = e.sum(1)
        ll = (u[r, chosen] - m[:, 0] - np.log(Z)).sum()
        p = e / Z[:, None]
        g = X[r, chosen].sum(0) - np.einsum("ij,ijk->k", p, X)
        return -ll / n + (l2 * w * w).sum(), -g / n + 2 * l2 * w

    return minimize(f, np.zeros(k), jac=True, method="L-BFGS-B").x


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


def evaluate(d: pd.DataFrame, races: pd.DataFrame, col: str, lam2=1.0, lam3=1.0, s_cols=None, bonus=None, extra=None) -> dict:
    """的中率・対数損失・回収率(払戻金から計算できる戦略)をまとめて出す。

    s_cols=(列名, 列名) を渡すと、その列を2着・3着の強さとして3連単確率を作る(Stacker.strengths)。
    extra=(ids, E2, E3) は条件付きモデルの追加項(Stacker.cond_extra)。
    """
    d = d.sort_values(["race_id", "lane"])
    P = d.pivot(index="race_id", columns="lane", values=col).reindex(columns=range(1, 7)).fillna(1e-6)
    F = d.pivot(index="race_id", columns="lane", values="finish").reindex(columns=range(1, 7)).loc[P.index]
    ok = (F.fillna(99).values <= 3).sum(1) == 3
    P, F = P[ok], F[ok]
    rid = P.index.values
    Pv = P.values / P.values.sum(1, keepdims=True)
    S2 = S3 = None
    if s_cols:
        S2, S3 = (d.pivot(index="race_id", columns="lane", values=c).reindex(index=P.index, columns=range(1, 7))
                  .fillna(1e-9).values for c in s_cols)
    orders = np.argsort(F.fillna(99).values, axis=1)[:, :3]
    n = len(Pv)
    r = np.arange(n)
    res = {"races": int(n)}
    res["win_logloss"] = float(-np.log(Pv[r, orders[:, 0]]).mean())
    res["win_hit"] = float((Pv.argmax(1) == orders[:, 0]).mean())
    EX = align_extra(extra, rid)
    res["tri_logloss"] = float(-trifecta_logprob_batch(Pv, orders, lam2, lam3, S2, S3, bonus, EX).mean())

    def tri(i):
        return pl_trifecta_matrix(Pv[i], lam2, lam3, None if S2 is None else S2[i], None if S3 is None else S3[i],
                                  bonus, None if EX is None else (EX[0][i], EX[1][i]))

    rc = races.set_index("race_id").reindex(rid)
    tri_pay = rc["tri_pay"].values.astype(float)
    win_pay = rc["win_pay"].values.astype(float)
    hit1 = hit5 = 0
    pay1 = pay5 = 0.0
    tri_probs_top = np.zeros(n)
    for i in range(n):
        T = tri(i)
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
            T = tri(i)
            hits[i] = np.unravel_index(T.argmax(), T.shape) == tuple(orders[i])
        res["roi_tri_top1_confident"] = float((tri_pay * hits)[conf].sum() / (100 * conf.sum()))
        res["tri_hit_top1_confident"] = float(hits[conf].mean())
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}
