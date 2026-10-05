"""複数のアプローチの予想モデル。

どのモデルも predict_proba(df) で「各艇の1着確率(レース内で合計1)」を返す。
アプローチが違うモデルは間違え方も違うので、後でアンサンブルすると精度が上がる。

- GBDTWin       : 勾配ブースティング木で「1着になるか」を学習(非線形・交互作用に強い)
- GBDTPlace     : 同じく「3着以内に入るか」を学習(1着の情報だけより学習データが3倍)
- RankModel     : LightGBMのランキング学習(着順そのものを学習、lightgbmがある場合のみ)
- PLLogit       : 条件付きロジット/Plackett-Luce(線形・解釈しやすく過学習しにくい)
- RatingModel   : オンラインレーティング(枠効果+選手の強さ)だけを使う単純モデル
- RaceLevel     : レースを1つの標本にして6艇ぶんの特徴量を横に並べ、「どの枠が勝つか」を6クラスで直接学ぶ
                  (艇ごとのモデルでは拾いにくい「相手との組み合わせ」を見る。手元の試しで1着の誤差 1.212→1.178)
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

    n_seeds = 3  # 乱数を変えて3回学習し平均(結果のブレを抑える)

    def fit(self, df):
        y = (df["finish"] <= self.target).astype(int)
        w = recency_weight(df)
        self.ms = [_gbdt_classifier(self.seed + k).fit(df[self.feats], y, sample_weight=w)
                   for k in range(self.n_seeds)]
        self.m = self.ms[0]
        return self

    def raw(self, df):
        return np.mean([m.predict_proba(df[self.feats])[:, 1] for m in self.ms], axis=0)

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


RACE_LEVEL_PRIORITY = ["st_pred2", "st_pred", "rating", "rc_win", "nat_win_rate", "motor_2rate", "exhibit_time", "course", "class_num",
                       "rl_win", "course_win_hist", "mtx_top2", "nige_rate", "makuri_rate", "sashi_rate", "ex_st", "rc_avgst", "wind_x",
                       "mt_top2", "rc_top3", "winrate_growth_180", "tilt", "weight", "loc_win_rate", "boat_2rate", "rating_growth_180",
                       "makurizashi_rate", "course_st_hist", "st_bias", "wind", "wave", "lane"]


class RaceLevel:
    """レース単位の6クラスモデル。各艇の特徴量を枠順に横へ並べ、勝った枠を直接学ぶ。

    手元の試し(1着logloss): 特徴量を上位12個→1.179、24個→1.176、48個→1.170、72個→1.166、全部(約150個)→1.162 と、
    多いほど良かったので全部使う(k=None)。進入コース順に並べるのは枠順より悪かった(枠の情報が落ちる)。
    """
    name = "race_level"
    k = None  # None=全部。数を絞るときは優先順(RACE_LEVEL_PRIORITY)の上位から

    def __init__(self, feats, seed=0):
        pri = [c for c in RACE_LEVEL_PRIORITY if c in feats]
        self.feats = (pri + [c for c in feats if c not in pri])[: self.k]
        self.seed = seed

    def _wide(self, df):
        X, mask, fin, uniq, idx, ridx, pos = _race_tensor(df, self.feats)
        W = np.concatenate([X.reshape(len(X), -1), mask.astype(float)], axis=1)
        if getattr(self, "keep", None) is not None:  # 学習時に全部欠損だった列は落とす(sklearn の binning が落ちる)
            W = W[:, self.keep]
        return W, mask, fin, uniq, idx, ridx, pos

    def fit(self, df):
        self.keep = None
        W, mask, fin, *_ = self._wide(df)
        self.keep = ~np.all(np.isnan(W), axis=0)
        W = W[:, self.keep]
        f = np.nan_to_num(fin, nan=99)
        ok = (f.min(1) == 1)
        y = np.argmin(f[ok], axis=1)
        if lgb is not None:
            self.m = lgb.LGBMClassifier(objective="multiclass", n_estimators=400, learning_rate=0.04, num_leaves=31,
                                        min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.5,
                                        reg_lambda=1.0, random_state=self.seed, verbose=-1)
        else:
            self.m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                                    min_samples_leaf=50, l2_regularization=1.0, random_state=self.seed)
        self.m.fit(W[ok], y)
        return self

    def predict_proba(self, df):
        W, mask, fin, uniq, idx, ridx, pos = self._wide(df)
        P = np.full((len(W), 6), 1e-6)
        P[:, self.m.classes_] = self.m.predict_proba(W)
        P = np.where(mask, P, 1e-6)
        P /= P.sum(1, keepdims=True)
        out = pd.Series(P[ridx, pos], index=idx).reindex(df.index).values
        return race_normalize(out, df["race_id"].values)


class RaceCond:
    """2着・3着の条件付きレース単位モデル(D21)。

    6艇の特徴量を横に並べたものに「1着の枠」(3着は「1着・2着の枠」)の one-hot を足し、2着(3着)の枠を6クラスで学ぶ。
    cond(df) は各レースについて log P(2着=j | 1着=i) の 6x6 と log P(3着=k | 1着=i, 2着=j) の 6x6x6 を返す。
    スタッカー(ensemble.Stacker)が2着・3着の条件付きロジットの特徴量としてこれを足し、重みを学ぶ。
    手元の試し: 本当の1着を知ったときの2着の誤差 1.423(1着確率を除いて正規化)→1.360。
    """
    name = "race_cond"

    def __init__(self, feats, seed=0):
        self.rl = RaceLevel(feats, seed)
        self.seed = seed

    def _clf(self):
        if lgb is not None:
            return lgb.LGBMClassifier(objective="multiclass", n_estimators=300, learning_rate=0.05, num_leaves=31,
                                      min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.5,
                                      reg_lambda=1.0, random_state=self.seed, verbose=-1)
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                              min_samples_leaf=50, l2_regularization=1.0, random_state=self.seed)

    @staticmethod
    def _oh(idx, n):
        E = np.zeros((n, 6))
        E[np.arange(n), idx] = 1.0
        return E

    def fit(self, df):
        self.rl.keep = None
        W, mask, fin, *_ = self.rl._wide(df)
        self.rl.keep = ~np.all(np.isnan(W), axis=0)
        W = W[:, self.rl.keep]
        f = np.nan_to_num(fin, nan=99)
        o = np.argsort(f, axis=1)[:, :3]
        n = len(W)
        ok2 = (f <= 2).sum(1) == 2
        X2 = np.concatenate([W, self._oh(o[:, 0], n)], axis=1)
        self.m2 = self._clf().fit(X2[ok2], o[ok2, 1])
        ok3 = (f <= 3).sum(1) == 3
        X3 = np.concatenate([W, self._oh(o[:, 0], n), self._oh(o[:, 1], n)], axis=1)
        self.m3 = self._clf().fit(X3[ok3], o[ok3, 2])
        return self

    def _probs(self, m, X, mask, drop):
        P = np.full((len(X), 6), 1e-9)
        P[:, m.classes_] = m.predict_proba(X)
        P = np.where(mask, P, 1e-9)
        for d in drop:
            P[np.arange(len(X)), d] = 1e-9
        return np.log(P / P.sum(1, keepdims=True))

    def cond(self, df):
        """(race_id の配列, L2 (n,6,6), L3 (n,6,6,6))。L2[r, i, j] = log P(2着=j | 1着=i)、L3[r, i, j, k] = log P(3着=k | 1着=i, 2着=j)。"""
        W, mask, fin, uniq, *_ = self.rl._wide(df)
        n = len(W)
        L2 = np.zeros((n, 6, 6))
        L3 = np.zeros((n, 6, 6, 6))
        for i in range(6):
            oi = self._oh(np.full(n, i), n)
            L2[:, i, :] = self._probs(self.m2, np.concatenate([W, oi], axis=1), mask, [np.full(n, i)])
            for j in range(6):
                if j == i:
                    continue
                oj = self._oh(np.full(n, j), n)
                L3[:, i, j, :] = self._probs(self.m3, np.concatenate([W, oi, oj], axis=1), mask, [np.full(n, i), np.full(n, j)])
        return uniq, L2, L3


def available_models():
    ms = [GBDTWin, GBDTPlace, PLLogit, RatingModel, RaceLevel]
    if lgb is not None:
        ms.insert(2, RankModel)
    return ms
