"""グレードレース(SG・PG1・G1・G2)の裏新聞の下書きを、毎朝まとめて作る。

data/assen/assen_YYYYMM.json(scripts/fetch_assen.py が毎朝更新)から、初日が「今日の DAYS_BEFORE 日後まで」で
「終わっていない」節を選び、節ごとに下書き一式(HTML・note の本文・X の投稿案)と注目選手のカード画像を作る。
欠場や追加の斡旋は毎朝の作り直しで反映される。

出力(すべて暗号化。アプリの「記事」タブが読む。cards ブランチの ura/ に1コミットだけで置く):
  DIR/ura/index.json            一覧 {asof, items: [{key, title, grade, venue, jcd, hd, n, picks, images}]}
  DIR/ura/<key>.json            下書き {title, ..., html, note, x, picks, images: [{file, name}]}
  DIR/ura/<key>_i<k>.json       カード画像 {name, png(base64)}
  key = 場コード2桁_初日(例 04_20261013)

python scripts/ura_auto.py --out DIR [--days-before 7] [--no-images] [--only 04_20261013]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from kyotei import racer_card as rc  # noqa: E402
from kyotei.card_render import card_image_html  # noqa: E402
from kyotei.publish import write_json  # noqa: E402
import ura_shinbun  # noqa: E402

GRADES = ("SG", "PG1", "G1", "G2")
SERIES_DAYS = 6          # SG・G1 はふつう6日間。終わった節は作らない
JST = dt.timezone(dt.timedelta(hours=9))


def short_title(raw: str, venue: str, grade: str) -> str:
    """「開設７２周年記念トーキョー・ベイ・カップ」→「G1 トーキョー・ベイ・カップ」。"""
    t = unicodedata.normalize("NFKC", raw or "")
    t = re.sub(r"開設\d+周年記念(競走)?", "", t)
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ・")
    return f"{grade} {t or venue + '周年記念'}"


def series_in_window(today: dt.date, days_before: int) -> list[dict]:
    out, seen = [], set()
    for p in sorted((ROOT / "data/assen").glob("assen_*.json")):
        for s in json.loads(p.read_text(encoding="utf-8")):
            if s.get("grade") not in GRADES or not s.get("racers"):
                continue
            first = dt.datetime.strptime(s["hd"], "%Y%m%d").date()
            if not (first - dt.timedelta(days=days_before) <= today <= first + dt.timedelta(days=SERIES_DAYS - 1)):
                continue
            key = f"{s['jcd']:02d}_{s['hd']}"
            if key not in seen:
                seen.add(key)
                out.append({**s, "key": key})
    return sorted(out, key=lambda s: (s["hd"], s["jcd"]))


async def render_png(pages: list[tuple[str, str]]) -> list[bytes]:
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for _, html in pages:
            await pg.set_content(html)
            await pg.evaluate("document.fonts.ready")   # 見出しと数字のフォント(Google Fonts)が届くまで待つ
            await pg.wait_for_timeout(300)
            out.append(await pg.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1350}))
        await b.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days-before", type=int, default=7)
    ap.add_argument("--n", type=int, default=8, help="注目選手の数")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--only", default=None, help="この key の節だけ(試すとき)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD(試すとき)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    out = pathlib.Path(a.out) / "ura"
    out.mkdir(parents=True, exist_ok=True)
    series = [s for s in series_in_window(today, a.days_before) if not a.only or s["key"] == a.only]
    items = []
    if series:
        d = rc.load_table()
        cards, meta = rc.build(d)
    for s in series:
        venue = rc.VENUES.get(s["jcd"], s.get("venue", ""))
        title = short_title(s.get("title") or s.get("title_page", ""), venue, s["grade"])
        r = ura_shinbun.make(title, [str(x["id"]) for x in s["racers"]], s["jcd"], a.n, "", d, cards, meta)
        picks = r["picks"]
        images = []
        if not a.no_images:
            used: set = set()
            pages = [(f"{c['id']}_{c['name']}.png", card_image_html(c, s["jcd"], f"{s['grade']}{venue} 出場選手カード", used))
                     for c, *_x in picks]
            try:
                pngs = asyncio.run(render_png(pages))
            except Exception as e:  # 描画の道具が無いときは画像なしで続ける
                print("画像は作れませんでした:", e)
                pngs = []
            for k, ((name, _), png) in enumerate(zip(pages, pngs)):
                f = f"{s['key']}_i{k}.json"
                write_json(out / f, {"name": name, "png": base64.b64encode(png).decode()})
                images.append({"file": f, "name": name})
        pick_rows = [{"id": c["id"], "name": c["name"], "tag": t["t"]} for c, t, *_x in picks]
        write_json(out / f"{s['key']}.json", {
            "key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
            "html": r["html"], "note": r["note"], "x": r["x"], "picks": pick_rows, "images": images,
            "n": len(r["sel"]), "missing": r["missing"], "asof": meta["asof"]})
        items.append({"key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
                      "n": len(r["sel"]), "picks": [p["name"] for p in pick_rows], "images": len(images)})
        print(s["key"], title, f"{len(r['sel'])}人", f"画像{len(images)}枚", "見つからない:", r["missing"] or "なし")
    write_json(out / "index.json", {"asof": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(),
                                    "days_before": a.days_before, "items": items})
    print(f"ura: {len(items)} 節 → {out}")


if __name__ == "__main__":
    main()
