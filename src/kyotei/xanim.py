"""X 用の「データを調べてみました」カードと、そのアニメーション(棒が伸びる短い動画)。

2026-10-07 ユーザー「明らかにAIで作ってますみたいな感じではなく、伸びてる人の真似していこう」(伸びている人の例: 問いのタイトル+棒グラフ+大きな数字+数えた数、
アニメーションつき)。人気投稿の分析でも、動画は画像の約2倍伸びやすかった。
- chart_html(spec, animate): 1080×1350 のカード。animate=True で棒が下から伸び、数字が数え上がり、差が出てくる(約1.6秒)。False は最後の形の静止画
- render_png(html) / render_mp4(html): 画像 / 動画(H.264、約5秒。最後の形で止まる)。動画は playwright で録って ffmpeg で mp4 に

spec = {"title": "今節2連勝中だと、3着以内率はどれだけ変わる?", "sub": "公式の成績データ(2023年10月〜)から",
        "bars": [{"label": "ふだん", "value": 50.5, "color": "#5fbf9a"}, {"label": "今節2連勝中", "value": 57.3, "color": "#ef8a75"}],
        "unit": "%", "panel": [("ふだん→この条件", "51%→57%"), ("数えた数", "24,403走")], "handle": "@mikata_kyotei"}
"""
from __future__ import annotations

import html as _h
import json
import pathlib
import shutil
import subprocess
import tempfile

F = "'Noto Sans CJK JP','Zen Kaku Gothic New',sans-serif"
NUM = "'Barlow Condensed','Noto Sans CJK JP',sans-serif"
BG, PANEL, INK, MUTE, GRID = "#0f1f33", "#16294a", "#ffffff", "#9fb0c6", "#24385a"
UP, DOWN, SAME, BASE = "#ef8a75", "#6fa8ff", "#c7ced8", "#5fbf9a"


def _fmt(v: float, unit: str) -> str:
    """数字の書き方の決まり: 10以上は整数(「57%」)、10未満は小数1桁(「3.1%」)。"""
    s = f"{v:.1f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{int(v + 0.5) if v >= 0 else -int(-v + 0.5)}"   # 四捨五入(round は偶数への丸めなので使わない)
    return s + unit


def _r(v: float) -> float:
    return float(_fmt(v, ""))


def chart_html(spec: dict, animate: bool = True) -> str:
    e = _h.escape
    bars = spec["bars"][:4]
    unit = spec.get("unit", "%")
    vmax = max(b["value"] for b in bars)
    vmin = min(b["value"] for b in bars)
    # 縦の目盛り: 差が見えるように下を切る(0からにすると差が見えない)。下の端はキリのいい数に
    step = 10 if vmax - vmin > 25 else 5
    lo = max(0, (int(vmin * 0.7) // step) * step)
    hi = ((int(vmax * 1.12) // step) + 1) * step
    ticks = list(range(lo, hi + 1, step))
    H = 470   # グラフの高さ(px)
    ypx = lambda v: (v - lo) / (hi - lo) * H  # noqa: E731
    grid = "".join(f'<div class="gl" style="bottom:{ypx(t):.0f}px"><span>{t}</span></div>' for t in ticks)
    cols = ""
    for i, b in enumerate(bars):
        d = ""
        if i > 0 and spec.get("delta", True):
            dv = _r(b["value"]) - _r(bars[0]["value"])   # 見えている数字どうしの差
            d = f'<div class="dl" style="color:{b["color"]}">{"+" if dv >= 0 else "−"}{_fmt(abs(dv), "")}</div>'
        cols += (f'<div class="col"><div class="stack" style="height:{ypx(b["value"]):.0f}px">{d}'
                 f'<div class="val" data-v="{b["value"]}" data-u="{e(unit)}">{_fmt(b["value"], unit)}</div>'
                 f'<div class="bar" style="background:{b["color"]};animation-delay:{0.15 + i * 0.2:.2f}s"></div></div>'
                 f'<div class="lb">{e(b["label"])}</div></div>')
    panel = "".join(f'<div class="pi"><small>{e(k)}</small><b>{e(v)}</b></div>' for k, v in (spec.get("panel") or [])[:3])
    t_len = len(spec["title"])
    t_size = 64 if t_len <= 20 else 56 if t_len <= 26 else 48 if t_len <= 34 else 42
    anim = """
.bar{transform-origin:bottom;animation:grow 1.0s cubic-bezier(.2,.8,.2,1) both}
@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
.val,.dl,.panel{animation:fade .5s ease-out both} .val{animation-delay:.9s} .dl{animation-delay:1.3s} .panel{animation-delay:1.5s}
@keyframes fade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}""" if animate else ""
    count_js = """<script>
document.querySelectorAll('.val').forEach((el)=>{const v=+el.dataset.v,u=el.dataset.u,t0=performance.now()+700;
const f=(t)=>{const k=Math.min(1,Math.max(0,(t-t0)/900));const x=v*(1-Math.pow(1-k,3));
el.textContent=(Math.abs(v)<10?x.toFixed(1):Math.round(x))+u;if(k<1)requestAnimationFrame(f)};requestAnimationFrame(f)});
</script>""" if animate else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
html,body{{margin:0;background:{BG}}} .c{{width:1080px;height:1350px;background:{BG};font-family:{F};color:{INK};position:relative;overflow:hidden}}
.hd{{padding:96px 70px 0}} .hd h1{{margin:0;font:900 {t_size}px/1.3 {F};letter-spacing:.01em;word-break:keep-all;overflow-wrap:anywhere;line-break:strict}} .hd p{{margin:16px 0 0;font:700 28px/1.4 {F};color:{MUTE}}}
.box{{margin:36px 50px 0;background:{PANEL};border-radius:28px;padding:30px 50px 20px}}
.ch{{position:relative;height:{H}px;margin:104px 10px 0 70px}}
.gl{{position:absolute;left:0;right:0;border-top:2px solid {GRID}}} .gl span{{position:absolute;left:-70px;top:-18px;font:500 26px {NUM};color:{MUTE}}}
.cols{{position:absolute;left:0;right:0;bottom:0;top:0;display:flex;justify-content:space-around;align-items:flex-end}}
.col{{width:{int(560 / max(len(bars), 2))}px;display:flex;flex-direction:column;align-items:center;position:relative;height:100%;justify-content:flex-end}}
.stack{{position:relative;width:100%}} .bar{{position:absolute;inset:0;border-radius:18px 18px 4px 4px}}
.val{{position:absolute;left:-40px;right:-40px;bottom:100%;margin-bottom:12px;text-align:center;font:700 66px {NUM};white-space:nowrap}}
.dl{{position:absolute;left:-40px;right:-40px;bottom:100%;margin-bottom:90px;text-align:center;font:700 40px {NUM}}}
.lb{{position:absolute;top:100%;margin-top:18px;font:900 32px/1.25 {F};text-align:center;width:160%;left:-30%}}
.panel{{display:flex;gap:20px;margin:28px 50px 0}} .pi{{flex:1;background:{PANEL};border-radius:22px;padding:22px 28px}}
.pi small{{display:block;font:700 26px {F};color:{MUTE}}} .pi b{{display:block;margin-top:6px;font:700 52px {NUM};white-space:nowrap}}
.hn{{position:absolute;right:56px;top:36px;font:700 26px {F};color:{MUTE}}}{anim}
</style></head><body><div class="c"><div class="hd"><h1>{e(spec["title"])}</h1><p>{e(spec.get("sub") or "")}</p></div>
<div class="box"><div class="ch">{grid}<div class="cols">{cols}</div></div><div style="height:80px"></div></div>
<div class="panel">{panel}</div><div class="hn">{e(spec.get("handle") or "@mikata_kyotei")}</div></div>{count_js}</body></html>"""


def mikata_html(spec: dict, animate: bool = True) -> str:
    """ミカタの紙面の型(2026-10-08 ユーザー「添付したやつとそっくりすぎ、ミカタ感をもっとだそう」)。
    黒い見出しの帯+6色の枠の帯+生成りの紙。棒は「スタートで並んで伸びていく艇」に見立てて横に伸び、先頭に艇の色の舳先、
    差は旗で。最後にミカタ(カモメの記者)が吹き出しでひと言。"""
    from .card_render import gull_svg, LANE_BG
    e = _h.escape
    bars = spec["bars"][:3]
    unit = spec.get("unit", "%")
    vmax = max(b["value"] for b in bars)
    vmin = min(b["value"] for b in bars)
    lo = max(0.0, vmin - (vmax - vmin) * 2.2 - 5)   # 差が見えるように左を切る(目盛りで切ったことを見せる)
    lo = float(int(lo // 5 * 5))
    hi = vmax + (vmax - lo) * 0.18
    W = 600
    xpx = lambda v: (v - lo) / (hi - lo) * W  # noqa: E731
    rows = ""
    for i, b in enumerate(bars):
        lane = b.get("lane", 6 if i == 0 else 3)
        col = "#9a937f" if i == 0 else {"多い": "#c8141c", "少ない": "#0b5fb4", "ほぼ同じ": "#56636e"}.get(spec.get("tone"), "#c8141c")
        flag = ""
        if i > 0:
            dv = _r(b["value"]) - _r(bars[0]["value"])
            flag = f'<span class="flag" style="background:{col}">{"+" if dv >= 0 else "−"}{_fmt(abs(dv), "")}</span>'
        rows += (f'<div class="rw"><div class="nm">{e(b["label"])}{flag}</div>'
                 f'<div class="lane"><div class="run" style="width:{xpx(b["value"]):.0f}px;animation-delay:{0.25 + i * 0.25:.2f}s">'
                 f'<i class="wake" style="background:{col}"></i><i class="bow" style="border-left-color:{col};"></i></div>'
                 f'<div class="num" style="left:{xpx(b["value"]):.0f}px" data-v="{b["value"]}" data-u="{e(unit)}"><span>{_fmt(b["value"], unit)}</span></div></div></div>')
        _ = lane
    ticks = "".join(f'<i style="left:{xpx(t) + 24:.0f}px"><b>{t:g}</b></i>' for t in range(int(lo), int(hi) + 1, 5 if hi - lo <= 40 else 10))
    lanes = "".join(f'<i style="background:{c}"></i>' for c in LANE_BG)
    t_len = len(spec["title"])
    t_size = 62 if t_len <= 20 else 54 if t_len <= 26 else 48 if t_len <= 36 else 42
    say = spec.get("say") or "こういう見方もあるよ"
    vw = spec.get("view")
    view_html = (f'<p class="vw"><small>ミカタの見方</small><b>{e(vw[0])}</b><span class="v2">{e(vw[1])}</span><span class="v3">{e(vw[2])}</span></p>' if vw
                 else f'<p><small>ミカタ(カモメの記者)</small>{e(say)}<span class="mt">こういう見方もあるよ</span></p>')
    anim = """
.run{transform-origin:left center;animation:go 1.2s cubic-bezier(.25,.85,.3,1) both}
@keyframes go{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.num{animation:pop .45s ease-out both;animation-delay:1.25s} .flag{animation:pop .45s ease-out both;animation-delay:1.7s}
.say{animation:slide .55s cubic-bezier(.2,.8,.2,1) both;animation-delay:2.1s}
@keyframes pop{from{opacity:0;transform:translateY(10px) scale(.9)}to{opacity:1;transform:none}}
@keyframes slide{from{opacity:0;transform:translateX(-40px)}to{opacity:1;transform:none}}
.say .vw b,.say .vw .v2,.say .vw .v3{animation:rise .5s cubic-bezier(.2,.8,.2,1) both}
.say .vw b{animation-delay:2.55s} .say .vw .v2{animation-delay:3.05s} .say .vw .v3{animation:rise .5s cubic-bezier(.2,.8,.2,1) both,nudge .6s ease-in-out 4.1s 1}
.say .vw .v3{animation-delay:3.6s,4.2s}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes nudge{0%,100%{transform:none}50%{transform:translateX(8px)}}
@media (prefers-reduced-motion: reduce){.run,.num,.flag,.say,.say .vw b,.say .vw .v2,.say .vw .v3{animation:none}}""" if animate else ""
    count_js = """<script>
document.querySelectorAll('.num').forEach((el)=>{const v=+el.dataset.v,u=el.dataset.u,t0=performance.now()+1250;
const f=(t)=>{const k=Math.min(1,Math.max(0,(t-t0)/700));const x=v*(0.8+0.2*(1-Math.pow(1-k,3)));
el.querySelector('span').textContent=(Math.abs(v)<10?x.toFixed(1):Math.round(x))+u;if(k<1)requestAnimationFrame(f)};requestAnimationFrame(f)});
</script>""" if animate else ""
    F2 = "'Noto Sans CJK JP','Zen Kaku Gothic New',sans-serif"
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
html,body{{margin:0;background:#f4efdf}} .c{{width:1080px;height:1350px;background:#f4efdf;font-family:{F2};color:#14212c;position:relative;overflow:hidden}}
.top{{background:#17191c;color:#fff;padding:44px 60px 40px}} .top small{{display:block;font:900 30px {F2};color:#ffe100;letter-spacing:.06em}}
.top h1{{margin:14px 0 0;font:900 {t_size}px/1.3 {F2};word-break:keep-all;overflow-wrap:anywhere}}
.lb{{display:flex;gap:4px;height:14px;padding:4px 0}} .lb i{{flex:1}}
.sub{{margin:28px 60px 0;font:700 28px/1.5 {F2};color:#56636e}}
.course{{position:relative;margin:36px 60px 0 60px;padding:34px 0 62px;border-left:6px solid #14212c}}

.rw{{position:relative;margin:0 0 44px;z-index:1}} .nm{{font:900 36px {F2};margin:0 0 12px 24px;display:flex;align-items:center;gap:16px}}
.lane{{position:relative;height:96px;margin-left:24px}}
.run{{position:absolute;left:0;top:0;height:96px;display:flex;align-items:center}}
.wake{{display:block;height:64px;flex:1;border-radius:0 6px 6px 0;opacity:.92}}
.bow{{display:block;width:0;height:0;border-top:48px solid transparent;border-bottom:48px solid transparent;border-left:56px solid #fff;filter:drop-shadow(2px 0 0 #14212c)}}
.num{{position:absolute;top:-2px;margin-left:30px;font:900 92px/1 {F2};white-space:nowrap}}
.flag{{display:inline-block;color:#fff;font:900 34px/1 {F2};padding:9px 26px 9px 16px;clip-path:polygon(0 0,100% 0,86% 50%,100% 100%,0 100%)}}
.ticks{{position:absolute;left:0;right:0;top:0;bottom:0;z-index:0}} .ticks i{{position:absolute;top:0;bottom:44px;border-left:2px solid #e3dcc6}}
.ticks b{{position:absolute;bottom:-40px;left:-24px;width:48px;text-align:center;font:700 22px {F2};color:#8a8270}}
.say{{position:absolute;left:60px;right:60px;bottom:120px;display:flex;align-items:center;gap:22px}}
.say p{{margin:0;flex:1;background:#fff;border:4px solid #14212c;border-radius:26px;padding:22px 30px;font:900 36px/1.45 {F2};position:relative}}
.say p::before{{content:"";position:absolute;left:-26px;top:50%;margin-top:-14px;border:14px solid transparent;border-right:22px solid #14212c}}
.say small{{display:block;font:700 24px {F2};color:#c8141c;margin-bottom:4px}} .say .vw{{padding:18px 28px}} .say .vw b{{display:block;font:900 38px/1.35 {F2};color:#c8141c}} .say .vw .v2{{display:block;font:900 32px/1.4 {F2}}} .say .vw .v3{{display:block;font:700 30px/1.4 {F2};color:#56636e;margin-top:2px}} .say .mt{{display:block;font:700 28px {F2};color:#56636e;margin-top:4px}}
.ft{{position:absolute;left:60px;right:60px;bottom:40px;display:flex;justify-content:space-between;font:700 24px {F2};color:#56636e}} .ft b{{color:#c8141c;font:900 28px {F2}}}{anim}
</style></head><body><div class="c"><div class="top"><small>ミカタ検証ラボ ・ 数えてみた</small><h1>{e(spec["title"])}</h1></div><div class="lb">{lanes}</div>
<div class="sub">{e(spec.get("sub") or "")}</div>
<div class="course">{rows}<div class="ticks">{ticks}</div></div>
<div class="say">{gull_svg(132, bg="#ffffff", cls="g")}{view_html}</div>
<div class="ft"><span>{e(spec.get("count") or "")}</span><b>@mikata_kyotei</b></div></div>{count_js}</body></html>"""


def render_png(html: str) -> tuple[bytes, dict | None]:
    """静止画(最後の形)と、はみ出しの測り(kyotei.factcheck.OVERFLOW_JS と同じ考え方: 文字がカードの外に出ていないか)。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1350})
        pg.set_content(html)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        over = pg.evaluate("""() => { const c = document.querySelector('.c').getBoundingClientRect(); let v=-1e9,h=-1e9;
          const w = document.createTreeWalker(document.querySelector('.c'), NodeFilter.SHOW_TEXT);
          while (w.nextNode()) { const r = document.createRange(); r.selectNodeContents(w.currentNode);
            for (const x of r.getClientRects()) { if (!x.width) continue; v = Math.max(v, x.bottom - c.bottom + 8); h = Math.max(h, x.right - c.right + 8, c.left + 8 - x.left); } }
          let o = -1e9; const sy = document.querySelector('.say'), co = document.querySelector('.course');
          if (sy && co) { const top = sy.getBoundingClientRect().top; for (const el of co.querySelectorAll('*')) { const r = el.getBoundingClientRect(); if (r.height) o = Math.max(o, r.bottom - top + 8); } }
          return {v: Math.round(v), h: Math.round(h), o: Math.round(o)}; }""")
        png = pg.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        b.close()
    return png, over


def render_mp4(html: str, seconds: float | None = None) -> bytes | None:
    """アニメーションを録って mp4(H.264・yuv420p・30fps)に。ffmpeg が無い・失敗したら None(静止画で出す)。"""
    if seconds is None:
        seconds = 6.0 if 'class="vw"' in html else 5.0
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return None
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": 1080, "height": 1350}, record_video_dir=str(tdp), record_video_size={"width": 1080, "height": 1350})
            pg = ctx.new_page()
            pg.set_content(html.replace("<body>", '<body style="visibility:hidden">', 1))   # 読み込み中の白い画面を録らない
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(200)
            t_start = pg.evaluate("performance.now()")
            pg.set_content(html)   # ここから動き始める
            pg.wait_for_timeout(int(seconds * 1000))
            ctx.close()
            b.close()
        webm = next(tdp.glob("*.webm"), None)
        if not webm:
            return None
        mp4 = tdp / "out.mp4"
        # 頭の読み込み分(白・空)を少し切る。最後の形で止まった時間を含めて seconds 秒ぶん
        cmd = [ff, "-y", "-loglevel", "error", "-ss", "0.45", "-i", str(webm), "-t", f"{seconds:.1f}",
               "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "20",
               "-movflags", "+faststart", "-an", str(mp4)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not mp4.exists():
            print("動画にできませんでした:", r.stderr[:300])
            return None
        _ = t_start
        return mp4.read_bytes()


def neta_spec(r: dict, n: int | None = None, view: list[str] | None = None) -> dict:
    """1枚1ネタ(lab.neta_items の1行)から、カードの中身を作る。見出しは「だれの・どのレースの」話かが分かる問い(lab.NETA_SUBJ)。"""
    sj = r.get("subj")
    if not sj:
        raise ValueError(f"主語が決まっていない物差し: {r.get('id')}")
    q, label, ref_ = sj
    refl = r.get("refl") or "ふだん"
    ref = ref_ or ("ふだん" if refl.startswith(("ふだん", "その人のふだん", "全レース", "本人のふだん")) else refl)
    col = {"多い": UP, "少ない": DOWN, "ほぼ同じ": SAME}[r["answer"]]
    a, b = _fmt(r["a"], "%"), _fmt(r["b"], "%")
    unit = "走" if "3着以内" in q or "選手が" in q else "レース"
    panel = [(f"{ref}→この条件", f"{b}→{a}")]
    if n:
        panel.append(("数えた数", f"{n:,}{unit}"))
    nums = f"ふだん{b}→{a}" if ref == "ふだん" else f"{ref}の{b}→{a}"
    say = {"多い": f"{nums}。はっきり差が出たね",
           "少ない": f"{nums}。予想のときに思い出したいね",
           "ほぼ同じ": f"{nums}。ここは気にしなくてよさそう"}[r["answer"]]
    count = f"公式の成績データ(2023年10月〜)・{n:,}{unit}を数えました" if n else "公式の成績データ(2023年10月〜)で数えました"
    return {"say": say, "count": count, "tone": r["answer"], **({"view": view} if view else {}),
            "title": f"{q}は?", "sub": (f"{ref}とくらべて、ミカタが約3年分のレースで数えてみた" if len(ref) <= 12 else "ミカタが約3年分のレースで数えてみた"),
            "bars": [{"label": ref, "value": r["b"], "color": BASE}, {"label": label if len(label) <= 11 else "この条件", "value": r["a"], "color": col}],
            "unit": "%", "panel": panel, "handle": "@mikata_kyotei"}


if __name__ == "__main__":   # 手元の確認: python -m kyotei.xanim out/anim
    import sys
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/anim")
    out.mkdir(parents=True, exist_ok=True)
    r = {"name": "今節、2連勝中", "line": "3着以内に入るのは57%(その人のふだんは51%)", "a": 57.3, "b": 50.5, "answer": "多い", "refl": "その人のふだん",
         "subj": ("今節2連勝中の選手が3着以内に入る割合", "今節2連勝中", None)}
    sp = neta_spec(r, 24403)
    png, over = render_png(chart_html(sp, animate=False))
    (out / "neta.png").write_bytes(png)
    mp4 = render_mp4(chart_html(sp, animate=True))
    if mp4:
        (out / "neta.mp4").write_bytes(mp4)
    print(json.dumps({"over": over, "mp4": len(mp4) if mp4 else None}))
