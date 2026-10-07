"""選手の「型」が本物か(たまたまか)を確かめる: 同じ選手を2つの期間に分け、片方で強い選手がもう片方でも強いか(相関)を見る。

分け方: 月の奇数・偶数(時期のかたよりを避ける)。各期間で決まった走数以上ある選手だけ。
状況の強さは「その状況の3着以内の上積み − その期間の本人の普段の上積み」(本人比)。
相関が 0 に近い型は、選手の性質ではなく偶然の可能性が高い → タグや記事の見出しには使わない。

python scripts/trait_reliability.py → reports/trait_reliability.json
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import racer_card as rc  # noqa: E402

OUT = ROOT / "reports/trait_reliability.json"


def prep(d: pd.DataFrame) -> pd.DataFrame:
    s = d[d["finish"].between(1, 6)].copy()
    s["top3"] = (s["finish"] <= 3).astype(float)
    s["win"] = (s["finish"] == 1).astype(float)
    s["res3"] = s["top3"] - s["course"].map(s.groupby("course")["top3"].mean())
    t = s["race_title"].astype(str)
    s["yosen"] = t.str.contains("予選")
    s["big"] = t.str.contains("準優|優勝戦")
    semi = s[t.str.contains("準優")][["jcd", "date"]].drop_duplicates()
    semi["date"] = (pd.to_datetime(semi["date"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    kd = set(map(tuple, semi.values.tolist()))
    s["kake"] = s["yosen"] & pd.Series([(j, x) in kd for j, x in zip(s["jcd"], s["date"])], index=s.index)
    s["rough"] = (s["wave"] >= 5) | (s["wind"] >= 5)
    s["ex_rank"] = s.groupby("race_id")["exhibit_time"].rank(method="min")
    s["exlate"] = s["ex_rank"] >= 4
    # 節: 初日 = 日付 − (何日目 − 1)
    dd = pd.to_datetime(s["date"])
    s["series"] = s["jcd"].astype(str) + "_" + (dd - pd.to_timedelta(s["day_no"].fillna(1) - 1, unit="D")).dt.strftime("%Y%m%d")
    s = s.sort_values(["racer_id", "series", "day_no", "rno"])
    s["nth"] = s.groupby(["racer_id", "series"]).cumcount() + 1          # 節の何走目か
    s["first"] = s["nth"] == 1                                            # 節の初戦
    s["day1"] = s["day_no"] == 1
    s["early_y"] = s["yosen"] & s["day_no"].isin([1, 2])
    s["late_y"] = s["yosen"] & s["day_no"].isin([3, 4])
    s["half"] = pd.to_datetime(s["date"]).dt.month % 2
    return s


def own_rel(g: pd.DataFrame, mask: str, min_n: int) -> pd.Series:
    base = g.groupby("racer_id")["res3"].mean()
    x = g[g[mask]].groupby("racer_id")["res3"].agg(["mean", "size"])
    x = x[x["size"] >= min_n]
    return x["mean"] - base.reindex(x.index)


def diff(g: pd.DataFrame, a: str, b: str, min_n: int) -> pd.Series:
    """後半 − 前半(予選の3〜4日目 − 1〜2日目)。"""
    xa = g[g[a]].groupby("racer_id")["res3"].agg(["mean", "size"])
    xb = g[g[b]].groupby("racer_id")["res3"].agg(["mean", "size"])
    ok = (xa["size"] >= min_n) & (xb.reindex(xa.index)["size"] >= min_n)
    return (xa["mean"] - xb.reindex(xa.index)["mean"])[ok]


def corr(a: pd.Series, b: pd.Series) -> dict:
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(j) < 30:
        return {"n": int(len(j))}
    r = float(j["a"].corr(j["b"]))
    rs = float(j["a"].rank().corr(j["b"].rank()))
    # 選手を入れ替えて作った相関の90%区間(偶然でもこのくらいは出る)
    rng = np.random.default_rng(0)
    null = [float(np.corrcoef(j["a"].values, rng.permutation(j["b"].values))[0, 1]) for _ in range(300)]
    boot = []
    for _ in range(300):
        k = j.sample(len(j), replace=True, random_state=int(rng.integers(1e9)))
        boot.append(float(k["a"].corr(k["b"])))
    return {"n": int(len(j)), "r": round(r, 3), "spearman": round(rs, 3),
            "ci90": [round(float(np.quantile(boot, 0.05)), 3), round(float(np.quantile(boot, 0.95)), 3)],
            "null90": round(float(np.quantile(np.abs(null), 0.90)), 3)}


def growth_persistence(s: pd.DataFrame) -> dict:
    """勢い(直近90日の勝率の点 − その前の1年)は、次の90日にどれだけ残るか。複数の時点で計算して回帰の傾き。"""
    s = s.assign(pts=s["finish"].map(rc.POINTS).astype(float), dt=pd.to_datetime(s["date"]))
    rows = []
    for cut in pd.date_range("2024-12-01", s["dt"].max() - pd.Timedelta(days=90), freq="60D"):
        rec = s[(s["dt"] > cut - pd.Timedelta(days=90)) & (s["dt"] <= cut)].groupby("racer_id")["pts"].agg(["mean", "size"])
        prv = s[(s["dt"] > cut - pd.Timedelta(days=455)) & (s["dt"] <= cut - pd.Timedelta(days=90))].groupby("racer_id")["pts"].agg(["mean", "size"])
        nxt = s[(s["dt"] > cut) & (s["dt"] <= cut + pd.Timedelta(days=90))].groupby("racer_id")["pts"].agg(["mean", "size"])
        j = pd.concat([rec, prv, nxt], axis=1, keys=["r", "p", "n"]).dropna()
        j = j[(j[("r", "size")] >= 15) & (j[("p", "size")] >= 30) & (j[("n", "size")] >= 15)]
        rows.append(pd.DataFrame({"x": j[("r", "mean")] - j[("p", "mean")], "y": j[("n", "mean")] - j[("p", "mean")]}))
    a = pd.concat(rows)
    slope = float(np.polyfit(a["x"], a["y"], 1)[0])
    big = a[a["x"] >= 0.6]       # 「上り調子」タグに近い、勝率の点が0.6以上伸びた選手(勝率なら約+0.6)
    return {"n": int(len(a)), "slope": round(slope, 3), "r": round(float(a["x"].corr(a["y"])), 3),
            "up_n": int(len(big)), "up_x": round(float(big["x"].mean()), 3), "up_y_next90": round(float(big["y"].mean()), 3)}


def main():
    d = rc.load_table()
    s = prep(d)
    h = {k: s[s["half"] == k] for k in (0, 1)}
    out = {"split": "月の奇数・偶数", "traits": {}}

    def add(name, label, fn):
        out["traits"][name] = {"label": label, **corr(fn(h[0]), fn(h[1]))}
        print(name, label, out["traits"][name])
    # 比べるための「本物の性質」
    add("st", "平均ST(参考)", lambda g: g.groupby("racer_id")["st"].agg(["mean", "size"]).query("size >= 40")["mean"])
    add("res3", "3着以内の上積み(参考)", lambda g: g.groupby("racer_id")["res3"].agg(["mean", "size"]).query("size >= 60")["mean"])
    add("nige", "1コースの1着率(参考)", lambda g: g[g["course"] == 1].groupby("racer_id")["win"].agg(["mean", "size"]).query("size >= 15")["mean"])
    # 状況ごとの強さ(本人比)
    add("first", "節の初戦", lambda g: own_rel(g, "first", 12))
    add("day1", "初日", lambda g: own_rel(g, "day1", 15))
    add("late_y", "予選の後半(3〜4日目 − 1〜2日目)", lambda g: diff(g, "late_y", "early_y", 12))
    add("kake", "勝負駆け(予選最終日)", lambda g: own_rel(g, "kake", 8))
    add("big", "準優・優勝戦", lambda g: own_rel(g, "big", 8))
    add("rough", "荒れ水面", lambda g: own_rel(g, "rough", 12))
    add("exlate", "展示タイム4位以下", lambda g: own_rel(g, "exlate", 15))
    out["growth"] = growth_persistence(s)
    print("growth", out["growth"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")



def pair_corr(h0: pd.DataFrame, h1: pd.DataFrame, key: str, min_n: int) -> dict:
    """選手×場、選手×コースのような組ごとの本人比の上積み(その組の3着以内の上積み − 本人の普段)。"""
    def f(g):
        base = g.groupby("racer_id")["res3"].mean()
        x = g.groupby(["racer_id", key])["res3"].agg(["mean", "size"])
        x = x[x["size"] >= min_n]
        return x["mean"] - base.reindex(x.index.get_level_values(0)).values
    return corr(f(h0), f(h1))


def extra():
    d = rc.load_table()
    s = prep(d)
    h0, h1 = s[s["half"] == 0], s[s["half"] == 1]
    out = json.loads(OUT.read_text(encoding="utf-8"))
    out["traits"]["venue"] = {"label": "場との相性(選手×場、各期間10走以上)", **pair_corr(h0, h1, "jcd", 10)}
    out["traits"]["course"] = {"label": "コースごとの得意(選手×コース、各期間10走以上)", **pair_corr(h0, h1, "course", 10)}
    fr = lambda g: g[g["lane"] >= 2].assign(f=lambda x: (x["course"] < x["lane"]).astype(float)).groupby("racer_id")["f"].agg(["mean", "size"]).query("size >= 40")["mean"]  # noqa: E731
    out["traits"]["front"] = {"label": "前づけ率", **corr(fr(h0), fr(h1))}
    def rate(g, cmask, kim, min_n):
        x = g[cmask(g)].assign(w=lambda z: ((z["finish"] == 1) & (z["kimarite"] == kim)).astype(float)).groupby("racer_id")["w"].agg(["mean", "size"])
        return x[x["size"] >= min_n]["mean"]
    def exm(g, f):
        x = g.dropna(subset=["ex_st", "st"]).assign(v=lambda z: f(z["st"] - z["ex_st"])).groupby("racer_id")["v"].agg(["mean", "size"])
        return x[x["size"] >= 15]["mean"]
    tests = {
        "ex_mae": ("展示STと本番STのずれ", lambda g: exm(g, abs)),
        "ex_delta": ("展示→本番のSTの差", lambda g: exm(g, lambda v: v)),
        "sashi": ("差しで勝つ割合", lambda g: rate(g, lambda z: z["course"] >= 2, 2, 15)),
        "makuri": ("まくりで勝つ割合", lambda g: rate(g, lambda z: z["course"] >= 2, 3, 15)),
        "mz": ("まくり差しで勝つ割合", lambda g: rate(g, lambda z: z["course"] >= 3, 4, 15)),
        "out": ("4〜6コースの3着以内の上積み", lambda g: g[g["course"] >= 4].groupby("racer_id")["res3"].agg(["mean", "size"]).query("size >= 15")["mean"]),
    }
    for k, (label, fn) in tests.items():
        out["traits"][k] = {"label": label, **corr(fn(h0), fn(h1))}
    for k in ("venue", "course", "front", *tests):
        print(k, out["traits"][k])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    extra() if "--extra" in sys.argv else (main(), extra())
