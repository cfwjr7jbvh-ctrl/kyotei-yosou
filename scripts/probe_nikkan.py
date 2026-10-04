"""日刊スポーツのボートレース予想情報(raceyosou.jp)で、どの場が、どこまで過去の日を見られるかを調べる(調査用)。

文章は保存せず、ページがあるか・表の行数・見出しだけを data/probe/nikkan_summary.json に書く。1秒に1回以下。
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path("data/probe/nikkan_summary.json")
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou research; personal use)"}
BASE = "https://nikkansports.raceyosou.jp/boatrace/"
_last = [0.0]


def get(url):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
            r.encoding = r.apparent_encoding
        return r
    except Exception:  # noqa: BLE001
        return None


def look(url):
    r = get(url)
    if r is None:
        return {"url": url, "status": None}
    soup = BeautifulSoup(r.text, "html.parser")
    for s in soup(["script", "style"]):
        s.decompose()
    ct = soup.select("table.comment_table tr")
    st = soup.select("table.sign_table tr")
    heads = [re.sub(r"\s+", " ", h.get_text(" ", strip=True))[:30] for h in soup.select("h1,h2,h3")][:14]
    tabs = []
    for t in soup.select("table")[:12]:
        th = [re.sub(r"\s+", " ", x.get_text(" ", strip=True))[:12] for x in t.select("th")][:16]
        tabs.append({"class": ".".join(t.get("class", [])), "rows": len(t.select("tr")), "th": th})
    # コメント欄の「【 前日 】」「【 当日 】」などの区分だけ数える(文章は残さない)
    kinds = {}
    for td in soup.select("table.comment_table td"):
        for k in re.findall(r"【\s*([^】]{1,6}?)\s*】", td.get_text(" ")):
            kinds[k] = kinds.get(k, 0) + 1
    return {"url": url, "final": r.url, "status": r.status_code, "len": len(r.text), "comment_rows": len(ct), "sign_rows": len(st),
            "comment_kinds": kinds, "heads": heads, "tables": tabs}


def main():
    res = {"portal": None, "slugs": {}, "dates": {}, "race_page": {}}
    r = get(BASE + "portal/")
    slugs = {}
    if r is not None and r.ok:
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            h = urllib.parse.urljoin(r.url, a["href"])
            m = re.match(r"https?://nikkansports\.raceyosou\.jp/boatrace/([a-z]+)/?", h)
            if m and m.group(1) not in ("portal", "data"):
                slugs.setdefault(m.group(1), a.get_text(" ", strip=True)[:10])
    res["slugs"] = slugs
    print("slugs", slugs)
    # 過去の日がどこまで見られるか(徳山と戸田、1R)
    for slug in ("tokuyama", "toda"):
        for d in ("20261003", "20260920", "20260801", "20260401", "20260101", "20250701", "20250101", "20240601", "20231015"):
            x = look(f"{BASE}{slug}/{d}/1")
            res["dates"][f"{slug}/{d}"] = {k: x.get(k) for k in ("status", "final", "len", "comment_rows", "sign_rows", "comment_kinds")}
            print(slug, d, res["dates"][f"{slug}/{d}"])
    # 1レースのページの作り(見出しと表の見出し)
    res["race_page"] = look(f"{BASE}tokuyama/20261004/1")
    # 他の場の今日のページもあるか
    for slug in list(slugs)[:16]:
        x = look(f"{BASE}{slug}/20261004/1")
        res["dates"][f"{slug}/20261004"] = {k: x.get(k) for k in ("status", "final", "len", "comment_rows", "sign_rows", "comment_kinds")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
