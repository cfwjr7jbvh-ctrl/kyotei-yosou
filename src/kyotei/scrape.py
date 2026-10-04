"""公式サイトのレースページ(直前情報・3連単オッズ)の取得と解析。

アクセスは1リクエストごとに間隔を空け、サイトに負荷をかけないようにする。
"""
from __future__ import annotations

import itertools
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from bs4 import BeautifulSoup

BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = {"User-Agent": "Mozilla/5.0 (personal kyotei prediction research; low-frequency)"}
_session = requests.Session()
_last = [0.0]


def fetch(page: str, jcd: int, rno: int, hd: str, wait: float = 1.0) -> str | None:
    dt = time.time() - _last[0]
    if dt < wait:
        time.sleep(wait - dt)
    _last[0] = time.time()
    url = f"{BASE}/{page}?rno={rno}&jcd={jcd:02d}&hd={hd}"
    for attempt in range(3):
        try:
            r = _session.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    return None


_lock = threading.Lock()
_tls = threading.local()


def fetch_many(reqs: list[tuple], workers: int = 4, gap: float = 0.5) -> list[str | None]:
    """reqs: [(ページ, 場, R, 日付), ...] を同時に数本ずつ取る。
    公式サイトは1ページの応答に約10秒かかるので、順番に取ると直前予想の1周が長くなる。
    同時に待つ本数を増やすだけで、リクエストを始める間隔は gap 秒以上あける(サイトへの負荷は小さいまま)。"""
    def one(r):
        page, jcd, rno, hd = r
        url = f"{BASE}/{page}?rno={rno}&jcd={int(jcd):02d}&hd={hd}"
        sess = getattr(_tls, "s", None)
        if sess is None:
            sess = _tls.s = requests.Session()
        for attempt in range(3):
            with _lock:
                d = time.time() - _last[0]
                if d < gap:
                    time.sleep(gap - d)
                _last[0] = time.time()
            try:
                res = sess.get(url, headers=UA, timeout=30)
                if res.status_code == 200:
                    return res.text
            except requests.RequestException:
                pass
            time.sleep(3 * (attempt + 1))
        return None
    if not reqs:
        return []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, reqs))


def _num(s: str):
    m = re.search(r"-?\d*\.?\d+", s or "")
    return float(m.group(0)) if m else np.nan


# 3連単オッズ表は「1着艇ごとの列」×「2着・3着の組み合わせ20行」で並んでいる
_TRI_ORDER = [(f, s, t) for f in range(1, 7)
              for s, t in itertools.permutations([x for x in range(1, 7) if x != f], 2)]


def parse_odds3t(html: str) -> dict[str, float]:
    """表の各行は 6列(1着艇1〜6)×[2着(4行に1回だけ), 3着, オッズ]。"""
    s = BeautifulSoup(html, "html.parser")
    if len(s.select("td.oddsPoint")) != 120:
        return {}
    tb = s.select_one("td.oddsPoint").find_parent("tbody")
    second = [None] * 6
    out = {}
    for tr in tb.select("tr"):
        tds = tr.select("td")
        per = len(tds) // 6
        if per not in (2, 3):
            continue
        for col in range(6):
            cell = tds[col * per:(col + 1) * per]
            if per == 3:
                second[col] = int(_num(cell[0].get_text()))
            third = int(_num(cell[-2].get_text()))
            out[f"{col + 1}-{second[col]}-{third}"] = _num(cell[-1].get_text(strip=True))
    return out if len(out) == 120 else {}


def parse_beforeinfo(html: str) -> dict:
    """展示タイム・チルト・体重・スタート展示(進入とST)・気象。"""
    s = BeautifulSoup(html, "html.parser")
    boats = {}
    tables = s.select("table.is-w748")
    if tables:
        for tb in tables[0].select("tbody"):
            tds = tb.select("tr")[0].select("td")
            if len(tds) < 6:
                continue
            lane = int(_num(tds[0].get_text()))
            boats[lane] = {"weight_now": _num(tds[3].get_text()),
                           "exhibit_time": _num(tds[4].get_text()),
                           "tilt": _num(tds[5].get_text()),
                           "parts_changed": int(bool(tds[7].get_text(strip=True))) if len(tds) > 7 else 0,
                           # 部品交換の中身(例: キャブ・ピストン、複数は「,」区切り)と、プロペラ(新ペラなど)
                           "parts": ",".join(tds[7].get_text(" ", strip=True).split()) if len(tds) > 7 else "",
                           "propeller": tds[6].get_text(strip=True) if len(tds) > 6 else ""}
    for course, div in enumerate(s.select("div.table1_boatImage1"), start=1):
        num = div.select_one(".table1_boatImage1Number")
        tm = div.select_one(".table1_boatImage1Time")
        if not num:
            continue
        lane = int(_num(num.get_text()))
        txt = tm.get_text(strip=True) if tm else ""
        b = boats.setdefault(lane, {})
        b["ex_course"] = course
        b["ex_st"] = _num(txt.replace("F", "")) * (-1 if txt.startswith("F") else 1)
    w = {}
    for unit in s.select(".weather1_bodyUnit"):
        title = unit.select_one(".weather1_bodyUnitLabelTitle")
        data = unit.select_one(".weather1_bodyUnitLabelData")
        if title and data:
            w[title.get_text(strip=True)] = _num(data.get_text())
        img = unit.select_one(".weather1_bodyUnitImage")
        if img and "is-windDirection" in (unit.get("class") or []):
            m = re.search(r"is-wind(\d+)", " ".join(img.get("class", [])))
            if m:
                w["wind_dir_code"] = int(m.group(1))
    return {"boats": boats, "wind": w.get("風速"), "wave": w.get("波高"),
            "air_temp": w.get("気温"), "water_temp": w.get("水温"),
            "wind_dir_code": w.get("wind_dir_code")}


def parse_raceresult(html: str) -> dict | None:
    """レース結果ページから3連単の組番・払戻金と決まり手。まだ結果が出ていない(中止を含む)ときは None。"""
    soup = BeautifulSoup(html, "html.parser")
    out = None
    for tb in soup.select("tbody"):
        tds = tb.select("td")
        if not tds or tds[0].get_text(strip=True) != "3連単":
            continue
        nums = [x.get_text(strip=True) for x in tb.select(".numberSet1_number")][:3]
        pay = tb.select_one(".is-payout1")
        yen = re.sub(r"[^\d]", "", pay.get_text()) if pay else ""
        if len(nums) == 3 and all(n.isdigit() for n in nums) and yen:
            out = {"tri_combo": "-".join(nums), "tri_pay": int(yen)}
        break
    if out is None:
        return None
    for t in soup.select("table"):
        txt = t.get_text(" ", strip=True)
        if txt.startswith("決まり手"):
            out["kimarite"] = txt.replace("決まり手", "").strip()
            break
    return out


def _expand(row: list[str]) -> list[str]:
    """「2 = 1 - 4」→ 2-1-4 と 1-2-4(= は前後どちらの順でも)。「2 - 6 - 1」はそのまま。"""
    out = [[]]
    i = 0
    while i < len(row):
        tok = row[i]
        if tok.isdigit():
            if i + 1 < len(row) and row[i + 1] == "=" and i + 2 < len(row):
                a, b = tok, row[i + 2]
                out = [o + [a, b] for o in out] + [o + [b, a] for o in out]
                i += 3
                continue
            out = [o + [tok] for o in out]
        i += 1
    return ["-".join(o) for o in out]


def parse_pcexpect(html: str) -> dict | None:
    """公式のコンピュータ予想: 各艇の印(1=◎ 2=○ 3=▲ 4=△)、自信度(1〜5)、予想フォーカス(2連単・3連単に展開)。"""
    soup = BeautifulSoup(html, "html.parser")
    marks = {}
    for t in soup.select("div.table1 table"):
        if "印" not in t.get_text():
            continue
        for tb in t.select("tbody"):
            tds = tb.select("td")
            if len(tds) < 2:
                continue
            lane = _num(tds[1].get_text())
            img = tds[0].select_one("img")
            m = re.search(r"icon_mark1_(\d)", img.get("src", "")) if img else None
            if np.isfinite(lane) and m:
                marks[int(lane)] = int(m.group(1))
        break
    lv = soup.select_one(".state2_lv")
    conf = None
    if lv:
        m = re.search(r"is-lv(\d)", " ".join(lv.get("class", [])))
        conf = int(m.group(1)) if m else None
    f2, f3 = [], []
    for row in soup.select(".numberSet2_row"):
        toks = re.findall(r"\d|=|-", row.get_text(" ", strip=True))
        combos = _expand(toks)
        for c in combos:
            (f3 if c.count("-") == 2 else f2).append(c)
    if not marks and not f3:
        return None
    return {"marks": marks, "conf": conf, "focus2": list(dict.fromkeys(f2)), "focus3": list(dict.fromkeys(f3))}


def race_days(hd: str) -> list[int]:
    """その日に開催している場コード一覧(公式トップから)。"""
    r = _session.get(f"{BASE}/index?hd={hd}", headers=UA, timeout=30)
    return sorted({int(x) for x in re.findall(r"jcd=(\d\d)", r.text)}) if r.ok else []
