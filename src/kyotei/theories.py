"""出走表に「理論」をぶつける(毎日のレースカードと記事の『理論ぶつけ』)。

買い目は出さない。レースごとに、検証ラボで確かめた理論のうち当てはまるものを並べ、
「データで本物」「人気どおり」「オカルト枠」などの札をつける。数字は reports/lab/*.json(毎週更新)から読むので、
記事と食い違わない。

各ノートの形:
  {"id": 理論の id, "title": 見出し, "lanes": [関係する枠], "text": 説明(数字つき), "badge": 札, "kind": real/known/edge/occult/trial/info,
   "dir": 1号艇への向き(+1=インに有利、-1=インに不利、0=どちらでもない), "lab": 検証ラボの記事 id, "gen": ゲンさんのひと言 or None}
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
from functools import lru_cache

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB = ROOT / "reports/lab"
VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ",
          12: "住之江", 13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋", 22: "福岡",
          23: "唐津", 24: "大村"}
VENUE_PREF = {1: "群馬", 2: "埼玉", 3: "東京", 4: "東京", 5: "東京", 6: "静岡", 7: "愛知", 8: "愛知", 9: "三重", 10: "福井", 11: "滋賀", 12: "大阪",
              13: "兵庫", 14: "徳島", 15: "香川", 16: "岡山", 17: "広島", 18: "山口", 19: "山口", 20: "福岡", 21: "福岡", 22: "福岡", 23: "佐賀", 24: "長崎"}


# ---------------------------------------------------------------- 検証ラボの数字
@lru_cache(maxsize=None)
def _lab(tid: str) -> dict:
    p = LAB / f"{tid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _m(tid: str, i: int):
    """(measure, verdicts) を返す。無ければ (None, None)。"""
    ms = _lab(tid).get("measures") or []
    if i >= len(ms):
        return None, None
    return ms[i][1], ms[i][2]


def _n(v, per=100):
    if v is None or v != v:
        return "-"
    x = v * per
    return f"{x:.1f}" if x < 10 else f"{round(x)}"


def _cnt(m, per=100):
    """「100レースで23回(ふだん9.5回)」"""
    if not m:
        return ""
    return f"{_n(m['in1'], per)}回(ふだん{_n(m['in1_ref'], per)}回)"


def _badge(v, occult=False):
    """札。人気(オッズ)との関係を優先して1つに。"""
    if occult:
        return "オカルト枠", "occult"
    if not v:
        return "参考", "info"
    known = v.get("known") or ""
    if "追試中" in known:
        return "データで本物・人気以上かは追試中", "trial"
    if v.get("edge") == 1:
        return "データで本物・人気以上に来る", "edge"
    if v.get("edge") == -1:
        return "データで本物・人気のわりにひかえめ", "edge"
    if v.get("real") and v.get("edge") == 0:
        return "データで本物・人気どおり", "known"
    if v.get("real"):
        return "データで本物", "real"
    return "差は小さい", "info"


def _note(tid, title, lanes, text, v=None, dir_=0, occult=False, gen=None, force=False):
    """データで差が小さい理論は出さない(force=True の情報だけは出す)。"""
    if v is not None and not v.get("real") and not occult and not force:
        return None
    b, k = _badge(v, occult)
    return {"id": tid, "title": title, "lanes": [int(x) for x in lanes], "text": text, "badge": b, "kind": k, "dir": int(dir_), "lab": tid,
            "lab_title": _lab(tid).get("title"), "gen": gen}


# ---------------------------------------------------------------- 日・場の情報
def _rokuyo(day: dt.date) -> str | None:
    try:
        from .koyomi import rokuyo
        return rokuyo(day)
    except Exception:  # noqa: BLE001
        return None


def _moon_age(day: dt.date) -> float:
    t = (dt.datetime(day.year, day.month, day.day, 12) - dt.datetime(2000, 1, 6, 18, 14)).total_seconds() / 86400
    return t % 29.530589


def forecast_wind(day: dt.date) -> dict:
    """{(jcd, 時): 風速 m/s}。天気予報(data/weather/forecast_YYYYMM)の最新の取得分。"""
    f = ROOT / f"data/weather/forecast_{day.strftime('%Y%m')}.csv.gz"
    if not f.exists():
        return {}
    try:
        w = pd.read_csv(f)
    except Exception:  # noqa: BLE001
        return {}
    w = w[w["time"].astype(str).str.startswith(day.isoformat())]
    if w.empty:
        return {}
    w = w.sort_values("fetched").drop_duplicates(["jcd", "time"], keep="last")
    hum = "relative_humidity_2m" in w
    out = {}
    for q in w.itertuples():
        h = int(str(q.time)[11:13])
        out[(int(q.jcd), h)] = (float(q.wind_speed_10m), float(getattr(q, "relative_humidity_2m")) if hum else None)
    return out


def accident_table(ent: pd.DataFrame, day: dt.date) -> dict:
    """{racer_id: (今期の事故率の目安, 期末までの日数)}。検証ラボ penalty と同じ数え方(その日より前の成績から)。"""
    if ent is None or ent.empty or "result_code" not in ent:
        return {}
    mo, yr = day.month, day.year
    if 5 <= mo <= 10:
        start, end = dt.date(yr, 5, 1), dt.date(yr, 10, 31)
    elif mo >= 11:
        start, end = dt.date(yr, 11, 1), dt.date(yr + 1, 4, 30)
    else:
        start, end = dt.date(yr - 1, 11, 1), dt.date(yr, 4, 30)
    e = ent[(ent["date"] >= start.isoformat()) & (ent["date"] < day.isoformat())]
    rc = e["result_code"].astype(str)
    pts = rc.map({"F": 20, "L1": 20, "K1": 10, "S1": 10, "S2": 15}).fillna(0)
    cnt = rc.isin(["01", "02", "03", "04", "05", "06", "F", "L1", "K1", "S1", "S2"]).astype(float)
    g = pd.DataFrame({"r": e["racer_id"], "p": pts, "c": cnt}).groupby("r").sum()
    g = g[g["c"] >= 20]
    left = (end - day).days
    return {int(k): (float(v.p / v.c), left) for k, v in g.iterrows()}


# ---------------------------------------------------------------- 理論のチェック
def _last2(s) -> list[str]:
    """今節成績の文字列('3 114 66')から、直前の2走。"""
    if not isinstance(s, str):
        return []
    ch = [c for c in s if not c.isspace()]
    return ch[-2:] if len(ch) >= 2 else []


def race_theories(rdf: pd.DataFrame, ctx: dict | None = None) -> list[dict]:
    """1レース(6行)に当てはまる理論のノート。ctx: day(date), acc(dict), wind(dict), late(bool), twice(dict racer_id→何走目)"""
    ctx = ctx or {}
    r = rdf.sort_values("lane").set_index("lane", drop=False)
    if r.empty:
        return []
    r0 = r.iloc[0]
    day = ctx.get("day") or dt.date.fromisoformat(str(r0.get("date"))[:10])
    late = bool(ctx.get("late"))
    jcd, rno = int(r0["jcd"]), int(r0["rno"])
    g = lambda lane, col: (r.at[lane, col] if lane in r.index and col in r.columns else np.nan)  # noqa: E731
    notes = []

    # --- レースの種類
    rt = str(r0.get("race_type") or "")
    if "優勝戦" in rt and "準" not in rt:
        m, v = _m("final", 1)
        notes.append(_note("final", "優勝戦", [1], f"優勝戦の1号艇は100レースで{_n(m['in1']) if m else '-'}回勝つ(予選は{_n(m['in1_ref']) if m else '-'}回)。大一番はスタートをむしろ攻める(STはふだんより早く、Fも多い)", v, +1))
    elif "準優" in rt:
        m, v = _m("final", 0)
        notes.append(_note("final", "準優勝戦", [1], f"準優の1号艇は100レースで{_n(m['in1']) if m else '-'}回勝つ(予選は{_n(m['in1_ref']) if m else '-'}回)。1着・2着が優勝戦へ。『2着でいい走り』は数字には出ない", v, +1))
    for kw, i in (("特別選抜", 0), ("ドリーム", 1)):
        if kw in rt:
            m, v = _m("kikaku", i)
            if m:
                notes.append(_note("kikaku", f"企画レース({kw}戦)", [1], f"{kw}戦の1号艇は100レースで{_n(m['in1'])}回勝つ(全レースは{_n(m['in1_ref'])}回)。" + ("" if "追試中" in (v.get("known") or "") else "堅いことは、みんな知っている"), v, +1))
    if int(r0.get("fixed_entry") or 0) == 1:
        m, v = _m("fixed", 1)
        notes.append(_note("fixed", "進入固定", [1], f"前づけができないので1号艇は助走を十分にとれる。力の差が同じくらいでも1号艇が{_cnt(m)}勝つ", v, +1))

    # --- 番組の癖(場×レース番号)
    bg = _lab("bangumi")
    for ti, sign in ((0, +1), (1, -1)):
        tbl = (bg.get("tables") or [[None, []], [None, []]])[ti][1]
        for x in tbl:
            if x.get("venue") == VENUES.get(jcd) and int(x.get("rno") or 0) == rno:
                notes.append(_note("bangumi", "番組の癖: " + ("インが堅い枠" if sign > 0 else "インが荒れる枠"), [1],
                                   f"{VENUES.get(jcd)}{rno}Rは、1号艇が100レースで{_n(x['in1'])}回勝つ枠(全国の場×レース番号で{'上位' if sign > 0 else '下位'}8つ)。毎年ほぼ同じ顔ぶれ",
                                   _m("bangumi", ti)[1], sign))

    # --- カドの一撃
    st = {k: g(k, "rc_avgst") for k in range(1, 5)}
    if all(st[k] == st[k] for k in range(1, 5)):
        gap = st[4] - min(st[1], st[2], st[3])
        if gap <= -0.02:
            m, v = _m("slowdash", 0)
            exn = None
            if late and "course" in r.columns:
                exn = all(int(g(k, "course")) == k for k in range(1, 7) if k in r.index and g(k, "course") == g(k, "course"))
            if exn is not False:
                notes.append(_note("slowdash", "カドの一撃", [4],
                                   f"4号艇がカドに入れば、ふだんのSTが内の3人より{abs(gap):.2f}秒速い。この形だとカドの1着は100レースで{_cnt(m)}",
                                   v, -1, gen="4カドのまくりこそ競艇の華よ!"))

    # --- 1号艇: 隠れA2
    if str(g(1, "racer_class")) == "B1" and g(1, "rc_avgst") <= 0.15 and g(1, "nige_rate") >= 0.55:
        m, v = _m("a1in", 3)
        notes.append(_note("a1in", "隠れA2の1号艇", [1], f"B1でも、スタートが速く1コースで勝ってきた人。この形の1号艇は100レースで{_cnt(m)}", v, +1))

    # --- 選手ごと
    acc = ctx.get("acc") or {}
    twice = ctx.get("twice") or {}
    for lane in r.index:
        q = r.loc[lane]
        from .racer_card import full_name
        nm = str(full_name(q.get("racer_id"), q.get("racer_name")) or "").replace("　", "")
        who = f"{lane}号艇{(' ' + nm) if nm else ''}"
        wl = f"{lane}号艇"   # 不利な方向の話は名前を出さない(選手をけなす書き方を避ける)
        l2 = _last2(q.get("series_str"))
        if l2 == ["1", "1"]:
            m, v = _m("hot", 0)
            notes.append(_note("hot", "今節2連勝中", [lane], f"{who}は今節2連勝中。こういう選手は3着以内が100走で{_cnt(m)}", v, +1 if lane == 1 else 0))
        elif len(l2) == 2 and all(c in "56" for c in l2):
            m, v = _m("hot", 2)
            notes.append(_note("hot", "2走続けて5・6着", [lane], f"{wl}は今節2走続けて5・6着。こういうときの次のレースは、3着以内が100走で{_cnt(m)}", v, -1 if lane == 1 else 0))
        fs = q.get("f_since")
        if fs == fs and fs is not None and fs <= 10:
            m, v = _m("flying", 0)
            notes.append(_note("flying", "フライング直後", [lane], f"{wl}は最後のフライングから{int(fs)}走目。F直後の10走はスタートが控えめ。3着以内は100走で{_cnt(m)}", v, -1 if lane == 1 else 0))
        rd = q.get("rest_days")
        if rd == rd and rd is not None and rd >= 30:
            m, v = _m("rest", 1 if rd >= 90 else 0)
            notes.append(_note("rest", "休み明け", [lane], f"{wl}は{int(rd)}日ぶりのレース。休み明けは3着以内が100走で{_cnt(m)}", v, -1 if lane == 1 else 0))
        a = acc.get(int(q.get("racer_id") or 0))
        if a and a[1] <= 42 and a[0] >= 0.5:
            m, v = _m("penalty", 0)
            notes.append(_note("penalty", "期末の事故率", [lane], f"{wl}は今期の事故率の目安が{a[0]:.2f}(0.70を超えるとB2級)。期末はスタートを控えめにしやすい。3着以内は100走で{_cnt(m)}",
                               v, -1 if lane == 1 else 0))
        ma = q.get("motor_age")
        if lane == 1 and ma == ma and ma is not None and ma <= 14:
            m, v = _m("newmotor", 0)
            notes.append(_note("newmotor", "新モーター2週間以内", list(r.index), f"この場は新モーターになって{int(ma)}日。2連率はまだ当てにならない(上位と下位の差が小さい)。展示タイムを見よう", None, 0, force=True))
        if late:
            wd = q.get("w_dev")
            if wd == wd and wd is not None and abs(wd) >= 1.5:
                m, v = _m("weight", 1 if wd > 0 else 0)
                notes.append(_note("weight", "当日の体重", [lane], f"{wl}は当日の体重がふだんより{abs(wd):.1f}kg{'重い' if wd > 0 else '軽い'}。3着以内は100走で{_cnt(m)}", v,
                                   (-1 if wd > 0 else +1) if lane == 1 else 0))
            tl, cs = q.get("tilt"), q.get("course")
            if tl == tl and cs == cs and tl is not None and cs is not None and cs >= 4 and tl >= 1.5:
                m, v = _m("tilt", 0)
                notes.append(_note("tilt", "外でチルトを跳ねた", [lane], f"{who}は{int(cs)}コースでチルト{tl:+.1f}度。伸び勝負の合図。3着以内は100走で{_cnt(m)}", v, -1))
        # オカルト枠: 名前・ラッキー7
        for ch, tag in (("勝", "勝"), ("龍", "龍"), ("竜", "龍"), ("翔", "翔")):
            if ch in nm:
                notes.append(_note("name", f"名前に『{tag}』", [lane], f"{who}の名前に『{tag}』の字。データでは名前の字で成績は変わらない。でも応援したくなる", None, 0, occult=True,
                                   gen="名前に勝って入ってたら、そりゃ買いたくなるだろ"))
                break


    l7 = [int(k) for k in r.index if "motor_no" in r.columns and g(k, "motor_no") == g(k, "motor_no") and int(g(k, "motor_no")) % 10 == 7]
    if l7:
        notes.append(_note("lucky7", "ラッキー7のモーター", l7, f"{'・'.join(f'{k}号艇' for k in l7)}のモーターは番号の末尾が7。データでは当たりモーターではない。でも縁起はいい", None, 0, occult=True))

    # --- 展示の進入が深い(直前)
    if late and "course" in r.columns:
        c6, c5 = g(6, "course"), g(5, "course")
        if (c6 == c6 and c6 <= 3) or (c5 == c5 and c5 <= 2):
            m, v = _m("formation", 0)
            notes.append(_note("formation", "展示で外の艇が深く内へ", [1], f"スロー勢が増えて1コースは深くなりやすい。このとき1コースの艇の1着は100レースで{_cnt(m)}", v, -1))
    elif "front_rate" in r.columns:
        fr = [k for k in r.index if k >= 4 and g(k, "front_rate") == g(k, "front_rate") and g(k, "front_rate") >= 0.3]
        if fr:
            m, v = _m("formation", 0)
            notes.append(_note("formation", "前づけの常連がいる", fr, f"{'・'.join(f'{k}号艇' for k in fr)}は前づけの多い選手。外の艇が深く入ると、1コースの艇の1着は100レースで{_cnt(m)}", v, -1))

    # --- 風(予報 or 直前)
    wind = None
    hum = None
    if late and "wind" in r.columns and r0.get("wind") == r0.get("wind"):
        wind = float(r0.get("wind"))
        src = "直前情報"
    else:
        fw = ctx.get("wind") or {}
        try:
            h = int(str(r0.get("deadline") or "")[:2])
        except ValueError:
            h = None
        if h is not None and (jcd, h) in fw:
            wind, hum = fw[(jcd, h)]
        src = "天気予報"
    if wind is not None and wind >= 5:
        m, v = _m("wind", 1 if wind >= 7 else 0)
        notes.append(_note("wind", f"風{wind:.0f}m", [1], f"{src}の風が{wind:.0f}m。風5m以上で1号艇の1着は100レースで{_cnt(m)}", v, -1))
    if hum is not None and hum >= 75:
        m, v = _m("humid", 0)
        notes.append(_note("humid", f"湿度{hum:.0f}%", [1], f"湿った空気の日は1号艇が強い。100レースで{_cnt(m)}", v, +1))

    # --- 場のらしい出目(情報)
    dm = _lab("deme").get("numbers", {}).get("venues", [])
    for x in dm:
        if x.get("venue") == VENUES.get(jcd) and (x.get("lift_l") or 0) >= 1.2:
            notes.append(_note("deme", "この場の『らしい出目』", [], f"{VENUES.get(jcd)}の『らしい出目』は{x['sig']}(全国の{x['lift_e']:.1f}倍、最近の1年も多い)。予想の出発点に", None, 0))
            break

    # --- 暦(オカルト枠、レースごとではなく日の話。1日1回だけ出したいので rno==1 のレースか、記事側でまとめる)
    if ctx.get("calendar", True):
        rk = _rokuyo(day)
        if rk == "赤口":
            m, v = _m("rokuyo", 0)
            notes.append(_note("rokuyo", "今日は赤口", [1], f"六曜で1号艇がいちばん勝っているのは赤口({_n(m['in1']) if m else '-'}回)。理由は不明、追試中", None, +1, occult=True,
                               gen="ほらみろ、暦は生きてるんだよ!"))
        elif rk in ("大安", "仏滅"):
            notes.append(_note("rokuyo", f"今日は{rk}", [], f"{rk}でも成績はほかの日とほぼ同じ。でも気分は大事", None, 0, occult=True))
        age = _moon_age(day)
        if abs(age - 14.77) <= 1.2:
            notes.append(_note("moon", "満月の日", [], "満月の日でも1号艇の強さも荒れ方もふだんと同じ。でも満月のナイターは特別な気分", None, 0, occult=True))
    order = {"edge": 0, "trial": 1, "real": 2, "known": 3, "info": 4, "occult": 5}
    notes = [n for n in notes if n]
    notes.sort(key=lambda n: (order.get(n["kind"], 9), n["id"]))
    return notes


def summarize(notes: list[dict]) -> dict:
    """1号艇に向く理論と向かない理論の数。両方あれば『悩ましい』。"""
    real = [n for n in notes if n["kind"] != "occult"]
    plus = [n["title"] for n in real if n["dir"] > 0]
    minus = [n["title"] for n in real if n["dir"] < 0]
    return {"n": len(notes), "plus": plus, "minus": minus, "conflict": bool(plus and minus)}
