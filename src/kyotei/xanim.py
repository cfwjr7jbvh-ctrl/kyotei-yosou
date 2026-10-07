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
          return {v: Math.round(v), h: Math.round(h)}; }""")
        png = pg.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        b.close()
    return png, over


def render_mp4(html: str, seconds: float = 5.0) -> bytes | None:
    """アニメーションを録って mp4(H.264・yuv420p・30fps)に。ffmpeg が無い・失敗したら None(静止画で出す)。"""
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


def neta_spec(r: dict, n: int | None = None) -> dict:
    """1枚1ネタ(lab.neta_items の1行)から、カードの中身を作る。"""
    import re
    name = re.sub(r"[((][^))]*[))]", "", r["name"]).strip().replace("今節、", "今節")
    line = r.get("line", "")
    metric = line.split("のは")[0]
    if "3着以内" in metric:
        m_short = "3着以内率"
    elif "1号艇が勝つ" in metric:
        m_short = "1号艇の1着率"
    elif metric.endswith("勝つ"):
        m_short = "1着率"
    else:
        m_short = metric + "割合"
    refl = r.get("refl") or "ふだん"
    refl = "ふだん" if refl.startswith(("その人のふだん", "ふだん")) else refl
    col = {"多い": UP, "少ない": DOWN, "ほぼ同じ": SAME}[r["answer"]]
    panel = [(f"{refl}→この条件", f"{_fmt(r['b'], '%')}→{_fmt(r['a'], '%')}")]
    if n:
        unit = "走" if "3着以内" in m_short else "レース"
        panel.append(("数えた数", f"{n:,}{unit}"))
    return {"title": f"{name}だと、{m_short}はどれだけ変わる?", "sub": "公式の成績データ(2023年10月〜)で数えました",
            "bars": [{"label": refl, "value": r["b"], "color": BASE}, {"label": name if len(name) <= 10 else "この条件", "value": r["a"], "color": col}],
            "unit": "%", "panel": panel, "handle": "@mikata_kyotei"}


if __name__ == "__main__":   # 手元の確認: python -m kyotei.xanim out/anim
    import sys
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/anim")
    out.mkdir(parents=True, exist_ok=True)
    r = {"name": "今節、2連勝中", "line": "3着以内に入るのは57%(その人のふだんは51%)", "a": 57.3, "b": 50.5, "answer": "多い", "refl": "その人のふだん"}
    sp = neta_spec(r, 24403)
    png, over = render_png(chart_html(sp, animate=False))
    (out / "neta.png").write_bytes(png)
    mp4 = render_mp4(chart_html(sp, animate=True))
    if mp4:
        (out / "neta.mp4").write_bytes(mp4)
    print(json.dumps({"over": over, "mp4": len(mp4) if mp4 else None}))
