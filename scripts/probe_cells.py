"""収集する表のセルの中身の形を調べる(調査用)。文章は先頭10文字まで、画像は alt とファイル名だけ。
→ data/probe/cells_summary.json
"""
from __future__ import annotations

import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path("data/probe/cells_summary.json")
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou research; personal use)"}
PAGES = {
    "nikkan_tokuyama_past": ("https://nikkansports.raceyosou.jp/boatrace/tokuyama/20261003/1",
                             ["table.sign_table", "table.start_table", "table.comment_table", "table.sign_head"]),
    "nikkan_biwako_past": ("https://nikkansports.raceyosou.jp/boatrace/biwako/20260904/1", ["table.sign_table", "table.start_table", "table.sign_head"]),
    "karatsu_comment": ("https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_racers_comment", ["div.racers_comment table"]),
    "omura_comment": ("https://omurakyotei.jp/yosou/comment.php", ["table#tblcomment"]),
    "mikuni_races": ("http://www.mikuniks-web.jp/races/", ["div.wide-device-only table.table"]),
    "karatsu_timerank": ("https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank", ["div.tableBlock table"]),
    "tokuyama_timerank": ("https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_timerank", ["table"]),
}
_last = [0.0]


def get(url):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    r = requests.get(url, headers=UA, timeout=25)
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r


def cell(c) -> dict:
    txt = re.sub(r"\s+", " ", c.get_text(" ", strip=True))
    d = {"tag": c.name, "cls": ".".join(c.get("class", [])), "text": txt[:10] + (f"…({len(txt)})" if len(txt) > 10 else "")}
    imgs = [(i.get("alt", ""), (i.get("src", "") or "").rsplit("/", 1)[-1]) for i in c.select("img")]
    if imgs:
        d["img"] = imgs[:4]
    inner = sorted({".".join(x.get("class", [])) for x in c.find_all(True) if x.get("class")})
    if inner:
        d["inner_cls"] = inner[:8]
    if c.get("colspan") or c.get("rowspan"):
        d["span"] = [c.get("colspan"), c.get("rowspan")]
    return d


def main():
    res = {}
    for name, (url, sels) in PAGES.items():
        try:
            r = get(url)
        except Exception as e:  # noqa: BLE001
            res[name] = {"err": repr(e)}
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        out = {"status": r.status_code, "tables": {}}
        for sel in sels:
            ts = soup.select(sel)
            if not ts:
                out["tables"][sel] = None
                continue
            t = ts[0]
            out["tables"][sel] = {"count": len(ts), "rows": [[cell(c) for c in tr.find_all(["td", "th"])][:16] for tr in t.select("tr")[:9]]}
        res[name] = out
        print(name, r.status_code, {k: (v or {}).get("count") for k, v in out["tables"].items()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
