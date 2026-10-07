"""ミカタ新聞(これからのレースの1レース特集)。買う人が多そうなレース(3連単の売上の見込み、src/kyotei/demand.py)を全場から選ぶ。

中身: 6人の「型」(選手カードのタグ。よい面だけ)+ そのレースに当てはまる理論 + ミカタとゲンさんのひと言。買い目は出さない。
公式の出走表は使わず、自分たちで集計した数字(選手カード・検証ラボ)だけ。
ura_auto.py が記事タブに入れ、上の部分を X の締切前の投稿の画像にする。
"""
from __future__ import annotations

import datetime as dt
import html as _h
import re
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
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ / ゲンかつぎ担当 ゲンさん(ゲンかつぎ歴40年の大先輩)<br>型は選手カード、理論は検証ラボ(公式の成績データを独自に集計)から</span></div></div></header>
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
    return ("F" if v < 0 else "") + f"{abs(v):.2f}"


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
.row{{display:flex;align-items:center;gap:16px;padding:5px 0;border-bottom:2px solid #d8d0b8}}
.row .nm{{flex:1;font:900 36px/1.15 {F}}} .row .nm small{{display:block;font:700 24px {F};color:#56636e;margin-top:4px}}
.row.r1 .nm{{display:flex;align-items:baseline;gap:14px;white-space:nowrap}} .row.r1 .nm small{{display:inline;margin:0;font:700 28px {F}}}
.bar{{width:250px;height:26px;background:#e3dcc6;position:relative}} .bar i{{position:absolute;left:0;top:0;bottom:0;background:#14212c}} .bar.n i{{background:#c8141c}}
.row .p{{width:110px;text-align:right;font:900 40px {F}}} .row .p small{{font-size:24px}}
.kim{{display:flex;gap:10px}} .kim div{{flex:1;background:#fff;border:2px solid #14212c;padding:10px 6px;text-align:center;font:700 26px {F}}}
.kim div b{{display:block;font:900 44px {F}}}
.lines{{list-style:none;margin:0;padding:0;display:grid;gap:12px}} .lines li{{background:#fff;border-left:10px solid #2e8b57;padding:12px 18px;font:700 29px/1.45 {F}}}
.lines.sm li{{font-size:27px;padding:10px 16px}} .lines li.m{{border-color:#c8141c}} .lines li small{{display:block;font:700 24px/1.4 {F};color:#56636e}}
.hook{{margin:24px 48px 0;background:#ffe100;padding:18px 24px;font:900 44px/1.3 {F};border:3px solid #14212c}}
.br{{display:flex;align-items:center;gap:16px;background:#fff;border:3px solid #14212c;padding:10px 18px;margin-bottom:10px}}
.br .k{{font:900 26px {F};padding:6px 10px;color:#fff;background:#14212c;white-space:nowrap;align-self:flex-start}} .br.n .k{{background:#c8141c}} .br.o .k{{background:#8a949c}}
.br .bm{{flex:1}} .br .bm b{{display:flex;align-items:center;gap:12px;font:900 36px/1.25 {F}}} .br .bm small{{display:block;font:700 26px/1.4 {F};color:#14212c;margin-top:4px}}
.br .bm p{{margin:4px 0 0;font:700 23px/1.4 {F};color:#56636e}} .br .pc{{font:900 52px {F};white-space:nowrap}} .br .pc small{{font-size:26px}}
.br .lt{{width:44px;height:44px;flex:0 0 44px;font-size:28px}} .row em{{font-style:normal;color:#c8141c}}
.gen{{background:#e8eef7;border:3px solid #0b5fb4;padding:12px 18px}} .gw{{display:flex;gap:12px;align-items:center;margin-bottom:6px}}
.gen span{{font:900 26px {F};color:#fff;background:#0b5fb4;padding:4px 10px;white-space:nowrap}} .gw small{{font:700 24px {F};color:#0b5fb4}}
.gen p{{margin:0;font:700 30px/1.45 {F}}}
.h .key{{display:block;margin-top:4px;font:700 22px {F};color:#56636e}} .ths{{list-style:none;margin:0;padding:0;display:grid;gap:10px}} .ths li{{background:#fff;border-left:10px solid #8a949c;padding:10px 18px}}
.ths li.p{{border-color:#2e8b57}} .ths li.m{{border-color:#c8141c}} .ths li b{{font:900 32px {F}}}
.ths .bd{{display:inline-block;margin-left:12px;padding:3px 12px;border-radius:999px;font:700 22px {F};background:#e3dcc6;color:#33404a;vertical-align:4px}}
.ths .bd.real{{background:#2e8b57;color:#fff}} .ths .bd.edge{{background:#c8141c;color:#fff}} .ths .bd.known{{background:#14212c;color:#fff}}
.ths li p{{margin:6px 0 0;font:700 26px/1.45 {F}}}
.words{{list-style:none;margin:0;padding:0;display:grid;gap:8px}} .words li{{display:flex;gap:14px;align-items:flex-start;font:700 25px/1.45 {F}}} .words li b{{flex:0 0 150px;padding:2px 10px;background:#14212c;color:#ffe100;font:900 24px/1.45 {F};text-align:center}}
.bk{{display:flex;align-items:center;gap:16px;background:#fff;border:3px solid #c8141c;padding:8px 16px;margin-bottom:8px}}
.bk .bm{{flex:1}} .bk .bm b{{font:900 34px/1.2 {F}}} .bk .bm small{{display:block;font:700 26px/1.35 {F};color:#14212c;margin-top:2px}}
.bk .pc{{font:900 46px {F};white-space:nowrap}} .bk .pc small{{font-size:24px}} .bk .lt{{width:44px;height:44px;flex:0 0 44px;font-size:28px}}
.wk{{list-style:none;margin:6px 0 0;padding:0;font:700 26px/1.4 {F};color:#56636e}} .wk li::before{{content:"・"}}
.ft{{position:absolute;left:48px;right:48px;bottom:30px;display:flex;align-items:center;gap:16px;font:700 22px/1.4 {F};color:#56636e}}
.ft b{{color:#c8141c;font:900 30px {F};margin-left:auto;white-space:nowrap}}"""


def _card(head_small: str, h1: str, sub: str, body: str) -> str:
    lanes = "".join(f'<i style="background:{c}"></i>' for c in LANE_BG)
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{CARD_CSS}</style></head><body><div class="c">'
            f'<div class="top"><small>{e(head_small)}</small><h1>{e(h1)}</h1><p>{e(sub)}</p></div><div class="lb">{lanes}</div>{body}'
            f'<div class="ft">{gull_svg(64, bg="#ffffff", cls="f")}<span>数字はミカタの計算(朝の出走表から。展示の前)。<br>予想を楽しむための材料です。舟券は20歳から</span><b>@mikata_kyotei</b></div>'
            f'</div></body></html>')


def _lab_pair(lab_id: str, key: str) -> tuple[float, float] | None:
    """検証ラボの数字(100あたり)を、記事と食い違わないように JSON から読む。"""
    import json
    try:
        from kyotei.publish import load_private
        t = load_private(ROOT / f"reports/lab/{lab_id}.json", {})
        for name, m, _v in t["measures"]:
            if key in name:
                return round(m["in1"] * 100, 1), round(m["in1_ref"] * 100, 1)
    except Exception:  # noqa: BLE001
        pass
    return None


KIM_TAG = {"まくり屋": "まくり", "差し職人": "差し", "まくり差しの職人": "まくり差し", "イン逃げ番長": "逃げ"}
FIT = {"逃げ": ("イン逃げ番長", "スタート職人"), "まくり": ("まくり屋", "スタート職人", "外からでも届く"),
       "差し": ("差し職人",), "まくり差し": ("まくり差しの職人", "外からでも届く")}


def _tags(b: dict, cards: dict | None) -> list[dict]:
    c = (cards or {}).get(int(b.get("racer_id") or 0))
    return sorted(rc.tags_for(c), key=lambda t: -t["score"]) if c else []


def _type_of(b: dict, model_type: str | None, cards: dict | None) -> str | None:
    """勝ち方: 1号艇は逃げ。ほかは、その人の決まり手の型(まくり屋・差し職人…)があればそれ、無ければモデルの勝ち筋。"""
    if int(b["lane"]) == 1:
        return "逃げ"
    for t in _tags(b, cards):
        if t["t"] in KIM_TAG and KIM_TAG[t["t"]] != "逃げ":
            return KIM_TAG[t["t"]]
    return model_type


def _why(b: dict, typ: str | None, cards: dict | None) -> str:
    """その勝ち方を推す理由の1行(勝ち方に合う型だけ。合う型が無ければ空)。"""
    fit = FIT.get(typ or "", ())
    t = next((t for t in _tags(b, cards) if t["t"] in fit), None)
    return f"{t['t']}: {t['why']}" if t else ""


COURSE_TYPE = {2: "差し", 3: "まくり", 4: "まくり", 5: "まくり差し", 6: "まくり差し"}


def _stm(v) -> str:
    """市場の書き方「ST.15」。"""
    t = _st(v)
    return "ST" + (t[1:] if t.startswith("0") else t)


def breakers(rr: dict, cards: dict | None, k: int = 2) -> dict:
    """1号艇を崩すなら誰か(2026-10-07 ユーザー「崩すのは誰だ?なら少しはデータからの方向性出さないと」)。
    2〜6号艇を1着の見込みの順に k 人。勝ち方は展開の見込み(tenkai)→ その人の型 → コースのふつうの勝ち方。
    理由は数字で言えるものだけ: 1号艇よりスタートが速い / その枠のふだんより見込みが高い / 勝ち方に合う型 / インに不利な理論。
    1号艇の気になる点も、名前は出さず艇番で(選手をけなさない)。"""
    boats = sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))
    if len(boats) < 6 or not all(b.get("p_win") is not None for b in boats):
        return {}
    one = boats[0]
    tk = rr.get("tenkai") or {}
    ptype = {}
    for pth in sorted(tk.get("paths") or [], key=lambda x: -x.get("p", 0)):
        ptype.setdefault(int(pth["lane"]), pth["type"])
    st = {int(b["lane"]): (b.get("traits") or {}).get("st") for b in boats}
    th_minus = {}
    for n in rr.get("theories") or []:
        if n.get("kind") != "occult" and int(n.get("dir") or 0) < 0:
            for ln in n.get("lanes") or []:
                if int(ln) != 1:
                    th_minus.setdefault(int(ln), n["title"])
    out = []
    for b in sorted(boats[1:], key=lambda b: -b["p_win"])[:k]:
        ln = int(b["lane"])
        typ = ptype.get(ln) or _type_of(b, None, cards) or COURSE_TYPE.get(ln)
        why = []
        if st.get(ln) is not None and st.get(1) is not None and st[ln] <= st[1] - 0.02:
            why.append(f"{_stm(st[ln])}(1号艇は{_stm(st[1])})")
        r = b["p_win"] * 100 / LANE_BASE[ln]
        if r >= 1.2:
            why.append(f"いつもの{ln}号艇({LANE_BASE[ln]:.0f}%)より高い")
        w = _why(b, typ, cards)
        if w:
            why.append(w.split(":")[0])
        if ln in th_minus:
            why.append(th_minus[ln])
        out.append({"lane": ln, "name": b.get("name") or "", "type": typ, "p": b["p_win"], "why": why[:2]})
    weak = []
    if st.get(1) is not None and all(st.get(i) is not None for i in range(1, 7)):
        rank = 1 + sum(1 for i in range(2, 7) if st[i] < st[1])
        if rank >= 4:
            weak.append(f"1号艇のスタートは6人中{rank}番目の速さ({_stm(st[1])})")
    nige = (one.get("traits") or {}).get("nige")
    if nige is not None and nige < 0.45:
        weak.append(f"1号艇の逃げ率は{_pct(nige)}%(ふだんの1号艇は55%)")
    cls = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}
    c1 = cls.get(str(one.get("class") or ""), 0)
    higher = sum(1 for b in boats[1:] if cls.get(str(b.get("class") or ""), 0) > c1)
    if higher >= 3:
        weak.append(f"1号艇より級別が上の選手が{higher}人")
    kim = tk.get("kimarite") or {}
    return {"list": out, "weak": weak[:2], "in_lose": (rr.get("arashi") or {}).get("in_lose"), "kim": kim}


def story(rr: dict, cards: dict | None) -> dict:
    """「だから何?」で終わらせないための骨組み。
    hook: このレースの問い(「Aの逃げか、Bのまくりか」)、branches: 展開の分かれ道(見込みと理由)、
    checks: 展示で見るのはここ(検証ラボで本物と分かった材料だけ。展示STは「ほぼウソ」なので使わない)。"""
    mv = mikata_view(rr)
    if not mv:
        return {}
    boats = sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))
    nm = {int(b["lane"]): (b.get("name") or "") for b in boats}
    h, n = mv["hon"], mv["ner"]
    ht = _type_of(h, mv["hon_type"], cards) or "1着"
    nt = _type_of(n, mv["ner_type"], cards) if n else None
    hook = (f"{h['lane']}号艇 {nm[int(h['lane'])]}の{ht}か、{n['lane']}号艇 {nm[int(n['lane'])]}の{nt or '一撃'}か"
            if n else f"{h['lane']}号艇 {nm[int(h['lane'])]}の{ht}は堅い? 崩すなら誰だ")
    br = [{"k": "本命", "lane": int(h["lane"]), "name": nm[int(h["lane"])], "type": ht if ht != "1着" else None, "p": h["p_win"], "why": _why(h, ht, cards),
           "second": mv["second"][:2]}]
    if n:
        br.append({"k": "狙い目かも?", "lane": int(n["lane"]), "name": nm[int(n["lane"])], "type": nt, "p": n["p_win"],
                   "why": _why(n, nt, cards), "ratio": mv["ratio"]})
    else:   # 「崩すなら誰だ」と問うたら、データからの答えも出す
        bk = (breakers(rr, cards, 1).get("list") or [None])[0]
        if bk and int(h["lane"]) == 1:
            br.append({"k": "崩すなら", "lane": bk["lane"], "name": bk["name"], "type": bk["type"], "p": bk["p"], "why": " ・ ".join(bk["why"])})
    rest = max(0.0, 1 - sum(x["p"] for x in br))
    checks = []
    tj = _lab_pair("tenji", "展示タイム1位")
    if tj:
        who = n or h
        checks.append(f"展示タイムで{who['lane']}号艇がいちばん速いか。展示タイム1位の艇は、3着以内が{tj[1]:.0f}%→{tj[0]:.0f}%に上がる")
    st = {int(b["lane"]): (b.get("traits") or {}).get("st") for b in boats}
    if all(st.get(k) is not None for k in (1, 2, 3, 4)) and st[4] <= min(st[1], st[2], st[3]) - 0.02:
        kd = _lab_pair("slowdash", "0.02秒以上速い")
        if kd:
            checks.insert(0, f"4号艇のスタートが内の3人より速い。こういうレースは4号艇の1着が{kd[1]:.0f}%→{kd[0]:.0f}%に上がる")
    hot = [x for x in rr.get("theories") or [] if x.get("id") == "hot" and "連勝" in x.get("title", "")]
    if hot:
        hp = _lab_pair("hot", "今節、2連勝中")
        ln = "・".join(f"{l}号艇" for x in hot for l in x.get("lanes") or [])
        if ln and hp:
            checks.append(f"{ln}は今節2連勝中。今節2連勝中の艇は、3着以内が{hp[1]:.0f}%→{hp[0]:.0f}%に上がる")
    if not n:
        checks.append("1号艇の展示タイムが4位以下なら、本命を疑う(展示の順位が下がるほど、勝つ見込みも下がる)")
    occ = [x for x in rr.get("theories") or [] if x.get("kind") == "occult"]
    gen = ((occ[0].get("gen") or f"{occ[0]['title']}か。関係ねえのは分かってる。でもワンチャン、あるだろ?") if occ
           else "理論もいいが、最後は展示だ。ピットを出ていく顔つきを見とけよ")   # その理論のひと言(実際の字・艇番に合わせたもの)を使う
    if occ and occ[0].get("gen") and "号艇" not in gen:   # だれの話か分かるように(「1号艇の名前に『竜』。…」)
        gen = f"{occ[0]['title']}。{gen}"
    who = n or h
    short = [f"展示タイムで{who['lane']}号艇がいちばん速いか"]
    if any(c.startswith("4号艇のスタートが内の3人より速い") for c in checks):
        short.append("4号艇のスタートが内より速い")
    return {"hook": hook, "branches": br, "rest": rest, "checks": checks[:2], "gen": gen, "mv": mv, "hon_type": ht, "ner_type": nt, "short": short}


def x_cards(series_name: str, grade: str, rr: dict, cards: dict | None, day: dt.date) -> list[str]:
    """X 用のカード2枚(スマホで読める大きな文字)。
    1枚目「このレースの分かれ道」: 問い → 本線と狙い目かも(見込みと理由、2着の候補)→ 展示で見るのはここ。
    2枚目「6人の材料」: 1着の見込み・平均ST・いちばん強い型、ゲンさんのひと言。"""
    rt = str(rr.get("race_type") or "")
    race = f"{rr['venue']}{rr['rno']}R"
    small = f"ミカタ新聞 {day.month}/{day.day} ・ " + ((grade + " " + series_name).strip() or "これからのレース")
    h1 = f"{race} {rt}"
    sub = f"{rr.get('deadline') or ''}締切"
    st_ = story(rr, cards)
    boats = sorted(rr.get("boats", []), key=lambda b: int(b["lane"]))
    out = []
    # 1枚目: 分かれ道
    if st_:
        nm = {int(b["lane"]): (b.get("name") or "") for b in boats}
        brs = ""
        for x in st_["branches"]:
            i = x["lane"] - 1
            extra = ""
            if x.get("second"):
                extra = f"<small>{x['lane']}号艇が勝ったときの2着: " + "・".join(f"{s['lane']}号艇 {_pct(s['p'])}%" for s in x["second"]) + "</small>"
            if x.get("ratio"):
                extra = f"<small>いつもの{x['lane']}号艇は{LANE_BASE[x['lane']]:.0f}%。それより高い</small>"
            brs += (f'<div class="br{" n" if x["k"] != "本命" else ""}"><span class="k">{e(x["k"])}</span>'
                    f'<div class="bm"><b><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{x["lane"]}</span>{e(x["name"])}{("の" + e(x["type"])) if x["type"] else ""}</b>'
                    f'{extra}' + (f'<p>{e(x["why"])}</p>' if x["why"] else "") + f'</div><div class="pc">{_pct(x["p"])}<small>%</small></div></div>')
        brs += f'<div class="br o"><span class="k">それ以外</span><div class="bm"><b>ほかの艇が勝つ</b></div><div class="pc">{_pct(st_["rest"])}<small>%</small></div></div>'
        chk = "".join(f"<li>{e(c)}</li>" for c in st_["checks"])
        body1 = (f'<div class="hook">{e(st_["hook"])}</div>'
                 f'<div class="sec"><p class="h">どう決まる?(勝つ見込み)</p>{brs}</div>'
                 + (f'<div class="sec"><p class="h">ここを見て決める</p><ul class="lines sm">{chk}</ul></div>' if chk else ""))
    else:
        body1 = '<div class="hook">6人の材料を並べました</div>'
    out.append(_card(small, h1, sub, body1))
    # 2枚目: 6人の材料
    rows = ""
    mx = max([b.get("p_win") or 0 for b in boats] + [0.01])
    ner = (st_.get("mv") or {}).get("ner") if st_ else None
    for b in boats:
        i = int(b["lane"]) - 1
        stv = (b.get("traits") or {}).get("st")
        c = (cards or {}).get(int(b.get("racer_id") or 0))
        tg = sorted(rc.tags_for(c), key=lambda t: -t["score"])[:1] if c else []
        rows += (f'<div class="row r1"><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'
                 f'<div class="nm">{e(b.get("name") or "")}<small>{e(str(b.get("class") or ""))} {_stm(stv)}'
                 + (f' <em>{e(tg[0]["t"])}</em>' if tg else "") + '</small></div>'
                 f'<div class="bar{" n" if ner is b else ""}"><i style="width:{(b.get("p_win") or 0) / mx * 100:.0f}%"></i></div>'
                 f'<div class="p">{_pct(b.get("p_win"))}<small>%</small></div></div>')
    bk = breakers(rr, cards, 2)
    il = bk.get("in_lose")
    bks = ""
    for x in bk.get("list") or []:
        i = x["lane"] - 1
        bks += (f'<div class="bk"><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{x["lane"]}</span>'
                f'<div class="bm"><b>{e(x["name"])}{("の" + e(x["type"])) if x["type"] else ""}</b>'
                + (f'<small>{e(" ・ ".join(x["why"]))}</small>' if x["why"] else "") + f'</div><div class="pc">{_pct(x["p"])}<small>%</small></div></div>')
    kim = bk.get("kim") or {}
    kim_s = " ・ ".join(f"{k} {_pct(kim[k])}%" for k in ("差し", "まくり", "まくり差し") if kim.get(k) is not None)
    weak = "".join(f"<li>{e(w)}</li>" for w in ([f"崩れ方の見込み: {kim_s}"] if kim_s else []) + (bk.get("weak") or []))
    gen = (st_ or {}).get("gen") or ""   # 3枚目(場所がある)に置くので、ひと言はそのまま
    body2 = (f'<div class="sec"><p class="h">6人の勝つ見込み<span class="key">スタートは平均の速さ ・ 赤字はその人の得意な型</span></p>{rows}</div>'
             + (f'<div class="sec"><p class="h">1号艇を崩すなら<span class="key">1号艇以外が勝つ見込み {_pct(il)}%(ふだん45%)</span></p>{bks}'
                + (f'<ul class="wk">{weak}</ul>' if weak else "") + '</div>' if bks else "")
             )
    gen_html = f'<div class="sec gen"><div class="gw"><span>ゲンさん</span><small>ゲンかつぎ歴40年の大先輩</small></div><p>{e(gen)}</p></div>' if gen else ""
    if not theory_lines(rr):   # 3枚目が無いときは2枚目に
        body2 += gen_html
    out.append(_card(small, h1, sub + " ・ 2/2", body2))
    # 3枚目: 当てはまる理論(札と、何を見てどれくらい違うかの1行)と、ことばの説明
    th = theory_lines(rr, 4)
    if th and gen_html and any(x.get("occ") for x in th):   # オカルト枠はゲンさんのひと言と同じ話なので、ひと言のほうに任せる(どちらでもない理論は残す)
        th = [x for x in th if not x.get("occ")]
    th = th[:4]
    # はみ出さないように、見込みの高さ(見出し1行+本文の行数)で数を決める(本文は1行に約36字)
    budget, used, keep = (560 if gen_html else 760), 0, []
    for x in th:
        hgt = 82 + 38 * max(1, -(-len(x["text"]) // 36))
        if keep and used + hgt > budget:
            break
        keep.append(x)
        used += hgt
    th = keep
    if th:
        lis = "".join(f'<li class="{x["cls"]}"><b>{e(x["title"])}</b><span class="bd {x["bcls"]}">{e(x["badge"])}</span><p>{e(x["text"])}</p></li>' for x in th)
        words = glossary(st_, th, 2)
        body3 = (f'<div class="sec"><p class="h">このレースに当てはまる理論<span class="key">緑=インに有利 ・ 赤=インに不利</span></p><ul class="ths">{lis}</ul></div>'
                 + (f'<div class="sec"><p class="h">ことば</p><ul class="words">' + "".join(f"<li><b>{e(k)}</b>{e(v)}</li>" for k, v in words) + "</ul></div>" if words else "")
                 + gen_html)
        out.append(_card(small, h1, sub + " ・ 3/3", body3))
        out[1] = out[1].replace(" ・ 2/2</p>", " ・ 2/3</p>")
    return out


BADGE_CLS = {"データで本物": "real", "人気どおり": "known", "人気以上に来る": "edge", "人気のわりにひかえめ": "low", "追試中": "trial", "オカルト枠": "occ"}
BADGE_NOTE = {"人気どおり": "人気どおり(配当は安め)", "人気以上に来る": "人気以上に来る(狙い目の材料)", "人気のわりにひかえめ": "人気のわりにひかえめ"}


def theory_lines(rr: dict, k: int = 3) -> list[dict]:
    """当てはまる理論を、札(信用度)と1行の説明(数字つき)で。インに有利なものを先、オカルト枠は最後に1つだけ。"""
    notes = list(rr.get("theories") or [])
    real = [n for n in notes if n.get("kind") != "occult"]
    occ = [n for n in notes if n.get("kind") == "occult"][:1]
    pri = {"人気以上に来る": 0, "データで本物": 1, "人気どおり": 2, "追試中": 3, "人気のわりにひかえめ": 4}
    real.sort(key=lambda n: (pri.get(str(n.get("badge")), 5), n.get("title", "")))
    # インに有利と不利を1つずつ必ず入れて(「悩ましい」の中身)、残りは信用度の高い札から
    pick = [x for x in (next((n for n in real if (n.get("dir") or 0) > 0), None), next((n for n in real if (n.get("dir") or 0) < 0), None)) if x]
    pick += [n for n in real if n not in pick][:max(0, k - len(pick))]
    pick.sort(key=lambda n: (-(n.get("dir") or 0) if (n.get("dir") or 0) else 0.5, pri.get(str(n.get("badge")), 5)))
    out = []
    for n in pick + occ:
        txt = str(n.get("text") or "")
        sents = [x for x in txt.split("。") if x.strip()]
        # 何を見て(1文目)+ どれくらい違うか(数字の入った最初の文)。数字が1文目にあればそれだけ
        first = sents[0] if sents else txt
        if not re.search(r"\d+(\.\d+)?(回|%)", first):   # 数字の書き方は「%」に変わった(2026-10-07)。古い「回」も拾う
            num = next((x for x in sents[1:] if re.search(r"\d+(\.\d+)?(回|%)", x)), None)
            if num:
                first = f"{first}。{num}"
        first = first + "。"
        if n.get("kind") == "occult":   # オカルト枠は「でも気分は大事」まで(楽しみ方として)
            first = "。".join(sents[:3]) + "。"
        d = n.get("dir") or 0
        badge = str(n.get("badge") or "")
        out.append({"title": n.get("title", ""), "badge": BADGE_NOTE.get(badge, badge), "bcls": BADGE_CLS.get(badge, ""),
                    "text": first if len(first) <= 110 else first[:108] + "…", "cls": "p" if d > 0 else ("m" if d < 0 else "o"),
                    "occ": n.get("kind") == "occult"})
    return out


WORDS = [("カド", "4コースのこと。助走を長くとれるので、まくりが出やすい"),
         ("逃げ", "1コースの艇が、そのまま先頭で回って勝つこと"),
         ("差し", "前の艇がターンでふくらんだ内側を抜けて勝つこと"),
         ("まくり", "外の艇が、内の艇の外を一気に回って抜くこと"),
         ("まくり差し", "外の艇が、内の艇の間を割って差すこと"),
         ("ST", "スタートタイミング。0に近いほど速い(.10 は 0.10秒)"),
         ("展示タイム", "レース前の試走で測る直線のタイム。速いほど足がいい"),
         ("前づけ", "外の枠の艇が、内のコースを取りにいくこと")]


def glossary(st_: dict, th: list[dict], k: int = 2) -> list[tuple[str, str]]:
    """このカードに出てくる言葉の説明(多くて2つ)。"""
    parts = [x["title"] + x["text"] for x in th]
    if st_:
        parts += [st_.get("hook", "")] + [b.get("type") or "" for b in st_.get("branches") or []] + list(st_.get("checks") or [])
    text = " ".join(parts)
    used = [(w, d) for w, d in WORDS if w in text]
    if any(w == "まくり差し" for w, _ in used):   # 「まくり差し」があるときは「まくり」「差し」を重ねて出さない
        used = [(w, d) for w, d in used if w not in ("まくり", "差し")]
    return used[:k]
