"""選手カード: 公式の成績データを自分たちで集計して、選手ごとの特性・ひと言タグ・レーダーチャートの値を作る。

使うのは data/history(番組表・競走成績)・data/previews(展示ST)・data/kimarite(決まり手)だけ。
公式サイトの出走表・オッズの表・写真は使わない(数字は全部ここで集計し直したもの)。

考え方:
- 枠(コース)の有利不利が大きいので、「3着内に入ったか」はコースごとの全体の3着内率を引いた「上積み」で比べる
  (イン戦が多い選手ほど数字が良く見える、を避ける)
- 場・荒れ水面・勝負駆け・大一番・展示が悪いときは、その選手の普段の上積みとの差で見る(強い選手がどこでも良く見える、を避ける)
- 回数が少ない数字は全体(または本人の普段)に寄せる(SHRINK 回分を足して割る)。カードには回数も必ず出す
- 全選手の中での位置(パーセンタイル)は「同じ級別の中で」(A1 / A2 / B級)と「全選手の中で」の両方。
  母集団は、集計期間に100走以上し、直近180日に走っている選手。レーダーチャートは同じ級別の中での位置
- ひと言タグは、決まった基準(TAG_RULES)を満たしたときだけ付け、根拠の数字と基準の文をそのまま残す。
  選手をけなすタグは作らない(弱点ではなく「型」や「得意」だけを書く)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POINTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}  # 勝率の点数
VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑", 9: "津", 10: "三国",
          11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関",
          20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}
SHRINK = 20          # 少ない回数を全体(本人の普段)に寄せる強さ(回数)
MIN_STARTS = 100     # パーセンタイルを出す母集団の条件
RADAR = ["スタート", "逃げ", "差し", "まくり", "安定感", "展示の信頼度"]
GROUP_NAME = {"A1": "A1", "A2": "A2", "B": "B級"}


def st_fmt(v) -> str:
    """ST の表示(.12)。アプリ(JavaScript の toFixed)と同じく四捨五入する。"""
    import math
    x = math.floor(abs(v) * 100 + 0.5 + 1e-9) / 100
    return ("F" if v < 0 else "") + f"{x:.2f}"[1:]


def load_table(since: str | None = None) -> pd.DataFrame:
    """1行 = 1選手の1走。必要な列だけ。"""
    from .data import load_history
    ent, races, _ = load_history(since=since)
    keep = ["race_id", "date", "jcd", "rno", "lane", "racer_id", "racer_name", "age", "branch", "racer_class",
            "motor_no", "motor_2rate", "day_no", "finish", "course", "st", "st_flag", "exhibit_time", "ex_st"]
    d = ent[[c for c in keep if c in ent.columns]].copy()
    d["race_id"] = d["race_id"].astype(str)
    r = races[[c for c in ("race_id", "race_title", "kimarite", "wind", "wave", "tri_pay", "tri_pop") if c in races.columns]].copy()
    r["race_id"] = r["race_id"].astype(str)
    d = d.merge(r.drop_duplicates("race_id"), on="race_id", how="left")
    d = d[d["course"].between(1, 6)]
    d["course"] = d["course"].astype(int)
    d["name"] = d["racer_name"].astype(str).str.replace(r"[\s　]+", "", regex=True)
    return d


def _shrunk(num, den, prior, k=SHRINK):
    return (num + k * prior) / (den + k)


def build(d: pd.DataFrame, asof: str | None = None) -> tuple[dict, dict]:
    """全選手のカード {racer_id: card} と、母集団の情報(基準・タグの数)を返す。"""
    asof = asof or str(d["date"].max())
    s = d[d["finish"].between(1, 6)].copy()            # 着順のついた走(フライング・欠場などを除く)
    s["finish"] = s["finish"].astype(int)
    s["win"] = (s["finish"] == 1).astype(float)
    s["top3"] = (s["finish"] <= 3).astype(float)
    s["pts"] = s["finish"].map(POINTS).astype(float)
    pop_c = s.groupby("course")[["win", "top3"]].mean()
    s["res3"] = s["top3"] - s["course"].map(pop_c["top3"])     # コースを差し引いた3着内の上積み
    s["kim"] = np.where(s["finish"] == 1, s["kimarite"], np.nan)
    g = s.groupby("racer_id")
    base = pd.DataFrame({"n": g.size(), "win": g["win"].mean(), "top3": g["top3"].mean(), "pts": g["pts"].mean(),
                         "res3": g["res3"].mean(), "last": g["date"].max(), "first": g["date"].min()})
    latest = d.sort_values("date").groupby("racer_id").tail(1).set_index("racer_id")
    for c in ("name", "racer_class", "branch", "age"):
        base[c] = latest[c].reindex(base.index)
    base["grp"] = base["racer_class"].map({"A1": "A1", "A2": "A2"}).fillna("B")
    own = base["res3"]

    def own_rel(mask, key):
        """条件に合う走の上積みを、本人の普段の上積みに寄せてから、普段との差を出す。"""
        x = s[mask].groupby("racer_id")["res3"].agg(["sum", "size"]).reindex(base.index)
        n = x["size"].fillna(0)
        base[f"{key}_n"] = n
        base[f"{key}_res"] = (x["sum"].fillna(0) + SHRINK * own) / (n + SHRINK) - own
        base.loc[n == 0, f"{key}_res"] = np.nan

    # スタート(フライング・出遅れを除く)
    ok_st = s["st"].between(0, 0.5) & s["st_flag"].isna()
    st = s[ok_st].groupby("racer_id")["st"].agg(["mean", "std", "size"])
    base["st_avg"], base["st_sd"], base["st_n"] = st["mean"], st["std"], st["size"].reindex(base.index).fillna(0)
    e = s[ok_st & s["ex_st"].between(0, 0.5)].copy()        # 展示ST → 本番ST
    e["dlt"] = e["st"] - e["ex_st"]
    ex = e.groupby("racer_id")["dlt"].agg(mean="mean", mae=lambda x: x.abs().mean(), n="size")
    base["ex_delta"], base["ex_mae"], base["ex_n"] = ex["mean"], ex["mae"], ex["n"].reindex(base.index).fillna(0)
    base["f_count"] = d[d["st_flag"] == "F"].groupby("racer_id").size().reindex(base.index).fillna(0)

    # 決まり手(1着になったときの決まり手 / そのコースからの出走数、全体の割合に寄せる)
    pri = {}

    def rate(mask_w, mask_n, key):
        w = s[mask_w].groupby("racer_id").size().reindex(base.index).fillna(0)
        n = s[mask_n].groupby("racer_id").size().reindex(base.index).fillna(0)
        pri[key] = float(w.sum() / max(n.sum(), 1))
        base[f"{key}_w"], base[f"{key}_n"] = w, n
        base[key] = _shrunk(w, n, pri[key])
    rate((s["course"] == 1) & (s["kim"] == 1), s["course"] == 1, "nige")
    rate((s["course"] >= 2) & (s["kim"] == 2), s["course"] >= 2, "sashi")
    rate((s["course"] >= 2) & (s["kim"] == 3), s["course"] >= 2, "makuri")
    rate((s["course"] >= 3) & (s["kim"] == 4), s["course"] >= 3, "mz")
    rate((s["course"] >= 2) & s["kim"].isin([3, 4]), s["course"] >= 2, "attack")
    o = s[s["course"] >= 4].groupby("racer_id")["res3"].agg(["sum", "size"]).reindex(base.index)
    base["out_n"] = o["size"].fillna(0)
    base["out_res"] = o["sum"] / (o["size"] + SHRINK)

    cg = s.groupby(["racer_id", "course"]).agg(n=("win", "size"), win=("win", "mean"), top3=("top3", "mean"))
    stc = s[ok_st].groupby(["racer_id", "course"])["st"].mean()
    vg = s.groupby(["racer_id", "jcd"])["res3"].agg(["sum", "size"])
    vg["res"] = (vg["sum"] + SHRINK * own.reindex(vg.index.get_level_values(0)).values) / (vg["size"] + SHRINK) \
        - own.reindex(vg.index.get_level_values(0)).values

    fr = d[d["lane"] >= 2].assign(front=lambda x: (x["course"] < x["lane"]).astype(float)).groupby("racer_id")["front"].agg(["mean", "size"])
    base["front"], base["front_n"] = fr["mean"].reindex(base.index), fr["size"].reindex(base.index).fillna(0)

    own_rel((s["wave"] >= 5) | (s["wind"] >= 5), "rough")              # 荒れ水面
    title = s["race_title"].astype(str)
    semi = s[title.str.contains("準優")][["jcd", "date"]].drop_duplicates()
    semi["date"] = (pd.to_datetime(semi["date"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    kd = set(map(tuple, semi.values.tolist()))
    is_k = title.str.contains("予選") & pd.Series([(j, t) in kd for j, t in zip(s["jcd"], s["date"])], index=s.index)
    own_rel(is_k, "kake")                                                 # 勝負駆け(予選最終日の予選)
    own_rel(title.str.contains("準優|優勝戦"), "big")                     # 大一番
    s["ex_rank"] = s.groupby("race_id")["exhibit_time"].rank(method="min")
    own_rel(s["ex_rank"] >= 4, "exlate")                                  # 展示タイムがレース内4位以下
    xt = s[s["ex_rank"].notna()].assign(t=lambda q: (q["ex_rank"] <= 2).astype(float)).groupby("racer_id")["t"].agg(["mean", "size"])
    base["extop"], base["extop_n"] = xt["mean"].reindex(base.index), xt["size"].reindex(base.index).fillna(0)   # 展示タイム1・2位の割合
    pop_exlate = float(s.loc[s["ex_rank"] >= 4, "res3"].mean() - s.loc[s["ex_rank"].notna(), "res3"].mean())

    a = pd.Timestamp(asof)
    dd = pd.to_datetime(s["date"])
    rec = s[dd > a - pd.Timedelta(days=90)].groupby("racer_id")["pts"].agg(["mean", "size"]).reindex(base.index)
    prv = s[(dd <= a - pd.Timedelta(days=90)) & (dd > a - pd.Timedelta(days=455))].groupby("racer_id")["pts"].agg(["mean", "size"]).reindex(base.index)
    base["pts90"], base["n90"] = rec["mean"], rec["size"].fillna(0)
    base["pts_prev"], base["n_prev"] = prv["mean"], prv["size"].fillna(0)
    base["growth"] = base["pts90"] - base["pts_prev"]

    # パーセンタイル(全選手 / 同じ級別)
    active = pd.to_datetime(base["last"]) > a - pd.Timedelta(days=180)
    pop = base[(base["n"] >= MIN_STARTS) & active]
    cond = {"ex_mae": pop["ex_n"] >= 30, "ex_delta": pop["ex_n"] >= 30, "growth": (pop["n90"] >= 15) & (pop["n_prev"] >= 30),
            "extop": pop["extop_n"] >= 50}
    lower = {"st_avg", "ex_mae"}
    lower.add("ex_delta")
    cols = ["st_avg", "ex_mae", "ex_delta", "nige", "sashi", "makuri", "mz", "attack", "top3", "res3", "front", "out_res", "growth", "pts", "extop"]

    def rank(v, ref, low):
        if ref.empty:
            return pd.Series(np.nan, index=v.index)
        rk = np.searchsorted(np.sort(ref.values), v.values, side="right") / len(ref)
        return pd.Series((1 - rk) * 100 if low else rk * 100, index=v.index).where(v.notna())
    PA, PG = pd.DataFrame(index=base.index), pd.DataFrame(index=base.index)
    for c in cols:
        ref = pop[c] if c not in cond else pop.loc[cond[c], c]
        PA[c] = rank(base[c], ref.dropna(), c in lower)
        PG[c] = np.nan
        for grp in ("A1", "A2", "B"):
            m = base["grp"] == grp
            PG.loc[m, c] = rank(base.loc[m, c], ref[pop.loc[ref.index, "grp"] == grp].dropna(), c in lower)

    by_racer = dict(tuple(d[["racer_id", "date", "rno", "jcd", "finish", "st_flag", "motor_no", "motor_2rate"]].groupby("racer_id")))
    # 準優・優勝戦は相手が強いので、出場する選手はみな普段より上積みが下がる → 出場した選手(15走以上)の平均を基準にする
    pop_big = float(pop.loc[pop["big_n"] >= 15, "big_res"].mean())
    pop_exd = float(pop.loc[pop["ex_n"] >= 30, "ex_delta"].median())
    ctx = {"pop_exlate": pop_exlate, "pop_big": pop_big, "pop_exd": pop_exd}
    cards = {}
    for rid, b in base.iterrows():
        cards[int(rid)] = _card(int(rid), b, PA.loc[rid], PG.loc[rid], cg, stc, vg, by_racer.get(rid), asof, ctx)
    # タグの付き方(少ないタグほど先に出す)
    counts = {}
    for c in cards.values():
        for t in c["tags"]:
            counts[t["t"]] = counts.get(t["t"], 0) + 1
    n_pop = max(len(pop), 1)
    for c in cards.values():
        for t in c["tags"]:
            t["share"] = round(counts[t["t"]] / n_pop, 3)
        c["tags"].sort(key=lambda t: (t["share"], -t["score"]))
    meta = {"asof": asof, "period": [str(d["date"].min()), asof], "pop_racers": int(len(pop)),
            "pop_by_group": {k: int(v) for k, v in pop["grp"].value_counts().items()},
            "pop_course_top3": {int(k): round(float(v), 4) for k, v in pop_c["top3"].items()},
            "pop_course_win": {int(k): round(float(v), 4) for k, v in pop_c["win"].items()},
            "kimarite_prior": {k: round(v, 4) for k, v in pri.items()}, "pop_exlate": round(pop_exlate, 4),
            "pop_big": round(pop_big, 4), "pop_ex_delta": round(pop_exd, 4),
            "rules": [{"tag": t["tag"], "rule": t["rule"]} for t in TAG_RULES] + [{"tag": "(場名)巧者", "rule": VENUE_RULE}],
            "tag_counts": counts}
    return cards, meta


def _f(v, nd=3):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _latest_series(x: pd.DataFrame | None) -> dict | None:
    """最新の節(同じ場で、最後の走から7日以内の走)の着順とモーター。"""
    if x is None or x.empty:
        return None
    x = x.sort_values(["date", "rno"])
    j = x["jcd"].iloc[-1]
    last = pd.Timestamp(x["date"].iloc[-1])
    y = x[(x["jcd"] == j) & (pd.to_datetime(x["date"]) > last - pd.Timedelta(days=7))]
    fin = ["F" if f == "F" else (str(int(v)) if pd.notna(v) else "-") for v, f in zip(y["finish"], y["st_flag"])]
    return {"jcd": int(j), "venue": VENUES.get(int(j), ""), "from": str(y["date"].iloc[0]), "to": str(y["date"].iloc[-1]),
            "finishes": fin, "motor_no": _f(y["motor_no"].iloc[-1], 0), "motor_2rate": _f(y["motor_2rate"].iloc[-1], 1)}


# フライングのあと(scripts/lab.py の flying、2026-10-05): 全選手で、直後10走はSTが平均+0.033秒遅く・3着内率-8ポイント、
# 11〜40走は+0.019秒・-3ポイント、41走目以降はほぼ戻る。慎重さの大きさは同じ選手でも毎回ちがう(1回目と2回目の相関0.10)
F_AFTER = [(10, 0.033, -0.08), (40, 0.019, -0.033)]


def _f_after(x: pd.DataFrame | None, asof: str) -> dict | None:
    """最後のフライングから何走目か(40走以内、180日以内のときだけ)。"""
    if x is None or x.empty:
        return None
    x = x.sort_values(["date", "rno"]).reset_index(drop=True)
    fi = x.index[x["st_flag"] == "F"]
    if not len(fi):
        return None
    k = int(fi[-1])
    since = len(x) - 1 - k
    d0 = str(x.loc[k, "date"])
    if since > 40 or pd.Timestamp(asof) - pd.Timestamp(d0) > pd.Timedelta(days=180):
        return None
    st_d, t3_d = next((a, b_) for n, a, b_ in F_AFTER if since <= n)
    return {"since": since, "date": d0, "st": st_d, "top3": t3_d}


def _card(rid, b, pa, pg, cg, stc, vg, x, asof, ctx) -> dict:
    courses = []
    for c in range(1, 7):
        if (rid, c) in cg.index:
            r = cg.loc[(rid, c)]
            courses.append({"c": c, "n": int(r["n"]), "win": _f(r["win"]), "top3": _f(r["top3"]), "st": _f(stc.get((rid, c)))})
        else:
            courses.append({"c": c, "n": 0, "win": None, "top3": None, "st": None})
    venues = []
    if rid in vg.index.get_level_values(0):
        v = vg.loc[rid]
        for j, r in v[v["size"] >= 15].sort_values("res", ascending=False).head(3).iterrows():
            venues.append({"jcd": int(j), "name": VENUES.get(int(j), ""), "n": int(r["size"]), "res": _f(r["res"])})
    P = lambda k: {"all": _f(pa[k], 0), "grp": _f(pg[k], 0)}  # noqa: E731
    card = {
        "id": rid, "name": b["name"], "class": b["racer_class"], "grp": b["grp"], "branch": b["branch"], "age": _f(b["age"], 0),
        "period": [str(b["first"]), str(b["last"])], "asof": asof,
        "n": int(b["n"]), "win": _f(b["win"]), "top3": _f(b["top3"]), "pts": _f(b["pts"], 2), "res3": _f(b["res3"]),
        "p": {k: P(k) for k in ("top3", "res3", "pts")},
        "st": {"avg": _f(b["st_avg"]), "sd": _f(b["st_sd"]), "n": _i(b["st_n"]), "f": _i(b["f_count"]), **P("st_avg")},
        "ex": {"delta": _f(b["ex_delta"]), "mae": _f(b["ex_mae"]), "n": _i(b["ex_n"]), **P("ex_mae"),
               "d_grp": _f(pg["ex_delta"], 0), "pop_delta": _f(ctx["pop_exd"])},
        "kim": {k: {"w": _i(b[f"{k}_w"]), "n": _i(b[f"{k}_n"]), "rate": _f(b[k]), **P(k)}
                for k in ("nige", "sashi", "makuri", "mz", "attack")},
        "courses": courses, "venues": venues,
        "front": {"rate": _f(b["front"]), "n": _i(b["front_n"]), **P("front")},
        "out": {"res": _f(b["out_res"]), "n": _i(b["out_n"]), **P("out_res")},
        "rough": {"res": _f(b["rough_res"]), "n": _i(b["rough_n"])},
        "kake": {"res": _f(b["kake_res"]), "n": _i(b["kake_n"])},
        "big": {"res": _f(b["big_res"]), "n": _i(b["big_n"]), "pop": _f(ctx["pop_big"])},
        "exlate": {"res": _f(b["exlate_res"]), "n": _i(b["exlate_n"]), "pop": _f(ctx["pop_exlate"])},
        "extime": {"top": _f(b["extop"]), "n": _i(b["extop_n"]), **P("extop")},
        "fafter": _f_after(x, asof),
        "growth": {"pts90": _f(b["pts90"], 2), "n90": _i(b["n90"]), "prev": _f(b["pts_prev"], 2), "n_prev": _i(b["n_prev"]),
                   "diff": _f(b["growth"], 2), "index": _f(GROWTH_KEEP * b["growth"], 2) if pd.notna(b["growth"]) else None, **P("growth")},
        "series": _latest_series(x),
    }
    card["radar"] = {"スタート": _f(pg["st_avg"], 0), "逃げ": _f(pg["nige"], 0), "差し": _f(pg["sashi"], 0),
                     "まくり": _f(pg["attack"], 0), "安定感": _f(pg["res3"], 0), "展示の信頼度": _f(pg["ex_mae"], 0)}
    card["tags"] = tags_for(card)
    return card


# ---------------------------------------------------------------- ひと言タグ
# 条件はカードの数字だけで判定し、根拠の文(why)と基準の文(rule)を残す。けなすタグは作らない。
# 「上位X%」は同じ級別(A1 / A2 / B級)の中での位置(全選手の中だと A1 はどれも上位になって差が出ないため)
def top(p) -> str:
    return f"上位{max(1, round(100 - p))}%"


def grp(c) -> str:
    return GROUP_NAME.get(c.get("grp"), "同級")


def pts(x) -> str:
    return f"{x * 100:+.0f}ポイント"


TAG_RULES = [
    {"tag": "スタート職人", "cat": "start",
     "rule": "平均STが同じ級別の中で上位10%以内(ST記録50走以上)",
     "test": lambda c: c["st"]["n"] >= 50 and (c["st"]["grp"] or 0) >= 90,
     "why": lambda c: f"平均ST {st_fmt(c['st']['avg'])}({grp(c)}の中で{top(c['st']['grp'])}、{c['st']['n']}走)",
     "score": lambda c: c["st"]["grp"]},
    {"tag": "展示STを信じていい", "cat": "ex",
     "rule": "展示STと本番STのずれ(差の絶対値の平均)が同じ級別の中で小さい方から15%以内(30走以上)",
     "test": lambda c: c["ex"]["n"] >= 30 and (c["ex"]["grp"] or 0) >= 85,
     "why": lambda c: f"展示と本番のSTのずれは平均{c['ex']['mae']:.3f}秒({grp(c)}の中で{top(c['ex']['grp'])}の小ささ、{c['ex']['n']}走)",
     "score": lambda c: c["ex"]["grp"]},
    {"tag": "本番で踏み込む", "cat": "ex2",
     "rule": "本番STが展示STからどれだけ遅くなるか(平均)が、同じ級別の中で小さい方から10%以内(30走以上。全選手の中央値は本番の方が約0.05秒遅い)",
     "test": lambda c: c["ex"]["n"] >= 30 and (c["ex"]["d_grp"] or 0) >= 90,
     "why": lambda c: f"本番のSTは展示より平均{c['ex']['delta']:+.2f}秒(全選手の中央値は{c['ex']['pop_delta']:+.2f}秒、{c['ex']['n']}走)",
     "score": lambda c: c["ex"]["d_grp"]},
    {"tag": "イン逃げ番長", "cat": "nige",
     "rule": "1コースの逃げ率(全体の平均に寄せた値)が同じ級別の中で上位10%以内(1コース20走以上)",
     "test": lambda c: c["kim"]["nige"]["n"] >= 20 and (c["kim"]["nige"]["grp"] or 0) >= 90,
     "why": lambda c: f"1コース{c['kim']['nige']['n']}走で{c['kim']['nige']['w']}回逃げ(逃げ率{c['kim']['nige']['w'] / c['kim']['nige']['n']:.0%}、{grp(c)}の中で{top(c['kim']['nige']['grp'])})",
     "score": lambda c: c["kim"]["nige"]["grp"]},
    {"tag": "差し職人", "cat": "sashi",
     "rule": "2コース以遠から差しで勝つ割合が同じ級別の中で上位10%以内(30走以上)",
     "test": lambda c: c["kim"]["sashi"]["n"] >= 30 and (c["kim"]["sashi"]["grp"] or 0) >= 90,
     "why": lambda c: f"2コース以遠{c['kim']['sashi']['n']}走で差し{c['kim']['sashi']['w']}勝({grp(c)}の中で{top(c['kim']['sashi']['grp'])})",
     "score": lambda c: c["kim"]["sashi"]["grp"]},
    {"tag": "まくり屋", "cat": "makuri",
     "rule": "2コース以遠からまくりで勝つ割合が同じ級別の中で上位10%以内(30走以上)",
     "test": lambda c: c["kim"]["makuri"]["n"] >= 30 and (c["kim"]["makuri"]["grp"] or 0) >= 90,
     "why": lambda c: f"2コース以遠{c['kim']['makuri']['n']}走でまくり{c['kim']['makuri']['w']}勝({grp(c)}の中で{top(c['kim']['makuri']['grp'])})",
     "score": lambda c: c["kim"]["makuri"]["grp"]},
    {"tag": "まくり差しの職人", "cat": "mz",
     "rule": "3コース以遠からまくり差しで勝つ割合が同じ級別の中で上位10%以内(30走以上)",
     "test": lambda c: c["kim"]["mz"]["n"] >= 30 and (c["kim"]["mz"]["grp"] or 0) >= 90,
     "why": lambda c: f"3コース以遠{c['kim']['mz']['n']}走でまくり差し{c['kim']['mz']['w']}勝({grp(c)}の中で{top(c['kim']['mz']['grp'])})",
     "score": lambda c: c["kim"]["mz"]["grp"]},
    {"tag": "外からでも届く", "cat": "out",
     "rule": "4〜6コースでの3着内の上積み(コース平均との差)が同じ級別の中で上位10%以内(30走以上)",
     "test": lambda c: c["out"]["n"] >= 30 and (c["out"]["grp"] or 0) >= 90,
     "why": lambda c: f"4〜6コースの3着内率がコース平均より{pts(c['out']['res'])}({c['out']['n']}走、{grp(c)}の中で{top(c['out']['grp'])})",
     "score": lambda c: c["out"]["grp"]},
    {"tag": "前づけの仕掛け人", "cat": "front",
     "rule": "2枠以上のとき、枠より内のコースに入った割合が15%以上(50走以上)",
     "test": lambda c: c["front"]["n"] >= 50 and (c["front"]["rate"] or 0) >= 0.15,
     "why": lambda c: f"2枠以上の{c['front']['n']}走のうち{c['front']['rate']:.0%}で枠より内のコースへ",
     "score": lambda c: 60 + 100 * c["front"]["rate"]},
    {"tag": "展示タイム番長", "cat": "extime",
     "rule": "展示タイムがレース内1・2位になる割合が、同じ級別の中で上位10%以内(展示50走以上)。"
             "展示上位が本番にどれだけ効くかは人によらずほぼ同じ(「展示だけの人」は時期を変えると入れ替わる)",
     "test": lambda c: c["extime"]["n"] >= 50 and (c["extime"]["grp"] or 0) >= 90,
     "why": lambda c: f"展示タイム1・2位が{c['extime']['top']:.0%}({c['extime']['n']}走、{grp(c)}の中で{top(c['extime']['grp'])})",
     "score": lambda c: c["extime"]["grp"]},
    {"tag": "展示は控えめ、本番で化ける", "cat": "exlate",
     "rule": "展示タイムがレース内4位以下の走でも、3着内の上積みが本人の普段とほぼ変わらない(普段との差が全選手の平均より+6ポイント以上良い、30走以上)",
     "test": lambda c: c["exlate"]["n"] >= 30 and c["exlate"]["res"] is not None and c["exlate"]["res"] - (c["exlate"]["pop"] or 0) >= 0.06,
     "why": lambda c: f"展示タイム4位以下の{c['exlate']['n']}走でも、3着内率は普段から{c['exlate']['res'] * 100:+.0f}ポイント(全選手の平均は{(c['exlate']['pop'] or 0) * 100:+.0f}ポイント)",
     "score": lambda c: 60 + 300 * (c["exlate"]["res"] - (c["exlate"]["pop"] or 0))},
    {"tag": "上り調子", "cat": "growth",
     "rule": "直近90日の勝率(1着10点〜6着1点の平均)が、その前の1年より0.8点以上高い(直近15走以上・前の1年30走以上)。26歳以下は「急成長中」",
     "test": lambda c: c["growth"]["n90"] >= 15 and c["growth"]["n_prev"] >= 30 and (c["growth"]["diff"] or 0) >= 0.8,
     "why": lambda c: f"勝率 {c['growth']['prev']:.2f}(前の1年)→ {c['growth']['pts90']:.2f}(直近90日、{c['growth']['n90']}走)。"
                      f"成長指数 {c['growth']['index']:+.2f}(伸びの4割ほどは次の3か月も残る傾向)",
     "score": lambda c: 60 + 20 * c["growth"]["diff"]},
    {"tag": "舟券に絡む安定感", "cat": "stable",
     "rule": "3着内の上積み(コース平均との差)が同じ級別の中で上位5%以内(100走以上)",
     "test": lambda c: c["n"] >= MIN_STARTS and (c["p"]["res3"]["grp"] or 0) >= 95,
     "why": lambda c: f"3着内率 {c['top3']:.0%}、コース平均より{pts(c['res3'])}({c['n']}走、{grp(c)}の中で{top(c['p']['res3']['grp'])})",
     "score": lambda c: c["p"]["res3"]["grp"]},
]
VENUE_RULE = "(使っていない)"

# 型が本物か(scripts/trait_reliability.py、2026-10-05): 同じ選手を奇数月・偶数月に分けたときの相関。
# 0.7 以上はタグにする。0.1 前後以下は偶然の幅が大きいのでタグにしない(カードには「参考」として数字だけ残す)
RELIABILITY = {"展示上位率": 0.93, "スタート": 0.94, "1コースの逃げ": 0.85, "前づけ": 0.97, "展示とのずれ": 0.84, "展示→本番": 0.86, "差し": 0.71,
               "まくり": 0.80, "まくり差し": 0.74, "外から": 0.91, "コースごとの得意": 0.30, "展示が下位": 0.26,
               "節の初戦": 0.10, "大一番": 0.08, "荒れ水面": 0.07, "勝負駆け": 0.05, "場との相性": 0.02, "予選の後半": 0.01}
GROWTH_KEEP = 0.41   # 直近90日の勝率の伸びのうち、次の90日に残る割合(平均。trait_reliability.py の growth)


def tags_for(c: dict) -> list[dict]:
    out = []
    for r in TAG_RULES:
        try:
            if r["test"](c):
                name = r["tag"]
                if name == "上り調子" and (c.get("age") or 99) <= 26:
                    name = "急成長中"
                out.append({"t": name, "cat": r["cat"], "why": r["why"](c), "rule": r["rule"], "score": round(float(r["score"](c)), 1)})
        except (TypeError, KeyError, ZeroDivisionError):
            continue
    return out


def find(cards: dict, key) -> dict | None:
    """登番(数字)か名前(空白は無視)で探す。"""
    k = str(key).strip()
    if k.isdigit():
        return cards.get(int(k))
    k = k.replace(" ", "").replace("　", "")
    return next((c for c in cards.values() if c["name"] == k), None)


def head_to_head(d: pd.DataFrame, ids: list[int], min_meet: int = 6) -> list[dict]:
    """選手同士の対戦成績(同じレースでどちらが先着したか)。どちらも着順がついたレースだけ。"""
    s = d[d["racer_id"].isin(ids) & d["finish"].between(1, 6)][["race_id", "racer_id", "finish"]]
    m = s.merge(s, on="race_id", suffixes=("_a", "_b"))
    m = m[m["racer_id_a"] < m["racer_id_b"]]
    out = []
    for (a, b), g in m.groupby(["racer_id_a", "racer_id_b"]):
        if len(g) >= min_meet:
            wa = int((g["finish_a"] < g["finish_b"]).sum())
            out.append({"a": int(a), "b": int(b), "n": int(len(g)), "a_ahead": wa, "b_ahead": int(len(g) - wa)})
    return sorted(out, key=lambda x: -x["n"])
