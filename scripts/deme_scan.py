"""出目買いの総当たり検証: 「この条件のとき、この出目(またはフォーメーション)を買い続けたら」の回収率。

公式の結果(全レース、2023-10〜)には3連単の当たり目と払戻金が載っているので、出目を決め打ちで買い続けた
場合の回収率はオッズ表が無くても正確に出せる(オッズを見ずに買う方法なので、後出しにもならない)。

総当たりすると運だけで回収率100%超えの組み合わせが必ず出る。そこで
  発見期間(前半2年)で良かったものが、確認期間(後半1年、発見に使っていない)でも良いか
を見る。確認期間でも100%を超え、日ごとに引き直した90%区間の下限も100%を超えたら「根拠あり」。

python scripts/deme_scan.py [--split 2025-10-01] [--min-hits 20] [--app]
→ reports/deme_scan.json
--app: アプリの「出目の期待値」用の集計 docs/data/deme.json と、ウォッチリストの追跡 reports/deme_watch.json も作る。
  deme.json は公開済みの結果から作る過去の集計だけ(モデルの予想は入らない)なので暗号化しない。
  ウォッチリスト = 2026-10-04 の検証で前半・後半とも回収率100%を超えた買い方。翌日以降のレースだけで成績を数える。
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/deme_scan.json"
APP = ROOT / "docs/data/deme.json"
WATCH = ROOT / "reports/deme_watch.json"
CATS = ["優勝戦", "準優勝戦", "選抜・特選", "予選", "一般", "企画レースなど"]

COMBOS = ["-".join(map(str, p)) for p in itertools.permutations(range(1, 7), 3)]
CIDX = {c: i for i, c in enumerate(COMBOS)}
CIDX.update({f"pop{x}": 119 + x for x in range(1, 121)})  # 120〜239 = 人気順(1〜120番人気)
NCOL = 240
JCD = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑", 9: "津", 10: "三国",
       11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関",
       20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}


def race_cat(t) -> str:
    t = str(t)
    if "準優" in t:
        return "準優勝戦"
    if "優勝戦" in t:
        return "優勝戦"
    if "予選" in t:
        return "予選"
    if "一般" in t:
        return "一般"
    if any(k in t for k in ("選抜", "特選", "特賞", "ドリーム")):
        return "選抜・特選"
    return "企画レースなど"


def strategies() -> list[tuple[str, list[str]]]:
    """買い方の一覧(名前, 3連単の組)。単品120通り + 1着固定のフォーメーション。"""
    out = [(c, [c]) for c in COMBOS]
    for a in range(1, 7):
        rest = [x for x in range(1, 7) if x != a]
        out.append((f"{a}-全-全", [c for c in COMBOS if c[0] == str(a)]))
        for b in rest:  # a-b-全(4点)
            out.append((f"{a}-{b}-全", [c for c in COMBOS if c[0] == str(a) and c[2] == str(b)]))
        for k in (2, 3, 4):  # a-ボックス-ボックス(2/6/12点)
            for s in itertools.combinations(rest, k):
                ss = "".join(map(str, s))
                out.append((f"{a}-{ss}-{ss}", [f"{a}-{x}-{y}" for x, y in itertools.permutations(s, 2)]))
    for s in itertools.combinations(range(1, 7), 3):  # 3連単ボックス(6点)
        out.append(("BOX" + "".join(map(str, s)), ["-".join(map(str, p)) for p in itertools.permutations(s)]))
    # 人気順で買う(最終オッズの人気順。買う時点の人気順とは少しずれるので参考)
    for lo, hi in ((1, 1), (2, 2), (3, 3), (1, 3), (4, 6), (1, 5), (7, 10), (1, 10), (11, 20), (21, 40)):
        out.append((f"人気{lo}" + (f"〜{hi}" if hi > lo else ""), [f"pop{x}" for x in range(lo, hi + 1)]))
    return out


def load() -> pd.DataFrame:
    files = sorted((ROOT / "data/history").glob("races_*.csv.gz"))
    r = pd.concat([pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id", "date", "jcd", "rno", "race_title", "wind", "wave",
                                                                    "tri_combo", "tri_pay", "tri_pop"]) for p in files])
    r = r.dropna(subset=["tri_combo", "tri_pay"])
    r = r[r["tri_combo"].isin(COMBOS)].drop_duplicates("race_id")
    ef = sorted((ROOT / "data/history").glob("entries_*.csv.gz"))
    e = pd.concat([pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id", "lane", "racer_class", "deadline", "day_no",
                                                                    "fixed_entry", "nat_win_rate"]) for p in ef])
    e1 = e[e["lane"] == 1].drop_duplicates("race_id").set_index("race_id")
    a1 = e[e["racer_class"] == "A1"].groupby("race_id").size()
    # 1号艇の勝率が他の5艇の最高と比べてどれだけ上か
    wr = e.pivot_table(index="race_id", columns="lane", values="nat_win_rate", aggfunc="first")
    gap = wr[1] - wr[[2, 3, 4, 5, 6]].max(axis=1)
    r = r.set_index("race_id")
    r["cat"] = r["race_title"].map(race_cat)
    r["venue"] = r["jcd"].map(JCD)
    r["cls1"] = e1["racer_class"].reindex(r.index)
    r["n_a1"] = a1.reindex(r.index).fillna(0).astype(int)
    r["gap1"] = gap.reindex(r.index)
    r["day_no"] = e1["day_no"].reindex(r.index)
    r["fixed"] = e1["fixed_entry"].reindex(r.index)
    dl = e1["deadline"].reindex(r.index).fillna("")
    hh = pd.to_numeric(dl.str.slice(0, 2), errors="coerce")
    r["slot"] = np.select([hh < 12, hh < 15, hh < 17, hh >= 17], ["朝(〜12時)", "昼(12〜15時)", "夕(15〜17時)", "ナイター(17時〜)"], "不明")
    r["ci"] = r["tri_combo"].map(CIDX).astype(int)
    r["pi"] = 119 + r["tri_pop"].fillna(120).clip(1, 120).astype(int)
    return r.reset_index()


def conditions(r: pd.DataFrame) -> list[tuple[str, np.ndarray]]:
    cs = [("全レース", np.ones(len(r), bool))]
    for col, name in (("cat", "種別"), ("venue", "場"), ("slot", "時間帯"), ("cls1", "1号艇")):
        for v in sorted(r[col].dropna().unique()):
            cs.append((f"{name}:{v}", (r[col] == v).values))
    for v in range(1, 13):
        cs.append((f"{v}R", (r["rno"] == v).values))
    for lo, hi, lab in ((0, 2, "風0〜2m"), (3, 4, "風3〜4m"), (5, 99, "風5m以上")):
        cs.append((lab, r["wind"].between(lo, hi).values))
    for lo, hi, lab in ((0, 2, "波0〜2cm"), (3, 5, "波3〜5cm"), (6, 999, "波6cm以上")):
        cs.append((lab, r["wave"].between(lo, hi).values))
    cs.append(("初日", (r["day_no"] == 1).values))
    fin = r.groupby(["jcd", "date"])["cat"].transform(lambda x: (x == "優勝戦").any())  # 優勝戦のある日 = 最終日
    cs.append(("最終日", fin.values.astype(bool)))
    cs.append(("進入固定", (r["fixed"] == 1).values))
    for k, lab in ((0, "A1なし"), (1, "A1が1人"), (2, "A1が2人以上")):
        cs.append((lab, ((r["n_a1"] == k) if k < 2 else (r["n_a1"] >= 2)).values))
    for lo, hi, lab in ((-9, -0.5, "1号艇が勝率で劣る"), (-0.5, 0.5, "1号艇と勝率が互角"), (0.5, 1.5, "1号艇がやや格上"),
                        (1.5, 9, "1号艇が格上")):
        cs.append((lab, r["gap1"].between(lo, hi, inclusive="left").values))
    # 種別 × 1号艇の級別(優勝戦・準優で1号艇がA1か)
    for c in ("優勝戦", "準優勝戦"):
        for v in ("A1", "A2", "B1"):
            cs.append((f"種別:{c}×1号艇:{v}", ((r["cat"] == c) & (r["cls1"] == v)).values))
    return cs


def day_sums(r: pd.DataFrame, mask: np.ndarray, M: np.ndarray, days: np.ndarray, nd: int):
    """条件に合うレースの、日ごと × 買い方ごとの払戻合計とレース数。"""
    sub = r.loc[mask]
    di = days[mask]
    pay = np.zeros((nd, NCOL))
    hits = np.zeros((nd, NCOL))
    for col in ("ci", "pi"):  # 当たった出目の列と、当たった人気順の列の両方に足す(買い方はどちらか一方だけを見る)
        np.add.at(pay, (di, sub[col].values), sub["tri_pay"].values)
        np.add.at(hits, (di, sub[col].values), 1)
    n = np.bincount(di, minlength=nd).astype(float)
    return pay @ M, n, hits @ M  # (日, 買い方)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2025-10-01")
    ap.add_argument("--min-hits", type=int, default=20, help="発見期間でこの本数以上当たっている買い方だけ見る")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--app", action="store_true")
    a = ap.parse_args()
    r = load()
    strat = strategies()
    M = np.zeros((NCOL, len(strat)))
    for j, (_, cs) in enumerate(strat):
        for c in cs:
            M[CIDX[c], j] = 1
    k = M.sum(axis=0)  # 1レースの点数
    udays, days = np.unique(r["date"].values, return_inverse=True)
    nd = len(udays)
    disc_d = udays < a.split
    rng = np.random.default_rng(0)
    W = rng.poisson(1.0, (a.boot, nd)).astype(float)
    conds = conditions(r)
    rows = []
    for cname, mask in conds:
        if mask.sum() < 300:
            continue
        P, n, H = day_sums(r, mask, M, days, nd)
        Pd, nd_, Hd = P[disc_d], n[disc_d], H[disc_d]
        Pc, nc, Hc = P[~disc_d], n[~disc_d], H[~disc_d]
        roi_d = Pd.sum(0) / (nd_.sum() * k * 100)
        roi_c = Pc.sum(0) / (max(nc.sum(), 1) * k * 100)
        hd, hc = Hd.sum(0), Hc.sum(0)
        for j in np.where(hd >= a.min_hits)[0]:
            rows.append({"cond": cname, "strat": strat[j][0], "points": int(k[j]), "races_disc": int(nd_.sum()),
                         "races_conf": int(nc.sum()), "hits_disc": int(hd[j]), "hits_conf": int(hc[j]),
                         "roi_disc": float(roi_d[j]), "roi_conf": float(roi_c[j]), "_mask": cname, "_j": int(j)})
    df = pd.DataFrame(rows)
    n_tests = len(df)
    over_d = df[df["roi_disc"] > 1.0]
    both = over_d[over_d["roi_conf"] > 1.0]
    # 発見期間の上位(回収率順)が確認期間でどうだったか
    top = df.sort_values("roi_disc", ascending=False).head(40).copy()
    # 確認期間の90%区間(日ごとに引き直し)を上位と、両方100%超えのものに付ける
    want = pd.concat([top, both]).drop_duplicates(["cond", "strat"])
    cmask = dict(conds)
    ci = {}
    for (cname, j), _ in want.groupby(["cond", "_j"]):
        P, n, _H = day_sums(r, cmask[cname], M[:, [j]], days, nd)
        Pc, nc = P[~disc_d, 0], n[~disc_d]
        Wc = W[:, ~disc_d]
        bs = (Wc @ Pc) / np.maximum(Wc @ nc, 1) / (k[j] * 100)
        ci[(cname, j)] = [float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]
    for d in (top, both):
        d["conf_ci90"] = [ci.get((c, j)) for c, j in zip(d["cond"], d["_j"])]
    clean = lambda d: d.drop(columns=["_mask", "_j"]).round(4).to_dict("records")  # noqa: E731
    # 発見期間と確認期間の回収率の相関(本当の差があれば、発見期間で良いものは確認期間でも良いはず)
    big = df[df["hits_disc"] >= 50]
    corr = float(np.corrcoef(big["roi_disc"], big["roi_conf"])[0, 1]) if len(big) > 10 else None
    # 発見期間の回収率の帯ごとの、確認期間の平均回収率(回帰の大きさ)
    bands = []
    for lo, hi in ((0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0), (1.0, 1.2), (1.2, 99)):
        g = big[(big["roi_disc"] >= lo) & (big["roi_disc"] < hi)]
        if len(g):
            bands.append({"disc": [lo, hi], "n": int(len(g)), "conf_mean": float(g["roi_conf"].mean()),
                          "conf_over100": float((g["roi_conf"] > 1).mean())})
    passed = [x for x in clean(both) if x["conf_ci90"] and x["conf_ci90"][0] > 1.0]
    # ユーザーの仮説・定番の確認用
    picks = df[df["strat"].isin(["3-256-256", "1-2-3", "1-23-23", "1-234-234", "1-全-全", "2-全-全", "3-全-全", "4-全-全",
                                 "人気1", "人気1〜3", "人気1〜10"])
               & df["cond"].isin(["全レース", "種別:優勝戦", "種別:準優勝戦", "種別:予選", "種別:一般", "種別:選抜・特選"])]
    res = {"split": a.split, "period": [str(r["date"].min()), str(r["date"].max())], "races": int(len(r)),
           "n_conditions": len(conds), "n_strategies": len(strat), "n_tests": int(n_tests),
           "n_over100_disc": int(len(over_d)), "n_over100_both": int(len(both)),
           "corr_disc_conf": corr, "bands": bands, "top_disc": clean(top), "over100_both": clean(both),
           "passed": passed, "checks": clean(picks.sort_values(["strat", "cond"]))}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.app:
        app_export(r, res, strat, M, conds)
    print(f"{len(r)}レース {res['period']} / 条件{len(conds)} × 買い方{len(strat)} → 検定{n_tests}件")
    print(f"発見期間で100%超え {len(over_d)}件 → 確認期間でも100%超え {len(both)}件 → 90%区間の下限も100%超え {len(passed)}件")
    print(f"発見と確認の回収率の相関 {corr}")
    for b in bands:
        print(f"  発見 {b['disc'][0]:.0%}〜{b['disc'][1]:.0%}: {b['n']}件 → 確認の平均 {b['conf_mean']:.0%}(100%超え {b['conf_over100']:.0%})")
    print("発見期間の上位:")
    for x in clean(top)[:25]:
        print(f"  {x['cond']:22s} {x['strat']:10s} {x['points']:2d}点 発見 {x['roi_disc']:.0%}({x['hits_disc']}本) → 確認 {x['roi_conf']:.0%}({x['hits_conf']}本) 区間 {x['conf_ci90']}")
    print("両方100%超え:")
    for x in clean(both):
        print(f"  {x['cond']:22s} {x['strat']:10s} {x['points']:2d}点 発見 {x['roi_disc']:.0%}({x['hits_disc']}本) → 確認 {x['roi_conf']:.0%}({x['hits_conf']}本) 区間 {x['conf_ci90']}")


def app_export(r: pd.DataFrame, res: dict, strat, M, conds):
    """アプリ用: 場×種別、R×種別 ごとに、出目120通りの的中本数と払戻合計(全期間・直近1年)。"""
    last = (pd.Timestamp(r["date"].max()) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    recent = (r["date"] > last).values
    ci = r["ci"].values
    pay = r["tri_pay"].values

    def cell(mask):
        out = {"n": int(mask.sum()), "n1": int((mask & recent).sum())}
        for key, m in (("", mask), ("1", mask & recent)):
            out["h" + key] = np.bincount(ci[m], minlength=120).astype(int).tolist()
            out["p" + key] = (np.bincount(ci[m], weights=pay[m], minlength=120) / 10).round().astype(int).tolist()  # 10円単位
        return out
    cells = {}
    venues = ["all"] + [JCD[j] for j in sorted(JCD)]
    for v in venues:
        mv = np.ones(len(r), bool) if v == "all" else (r["venue"] == v).values
        for c in ["all"] + CATS:
            m = mv if c == "all" else mv & (r["cat"] == c).values
            if m.sum() >= 30:
                cells[f"{v}|{c}|all"] = cell(m)
    for rno in range(1, 13):
        mr = (r["rno"] == rno).values
        for c in ["all"] + CATS:
            m = mr if c == "all" else mr & (r["cat"] == c).values
            if m.sum() >= 30:
                cells[f"all|{c}|{rno}"] = cell(m)
    # ウォッチリスト(初回に固定し、以後は翌日からの成績だけ数え直す)
    if WATCH.exists():
        watch = json.loads(WATCH.read_text(encoding="utf-8"))
    else:
        since = str(r["date"].max())
        watch = {"since": since, "note": "この日までの検証で前半・後半とも回収率100%超え。この日より後のレースだけで数える",
                 "items": [{"cond": x["cond"], "strat": x["strat"], "points": x["points"], "roi_disc": x["roi_disc"],
                            "roi_conf": x["roi_conf"]} for x in res["over100_both"]]}
    cmask = dict(conds)
    sidx = {name: j for j, (name, _) in enumerate(strat)}
    fwd = (r["date"] > watch["since"]).values
    for it in watch["items"]:
        j = sidx[it["strat"]]
        cols = np.where(M[:, j] > 0)[0]
        m = cmask[it["cond"]] & fwd
        hit = np.isin(ci[m], cols) if it["strat"][:2] != "人気" else np.isin(r["pi"].values[m], cols)
        ret = float(pay[m][hit].sum())
        it["fwd"] = {"races": int(m.sum()), "hits": int(hit.sum()), "ret": ret,
                     "roi": ret / (m.sum() * it["points"] * 100) if m.sum() else None}
    WATCH.write_text(json.dumps(watch, ensure_ascii=False, indent=1), encoding="utf-8")
    from kyotei.publish import write_json
    write_json(APP, {"updated": str(r["date"].max()), "period": res["period"], "last_from": last, "cats": CATS,
                     "venues": venues[1:], "cells": cells, "watch": watch,
                     "scan": {k: res[k] for k in ("races", "n_tests", "n_over100_disc", "n_over100_both", "bands")}
                     | {"passed": len(res["passed"])}}, encrypt=False)
    print("app:", len(cells), "cells", f"{APP.stat().st_size / 1e3:.0f}KB", "watch", len(watch["items"]))


if __name__ == "__main__":
    main()
