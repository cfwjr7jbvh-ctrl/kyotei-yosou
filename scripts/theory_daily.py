"""毎日の記事「今日の理論ぶつけ」。朝の予想(docs/data/days/YYYY-MM-DD.json)に付いた理論のノートから作る。

買い目は出さない。出走表のレースごとに、検証ラボの理論のうち当てはまるものを並べ、
「インに有利な理論」と「インに不利な理論」がぶつかるレースを『悩ましいレース』として出す。
  python scripts/theory_daily.py --day 2026-10-06 --out out/theory   (確認用。本番は ura_auto.py が記事タブに入れる)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import mag, theories  # noqa: E402
from kyotei.card_render import gull_svg  # noqa: E402
from kyotei.publish import read_json  # noqa: E402
from kyotei.xtext import xlen  # noqa: E402

e = html.escape
INDEX = [("slowdash", "カドの一撃の形"), ("hot", "今節の勢い(2連勝中・2走続けて5・6着)"), ("penalty", "期末の事故率"), ("wind", "強い風の予報"), ("humid", "湿った空気"),
         ("formation", "前づけの常連"), ("a1in", "隠れA2の1号艇"), ("fixed", "進入固定"), ("final", "準優・優勝戦"), ("bangumi", "番組の癖"), ("flying", "フライング直後"),
         ("rest", "長い休み明け"), ("newmotor", "新モーター")]
WEEK = "月火水木金土日"


_NUM2 = re.compile(r"(\d+(?:\.\d)?%)[((]([^))%\d]*)(\d+(?:\.\d)?%)[))]")   # 「69%(予選は55%)」
_NUM1 = re.compile(r"1着が(\d+(?:\.\d)?%)の枠")                                  # 番組の癖「1号艇の1着が72%の枠」


_ARR = re.compile(r"(\d+(?:\.\d)?)%→(\d+(?:\.\d)?)%")                     # 「ふだん51%→57%に上がる」(2026-10-07〜 の書き方)


def _p(x: float) -> str:
    return f"{x:.1f}%" if x < 10 else f"{int(x + 0.5)}%"


def clash_stat(r: dict, title: str) -> dict | None:
    """悩ましいレースの理論1つぶんの数字を形で: {what(何の率), ref(くらべる相手), a(相手の率), b(この条件の率), edge(人気とのくらべ)}。
    札に num があればそれ(2026-10-08〜)。無ければ札の文から読む。読めなければ None"""
    n = next((x for x in r.get("theories") or [] if x.get("title") == title and x.get("kind") != "occult"), None)
    if not n:
        return None
    if n.get("num"):
        return dict(n["num"])
    text, badge = n.get("text") or "", n.get("badge") or ""
    edge = 1 if "人気以上" in badge else -1 if "ひかえめ" in badge else 0 if "人気どおり" in badge else None
    lanes = n.get("lanes") or []
    m = _NUM2.search(text)
    if m:
        seg = re.split(r"[。、]", text[:m.start()])[-1]   # 数字のすぐ前の句で、何の率かを決める
        what = "3着以内" if "3着以内" in seg else "カドの1着" if "カド" in seg else "1コースの艇の1着" if "1コース" in seg else "1号艇の1着"
        return {"what": what, "ref": m.group(2).strip().removesuffix("は") or "ふだん", "a": float(m.group(3)[:-1]), "b": float(m.group(1)[:-1]), "edge": edge}
    m = _ARR.search(text)
    if m:
        seg = re.split(r"[。]", text[:m.start()])[-1]
        a, b = float(m.group(1)), float(m.group(2))
        if "以外が勝つ" in seg:   # 「1号艇以外が勝つのはふだん43%→53%」→ 1号艇の1着 57%→47%(物差しをそろえる)
            what, a, b = ("1コースの艇の1着" if "1コース" in seg else "1号艇の1着"), round(100 - a, 1), round(100 - b, 1)
        elif "3着以内" in seg:
            what = f"{lanes[0]}号艇の3着以内" if len(lanes) == 1 else "3着以内"
        elif "カド" in seg:
            what = "カドの1着"
        elif "1コース" in seg:
            what = "1コースの艇の1着"
        else:
            what = "1号艇の1着"
        return {"what": what, "ref": "ふだん", "a": a, "b": b, "edge": edge}
    m = _NUM1.search(text)
    return {"what": "1号艇の1着", "ref": "", "a": None, "b": float(m.group(1)[:-1]), "edge": edge} if m else None


def clash_num(r: dict, title: str) -> str:
    """悩ましいレースの理論1つぶんの数字(「1号艇の1着 予選55%→69%」)。数字は理論の札(検証ラボの JSON から入る)を読む。
    名前だけだと、どちらの理論が重いか読み手が比べられない(X の1行目・2行目は数字、が市場の型)。読めないときは空。"""
    st = clash_stat(r, title)
    if not st:
        return ""
    if st.get("a") is None:
        return f"{st['what']}{_p(st['b'])}"
    return f"{st['what']} {st['ref']}{_p(st['a'])}→{_p(st['b'])}"


def _sg(x: float) -> str:
    return ("+" if x >= 0 else "−") + (f"{abs(x):.1f}" if abs(x) < 10 else f"{int(abs(x) + 0.5)}")


def clash_view(plus: tuple | None, minus: tuple | None, short: bool = False) -> str:
    """悩ましいレースの「見方」(2026-10-08 ユーザー「どっちがどれくらいの影響があって、こんな感じならこういう考えが妙味があるかも?みたいな情報を入れないと」)。
    plus/minus: (理論の名前, clash_stat)。①同じ物差しなら、どっちが大きく動かすか ②人気とのくらべ(人気以上・ひかえめ)から、どっちから考えると妙味があるか。
    買い目は出さない。short=True は X の本文用(短く)"""
    out = []
    ps, ms = (plus[1] if plus else None), (minus[1] if minus else None)
    if ps and ms and ps["what"] == ms["what"] and ps.get("a") is not None and ms.get("a") is not None:
        dp, dm = ps["b"] - ps["a"], ms["b"] - ms["a"]
        big = plus[0] if abs(dp) >= abs(dm) else minus[0]
        out.append(f"動く幅は「{big}」が大きい" + ("。" if short else f"({_sg(dp)}と{_sg(dm)})。"))
    ep, em = (ps or {}).get("edge"), (ms or {}).get("edge")
    one = "1号艇" if "1号艇" in ((ps or ms or {}).get("what") or "1号艇") else "1コースの艇"
    but = "でも" if out else ""
    if em == -1:
        out.append(f"{but}「{minus[0]}」の{one}は人気のわりにひかえめ。" + ("" if short else f"{one}に人気が集まるなら、") + f"{one}以外に妙味があるかも")
    elif ep == 1:
        out.append(f"{but}「{plus[0]}」の{one}は人気以上に来ている。" + ("" if short else f"{one}の人気がそこそこなら、") + f"{one}に妙味があるかも")
    elif ep == -1:
        out.append(f"{but}「{plus[0]}」でも{one}は人気のわりにひかえめ。人気が{one}に寄りすぎていないかを見よう")
    elif em == 1:
        out.append(f"{but}「{minus[0]}」でも{one}は人気以上に来ている。" + ("" if short else f"{one}の人気が落ちていたら、") + f"{one}に妙味があるかも")
    elif ep == 0 and em == 0:
        out.append("どちらも人気どおり。締切前の人気がどっちに寄っているかを見よう")
    else:
        out.append("締切前の人気がどっちに寄っているかを見よう")
    return "".join(out)


def clash_item(r: dict, title: str) -> dict:
    return {"title": title, "lanes": next((x.get("lanes") or [] for x in r.get("theories") or [] if x.get("title") == title), []), "stat": clash_stat(r, title)}


def clash_mains(r: dict) -> tuple:
    """両側の主役の理論 (名前, 数字)。両側に同じ物差し(1号艇の1着など)があればその組み合わせを優先。"""
    sm = r.get("th_sum") or {}
    P = [(t, clash_stat(r, t)) for t in sm.get("plus") or []]
    M = [(t, clash_stat(r, t)) for t in sm.get("minus") or []]
    P, M = [x for x in P if x[1]] or P[:1], [x for x in M if x[1]] or M[:1]
    for p_ in P:
        for m_ in M:
            if p_[1] and m_[1] and p_[1]["what"] == m_[1]["what"]:
                return p_, m_
    return (P[0] if P else None), (M[0] if M else None)


def clash_side(r: dict, titles: list[str], k: int | None = None) -> str:
    """「準優勝戦(1号艇の1着 予選55%→69%)・進入固定(…)」。k を指定すると先頭の k 個だけ数字つきで、残りは「ほか◯つ」。"""
    k = len(titles) if k is None else k
    out = "・".join(t + (f"({c})" if (c := clash_num(r, t)) else "") for t in titles[:k])
    return out + (f" ほか{len(titles) - k}つ" if len(titles) > k else "")


def _calendar(day: dt.date) -> list[str]:
    out = []
    rk = theories._rokuyo(day)
    if rk:
        if rk == "赤口":
            out.append("今日は赤口。六曜でいちばん1号艇が勝っているのは、なぜか赤口(追試中)")
        else:
            out.append(f"今日は{rk}。六曜で成績はほとんど変わらない。でも気分は大事")
    age = theories._moon_age(day)
    if abs(age - 14.77) <= 1.2:
        out.append("今日は満月のころ。満月でも荒れ方はふだんと同じ。でも満月のナイターは特別な気分")
    return out


def build(day: dt.date, data: dict, view: bool = False) -> dict | None:
    """view=True: 悩ましいレースに「見方」(どっちが大きく動かすか・人気とのくらべ)を入れる新しい形(ユーザーの確認が出るまで False)"""
    races = [r for r in data.get("races", []) if r.get("theories") is not None]
    try:   # 出す前の見張り: 出走表と合わない札(名前に無い字など)は外す(kyotei.factcheck)
        from kyotei import factcheck
        for r in races:
            factcheck.clean_notes(r)
    except Exception as ex:  # noqa: BLE001
        print("factcheck failed:", ex)
    if not races:
        return None
    n_notes = sum(len([n for n in r["theories"] if n["kind"] != "occult"]) for r in races)
    conf = [r for r in races if (r.get("th_sum") or {}).get("conflict")]
    conf.sort(key=lambda r: -len(r["theories"]))
    rich = sorted(races, key=lambda r: -len([n for n in r["theories"] if n["kind"] in ("edge", "trial", "real")]))[:5]
    idx = defaultdict(list)   # 理論ごとに (レース, 当てはまった艇) 。同じレースで複数の艇なら1つにまとめる
    for r in races:
        by = {}
        for n in r["theories"]:
            if n["id"] in by:
                by[n["id"]]["lanes"] = sorted(set(by[n["id"]].get("lanes") or []) | set(n.get("lanes") or []))
            else:
                by[n["id"]] = dict(n)
        for tid, n in by.items():
            idx[tid].append((r, n))
    cal = _calendar(day)
    # 記事の型(2026-10-06 決定): タイトルで今日いちばんの見どころ → ミカタのひと言 → 悩ましいレース → 集まったレース → 索引 → 最後にゲンさんのゲンかつぎ(オカルト枠)
    def race_name(r):
        return f"{r['venue']}{r['rno']}R({r.get('deadline') or '-'})"

    def race_short(r):
        return f"{r['venue']}{r['rno']}R"

    base_title = f"今日の理論ぶつけ {day.month}/{day.day}({WEEK[day.weekday()]})"
    if conf:
        top = conf[0]; sm0 = top["th_sum"]
        title = f"{base_title}|悩ましいのは{race_short(top)}"
        headline = f"悩ましいのは、{race_short(top)}"
        np_, nm_ = clash_num(top, sm0["plus"][0]), clash_num(top, sm0["minus"][0])
        lead = (f"いちばん悩ましいのは{race_name(top)}。インに有利な『{sm0['plus'][0]}』{f'({np_})' if np_ else ''}と、不利な『{sm0['minus'][0]}』{f'({nm_})' if nm_ else ''}がぶつかる。"
                f"今日の出走表{len(races)}レースに検証ラボの理論をぶつけて、当てはまったのは{n_notes}。悩ましいレースは{len(conf)}つ。どの理論に乗るかは、あなた次第")
    else:
        top = rich[0] if rich else None
        title = base_title + (f"|理論が集まったのは{race_short(top)}" if top and top["theories"] else "")
        headline = (f"理論が集まったのは、{race_short(top)}" if top and top["theories"] else "今日の理論ぶつけ")
        lead = (f"今日の出走表{len(races)}レースに検証ラボの理論をぶつけて、当てはまったのは{n_notes}。理論どうしがぶつかるレースはなし。素直な日かも。"
                + (f"理論がいちばん集まったのは{race_name(top)}" if top and top["theories"] else ""))

    def note_html(n):
        lanes = "".join(f'<span class="ln l{x}">{x}</span>' for x in n.get("lanes") or [])
        return (f'<li class="th {e(n["kind"])}"><b>{e(n["title"])}</b>{lanes}<span class="bd">{e(n["badge"])}</span><p>{e(n["text"])}</p></li>')

    sec_conf = ""
    for r in conf[:6]:
        sm = r["th_sum"]
        sec_conf += (f'<div class="rc"><p class="rc-h">{e(race_name(r))}</p><p class="vs"><span class="p">インに有利: {e("・".join(sm["plus"]))}</span>'
                     f'<span class="m">インに不利: {e("・".join(sm["minus"]))}</span></p><ul>{"".join(note_html(n) for n in r["theories"] if n["kind"] != "occult")}</ul></div>')
    if not sec_conf:
        sec_conf = "<p>今日は、理論どうしがぶつかるレースは見つからなかった。素直な日かも</p>"
    sec_rich = "".join(f'<div class="rc"><p class="rc-h">{e(race_name(r))}<small>理論{len(r["theories"])}つ</small></p><ul>{"".join(note_html(n) for n in r["theories"])}</ul></div>'
                       for r in rich if r["theories"])
    sec_idx = ""
    for tid, nm in INDEX:
        if tid in idx:
            lst = "、".join(race_name(r) + (f"[{'・'.join(str(x) for x in n['lanes'])}号艇]" if n.get("lanes") and tid not in ("final", "fixed", "bangumi", "wind", "humid", "newmotor") else "")
                           for r, n in idx[tid][:12])
            more = f" ほか{len(idx[tid]) - 12}" if len(idx[tid]) > 12 else ""
            sec_idx += f"<h4>{e(nm)}<small>{len(idx[tid])}件</small></h4><p class='ix'>{e(lst + more)}</p>"
    occ = idx.get("name", []) + idx.get("lucky7", [])
    occ_txt = "、".join(f"{race_name(r)}[{n['title']}]" for r, n in occ[:10])
    cal_html = "".join(f"<li>{e(x)}</li>" for x in cal)
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex"><title>{e(title)}</title>{mag.FONTS}<style>{mag.CSS}
.rc{{background:var(--card);border:2px solid var(--rule);padding:12px 14px;margin:0 0 12px}} .rc-h{{margin:0 0 6px;font:700 16px/1.5 var(--sans)}} .rc-h small{{margin-left:8px;font-weight:500;font-size:12px;color:var(--mute)}}
.rc ul{{list-style:none;margin:0;padding:0;display:grid;gap:8px}} .th{{border-left:4px solid var(--rule);padding:2px 0 2px 10px;font-size:14px}} .th p{{margin:3px 0 0;font-size:13.5px;line-height:1.7}}
.th.edge{{border-color:#c98a00}} .th.real,.th.known,.th.trial{{border-color:#2e8b57}} .th.occult{{border-color:#8a5cc8}}
.bd{{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid var(--rule);margin-left:6px;color:var(--mute)}} .ln{{display:inline-block;min-width:18px;text-align:center;font:700 12px var(--num);border:1px solid var(--ink);margin-left:4px}}
.vs{{display:grid;gap:4px;margin:0 0 8px;font-size:13px}} .vs .p{{color:#1e6b3f;font-weight:700}} .vs .m{{color:#a3121a;font-weight:700}}
.dlg{{background:#f1e9fb;border:2px solid #8a5cc8;padding:10px 12px;font-size:14px;line-height:1.8}} .dlg .g{{color:#0b5fb4}} .dlg .m{{color:#c8141c}}
.mag h4{{margin:14px 0 4px;font:400 16px var(--head)}} .mag h4 small{{margin-left:8px;font-size:12px;color:var(--mute)}} .ix{{margin:0;font-size:13.5px;line-height:1.8}}
</style></head><body>
<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ 理論ぶつけ<small>出走表に、検証ラボの理論を全部ぶつける</small></div><div class="issue"><b>DAILY</b><br>{e(day.isoformat())}</div></div>
<p class="cv-kicker">{e(base_title)} ・ 考え方を並べる</p><h1 class="cv-h">{e(headline)}</h1><p class="cv-deck">{e(lead)}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ / 暦とオカルト担当 ゲンさん(ゲンかつぎ歴40年の大先輩)<br>理論の数字は検証ラボ(公式の成績データを独自に集計)から</span></div></div></header>
<main class="mag">
<section><span class="label">今日の悩ましいレース</span><p>インに有利な理論と不利な理論が、同じレースでぶつかっている。どっちに乗る?</p>{sec_conf}</section>
<section><span class="label">理論がいちばん集まったレース</span>{sec_rich}</section>
<section><span class="label">理論別の索引</span>{sec_idx}</section>
<section><span class="label">おまけ: ゲンさんのゲンかつぎ(オカルト枠)</span>
<p class="dlg"><b class="g">ゲンさん(ゲンかつぎ歴40年の大先輩)</b>「関係ねえのは分かってる。でもワンチャン、大いなる力が働いてるかもしれねえだろ?」 <b class="m">ミカタ</b>「乗るかどうかは、気分しだいだね」</p><ul>{cal_html or "<li>今日は特別な暦の日ではない。……ふつうの日こそ、データの出番</li>"}</ul>
<p>名前・モーター番号のオカルト: {e(occ_txt or "今日は見当たらない")}</p></section>
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>理論は『正解』じゃなくて『見方』。いくつかの理論がぶつかるレースほど、自分の予想を立てる楽しさがあるよ</p></blockquote>
<blockquote class="ft-quote gen">{gull_svg(64, bg="#ffffff", cls="q", who="gen")}<p><small>ゲンさんの返し</small>理論にすがりたい日もあるさ。どの理論を信じるかで、レースの見え方が変わる。それが楽しいんだ</p></blockquote>
<section class="method"><h3>データについて</h3><p>理論の数字は、ミカタ検証ラボで公式の成績データ(2023年10月〜)を集計したもの。『データで本物』は偶然では出にくい差、『人気どおり』は人気にも出ている差(配当は安め)、『人気以上に来る』は人気より多く来ている差、『オカルト枠』は差が出なかった理論。
朝の出走表の時点の情報で作っています(展示の情報は入っていません)。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ 理論ぶつけ ・ 毎朝更新。考え方を並べる。どれに乗るかは、あなた次第。</span></footer></main></body></html>"""
    # note 本文
    lines = [f"【タイトル案】{title}", "", lead, "", "■今日の悩ましいレース"]
    for r in conf[:6]:
        sm = r["th_sum"]
        lines += [f"・{race_name(r)}", f"  インに有利: {'・'.join(sm['plus'])}", f"  インに不利: {'・'.join(sm['minus'])}"]
    lines += ["", "■理論別の索引"]
    for tid, nm in INDEX:
        if tid in idx:
            lines.append(f"・{nm}: " + "、".join(race_name(r) for r, n in idx[tid][:8]))
    lines += ["", "■おまけ: ゲンさんのゲンかつぎ(オカルト枠)", "(ゲンさん=ゲンかつぎ歴40年の大先輩)"] + [f"・{x}" for x in cal] + ([f"・名前・モーター番号: {occ_txt}"] if occ_txt else [])
    lines += ["", "この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"]
    # X
    if conf:
        r = conf[0]; sm = r["th_sum"]
        # 市場の作りに合わせる(2026-10-06): 1行目は 場名+R+締切、1行1情報、ゲンさんのセリフは画像の中
        dl = f" 締切{r['deadline']}" if r.get("deadline") else ""
        # 2026-10-07: 理論の名前だけでなく数字も(「準優勝戦(1号艇の1着 予選55%→69%)」)。入る長さで、数字の多い形から選ぶ
        tail_ = f"\n\nあなたはどっちに乗る?\n#今日の理論ぶつけ #ボートレース{r['venue']} #競艇"
        mains = clash_mains(r)
        vw = clash_view(*mains, short=True) if view else ""
        if vw:   # 見方を入れる形(確認が出たら): 両側は主役の1つずつ、タグは場名と #競艇 だけ(入らなければタグなし)
            def _sd(t_):
                return t_[0] + (f"({c})" if (c := clash_num(r, t_[0])) else "") if t_ else ""
            for tg in (f"\n#ボートレース{r['venue']} #競艇", ""):
                b = (f"今日の悩ましいレース|{race_short(r)}{dl}\n\nインに有利: {_sd(mains[0])}\nインに不利: {_sd(mains[1])}\n\n→ {vw}\n\nあなたはどっちに乗る?{tg}")
                if xlen(b) <= 280:
                    tail_ = None
                    body = b
                    break
        body = "" if tail_ is not None else body
        for k in ((None, 2, 1) if tail_ is not None else ()):
            b = f"今日の悩ましいレース|{race_short(r)}{dl}\n\nインに有利: {clash_side(r, sm['plus'], k)}\nインに不利: {clash_side(r, sm['minus'], k)}{tail_}"
            if xlen(b) <= 280:
                body = b
                break
        if not body:
            body = f"今日の悩ましいレース|{race_short(r)}{dl}\n\nインに有利: {'・'.join(sm['plus'])}\nインに不利: {'・'.join(sm['minus'])}{tail_}"
    else:
        body = f"【今日の理論ぶつけ】{day.month}/{day.day}\n\n今日の出走表{len(races)}レースに、検証ラボの理論をぶつけました。当てはまった理論は{n_notes}。\n\nゲンかつぎ歴40年のゲンさん「理論にすがりたい日もあるさ」"
    if xlen(body) > 280 and conf:
        body = (f"今日の悩ましいレース|{race_short(r)}{dl}\n\nインに有利: {sm['plus'][0]}\nインに不利: {sm['minus'][0]}\n\nあなたはどっちに乗る?\n#今日の理論ぶつけ #ボートレース{r['venue']} #競艇")
    if xlen(body) > 280:
        body = f"【今日の理論ぶつけ】{day.month}/{day.day}\n\n悩ましいレース{len(conf)}つ。インに有利な理論と不利な理論がぶつかっています。\n\nあなたはどっちに乗る?"
    # X の画像: 記事の紙面は撮らない(スマホで文字が5pxになる)。悩ましいレース1つを大きな文字のカードに(kyotei.xcard)
    card = None
    if conf:
        from kyotei.xcard import theory_card_html
        r = conf[0]; sm = r["th_sum"]

        def items(titles):
            return [{"title": t_, "lanes": next((x.get("lanes") or [] for x in r["theories"] if x.get("title") == t_), []), "num": clash_num(r, t_)}
                    for t_ in titles]
        if view:
            from kyotei.xcard import clash_card_html
            mains = clash_mains(r)
            card = clash_card_html(f"{day.month}/{day.day}({WEEK[day.weekday()]})", race_short(r), r.get("deadline") or "", str(r.get("race_type") or ""),
                                   [clash_item(r, t_) for t_ in sm["plus"]], [clash_item(r, t_) for t_ in sm["minus"]], clash_view(*mains))
        else:
            card = theory_card_html(f"{day.month}/{day.day}({WEEK[day.weekday()]})", race_short(r), r.get("deadline") or "", str(r.get("race_type") or ""),
                                    items(sm["plus"]), items(sm["minus"]), len(conf) - 1)
    return {"title": title, "html": page, "card": card, "note": "\n".join(lines),
            "x": f"--- 投稿1({xlen(body)}/280) ---\n{body}\n\n画像: 悩ましいレースのカード(大きな文字の1枚)\n出し方: 記事のリンクは本文に入れず、この投稿への自分の返信に付ける",
            "n_conf": len(conf), "n_races": len(races)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--data", default=None, help="予想のJSON(省略時は docs/data/days/<day>.json)")
    ap.add_argument("--out", default=str(ROOT / "out/theory"))
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.day) if a.day else dt.date.today()
    data = read_json(pathlib.Path(a.data) if a.data else ROOT / f"docs/data/days/{day.isoformat()}.json")
    t = build(day, data)
    if not t:
        print("理論のついた予想がありません"); return
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / f"theory_{day.isoformat()}.html").write_text(t["html"], encoding="utf-8")
    (out / f"theory_{day.isoformat()}.txt").write_text(t["note"] + "\n\n" + t["x"], encoding="utf-8")
    print("wrote", out, t["n_races"], "races", t["n_conf"], "conflicts")


if __name__ == "__main__":
    main()
