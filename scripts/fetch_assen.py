"""大会(節)の出場選手一覧を取る: 公式の月間スケジュールから節を見つけ、斡旋ページから出場選手の登番と名前を取る。

裏新聞の下書き(scripts/ura_shinbun.py --assen ...)に渡すため。保存するのは「どの節に誰が出るか」という事実だけ
(公式の表そのものは保存しない)。SG・G1 などのグレードは、スケジュールの表示から読み取れたときだけ付ける。

python scripts/fetch_assen.py [--months 2] [--grades SG,PG1,G1,G2] [--probe]
→ data/assen/assen_YYYYMM.json(月ごと: [{jcd, venue, hd, title, grade, racers: [{id, name}]}])
  --probe のときは、スケジュールの作り(リンクと class 名)の要約を data/probe/assen_summary.json にも書く
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.racer_card import VENUES  # noqa: E402

BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = {"User-Agent": "Mozilla/5.0 (personal kyotei research; low-frequency)"}
OUT = ROOT / "data/assen"
PROBE = ROOT / "data/probe/assen_summary.json"
JST = dt.timezone(dt.timedelta(hours=9))
GRADE_PAT = [("SG", r"SG"), ("PG1", r"PG1|PGⅠ"), ("G1", r"G1|GⅠ"), ("G2", r"G2|GⅡ"), ("G3", r"G3|GⅢ"), ("一般", r"IP|ippan|一般")]
_s = requests.Session()
_last = [0.0]


def get(url: str) -> str | None:
    wait = 1.5 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    for k in range(3):
        try:
            r = _s.get(url, headers=UA, timeout=40)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(4 * (k + 1))
    return None


def grade_of(tokens: str) -> str | None:
    for g, pat in GRADE_PAT:
        if re.search(pat, tokens):
            return g
    return None


def schedule(ym: str, probe: dict | None) -> list[dict]:
    """月間スケジュールから節(場・初日・名前・グレード)を集める。"""
    html = get(f"{BASE}/monthlyschedule?ym={ym}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    samples = []
    for a in soup.select("a[href]"):
        m = re.search(r"(raceindex|assen)\?jcd=(\d\d)&hd=(\d{8})", a["href"])
        if not m:
            continue
        jcd, hd = int(m.group(2)), m.group(3)
        if (jcd, hd) in seen:
            continue
        seen.add((jcd, hd))
        # グレードは、リンクやその親の class 名・文字から読む
        ctx = []
        el = a
        for _ in range(3):
            if el is None:
                break
            ctx += el.get("class", []) if hasattr(el, "get") else []
            el = el.parent
        tokens = " ".join(ctx) + " " + a.get_text(" ", strip=True)
        out.append({"jcd": jcd, "venue": VENUES.get(jcd, ""), "hd": hd, "title": a.get_text(" ", strip=True)[:60],
                    "grade": grade_of(tokens)})
        if len(samples) < 12:
            samples.append({"href": a["href"][:120], "text": a.get_text(" ", strip=True)[:40], "classes": ctx[:10]})
    if probe is not None:
        probe[ym] = {"n_series": len(out), "samples": samples, "grades": {g: sum(1 for x in out if x["grade"] == g) for g in
                                                                          {x["grade"] for x in out}}}
    return out


def assen(jcd: int, hd: str, probe: dict | None) -> dict:
    html = get(f"{BASE}/assen?jcd={jcd:02d}&hd={hd}")
    if not html:
        return {"racers": [], "error": "fetch"}
    soup = BeautifulSoup(html, "html.parser")
    racers, seen = [], set()
    for a in soup.select("a[href*='toban=']"):
        m = re.search(r"toban=(\d{4})", a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            racers.append({"id": int(m.group(1)), "name": re.sub(r"[\s　]+", "", a.get_text(" ", strip=True))[:12]})
    head = soup.select_one("h2, h3, .heading2_titleName, .title16_titleDetail__add2020")
    title = re.sub(r"\s+", " ", head.get_text(" ", strip=True))[:80] if head else ""
    tokens = " ".join(c for el in soup.select("[class*='is-'], [class*='grade']")[:40] for c in el.get("class", []))
    if probe is not None and len(probe.setdefault("assen", [])) < 3:
        probe["assen"].append({"jcd": jcd, "hd": hd, "n_racers": len(racers), "title": title,
                               "headings": [re.sub(r"\s+", " ", h.get_text(" ", strip=True))[:50] for h in soup.select("h1,h2,h3")][:8],
                               "grade_tokens": tokens[:300]})
    return {"racers": racers, "title_page": title, "grade_page": grade_of(tokens)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=2)
    ap.add_argument("--grades", default="SG,PG1,G1,G2", help="斡旋を取るグレード(カンマ区切り。all で全部)")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    want = None if a.grades == "all" else set(a.grades.split(","))
    probe = {} if a.probe else None
    today = dt.datetime.now(JST).date()
    yms = []
    y, m = today.year, today.month
    for _ in range(a.months):
        yms.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    OUT.mkdir(parents=True, exist_ok=True)
    for ym in yms:
        series = schedule(ym, probe)
        path = OUT / f"assen_{ym}.json"
        old = {(x["jcd"], x["hd"]): x for x in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])}
        n_fetch = 0
        for s in series:
            if s["hd"] < today.strftime("%Y%m%d"):
                continue  # 始まった節は取り直さない
            if want is not None and s["grade"] not in want and not (a.probe and n_fetch < 2):
                continue
            got = assen(s["jcd"], s["hd"], probe)
            n_fetch += 1
            if got["racers"]:
                s.update({"racers": got["racers"], "title_page": got.get("title_page"),
                          "grade": s["grade"] or got.get("grade_page"),
                          "fetched": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")})
                old[(s["jcd"], s["hd"])] = s
            print(ym, s["venue"], s["hd"], s["grade"], s["title"][:30], len(got["racers"]), "人")
        path.write_text(json.dumps(sorted(old.values(), key=lambda x: (x["hd"], x["jcd"])), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(ym, "節", len(series), "斡旋を取った", n_fetch)
    if probe is not None:
        PROBE.parent.mkdir(parents=True, exist_ok=True)
        PROBE.write_text(json.dumps(probe, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
