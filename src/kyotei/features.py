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


def _smoothed(num, den, prior, strength):
    return (num.fillna(0) + prior * strength) / (den.fillna(0) + strength)


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

    # 選手の直近180日
    r = _rolling_prior(df, ["racer_id"], {"win": "_win", "top3": "_top3", "fin": "_fin",
                                          "st": "_st", "has": "_has", "hst": "_has_st"}, "180D", "rc")
    df = df.merge(r, on=["racer_id", "date"], how="left")
    df["rc_n"] = df["rc_has"].fillna(0)
    df["rc_win"] = _smoothed(df["rc_win"], df["rc_has"], 1 / 6, 5)
    df["rc_top3"] = _smoothed(df["rc_top3"], df["rc_has"], 0.5, 5)
    df["rc_avgfin"] = _smoothed(df["rc_fin"], df["rc_has"], 3.5, 5)
    df["rc_avgst"] = _smoothed(df["rc_st"], df["rc_hst"], 0.16, 5)

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

    # モーター(場×番号、直近120日。モーターは年1回程度で入れ替わる)
    r = _rolling_prior(df, ["jcd", "motor_no"], {"top2": "_top2", "has": "_has"}, "120D", "mt")
    df = df.merge(r, on=["jcd", "motor_no", "date"], how="left")
    df["mt_top2"] = _smoothed(df["mt_top2"], df["mt_has"], 1 / 3, 10)

    drop = [c for c in df.columns if c.startswith("_") or c in
            ("rc_fin", "rc_st", "rc_has", "rc_hst", "rl_has", "vl_has", "mt_has", "rc_n_x")]
    return df.drop(columns=drop)


class OnlineRating:
    """枠の有利不利を同時に学習するPlackett-Luce型レーティング(Elo の多人数版)。

    レースごとに 強さ = 枠効果[枠] + 選手レーティング とし、実際の着順の
    対数尤度の勾配方向に少しずつ更新する。予測時は「前日までの値」を使う。
    """

    def __init__(self, lr: float = 0.06, lane_lr: float = 0.002):
        self.lr, self.lane_lr = lr, lane_lr
        self.r: dict[int, float] = {}
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
            self.r[int(rid)] = self.r.get(int(rid), 0.0) + self.lr * grad[i]
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


def add_relative(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("race_id")
    src = REL_SRC + ["rating", "rc_win", "rl_win"]
    if "exhibit_time" in df and df["exhibit_time"].notna().any():
        src = src + ["exhibit_time"]
    if "rc_avgst" in df:
        src = src + ["rc_avgst"]
    for c in src:
        if c not in df:
            continue
        df[f"{c}_diff"] = df[c] - g[c].transform("mean")
        df[f"{c}_rank"] = g[c].rank(ascending=(c in ("exhibit_time", "rc_avgst")), method="average")
    if "exhibit_time" in df and df["exhibit_time"].notna().any():
        df["exhibit_gap_best"] = df["exhibit_time"] - g["exhibit_time"].transform("min")
    # 1号艇の強さ(イン逃げできるか)は全艇の着順に効く
    lane1 = df[df["lane"] == 1].set_index("race_id")
    for c in ("nat_win_rate", "rating", "rl_win", "class_num"):
        df[f"lane1_{c}"] = df["race_id"].map(lane1[c])
    return df


GRADE_WORDS = [("優勝", 6), ("準優", 5), ("ドリーム", 4), ("特選", 3), ("特賞", 3), ("選抜", 3),
               ("予選", 2), ("一般", 1)]
LATE_ONLY = ("exhibit", "course", "wind", "wave", "ex_st", "tilt")


def race_grade(s) -> int:
    s = str(s)
    for w, v in GRADE_WORDS:
        if w in s:
            return v
    return 1


def build(entries: pd.DataFrame, races: pd.DataFrame | None = None) -> pd.DataFrame:
    df = entries.copy()
    df["class_num"] = df["racer_class"].map(CLASS_NUM).fillna(1)
    if "race_type" in df:
        df["race_grade"] = df["race_type"].map(race_grade)
    if races is not None:
        keep = [c for c in ("wind", "wave") if c in races and c not in df]
        if keep:
            df = df.merge(races[["race_id"] + keep], on="race_id", how="left")
    df = add_history(df)
    df = add_rating(df)
    df = add_late(df)
    return df.sort_values(["date", "race_id", "lane"]).reset_index(drop=True)


def add_late(df: pd.DataFrame) -> pd.DataFrame:
    """直前情報(展示タイム・進入コース・風・波)から作る特徴量。"""
    df = df.copy()
    if "course" in df:
        df["course_shift"] = df["course"] - df["lane"]
        df["course_in"] = (df["course"] == 1).astype(float).where(df["course"].notna())
    return add_relative(df)


def feature_columns(df: pd.DataFrame, stage: str = "late") -> list[str]:
    exclude = {"race_id", "date", "racer_id", "racer_class", "finish", "st", "motor_no",
               "boat_no", "racer_name", "branch", "rating_strength", "deadline", "result_code",
               "st_flag", "race_type", "weight_now"}
    cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
            and df[c].notna().mean() > 0.5]
    if stage == "early":
        cols = [c for c in cols if not any(c.startswith(p) for p in LATE_ONLY)]
    return cols
