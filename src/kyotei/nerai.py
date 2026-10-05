"""狙い目の材料: 裏新聞で「枠(コース)が決まったらチェックする」ための集計。

買い目や的中を示すものではなく、出走表が出たときに読者が自分で組み立てるための材料。
- waku_table: 出場選手の、進入したコースごとの成績の上位(1〜4コースは1着率、5・6コースは3着内率)
- best_course: 選手ごとに、同じ級別の平均と比べて一番光るコース(2〜6コース)
- venue_trend: その場の傾向(1コースの強さ、1コース以外が勝つときの決まり手、人気薄で決まった割合)。
  配当の額(万舟など)は使わない(儲けを思わせる表現は避ける。公営競技の広告の指針に自主的に合わせる)。
  グレードレースは出場選手のほぼ全員が A1 なので、「6人中5人以上が A1 のレース」を「トップ級のレース」として別に出す
順位は、回数が少ない選手を同じ級別の平均に寄せた値で付ける(表示するのは実際の回数と率)。
"""
from __future__ import annotations

import pandas as pd

K = 10                 # 回数が少ない選手を級別の平均に寄せる強さ(回数)
UPSET_POP = 10         # 「人気薄で決まった」= 3連単の結果がこの人気順位以下
MIN_N = 8              # 早見表に載せる最低の走数
KIM = {1: "逃げ", 2: "差し", 3: "まくり", 4: "まくり差し", 5: "抜き", 6: "恵まれ"}
METRIC = {1: "win", 2: "win", 3: "win", 4: "win", 5: "top3", 6: "top3"}
METRIC_NAME = {"win": "1着率", "top3": "3着内率"}


def _runs(d: pd.DataFrame) -> pd.DataFrame:
    s = d[d["finish"].between(1, 6)].copy()
    s["win"] = (s["finish"] == 1).astype(float)
    s["top3"] = (s["finish"] <= 3).astype(float)
    s["grp"] = s["racer_class"].map({"A1": "A1", "A2": "A2"}).fillna("B")
    return s


def course_base(d: pd.DataFrame) -> pd.DataFrame:
    """級別 × コースの平均(1着率・3着内率)。index = (grp, course)。"""
    return _runs(d).groupby(["grp", "course"])[["win", "top3"]].mean()


def _shrunk(rate, n, prior):
    return (rate * n + K * prior) / (n + K)


def waku_table(sel: list[dict], base: pd.DataFrame, top: int = 3) -> dict[int, list[dict]]:
    """コースごとの上位。{course: [{id, name, n, k, rate, avg}]}(k は1着か3着内の回数、avg は同じ級別の平均)。"""
    out = {}
    for crs in range(1, 7):
        m = METRIC[crs]
        rows = []
        for c in sel:
            x = c["courses"][crs - 1]
            if x["n"] < MIN_N or x[m] is None:
                continue
            avg = float(base.loc[(c["grp"], crs), m]) if (c["grp"], crs) in base.index else None
            rows.append({"id": c["id"], "name": c["name"], "n": x["n"], "k": round(x[m] * x["n"]), "rate": x[m],
                         "avg": avg, "score": _shrunk(x[m], x["n"], avg if avg is not None else x[m])})
        out[crs] = sorted(rows, key=lambda r: -r["score"])[:top]
    return out


def best_course(c: dict, base: pd.DataFrame, min_diff: float = 0.05) -> dict | None:
    """2〜6コースのうち、同じ級別の平均より3着内率が一番上回るコース(回数が少ないほど平均に寄せる)。"""
    best = None
    for crs in range(2, 7):
        x = c["courses"][crs - 1]
        if x["n"] < 10 or x["top3"] is None or (c["grp"], crs) not in base.index:
            continue
        b = base.loc[(c["grp"], crs)]
        diff = _shrunk(x["top3"], x["n"], float(b["top3"])) - float(b["top3"])
        if diff >= min_diff and (best is None or diff > best["diff"]):
            best = {"c": crs, "n": x["n"], "win": x["win"], "top3": x["top3"], "avg_win": float(b["win"]),
                    "avg_top3": float(b["top3"]), "diff": diff}
    return best


def venue_trend(d: pd.DataFrame, jcd: int) -> dict:
    """その場の傾向と、全国の同じ数字。"""
    s = _runs(d)
    win = s[s["finish"] == 1].drop_duplicates("race_id").set_index("race_id")
    a1 = s.assign(a=(s["racer_class"] == "A1")).groupby("race_id")["a"].sum()
    r = pd.DataFrame({"jcd": win["jcd"], "course": win["course"], "kim": win["kimarite"],
                      "pop": win["tri_pop"] if "tri_pop" in win else pd.NA, "a1": a1.reindex(win.index)})
    r["top_lv"] = r["a1"] >= 5

    def stats(x: pd.DataFrame) -> dict:
        if not len(x):
            return {"n": 0}
        dist = x["course"].value_counts(normalize=True)
        pop = pd.to_numeric(x["pop"], errors="coerce").dropna()
        return {"n": int(len(x)), "c1": float(dist.get(1, 0)), "dist": {int(k): float(dist.get(k, 0)) for k in range(1, 7)},
                "upset": float((pop >= UPSET_POP).mean()) if len(pop) else None}
    v = r[r["jcd"] == jcd]
    non1 = v[(v["course"] > 1) & v["kim"].notna()]["kim"].astype(int).value_counts(normalize=True)
    nat_non1 = r[(r["course"] > 1) & r["kim"].notna()]["kim"].astype(int).value_counts(normalize=True)
    return {"jcd": jcd, "all": stats(v), "top": stats(v[v["top_lv"]]), "nat_all": stats(r), "nat_top": stats(r[r["top_lv"]]),
            "kim_non1": {KIM[k]: float(non1.get(k, 0)) for k in (3, 2, 4, 5)},
            "nat_kim_non1": {KIM[k]: float(nat_non1.get(k, 0)) for k in (3, 2, 4, 5)},
            "period": [str(s["date"].min()), str(s["date"].max())]}


def trend_lines(t: dict, venue: str) -> list[str]:
    """場の傾向を文にする(数字と比べる相手を必ず並べる)。"""
    a, tp, na, nt = t["all"], t["top"], t["nat_all"], t["nat_top"]
    out = []
    if tp.get("n", 0) >= 100:
        out.append(f"1コースの1着率:トップ級のレース(6人中5人以上がA1、{tp['n']}レース)で{tp['c1']:.0%}"
                   f"(全国のトップ級は{nt['c1']:.0%})。{venue}の全レースでは{a['c1']:.0%}")
    elif a.get("n"):
        out.append(f"1コースの1着率:{a['c1']:.0%}(全国は{na['c1']:.0%}、{a['n']}レース)")
    k = sorted(t["kim_non1"].items(), key=lambda x: -x[1])[:3]
    if a.get("n"):
        out.append("1コース以外が勝つときの決まり手:" + "、".join(f"{n}{v:.0%}" for n, v in k)
                   + "(全国は" + "、".join(f"{n}{t['nat_kim_non1'][n]:.0%}" for n, _ in k) + ")")
    ref = tp if tp.get("n", 0) >= 100 and tp.get("upset") is not None else a
    nref = nt if ref is tp else na
    if ref.get("upset") is not None and nref.get("upset") is not None:
        lbl = "トップ級のレースで" if ref is tp else ""
        out.append(f"3連単が{UPSET_POP}番人気以下で決まった割合:{lbl}{ref['upset']:.0%}"
                   f"(全国{'のトップ級' if ref is tp else ''}は{nref['upset']:.0%})")
    return out


def trend_headline(t: dict, venue: str) -> str | None:
    """X やリードに使う、場の傾向のひと言(全国との差がはっきりあるときだけ)。"""
    tp, nt, a, na = t["top"], t["nat_top"], t["all"], t["nat_all"]
    ref, nref, lbl = (tp, nt, "トップ級のレースでも") if tp.get("n", 0) >= 100 else (a, na, "")
    if not ref.get("n"):
        return None
    d = ref["c1"] - nref["c1"]
    if d <= -0.04:
        k = max(t["kim_non1"].items(), key=lambda x: x[1])[0]
        return f"{venue}は{lbl}1コースの1着率が{ref['c1']:.0%}(全国{nref['c1']:.0%})。インが絶対ではない水面で、1コース以外の勝ちは{k}が最多"
    if d >= 0.04:
        return f"{venue}は{lbl}1コースの1着率が{ref['c1']:.0%}(全国{nref['c1']:.0%})。インが強い水面"
    return None
