"""早見表(保存したくなるまとめ)の数字を数える。2026-10-07 ユーザー「みんなが欲しがる情報まとめシート」「出目確率表」「各場の特徴まとめ、比較版や特化版」「めちゃくちゃいいの作り込んで」。

数えるもの(公式の成績データ 2023-10〜 を自分たちで集計):
- 24場の性格: イン(1コース)の1着率、コース別の1着率・3着以内率、決まり手の割合、荒れやすさ(3連単が31番人気より下で決まった割合)、
  進入が動く割合、強い風(5m以上)の日のインの1着率、夏と冬、ナイターかどうか、水面(海水・淡水・汽水)、
  海の場は潮(満潮のころ・干潮のころ)のインの1着率(差が前の2年と最近の1年で同じ向きのときだけ「本当」)
- 級別×コース: A1〜B2 × 1〜6コースの1着率・3着以内率
- 出目: 全国の出目の割合(上位)、人気から見た来やすさ(オッズのあるレース)、1号艇の級別・強い風の日の上位、場ごとの「らしい出目」(前の2年と最近の1年の両方で全国より多いものだけ★)

  python scripts/hayami.py [--out out/hayami/hayami.json]
数字の書き方は言葉の決まりどおり(%、差は「47%→66%」、めったに無い出目は「1000レースで◯回」)。買い目・回収率・配当の額は出さない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
          13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}
WATER = {1: "淡水", 2: "淡水", 3: "汽水", 4: "海水", 5: "淡水", 6: "汽水", 7: "汽水", 8: "海水", 9: "海水", 10: "汽水", 11: "淡水", 12: "淡水",
         13: "淡水", 14: "海水", 15: "海水", 16: "海水", 17: "海水", 18: "海水", 19: "海水", 20: "海水", 21: "淡水", 22: "汽水", 23: "海水", 24: "海水"}
KIM = {1: "逃げ", 2: "差し", 3: "まくり", 4: "まくり差し", 5: "抜き", 6: "恵まれ"}
ARE_POP = 30   # 3連単がこの人気順より下(31番人気〜)で決まったら「荒れた」
WIND = 5       # 強い風(m)
SPLIT = "2025-10-01"   # 前の2年 / 最近の1年


def r3(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


def boot_diff(a: np.ndarray, b: np.ndarray, n=2000, seed=0):
    """2つの0/1の列の率の差の90%区間(それぞれ引き直し)。"""
    rng = np.random.default_rng(seed)
    if len(a) < 30 or len(b) < 30:
        return None
    da = rng.binomial(len(a), a.mean(), n) / len(a)
    db = rng.binomial(len(b), b.mean(), n) / len(b)
    d = da - db
    return [r3(np.quantile(d, 0.05)), r3(np.quantile(d, 0.95))]


def strat_diff(a: pd.DataFrame, b: pd.DataFrame, key: str = "rno", col: str = "in1"):
    """a と b の率の差を、レース番号ごとに比べて重みつきで平均する(レース番号の偏りを除く)。
    例: 平和島では満潮が後半のレース(11R・12R)に寄っていて、後半は1号艇がもともと強いので、そろえないと潮の差が大きく見える(2026-10-07 確認)。
    返り値: (差, 90%区間)。"""
    ga, gb = a.groupby(key)[col].agg(["mean", "size"]), b.groupby(key)[col].agg(["mean", "size"])
    m = ga.join(gb, lsuffix="_a", rsuffix="_b", how="inner")
    m = m[(m["size_a"] >= 5) & (m["size_b"] >= 5)]
    if m.empty:
        return None, None
    w = m["size_a"] * m["size_b"] / (m["size_a"] + m["size_b"])
    d = float(((m["mean_a"] - m["mean_b"]) * w).sum() / w.sum())
    pa, pb = m["mean_a"].clip(0.01, 0.99), m["mean_b"].clip(0.01, 0.99)
    var = float((w ** 2 * (pa * (1 - pa) / m["size_a"] + pb * (1 - pb) / m["size_b"])).sum() / w.sum() ** 2)
    se = var ** 0.5
    return d, [r3(d - 1.645 * se), r3(d + 1.645 * se)]


def load(end: str):
    from kyotei.data import load_history
    ent, races, odds = load_history()
    ent = ent[ent["date"] < end].copy()
    races = races[races["date"] < end].copy()
    # 1着が決まったレース(F・欠場があったレースも含める。ほかのデータの「1コース1着率」と同じ数え方)
    rid = set(ent.loc[ent["finish"] == 1, "race_id"])
    ent = ent[ent["race_id"].isin(rid)]
    races = races[races["race_id"].isin(rid)].drop_duplicates("race_id").set_index("race_id")
    return ent, races, odds


def race_table(ent: pd.DataFrame, races: pd.DataFrame) -> pd.DataFrame:
    w = ent[ent["finish"] == 1].drop_duplicates("race_id").set_index("race_id")   # 同着は1艇目
    t = pd.DataFrame(index=races.index)
    t["jcd"] = races["jcd"].astype(int)
    t["date"] = races["date"].astype(str)
    t["win_course"] = w["course"].reindex(t.index)
    t["kim"] = races["kimarite"]
    t["wind"] = pd.to_numeric(races["wind"], errors="coerce")
    t["tri_pop"] = pd.to_numeric(races["tri_pop"], errors="coerce")
    t["tri"] = races["tri_combo"]
    l1 = ent[ent["lane"] == 1].drop_duplicates("race_id").set_index("race_id")
    t["l1_class"] = l1["racer_class"].reindex(t.index)
    t["race_type"] = l1["race_type"].reindex(t.index) if "race_type" in l1 else None
    t["deadline"] = l1["deadline"].reindex(t.index) if "deadline" in l1 else None
    moved = ent.assign(m=(ent["course"] != ent["lane"])).groupby("race_id")["m"].any()
    t["moved"] = moved.reindex(t.index).fillna(False)
    t["in1"] = (t["win_course"] == 1).astype(float)
    t["month"] = pd.to_datetime(t["date"]).dt.month
    t["rno"] = pd.Series(t.index, index=t.index).str[-2:].astype(int)
    t["late"] = t["date"] >= SPLIT
    return t


def venue_profile(t: pd.DataFrame, ent: pd.DataFrame) -> dict:
    out = {}
    nat = t
    cw_nat = nat["win_course"].value_counts(normalize=True)
    for j in sorted(t["jcd"].unique()):
        v = t[t["jcd"] == j]
        e = ent[ent["jcd"] == j]
        top3 = e.assign(t3=e["finish"] <= 3).groupby("course")["t3"].mean()
        cw = v["win_course"].value_counts(normalize=True)
        kim = v["kim"].value_counts(normalize=True)
        strong = v[v["wind"] >= WIND]
        calm = v[v["wind"] < WIND]
        summer = v[v["month"].isin([7, 8, 9])]
        winter = v[v["month"].isin([12, 1, 2])]
        night = float((v["deadline"].astype(str) >= "17:30").mean()) if v["deadline"] is not None else None
        ippan = v[v["race_type"].astype(str).str.contains("予選|一般", na=False)]
        a1 = ippan[ippan["l1_class"] == "A1"]
        out[int(j)] = {
            "name": VENUES[int(j)], "water": WATER[int(j)], "races": int(len(v)),
            "in1": r3(v["in1"].mean()), "in1_first": r3(v.loc[~v["late"], "in1"].mean()), "in1_last": r3(v.loc[v["late"], "in1"].mean()),
            "course_win": {int(c): r3(cw.get(c, 0)) for c in range(1, 7)},
            "course_top3": {int(c): r3(top3.get(c, np.nan)) for c in range(1, 7)},
            "kimarite": {KIM[k]: r3(kim.get(float(k), 0)) for k in KIM},
            "are": r3((v["tri_pop"] > ARE_POP).mean()),
            "moved": r3(v["moved"].mean()),
            "wind": {"n_strong": int(len(strong)), "in1_strong": r3(strong["in1"].mean()) if len(strong) else None,
                     "in1_calm": r3(calm["in1"].mean()), "ci": strat_diff(strong, calm)[1], "diff_adj": r3(strat_diff(strong, calm)[0]),
                     "share_strong": r3(len(strong) / max(len(v), 1))},
            "season": {"summer": r3(summer["in1"].mean()), "winter": r3(winter["in1"].mean()),
                       "n_summer": int(len(summer)), "n_winter": int(len(winter))},
            "night_share": r3(night),
            "a1_in1": r3(a1["in1"].mean()) if len(a1) >= 100 else None, "a1_n": int(len(a1)),
            "b1_in1": r3(ippan[ippan["l1_class"] == "B1"]["in1"].mean()) if (ippan["l1_class"] == "B1").sum() >= 100 else None,
            "avg_st": r3(e.loc[e["st"].between(0, 0.5), "st"].mean()),
        }
    out[0] = {"name": "全国", "races": int(len(t)), "in1": r3(t["in1"].mean()),
              "course_win": {int(c): r3(cw_nat.get(c, 0)) for c in range(1, 7)},
              "course_top3": {int(c): r3(v) for c, v in ent.assign(t3=ent["finish"] <= 3).groupby("course")["t3"].mean().items() if 1 <= c <= 6},
              "kimarite": {KIM[k]: r3(t["kim"].value_counts(normalize=True).get(float(k), 0)) for k in KIM},
              "are": r3((t["tri_pop"] > ARE_POP).mean()), "moved": r3(t["moved"].mean()),
              "wind": {"in1_strong": r3(t.loc[t["wind"] >= WIND, "in1"].mean()), "in1_calm": r3(t.loc[t["wind"] < WIND, "in1"].mean()),
                       "n_strong": int((t["wind"] >= WIND).sum())},
              "season": {"summer": r3(t.loc[t["month"].isin([7, 8, 9]), "in1"].mean()), "winter": r3(t.loc[t["month"].isin([12, 1, 2]), "in1"].mean())},
              "avg_st": r3(ent.loc[ent["st"].between(0, 0.5), "st"].mean()),
              "a1_in1": r3(t[t["race_type"].astype(str).str.contains("予選|一般", na=False) & (t["l1_class"] == "A1")]["in1"].mean()),
              "b1_in1": r3(t[t["race_type"].astype(str).str.contains("予選|一般", na=False) & (t["l1_class"] == "B1")]["in1"].mean())}
    return out


def tide_effect(t: pd.DataFrame) -> dict:
    """海・汽水の場で、満潮のころと干潮のころのインの1着率。前の2年と最近の1年で同じ向きか。"""
    try:
        from kyotei.tide import tide_for
    except Exception:  # noqa: BLE001
        return {}
    d = t.reset_index()[["race_id", "jcd", "date", "deadline", "in1", "late", "rno"]].copy()
    d = d[d["deadline"].notna()]
    d = tide_for(d)
    out = {}
    for j, v in d.groupby("jcd"):
        if WATER[int(j)] == "淡水":
            continue
        hi, lo = v[v["tide_kind"] == "満潮のころ"], v[v["tide_kind"] == "干潮のころ"]
        if len(hi) < 300 or len(lo) < 300:
            continue
        d_all, ci = strat_diff(hi, lo)
        d1, _ = strat_diff(hi[~hi["late"]], lo[~lo["late"]])
        d2, _ = strat_diff(hi[hi["late"]], lo[lo["late"]])
        real = bool(ci and (ci[0] > 0 or ci[1] < 0) and d1 is not None and d2 is not None and np.sign(d1) == np.sign(d2) == np.sign(d_all))
        out[int(j)] = {"in1_high": r3(hi["in1"].mean()), "in1_low": r3(lo["in1"].mean()), "n_high": int(len(hi)), "n_low": int(len(lo)),
                       "diff_raw": r3(float(hi["in1"].mean() - lo["in1"].mean())), "diff": r3(d_all), "diff_first": r3(d1), "diff_last": r3(d2),
                       "ci": ci, "real": real, "note": "差はレース番号ごとに比べて平均(満潮・干潮の時間がレース番号に偏るため)"}
    return out


def class_course(ent: pd.DataFrame) -> dict:
    e = ent[ent["course"].between(1, 6) & ent["racer_class"].isin(["A1", "A2", "B1", "B2"])]
    g = e.assign(w=e["finish"] == 1, t3=e["finish"] <= 3).groupby(["racer_class", "course"])
    out = {}
    for (c, k), v in g:
        out.setdefault(c, {})[int(k)] = {"win": r3(v["w"].mean()), "top3": r3(v["t3"].mean()), "n": int(len(v))}
    return out


def deme(t: pd.DataFrame, odds: pd.DataFrame | None) -> dict:
    from kyotei.betting import COMBOS, market_probs, odds_matrix
    v = t[t["tri"].isin(COMBOS)]
    share = v["tri"].value_counts(normalize=True)
    top = share.head(20)
    out = {"races": int(len(v)), "top": [{"combo": c, "share": r3(s)} for c, s in top.items()]}
    # 人気から見た来やすさ(オッズのあるレース): 実際の回数 ÷ 人気の確率の合計
    if odds is not None and not odds.empty:
        rids = np.array(sorted(set(v.index) & set(odds["race_id"].unique())))
        O = odds_matrix(odds, rids)
        ok = np.isfinite(O).sum(1) >= 100
        rids, O = rids[ok], O[ok]
        P = np.array([market_probs(o) for o in O])
        y = np.array([COMBOS.index(c) for c in v.loc[rids, "tri"]])
        rng = np.random.default_rng(3)
        idx = rng.integers(0, len(rids), (1000, len(rids)))
        ratio = {}
        for c in list(top.index):
            i = COMBOS.index(c)
            act = (y == i).astype(float)
            exp = P[:, i]
            b = act[idx].sum(1) / exp[idx].sum(1)
            ratio[c] = {"ratio": r3(act.sum() / exp.sum()), "ci": [r3(np.quantile(b, 0.05)), r3(np.quantile(b, 0.95))],
                        "actual": int(act.sum()), "expected": round(float(exp.sum()), 1)}
        out["popular_ratio"] = {"races": int(len(rids)), "by_combo": ratio}
    # 条件別の上位5(1号艇の級別・強い風)
    cond = {}
    for c in ("A1", "A2", "B1", "B2"):
        s = v[v["l1_class"] == c]["tri"].value_counts(normalize=True).head(5)
        cond[f"1号艇{c}"] = {"races": int((v["l1_class"] == c).sum()), "top": [{"combo": k, "share": r3(x)} for k, x in s.items()]}
    s = v[v["wind"] >= WIND]["tri"].value_counts(normalize=True).head(5)
    cond["風5m以上"] = {"races": int((v["wind"] >= WIND).sum()), "top": [{"combo": k, "share": r3(x)} for k, x in s.items()]}
    out["conditions"] = cond
    # 場ごとの「らしい出目」。インが強い場は 1-◯-◯ がみんな多くなるだけなので、
    # 「1着の艇番の割合はその場のまま、2着・3着の並びは全国どおり」なら何回のはずか、と比べる(らしさ = 実際 ÷ その見込み)。
    # 前の2年と最近の1年の両方で1.15倍以上、かつ最近の1年でも30回以上あれば★
    v = v.assign(first=v["tri"].str[0])
    def cond_nat(d):   # 全国の P(出目 | 1着の艇番)
        cnt = d.groupby(["first", "tri"]).size()
        return cnt / cnt.groupby(level=0).transform("sum")
    def expected(g, cn):
        pf = g["first"].value_counts(normalize=True)
        return {c: float(pf.get(c[0], 0) * cn.get((c[0], c), 0)) for c in g["tri"].unique()}
    cn_all, cn_f, cn_l = cond_nat(v), cond_nat(v[~v["late"]]), cond_nat(v[v["late"]])
    venue = {}
    for j, g in v.groupby("jcd"):
        gf, gl = g[~g["late"]], g[g["late"]]
        sj, sf, sl = (x["tri"].value_counts(normalize=True) for x in (g, gf, gl))
        ea, ef, el = expected(g, cn_all), expected(gf, cn_f), expected(gl, cn_l)
        nlast = gl["tri"].value_counts()
        rows = []
        for c, x in sj.items():
            la, lf, ll = x / max(ea.get(c, 0), 1e-9), sf.get(c, 0) / max(ef.get(c, 0), 1e-9), sl.get(c, 0) / max(el.get(c, 0), 1e-9)
            rows.append({"combo": c, "share": r3(x), "national": r3(share.get(c)), "lift_raw": r3(x / share.get(c, np.nan)),
                         "like": r3(la), "like_first": r3(lf), "like_last": r3(ll), "n": int((g["tri"] == c).sum()),
                         "n_last": int(nlast.get(c, 0)), "exp_last": round(float(el.get(c, 0) * len(gl)), 1),
                         "found": bool(lf >= 1.2 and sf.get(c, 0) * len(gf) >= 40)})
        # 前の2年で見つけたもの(らしさ1.2倍以上・40回以上)を、最近の1年で確かめる(見つけた数で割った厳しめの線。たまたまを外す)
        from scipy.stats import poisson
        found = [r for r in rows if r["found"]]
        for r in rows:
            r["p_last"] = None
            r["star"] = False
        for r in found:
            pv = float(poisson.sf(r["n_last"] - 1, max(r["exp_last"], 1e-9)))
            r["p_last"] = round(pv, 5)
            r["star"] = bool(pv < 0.05 / max(len(found), 1) and r["like_last"] >= 1.15)
        top = rows[:8]
        stars = sorted([r for r in rows if r["star"]], key=lambda r: -r["like"])[:5]
        venue[int(j)] = {"races": int(len(g)), "top": top, "stars": stars}
    out["venue"] = venue
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out/hayami/hayami.json"))
    ap.add_argument("--end", default=None, help="この日の前日まで(既定: 今月の1日)")
    a = ap.parse_args(argv)
    end = a.end or dt.date.today().replace(day=1).isoformat()
    ent, races, odds = load(end)
    t = race_table(ent, races)
    res = {"period": [str(t["date"].min()), str(t["date"].max())], "races": int(len(t)), "split": SPLIT,
           "venues": venue_profile(t, ent), "tide": tide_effect(t), "class_course": class_course(ent), "deme": deme(t, odds),
           "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out, res["period"], res["races"])


if __name__ == "__main__":
    main()
