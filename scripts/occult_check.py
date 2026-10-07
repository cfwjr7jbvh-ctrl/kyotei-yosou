"""オカルト(よく言われるジンクス)と、場面(優勝戦・準優・選抜など)の違いをデータで確かめる。

- scenes: 場面ごとに「いつもとどう違うか」(1号艇の1着率・平均ST・進入が動いた割合・人気薄で決まった割合・まくりの割合)。予選と比べる
- racer_scene: 大一番での「選手ごとのいつもとの違い」(ST・3着以内)が本物か(奇数月・偶数月の相関)
- occult: 雨の日、最終レース、地元、3-2.5.6-2.5.6、1-2-3
  出目は「人気(オッズ)のわりに来るか」= 実際に来た回数 ÷ オッズから見込まれる回数(控除を除いた市場の確率)で見る(お金の額は出さない)

python scripts/occult_check.py → reports/occult.json
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from kyotei import racer_card as rc  # noqa: E402
from kyotei.data import load_history  # noqa: E402

OUT = ROOT / "reports/occult.json"
PREF = {1: "群馬", 2: "埼玉", 3: "東京", 4: "東京", 5: "東京", 6: "静岡", 7: "愛知", 8: "愛知", 9: "三重", 10: "福井", 11: "滋賀",
        12: "大阪", 13: "兵庫", 14: "徳島", 15: "香川", 16: "岡山", 17: "広島", 18: "山口", 19: "山口", 20: "福岡", 21: "福岡",
        22: "福岡", 23: "佐賀", 24: "長崎"}


def scene_of(t: str) -> str:
    if "準優" in t:          # 「準優勝戦」は「優勝戦」を含むので先に
        return "準優勝戦"
    if "優勝戦" in t:
        return "優勝戦"
    if "ドリーム" in t:
        return "ドリーム戦"
    if "予選" in t:
        return "予選"
    if any(k in t for k in ("選抜", "特選", "特賞")):
        return "選抜・特選"
    return "一般戦ほか"


def boot_diff(x: pd.Series, g: pd.Series, n=400, seed=0) -> list[float]:
    """日ごとにまとめて引き直した差の90%区間(x は 0/1、g はグループのラベル True/False)。"""
    rng = np.random.default_rng(seed)
    a, b = x[g].values, x[~g].values
    out = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)]
    return [round(float(np.quantile(out, 0.05)), 4), round(float(np.quantile(out, 0.95)), 4)]


def main():
    ent, races, odds = load_history()
    ent["race_id"] = ent["race_id"].astype(str)
    races["race_id"] = races["race_id"].astype(str)
    s = ent[ent["finish"].between(1, 6) & ent["course"].between(1, 6)].copy()
    s = s.merge(races[["race_id", "race_title", "weather", "tri_combo", "tri_pop", "kimarite", "rno"]].rename(columns={"rno": "rno_r"}),
                on="race_id", how="left")
    s["scene"] = s["race_title"].astype(str).map(scene_of)
    win = s[s["finish"] == 1].drop_duplicates("race_id").set_index("race_id")
    moved = s.groupby("race_id").apply(lambda g: bool((g["course"] != g["lane"]).any()), include_groups=False)
    st = s[s["st_flag"].isna() | (s["st_flag"] == "")] if "st_flag" in s else s
    st_mean = st.groupby("race_id")["st"].mean()
    R = pd.DataFrame({"scene": win["scene"], "c1": (win["course"] == 1).astype(float), "jcd": win["jcd"],
                      "upset": (pd.to_numeric(win["tri_pop"], errors="coerce") >= 30).astype(float),
                      "makuri": win["kimarite"].isin([3, 4]).astype(float), "rno": win["rno"], "weather": win["weather"],
                      "moved": moved.reindex(win.index).astype(float), "st": st_mean.reindex(win.index)})
    out = {"period": [str(s["date"].min()), str(s["date"].max())], "scenes": {}, "occult": []}
    base = R[R["scene"] == "予選"]
    for sc in ["予選", "選抜・特選", "ドリーム戦", "準優勝戦", "優勝戦", "一般戦ほか"]:
        x = R[R["scene"] == sc]
        out["scenes"][sc] = {"n": int(len(x)), "c1": round(float(x["c1"].mean()), 4), "st": round(float(x["st"].mean()), 4),
                             "moved": round(float(x["moved"].mean()), 4), "upset": round(float(x["upset"].mean()), 4),
                             "makuri": round(float(x["makuri"].mean()), 4),
                             "d_st": round(float(x["st"].mean() - base["st"].mean()), 4)}
        print(sc, out["scenes"][sc])

    # 選手ごとの「大一番でのいつもとの違い」が本物か
    import trait_reliability as tr
    s["half"] = pd.to_datetime(s["date"]).dt.month % 2
    s["big"] = s["scene"].isin(["準優勝戦", "優勝戦"])
    def st_diff(g):
        x = g.dropna(subset=["st"])
        b = x[x["big"]].groupby("racer_id")["st"].agg(["mean", "size"])
        u = x[~x["big"]].groupby("racer_id")["st"].mean()
        b = b[b["size"] >= 8]
        return b["mean"] - u.reindex(b.index)
    out["racer_scene"] = {"st_big": {"label": "準優・優勝戦でのSTのいつもとの差", **tr.corr(st_diff(s[s["half"] == 0]), st_diff(s[s["half"] == 1]))}}
    print("racer_scene", out["racer_scene"])

    # オカルト
    def add(key, belief, val, ref, ci, unit, verdict, note=""):
        out["occult"].append({"key": key, "belief": belief, "value": val, "ref": ref, "ci90": ci, "unit": unit, "verdict": verdict, "note": note})
        print(key, belief, val, ref, ci, verdict)
    # 雨の日(場ごとの差の平均。場ごとに雨の多さが違うため)
    rows = []
    for j, g in R[R["weather"].isin(["雨", "晴", "曇り"])].groupby("jcd"):
        r_ = g[g["weather"] == "雨"]
        if len(r_) >= 50:
            rows.append((len(r_), r_["c1"].mean() - g[g["weather"] != "雨"]["c1"].mean()))
    w = np.array([r[0] for r in rows]); dlt = np.array([r[1] for r in rows])
    d_rain = float((w * dlt).sum() / w.sum())
    rr = R[R["weather"].isin(["雨", "晴", "曇り"])]
    ci = boot_diff(rr["c1"], rr["weather"] == "雨")
    add("rain", "雨の日はインが弱い", round(float(rr[rr["weather"] == "雨"]["c1"].mean()), 4), round(float(rr[rr["weather"] != "雨"]["c1"].mean()), 4),
        ci, "1号艇の1着率", "本当" if d_rain <= -0.01 and ci[1] < 0 else ("逆" if d_rain >= 0.01 and ci[0] > 0 else "ほぼ差なし"),
        f"場ごとの差の平均 {d_rain * 100:+.1f}ポイント")
    # 最終レース
    last = R["rno"] == 12
    ci = boot_diff(R["upset"], last)
    u12, uo = float(R[last]["upset"].mean()), float(R[~last]["upset"].mean())
    add("r12", "最終レース(12R)は荒れる", round(u12, 4), round(uo, 4), ci, "人気薄(3連単30番人気以下)で決まった割合",
        "本当" if ci[0] > 0 else ("逆" if ci[1] < 0 else "ほぼ差なし"), f"1号艇の1着率は12R {R[last]['c1'].mean():.0%}・ほか {R[~last]['c1'].mean():.0%}")
    # 地元
    s["home"] = s["branch"].astype(str) == s["jcd"].map(PREF)
    s["top3"] = (s["finish"] <= 3).astype(float)
    s["res3"] = s["top3"] - s["course"].map(s.groupby("course")["top3"].mean())
    own = s.groupby("racer_id")["res3"].mean()
    hm = s[s["home"]].groupby("racer_id")["res3"].agg(["mean", "size"])
    aw = s[~s["home"]].groupby("racer_id")["res3"].agg(["mean", "size"])
    j = pd.concat([hm, aw], axis=1, keys=["h", "a"]).dropna()
    j = j[(j[("h", "size")] >= 20) & (j[("a", "size")] >= 20)]
    dd = (j[("h", "mean")] - j[("a", "mean")])
    rng = np.random.default_rng(1)
    bt = [float(rng.choice(dd.values, len(dd)).mean()) for _ in range(500)]
    add("home", "地元の選手は強い", round(float(dd.mean()), 4), 0.0, [round(float(np.quantile(bt, 0.05)), 4), round(float(np.quantile(bt, 0.95)), 4)],
        "3着以内率の地元とそれ以外の差(同じ選手で比べる)", "本当(小さい)" if np.quantile(bt, 0.05) > 0 else "ほぼ差なし",
        f"{len(dd)}人。ただし「誰が○○巧者か」は偶然の幅が大きい(相関0.02)")
    # 出目: 人気のわりに来るか(オッズのあるレース)
    if odds is not None:
        o = odds.copy()
        o["race_id"] = o["race_id"].astype(str)
        o = o[o["odds"] > 0]
        o["q"] = 1 / o["odds"]
        o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
        res = races.set_index("race_id")["tri_combo"]
        o = o[o["race_id"].isin(res.index)]
        o["hit"] = (o["combo"] == o["race_id"].map(res)).astype(float)
        nr = o["race_id"].nunique()
        for key, belief, combos in (("3256", "3-2.5.6-2.5.6 は熱い", ["3-%d-%d" % (a, b) for a, b in itertools.permutations([2, 5, 6], 2)]),
                                    ("123", "1-2-3 はよく来る", ["1-2-3"])):
            x = o[o["combo"].isin(combos)]
            hits, expv = float(x["hit"].sum()), float(x["q"].sum())
            bt = []
            ids = x["race_id"].unique()
            g = x.groupby("race_id")[["hit", "q"]].sum()
            for _ in range(400):
                k = g.iloc[rng.integers(0, len(g), len(g))]
                bt.append(float(k["hit"].sum() / k["q"].sum()))
            ratio = hits / expv
            ci = [round(float(np.quantile(bt, 0.05)), 3), round(float(np.quantile(bt, 0.95)), 3)]
            add(key, belief, round(ratio, 3), 1.0, ci, f"人気(オッズ)のわりに来た割合(1.0=人気どおり、{nr:,}レース・{int(hits)}回)",
                "人気どおり" if ci[0] <= 1 <= ci[1] else ("人気のわりに来る" if ci[0] > 1 else "人気のわりに来ない"),
                f"来た割合 {hits / nr:.1%}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
