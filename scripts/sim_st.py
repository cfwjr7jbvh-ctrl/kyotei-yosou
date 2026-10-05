"""「選手をオブジェクトにして、スタートからレースを組み立てる」予測の試作(改良案 D18)。

考え方: 選手ごとに「展示STからの本番STの分布」を持たせ、本番STを何回も引いて(シミュレーション)、
その隊形(内の艇との差、スリットでの位置)から勝ち筋を決める小さなモデルで1着確率を出し、平均する。
比べるもの:
  (a) 本番STを知っていたら(神のみぞ知る上限): 隊形でどこまで決まるか
  (b) 展示STだけ(いまの直前予想に近い情報)
  (c) 選手の分布からSTを30回引いて平均(選手のオブジェクト化)
評価: 2026-02-26 以降(いまの検証と同じテスト期間)の1着のlogloss。アンサンブルは 1.158。
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, "src")
from kyotei.data import load_history

ent, races, _ = load_history()
ent["race_id"] = ent["race_id"].astype(str)
s = ent[ent["finish"].between(1, 6) & ent["course"].between(1, 6)].copy()
s = s.dropna(subset=["st"])
s = s[s["st_flag"].isna() | (s["st_flag"] == "")] if "st_flag" in s else s
s["win"] = (s["finish"] == 1).astype(int)
s["date"] = pd.to_datetime(s["date"])
s = s.sort_values(["race_id", "course"])
full = s.groupby("race_id")["course"].transform("size") == 6
s = s[full].copy()
TEST = pd.Timestamp("2026-02-26"); TRAIN_END = pd.Timestamp("2025-07-20")

# 選手オブジェクト: 展示ST→本番STの分布(平均のずれと散らばり)を、学習期間だけで作る
tr = s[s["date"] <= TRAIN_END].dropna(subset=["ex_st"])
dlt = (tr["st"] - tr["ex_st"])
obj = tr.assign(d=dlt).groupby("racer_id")["d"].agg(["mean", "std", "size"])
pop_mean, pop_sd = float(dlt.mean()), float(dlt.std())
K = 20
obj["m"] = (obj["mean"] * obj["size"] + pop_mean * K) / (obj["size"] + K)
obj["sd"] = np.sqrt((obj["std"].fillna(pop_sd) ** 2 * obj["size"] + pop_sd ** 2 * K) / (obj["size"] + K))

def formation(df: pd.DataFrame, stcol: str) -> pd.DataFrame:
    """隊形の特徴: ST、内の艇との差、外の艇との差、6艇の中のSTの順位、先頭との差。"""
    g = df.groupby("race_id")[stcol]
    d = pd.DataFrame(index=df.index)
    d["course"] = df["course"].values
    d["st"] = df[stcol].values
    d["rank"] = g.rank(method="min").values
    d["lead_first"] = (df[stcol] - g.transform("min")).values
    inner = df.groupby("race_id")[stcol].shift(1); outer = df.groupby("race_id")[stcol].shift(-1)
    d["vs_in"] = (inner - df[stcol]).fillna(0).values      # 正なら内より速い
    d["vs_out"] = (outer - df[stcol]).fillna(0).values
    d["cls"] = df["racer_class"].map({"A1": 3, "A2": 2, "B1": 1, "B2": 0}).fillna(1).values
    d["nat"] = df["nat_win_rate"].values
    d["motor"] = df["motor_2rate"].values
    return d

def fit_eval(name, stcol_train, stcol_test_fn, n_samp=1, train_fn=None):
    trn, tst = s[s["date"] <= TRAIN_END], s[s["date"] >= TEST]
    if train_fn is not None:   # 学習も同じ作り方のSTで(本番STで学んで予想だけ見込みのSTにすると、ずれる)
        parts = []
        for k in range(min(n_samp, 5)):
            t2 = trn.copy(); t2["_st"] = train_fn(t2, k); parts.append(t2)
        trn = pd.concat(parts); stcol_train = "_st"
    Xtr = formation(trn, stcol_train); ytr = trn["win"].values
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, random_state=0).fit(Xtr, ytr)
    P = np.zeros(len(tst))
    for k in range(n_samp):
        t2 = tst.copy(); t2["_st"] = stcol_test_fn(t2, k)
        p = m.predict_proba(formation(t2, "_st"))[:, 1]
        P += p
    P /= n_samp
    tst = tst.assign(p=P)
    tst["p"] = tst["p"] / tst.groupby("race_id")["p"].transform("sum")
    ll = -np.log(np.clip(tst.loc[tst["win"] == 1, "p"], 1e-6, 1)).mean()
    hit = (tst.loc[tst.groupby("race_id")["p"].idxmax(), "win"]).mean()
    print(f"{name}: 1着logloss {ll:.3f} / 1着的中 {hit:.1%} ({tst['race_id'].nunique()}レース)")

rng = np.random.default_rng(0)
fit_eval("(a) 本番STを知っていたら", "st", lambda t, k: t["st"].values)
fit_eval("(b) 展示STをそのまま", "ex_st", lambda t, k: t["ex_st"].fillna(t["ex_st"].mean()).values)
def sampled(t, k):
    m = t["racer_id"].map(obj["m"]).fillna(pop_mean).values
    sd = t["racer_id"].map(obj["sd"]).fillna(pop_sd).values
    return t["ex_st"].fillna(t["ex_st"].mean()).values + m + rng.normal(0, 1, len(t)) * sd
fit_eval("(c) 選手の分布からST 30回(学習も引いたSTで)", "st", sampled, n_samp=30, train_fn=sampled)
def expected(t, k):
    return t["ex_st"].fillna(t["ex_st"].mean()).values + t["racer_id"].map(obj["m"]).fillna(pop_mean).values
fit_eval("(d) 選手ごとの見込みST(平均だけ、学習も同じ)", "st", expected, train_fn=expected)
