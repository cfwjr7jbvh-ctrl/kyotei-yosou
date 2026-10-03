"""複数のアプローチの予想モデル。

どのモデルも predict_proba(df) で「各艇の1着確率(レース内で合計1)」を返す。
アプローチが違うモデルは間違え方も違うので、後でアンサンブルすると精度が上がる。

- GBDTWin       : 勾配ブースティング木で「1着になるか」を学習(非線形・交互作用に強い)
- GBDTPlace     : 同じく「3着以内に入るか」を学習(1着の情報だけより学習データが3倍)
- RankModel     : LightGBMのランキング学習(着順そのものを学習、lightgbmがある場合のみ)
- PLLogit       : 条件付きロジット/Plackett-Luce(線形・解釈しやすく過学習しにくい)
- RatingModel   : オンラインレーティング(枠効果+選手の強さ)だけを使う単純モデル
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier

try:  # GitHub Actions では lightgbm を使う。無ければ sklearn にフォールバック
    import lightgbm as lgb
except Exception:  # noqa: BLE001
    lgb = None


def race_softmax(scores: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    s = pd.Series(scores)
    m = s.groupby(race_ids).transform("max")
    e = np.exp(s - m)
    return (e / e.groupby(race_ids).transform("sum")).values


def race_normalize(p: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    s = pd.Series(np.clip(p, 1e-6, None))
    return (s / s.groupby(race_ids).transform("sum")).values


def recency_weight(df, half_life_days: float = 365.0):
    """新しいレースほど重く学習する(1年で重み半分)。"""
    d = pd.to_datetime(df["date"])
    age = (d.max() - d).dt.days.values
    return 0.5 ** (age / half_life_days)


def _gbdt_classifier(seed: int):
    if lgb is not None:
        return lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31,
                                  min_child_samples=50, subsample=0.8, subsample_freq=1,
                                  colsample_bytree=0.8, reg_lambda=1.0, random_state=seed,
                                  verbose=-1)
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                          min_samples_leaf=50, l2_regularization=1.0,
                                          random_state=seed)


class GBDTWin:
    name = "gbdt_win"
    target = 1

    def __init__(self, feats, seed=0):
        self.feats, self.seed = feats, seed

    def fit(self, df):
        y = (df["finish"] <= self.target).astype(int)
        self.m = _gbdt_classifier(self.seed).fit(df[self.feats], y, sample_weight=recency_weight(df))
        return self

    def raw(self, df):
        return self.m.predict_proba(df[self.feats])[:, 1]

    def predict_proba(self, df):
        p = self.raw(df)
        if self.target == 1:
            return race_normalize(p, df["race_id"].values)
        # 3着内確率 → 1着確率へ: 強さ ≈ logit(p) とみなしてsoftmax
        return race_softmax(np.log(p / (1 - p + 1e-9) + 1e-9), df["race_id"].values)


class GBDTPlace(GBDTWin):
    name = "gbdt_place"
    target = 3


class RankModel:
    name = "rank"

    def __init__(self, feats, seed=0):
        self.feats, self.seed = feats, seed

    def fit(self, df):
        df = df.sort_values(["race_id", "lane"])
        rel = (7 - df["finish"].fillna(7)).clip(0, 6).astype(int)
        rel = rel.map({6: 10, 5: 5, 4: 3, 3: 2, 2: 1, 1: 0, 0: 0})
        group = df.groupby("race_id", sort=False).size().values
        self.m = lgb.LGBMRanker(n_estimators=500, learning_rate=0.03, num_leaves=31,
                                min_child_samples=50, subsample=0.8, subsample_freq=1,
                                colsample_bytree=0.8, random_state=self.seed, verbose=-1,
                                label_gain=list(range(11)))
        self.m.fit(df[self.feats], rel, group=group)
        self.temp = 1.0
        return self

    def predict_proba(self, df):
        return race_softmax(self.m.predict(df[self.feats]) * self.temp, df["race_id"].values)


def _race_tensor(df: pd.DataFrame, feats: list[str]):
    df = df.sort_values(["race_id", "lane"])
    races = df["race_id"].values
    uniq, start = np.unique(races, return_index=True)
    n, d = len(uniq), len(feats)
    X = np.zeros((n, 6, d))
    mask = np.zeros((n, 6), bool)
    fin = np.full((n, 6), np.nan)
    pos = df["lane"].values - 1
    ridx = np.searchsorted(uniq, races)
    X[ridx, pos] = df[feats].values
    mask[ridx, pos] = True
    if "finish" in df:
        fin[ridx, pos] = df["finish"].values
    return X, mask, fin, uniq, df.index.values, ridx, pos


class PLLogit:
    """Plackett-Luce(上位3着の順序)の線形モデルを最尤推定する。"""
    name = "pl_logit"

    def __init__(self, feats, l2=1e-3, top=3):
        self.feats, self.l2, self.top = feats, l2, top

    def _prep(self, df):
        Z = df[self.feats].astype(float)
        return ((Z - self.mu) / self.sd).fillna(0.0)

    def fit(self, df):
        self.mu = df[self.feats].astype(float).mean()
        self.sd = df[self.feats].astype(float).std().replace(0, 1).fillna(1)
        zc = [f"_z{i}" for i in range(len(self.feats))]
        d2 = pd.DataFrame(self._prep(df).values, columns=zc, index=df.index)
        d2[["race_id", "lane", "finish"]] = df[["race_id", "lane", "finish"]]
        X, mask, fin, *_ = _race_tensor(d2, zc)
        valid = (np.nan_to_num(fin, nan=99) <= 3).sum(1) >= self.top
        X, mask, fin = X[valid], mask[valid], fin[valid]
        orders = np.argsort(np.nan_to_num(fin, nan=99), axis=1)[:, :self.top]
        rr = np.arange(len(X))

        def f(w):
            u = X @ w
            avail = mask.copy()
            ll, g = 0.0, np.zeros_like(w)
            for t in range(self.top):
                uu = np.where(avail, u, -np.inf)
                m = uu.max(1, keepdims=True)
                e = np.where(avail, np.exp(uu - m), 0)
                Zs = e.sum(1)
                ch = orders[:, t]
                ll += (u[rr, ch] - m[:, 0] - np.log(Zs)).sum()
                p = e / Zs[:, None]
                g += X[rr, ch].sum(0) - np.einsum("ij,ijk->k", p, X)
                avail[rr, ch] = False
            n = len(X)
            return -ll / n + self.l2 * w @ w, -g / n + 2 * self.l2 * w

        res = minimize(f, np.zeros(len(self.feats)), jac=True, method="L-BFGS-B")
        self.w = res.x
        return self

    def predict_proba(self, df):
        u = self._prep(df).values @ self.w
        return race_softmax(u, df["race_id"].values)


class RatingModel:
    name = "rating"

    def __init__(self, *_a, **_k):
        pass

    def fit(self, df):
        return self

    def predict_proba(self, df):
        return race_softmax(df["rating_strength"].values, df["race_id"].values)


def available_models():
    ms = [GBDTWin, GBDTPlace, PLLogit, RatingModel]
    if lgb is not None:
        ms.insert(2, RankModel)
    return ms
