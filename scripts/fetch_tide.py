"""潮位(気象庁の潮位表=天文潮の推算値)を集める。過去の年もさかのぼって取れる(推算なので、いつの年でも同じ方法で出ている)。

2026-10-07 ユーザー「検証に追加のデータが必要なら収集をはじめ、過去に遡及してあつめられるならあつめる」→ 最初の1本(待ち行列の tide「満潮はイン、干潮は外」)。
- 観測点の一覧ページ(station{年}.php)から緯度・経度を読み、24場それぞれにいちばん近い観測点を割り当てる(60km より遠ければ無し)
- 年ごとのテキスト(1日1行: 毎時の潮位24個・満潮4回・干潮4回)を読み、data/tide/tide_{年}.csv.gz に保存
- 場と観測点の対応は data/tide/stations.json
Actions(tide.yml)で動かす。手元は外に出られない。

  python scripts/fetch_tide.py --years 2023 2024 2025 2026 2027
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
import time

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/tide"
BASE = "https://www.data.jma.go.jp/kaiyou"
STATION_PAGES = ["{b}/db/tide/suisan/station{y}.php"]
TXT_URLS = ["{b}/data/db/tide/suisan/txt/{y}/{c}.txt", "https://ds.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{y}/{c}.txt"]
UA = {"User-Agent": "kyotei-yosou research (tide for boat race analysis)"}
# 24場の位置(scripts/lab.py の VENUE_LL と同じ)
VENUE_LL = {1: (36.39, 139.33), 2: (35.81, 139.66), 3: (35.69, 139.87), 4: (35.58, 139.74), 5: (35.62, 139.52), 6: (34.72, 137.60),
            7: (34.82, 137.23), 8: (34.88, 136.84), 9: (34.72, 136.54), 10: (36.21, 136.14), 11: (35.03, 135.88), 12: (34.61, 135.47),
            13: (34.72, 135.42), 14: (34.17, 134.61), 15: (34.29, 133.79), 16: (34.47, 133.81), 17: (34.31, 132.32), 18: (34.05, 131.80),
            19: (33.95, 130.94), 20: (33.90, 130.81), 21: (33.89, 130.66), 22: (33.59, 130.40), 23: (33.46, 129.97), 24: (32.92, 129.96)}
# 水面(潮の影響があるか)。淡水の場は観測点が近くても潮は関係ない(参考の印)
WATER = {1: "淡水", 2: "淡水", 3: "汽水", 4: "海水", 5: "淡水", 6: "汽水", 7: "汽水", 8: "海水", 9: "海水", 10: "汽水", 11: "淡水", 12: "淡水",
         13: "淡水", 14: "海水", 15: "海水", 16: "海水", 17: "海水", 18: "海水", 19: "海水", 20: "海水", 21: "淡水", 22: "汽水", 23: "海水", 24: "海水"}
MAX_KM = 60


def get(url: str) -> requests.Response | None:
    last = ""
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            last = str(r.status_code)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                break
        except requests.RequestException as ex:
            last = type(ex).__name__
        time.sleep(2 + 3 * i)
    DEBUG.append(f"取れない: {url} ({last})")
    return None


DEBUG: list[str] = []   # うまく取れないときの手がかり(data/tide/_debug.txt に残す。Actions のログは手元から読めないため)


def _deg(s: str) -> float | None:
    s = s.replace("&deg;", "°").replace("&#176;", "°").replace("&#xB0;", "°")
    m = re.match(r"\s*[NE北東]?\s*(\d+)\s*[°゜度º˚]\s*(\d+)", s)
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def stations(year: int) -> list[dict]:
    """観測点の一覧(記号・名前・緯度・経度)。表の行から読む。"""
    for pat in STATION_PAGES:
        r = get(pat.format(b=BASE, y=year))
        if not r:
            continue
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
        DEBUG.append(f"一覧ページ {year}: {len(html)}字。表の行の例: " + " / ".join(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", x))[:200] for x in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)[3:6]))
        out = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
            # 地点記号は英字を含む2文字(「Q8」「ZG」)。数字だけの列は通し番号なので記号ではない
            code = next((c for c in cells if re.fullmatch(r"[A-Z0-9]{2}", c) and re.search(r"[A-Z]", c)), None)
            lats = [x for x in (_deg(c) for c in cells) if x is not None]
            if code and len(lats) >= 2:
                i = cells.index(code)
                name = next((c for c in cells[i + 1:] if c and not re.search(r"[\dA-Za-z]", c)), "")
                out.append({"code": code, "name": name, "lat": lats[0], "lon": lats[1]})
        if out:
            return out
    return []


def km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def parse_txt(text: str) -> list[dict]:
    """1日1行(固定幅)。1〜72桁: 0〜23時の潮位(3桁×24、cm)、73〜78: 年月日(YYMMDD)、79〜80: 地点記号、
    81〜108: 満潮(時刻4桁+潮位3桁)×4、109〜136: 干潮×4。予測が無い所は 9999 / 999。"""
    rows = []
    for ln in text.splitlines():
        if len(ln) < 80:
            continue
        try:
            hh = [int(ln[i * 3:(i + 1) * 3]) for i in range(24)]
            yy, mm, dd = int(ln[72:74]), int(ln[74:76]), int(ln[76:78])
        except ValueError:
            continue
        rec = {"date": f"{2000 + yy:04d}-{mm:02d}-{dd:02d}", "code": ln[78:80].strip()}
        for i, v in enumerate(hh):
            rec[f"h{i:02d}"] = v
        for kind, off in (("hi", 80), ("lo", 108)):
            for k in range(4):
                seg = ln[off + k * 7: off + (k + 1) * 7]
                t, h = seg[:4].strip(), seg[4:7].strip()
                ok = t.isdigit() and t != "9999" and h.lstrip("-").isdigit() and h != "999"
                rec[f"{kind}{k + 1}_t"] = f"{int(t) // 100:02d}:{int(t) % 100:02d}" if ok else None
                rec[f"{kind}{k + 1}_cm"] = int(h) if ok else None
        rows.append(rec)
    return rows


def main(argv=None):
    try:
        _main(argv)
    except Exception:
        import traceback
        DEBUG.append(traceback.format_exc())
        raise
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "_debug.txt").write_text("\n".join(DEBUG[-200:]), encoding="utf-8")
        for ln in DEBUG[-8:]:   # Actions の注釈に出す(手元からはログが読めないが、注釈は読める)
            print("::warning::" + ln.replace("\n", " | ")[:900])


def _main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2023, 2024, 2025, 2026, 2027])
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    st = []
    for y in sorted(a.years, reverse=True):   # 新しい年の一覧から(観測点の入れ替わりは少ない)
        st = stations(y)
        if st:
            print("観測点の一覧:", y, len(st), "地点")
            break
    if not st:
        (OUT / "_debug.txt").write_text("\n".join(DEBUG), encoding="utf-8")
        raise SystemExit("観測点の一覧が読めませんでした")
    venue_st = {}
    for j, ll in VENUE_LL.items():
        best = min(st, key=lambda s: km(ll, (s["lat"], s["lon"])))
        d = km(ll, (best["lat"], best["lon"]))
        venue_st[j] = {"code": best["code"], "name": best["name"], "km": round(d, 1), "water": WATER[j]} if d <= MAX_KM else {"code": None, "km": round(d, 1), "water": WATER[j]}
    (OUT / "stations.json").write_text(json.dumps(venue_st, ensure_ascii=False, indent=1), encoding="utf-8")
    print("場と観測点:", {j: (v.get("name"), v["km"]) for j, v in venue_st.items()})
    codes = sorted({v["code"] for v in venue_st.values() if v.get("code")})
    for y in a.years:
        rows = []
        for c in codes:
            r = None
            for pat in TXT_URLS:
                r = get(pat.format(b=BASE, y=y, c=c))
                if r:
                    break
            if not r:
                print("  無し:", y, c)
                continue
            txt = r.content.decode("ascii", "ignore")
            try:
                rr = parse_txt(txt)
            except Exception as ex:  # noqa: BLE001
                DEBUG.append(f"読めない: {y} {c} {type(ex).__name__} {ex} 先頭: {txt[:160]!r}")
                continue
            if not rr:
                DEBUG.append(f"行が無い: {y} {c} 先頭: {txt[:160]!r}")
            rows += rr
            time.sleep(1.0)   # 相手のサーバーにやさしく
        if rows:
            df = pd.DataFrame(rows)
            df.to_csv(OUT / f"tide_{y}.csv.gz", index=False, compression="gzip")
            print(y, len(df), "行", df["code"].nunique(), "地点")
        else:
            print(y, "取れませんでした")
    DEBUG.append("場と観測点: " + ", ".join(f"{j}:{v.get('code')}{v.get('name', '')}({v['km']}km)" for j, v in venue_st.items()))


if __name__ == "__main__":
    main()
