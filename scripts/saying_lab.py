"""コメントでよく見る「◯号艇の◯◯」「◯◯は◯◯巧者」「◯◯のまくり」は本当か。

同じ選手を2つの期間(月の奇数・偶数)に分け、片方の期間で「上位2割」だった選手(や選手×コース、選手×場の組)が、
もう片方の期間でも上位2割に入るかを数える。偶然なら100人中20人。多いほど「その人の性質」。
あわせて、両方の期間で上位だった有名選手の例(よい面だけ)を出す。

python scripts/saying_lab.py → reports/saying.json(scripts/lab.py の t_saying が読む)
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from kyotei import racer_card as rc  # noqa: E402
import trait_reliability as tr  # noqa: E402

OUT = ROOT / "reports/saying.json"
COURSE_W = {1: "1コース", 2: "2コース", 3: "3コース", 4: "4コース(カド)", 5: "5コース", 6: "6コース"}


def keep_rate(a: pd.Series, b: pd.Series, q: float = 0.8, seed: int = 0) -> dict:
    """a で上位2割 → b でも上位2割の割合(両方向の平均)と、選手を引き直したときの90%の幅。"""
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(j) < 50:
        return {"n": int(len(j))}

    def rate(x):
        ta, tb = x["a"] >= x["a"].quantile(q), x["b"] >= x["b"].quantile(q)
        return float(((ta & tb).sum() / max(ta.sum(), 1) + (ta & tb).sum() / max(tb.sum(), 1)) / 2)
    r = rate(j)
    rng = np.random.default_rng(seed)
    boot = [rate(j.sample(len(j), replace=True, random_state=int(rng.integers(1e9)))) for _ in range(200)]
    return {"n": int(len(j)), "keep": round(r, 4), "lo": round(float(np.quantile(boot, 0.05)), 4),
            "hi": round(float(np.quantile(boot, 0.95)), 4), "chance": round(1 - q, 4)}


def per_racer(g, fn):
    return fn(g)


def main():
    d = rc.load_table()
    s = tr.prep(d)
    s["name"] = d.loc[s.index, "name"] if "name" in d.columns else s["racer_id"].astype(str)
    h = {k: s[s["half"] == k] for k in (0, 1)}
    out = {"split": "月の奇数・偶数", "asof": str(s["date"].max()), "n_starts": int(len(s)), "traits": {}}

    def own(g, key, min_n):
        base = g.groupby("racer_id")["res3"].mean()
        x = g.groupby(["racer_id", key])["res3"].agg(["mean", "size"])
        x = x[x["size"] >= min_n]
        return x["mean"] - base.reindex(x.index.get_level_values(0)).values

    def kim(g, cmask, k, min_n):
        x = g[cmask(g)].assign(w=lambda z: ((z["finish"] == 1) & (z["kimarite"] == k)).astype(float)).groupby("racer_id")["w"].agg(["mean", "size"])
        return x[x["size"] >= min_n]["mean"]

    tests = {
        # その人の強さそのもの
        "st": ("スタートが速い人(平均ST)", lambda g: -g.groupby("racer_id")["st"].agg(["mean", "size"]).query("size >= 40")["mean"]),
        "nige": ("インが強い人(1コースの1着)", lambda g: g[g["course"] == 1].groupby("racer_id")["win"].agg(["mean", "size"]).query("size >= 15")["mean"]),
        "makuri": ("まくり屋(まくりで勝つ割合)", lambda g: kim(g, lambda z: z["course"] >= 2, 3, 15)),
        "sashi": ("差し屋(差しで勝つ割合)", lambda g: kim(g, lambda z: z["course"] >= 2, 2, 15)),
        "out": ("外からでも届く人(4〜6コースの3着以内)", lambda g: g[g["course"] >= 4].groupby("racer_id")["res3"].agg(["mean", "size"]).query("size >= 15")["mean"]),
        "front": ("前づけする人", lambda g: g[g["lane"] >= 2].assign(f=lambda x: (x["course"] < x["lane"]).astype(float)).groupby("racer_id")["f"].agg(["mean", "size"]).query("size >= 40")["mean"]),
        # 「◯号艇の◯◯」「◯◯巧者」(その人のふだんより、どれだけ強いか)
        "course": ("「◯コースの◯◯」(その人のふだんより、そのコースだけ強い)", lambda g: own(g, "course", 10)),
        "venue": ("「◯◯巧者」(その人のふだんより、その場だけ強い)", lambda g: own(g, "jcd", 10)),
        "rough": ("「荒れ水面の◯◯」(その人のふだんより、波や風が強い日だけ強い)", lambda g: tr.own_rel(g, "rough", 12)),
        "big": ("「大一番の◯◯」(その人のふだんより、準優・優勝戦だけ強い)", lambda g: tr.own_rel(g, "big", 8)),
    }
    vals = {}
    for k, (label, fn) in tests.items():
        a, b = fn(h[0]), fn(h[1])
        vals[k] = (a, b)
        out["traits"][k] = {"label": label, **keep_rate(a, b)}
        print(k, out["traits"][k])

    # 有名選手の例: 両方の期間で上位2割に入った A1(よい面だけ)。名前は全部の字
    cls = s.sort_values("date").groupby("racer_id")["racer_class"].last()
    names = s.groupby("racer_id")["name"].last()
    starts = s.groupby("racer_id").size()
    ex = {}
    for k in ("nige", "makuri", "sashi", "out", "front", "st"):
        a, b = vals[k]
        j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
        top = j[(j["a"] >= j["a"].quantile(0.8)) & (j["b"] >= j["b"].quantile(0.8))]
        top = top[top.index.map(lambda i: cls.get(i) == "A1")]
        top = top.assign(m=(top["a"] + top["b"]) / 2, n=top.index.map(starts)).sort_values("m", ascending=False)
        ex[k] = [names[i] for i in top.index[:6]]
    # 「◯コースの◯◯」で、両方の期間とも上位だった組(A1、各期間20走以上)
    a, b = vals["course"]
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    cnt = s.groupby(["racer_id", "course"]).size()
    j = j[[cnt.get(i, 0) >= 40 for i in j.index]]
    top = j[(j["a"] >= j["a"].quantile(0.9)) & (j["b"] >= j["b"].quantile(0.9))]
    top = top[[cls.get(i[0]) == "A1" for i in top.index]]
    top = top.assign(m=(top["a"] + top["b"]) / 2).sort_values("m", ascending=False)
    ex["course"] = [f"{COURSE_W[int(c)]}の{names[r]}" for r, c in top.index[:8]]
    out["traits"]["course"]["pairs_both_top10"] = int(len(top))
    out["examples"] = ex

    # 峰竜太(4320)のコースごと(その人のふだんより、100走あたり何回多いか。2つの期間)
    me = {}
    for c in range(1, 7):
        r_ = []
        for g in (h[0], h[1]):
            x = g[g["racer_id"] == 4320]
            base = x["res3"].mean()
            y = x[x["course"] == c]
            r_.append([round(float((y["res3"].mean() - base) * 100), 1) if len(y) else None, int(len(y))])
        me[str(c)] = r_
    out["mine"] = {"id": 4320, "name": names.get(4320), "course": me}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["examples"], ensure_ascii=False), json.dumps(out["mine"], ensure_ascii=False))


if __name__ == "__main__":
    main()
