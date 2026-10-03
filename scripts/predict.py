"""毎日の予想を作ってサイト用JSONに書き出す。

  python scripts/predict.py morning   # 当日の番組表から朝予想+前日の答え合わせ
  python scripts/predict.py live      # 締切が近いレースを直前情報・オッズで更新

出力: docs/data/days/YYYY-MM-DD.json, docs/data/index.json, docs/data/track.json
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_history import download_text  # noqa: E402
from kyotei import features  # noqa: E402
from kyotei.betting import COMBOS, blend, market_probs, model_tri_probs, select_bets  # noqa: E402
from kyotei.parse_lzh import parse_program, parse_result  # noqa: E402
from kyotei.publish import read_json, write_check, write_json  # noqa: E402
from kyotei.scrape import fetch, parse_beforeinfo, parse_odds3t  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
DAYS = ROOT / "docs/data/days"
CACHE = ROOT / "data/cache"
VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡",
          8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門",
          15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋",
          22: "福岡", 23: "唐津", 24: "大村"}
EV_MIN, P_MIN, MAX_BETS = 1.2, 0.01, 5


def now():
    return dt.datetime.now(JST)


def load_bundle():
    with open(ROOT / "models/bundle.pkl", "rb") as f:
        return pickle.load(f)


def predict_win(bundle, stage, df):
    st = bundle["stages"][stage]
    X = df.copy()
    for c in st["feats"]:
        if c not in X:
            X[c] = np.nan
    probs = {k: m.predict_proba(X) for k, m in st["models"].items()}
    return st["stack"].predict(X, probs), st["stack"]


def race_payload(rdf: pd.DataFrame, p_win: np.ndarray, stack, stage: str, odds=None, blend_ab=None):
    rdf = rdf.sort_values("lane")
    w = np.full(6, 1e-6)
    w[rdf["lane"].values - 1] = p_win
    w = w / w.sum()
    pm = model_tri_probs(w, stack.lam2, stack.lam3)
    p_final, bets, market = pm, [], None
    if odds is not None and np.isfinite(odds).sum() >= 100:
        pk = market_probs(odds)
        market = pk
        if blend_ab:
            p_final = blend(pm, pk, *blend_ab)
        bets = select_bets(p_final, odds, EV_MIN, P_MIN, MAX_BETS)
    top = np.argsort(-p_final)[:10]
    r0 = rdf.iloc[0]
    boats = []
    for _, b in rdf.iterrows():
        boats.append({k: (None if pd.isna(v) else v) for k, v in {
            "lane": int(b["lane"]), "name": b.get("racer_name"), "class": b.get("racer_class"),
            "racer_id": int(b["racer_id"]), "age": b.get("age"), "branch": b.get("branch"),
            "nat_win_rate": b.get("nat_win_rate"), "loc_win_rate": b.get("loc_win_rate"),
            "motor_2rate": b.get("motor_2rate"), "exhibit_time": b.get("exhibit_time"),
            "course": b.get("course"), "ex_st": b.get("ex_st"),
            "p_win": round(float(w[int(b["lane"]) - 1]), 4)}.items()})
    out = {"race_id": r0["race_id"], "jcd": int(r0["jcd"]), "venue": VENUES.get(int(r0["jcd"]), ""),
           "rno": int(r0["rno"]), "deadline": r0.get("deadline"), "race_type": r0.get("race_type"),
           "stage": stage, "updated_at": now().strftime("%H:%M"), "boats": boats,
           "top": [{"combo": COMBOS[i], "prob": round(float(p_final[i]), 4),
                    **({"odds": float(odds[i])} if odds is not None and np.isfinite(odds[i]) else {})}
                   for i in top],
           "bets": bets}
    if market is not None:
        out["market_top"] = [{"combo": COMBOS[i], "prob": round(float(market[i]), 4)}
                             for i in np.argsort(-market)[:3]]
    return out


def update_index():
    days = sorted(p.stem for p in DAYS.glob("*.json"))
    write_json(ROOT / "docs/data/index.json", {"days": days[-60:], "latest": days[-1] if days else None},
               encrypt=False)


def score_day(day: dt.date):
    """前日の予想に結果を付けて、成績を集計する。"""
    p = DAYS / f"{day.isoformat()}.json"
    if not p.exists():
        return
    data = read_json(p)
    k = download_text("K", day)
    if not k:
        return
    _, races = parse_result(k, day.isoformat())
    res = {r["race_id"]: r for r in races}
    tot = {"date": day.isoformat(), "races": 0, "top1_hit": 0, "bets": 0, "bet_hits": 0,
           "invest": 0, "return": 0}
    for race in data["races"]:
        r = res.get(race["race_id"])
        if not r or not isinstance(r.get("tri_combo"), str):
            continue
        pay = r.get("tri_pay")
        pay = int(pay) if pay == pay and pay is not None else 0
        race["result"] = {"tri_combo": r["tri_combo"], "tri_pay": pay}
        tot["races"] += 1
        tot["top1_hit"] += int(race["top"] and race["top"][0]["combo"] == r["tri_combo"])
        for b in race.get("bets", []):
            tot["bets"] += 1
            tot["invest"] += 100
            if b["combo"] == r["tri_combo"]:
                tot["bet_hits"] += 1
                tot["return"] += pay
                b["hit"] = True
    data["summary"] = tot
    write_json(p, data)
    tp = ROOT / "docs/data/track.json"
    track = read_json(tp) if tp.exists() else {"days": []}
    track["days"] = [d for d in track["days"] if d["date"] != tot["date"]] + [tot]
    track["days"].sort(key=lambda d: d["date"])
    write_json(tp, track)


def morning(day: dt.date):
    write_check()
    score_day(day - dt.timedelta(days=1))
    b = download_text("B", day)
    if not b:
        print("番組表がまだありません:", day)
        update_index()
        return
    today = pd.DataFrame(parse_program(b, day.isoformat()))
    H = ROOT / "data/history"
    since = (day - dt.timedelta(days=760)).strftime("%Y%m")
    ent = pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in sorted(H.glob("entries_*.csv.gz"))
                     if p.stem.split("_")[1] >= since])
    races = pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in sorted(H.glob("races_*.csv.gz"))
                       if p.stem.split("_")[1] >= since])
    ent = ent[ent["date"] < day.isoformat()]
    df = features.build(pd.concat([ent, today], ignore_index=True), races)
    df = df[df["date"] == day.isoformat()].reset_index(drop=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_pickle(CACHE / f"features_{day.isoformat()}.pkl")
    bundle = load_bundle()
    p, stack = predict_win(bundle, "early", df)
    df["p"] = p
    out = {"date": day.isoformat(), "model_built_at": bundle.get("built_at"), "races": []}
    for rid, rdf in df.groupby("race_id", sort=True):
        out["races"].append(race_payload(rdf, rdf["p"].values, stack, "early"))
    out["races"].sort(key=lambda r: (r["deadline"] or "", r["jcd"]))
    write_json(DAYS / f"{day.isoformat()}.json", out)
    update_index()
    print("morning:", len(out["races"]), "races")


def live(day: dt.date, ahead_min: int = 35):
    fp = CACHE / f"features_{day.isoformat()}.pkl"
    jp = DAYS / f"{day.isoformat()}.json"
    if not fp.exists() or not jp.exists():
        print("朝の予想がまだありません")
        return
    df = pd.read_pickle(fp)
    data = read_json(jp)
    bundle = load_bundle()
    t = now()
    hd = day.strftime("%Y%m%d")
    n = 0
    for i, race in enumerate(data["races"]):
        if not race.get("deadline"):
            continue
        hh, mm = map(int, race["deadline"].split(":"))
        dl = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (t - dt.timedelta(minutes=1) <= dl <= t + dt.timedelta(minutes=ahead_min)):
            continue
        rdf = df[df["race_id"] == race["race_id"]].copy()
        html = fetch("beforeinfo", race["jcd"], race["rno"], hd)
        info = parse_beforeinfo(html) if html else {"boats": {}}
        boats = info.get("boats", {})
        if not boats or all(not np.isfinite(b.get("exhibit_time", np.nan)) for b in boats.values()):
            continue  # 展示前
        for lane, b in boats.items():
            m = rdf["lane"] == lane
            rdf.loc[m, "exhibit_time"] = b.get("exhibit_time")
            rdf.loc[m, "course"] = b.get("ex_course")
            rdf.loc[m, "ex_st"] = b.get("ex_st")
        rdf["wind"], rdf["wave"] = info.get("wind"), info.get("wave")
        rdf = features.add_late(rdf)
        oh = fetch("odds3t", race["jcd"], race["rno"], hd)
        od = parse_odds3t(oh) if oh else {}
        odds = np.array([od.get(c, np.nan) for c in COMBOS]) if od else None
        p, stack = predict_win(bundle, "late", rdf)
        data["races"][i] = race_payload(rdf, p, stack, "late", odds, bundle.get("blend"))
        n += 1
    data["updated_at"] = t.strftime("%H:%M")
    write_json(jp, data)
    print("live updated:", n, "races")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else now().date()
    t0 = time.time()
    {"morning": morning, "live": live}[mode](day)
    print(f"{time.time()-t0:.0f}s")
