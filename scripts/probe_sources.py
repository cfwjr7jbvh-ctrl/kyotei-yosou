"""選手コメント・前検タイムなどのページの「表の作り」と利用規約の文言を調べる(調査用)。

公開リポジトリに文章を置かないよう、表は見出し(th)と短い値だけを残し、長い文は先頭12文字に切る。
利用規約は、複製・転載・自動取得などに触れた文だけを抜き出す。アクセスは全体で1秒に1回以下。
→ data/probe/sources_summary.json
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path("data/probe/sources_summary.json")
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou research; personal use)"}
TARGETS = {
    "karatsu_comment": "https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_racers_comment",
    "karatsu_timerank": "https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank",
    "karatsu_top": "https://www.boatrace-karatsu.jp/modules/raceinfo/",
    "omura_comment": "https://omurakyotei.jp/yosou/comment.php",
    "omura_yosou": "https://omurakyotei.jp/yosou/",
    "ashiya_comment": "https://www.boatrace-ashiya.com/modules/raceinfo/?page=index_racers_comment",
    "mikuni_kisha": "http://www.mikuniks-web.jp/races/",
    "mikuni_kisha_1": "https://www2.mikuniks-web.jp/races/1",
    "nikkan_tokuyama": "http://nikkansports.raceyosou.jp/boatrace/tokuyama/",
    "nikkan_root": "http://nikkansports.raceyosou.jp/boatrace/",
    "nikkan_top": "http://nikkansports.raceyosou.jp/",
    "kiryu_timedata": "https://www.kiryu-kyotei.com/modules/raceinfo/?page=index_timedata",
    "amagasaki_raceinfo": "https://www.boatrace-amagasaki.jp/modules/raceinfo/",
    "boatrace_sp_suminoe": "https://boatrace-sp.jp/suminoe_yosou_comment/",
}
ROBOTS = ["https://boatrace-sp.jp/robots.txt", "http://nikkansports.raceyosou.jp/robots.txt", "http://www.mikuniks-web.jp/robots.txt",
          "https://www2.mikuniks-web.jp/robots.txt"]
TERMS_WORDS = r"複製|転載|著作|自動|スクレイピング|機械的|クローラ|ロボット|プログラム|私的|営利|二次利用|無断"
TERMS_LINK = r"利用規約|ご利用にあたって|サイトポリシー|ご利用について|免責|著作権|利用条件"
_last = [0.0]


def get(url: str):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except Exception as e:  # noqa: BLE001
        return None, repr(e)
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r, None


def short(s: str, n: int = 12) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n] + f"…({len(s)})"


def tables(soup) -> list[dict]:
    out = []
    for t in soup.select("table")[:8]:
        rows = []
        for tr in t.select("tr")[:5]:
            rows.append([("TH:" if c.name == "th" else "") + short(c.get_text(" ", strip=True), 20 if c.name == "th" else 12)
                         + (f" [{'.'.join(c.get('class', []))}]" if c.get("class") else "")
                         for c in tr.find_all(["td", "th"])][:14])
        par = t.parent
        out.append({"class": ".".join(t.get("class", [])), "id": t.get("id"), "n_rows": len(t.select("tr")),
                    "parent": f"{par.name}.{'.'.join(par.get('class', []))}" if par is not None else "", "rows": rows})
    return out


def main():
    res = {"targets": {}, "robots": {}, "terms": {}}
    term_pages = {}
    for name, url in TARGETS.items():
        r, err = get(url)
        if r is None or not r.ok:
            res["targets"][name] = {"url": url, "status": getattr(r, "status_code", None), "err": err}
            print(name, "NG", getattr(r, "status_code", None), err)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup(["script", "style", "noscript"]):
            s.decompose()
        forms = [{"action": f.get("action"), "method": f.get("method"),
                  "fields": [{"name": i.get("name"), "type": i.get("type") or i.name,
                              "values": [o.get("value") for o in i.select("option")][:15]} for i in f.select("input,select")][:8]}
                 for f in soup.select("form")][:4]
        links = []
        for a in soup.select("a[href]"):
            h = urllib.parse.urljoin(r.url, a["href"])
            t = a.get_text(" ", strip=True)
            if re.search(TERMS_LINK, t) and h.startswith("http"):
                term_pages.setdefault(urllib.parse.urlsplit(h).netloc, h)
            if re.search(r"\d{8}|day=|date=|hd=|races/\d|rno=|race=", h) and len(links) < 30:
                links.append({"text": short(t, 10), "href": h[:160]})
        res["targets"][name] = {"url": url, "final": r.url, "status": r.status_code, "len": len(r.text),
                                "title": soup.title.get_text(strip=True)[:80] if soup.title else "",
                                "tables": tables(soup), "forms": forms, "links": links,
                                "headings": [short(h.get_text(" ", strip=True), 30) for h in soup.select("h1,h2,h3,h4")][:20]}
        print(name, r.status_code, len(r.text), "tables", len(res["targets"][name]["tables"]))
    for u in ROBOTS:
        r, err = get(u)
        res["robots"][u] = (r.text[:800] if r is not None and r.ok and "<html" not in r.text[:300].lower() else f"none ({getattr(r, 'status_code', err)})")
    for host, u in term_pages.items():
        r, err = get(u)
        if r is None or not r.ok:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup(["script", "style"]):
            s.decompose()
        sents = re.split(r"(?<=[。．])", re.sub(r"\s+", " ", soup.get_text(" ")))
        res["terms"][host] = {"url": u, "clauses": [s.strip()[:220] for s in sents if re.search(TERMS_WORDS, s)][:15]}
        print("terms", host, len(res["terms"][host]["clauses"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
