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
from kyotei.scrape import fetch, fetch_many, parse_beforeinfo, parse_odds3t, parse_pcexpect, parse_raceresult  # noqa: E402
from kyotei.arashi import IN_LOSE_MIN, arashi  # noqa: E402
from kyotei.notify import notify_bets  # noqa: E402
from kyotei.tenkai import scenarios, tenkai, traits  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
DAYS = ROOT / "docs/data/days"
CACHE = ROOT / "data/cache"
VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡",
          8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門",
          15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋",
          22: "福岡", 23: "唐津", 24: "大村"}
EV_MIN, P_MIN, MAX_BETS = 1.0, 0.01, 5  # 期待値(確率×オッズ)が100%以上の組を出す
PICK_MAX = 3  # AIの狙い目(参考): モデルの確率×オッズが100%以上の組を、期待値の高い順に3点まで


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
                 bet_filter=None, s23=None, bet_rule=None):
    rdf = rdf.sort_values("lane")
    w = np.full(6, 1e-6)
    w[rdf["lane"].values - 1] = p_win
    w = w / w.sum()
    s2 = s3 = None
    if s23 is not None:  # 2着・3着の強さ(着順ごとの重み)
        s2, s3 = np.full(6, 1e-9), np.full(6, 1e-9)
        s2[rdf["lane"].values - 1], s3[rdf["lane"].values - 1] = s23
    pm = model_tri_probs(w, stack.lam2, stack.lam3, s2, s3, getattr(stack, "bonus", None))
    p_final, bets, market, pick = pm, [], None, []
    if odds is not None and np.isfinite(odds).sum() >= 100:
        pk = market_probs(odds)
        market = pk
        if blend_ab:
            p_final = blend(pm, pk, *blend_ab)
        p_bet = bet_filter.adjust(p_final, odds, (pk, entropy(w))) if bet_filter else p_final
        bets = select_bets(p_bet, odds, EV_MIN, P_MIN, MAX_BETS)
        if bet_rule:  # 荒れ狙い(追試に合格したときだけ学習が入れる): 1号艇が負けそうなレースだけ、モデルの確率で買う
            bets = select_bets(pm, odds, EV_MIN, P_MIN, MAX_BETS) if 1 - w[0] >= bet_rule["in_lose_min"] else []
        else:
            # AIの狙い目(参考): 合成確率(オッズ寄り)では期待値100%超えがほぼ出ないので、モデルの確率で計算した組を参考に出す。
            # 過去の検証では回収率80%前後(100%未満)。成績は score_day で別に集計し、締切前のオッズでの本当の回収率を確かめる
            pick = select_bets(pm, odds, EV_MIN, P_MIN, PICK_MAX)
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
        boats[-1]["traits"] = traits(b)  # 選手の特性(決まり手の得意度・ST・前づけ・当地・モーターなど)
    # 展開予測: 決まり手の確率と、勝ち筋(誰がどの決まり手で勝つか)
    tk = tenkai([b for _, b in rdf.iterrows()], {int(l): float(w[int(l) - 1]) for l in rdf["lane"]}, stage == "late")
    # 展開シナリオ: 勝ち筋ごとに「その艇が勝つなら2着・3着は誰か」(表示している3連単の確率から)
    tk["scenarios"] = scenarios(p_final, tk["paths"], odds if market is not None else None)
    out = {"race_id": r0["race_id"], "jcd": int(r0["jcd"]), "venue": VENUES.get(int(r0["jcd"]), ""),
           "rno": int(r0["rno"]), "deadline": r0.get("deadline"), "race_type": r0.get("race_type"),
           "stage": stage, "updated_at": now().strftime("%H:%M"), "boats": boats,
           "top": [{"combo": COMBOS[i], "prob": round(float(p_final[i]), 4),
                    **({"odds": float(odds[i])} if odds is not None and np.isfinite(odds[i]) else {})}
                   for i in top],
           "bets": bets, "pick": pick, "tenkai": tk,
           # 荒れ度: 1号艇が負ける確率(各艇の1着確率と同じモデル)と、万舟になる確率(オッズがあれば100倍以上の組の確率)
           "arashi": arashi(w, p_final, odds if market is not None else None)}
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
           "invest": 0, "return": 0, "nerai_races": 0, "nerai_bets": 0, "nerai_hits": 0, "nerai_return": 0,
           "pick_races": 0, "pick_bets": 0, "pick_hits": 0, "pick_return": 0}
    for race in data["races"]:
        r = res.get(race["race_id"])
        if not r or not isinstance(r.get("tri_combo"), str):
            continue
        pay = r.get("tri_pay")
        pay = int(pay) if pay == pay and pay is not None else 0
        kim = (race.get("result") or {}).get("kimarite")  # 当日に取った決まり手は残す
        race["result"] = {"tri_combo": r["tri_combo"], "tri_pay": pay, **({"kimarite": kim} if kim else {})}
        tot["races"] += 1
        tot["top1_hit"] += int(race["top"] and race["top"][0]["combo"] == r["tri_combo"])
        for b in race.get("bets", []) + (race.get("nerai") or []) + (race.get("pick") or []):
            b.pop("hit", None)  # 当日に付けた的中は、確定した結果で付け直す
        for b in race.get("bets", []):
            tot["bets"] += 1
            tot["invest"] += 100
            if b["combo"] == r["tri_combo"]:
                tot["bet_hits"] += 1
                tot["return"] += pay
                b["hit"] = True
        for key in ("nerai", "pick"):  # 荒れ狙い(10/04 で終了)と AIの狙い目(参考)。1点100円で買ったとして集計
            if not race.get(key):
                continue
            tot[f"{key}_races"] += 1
            for b in race[key]:
                tot[f"{key}_bets"] += 1
                if b["combo"] == r["tri_combo"]:
                    tot[f"{key}_hits"] += 1
                    tot[f"{key}_return"] += pay
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


def build_today(day: dt.date):
    """当日の番組表と過去成績から特徴量を作り、直前予想用に data/cache に保存する。番組表が無ければ None。"""
    b = download_text("B", day)
    if not b:
        return None
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
    return df


def merge_live(day: dt.date, prev_path: str):
    """前回までの直前予想(stage=late のレース)を、当日の予想ファイルに重ねる。

    直前予想のファイルは履歴を積み上げないよう live ブランチに上書きで置くので、
    main の朝の予想(作り直されることもある)に、live ブランチの直前予想を重ねてから更新する。
    """
    jp = DAYS / f"{day.isoformat()}.json"
    prev = pathlib.Path(prev_path)
    if not jp.exists() or not prev.exists():
        return
    base, old = read_json(jp), read_json(prev)
    late = {r["race_id"]: r for r in old.get("races", []) if r.get("stage") == "late" or r.get("result")}
    if not late:
        return
    pcx = {r["race_id"]: r["pcx"] for r in old.get("races", []) if r.get("pcx") is not None}  # 公式のコンピュータ予想
    base["races"] = [late.get(r["race_id"], r) for r in base["races"]]
    for r in base["races"]:
        if r.get("pcx") is None and r["race_id"] in pcx:
            r["pcx"] = pcx[r["race_id"]]
    base["updated_at"] = old.get("updated_at", base.get("updated_at"))
    write_json(jp, base)
    print("merged late races:", len(late))


def morning(day: dt.date):
    write_check()
    score_day(day - dt.timedelta(days=1))
    backfill_own(day - dt.timedelta(days=1))
    df = build_today(day)
    if df is None:
        print("番組表がまだありません:", day)
        update_index()
        return
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
LIVE_ODDS = ROOT / "data/odds_live"


def save_live_odds(rows: list[dict]):
    """直前予想のときに取った3連単オッズを保存する(締切前のオッズでの期待値の検証用、改良案 A2・F4)。

    確定オッズは後からでも取れるが、締切前のオッズは今しか取れない。容量を抑えるため、
    レースごとに「締切に一番近い取得」と「一番早い取得」の2回分だけ残す。
    """
    if not rows:
        return
    df = pd.DataFrame(rows)
    LIVE_ODDS.mkdir(parents=True, exist_ok=True)
    for ymd, g in df.groupby(df["race_id"].str[:8]):
        p = LIVE_ODDS / f"live_{ymd}.csv.gz"
        if p.exists():
            g = pd.concat([pd.read_csv(p, dtype={"race_id": str}), g])
        mb = g.groupby("race_id")["min_before"]
        g = g[(g["min_before"] == mb.transform("min")) | (g["min_before"] == mb.transform("max"))]
        g = g.drop_duplicates(["race_id", "min_before", "combo"]).sort_values(["race_id", "min_before", "combo"])
        g.to_csv(p, index=False, compression="gzip")


def save_own_previews(rows: list[dict]):
    """自分たちで取得した直前情報を保存(Open API と同じ列)。同じレースは新しい方で上書き。"""
    if not rows:
        return
    df = pd.DataFrame(rows)
    for ymd, g in df.groupby(df["race_id"].str[:8]):  # 日ごとのファイル(直前予想のループと翌朝の補完がぶつからない)
        p = OWN / f"own_{ymd}.csv.gz"
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
             "water_temp": info.get("water_temp"), "parts": b.get("parts") or "", "propeller": b.get("propeller") or "",
             "source": "own"}
            for lane, b in info.get("boats", {}).items()]


def backfill_own(day: dt.date):
    """直前予想で取り逃したレースの直前情報を、翌朝に公式サイトから補う。"""
    p = DAYS / f"{day.isoformat()}.json"
    if not p.exists():
        return
    data = read_json(p)
    own = OWN / f"own_{day:%Y%m%d}.csv.gz"
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


def attach_results(data: dict, t: dt.datetime, hd: str, limit: int = 40) -> int:
    """締切から6分〜14時間(その日のうち)のレースの結果(3連単・払戻・決まり手)を公式サイトから取り、的中を付ける。
    翌朝の答え合わせ(score_day)を待たずに、現地で結果と的中が見られるようにする。1レースにつき結果が出るまで取りに行く。"""
    cand = []
    for race in data["races"]:
        if race.get("result") or not race.get("deadline"):
            continue
        hh, mm = map(int, race["deadline"].split(":"))
        dl = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dl + dt.timedelta(minutes=6) <= t <= dl + dt.timedelta(hours=14):
            cand.append(race)
    cand = cand[:limit]
    n, got = len(cand), 0
    for race, html in zip(cand, fetch_many([("raceresult", r["jcd"], r["rno"], hd) for r in cand])):
        res = parse_raceresult(html) if html else None
        if not res:
            continue
        race["result"] = res
        got += 1
        for k in ("bets", "nerai", "pick"):
            for b in race.get(k) or []:
                b["hit"] = b["combo"] == res["tri_combo"]
    if n:
        print(f"results: {got}/{n} races")
    return got


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
    odds_rows = []
    updated = []
    # 直前情報(展示)は出そろえば変わらないので、12分以内に取ったものは使い回し、オッズだけ毎回取り直す。
    # 締切が近いレースほど何度も取り直していたため、1周に6〜10分かかっていた
    bi_path = CACHE / f"beforeinfo_{day.isoformat()}.pkl"
    try:
        bi_cache = pickle.loads(bi_path.read_bytes()) if bi_path.exists() else {}
    except Exception:  # noqa: BLE001
        bi_cache = {}
    perf = {"started": t.strftime("%H:%M:%S"), "window": 0, "beforeinfo": 0, "beforeinfo_cached": 0, "odds": 0,
            "sec_fetch": 0.0, "sec_predict": 0.0}
    has_ex = lambda info: any(np.isfinite(b.get("exhibit_time", np.nan)) for b in info.get("boats", {}).values())  # noqa: E731
    # 締切前のレースを選び、必要なページを先にまとめて並行で取る(公式サイトは1ページ約10秒かかる)
    win = []
    for i, race in enumerate(data["races"]):
        if not race.get("deadline"):
            continue
        hh, mm = map(int, race["deadline"].split(":"))
        dl = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t - dt.timedelta(minutes=1) <= dl <= t + dt.timedelta(minutes=ahead_min):
            win.append((i, race, dl))
    perf["window"] = len(win)
    need = [race for _, race, _ in win if not ((c := bi_cache.get(race["race_id"])) and c["complete"]
                                               and (now() - c["at"]).total_seconds() < 12 * 60)]
    perf["beforeinfo"], perf["beforeinfo_cached"] = len(need), len(win) - len(need)
    t1 = time.time()
    for race, html in zip(need, fetch_many([("beforeinfo", r["jcd"], r["rno"], hd) for r in need])):
        info = parse_beforeinfo(html) if html else {"boats": {}}
        bx = info.get("boats", {})
        done = len(bx) >= 5 and all(np.isfinite(b.get("exhibit_time", np.nan)) for b in bx.values())
        bi_cache[race["race_id"]] = {"at": now(), "info": info, "complete": done}
    # 公式のコンピュータ予想(当日の朝に出て変わらない)。締切2時間前からのレースに1回だけ取って付けておく(1周12レースまで)
    try:  # 表示用のおまけなので、失敗しても直前予想の更新は止めない
        pcx_need = []
        for race in data["races"]:
            if race.get("pcx") is not None or race.get("result") or not race.get("deadline"):
                continue
            hh, mm = map(int, race["deadline"].split(":"))
            if t - dt.timedelta(minutes=1) <= t.replace(hour=hh, minute=mm, second=0, microsecond=0) <= t + dt.timedelta(minutes=120):
                pcx_need.append(race)
        pcx_need = sorted(pcx_need, key=lambda r: r["deadline"])[:12]
        for race, html in zip(pcx_need, fetch_many([("pcexpect", r["jcd"], r["rno"], hd) for r in pcx_need])):
            x = parse_pcexpect(html) if html else None
            race["pcx"] = {"marks": x["marks"], "focus3": x["focus3"][:6]} if x else {}
        perf["pcx"] = len(pcx_need)
    except Exception as e:  # noqa: BLE001
        print("pcexpect:", repr(e))
    ready = [race for _, race, _ in win if race["race_id"] in bi_cache and has_ex(bi_cache[race["race_id"]]["info"])]
    odds_html = dict(zip([r["race_id"] for r in ready],
                         fetch_many([("odds3t", r["jcd"], r["rno"], hd) for r in ready])))
    perf["odds"] = len(ready)
    perf["sec_fetch"] = time.time() - t1
    for i, race, dl in win:
        rdf = df[df["race_id"] == race["race_id"]].copy()
        c = bi_cache.get(race["race_id"])
        info = c["info"] if c else {"boats": {}}
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
        rdf["air_temp"], rdf["water_temp"] = info.get("air_temp"), info.get("water_temp")
        rdf["wind_dir"] = info.get("wind_dir_code")
        if wind_tab is not None:
            rdf = features.apply_wind(rdf, wind_tab)
        rdf = features.add_late(rdf)
        oh = odds_html.get(race["race_id"])
        od = parse_odds3t(oh) if oh else {}
        mins = round((dl - now()).total_seconds() / 60, 1)  # 締切まで何分の時点のオッズか
        odds_rows += [{"race_id": race["race_id"], "min_before": mins, "combo": c, "odds": v}
                      for c, v in od.items() if c in COMBOS]
        odds = np.array([od.get(c, np.nan) for c in COMBOS]) if od else None
        t1 = time.time()
        p, stack, s23 = predict_win(bundle, "late", rdf)
        new = race_payload(rdf, p, stack, "late", odds, bundle.get("blend"), bundle.get("bet_filter"), s23=s23,
                           bet_rule=bundle.get("bet_rule"))
        perf["sec_predict"] += time.time() - t1
        # 展示前(朝予想)の1着率を残し、アプリで「展示を見てどう変わったか」を出せるようにする
        before = {b["lane"]: b.get("p_win_early", b.get("p_win") if race.get("stage") != "late" else None)
                  for b in race.get("boats", [])}
        for b in new["boats"]:
            if before.get(b["lane"]) is not None:
                b["p_win_early"] = before[b["lane"]]
        if race.get("pcx") is not None:
            new["pcx"] = race["pcx"]
        data["races"][i] = new
        updated.append(new)
        n += 1
    t1 = time.time()
    perf["results"] = attach_results(data, now(), hd)  # 終わったレースの結果と的中
    perf["sec_results"] = round(time.time() - t1, 1)
    try:
        bi_path.parent.mkdir(parents=True, exist_ok=True)
        bi_path.write_bytes(pickle.dumps(bi_cache))
    except Exception:  # noqa: BLE001
        pass
    data["updated_at"] = t.strftime("%H:%M")
    write_json(jp, data)
    save_own_previews(own_rows)
    save_live_odds(odds_rows)
    # 買い目が出ているレースの数(締切前のもの。中身は書かない)
    upcoming = [r for r in data["races"] if not r.get("result") and r.get("stage") == "late"]
    perf.update({"updated": n, "sec_fetch": round(perf["sec_fetch"], 1), "sec_predict": round(perf["sec_predict"], 1),
                 "sec_total": round((now() - t).total_seconds(), 1),
                 "late_races_open": len(upcoming),
                 "bets_races_open": sum(1 for r in upcoming if r.get("bets")),
                 "bets_open": sum(len(r.get("bets") or []) for r in upcoming),
                 "bets_ev_max": round(max([b["ev"] for r in upcoming for b in r.get("bets") or []] or [0]), 2),
                 "bets_races_today": sum(1 for r in data["races"] if r.get("bets")),
                 "pick_races_open": sum(1 for r in upcoming if r.get("pick"))})
    print("live updated:", n, "races", json.dumps(perf, ensure_ascii=False))
    try:  # 1周の内訳(レース数・取得回数・秒数)。直前予想ループが live ブランチに置く(中身は数字だけ)
        (CACHE / "live_perf.json").write_text(json.dumps(perf, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    notify_bets(day, updated, now(), EV_MIN)  # 新しく出た期待値100%以上の買い目を LINE へ(設定があるときだけ)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    t0 = time.time()
    if mode == "merge-live":  # python scripts/predict.py merge-live 前回の予想ファイル [日付]
        merge_live(dt.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else now().date(), sys.argv[2])
    else:
        day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else now().date()
        {"morning": morning, "live": live, "features": build_today}[mode](day)
    print(f"{time.time()-t0:.0f}s")
