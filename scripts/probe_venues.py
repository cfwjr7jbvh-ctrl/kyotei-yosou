"""各場の公式サイトに「選手コメント」などのページがあるかを調べる(調査用、1回きり)。

各場のトップ(PC・スマホ)から、リンクの文字かURLに「コメント」「comment」「前検」「オリジナル展示」「展示」などを含むものを集め、
それぞれ最初の数ページを調べる。robots.txt も見る。公開リポジトリにページそのものは置かず、
ページの作り(コメントらしい文の例を短く数件、それを囲むタグ、日付やレースの切り替えのリンク)だけを
data/probe/venues_summary.json にまとめる。アクセスは全体で1秒に1回以下。
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path("data/probe/venues_summary.json")
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou research; personal use)"}
SITES = {1: "https://www.kiryu-kyotei.com/", 2: "https://www.boatrace-toda.jp/", 3: "https://www.boatrace-edogawa.com/",
         4: "https://www.heiwajima.gr.jp/", 5: "https://www.boatrace-tamagawa.com/", 6: "https://www.boatrace-hamanako.jp/",
         7: "https://www.gamagori-kyotei.com/", 8: "https://www.boatrace-tokoname.jp/", 9: "https://www.boatrace-tsu.com/",
         10: "https://www.boatrace-mikuni.jp/", 11: "https://www.boatrace-biwako.jp/", 12: "https://www.boatrace-suminoe.jp/",
         13: "https://www.boatrace-amagasaki.jp/", 14: "https://www.n14.jp/", 15: "https://www.marugameboat.jp/",
         16: "https://www.kojimaboat.jp/", 17: "https://www.boatrace-miyajima.com/", 18: "https://www.boatrace-tokuyama.jp/",
         19: "https://www.boatrace-shimonoseki.jp/", 20: "https://www.wmb.jp/", 21: "https://www.boatrace-ashiya.com/",
         22: "https://www.boatrace-fukuoka.com/", 23: "https://www.boatrace-karatsu.jp/", 24: "https://omurakyotei.jp/"}
KEYS = ["コメント", "comment", "前検", "オリジナル展示", "展示データ", "まわり足", "気配", "談話", "インタビュー", "記者", "予想"]
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


WORDS = r"出足|伸び|回り足|行き足|まわり足|乗りやすい|舟足|足色|レース足|ターン"


def css_path(el, depth=4) -> str:
    out = []
    while el is not None and getattr(el, "name", None) and el.name not in ("html", "body") and len(out) < depth:
        cls = ".".join(el.get("class", [])[:2])
        out.append(el.name + (("." + cls) if cls else "") + (("#" + el["id"]) if el.get("id") else ""))
        el = el.parent
    return " < ".join(out)


def describe(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    hits = [t for t in soup.find_all(string=re.compile(WORDS))]
    ex = []
    for t in hits[:6]:
        txt = re.sub(r"\s+", " ", str(t)).strip()
        ex.append({"text": txt[:60], "path": css_path(t.parent)})
    nav = []
    for a in soup.select("a[href]"):
        h = a["href"]
        if re.search(r"(day|date|hd|ymd|kaisai|race|rno|r=|no=|sel)", h, re.I) and len(nav) < 25:
            nav.append({"text": a.get_text(" ", strip=True)[:20], "href": urllib.parse.urljoin(url, h)[:160]})
    sels = [{"name": s_.get("name"), "options": [o.get_text(strip=True)[:15] for o in s_.select("option")][:12]} for s_ in soup.select("select")][:5]
    title = soup.title.get_text(strip=True)[:80] if soup.title else ""
    return {"title": title, "n_comment_words": len(hits), "examples": ex, "nav": nav, "selects": sels,
            "iframes": [f.get("src", "")[:160] for f in soup.select("iframe")][:5],
            "scripts_json": bool(re.search(r"\.json|ajax|api/", html))}


def safe(s: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", s)[:120]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    for jcd, top in SITES.items():
        info = {"top": top, "pages": [], "links": []}
        rb, err = get(urllib.parse.urljoin(top, "/robots.txt"))
        if rb is not None and rb.ok and "<html" not in rb.text[:500].lower():
            info["robots"] = rb.text[:1500]
        cand = {}
        for start in (top, urllib.parse.urljoin(top, "/sp/")):
            r, err = get(start)
            if r is None or not r.ok:
                info["pages"].append({"url": start, "status": getattr(r, "status_code", None), "err": err})
                continue
            info["pages"].append({"url": r.url, "status": r.status_code, "len": len(r.text)})
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href]"):
                text = a.get_text(" ", strip=True)
                href = urllib.parse.urljoin(r.url, a["href"])
                if any(k.lower() in (text + " " + href).lower() for k in KEYS) and href.startswith("http"):
                    cand.setdefault(href, text[:40])
        info["links"] = [{"url": u, "text": t} for u, t in cand.items()]
        # コメントらしいリンクを優先して最大4ページ保存
        pri = sorted(cand.items(), key=lambda kv: (0 if ("コメント" in kv[1] or "comment" in kv[0].lower()) else 1))
        for i, (u, t) in enumerate(pri[:4]):
            r, err = get(u)
            ok = r is not None and r.ok
            page = {"url": u, "text": t, "status": getattr(r, "status_code", None), "err": err, "len": len(r.text) if ok else 0}
            if ok:
                page.update(describe(r.text, r.url))
            info["pages"].append(page)
        summary[jcd] = info
        print(jcd, top, "links", len(cand), [(p.get("text"), p.get("status"), p.get("n_comment_words")) for p in info["pages"][2:]])
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
