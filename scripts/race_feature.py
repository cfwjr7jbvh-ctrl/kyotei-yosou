"""ミカタ新聞(これからのレースの1レース特集)。買う人が多そうなレース(3連単の売上の見込み、src/kyotei/demand.py)を全場から選ぶ。

中身: 6人の「型」(選手カードのタグ。よい面だけ)+ そのレースに当てはまる理論 + ミカタとゲンさんのひと言。買い目は出さない。
公式の出走表は使わず、自分たちで集計した数字(選手カード・検証ラボ)だけ。
ura_auto.py が記事タブに入れ、上の部分を X の締切前の投稿の画像にする。
"""
from __future__ import annotations

import datetime as dt
import html as _h
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import mag  # noqa: E402
from kyotei import racer_card as rc  # noqa: E402
from kyotei.card_render import gull_svg, LANE_BG, LANE_FG  # noqa: E402
from kyotei.demand import stars  # noqa: E402
from kyotei import seo  # noqa: E402

e = _h.escape
WEEK = "月火水木金土日"


def racer_row(b: dict, cards: dict | None) -> tuple[str, str]:
    """(紙面の1行, note の1行)。型は強い順に2つまで。型が無い人は「ふだんどおりの強さ」。"""
    c = (cards or {}).get(int(b.get("racer_id") or 0))
    tags = sorted(rc.tags_for(c), key=lambda t: -t["score"])[:2] if c else []
    i = int(b["lane"]) - 1
    tg = "".join(f'<span class="tg">{e(t["t"])}</span>' for t in tags) or '<span class="tg plain">ふだんどおりの強さ</span>'
    why = tags[0]["why"] if tags else ""
    row = (f'<li><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'
           f'<div><b>{e(b.get("name") or "")}</b><small>{e(str(b.get("class") or ""))}</small>{tg}'
           + (f'<p>{e(why)}</p>' if why else "") + "</div></li>")
    note = f"{i + 1}号艇 {b.get('name')}({b.get('class') or ''}): " + ("・".join(t["t"] for t in tags) or "ふだんどおりの強さ") + (f"。{why}" if why else "")
    return row, note


def type_names(rr: dict, cards: dict | None, k: int = 2) -> str:
    """X 用: 強い型を持つ選手を k 人(検索される選手名を本文に)。「1号艇 今垣光太郎(まくり屋)」"""
    rows = []
    for b in sorted(rr.get("boats", []), key=lambda b: int(b["lane"])):
        c = (cards or {}).get(int(b.get("racer_id") or 0))
        tg = sorted(rc.tags_for(c), key=lambda t: -t["score"]) if c else []
        if tg and b.get("name"):
            rows.append((tg[0]["score"], f"{b['lane']}号艇 {b['name']}({tg[0]['t']})"))
    rows.sort(key=lambda x: -x[0])
    return "・".join(r for _, r in rows[:k])


def make(series_name: str, grade: str, rr: dict, cards: dict | None, score: float, day: dt.date) -> dict:
    rt = str(rr.get("race_type") or "")
    race = f"{rr['venue']}{rr['rno']}R"
    where = f"{series_name}の{rt}、{race}" if series_name else f"{race}({rt or 'レース'})"
    sm = rr.get("th_sum") or {}
    notes = [n for n in rr.get("theories") or [] if n.get("kind") != "occult"]
    occ = [n for n in rr.get("theories") or [] if n.get("kind") == "occult"]
    if sm.get("conflict"):
        pl = [x for x in sm["plus"] if x not in rt] or sm["plus"]   # 「優勝戦」の理論は見出しでは言わない(レース名と重なる)
        head = f"悩ましい{race}。インに有利『{pl[0]}』×不利『{sm['minus'][0]}』"
        lead = (f"{where}、{rr.get('deadline')}締切。インに有利な理論と不利な理論がぶつかっている。"
                f"6人の型と当てはまる理論を並べました。どれに乗るかは、あなた次第")
    else:
        head = f"{race}、6人の型と理論を1枚に"
        lead = (f"{where}、{rr.get('deadline')}締切。6人それぞれの強い型と、このレースに当てはまる理論{len(notes)}つ。"
                f"どれに乗るかは、あなた次第")
    rows = [racer_row(b, cards) for b in sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))]
    th_html = "".join(f'<li class="th {e(n["kind"])}"><b>{e(n["title"])}</b><span class="bd">{e(n["badge"])}</span><p>{e(n["text"])}</p></li>' for n in notes)
    # 検索で見つけてもらう: 先頭に場名+R・レースの種類・大会名(src/kyotei/seo.py)
    mv = mikata_view(rr)
    view_html, view_note = "", []
    if mv:
        h = mv["hon"]
        hl = f"本線: {h['lane']}号艇 {h.get('name') or ''}{('の' + mv['hon_type']) if mv['hon_type'] else ''}(1着の見込み{_pct(h['p_win'])}%、ふだんの{h['lane']}号艇は{LANE_BASE[int(h['lane'])]:.0f}%)"
        if mv["ner"]:
            n_ = mv["ner"]
            nl = f"狙い目かも? {n_['lane']}号艇 {n_.get('name') or ''}{('の' + mv['ner_type']) if mv['ner_type'] else ''}(1着の見込み{_pct(n_['p_win'])}%、ふだんの{n_['lane']}号艇の{mv['ratio']:.1f}倍)"
        else:
            nl = "狙い目かも? 本線が堅め(ふだんより見込みが高い外の艇は見当たらない)"
        bl = " / ".join(f"{b['lane']}号艇 {_pct(b.get('p_win'))}%" for b in sorted(rr.get("boats", []), key=lambda b: int(b["lane"])))
        kim = mv.get("kim") or {}
        kl = "・".join(f"{k}{_pct(kim.get(k))}%" for k in ("逃げ", "差し", "まくり", "まくり差し"))
        view_note = ["■ミカタの見立て(モデルの見込み。朝の出走表の時点)", hl, nl, f"1着の見込み: {bl}", f"展開(決まり手): {kl}"]
        view_html = ('<section><span class="label">ミカタの見立て(モデルの見込み)</span><ul class="ths">'
                     + "".join(f'<li class="th real"><p>{e(x)}</p></li>' for x in view_note[1:]) + "</ul></section>")
    title = f"【競艇】{race} {rt}{('|' + series_name) if series_name else ''} 本線と狙い目・6人の型|ミカタ新聞 {day.month}/{day.day}"
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex"><title>{e(title)}</title>{mag.FONTS}<style>{mag.CSS}
.six{{list-style:none;margin:0;padding:0;display:grid;gap:8px}} .six li{{display:flex;gap:10px;align-items:flex-start;background:var(--card);border:2px solid var(--rule);padding:10px 12px}}
.six .lt{{flex:0 0 34px;height:34px;display:grid;place-items:center;font:900 20px var(--num);border:1px solid #111}} .six b{{font:700 17px var(--sans)}} .six small{{margin-left:6px;color:var(--mute);font-size:12px}}
.tg{{display:inline-block;margin:0 0 0 6px;padding:1px 8px;border-radius:999px;background:#17191c;color:#ffe100;font:700 12px var(--sans)}} .tg.plain{{background:#e3dcc6;color:#33404a}}
.six p{{margin:4px 0 0;font-size:13px;line-height:1.6}}
.ths{{list-style:none;margin:0;padding:0;display:grid;gap:8px}} .th{{border-left:4px solid var(--rule);padding:2px 0 2px 10px;font-size:14px}} .th p{{margin:3px 0 0;font-size:13.5px;line-height:1.7}}
.th.edge{{border-color:#c98a00}} .th.real,.th.known,.th.trial{{border-color:#2e8b57}}
.bd{{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid var(--rule);margin-left:6px;color:var(--mute)}}
.vs{{display:grid;gap:4px;margin:0 0 10px;font-size:14px}} .vs .p{{color:#1e6b3f;font-weight:700}} .vs .m{{color:#a3121a;font-weight:700}}
</style></head><body>
<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ新聞<small>{e((grade + ' ' + series_name).strip() or 'これからのレース')}</small></div><div class="issue"><b>{e(stars(score))}</b><br>{day.month}/{day.day}({WEEK[day.weekday()]})</div></div>
<p class="cv-kicker">{e(rt)} ・ {e(race)} ・ {e(str(rr.get('deadline') or ''))}締切</p><h1 class="cv-h">{e(head)}</h1><p class="cv-deck">{e(lead)}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ / ゲンかつぎ担当 ゲンさん<br>型は選手カード、理論は検証ラボ(公式の成績データを独自に集計)から</span></div></div></header>
<main class="mag">
{view_html}
<section><span class="label">6人の型(よい面だけ)</span><ul class="six">{''.join(r for r, _ in rows)}</ul></section>
<section><span class="label">このレースに当てはまる理論</span>
{f'<p class="vs"><span class="p">インに有利: {e("・".join(sm["plus"]))}</span><span class="m">インに不利: {e("・".join(sm["minus"]))}</span></p>' if sm.get("conflict") else ''}
<ul class="ths">{th_html or '<li>当てはまる理論は見つからなかった。6人の型と水面を見る人が、いちばん楽しめるレース</li>'}</ul></section>
{f'<section><span class="label">おまけ: ゲンさんのゲンかつぎ</span><ul>{"".join(f"<li>{e(n['title'])}: {e(n['text'])}</li>" for n in occ)}</ul></section>' if occ else ''}
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>6人の型を頭に入れて、展示とスリットを見てね。型どおりに動くか、そこが見どころ</p></blockquote>
<blockquote class="ft-quote gen">{gull_svg(64, bg="#ffffff", cls="q", who="gen")}<p><small>ゲンさんの返し</small>理論もいいが、最後は展示だ。ピットを出ていく顔つきを見とけよ</p></blockquote>
<section class="method"><h3>データについて</h3><p>型は選手カード(公式の成績データ、2023年10月〜を独自に集計)のタグのうち強い2つ。理論の数字は検証ラボから。朝の出走表の時点の情報で作っています(展示は入っていません)。
この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ新聞 ・ 買う人が多そうなレースを毎日。考え方を並べる。どれに乗るかは、あなた次第。</span></footer></main></body></html>"""
    note = "\n".join([f"【タイトル案】{title}", "", lead, ""] + view_note + ["", "■6人の型(よい面だけ)"] + [f"・{n}" for _, n in rows]
                     + ["", "■このレースに当てはまる理論"]
                     + ([f"インに有利: {'・'.join(sm['plus'])}", f"インに不利: {'・'.join(sm['minus'])}"] if sm.get("conflict") else [])
                     + [f"・{n['title']}: {n['text']}" for n in notes]
                     + ["", "この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。",
                        "", seo.note_tags(rr["venue"], series_name or None, [b.get("name") for b in sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))][:6])])
    return {"title": title, "html": page, "note": note}


# ---------------------------------------------------------------- X 用のカード(1080×1350、スマホで読める大きな文字)
LANE_BASE = {1: 55.1, 2: 13.9, 3: 13.0, 4: 10.2, 5: 6.0, 6: 3.2}   # 枠ごとのふだんの1着(100レースあたり、2025年の全レース)
F = "'Noto Sans CJK JP','Zen Kaku Gothic New',sans-serif"


def _pct(v) -> int:
    return int(round(float(v or 0) * 100))


def _st(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return ("F" if v < 0 else "") + f"{abs(v):.2f}"[1:]


def mikata_view(rr: dict) -> dict:
    """ミカタの見立て: 本線(1着の見込みがいちばん高い艇)と「狙い目かも」(その枠のふだんより見込みが高い艇)。
    買い目(組み合わせ)は出さない。数字はミカタのモデルの見込み(朝の出走表の時点)。"""
    boats = sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))
    if not boats or not all(b.get("p_win") is not None for b in boats):
        return {}
    tk = rr.get("tenkai") or {}
    typ = {}
    for pth in tk.get("paths") or []:
        typ.setdefault(int(pth["lane"]), pth["type"])
    for sc in tk.get("scenarios") or []:
        typ.setdefault(int(sc["lane"]), sc.get("type"))
    hon = max(boats, key=lambda b: b["p_win"])
    cand = [b for b in boats if b is not hon and b["p_win"] >= 0.08]
    ner = max(cand, key=lambda b: b["p_win"] * 100 / LANE_BASE[int(b["lane"])], default=None)
    ratio = ner["p_win"] * 100 / LANE_BASE[int(ner["lane"])] if ner else 0
    if ner is None or ratio < 1.3:
        ner = None
    sc0 = next((s for s in tk.get("scenarios") or [] if int(s["lane"]) == int(hon["lane"])), None)
    return {"hon": hon, "hon_type": typ.get(int(hon["lane"])) or ("逃げ" if hon["lane"] == 1 else ""),
            "ner": ner, "ner_type": typ.get(int(ner["lane"])) if ner else None, "ratio": ratio,
            "second": (sc0 or {}).get("second") or [], "kim": tk.get("kimarite") or {},
            "in_lose": (rr.get("arashi") or {}).get("in_lose")}


CARD_CSS = f"""html,body{{margin:0}} .c{{width:1080px;height:1350px;background:#f4efdf;font-family:{F};color:#14212c;position:relative;overflow:hidden}}
.top{{background:#17191c;color:#fff;padding:30px 48px 26px}} .top small{{display:block;font:900 30px {F};color:#ffe100;letter-spacing:.04em}}
.top h1{{margin:8px 0 0;font:900 58px/1.2 {F}}} .top p{{margin:8px 0 0;font:700 30px {F};color:#c9ced2}}
.lb{{display:flex;gap:4px;height:12px;padding:4px 0;background:#f4efdf}} .lb i{{flex:1}}
.sec{{margin:22px 48px 0}} .h{{font:900 32px {F};color:#c8141c;margin:0 0 12px}}
.view{{display:grid;gap:14px}} .v{{display:flex;align-items:center;gap:18px;background:#fff;border:3px solid #14212c;padding:12px 20px}}
.v .k{{font:900 30px {F};padding:6px 14px;color:#fff;background:#14212c;white-space:nowrap}} .v.n .k{{background:#c8141c}}
.v b{{font:900 40px/1.25 {F}}} .v small{{display:block;font:700 26px/1.4 {F};color:#56636e;margin-top:4px}}
.lt{{display:inline-grid;place-items:center;width:52px;height:52px;font:900 34px {F};border:2px solid #111;flex:0 0 52px}}
.row{{display:flex;align-items:center;gap:16px;padding:7px 0;border-bottom:2px solid #d8d0b8}}
.row .nm{{flex:1;font:900 36px/1.15 {F}}} .row .nm small{{display:block;font:700 24px {F};color:#56636e;margin-top:4px}}
.bar{{width:250px;height:26px;background:#e3dcc6;position:relative}} .bar i{{position:absolute;left:0;top:0;bottom:0;background:#14212c}} .bar.n i{{background:#c8141c}}
.row .p{{width:110px;text-align:right;font:900 40px {F}}} .row .p small{{font-size:24px}}
.kim{{display:flex;gap:10px}} .kim div{{flex:1;background:#fff;border:2px solid #14212c;padding:10px 6px;text-align:center;font:700 26px {F}}}
.kim div b{{display:block;font:900 44px {F}}}
.lines{{list-style:none;margin:0;padding:0;display:grid;gap:12px}} .lines li{{background:#fff;border-left:10px solid #2e8b57;padding:12px 18px;font:700 32px/1.45 {F}}}
.lines li.m{{border-color:#c8141c}} .lines li small{{display:block;font:700 24px/1.4 {F};color:#56636e}}
.ft{{position:absolute;left:48px;right:48px;bottom:30px;display:flex;align-items:center;gap:16px;font:700 22px/1.4 {F};color:#56636e}}
.ft b{{color:#c8141c;font:900 30px {F};margin-left:auto;white-space:nowrap}}"""


def _card(head_small: str, h1: str, sub: str, body: str) -> str:
    lanes = "".join(f'<i style="background:{c}"></i>' for c in LANE_BG)
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{CARD_CSS}</style></head><body><div class="c">'
            f'<div class="top"><small>{e(head_small)}</small><h1>{e(h1)}</h1><p>{e(sub)}</p></div><div class="lb">{lanes}</div>{body}'
            f'<div class="ft">{gull_svg(64, bg="#ffffff", cls="f")}<span>数字はミカタのモデルの見込み(朝の出走表の時点・展示前)。<br>予想を楽しむための材料です。舟券は20歳から</span><b>@mikata_kyotei</b></div>'
            f'</div></body></html>')


def x_cards(series_name: str, grade: str, rr: dict, cards: dict | None, day: dt.date) -> list[str]:
    """X 用のカード2枚。1枚目: ミカタの見立て(本線・狙い目かも)と6艇の1着の見込み・平均ST。2枚目: 展開(決まり手)と2着の候補、当てはまる理論、型。"""
    rt = str(rr.get("race_type") or "")
    race = f"{rr['venue']}{rr['rno']}R"
    small = f"ミカタ新聞 {day.month}/{day.day} ・ " + ((grade + " " + series_name).strip() or "これからのレース")
    h1 = f"{race} {rt}"
    sub = f"{rr.get('deadline') or ''}締切"
    mv = mikata_view(rr)
    boats = sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))
    out = []
    # 1枚目
    v = ""
    if mv:
        h = mv["hon"]
        v += (f'<div class="v"><span class="k">本線</span><div><b>{h["lane"]}号艇 {e(h.get("name") or "")}{("の" + mv["hon_type"]) if mv["hon_type"] else ""}</b>'
              f'<small>1着の見込み {_pct(h["p_win"])}%(ふだんの{h["lane"]}号艇は{LANE_BASE[int(h["lane"])]:.0f}%)</small></div></div>')
        if mv["ner"]:
            n = mv["ner"]
            v += (f'<div class="v n"><span class="k">狙い目かも?</span><div><b>{n["lane"]}号艇 {e(n.get("name") or "")}{("の" + mv["ner_type"]) if mv["ner_type"] else ""}</b>'
                  f'<small>1着の見込み {_pct(n["p_win"])}%。ふだんの{n["lane"]}号艇({LANE_BASE[int(n["lane"])]:.0f}%)の{mv["ratio"]:.1f}倍</small></div></div>')
        else:
            v += '<div class="v n"><span class="k">狙い目かも?</span><div><b>本線が堅め</b><small>ふだんより見込みが高い外の艇は見当たらない</small></div></div>'
    rows = ""
    mx = max([b.get("p_win") or 0 for b in boats] + [0.01])
    for b in boats:
        i = int(b["lane"]) - 1
        st = (b.get("traits") or {}).get("st")
        rows += (f'<div class="row"><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'
                 f'<div class="nm">{e(b.get("name") or "")}<small>{e(str(b.get("class") or ""))} ・ 平均ST {_st(st)}</small></div>'
                 f'<div class="bar{" n" if mv and mv.get("ner") is b else ""}"><i style="width:{(b.get("p_win") or 0) / mx * 100:.0f}%"></i></div>'
                 f'<div class="p">{_pct(b.get("p_win"))}<small>%</small></div></div>')
    body1 = (f'<div class="sec"><p class="h">ミカタの見立て</p><div class="view">{v}</div></div>'
             f'<div class="sec"><p class="h">1着の見込み(ミカタのモデル)</p>{rows}</div>')
    out.append(_card(small, h1, sub, body1))
    # 2枚目
    kim = mv.get("kim") or (rr.get("tenkai") or {}).get("kimarite") or {}
    kd = "".join(f'<div>{k}<b>{_pct(kim.get(k))}%</b></div>' for k in ("逃げ", "差し", "まくり", "まくり差し"))
    sec_ = ""
    if mv and mv["second"]:
        h = mv["hon"]
        nm_ = {int(b["lane"]): b.get("name") or "" for b in boats}
        sec_ = (f'<div class="sec"><p class="h">{h["lane"]}号艇が勝つなら、2着は?</p><ul class="lines">'
                + "".join(f'<li>{s["lane"]}号艇 {e(nm_.get(int(s["lane"]), ""))}<small>{h["lane"]}号艇が1着のとき、2着になる見込み {_pct(s["p"])}%</small></li>' for s in mv["second"][:2])
                + "</ul></div>")
    sm = rr.get("th_sum") or {}
    th = ""
    if sm.get("plus") or sm.get("minus"):
        th = ('<div class="sec"><p class="h">当てはまる理論</p><ul class="lines">'
              + (f'<li>インに有利: {e("・".join((sm.get("plus") or [])[:3]))}</li>' if sm.get("plus") else "")
              + (f'<li class="m">インに不利: {e("・".join((sm.get("minus") or [])[:3]))}</li>' if sm.get("minus") else "") + "</ul></div>")
    il = mv.get("in_lose") if mv else None
    body2 = (f'<div class="sec"><p class="h">展開の見込み(決まり手)</p><div class="kim">{kd}</div></div>' + sec_ + th
             + (f'<div class="sec"><p class="h">荒れそう度</p><ul class="lines"><li class="m">1号艇以外が勝つ見込み {_pct(il)}%<small>ふだんは45%(100レースで45回)</small></li></ul></div>' if il is not None else ""))
    out.append(_card(small, h1, sub + " ・ つづき 2/2", body2))
    return out
