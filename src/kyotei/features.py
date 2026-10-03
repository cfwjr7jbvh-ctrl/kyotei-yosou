"""特徴量の作成。

entries(1行=1艇)に以下を足す。過去成績系はすべて「前日まで」のデータだけで
計算するので、未来の情報が混ざる(リーク)ことはない。

1. 出走表そのもの   : 枠、級別、勝率、2連率、モーター・ボート2連率、体重
2. レース内の相対値 : 勝率やモーターの「同レース平均との差」「順位」
3. 直前情報         : 展示タイムの順位・最速との差(あれば)
4. 過去成績         : 選手の直近半年の1着率・3着内率・平均着順・平均ST、
                      選手×コース別1着率、場×コース別1着率、モーター実績
5. レーティング     : 枠の有利不利を除いた選手の強さ(オンライン更新)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CLASS_NUM = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}

BASE_COLS = ["lane", "class_num", "weight", "nat_win_rate", "nat_2rate", "loc_win_rate",
             "loc_2rate", "motor_2rate", "boat_2rate", "jcd", "rno"]
REL_SRC = ["nat_win_rate", "loc_win_rate", "motor_2rate", "class_num", "boat_2rate"]


def _rolling_prior(df: pd.DataFrame, key: list[str], vals: dict[str, str], window: str,
                   prefix: str) -> pd.DataFrame:
    """key ごとに、前日までの window 期間の合計を求めて (key, date) で返す。"""
    g = df.groupby(key + ["date"], sort=False).agg(**{k: (v, "sum") for k, v in vals.items()},
                                                    n=("race_id", "size")).reset_index()
    g = g.sort_values("date")
    g["date"] = pd.to_datetime(g["date"])
    cols = list(vals) + ["n"]
    out = (g.set_index("date").groupby(key, sort=False)[cols]
           .rolling(window, closed="left").sum().reset_index())
    out = out.rename(columns={c: f"{prefix}_{c}" for c in cols})
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def _asof_stats(df: pd.DataFrame, key: list[str], vals: dict[str, str], window: str,
                query: pd.DataFrame) -> pd.DataFrame:
    """key ごとの「前日までの window 期間の合計」を、query の (key, date) に付ける。

    query 側の key がその日に結果を持たなくても使える(例: 当日の進入コース)。
    """
    src = df.dropna(subset=key)
    g = src.groupby(key + ["date"]).agg(**{k: (v, "sum") for k, v in vals.items()}).reset_index()
    g["date"] = pd.to_datetime(g["date"])
    g = g.sort_values("date")
    cols = list(vals)
    roll = (g.set_index("date").groupby(key)[cols].rolling(window).sum().reset_index())
    roll = roll.sort_values("date")
    q = query[key + ["date"]].copy()
    q["_row"] = np.arange(len(q))
    q["date"] = pd.to_datetime(q["date"])
    q = q.dropna(subset=key).sort_values("date")
    for k in key:
        q[k] = q[k].astype(roll[k].dtype)
    m = pd.merge_asof(q, roll, on="date", by=key, allow_exact_matches=False)
    out = pd.DataFrame(index=np.arange(len(query)), columns=cols, dtype=float)
    out.loc[m["_row"].values, cols] = m[cols].values
    return out


def _smoothed(num, den, prior, strength):
    return (num.fillna(0) + prior * strength) / (den.fillna(0) + strength)


def wind_bin(w):
    return pd.cut(pd.to_numeric(w, errors="coerce"), [-1, 1, 3, 5, 99], labels=False)


def wind_table(df: pd.DataFrame) -> pd.DataFrame:
    """直前予想用: 場×風向き×風の強さ×枠 の直近2年の集計(前日まで)。"""
    d = df[df["finish"].notna() & df["wind_dir"].notna()].copy()
    d = d[pd.to_datetime(d["date"]) >= pd.to_datetime(d["date"]).max() - pd.Timedelta(days=730)]
    d["_wbin"] = wind_bin(d["wind"])
    return (d.assign(w=(d["finish"] == 1).astype(float))
            .groupby(["jcd", "wind_dir", "_wbin", "lane"])["w"].agg(["sum", "count"]).reset_index())


def apply_wind(df: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_wbin"] = wind_bin(df["wind"])
    m = df[["jcd", "wind_dir", "_wbin", "lane"]].merge(table, how="left",
                                                       on=["jcd", "wind_dir", "_wbin", "lane"])
    df["vw_win"] = _smoothed(m["sum"], m["count"], df["vl_win"].values, 30).values
    df.loc[df["wind_dir"].isna(), "vw_win"] = np.nan
    return df.drop(columns=["_wbin"])


def add_history(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    has_res = df["finish"].notna() if "finish" in df else pd.Series(False, index=df.index)
    f = df["finish"].where(has_res)
    df["_win"] = (f == 1).astype(float).where(has_res, 0)
    df["_top2"] = (f <= 2).astype(float).where(has_res, 0)
    df["_top3"] = (f <= 3).astype(float).where(has_res, 0)
    df["_fin"] = f.fillna(0)
    df["_st"] = df["st"].where(has_res & df["st"].notna(), 0) if "st" in df else 0.0
    df["_has"] = has_res.astype(float)
    df["_has_st"] = (has_res & df["st"].notna()).astype(float) if "st" in df else 0.0
    df["_st2"] = df["_st"] ** 2
    # フライング・出遅れ(F/L)。F持ちはスタートを控えるので重要
    fl = pd.Series(False, index=df.index)
    for c in ("st_flag", "result_code"):
        if c in df:
            fl |= df[c].astype(str).str.startswith(("F", "L"))
    df["_fl"] = fl.astype(float)
    # 展示ST→本番STのズレ(選手ごとのクセ)。F は本番STをマイナス扱い
    if "ex_st" in df and "st" in df:
        st_signed = df["st"] * np.where(df.get("st_flag", pd.Series("", index=df.index)).astype(str) == "F", -1, 1)
        dd = (st_signed - df["ex_st"]).where(has_res)
        ok = dd.notna() & (dd.abs() < 0.3)
        df["_sd"] = dd.where(ok, 0)
        df["_sd2"] = (dd ** 2).where(ok, 0)
        df["_sdn"] = ok.astype(float)
    if "exhibit_time" in df:
        df["_exrank"] = df.groupby("race_id")["exhibit_time"].rank().where(has_res, np.nan)
        df["_has_ex"] = df["_exrank"].notna().astype(float)
        df["_exrank"] = df["_exrank"].fillna(0)

    # 選手の直近180日
    r = _rolling_prior(df, ["racer_id"], {"win": "_win", "top3": "_top3", "fin": "_fin",
                                          "st": "_st", "has": "_has", "hst": "_has_st",
                                          "fl": "_fl", "st2": "_st2"}, "180D", "rc")
    df = df.merge(r, on=["racer_id", "date"], how="left")
    df["rc_n"] = df["rc_has"].fillna(0)
    df["rc_win"] = _smoothed(df["rc_win"], df["rc_has"], 1 / 6, 5)
    df["rc_top3"] = _smoothed(df["rc_top3"], df["rc_has"], 0.5, 5)
    df["rc_avgfin"] = _smoothed(df["rc_fin"], df["rc_has"], 3.5, 5)
    df["rc_avgst"] = _smoothed(df["rc_st"], df["rc_hst"], 0.16, 5)
    df["rc_fcount"] = df["rc_fl"].fillna(0)
    # スタートの安定度(STのばらつき。小さいほど安定)
    msq = _smoothed(df["rc_st2"], df["rc_hst"], 0.16 ** 2 + 0.05 ** 2, 5)
    df["rc_stsd"] = np.sqrt(np.maximum(msq - df["rc_avgst"] ** 2, 1e-4))

    # 決まり手の得意度(1年): 1コースからの逃げ率、2コース以遠からの差し・まくり・まくり差し率
    # 前づけ(枠より内のコースを取る)の頻度もここで数える
    crs_h = (df["course"] if "course" in df else df["lane"]).where(has_res)
    df["_c1"] = (crs_h == 1).astype(float)
    df["_cx"] = (crs_h >= 2).astype(float)
    df["_front"] = (crs_h < df["lane"]).astype(float)
    tvals = {"c1": "_c1", "cx": "_cx", "front": "_front", "has": "_has"}
    if "kimarite" in df:
        km = pd.to_numeric(df["kimarite"], errors="coerce").where(has_res & (f == 1))
        for code, name in ((1, "nige"), (2, "sashi"), (3, "makuri"), (4, "makurizashi")):
            df[f"_k{name}"] = (km == code).astype(float)
            tvals[name] = f"_k{name}"
    r = _rolling_prior(df, ["racer_id"], tvals, "365D", "kt")
    df = df.merge(r, on=["racer_id", "date"], how="left")
    df["front_rate"] = _smoothed(df["kt_front"], df["kt_has"], 0.02, 10)
    if "kt_nige" in df:
        df["nige_rate"] = _smoothed(df["kt_nige"], df["kt_c1"], 0.5, 6)
        df["sashi_rate"] = _smoothed(df["kt_sashi"], df["kt_cx"], 0.03, 15)
        df["makuri_rate"] = _smoothed(df["kt_makuri"], df["kt_cx"], 0.03, 15)
        df["makurizashi_rate"] = _smoothed(df["kt_makurizashi"], df["kt_cx"], 0.03, 15)
    df = df.drop(columns=[c for c in df.columns if c.startswith("kt_")])

    # 選手×場(2年): 得意な水面
    r = _rolling_prior(df, ["racer_id", "jcd"], {"win": "_win", "top3": "_top3", "has": "_has"}, "730D", "rv")
    df = df.merge(r, on=["racer_id", "jcd", "date"], how="left")
    df["rv_win"] = _smoothed(df["rv_win"], df["rv_has"], df["rc_win"], 6)
    df["rv_top3"] = _smoothed(df["rv_top3"], df["rv_has"], df["rc_top3"], 6)

    # 荒れた水面(波5cm以上 or 風5m以上)での強さ(2年)
    if "wave" in df and "wind" in df:
        rough = ((pd.to_numeric(df["wave"], errors="coerce") >= 5) |
                 (pd.to_numeric(df["wind"], errors="coerce") >= 5)) & has_res
        df["_rough"] = rough.astype(float)
        df["_rough_top3"] = (rough & (f <= 3)).astype(float)
        r = _rolling_prior(df, ["racer_id"], {"cnt": "_rough", "t3": "_rough_top3"}, "730D", "rw")
        df = df.merge(r[["racer_id", "date", "rw_cnt", "rw_t3"]], on=["racer_id", "date"], how="left")
        df["rough_top3"] = _smoothed(df["rw_t3"], df["rw_cnt"], df["rc_top3"], 8)
        df = df.drop(columns=["rw_cnt", "rw_t3"])

    if "_sd" in df:  # 選手ごとの「展示ST→本番ST」のクセと、展示の信頼度(1年)
        r = _rolling_prior(df, ["racer_id"], {"d": "_sd", "d2": "_sd2", "cnt": "_sdn"}, "365D", "xs")
        df = df.merge(r, on=["racer_id", "date"], how="left")
        df["st_bias"] = _smoothed(df["xs_d"], df["xs_cnt"], 0.0, 8)
        msd = _smoothed(df["xs_d2"], df["xs_cnt"], 0.06 ** 2, 8)
        df["st_sd"] = np.sqrt(np.maximum(msd - df["st_bias"] ** 2, 1e-4))
        df["st_ex_n"] = df["xs_cnt"].fillna(0)
        df = df.drop(columns=["xs_d", "xs_d2", "xs_cnt", "xs_n"], errors="ignore")

    # 選手×実際の進入コース(1年)。直前予想で、展示の進入コースを当てはめて使う
    if "course" in df and df["course"].notna().any():
        df["_crs"] = df["course"].where(has_res)
        for c in range(1, 7):
            q = df[["racer_id", "date"]].assign(_crs=float(c))
            st = _asof_stats(df, ["racer_id", "_crs"], {"w": "_win", "s": "_st", "n": "_has",
                                                        "ns": "_has_st"}, "365D", q)
            prior = {1: .5, 2: .14, 3: .12, 4: .11, 5: .06, 6: .04}[c]
            df[f"rcc_win_{c}"] = _smoothed(st["w"], st["n"], prior, 4).values
            df[f"rcc_st_{c}"] = _smoothed(st["s"], st["ns"], 0.16, 4).values

    # 選手×枠(1年)
    r = _rolling_prior(df, ["racer_id", "lane"], {"win": "_win", "top3": "_top3", "has": "_has"},
                       "365D", "rl")
    df = df.merge(r, on=["racer_id", "lane", "date"], how="left")
    lane_prior = df["lane"].map({1: .5, 2: .14, 3: .12, 4: .11, 5: .06, 6: .04})
    df["rl_win"] = _smoothed(df["rl_win"], df["rl_has"], lane_prior, 4)
    df["rl_top3"] = _smoothed(df["rl_top3"], df["rl_has"], 0.5, 4)

    # 場×枠(2年)
    r = _rolling_prior(df, ["jcd", "lane"], {"win": "_win", "has": "_has"}, "730D", "vl")
    df = df.merge(r, on=["jcd", "lane", "date"], how="left")
    df["vl_win"] = _smoothed(df["vl_win"], df["vl_has"], lane_prior, 50)

    # 場×風向き×風の強さ×枠(2年)。水面の向きは場ごとに違うので、
    # 「この場でこの風だと何号艇が勝ちやすいか」をデータから学ぶ(向かい風・追い風の代わり)
    if "wind_dir" in df and "wind" in df:
        df["_wbin"] = wind_bin(df["wind"])
        st = _asof_stats(df.assign(_wd=df["wind_dir"].where(has_res)),
                         ["jcd", "_wd", "_wbin", "lane"], {"w": "_win", "n": "_has"}, "730D",
                         df.assign(_wd=df["wind_dir"]))
        df["vw_win"] = _smoothed(st["w"], st["n"], df["vl_win"], 30).values
        df.loc[df["wind_dir"].isna(), "vw_win"] = np.nan

    # モーター(場×番号、直近120日。モーターは年1回程度で入れ替わる)
    mvals = {"top2": "_top2", "has": "_has"}
    if "_exrank" in df:
        mvals.update(exr="_exrank", hex="_has_ex")
    r = _rolling_prior(df, ["jcd", "motor_no"], mvals, "120D", "mt")
    df = df.merge(r, on=["jcd", "motor_no", "date"], how="left")
    df["mt_top2"] = _smoothed(df["mt_top2"], df["mt_has"], 1 / 3, 10)
    if "mt_exr" in df:  # モーターの展示タイム順位の平均(小さいほど伸び・出足が良い)
        df["mt_exrank"] = _smoothed(df["mt_exr"], df["mt_hex"], 3.5, 10)

    drop = [c for c in df.columns if c.startswith("_") or c in
            ("rc_fin", "rc_st", "rc_has", "rc_hst", "rc_fl", "rc_st2", "rl_has", "vl_has", "mt_has",
             "mt_exr", "mt_hex", "rc_n_x", "rv_has", "rv_n")]
    return df.drop(columns=drop)


class OnlineRating:
    """枠の有利不利を同時に学習するPlackett-Luce型レーティング(Elo の多人数版)。

    レースごとに 強さ = 枠効果[枠] + 選手レーティング とし、実際の着順の
    対数尤度の勾配方向に少しずつ更新する。予測時は「前日までの値」を使う。
    """

    def __init__(self, lr: float = 0.06, lane_lr: float = 0.002):
        self.lr, self.lane_lr = lr, lane_lr
        self.r: dict[int, float] = {}
        self.n: dict[int, int] = {}
        self.lane = np.array([1.6, .5, .4, .3, 0., -.3])

    def strengths(self, racers, lanes):
        return self.lane[np.asarray(lanes) - 1] + np.array([self.r.get(int(x), 0.0) for x in racers])

    def update(self, racers, lanes, finish):
        racers, lanes, finish = np.asarray(racers), np.asarray(lanes), np.asarray(finish, float)
        ok = ~np.isnan(finish)
        if ok.sum() < 3:
            return
        s = self.strengths(racers, lanes)
        grad = np.zeros(len(racers))
        remaining = list(np.where(ok)[0])
        for idx in np.argsort(np.where(ok, finish, 99))[:3]:
            e = np.exp(s[remaining] - s[remaining].max())
            grad[remaining] -= e / e.sum()
            grad[idx] += 1
            remaining.remove(idx)
        for i, rid in enumerate(racers):
            rid = int(rid)
            n = self.n.get(rid, 0)
            lr = self.lr * (1 + 2.0 / (1 + n / 30))  # 経験が浅いほど大きく更新(新人の急成長に追従)
            self.r[rid] = self.r.get(rid, 0.0) + lr * grad[i]
            self.n[rid] = n + 1
        np.add.at(self.lane, lanes - 1, self.lane_lr * grad)


def add_rating(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["date", "race_id", "lane"]).reset_index(drop=True)
    rating = OnlineRating()
    out = np.zeros(len(df))
    lane_eff = np.zeros(len(df))
    for _, day in df.groupby("date", sort=True):
        idx = day.index.values
        out[idx] = [rating.r.get(int(x), 0.0) for x in day["racer_id"]]
        lane_eff[idx] = rating.lane[day["lane"].values - 1]
        if "finish" in day:
            for _, race in day.groupby("race_id", sort=False):
                rating.update(race["racer_id"].values, race["lane"].values, race["finish"].values)
    df["rating"] = out
    df["rating_strength"] = out + lane_eff
    df.attrs["rating_model"] = rating
    return df


def _asof_self(df: pd.DataFrame, col: str, days: int) -> np.ndarray:
    """選手ごとに、days 日前時点の col の値。"""
    base = df[["racer_id", "date", col]].dropna().drop_duplicates(["racer_id", "date"])
    base = base.assign(date=pd.to_datetime(base["date"])).sort_values("date")
    q = df[["racer_id", "date"]].copy()
    q["_row"] = np.arange(len(q))
    q["date"] = pd.to_datetime(q["date"]) - pd.Timedelta(days=days)
    q = q.sort_values("date")
    m = pd.merge_asof(q, base.rename(columns={col: "_v"}), on="date", by="racer_id")
    out = np.full(len(df), np.nan)
    out[m["_row"].values] = m["_v"].values
    return out


def add_growth(df: pd.DataFrame) -> pd.DataFrame:
    """選手の成長度(新人の伸びなど)。"""
    df = df.copy()
    for d in (90, 180):
        df[f"rating_growth_{d}"] = df["rating"] - _asof_self(df, "rating", d)
    df["winrate_growth_180"] = df["nat_win_rate"] - _asof_self(df, "nat_win_rate", 180)
    has = df["finish"].notna().astype(float) if "finish" in df else 0.0
    r = _rolling_prior(df.assign(_has=has), ["racer_id"], {"has": "_has"}, "730D", "xp")
    df = df.merge(r[["racer_id", "date", "xp_has"]], on=["racer_id", "date"], how="left")
    df["career_n_2y"] = df["xp_has"].fillna(0)
    df["toban"] = df["racer_id"]
    return df.drop(columns=["xp_has"])


def add_relative(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("race_id")
    src = REL_SRC + ["rating", "rc_win", "rl_win"]
    if "vw_win" in df and df["vw_win"].notna().any():
        src = src + ["vw_win"]
    if "rating_growth_180" in df:
        src = src + ["rating_growth_180"]
    if "exhibit_time" in df and df["exhibit_time"].notna().any():
        src = src + ["exhibit_time"]
    if "rc_avgst" in df:
        src = src + ["rc_avgst"]
    if "st_pred" in df and df["st_pred"].notna().any():
        src = src + ["st_pred"]
    for c in src:
        if c not in df:
            continue
        df[f"{c}_diff"] = df[c] - g[c].transform("mean")
        df[f"{c}_rank"] = g[c].rank(ascending=(c in ("exhibit_time", "rc_avgst", "st_pred")),
                                    method="average")
    if "exhibit_time" in df and df["exhibit_time"].notna().any():
        df["exhibit_gap_best"] = df["exhibit_time"] - g["exhibit_time"].transform("min")
    # 隣の艇(内・外)との関係。進入コースが分かればコース順、なければ枠順
    pos = df["course"].where(df["course"].notna(), df["lane"]) if "course" in df else df["lane"]
    key = df["race_id"].astype(str) + "_" + pos.astype(int).astype(str)
    for c in ("rc_avgst", "rating", "rc_win", "st_pred"):
        if c not in df:
            continue
        mp = pd.Series(df[c].values, index=key).groupby(level=0).first()
        inner = (df["race_id"].astype(str) + "_" + (pos - 1).astype(int).astype(str)).map(mp)
        outer = (df["race_id"].astype(str) + "_" + (pos + 1).astype(int).astype(str)).map(mp)
        df[f"in_{c}"] = inner.values
        df[f"out_{c}"] = outer.values
    if "rc_avgst" in df:  # 内の艇より自分のスタートが速いほど、まくりが決まりやすい
        df["st_adv_in"] = df["in_rc_avgst"] - df["rc_avgst"]
        df["st_adv_out"] = df["out_rc_avgst"] - df["rc_avgst"]
    if "in_st_pred" in df:
        df["st_pred_adv_in"] = df["in_st_pred"] - df["st_pred"]
        df["st_pred_adv_out"] = df["out_st_pred"] - df["st_pred"]
    df = add_matchups(df, pos)
    # 1号艇の強さ(イン逃げできるか)は全艇の着順に効く
    lane1 = df[df["lane"] == 1].set_index("race_id")
    for c in ("nat_win_rate", "rating", "rl_win", "class_num"):
        df[f"lane1_{c}"] = df["race_id"].map(lane1[c])
    return df


def add_matchups(df: pd.DataFrame, pos: pd.Series) -> pd.DataFrame:
    """特性同士の相性。ml_ は枠順(朝から分かる)、mu_ は進入コース順(展示後)で計算する。

    - in1_nige       : インの艇の逃げ率(高いほど外の艇は勝ちにくい)
    - makuri_x_st    : 自分のまくり率 × 内の艇よりスタートが速い度合い
    - sashi_x_in1    : 自分の差し率 × インの艇が逃げ損ねる率
    - mz_x_in1       : 自分のまくり差し率 × インの艇が逃げ損ねる率
    - out_makuri     : 外の艇のまくり率(外から攻められる危険)
    - makuri_pressure: 3・4コースの艇の「まくり率×スタート優位」の最大値(イン逃げを脅かす力)
    """
    if "makuri_rate" not in df:
        return df
    race = df["race_id"].astype(str)
    for prefix, p in (("ml_", df["lane"]), ("mu_", pos)):
        p = p.astype(int)
        st = df["st_pred"] if (prefix == "mu_" and "st_pred" in df) else df["rc_avgst"]
        tab = pd.DataFrame({"race": race.values, "p": p.values, "nige": df["nige_rate"].values,
                            "makuri": df["makuri_rate"].values, "st": st.values})
        idx = tab.set_index(["race", "p"])
        look = lambda col, q: pd.MultiIndex.from_arrays([race.values, q.values]).map(  # noqa: E731
            idx[col].groupby(level=[0, 1]).first())
        in1_nige = pd.Series(look("nige", pd.Series(1, index=df.index)), index=df.index).astype(float)
        in_st = pd.Series(look("st", p - 1), index=df.index).astype(float)
        out_mk = pd.Series(look("makuri", p + 1), index=df.index).astype(float)
        adv = (in_st - st).clip(-0.1, 0.1)
        df[prefix + "in1_nige"] = in1_nige.values
        df[prefix + "makuri_x_st"] = (df["makuri_rate"] * adv).values
        df[prefix + "sashi_x_in1"] = (df["sashi_rate"] * (1 - in1_nige)).values
        df[prefix + "mz_x_in1"] = (df["makurizashi_rate"] * (1 - in1_nige)).values
        df[prefix + "out_makuri"] = out_mk.values
        threat = (df["makuri_rate"] * adv.clip(lower=0)).where(p.isin([3, 4]))
        df[prefix + "makuri_pressure"] = threat.groupby(race).transform("max").fillna(0).values
    return df


GRADE_WORDS = [("優勝", 6), ("準優", 5), ("ドリーム", 4), ("特選", 3), ("特賞", 3), ("選抜", 3),
               ("予選", 2), ("一般", 1)]
LATE_ONLY = ("exhibit", "course", "wind", "wave", "ex_st", "tilt", "in_", "out_", "st_adv",
             "st_pred", "weight_diff", "vw_", "mu_")


def race_grade(s) -> int:
    s = str(s)
    for w, v in GRADE_WORDS:
        if w in s:
            return v
    return 1


def add_series(df: pd.DataFrame) -> pd.DataFrame:
    """今節の得点率と、準優勝戦ボーダーとの距離(勝負駆けの度合い)。番組表の時点の情報だけで計算。"""
    if "series_rate" not in df:
        return df
    racers = df.drop_duplicates(["date", "jcd", "racer_id"])[["date", "jcd", "racer_id", "series_rate"]]
    racers = racers.dropna(subset=["series_rate"])
    racers["series_rank"] = racers.groupby(["date", "jcd"])["series_rate"].rank(ascending=False, method="min")
    n = racers.groupby(["date", "jcd"])["racer_id"].transform("size")
    border = racers.groupby(["date", "jcd"])["series_rate"].transform(
        lambda x: x.sort_values(ascending=False).iloc[17] if len(x) >= 18 else np.nan)
    racers["series_rank_pct"] = racers["series_rank"] / n
    racers["border_gap"] = racers["series_rate"] - border
    df = df.merge(racers[["date", "jcd", "racer_id", "series_rank", "series_rank_pct", "border_gap"]],
                  on=["date", "jcd", "racer_id"], how="left")
    grade = df["race_grade"] if "race_grade" in df else pd.Series(2, index=df.index)
    gap = df["border_gap"].abs()
    # 予選(2)で、3日目以降、ボーダーまで1点以内 → 勝負駆け
    df["kachikake"] = ((grade == 2) & (df["day_no"] >= 3) & (gap <= 1.0)).astype(float)
    df["kachikake_strength"] = df["kachikake"] * (1.0 - gap.clip(upper=1.0))
    return df


def build(entries: pd.DataFrame, races: pd.DataFrame | None = None) -> pd.DataFrame:
    df = entries.copy()
    df["class_num"] = df["racer_class"].map(CLASS_NUM).fillna(1)
    if "race_type" in df:
        df["race_grade"] = df["race_type"].map(race_grade)
    if races is not None:
        keep = [c for c in ("wind", "wave", "kimarite") if c in races and c not in df]
        if keep:
            df = df.merge(races[["race_id"] + keep], on="race_id", how="left")
    df = add_series(df)
    df = add_history(df)
    df = add_rating(df)
    rating_model = df.attrs.get("rating_model")
    df = add_growth(df)
    df = add_late(df)
    df.attrs["rating_model"] = rating_model
    return df.sort_values(["date", "race_id", "lane"]).reset_index(drop=True)


def add_late(df: pd.DataFrame) -> pd.DataFrame:
    """直前情報(展示タイム・進入コース・風・波)から作る特徴量。"""
    df = df.copy()
    if "ex_st" in df and "st_bias" in df:
        # 展示STからの本番ST予想。展示を信じられる選手ほど展示を重く、そうでない選手は普段のSTを重く
        v0 = 0.045 ** 2
        w = v0 / (v0 + df["st_sd"] ** 2)
        pred = w * (df["ex_st"] + df["st_bias"]) + (1 - w) * df["rc_avgst"]
        df["st_pred"] = pred.where(df["ex_st"].notna(), df["rc_avgst"])
        df["st_pred_w"] = w.where(df["ex_st"].notna())
        df["ex_st_flying"] = (df["ex_st"] < 0).astype(float).where(df["ex_st"].notna())
    if "weight_now" in df:
        df["weight_diff"] = df["weight_now"] - df["weight"]
    if "wind_dir" in df and "wind" in df:
        ang = (pd.to_numeric(df["wind_dir"], errors="coerce") - 1) * np.pi / 8
        df["wind_x"] = df["wind"] * np.cos(ang)
        df["wind_y"] = df["wind"] * np.sin(ang)
    if "course" in df:
        df["course_shift"] = df["course"] - df["lane"]
        df["course_in"] = (df["course"] == 1).astype(float).where(df["course"].notna())
        if "rcc_win_1" in df:  # その選手の「このコースでの」成績
            crs = df["course"].fillna(df["lane"]).clip(1, 6).astype(int).values
            W = df[[f"rcc_win_{c}" for c in range(1, 7)]].values
            S = df[[f"rcc_st_{c}" for c in range(1, 7)]].values
            r = np.arange(len(df))
            df["course_win_hist"] = W[r, crs - 1]
            df["course_st_hist"] = S[r, crs - 1]
    return add_relative(df)


def feature_columns(df: pd.DataFrame, stage: str = "late") -> list[str]:
    exclude = {"race_id", "date", "racer_id", "racer_class", "finish", "st", "motor_no",
               "boat_no", "racer_name", "branch", "rating_strength", "deadline", "result_code",
               "st_flag", "race_type", "weight_now", "kimarite", "series_str",
               "race_time"}  # race_time はレース結果(未来の情報)なので特徴量にしない
    cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
            and df[c].notna().mean() > 0.5 and not c.startswith(("rcc_", "_"))]
    if stage == "early":
        cols = [c for c in cols if not any(c.startswith(p) for p in LATE_ONLY)]
    return cols
