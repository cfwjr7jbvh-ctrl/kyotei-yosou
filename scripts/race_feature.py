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
    title = f"ミカタ新聞 {day.month}/{day.day}|{(series_name + ' ') if series_name else ''}{race} {rt}の6人の型と理論"
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
    note = "\n".join([f"【タイトル案】{title}", "", lead, "", "■6人の型(よい面だけ)"] + [f"・{n}" for _, n in rows]
                     + ["", "■このレースに当てはまる理論"]
                     + ([f"インに有利: {'・'.join(sm['plus'])}", f"インに不利: {'・'.join(sm['minus'])}"] if sm.get("conflict") else [])
                     + [f"・{n['title']}: {n['text']}" for n in notes]
                     + ["", "この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"])
    return {"title": title, "html": page, "note": note}
