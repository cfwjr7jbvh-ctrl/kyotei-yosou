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
from kyotei.betting import COMBOS, blend, entropy, market_probs, model_tri_probs, select_bets  # noqa: E402
from kyotei.data import load_history  # noqa: E402
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
    stack = st["stack"]
    return stack.predict(X, probs), stack, stack.strengths(X, probs)


def race_payload(rdf: pd.DataFrame, p_win: np.ndarray, stack, stage: str, odds=None, blend_ab=None,
                 bet_filter=None, s23=None):
    rdf = rdf.sort_values("lane")
    w = np.full(6, 1e-6)
    w[rdf["lane"].values - 1] = p_win
    w = w / w.sum()
    s2 = s3 = None
    if s23 is not None:  # 2着・3着の強さ(着順ごとの重み)
        s2, s3 = np.full(6, 1e-9), np.full(6, 1e-9)
        s2[rdf["lane"].values - 1], s3[rdf["lane"].values - 1] = s23
    pm = model_tri_probs(w, stack.lam2, stack.lam3, s2, s3)
    p_final, bets, market = pm, [], None
    if odds is not None and np.isfinite(odds).sum() >= 100:
        pk = market_probs(odds)
        market = pk
        if blend_ab:
            p_final = blend(pm, pk, *blend_ab)
        p_bet = bet_filter.adjust(p_final, odds, (pk, entropy(w))) if bet_filter else p_final
        bets = select_bets(p_bet, odds, EV_MIN, P_MIN, MAX_BETS)
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
    rp = ROOT / "reports/track.json"  # 見直し用の数字だけの集計(平文)
    rp.parent.mkdir(exist_ok=True)
    rp.write_text(json.dumps(track, ensure_ascii=False, indent=1), encoding="utf-8")


def morning(day: dt.date):
    write_check()
    score_day(day - dt.timedelta(days=1))
    backfill_own(day - dt.timedelta(days=1))
    b = download_text("B", day)
    if not b:
        print("番組表がまだありません:", day)
        update_index()
        return
    today = pd.DataFrame(parse_program(b, day.isoformat()))
    since = (day - dt.timedelta(days=760)).strftime("%Y%m")
    ent, races, _ = load_history(since)
    ent = ent[ent["date"] < day.isoformat()]
    df = features.build(pd.concat([ent, today], ignore_index=True), races)
    wt = features.wind_table(df[df["date"] < day.isoformat()]) if "wind_dir" in df else None
    df = df[df["date"] == day.isoformat()].reset_index(drop=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    if wt is not None:
        wt.to_pickle(CACHE / f"wind_{day.isoformat()}.pkl")
    df.to_pickle(CACHE / f"features_{day.isoformat()}.pkl")
    bundle = load_bundle()
    p, stack, (s2, s3) = predict_win(bundle, "early", df)
    df["p"], df["s2"], df["s3"] = p, s2, s3
    out = {"date": day.isoformat(), "model_built_at": bundle.get("built_at"), "races": []}
    for rid, rdf in df.groupby("race_id", sort=True):
        out["races"].append(race_payload(rdf, rdf["p"].values, stack, "early",
                                         s23=(rdf["s2"].values, rdf["s3"].values)))
    out["races"].sort(key=lambda r: (r["deadline"] or "", r["jcd"]))
    write_json(DAYS / f"{day.isoformat()}.json", out)
    update_index()
    print("morning:", len(out["races"]), "races")


OWN = ROOT / "data/previews"


def save_own_previews(rows: list[dict]):
    """自分たちで取得した直前情報を保存(Open API と同じ列)。同じレースは新しい方で上書き。"""
    if not rows:
        return
    df = pd.DataFrame(rows)
    for ym, g in df.groupby(df["race_id"].str[:6]):
        p = OWN / f"own_{ym}.csv.gz"
        if p.exists():
            old = pd.read_csv(p, dtype={"race_id": str})
            g = pd.concat([old[~old["race_id"].isin(g["race_id"])], g])
        p.parent.mkdir(parents=True, exist_ok=True)
        g.sort_values(["race_id", "lane"]).to_csv(p, index=False, compression="gzip")


def preview_rows(race_id: str, info: dict) -> list[dict]:
    return [{"race_id": race_id, "lane": int(lane), "ex_course": b.get("ex_course"),
             "ex_st": b.get("ex_st"), "ex_time_p": b.get("exhibit_time"),
             "weight_now": b.get("weight_now"), "tilt": b.get("tilt"),
             "wind_dir": info.get("wind_dir_code"), "p_wind": info.get("wind"),
             "p_wave": info.get("wave"), "air_temp": info.get("air_temp"),
             "water_temp": info.get("water_temp"), "source": "own"}
            for lane, b in info.get("boats", {}).items()]


def backfill_own(day: dt.date):
    """直前予想で取り逃したレースの直前情報を、翌朝に公式サイトから補う。"""
    p = DAYS / f"{day.isoformat()}.json"
    if not p.exists():
        return
    data = read_json(p)
    own = OWN / f"own_{day:%Y%m}.csv.gz"
    have = set(pd.read_csv(own, dtype={"race_id": str})["race_id"]) if own.exists() else set()
    rows = []
    for race in data["races"]:
        if race["race_id"] in have:
            continue
        html = fetch("beforeinfo", race["jcd"], race["rno"], day.strftime("%Y%m%d"))
        info = parse_beforeinfo(html) if html else {}
        if info.get("boats"):
            rows += preview_rows(race["race_id"], info)
    save_own_previews(rows)
    print("backfilled previews:", len({r["race_id"] for r in rows}), "races")


def live(day: dt.date, ahead_min: int = 35):
    fp = CACHE / f"features_{day.isoformat()}.pkl"
    jp = DAYS / f"{day.isoformat()}.json"
    if not fp.exists() or not jp.exists():
        print("朝の予想がまだありません")
        return
    df = pd.read_pickle(fp)
    wp = CACHE / f"wind_{day.isoformat()}.pkl"
    wind_tab = pd.read_pickle(wp) if wp.exists() else None
    data = read_json(jp)
    bundle = load_bundle()
    t = now()
    hd = day.strftime("%Y%m%d")
    n = 0
    own_rows = []
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
        own_rows += preview_rows(race["race_id"], info)
        for lane, b in boats.items():
            m = rdf["lane"] == lane
            rdf.loc[m, "exhibit_time"] = b.get("exhibit_time")
            rdf.loc[m, "course"] = b.get("ex_course")
            rdf.loc[m, "ex_st"] = b.get("ex_st")
            rdf.loc[m, "tilt"] = b.get("tilt")
            rdf.loc[m, "weight_now"] = b.get("weight_now")
        rdf["wind"], rdf["wave"] = info.get("wind"), info.get("wave")
        rdf["wind_dir"] = info.get("wind_dir_code")
        if wind_tab is not None:
            rdf = features.apply_wind(rdf, wind_tab)
        rdf = features.add_late(rdf)
        oh = fetch("odds3t", race["jcd"], race["rno"], hd)
        od = parse_odds3t(oh) if oh else {}
        odds = np.array([od.get(c, np.nan) for c in COMBOS]) if od else None
        p, stack, s23 = predict_win(bundle, "late", rdf)
        data["races"][i] = race_payload(rdf, p, stack, "late", odds, bundle.get("blend"),
                                        bundle.get("bet_filter"), s23=s23)
        n += 1
    data["updated_at"] = t.strftime("%H:%M")
    write_json(jp, data)
    save_own_previews(own_rows)
    print("live updated:", n, "races")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else now().date()
    t0 = time.time()
    {"morning": morning, "live": live}[mode](day)
    print(f"{time.time()-t0:.0f}s")
