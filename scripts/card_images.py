"""選手カードの画像(1080×1350、X・Instagram・note 用)を書き出す。

python scripts/card_images.py 峰竜太 4238 ... [--venue 尼崎] [--assen data/assen/assen_202610.json:13:20261027] [--out out/cards_png]

数字は自分たちの集計(src/kyotei/racer_card.py)だけ。公式の写真・ロゴ・表は使わない。
画像は Chromium(Playwright)で描く。日本語フォントは Noto Sans CJK JP を使う(Actions では fonts-noto-cjk を入れる)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import racer_card as rc  # noqa: E402
from kyotei.card_render import card_image_html  # noqa: E402


def assen_ids(spec: str) -> tuple[list[int], int]:
    """data/assen/assen_YYYYMM.json:場コード:初日 → その節の登番一覧と場コード。"""
    path, jcd, hd = spec.rsplit(":", 2)
    for s in json.loads(pathlib.Path(path).read_text(encoding="utf-8")):
        if s["jcd"] == int(jcd) and s["hd"] == hd:
            return [r["id"] for r in s.get("racers", [])], int(jcd)
    raise SystemExit(f"見つかりません: {spec}")


async def render(pages: list[tuple[str, str]], out: pathlib.Path):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for name, html in pages:
            await pg.set_content(html)
            await pg.wait_for_timeout(150)
            await pg.screenshot(path=str(out / name), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("racers", nargs="*")
    ap.add_argument("--venue", default=None, help="大会の場(ほかの場の「巧者」タグを外す)")
    ap.add_argument("--assen", default=None, help="data/assen/assen_YYYYMM.json:場コード:初日")
    ap.add_argument("--kicker", default="データで見る選手カード")
    ap.add_argument("--out", default=str(ROOT / "out/cards_png"))
    a = ap.parse_args()
    keys = list(a.racers)
    jcd = None
    if a.assen:
        ids, jcd = assen_ids(a.assen)
        keys += [str(i) for i in ids]
    if a.venue:
        jcd = int(a.venue) if str(a.venue).isdigit() else next((k for k, v in rc.VENUES.items() if v == a.venue), None)
    d = rc.load_table()
    cards, _ = rc.build(d)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pages, used = [], set()  # まとめて作るときは、大きく出すタグがほかの選手とかぶらないようにする
    for k in keys:
        c = rc.find(cards, k)
        if not c:
            print("見つかりません:", k)
            continue
        pages.append((f"{c['id']}_{c['name']}.png", card_image_html(c, jcd, a.kicker, used)))
    asyncio.run(render(pages, out))
    print(f"{len(pages)}枚 → {out}")


if __name__ == "__main__":
    main()
