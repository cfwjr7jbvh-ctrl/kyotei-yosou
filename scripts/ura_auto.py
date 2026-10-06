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
from kyotei import demand  # noqa: E402
from kyotei import seo  # noqa: E402
from kyotei.xtext import xlen as xlen_  # noqa: E402
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


async def render_split(html: str, width: int = 1080, height: int = 1350, max_n: int = 4) -> list[bytes]:
    """紙面の全部を X 用に4:5の画像で最大4枚に。文章の途中で切れないよう、表紙・各段(section・ひと言・奥付)の切れ目で分ける。
    1枚に入らない段は、その段の中の行(li・p)の切れ目で分ける。余白は紙の色で埋める。"""
    from playwright.async_api import async_playwright
    from PIL import Image
    import io
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        await pg.set_content(html)
        await pg.evaluate("document.fonts.ready")
        await pg.wait_for_timeout(500)
        # 切ってよい位置(上から): 表紙の下、各段の下、段の中の行の下
        cuts = await pg.evaluate("""() => {
          const ys = new Set();
          const add = (el) => { const r = el.getBoundingClientRect(); ys.add(Math.round(r.bottom + window.scrollY)); };
          document.querySelectorAll('header.cover, main > *, main section li, main section > p, main section > ul').forEach(add);
          return [...ys].sort((a, b) => a - b);
        }""")
        total = await pg.evaluate("document.documentElement.scrollHeight")
        bg = await pg.evaluate("getComputedStyle(document.body).backgroundColor")
        full = Image.open(io.BytesIO(await pg.screenshot(full_page=True)))
        await b.close()
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", bg or "")
    color = tuple(int(x) for x in m.groups()) if m else (244, 239, 223)
    end_ = min(max(cuts) if cuts else total, total)
    band = 64                                   # 2枚目からの上の帯(「つづき 2/3」)
    spans, top = [], 0
    while top < end_ - 40 and len(spans) < max_n:
        room = height - (band if spans else 0)
        ok = [c for c in cuts if top + 200 < c <= top + room]
        bottom = max(ok) if ok else min(top + room, end_)
        if len(spans) == max_n - 1:
            bottom = min(top + room, end_)
        spans.append((top, bottom))
        top = bottom
    from PIL import ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 30)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    out = []
    for i, (t, bt) in enumerate(spans):
        img = Image.new("RGB", (width, height), color)
        y0 = 0
        if i:
            d_ = ImageDraw.Draw(img)
            d_.rectangle([0, 0, width, band - 8], fill=(23, 25, 28))
            d_.text((40, 12), f"ミカタ新聞 ・ つづき {i + 1}/{len(spans)}", font=font, fill=(255, 225, 0))
            y0 = band
        img.paste(full.crop((0, t, width, bt)), (0, y0))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def card_images(out: pathlib.Path, key: str, htmls: list[str], no_images: bool) -> list[dict]:
    """X 用のカード(1080×1350 で作った紙面)をそのまま画像に。"""
    if no_images:
        return []
    res = []
    for i, h in enumerate(htmls[:4]):
        try:
            png = asyncio.run(render_top(h))
        except Exception as e:  # noqa: BLE001
            print("カードの画像は作れませんでした:", e)
            continue
        f = f"{key}_c{i + 1}.json"
        write_json(out / f, {"name": f"{i + 1}_ミカタ新聞.png", "png": base64.b64encode(png).decode()})
        res.append({"file": f, "name": f"{i + 1}_ミカタ新聞.png"})
    return res


def x_images(out: pathlib.Path, key: str, html: str, name: str, no_images: bool) -> list[dict]:
    """紙面の全部を最大4枚に(X は1投稿に画像4枚まで)。"""
    if no_images:
        return []
    try:
        pngs = asyncio.run(render_split(html))
    except Exception as e:  # noqa: BLE001
        print("X 用の画像(全部)は作れませんでした:", e)
        im = x_image(out, key, html, name, no_images)
        return [im] if im else []
    res = []
    for i, png in enumerate(pngs):
        f = f"{key}_x{i + 1}.json"
        write_json(out / f, {"name": f"{i + 1}_{name}", "png": base64.b64encode(png).decode()})
        res.append({"file": f, "name": f"{i + 1}_{name}"})
    return res


NETA_START = dt.date(2026, 10, 6)   # 「1枚1ネタ」の1日目(前の日の21:30に投票で出題 → 次の日の15:30に答え)


def polled_yesterday(today: dt.date) -> bool:
    """前の日の21:30の投票を、実際に出したか(reports/x_drafts/posted.json)。出していなければ「昨日の投票の答え」と書かない。"""
    p = ROOT / "reports/x_drafts/posted.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("poll") == (today - dt.timedelta(days=1)).isoformat()
    except Exception:  # noqa: BLE001
        return False


def neta_card_html(r: dict) -> str:
    from kyotei.card_render import gull_svg, LANE_BG
    import html as _h
    e_ = _h.escape
    F = "'Noto Sans CJK JP','Zen Kaku Gothic New',sans-serif"
    col = {"多い": "#c8141c", "少ない": "#1f6fd1", "ほぼ同じ": "#6b7680"}[r["answer"]]
    v = {"多い": "ふだんより多い", "少ない": "ふだんより少ない", "ほぼ同じ": "ふだんとほぼ同じ"}[r["answer"]]
    bars = ""
    sub = r["line"].split("のは")[0] + "回数" if r.get("a") is not None and "のは" in r["line"] else r["line"]
    note = ""
    if r["answer"] == "ほぼ同じ" and r.get("a") is not None and abs(r["a"] - r["b"]) >= 0.5:
        note = '<div class="nt">この差は、たまたまでも出るくらいの幅です</div>'
    if r.get("a") is not None and r.get("b") is not None:
        mx = max(r["a"], r["b"], 1) * 1.08
        fmt = lambda v: f"{v:.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v)}"  # noqa: E731
        bars = ('<div class="bars">'
                f'<div class="br"><b>この条件</b><div class="tr"><div class="fl" style="width:{r["a"] / mx * 100:.1f}%;background:{col}"></div></div><em>{fmt(r["a"])}回</em></div>'
                f'<div class="br"><b>{e_(r.get("refl") or "ふだん")}</b><div class="tr"><div class="fl" style="width:{r["b"] / mx * 100:.1f}%;background:#8a949c"></div></div><em>{fmt(r["b"])}回</em></div></div>')
    lanes = "".join(f'<i style="background:{c}"></i>' for c in LANE_BG)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
html,body{{margin:0}} .c{{width:1080px;height:1350px;background:#f4efdf;font-family:{F};color:#14212c;position:relative;overflow:hidden}}
.top{{background:#17191c;color:#fff;padding:40px 60px 34px;position:relative}} .top small{{font:900 30px {F};color:#ffe100;letter-spacing:.06em}}
.top p{{margin:12px 0 0;font:700 28px/1.4 {F};color:#c9ced2}}
.lb{{position:absolute;left:0;right:0;bottom:-16px;height:16px;display:flex;gap:4px;padding:4px 0;background:#f4efdf}} .lb i{{flex:1}}
.q{{margin:90px 60px 0;font:900 64px/1.35 {F}}} .q span{{display:block;font:700 30px {F};color:#56636e;margin-bottom:14px}}
.v{{margin:50px 60px 0;background:{col};color:#fff;padding:26px 36px;font:900 72px/1.1 {F};display:inline-block}}
.n{{margin:46px 60px 0;font:700 38px/1.5 {F}}}
.bars{{margin:60px 60px 0}} .br{{display:flex;align-items:center;gap:20px;margin-bottom:26px;font:900 34px {F}}}
.br b{{width:230px;font:700 30px/1.25 {F};color:#56636e}} .br .tr{{flex:1;height:70px;background:#e3dcc6;position:relative}}
.br .fl{{height:100%}} .br em{{font-style:normal;width:130px;text-align:right}}
.nt{{margin:10px 60px 0;font:700 30px/1.4 {F};color:#56636e}}
.ft{{position:absolute;left:60px;right:60px;bottom:44px;display:flex;align-items:center;gap:18px;font:900 30px/1.3 {F}}}
.ft small{{display:block;font:700 22px {F};color:#56636e}} .ft .at{{margin-left:auto;color:#c8141c;font:900 34px {F}}}
</style></head><body><div class="c"><div class="top"><small>ミカタ検証ラボ ・ 1枚1ネタ</small><p>{e_(r['title'])}</p><div class="lb">{lanes}</div></div>
<div class="q"><span>この条件だと、どうなる?</span>「{e_(r['name'])}」</div><div class="v">{e_(v)}</div><div class="n">{e_(sub)}</div>{bars}{note}
<div class="ft">{gull_svg(80, bg="#ffffff", cls="f")}<div>17万レースで数えた<small>公式の成績データ(2023年10月〜)を独自に集計</small></div><div class="at">@mikata_kyotei</div></div></div></body></html>"""


def neta_image(out: pathlib.Path, r: dict, no_images: bool) -> dict | None:
    if no_images:
        return None
    try:
        png = asyncio.run(render_top(neta_card_html(r), 1080, 1350))
    except Exception as e:  # noqa: BLE001
        print("1枚1ネタの画像は作れませんでした:", e)
        return None
    key = "neta_" + r["id"].replace(":", "_")
    write_json(out / f"{key}_x.json", {"name": "02_1枚1ネタ.png", "png": base64.b64encode(png).decode()})
    return {"file": f"{key}_x.json", "name": "02_1枚1ネタ.png"}


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


def series_name_tag(x: dict) -> tuple[str, str]:
    """大会の短い名前と、ハッシュタグ(記号・空白を抜いたもの)。"""
    nm = short_title(x.get("title") or x.get("title_page", ""), rc.VENUES.get(x["jcd"], ""), x["grade"]).split(" ", 1)[-1]
    return nm, re.sub(r"[\s・･!！?？\-]", "", unicodedata.normalize("NFKC", nm))


FIXED_SLOTS = ["8:20", "12:10", "15:30", "18:30", "20:00", "21:30"]


def study_time(deadline: str, used: list[str]) -> str:
    """ミカタ新聞を出す時間: 締切の直前ではなく、予想する人がスマホを見る時間帯(朝の通勤・昼休み・夕方・帰り道)に。
    売上の9割は締切10分前から入る(展示を見てから買う)が、予想を組み立てるのはその前。
    朝のレース(〜13時)→ 8:50、昼(〜17時)→ 11:40、夕方(〜19:30)→ 16:40、ナイター → 18:10。
    締切の60分前より遅くならないように。同じ時間帯に2本なら25分ずらす(決まった投稿の時間とも重ねない)。"""
    hh, mm = map(int, deadline.split(":"))
    dl = hh * 60 + mm
    base = 8 * 60 + 50 if dl < 13 * 60 else 11 * 60 + 40 if dl < 17 * 60 else 16 * 60 + 40 if dl < 19 * 60 + 30 else 18 * 60 + 10
    t = min(base, dl - 60)
    taken = {int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in used + FIXED_SLOTS}
    while any(abs(t - u) < 15 for u in taken) and t + 25 <= dl - 45:
        t += 25
    return f"{t // 60}:{t % 60:02d}"


def news_posts(live: list[dict], races: list[dict], day: dt.date | None = None, top: int = 4, cards: dict | None = None) -> list[tuple]:
    """ミカタ新聞(これからのレースの1レース特集): 今日の全レースから、買う人が多そうなレース(3連単の売上の見込み)を選ぶ。
    1場1レースずつ大きい順に、足りなければ2レース目も。予想する人が見る時間帯(study_time)に X へ(画像=新聞の上の部分)。
    → [(時刻, 見出し, 本文, 締切, 見込み, レース, 大会 or None, 大会名 or "")]"""
    from kyotei.xtext import xlen
    ser = {}
    for x in live:
        ser.setdefault(x["jcd"], x)
    a1s = {j: demand.day_a1(races, j) for j in {r.get("jcd") for r in races}}
    cands = []
    for rr in races:
        if not rr.get("deadline") or not rr.get("boats"):
            continue
        x = ser.get(rr.get("jcd"))
        rt = str(rr.get("race_type") or "")
        sc = demand.score(x["grade"] if x else None, rt, rr.get("rno"), day, rr["deadline"], rr.get("jcd"), a1s.get(rr.get("jcd")))
        cands.append((sc, rr, x))
    cands.sort(key=lambda c: -c[0])
    picked, per = [], {}
    for rnd in (1, 2):
        for sc, rr, x in cands:
            if len(picked) >= top:
                break
            if sc < 0.5 or rr in [p[1] for p in picked] or per.get(rr["jcd"], 0) >= rnd:
                continue
            picked.append((sc, rr, x))
            per[rr["jcd"]] = per.get(rr["jcd"], 0) + 1
    out, used = [], []
    picked.sort(key=lambda c: c[1]["deadline"])
    for sc, rr, x in picked:
        rt = str(rr.get("race_type") or "")
        nm, tag = series_name_tag(x) if x else ("", f"ボートレース{rr['venue']}")
        at = study_time(rr["deadline"], used)
        used.append(at)
        sm = rr.get("th_sum") or {}
        notes = [n for n in (rr.get("theories") or []) if n.get("kind") != "occult"]
        # 検索される言葉: 1行目に場名+R・レースの種類・大会名、本文に選手名、タグは2個(src/kyotei/seo.py)
        head = f"{rr['venue']}{rr['rno']}R {rt}{('|' + nm) if nm else ''}({rr['deadline']}締切)【ミカタ新聞】"
        foot = seo.x_tags(rr["venue"], nm or None)
        import race_feature as _rf
        st_ = _rf.story(rr, cards)
        body = None
        if st_:   # 問い → 本線と狙い目かも → ここを見て決める → あなたは?(「だから何?」で終わらせない)
            h_ = st_["branches"][0]
            n_ = st_["branches"][1] if len(st_["branches"]) > 1 else None
            lines = [f"本線 {h_['lane']}号艇{('の' + h_['type']) if h_['type'] else ''} {_rf._pct(h_['p'])}%"]
            lines.append(f"狙い目かも? {n_['lane']}号艇{('の' + n_['type']) if n_['type'] else ''} {_rf._pct(n_['p'])}%(ふだんの{n_['ratio']:.1f}倍)" if n_ else "狙い目かも? 本線が堅め")
            for k in (2, 1, 0):
                chk = ("見るのはここ: " + " / ".join(st_["short"][:k])) if k else ""
                b = (f"{head}\n{st_['hook']}🔥\n\n" + "\n".join(lines) + (f"\n{chk}" if chk else "")
                     + f"\n\n材料は画像で📰 あなたはどっち?\n{foot}")
                if xlen(b) <= 280:
                    body = b
                    break
        if body is None:
            mid = (f"インに有利: {sm['plus'][0]}\nインに不利: {sm['minus'][0]}\n\nあなたはどっちに乗る?" if sm.get("conflict")
                   else "6艇の1着の見込みと展開は画像で📰 あなたの本線は?")
            b = f"{head}\n\n{mid}\n{foot}"
            body = b if xlen(b) <= 280 else None
        if body:
            out.append((at, f"新聞: {rr['venue']}{rr['rno']}R {rt}", body, rr["deadline"], sc, rr, x, nm))
    return out


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
    poll_today = None      # 21:30 の投票(選択肢)
    event_items: list = []  # 大会の準優・優勝戦の投稿(締切つき)
    more_imgs: dict = {}    # 見出し → 画像の一覧(ミカタ新聞は全部を最大4枚)
    evening = None
    hayami: dict = {}      # 節の key → (早見表の画像, コース別の上位)
    d = None
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
        hayami[s["key"]] = (images[0] if images else None, r["wt"])
        pick_rows = [{"id": c["id"], "name": c["name"], "tag": t["t"]} for c, t, *_x in picks]
        first_day = dt.datetime.strptime(s["hd"], "%Y%m%d").date()
        sc_s = demand.series_score(s["grade"], s["jcd"], None, first_day + dt.timedelta(days=SERIES_DAYS - 1))
        # 夜の投稿: 注目度がいちばん高い(同じなら近い)グレードレースの注目選手を日替わりで
        if picks and (evening is None or (-sc_s, s["hd"]) < (-evening["score"], evening["hd"])):
            k = today.toordinal() % len(picks)
            c, t_ = picks[k][0], picks[k][1]
            evening = {"score": sc_s, "hd": s["hd"], "title": title, "venue": venue, "name": c["name"], "tag": t_["t"], "why": t_.get("why", ""),
                       "image": images[k + 1] if len(images) > k + 1 else None}
        pages_ = save_pages(out, s["key"], r["html"], a.no_images)
        write_json(out / f"{s['key']}.json", {
            "key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
            "html": r["html"], "note": r["note"], "x": r["x"], "picks": pick_rows, "images": images, "pages": pages_,
            "pdf": f"{s['key']}_pdf.json" if pages_ else None,
            "n": len(r["sel"]), "missing": r["missing"], "asof": meta["asof"]})
        items.append({"key": s["key"], "title": title, "grade": s["grade"], "venue": venue, "jcd": s["jcd"], "hd": s["hd"],
                      "score": sc_s, "stars": demand.stars(sc_s), "n": len(r["sel"]), "picks": [p["name"] for p in pick_rows], "images": len(images)})
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
            try:
                import publish_log
                on_x = {r["key"][4:] for r in publish_log.load() if r["key"].startswith("lab_") and r["channel"] == "X"}
            except Exception:  # noqa: BLE001
                on_x = set()
            first = ["saying", "lucky7", "manshu", "tilt", "hot", "moon", "humid", "lane6", "a1in", "series", "motor", "c1lose", "e30"]   # X で先に出す順(話題になりやすい回から)
            order = sorted(labs, key=lambda t: (t["id"] in pinned, first.index(t["id"]) if t["id"] in first else 99, t.get("made") or "", t["id"]))
            order = [t for t in order if t["id"] not in on_x] or order   # X に出した回はとばす
            n_slot = sum(1 for k in range((today - dt.date(2026, 10, 6)).days + 1)
                         if (dt.date(2026, 10, 6) + dt.timedelta(days=k)).weekday() in (1, 4))
            t = order[max(n_slot - 1, 0) % len(order)]
            xq.append(("20:00", f"検証ラボ: {t['title']}", seo.with_tags(x_first(labmod.x_text(t)), "#競艇 #ボートレース"),
                       x_image(out, f"lab_{t['id']}", labmod.page(t, t.get("asof", "")), "03_検証ラボ.png", a.no_images)))
        elif evening:
            import x_post
            p_ = {"title": evening["title"], "venue": evening["venue"], "hd": evening["hd"], "name": evening["name"], "tag": evening["tag"]}
            xq.append(("20:00", f"注目選手: {evening['name']}", x_post.evening_text(p_, {"tags": [{"t": evening["tag"], "why": evening["why"]}]}),
                       evening["image"]))
    except Exception as ex:  # noqa: BLE001
        print("x evening failed:", ex)
    # 15:30 1枚1ネタ(前の日の投票の答え)と 21:30 投票(次の日の1枚1ネタを先に問題に)
    try:
        rows = labmod.neta_items(labs)
        if rows:
            k = (today - NETA_START).days
            if k >= 0:
                r_ = rows[k % len(rows)]
                xq.append(("15:30", "1枚1ネタ", seo.with_tags(labmod.neta_text(r_, from_poll=polled_yesterday(today)), "#競艇 #ボートレース"), neta_image(out, r_, a.no_images)))
            r2 = rows[(k + 1) % len(rows)]
            pq = labmod.neta_poll(r2)
            xq.append(("21:30", "投票(答えは明日15:30)", seo.with_tags(pq["text"], "#競艇 #ボートレース") + "\n\n選択肢: " + " / ".join(pq["options"]), None))
            poll_today = pq
    except Exception as ex:  # noqa: BLE001
        print("x neta failed:", ex)
    # ミカタ新聞: これからのレースのうち、買う人が多そうなレース(全場から)。予想する人が見る時間帯に、1レース特集の上の部分を画像にして X へ
    try:
        from kyotei.publish import read_json as _rj2
        dp2 = ROOT / f"docs/data/days/{today.isoformat()}.json"
        live = [x for x in series_in_window(today, 0) if dt.datetime.strptime(x["hd"], "%Y%m%d").date() <= today]
        if dp2.exists():
            races = _rj2(dp2).get("races", [])
            import race_feature
            if not series:
                d = rc.load_table()
                cards, meta = rc.build(d)
            for at, lbl, body, dl, sc, rr, x, nm in news_posts(live, races, today, cards=cards):
                img = None
                try:
                    f_ = race_feature.make(nm, x["grade"] if x else "", rr, cards, sc, today)
                    key_f = f"race_{today:%Y%m%d}_{rr['jcd']:02d}{int(rr['rno']):02d}"
                    ims = card_images(out, key_f, race_feature.x_cards(nm, x["grade"] if x else "", rr, cards, today), a.no_images)   # X 用の大きな文字のカード2枚
                    img = ims[0] if ims else None
                    more_imgs[lbl] = ims
                    pages_f = save_pages(out, key_f, f_["html"], a.no_images)
                    write_json(out / f"{key_f}.json", {"key": key_f, "title": f_["title"], "grade": "新聞", "venue": rr["venue"], "jcd": rr["jcd"],
                                                       "hd": f"{today:%Y%m%d}", "html": f_["html"], "note": f_["note"],
                                                       "x": f"--- 投稿1({xlen_(body)}/280) {at} ---\n{body}\n\n出し方: {at}に自動で出ます(画像つき)",
                                                       "picks": [], "images": ims, "pages": pages_f,
                                                       "pdf": f"{key_f}_pdf.json" if pages_f else None, "n": 6, "missing": [], "asof": today.isoformat()})
                    items.insert(0, {"key": key_f, "title": f_["title"], "grade": "新聞", "venue": rr["venue"], "jcd": rr["jcd"], "hd": f"{today:%Y%m%d}",
                                     "score": sc, "stars": demand.stars(sc), "n": 6, "picks": [], "images": len(ims)})
                except Exception as ex:  # noqa: BLE001
                    print("race feature failed:", ex)
                xq.append((at, lbl, body, img))
                event_items.append({"time": at, "deadline": dl, "label": lbl[4:]})
    except Exception as ex:  # noqa: BLE001
        print("x news failed:", ex)
    # 大会の速報(x_post.py の event が、レース結果を見て出す): 今日開催中のグレードレースの名前・タグ・この場の1号艇のふだん
    # 前の日: 18:30 に「明日から◯◯」+ 出場選手のコース別ベスト3(早見表の画像)
    series_today: list = []
    try:
        from kyotei.publish import read_json as _rj3
        dp3 = ROOT / f"docs/data/days/{today.isoformat()}.json"
        races3 = _rj3(dp3).get("races", []) if dp3.exists() else []
        jcds3 = {r_.get("jcd") for r_ in races3}
        allw = series_in_window(today, 1)
        seen_j: set = set()
        for x in allw:
            nm, tag = series_name_tag(x)
            same = [y for y in allw if y["jcd"] == x["jcd"] and y.get("title") == x.get("title")]
            started = any(dt.datetime.strptime(y["hd"], "%Y%m%d").date() <= today for y in same)
            if started:
                if x["jcd"] in seen_j or x["jcd"] not in jcds3:
                    continue
                seen_j.add(x["jcd"])
                in1 = None
                if d is not None:
                    v1 = d[(d["jcd"] == x["jcd"]) & (d["lane"] == 1) & d["finish"].notna()]
                    in1 = round(float((v1["finish"] == 1).mean()) * 100) if len(v1) >= 200 else None
                final = any(r_.get("jcd") == x["jcd"] and "優勝戦" in str(r_.get("race_type") or "") and "準" not in str(r_.get("race_type") or "")
                            for r_ in races3)
                series_today.append({"jcd": x["jcd"], "venue": rc.VENUES.get(x["jcd"], ""), "name": nm, "tag": tag, "grade": x["grade"],
                                     "final": final, "in1": in1})
            elif x["key"] in hayami and hayami[x["key"]][0] and x["hd"] == (today + dt.timedelta(days=1)).strftime("%Y%m%d"):
                img, wt = hayami[x["key"]]
                venue = rc.VENUES.get(x["jcd"], "")
                top1 = (wt.get(1) or [None])[0]
                body = (f"【明日から】{x['grade']} {nm}({venue})\n\n出場{len(x.get('racers') or [])}人の「コース別ベスト3」を1枚にしました📰 保存して現地のおともに"
                        + (f"\n\n1コースの逃げ切りがいちばん多いのは{top1['name']}選手({top1['k']}/{top1['n']}走)" if top1 else "")
                        + f"\n\nあなたの推しは入ってる?\n#{tag} #ボートレース")
                xq.append(("18:30", f"明日から: {nm}", body, img))
    except Exception as ex:  # noqa: BLE001
        print("x series failed:", ex)
    xq.sort(key=lambda q: tuple(int(v) for v in q[0].split(":")))
    # 「今日のX投稿」: その日の投稿文と画像を1か所に(コピーと画像の保存だけで出せる)
    if xq:
        from kyotei.xtext import xlen
        key = f"xpost_{today.strftime('%Y%m%d')}"
        wk = "月火水木金土日"[today.weekday()]
        title = f"今日のX投稿 {today.month}/{today.day}({wk})"
        xs = "\n\n".join(f"--- 投稿{i}({xlen(b)}字) {tm} {lbl} ---\n{b}" for i, (tm, lbl, b, _im) in enumerate(xq, 1))
        xs += "\n\n出し方: 時間は目安。画像は下の「画像」から保存して、同じ番号の投稿に添付。記事のリンクは本文に入れず、自分の返信に付ける"
        imgs = [x for _tm, l_, _b, im in xq for x in (more_imgs.get(l_) or ([im] if im else []))]
        rows = "".join(f"<section><h3>{i}. {tm} {lbl}</h3><pre>{b}</pre><p>{'画像あり: ' + im['name'] if im else '文字だけ'}</p></section>"
                       for i, (tm, lbl, b, im) in enumerate(xq, 1))
        html_ = (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                 f"<style>body{{font-family:sans-serif;margin:16px;line-height:1.7}} pre{{white-space:pre-wrap;background:#f4efdf;padding:12px}}</style>"
                 f"</head><body><h2>{title}</h2>{rows}</body></html>")
        write_json(out / f"{key}.json", {"key": key, "title": title, "grade": "X", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"),
                                         "html": html_, "note": "\n\n".join(b for _t, _l, b, _i in xq), "x": xs, "picks": [], "images": imgs,
                                         "queue": [{"time": tm, "label": lbl, "text": (b.split("\n\n選択肢: ")[0] if tm == "21:30" else b),
                                                    "image": im["file"] if im else None,
                                                    **({"images": [x["file"] for x in more_imgs[lbl]]} if more_imgs.get(lbl) else {}),
                                                    **({"poll": poll_today} if tm == "21:30" and poll_today else {}),
                                                    **({"deadline": next(e["deadline"] for e in event_items if e["time"] == tm and e["label"] in lbl)}
                                                       if lbl.startswith("新聞:") else {})} for tm, lbl, b, im in xq],
                                         "n": 0, "missing": [], "pages": [], "pdf": None, "asof": today.isoformat(), "series_today": series_today})
        items.insert(0, {"key": key, "title": title, "grade": "X", "venue": "", "jcd": 0, "hd": today.strftime("%Y%m%d"), "n": 0, "picks": [], "images": len(imgs)})
        print("x queue:", [(tm, lbl) for tm, lbl, _b, _i in xq])
    # 出した記事の記録(reports/published.json)を一覧と中身に付ける
    try:
        import publish_log
        pubs = publish_log.summary()
        for it in items:
            if it["key"] in pubs:
                it["pub"] = pubs[it["key"]]
                f = out / f"{it['key']}.json"
                if f.exists():
                    from kyotei.publish import read_json as _rj
                    dd = _rj(f)
                    dd["pub"] = pubs[it["key"]]
                    write_json(f, dd)
    except Exception as ex:  # noqa: BLE001
        print("published log failed:", ex)
    write_json(out / "index.json", {"asof": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(),
                                    "days_before": a.days_before, "items": items})
    print(f"ura: {len(items)} 節 → {out}")


if __name__ == "__main__":
    main()
