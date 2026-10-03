"""モーターの評価を細かくする特徴量(改良案 B1・B2・B3)。

どれも「前日まで」の結果だけで計算するので、朝予想・直前予想のどちらでも使える。

- モーター入れ替えの検出: 場ごとに、番組表のモーター2連率がほぼ全艇 0 になった日を
  「新しいモーターの使い始め」とみなす(実データでは全24場で年1回はっきり出る)。
  それ以前の同じ番号のモーターは別物なので、成績を混ぜない。
- 乗り手の腕を差し引いたモーターの力: 選手の強さ(レーティング)と枠から期待される
  「抜いた艇数」と、実際に抜いた艇数の差。強い選手が乗ると2連率が上がる分を除ける。
- 展示タイムのクセ補正: 展示タイムの「レース平均との差」から、その選手のいつもの差を引く。
- 今節の足: 同じ選手×同じモーターの直近7日(=今の節)の上の2つ。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import _rolling_prior


def _renewals(df: pd.DataFrame) -> pd.DataFrame:
    """(jcd, date) ごとの「モーターの世代」と「使い始めの日」。"""
    z = (df.assign(_z=(df["motor_2rate"].fillna(-1) == 0).astype(float))
         .groupby(["jcd", "date"])["_z"].mean().reset_index().sort_values(["jcd", "date"]))
    new = z["_z"] >= 0.8
    prev_new = new.groupby(z["jcd"]).shift(1, fill_value=False).astype(bool)
    z["_renew"] = new & ~prev_new
    z["_epoch"] = z.groupby("jcd")["_renew"].cumsum()
    z["_renew_date"] = z["date"].where(z["_renew"]).groupby(z["jcd"]).ffill()
    return z[["jcd", "date", "_epoch", "_renew_date"]]


def _beaten_residual(df: pd.DataFrame) -> pd.Series:
    """完走艇どうしで「実際に抜いた艇数 − 強さから期待される抜く艇数」。

    Plackett-Luce では、2艇の前後関係の確率は sigmoid(強さの差) になる。
    強さは add_rating の rating_strength(前日までのレーティング+枠の有利不利)。
    """
    fin = df["finish"] if "finish" in df else pd.Series(np.nan, index=df.index)
    ok = fin.notna() & df["rating_strength"].notna()
    d = df.loc[ok, ["race_id", "lane", "rating_strength"]].assign(fin=fin[ok])
    S = d.pivot(index="race_id", columns="lane", values="rating_strength").reindex(columns=range(1, 7))
    F = d.pivot(index="race_id", columns="lane", values="fin").reindex(columns=range(1, 7))
    s = S.values
    m = ~np.isnan(s)
    diff = s[:, :, None] - s[:, None, :]
    sig = 1.0 / (1.0 + np.exp(-np.nan_to_num(diff)))
    pair = m[:, :, None] & m[:, None, :]
    k = np.arange(s.shape[1])
    pair[:, k, k] = False  # 自分自身は数えない
    expected = (sig * pair).sum(2)
    n_fin = m.sum(1, keepdims=True)
    # 完走艇の中での順位(失格などで着順に抜けがあっても詰める)
    rank_in = pd.DataFrame(F.values).rank(axis=1, method="first").values
    actual = n_fin - rank_in
    R = pd.DataFrame(np.where(m, actual - expected, np.nan), index=S.index, columns=range(1, 7))
    long = R.stack().rename("r").reset_index()
    long.columns = ["race_id", "lane", "r"]
    key = df[["race_id", "lane"]].merge(long, on=["race_id", "lane"], how="left")
    return pd.Series(key["r"].values, index=df.index)


def add_motor(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "motor_2rate" not in df or "rating_strength" not in df:
        return df
    z = _renewals(df)
    df = df.merge(z, on=["jcd", "date"], how="left")
    age = (pd.to_datetime(df["date"]) - pd.to_datetime(df["_renew_date"])).dt.days
    df["motor_age"] = age.astype(float)  # 入れ替えを観測していなければ NaN

    has_res = df["finish"].notna() if "finish" in df else pd.Series(False, index=df.index)
    r = _beaten_residual(df)
    df["_mx_r"] = r.fillna(0)
    df["_mx_hr"] = r.notna().astype(float)
    df["_mx_top2"] = ((df["finish"] <= 2) & has_res).astype(float) if "finish" in df else 0.0
    df["_mx_has"] = has_res.astype(float)
    # 展示タイム: レース平均との差 − その選手のいつもの差(直近180日、前日まで)
    if "exhibit_time" in df:
        ex = pd.to_numeric(df["exhibit_time"], errors="coerce")
        ex = ex.where((ex > 6.0) & (ex < 7.6))  # 明らかな異常値は除く
        rel = ex - ex.groupby(df["race_id"]).transform("mean")
        df["_xr"] = rel.where(has_res).fillna(0)
        df["_xh"] = (rel.notna() & has_res).astype(float)
        rr = _rolling_prior(df, ["racer_id"], {"x": "_xr", "h": "_xh"}, "180D", "xq")
        df = df.merge(rr[["racer_id", "date", "xq_x", "xq_h"]], on=["racer_id", "date"], how="left")
        usual = df["xq_x"].fillna(0) / (df["xq_h"].fillna(0) + 5)
        adj = pd.Series(rel.values - usual.values, index=df.index).where(has_res.values)
        df["_mx_ex"] = adj.fillna(0)
        df["_mx_hex"] = adj.notna().astype(float)
        df = df.drop(columns=["xq_x", "xq_h", "xq_n"], errors="ignore")
    vals = {"r": "_mx_r", "hr": "_mx_hr", "top2": "_mx_top2", "has": "_mx_has"}
    if "_mx_ex" in df:
        vals.update(ex="_mx_ex", hex="_mx_hex")

    # B2・B3: 今のモーター(入れ替え後)の成績、前日まで
    m = _rolling_prior(df, ["jcd", "_epoch", "motor_no"], vals, "400D", "mtx")
    df = df.merge(m, on=["jcd", "_epoch", "motor_no", "date"], how="left")
    df["mtx_n"] = df["mtx_has"].fillna(0)
    df["mtx_top2"] = (df["mtx_top2"].fillna(0) + 10 / 3) / (df["mtx_has"].fillna(0) + 10)
    df["mtx_beat"] = df["mtx_r"].fillna(0) / (df["mtx_hr"].fillna(0) + 15)
    if "mtx_ex" in df:
        df["mtx_ex"] = df["mtx_ex"].fillna(0) / (df["mtx_hex"].fillna(0) + 10)

    # B1: 今節の足(同じ選手×同じモーターの直近7日)、前日まで
    s = _rolling_prior(df, ["jcd", "racer_id", "motor_no"], vals, "7D", "sx")
    df = df.merge(s, on=["jcd", "racer_id", "motor_no", "date"], how="left")
    df["sx_n"] = df["sx_has"].fillna(0)
    df["sx_beat"] = df["sx_r"].fillna(0) / (df["sx_hr"].fillna(0) + 3)
    if "sx_ex" in df:
        df["sx_ex"] = df["sx_ex"].fillna(0) / (df["sx_hex"].fillna(0) + 3)

    # レース内での比較(他の艇よりモーターが良いか)
    g = df.groupby("race_id")
    for c in ("mtx_beat", "mtx_ex", "sx_beat", "sx_ex", "mtx_top2"):
        if c in df:
            df[f"{c}_diff"] = df[c] - g[c].transform("mean")
    drop = [c for c in df.columns if c.startswith(("_mx", "_xr", "_xh")) or c in
            ("_epoch", "_renew_date", "mtx_r", "mtx_hr", "mtx_has", "mtx_hex", "sx_r", "sx_hr",
             "sx_has", "sx_hex", "sx_top2")]
    return df.drop(columns=drop)
