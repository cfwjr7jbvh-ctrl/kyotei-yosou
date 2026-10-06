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
from kyotei.mag import chart_image_html  # noqa: E402
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
        for name, html in pages:
            h = 1920 if name.startswith("早見表") else 1350
            await pg.set_viewport_size({"width": 1080, "height": h})
            await pg.set_content(html)
            await pg.evaluate("document.fonts.ready")   # 見出しと数字のフォント(Google Fonts)が届くまで待つ
            await pg.wait_for_timeout(300)
            out.append(await pg.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": h}))
        await b.close()
    return out


async def render_top(html: str, width: int = 1080, height: int = 1350) -> bytes:
    """紙面の上部だけを X 用の1枚に(4:5。スマホのタイムラインで切れずに出る縦横比)。"""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        await pg.set_content(html)
        await pg.evaluate("document.fonts.ready")
        await pg.wait_for_timeout(500)
        png = await pg.screenshot(clip={"x": 0, "y": 0, "width": width, "height": height})
        await b.close()
    return png


def x_first(xtext: str) -> str:
    """X の投稿案(--- 投稿1(…) --- の形)から、1本目の本文だけ。"""
    m = re.search(r"--- 投稿1[^\n]*---\n([\s\S]*?)(?=\n--- 投稿|\n(?:画像|出し方):|\Z)", xtext)
    return (m.group(1) if m else xtext).strip()


def x_image(out: pathlib.Path, key: str, html: str, name: str, no_images: bool) -> dict | None:
    if no_images:
        return None
    try:
        png = asyncio.run(render_top(html))
    except Exception as e:  # noqa: BLE001
        print("X 用の画像は作れませんでした:", e)
        return None
    f = f"{key}_x.json"
    write_json(out / f, {"name": name, "png": base64.b64encode(png).decode()})
    return {"file": f, "name": name}


async def render_pages(html: str, width: int = 1080, page_h: int = 1920) -> tuple[list[bytes], bytes]:
    """紙面(HTML)を、LINE で送れる画像(幅1080、1920pxごとに分割)と PDF に。"""
    from playwright.async_api import async_playwright
    from PIL import Image
    import io
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": width, "height": page_h}, device_scale_factor=1)
        await pg.set_content(html)
        await pg.evaluate("document.fonts.ready")
        await pg.wait_for_timeout(500)
        full = await pg.screenshot(full_page=True)
        # 記事や囲みの切れ目(各ブロックの上端)を取り、ページの区切りをそこに寄せる
        tops = await pg.evaluate("[...document.querySelectorAll('header, nav, article, section, .side, .chart, blockquote, footer')]"
                                 ".map(e => Math.round(e.getBoundingClientRect().top + window.scrollY))")
        pdf = await pg.pdf(width="1080px", height="1527px", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        await b.close()
    im = Image.open(io.BytesIO(full))
    out, y = [], 0
    tops = sorted(set(t for t in tops if 0 < t < im.height))
    while y < im.height:
        end = min(y + page_h, im.height)
        if end < im.height:
            cands = [t for t in tops if y + page_h * 0.55 <= t <= end]
            if cands:
                end = max(cands)
        part = im.crop((0, y, im.width, end))
        buf = io.BytesIO(); part.save(buf, "PNG", optimize=True); out.append(buf.getvalue())
        y = end
    return out, pdf


def save_pages(out: pathlib.Path, key: str, html: str, no_images: bool) -> list[dict]:
    """紙面の画像と PDF を ura/<key>_pN.json・ura/<key>_pdf.json に(暗号化)。"""
    if no_images:
        return []
    try:
        pngs, pdf = asyncio.run(render_pages(html))
    except Exception as e:  # noqa: BLE001
        print("紙面の画像は作れませんでした:", e)
        return []
    files = []
    for k, png in enumerate(pngs):
        f = f"{key}_p{k}.json"
        write_json(out / f, {"name": f"{key}_{k + 1:02d}.png", "png": base64.b64encode(png).decode()})
        files.append({"file": f, "name": f"{key}_{k + 1:02d}.png"})
    write_json(out / f"{key}_pdf.json", {"name": f"{key}.pdf", "pdf": base64.b64encode(pdf).decode()})
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days-before", type=int, default=7)
    ap.add_argument("--n", type=int, default=8, help="注目選手の数")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-all-images", action="store_true", help="出場全員のカード画像は作らない(注目選手だけ)")
    ap.add_argument("--only", default=None, help="この key の節だけ(試すとき)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD(試すとき)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    out = pathlib.Path(a.out) / "ura"
    out.mkdir(parents=True, exist_ok=True)
    series = [s for s in series_in_window(today, a.days_before) if not a.only or s["key"] == a.only]
    items = []
    xq: list = []          # 今日のX投稿: (時刻, 見出し, 本文, 画像)
    evening = None
    if series:
        d = rc.load_table()
        cards, meta = rc.build(d)
    allg = series_in_window(today, 60)
    for s in series:
        venue = rc.VENUES.get(s["jcd"], s.get("venue", ""))
        title = short_title(s.get("title") or s.get("title_page", ""), venue, s["grade"])
        nxt = next((x for x in allg if x["hd"] > s["hd"]), None)
        nxt_txt = (f"次号は {int(nxt['hd'][4:6])}/{int(nxt['hd'][6:])}〜の{rc.VENUES.get(nxt['jcd'], '')}"
                   f"「{short_title(nxt.get('title', ''), rc.VENUES.get(nxt['jcd'], ''), nxt['grade'])}」を予定しています。") if nxt else None
        r = ura_shinbun.make(title, [str(x["id"]) for x in s["racers"]], s["jcd"], a.n, "", d, cards, meta, nxt_txt)
        picks = r["picks"]
        images = []
        if not a.no_images:
            used: set = set()
            pages = [("早見表_待ち受け.png", chart_image_html(title, venue, r["wt"]))] + \
                    [(f"{c['id']}_{c['name']}.png", card_image_html(c, s["jcd"], f"{s['grade']}{venue} 出場選手カード", used))
                     for c, *_x in picks]
            n_main = len(pages)
            if not a.no_all_images:  # 出場全員ぶん(推しを探す読者用。note の「推し名簿」に貼れる)
                pick_ids = {c["id"] for c, *_x in picks}
                pages += [(f"{c['id']}_{c['name']}.png", card_image_html(c, s["jcd"], f"{s['grade']}{venue} 出場選手カード", used))
                          for c in r["sel"] if c["id"] not in pick_ids]
            try:
                pngs = asyncio.run(render_png(pages))
            except Exception as e:  # 描画の道具が無いときは画像なしで続ける
                print("画像は作れませんでした:", e)
                pngs = []
            for k, ((name, _), png) in enumerate(zip(pages, pngs)):
                f = f"{s['key']}_i{k}.json"
                write_json(out / f, {"name": name, "png": base64.b64encode(png).decode()})
                images.append({"file": f, "name": name, **({"extra": True} if k >= n_main else {})})
        pick_rows = [{"id": c["id"], "name": c["name"], "tag": t["t"]} for c, t, *_x in picks]
        if picks and (evening is None or s["hd"] < evening["hd"]):   # 夜の投稿: いちばん近いグレードレースの注目選手を日替わりで
            k = today.toordinal() % len(picks)
            c, t_ = picks[k][0], picks[k][1]
            evening = {"hd": s["hd"], "title": title, "venue": venue, "name": c["name"], "tag": t_["t"], "why": t_.get("why", ""),
                       "image": images[k + 1] if len(images) > k + 1 else None}
        pages_ = save_pages(out, s["key"], r["html"], a.no_images)
        write_json(out / f"{s['key']}.json", {
            "key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
            "html": r["html"], "note": r["note"], "x": r["x"], "picks": pick_rows, "images": images, "pages": pages_,
            "pdf": f"{s['key']}_pdf.json" if pages_ else None,
            "n": len(r["sel"]), "missing": r["missing"], "asof": meta["asof"]})
        items.append({"key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
                      "n": len(r["sel"]), "picks": [p["name"] for p in pick_rows], "images": len(images)})
        print(s["key"], title, f"{len(r['sel'])}人", f"画像{len(images)}枚", "見つからない:", r["missing"] or "なし")
    # 検証ラボ(reports/lab/*.json、毎週1本)も記事タブに
    import lab as labmod
    labs = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "reports/lab").glob("*.json")]
    for t in sorted(labs, key=lambda t: (t.get("made") or "", t["id"]), reverse=True)[:120]:   # ストック全部(新しい順。40本で切っていたため古い9本が出ていなかった)
        key = f"lab_{t['id']}"
        html_ = labmod.page(t, t.get("asof", ""))
        pages_ = save_pages(out, key, html_, a.no_images)
        write_json(out / f"{key}.json", {"key": key, "title": f"検証ラボ: {t['title']}", "grade": "LAB", "venue": "", "jcd": 0,
                                         "hd": (t.get("made") or "2026-01-01").replace("-", ""), "html": html_,
                                         "note": labmod.note_text(t), "x": labmod.x_text(t), "picks": [], "images": [], "n": 0, "missing": [],
                                         "pages": pages_, "pdf": f"{key}_pdf.json" if pages_ else None, "asof": t.get("asof", "")})
        items.append({"key": key, "title": f"検証ラボ: {t['title']}", "grade": "LAB", "venue": "", "jcd": 0,
                      "hd": (t.get("made") or "2026-01-01").replace("-", ""), "n": 0, "picks": [], "images": 0})
    # 毎日の「今日の理論ぶつけ」(朝の予想に付いた理論のノートから。買い目は出さない)
    try:
        import theory_daily
        from kyotei.publish import read_json
        dp = ROOT / f"docs/data/days/{today.isoformat()}.json"
        if dp.exists():
            t = theory_daily.build(today, read_json(dp))
            if t:
                key = f"theory_{today.strftime('%Y%m%d')}"
                pages_ = save_pages(out, key, t["html"], a.no_images)
                write_json(out / f"{key}.json", {"key": key, "title": t["title"], "grade": "毎日", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"),
                                                 "html": t["html"], "note": t["note"], "x": t["x"], "picks": [], "images": [], "n": 0, "missing": [],
                                                 "pages": pages_, "pdf": f"{key}_pdf.json" if pages_ else None, "asof": today.isoformat()})
                items.insert(0, {"key": key, "title": t["title"], "grade": "毎日", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"), "n": 0, "picks": [], "images": 0})
                print("theory daily:", t["n_races"], "races", t["n_conf"], "conflicts")
                xq.append(("8:20", "今日の理論ぶつけ", x_first(t["x"]), x_image(out, key, t["html"], "01_理論ぶつけ.png", a.no_images)))
            try:   # 昼: 今日の荒れそうなレース(文字だけ)
                import x_post
                now = dt.datetime.now(JST).replace(hour=12, minute=10, second=0, microsecond=0)
                at = x_post.morning_text(read_json(dp).get("races", []), now)
                if at:
                    xq.append(("12:10", "今日の荒れそうなレース", at, None))
            except Exception as ex:  # noqa: BLE001
                print("x arashi failed:", ex)
    except Exception as ex:  # noqa: BLE001  毎日の記事の失敗で、ほかの記事を止めない
        print("theory daily failed:", ex)
    # 夜: 火・金は検証ラボ(いちばん新しい1本)、ほかの日は次のグレードレースの注目選手
    try:
        if today.weekday() in (1, 4) and labs:
            # 火・金ごとに1本ずつ順番に(固定ポストで出した7本は後回し)。2026-10-06 からの火・金の回数で決める
            pinned = {"streak", "exst", "tenji", "wind", "slowdash", "final", "rokuyo"}
            order = sorted(labs, key=lambda t: (t["id"] in pinned, t.get("made") or "", t["id"]))
            n_slot = sum(1 for k in range((today - dt.date(2026, 10, 6)).days + 1)
                         if (dt.date(2026, 10, 6) + dt.timedelta(days=k)).weekday() in (1, 4))
            t = order[max(n_slot - 1, 0) % len(order)]
            xq.append(("20:00", f"検証ラボ: {t['title']}", x_first(labmod.x_text(t)),
                       x_image(out, f"lab_{t['id']}", labmod.page(t, t.get("asof", "")), "03_検証ラボ.png", a.no_images)))
        elif evening:
            import x_post
            p_ = {"title": evening["title"], "venue": evening["venue"], "hd": evening["hd"], "name": evening["name"], "tag": evening["tag"]}
            xq.append(("20:00", f"注目選手: {evening['name']}", x_post.evening_text(p_, {"tags": [{"t": evening["tag"], "why": evening["why"]}]}),
                       evening["image"]))
    except Exception as ex:  # noqa: BLE001
        print("x evening failed:", ex)
    # 「今日のX投稿」: その日の投稿文と画像を1か所に(コピーと画像の保存だけで出せる)
    if xq:
        from kyotei.xtext import xlen
        key = f"xpost_{today.strftime('%Y%m%d')}"
        wk = "月火水木金土日"[today.weekday()]
        title = f"今日のX投稿 {today.month}/{today.day}({wk})"
        xs = "\n\n".join(f"--- 投稿{i}({xlen(b)}字) {tm} {lbl} ---\n{b}" for i, (tm, lbl, b, _im) in enumerate(xq, 1))
        xs += "\n\n出し方: 時間は目安。画像は下の「画像」から保存して、同じ番号の投稿に添付。記事のリンクは本文に入れず、自分の返信に付ける"
        imgs = [im for _tm, _l, _b, im in xq if im]
        rows = "".join(f"<section><h3>{i}. {tm} {lbl}</h3><pre>{b}</pre><p>{'画像あり: ' + im['name'] if im else '文字だけ'}</p></section>"
                       for i, (tm, lbl, b, im) in enumerate(xq, 1))
        html_ = (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                 f"<style>body{{font-family:sans-serif;margin:16px;line-height:1.7}} pre{{white-space:pre-wrap;background:#f4efdf;padding:12px}}</style>"
                 f"</head><body><h2>{title}</h2>{rows}</body></html>")
        write_json(out / f"{key}.json", {"key": key, "title": title, "grade": "X", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"),
                                         "html": html_, "note": "\n\n".join(b for _t, _l, b, _i in xq), "x": xs, "picks": [], "images": imgs,
                                         "queue": [{"time": tm, "label": lbl, "text": b, "image": im["file"] if im else None} for tm, lbl, b, im in xq],
                                         "n": 0, "missing": [], "pages": [], "pdf": None, "asof": today.isoformat()})
        items.insert(0, {"key": key, "title": title, "grade": "X", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"), "n": 0, "picks": [], "images": len(imgs)})
        print("x queue:", [(tm, lbl) for tm, lbl, _b, _i in xq])
    write_json(out / "index.json", {"asof": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(),
                                    "days_before": a.days_before, "items": items})
    print(f"ura: {len(items)} 節 → {out}")


if __name__ == "__main__":
    main()
