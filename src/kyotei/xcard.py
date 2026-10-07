"""X に載せる画像の専用カード(1080×1350、4:5)。

2026-10-07 ユーザー「画像にするとちょっと読みづらいから X に載せる画像は気をつけて」:
記事の紙面(幅1080の HTML)をそのまま撮ると、スマホのタイムライン(幅360〜390)では文字が5px前後になって読めない。
X の画像は記事を撮らず、このカードを作る。決まり:
  - 1080×1350。スマホでは約1/3に縮むので、いちばん小さい文字でも34px(=12px)、主役の数字は64px以上
  - 1枚に載せるのは「場名+R / 結論 / 数字2つ / 問い」まで。くわしい表は記事へ
  - 色は意味で: インに有利=緑、不利=赤、本当=赤、ふだんと同じ=灰。数字は「47% → 66%」の形
"""
from __future__ import annotations

import html
import re

from kyotei.card_render import LANE_BG, LANE_FG, gull_svg

e = html.escape
F = "'Noto Sans CJK JP','Zen Kaku Gothic New',sans-serif"
INK, MUTE, PAPER, PLUS, MINUS = "#14212c", "#4d5a66", "#f4efdf", "#1e6b3f", "#b3121b"

BASE_CSS = f"""html,body{{margin:0}} .c{{width:1080px;height:1350px;background:{PAPER};font-family:{F};color:{INK};position:relative;overflow:hidden}}
.top{{background:#17191c;color:#fff;padding:38px 60px 34px;position:relative}} .top small{{display:block;font:900 32px {F};color:#ffe100;letter-spacing:.04em}}
.lb{{position:absolute;left:0;right:0;bottom:-18px;height:18px;display:flex;gap:4px;padding:4px 0;background:{PAPER}}} .lb i{{flex:1}}
.ln{{display:inline-flex;align-items:center;justify-content:center;width:52px;height:56px;font:900 38px {F};border:3px solid #111;margin-left:10px;vertical-align:middle}}
.ft{{position:absolute;left:60px;right:60px;bottom:40px;display:flex;align-items:center;gap:18px;font:900 30px/1.3 {F}}}
.ft small{{display:block;font:700 24px {F};color:{MUTE}}} .ft .at{{margin-left:auto;color:#c8141c;font:900 34px {F}}}"""


def _lanes_bar() -> str:
    return '<div class="lb">' + "".join(f'<i style="background:{c}"></i>' for c in LANE_BG) + "</div>"


def lane_box(n: int) -> str:
    return f'<span class="ln" style="background:{LANE_BG[n - 1]};color:{LANE_FG[n - 1]}">{n}</span>'


def _foot(sub: str) -> str:
    return (f'<div class="ft">{gull_svg(84, bg="#ffffff", cls="f")}<div>ミカタ<small>{e(sub)}</small></div>'
            f'<div class="at">@mikata_kyotei</div></div>')


_ARROW = re.compile(r"^(.*\S)\s+(\D*)(\d+(?:\.\d)?%)→(\d+(?:\.\d)?%)$")


def _num_html(num: str, col: str, title: str = "", lanes: list | None = None) -> str:
    """「1号艇の1着 予選48%→73%」→ 小さいラベル「1号艇の1着: 予選 → 準優勝戦」+ 大きい「48% → 73%」(右の数字だけ色)。形が違えばそのまま大きく。"""
    m = _ARROW.match(num or "")
    if not m:
        return f'<div class="nm"><b>{e(num)}</b></div>' if num else ""
    what, ref, a, b = m.groups()
    if "号艇" not in what and lanes:
        what = f"{lanes[0]}号艇の{what}"
    lab = what + (f": {ref.strip()} → {title}" if ref.strip() and title else "")
    return f'<div class="nm"><span>{e(lab)}</span><b>{e(a)} → <em style="color:{col}">{e(b)}</em></b></div>'


def theory_card_html(day_label: str, race: str, deadline: str, race_type: str,
                     plus: list[dict], minus: list[dict], n_more: int = 0) -> str:
    """毎朝 8:20 の「今日の悩ましいレース」。plus/minus: [{"title", "lanes": [1], "num": "1号艇の1着 予選48%→73%"}](各2つまで載せる)。"""
    def side(lbl, items, col):
        # 大きく載せるのは1つだけ(数字のあるものを優先)。残りは名前だけ1行に(はみ出さない・読める大きさを守る)
        main = next((it for it in items if it.get("num")), items[0]) if items else None
        rows = ""
        if main:
            lanes = "".join(lane_box(x) for x in (main.get("lanes") or [])[:2])
            rows = f'<div class="it"><div class="tt">{e(main["title"])}{lanes}</div>{_num_html(main.get("num", ""), col, main["title"], main.get("lanes"))}</div>'
        rest = [it["title"] for it in items if it is not main]
        more = f'<div class="mo">ほかに{len(rest)}つ: {e(rest[0][:14])}{" など" if len(rest) > 1 else ""}</div>' if rest else ""   # 1行に収める
        return f'<div class="sd" style="border-color:{col}"><div class="hd" style="background:{col}">{lbl}</div>{rows}{more}</div>'
    sub = " ・ ".join(x for x in (f"締切 {deadline}" if deadline else "", race_type or "") if x)
    css = BASE_CSS + f"""
.rc{{font:900 112px/1.05 {F};margin:10px 0 0;letter-spacing:.01em}} .rs{{font:700 40px {F};color:#d9dde0;margin-top:10px}}
.q{{margin:40px 60px 0;font:700 36px/1.4 {F};color:{MUTE}}}
.sd{{margin:20px 60px 0;border-left:16px solid;background:#fffdf6;padding:0 30px 18px 30px}}
.hd{{display:inline-block;color:#fff;font:900 36px {F};padding:8px 20px;margin:0 0 6px -30px}}
.it{{margin-top:8px}} .tt{{font:900 50px/1.25 {F}}}
.nm span{{display:block;font:700 34px/1.4 {F};color:{MUTE};margin-top:6px}} .nm b{{font:900 66px/1.15 {F}}} .nm em{{font-style:normal}}
.mo{{margin-top:6px;font:700 34px/1.4 {F};color:{MUTE}}}
.ask{{margin:24px 60px 0;font:900 58px/1.2 {F};color:#c8141c}}"""
    # 両方に「ほかに」が付く日は、上の説明の1行を省いて、はみ出さないようにする
    q = "" if len(plus) > 1 and len(minus) > 1 else '<div class="q">インに有利な理論と不利な理論がぶつかる</div>'
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">'
            f'<div class="top"><small>今日の悩ましいレース ・ {e(day_label)}</small><div class="rc">{e(race)}</div>'
            f'<div class="rs">{e(sub)}</div>{_lanes_bar()}</div>{q}'
            f'{side("インに有利", plus, PLUS)}{side("インに不利", minus, MINUS)}'
            f'<div class="ask">あなたは、どっちに乗る?</div>'
            f'{_foot("検証ラボの理論を、今日の出走表に")}'
            f'</div></body></html>')


def lab_card_html(title: str, verdict: str, real: bool, cond: str, sv: str,
                  a: float | None, b: float | None, refl: str, text_line: str = "",
                  market: str = "", gen: str = "") -> str:
    """毎週火・金 20:00 の検証ラボ。結論のハンコ → 2本の棒(この条件 / ふだん)→ 人気とのくらべ → ゲンさんの返し。
    a/b は率(0〜1)。率で書けない回(100人中◯人など)は a=None にして text_line を大きく出す。"""
    col = "#c8141c" if real else "#6b7680"
    if a is not None and b is not None:
        mx = max(a, b, 1e-6) * 1.1
        fmt = lambda v: (f"{v * 100:.1f}".rstrip("0").rstrip(".") if v < 0.1 else f"{round(v * 100)}") + "%"  # noqa: E731
        body = (f'<div class="sv">{e(sv)}のは</div><div class="bars">'
                f'<div class="br"><b>{e(cond)}</b><div class="tr"><div class="fl" style="width:{a / mx * 100:.1f}%;background:{col}"></div></div><em style="color:{col}">{fmt(a)}</em></div>'
                f'<div class="br"><b>{e(refl)}</b><div class="tr"><div class="fl" style="width:{b / mx * 100:.1f}%;background:#8a949c"></div></div><em>{fmt(b)}</em></div></div>')
    else:
        body = f'<div class="big">{e(text_line)}</div>'
    head, _, rest = verdict.partition("。")
    stamp = f'<div class="v">{e(head)}</div>' + (f'<div class="vr">{e(rest)}</div>' if rest else "")
    mk = f'<div class="mk">{e(market)}</div>' if market else ""
    gn = (f'<div class="gen">{gull_svg(96, bg="#ffffff", cls="g", who="gen")}<p><small>ゲンさん(ゲンかつぎ歴40年の大先輩)</small>{e(gen)}</p></div>' if gen else "")
    css = BASE_CSS + f"""
.top h1{{margin:12px 0 0;font:900 56px/1.3 {F}}}
.v{{margin:54px 60px 0;background:{col};color:#fff;padding:18px 34px;font:900 76px/1.1 {F};display:inline-block}}
.vr{{margin:18px 60px 0;font:900 42px/1.45 {F};color:{col}}}
.sv{{margin:40px 60px 0;font:700 36px/1.4 {F};color:{MUTE}}}
.bars{{margin:14px 60px 0}} .br{{margin-bottom:14px}} .br b{{display:block;font:900 38px/1.3 {F};margin-bottom:4px}}
.br .tr{{display:inline-block;width:690px;height:58px;background:#e3dcc6;vertical-align:middle;position:relative}} .br .fl{{height:100%}}
.br em{{display:inline-block;width:250px;text-align:right;font:900 70px/1 {F};font-style:normal;vertical-align:middle}}
.big{{margin:40px 60px 0;font:900 52px/1.4 {F}}}
.mk{{margin:10px 60px 0;font:700 36px/1.45 {F};color:{MUTE}}}
.gen{{margin:34px 60px 0;display:flex;gap:20px;align-items:flex-start}}
.gen p{{margin:0;flex:1;background:#fff;border:3px solid #111;border-radius:22px;padding:16px 24px;font:700 36px/1.5 {F}}}
.gen small{{display:block;font:900 28px {F};color:#0b5fb4}}"""
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">'
            f'<div class="top"><small>ミカタ検証ラボ ・ 17万レースで数えた</small><h1>{e(title)}</h1>{_lanes_bar()}</div>'
            f'{stamp}{body}{mk}{gn}'
            f'{_foot("公式の成績データ(2023年10月〜)を独自に集計")}</div></body></html>')


def tenji_card_html(day_label: str, race: str, deadline: str, race_type: str, rows: list[dict],
                    fact: tuple[str, str, str] | None, course_line: str, view_line: str = "") -> str:
    """展示速報(展示が出たらすぐ)。rows: 展示タイムの速い順 [{"rank", "lane", "time", "course"}]。
    fact: (ラベル, ふだん, 展示1位) 例 ("展示1位の艇が3着以内に入る", "51%", "63%")。course_line: 「進入は枠なり」など。"""
    sub = " ・ ".join(x for x in (f"締切 {deadline}" if deadline else "", race_type or "") if x)
    trs = ""
    for r in rows:
        top = r["rank"] == 1
        trs += (f'<div class="tr{" top" if top else ""}"><b class="rk">{r["rank"]}位</b>{lane_box(r["lane"])}'
                f'<span class="tm">{r["time"]:.2f}</span><span class="cs">{e(r.get("course") or "")}</span></div>')
    fh = (f'<div class="fact"><span>{e(fact[0])}(ふだん → 展示1位)</span><b>{e(fact[1])} → <em>{e(fact[2])}</em></b></div>' if fact else "")
    css = BASE_CSS + f"""
.rc{{font:900 104px/1.05 {F};margin:10px 0 0}} .rs{{font:700 38px {F};color:#d9dde0;margin-top:8px}}
.lst{{margin:40px 60px 0}} .tr{{display:flex;align-items:center;gap:6px;height:84px;border-bottom:3px solid #e3dcc6}}
.tr .rk{{width:110px;font:900 40px {F};color:{MUTE}}} .tr .ln{{margin:0 22px 0 0}}
.tr .tm{{font:900 56px {F};width:200px}} .tr .cs{{font:700 34px {F};color:{MUTE}}}
.tr.top{{background:#fff3c4}} .tr.top .rk{{color:#c8141c}} .tr.top .tm{{color:#c8141c}}
.cl{{margin:22px 60px 0;font:900 40px/1.35 {F}}}
.fact{{margin:18px 60px 0}} .fact span{{display:block;font:700 34px/1.4 {F};color:{MUTE}}} .fact b{{font:900 64px/1.15 {F}}} .fact em{{font-style:normal;color:#c8141c}}
.vw{{margin:12px 60px 0;font:700 36px/1.4 {F}}}"""
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">'
            f'<div class="top"><small>展示が出た ・ {e(day_label)}</small><div class="rc">{e(race)}</div><div class="rs">{e(sub)}</div>{_lanes_bar()}</div>'
            f'<div class="lst">{trs}</div><div class="cl">{e(course_line)}</div>{fh}'
            + (f'<div class="vw">{e(view_line)}</div>' if view_line else "")
            + f'{_foot("展示タイムの順位は、公式の直前情報から")}</div></body></html>')
