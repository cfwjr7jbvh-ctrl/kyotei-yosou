"""各場の公式サイトに「選手コメント」などのページがあるかを調べる(調査用、1回きり)。

各場のトップ(PC・スマホ)から、リンクの文字かURLに「コメント」「comment」「前検」「オリジナル展示」「展示」などを含むものを集め、
それぞれ最初の数ページを保存する。robots.txt も保存する。結果は out/venues/ に置き、ワークフローの成果物として1日だけ残す
(公開リポジトリにページそのものはコミットしない)。アクセスは全体で1秒に1回以下。
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path("out/venues")
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


def safe(s: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", s)[:120]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for jcd, top in SITES.items():
        info = {"top": top, "pages": [], "links": []}
        rb, err = get(urllib.parse.urljoin(top, "/robots.txt"))
        if rb is not None and rb.ok:
            (OUT / f"{jcd:02d}_robots.txt").write_text(rb.text[:20000], encoding="utf-8")
            info["robots"] = rb.text[:2000]
        cand = {}
        for start in (top, urllib.parse.urljoin(top, "/sp/")):
            r, err = get(start)
            if r is None or not r.ok:
                info["pages"].append({"url": start, "status": getattr(r, "status_code", None), "err": err})
                continue
            (OUT / f"{jcd:02d}_top_{safe(start)}.html").write_text(r.text, encoding="utf-8")
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
            if ok:
                (OUT / f"{jcd:02d}_p{i}_{safe(u.split('//', 1)[-1])}.html").write_text(r.text, encoding="utf-8")
            info["pages"].append({"url": u, "text": t, "status": getattr(r, "status_code", None), "err": err,
                                  "len": len(r.text) if ok else 0,
                                  "has_comment_words": bool(ok and re.search(r"出足|伸び|回り足|行き足|まわり足|乗りやすい|舟足", r.text))})
        summary[jcd] = info
        print(jcd, top, "links", len(cand), [(p.get("text"), p.get("status"), p.get("has_comment_words")) for p in info["pages"][2:]])
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
