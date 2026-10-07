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


def tenji_card_html(day_label: str, race: str, deadline: str, race_type: str, hook: str, rows: list[dict],
                    view_label: str, course_line: str, fact: tuple[str, str, str] | None, dev_line: str = "", nerai: str = "",
                    hook_red: bool = False) -> str:
    """展示速報(展示が出たらすぐ。2026-10-07 ユーザー「情報量ふやして、読み手の予測がワクワクする感じで」「狙い目かも?をオッズから逆算」)。
    hook: いちばん大きく見せる1行(「1号艇は展示2位。逃げの見込み 52%→58%」)
    rows: 艇番順 [{"lane", "time", "rank", "course", "p", "p0", "mkt", "nerai"}](p=展示込みの1着の見込み、p0=朝の見立て、mkt=人気から考えた1着の確率)
    fact: (ラベル, ふだん, 展示1位) / nerai: 「狙い目かも? 4号艇の1着 14%(人気から考えると8%)」"""
    sub = " ・ ".join(x for x in (f"締切 {deadline}" if deadline else "", race_type or "") if x)
    pc = lambda v: "-" if v is None else f"{round(v * 100)}%"  # noqa: E731
    trs = ""
    for r in rows:
        cls = " r1" if r.get("rank") == 1 else ""
        tag = '<i class="ng">狙い目かも?</i>' if r.get("nerai") else (f'<i class="cs">{e(r["course"])}</i>' if r.get("course") else "")
        bar = f'<span class="bar"><span style="width:{min(100, (r.get("p") or 0) * 100 / 0.7):.0f}%"></span></span>' if r.get("p") is not None else ""
        arw = '<sup class="up">↑</sup>' if r.get("dev", 0) > 0 else '<sup class="dn">↓</sup>' if r.get("dev", 0) < 0 else ""
        trs += (f'<div class="tr{cls}">{lane_box(r["lane"])}<b class="rk">{r["rank"]}位{arw}</b><span class="tm">{r["time"]:.2f}</span>'
                f'<span class="pw">{pc(r.get("p"))}{bar}</span><span class="mk">{pc(r.get("mkt"))}</span>{tag}</div>')
    fh = f'<div class="fact">{e(fact[0])} <b>{e(fact[1])} → <em>{e(fact[2])}</em></b></div>' if fact else ""
    css = BASE_CSS + f"""
.top{{padding:30px 60px 26px}} .rc{{font:900 96px/1.05 {F};margin:6px 0 0}} .rs{{font:700 36px {F};color:#d9dde0;margin-top:6px}}
.hk{{margin:28px 60px 0;font:900 42px/1.3 {F}}}
.hd{{display:flex;margin:22px 60px 0;font:700 28px {F};color:{MUTE};padding-bottom:6px;border-bottom:3px solid {INK}}}
.hd span:nth-child(1){{width:172px}} .hd span:nth-child(2){{width:150px}} .hd span:nth-child(3){{width:260px}} .hd span:nth-child(4){{width:130px}}
.lst{{margin:0 60px}} .tr{{display:flex;align-items:center;height:74px;border-bottom:2px solid #e3dcc6}}
.tr .ln{{margin:0 14px 0 0;width:48px;height:50px;font-size:34px}} .tr .rk{{width:110px;font:900 36px {F};color:{MUTE}}}
.tr .tm{{width:150px;font:900 44px {F}}} .tr .pw{{width:260px;font:900 44px {F};display:flex;align-items:center;gap:10px}}
.tr .bar{{display:inline-block;width:90px;height:14px;background:#e3dcc6}} .tr .bar span{{display:block;height:100%;background:{INK}}}
.tr .mk{{width:130px;font:700 38px {F};color:{MUTE}}} .tr i{{font-style:normal}}
.tr .ng{{background:#c8141c;color:#fff;font:900 26px {F};padding:4px 8px;white-space:nowrap}} .tr .cs{{font:700 28px {F};color:{MUTE}}}
.tr.r1{{background:#fff3c4}} .tr.r1 .rk,.tr.r1 .tm{{color:#c8141c}}
.cl{{margin:14px 60px 0;font:900 34px/1.35 {F}}}
.fact{{margin:8px 60px 0;font:700 34px/1.4 {F};color:{MUTE}}} .fact b{{font:900 44px {F};color:{INK}}} .fact em{{font-style:normal;color:#c8141c}}
.ngl{{margin:8px 60px 0;font:900 34px/1.4 {F};color:#c8141c}} .hk.red{{color:#c8141c}} .ngl.ink{{color:{INK}}}
.tr .rk sup{{font-size:30px;margin-left:2px}} .tr .rk .up{{color:#1e6b3f}} .tr .rk .dn{{color:#0b5fb4}}
.dvl{{margin:8px 60px 0;font:700 32px/1.4 {F};color:{INK}}}"""
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">'
            f'<div class="top"><small>ミカタ速報 ・ 展示で見方が変わった ・ {e(day_label)}</small><div class="rc">{e(race)}</div><div class="rs">{e(sub)}</div>{_lanes_bar()}</div>'
            f'<div class="hk{" red" if hook_red else ""}">{e(hook)}</div>'
            f'<div class="hd"><span>艇・展示</span><span>タイム</span><span>{e(view_label)}</span><span>人気</span></div>'
            f'<div class="lst">{trs}</div><div class="cl">{e(course_line)}</div>{fh}'
            + (f'<div class="dvl">{e(dev_line)}</div>' if dev_line else "")
            + (f'<div class="ngl{" ink" if hook_red else ""}">{e(nerai)}</div>' if nerai else "")
            + f'{_foot("見立て=AIの1着の見込み / 人気=締切前のオッズ / ↑↓=ふだんの展示順位より2つ以上上・下")}</div></body></html>')


def myomi_card_html(day_label: str, race: str, deadline: str, race_type: str, lane: int, p: float, mkt: float,
                    reasons: list[str], gen: str = "") -> str:
    """展示速報の1枚目「狙い目かも?」: 人気(みんなの予想)とミカタの見立てを2本の棒で並べ、見立ての方が高い=人気の割に来そう(妙味)を見せる。
    2026-10-07 ユーザー「人気8%が市場で予測は14%で妙味があるということを分かりやすく」「一枚に留める必要ない」。買い目(組)は出さない。"""
    sub = " ・ ".join(x for x in (f"締切 {deadline}" if deadline else "", race_type or "") if x)
    mx = max(p, mkt, 1e-6) * 1.1
    ratio = p / mkt if mkt > 0 else 0
    rs = "".join(f"<li>{e(x)}</li>" for x in reasons[:3])
    css = BASE_CSS + f"""
.top{{padding:30px 60px 26px}} .rc{{font:900 96px/1.05 {F};margin:6px 0 0}} .rs{{font:700 36px {F};color:#d9dde0;margin-top:6px}}
.t{{margin:34px 60px 0;font:900 66px/1.2 {F};color:#c8141c;display:flex;align-items:center;gap:6px}} .t .ln{{width:70px;height:76px;font-size:50px;margin:0 6px}}
.bars{{margin:22px 60px 0}} .br{{margin-bottom:14px}} .br b{{display:block;font:900 36px/1.3 {F};margin-bottom:6px}}
.br .tr{{display:inline-block;width:680px;height:62px;background:#e3dcc6;vertical-align:middle}} .br .fl{{height:100%}}
.br em{{display:inline-block;width:260px;text-align:right;font:900 76px/1 {F};font-style:normal;vertical-align:middle}}
.ex{{margin:6px 60px 0;font:900 44px/1.4 {F}}} .ex em{{font-style:normal;color:#c8141c}}
.why{{margin:14px 60px 0;padding:0;list-style:none}} .why li{{font:700 34px/1.45 {F};padding-left:1em;text-indent:-1em}} .why li::before{{content:"・"}}
.nt{{margin:14px 60px 0;font:700 28px/1.45 {F};color:{MUTE}}}
.gen{{margin:14px 60px 0;display:flex;gap:18px;align-items:flex-start}}
.gen p{{margin:0;flex:1;background:#fff;border:3px solid #111;border-radius:20px;padding:10px 20px;font:700 34px/1.4 {F}}}
.gen small{{display:block;font:900 26px {F};color:#0b5fb4}}"""
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">'
            f'<div class="top"><small>ミカタ速報 ・ 展示で見方が変わった ・ {e(day_label)}</small><div class="rc">{e(race)}</div><div class="rs">{e(sub)}</div>{_lanes_bar()}</div>'
            f'<div class="t">狙い目かも?{lane_box(lane)}の1着</div>'
            f'<div class="bars"><div class="br"><b>人気(みんなの予想)</b><span class="tr"><span class="fl" style="display:block;width:{mkt / mx * 100:.1f}%;background:#8a949c"></span></span><em>{round(mkt * 100)}%</em></div>'
            f'<div class="br"><b>ミカタの見立て(展示込み)</b><span class="tr"><span class="fl" style="display:block;width:{p / mx * 100:.1f}%;background:#c8141c"></span></span><em style="color:#c8141c">{round(p * 100)}%</em></div></div>'
            f'<div class="ex">見立てが人気の<em>{ratio:.1f}倍</em>。<br>人気の割に来そう=妙味あり</div>'
            + (f'<ul class="why">{rs}</ul>' if rs else "")
            + f'<div class="nt">人気=締切前のオッズから出した1着の確率。見立てはAIの計算で、当たりを約束するものではありません</div>'
            + (f'<div class="gen">{gull_svg(84, bg="#ffffff", cls="g", who="gen")}<p><small>ゲンさん(ゲンかつぎ歴40年の大先輩)</small>{e(gen)}</p></div>' if gen else "")
            + f'{_foot("こういう見方もあるよ ・ 6艇の展示は2枚目")}</div></body></html>')
