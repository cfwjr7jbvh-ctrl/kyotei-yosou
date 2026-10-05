"""毎日の記事「今日の理論ぶつけ」。朝の予想(docs/data/days/YYYY-MM-DD.json)に付いた理論のノートから作る。

買い目は出さない。出走表のレースごとに、検証ラボの理論のうち当てはまるものを並べ、
「インに追い風の理論」と「向かい風の理論」がぶつかるレースを『悩ましいレース』として出す。
  python scripts/theory_daily.py --day 2026-10-06 --out out/theory   (確認用。本番は ura_auto.py が記事タブに入れる)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import mag, theories  # noqa: E402
from kyotei.card_render import gull_svg  # noqa: E402
from kyotei.publish import read_json  # noqa: E402
from kyotei.xtext import xlen  # noqa: E402

e = html.escape
INDEX = [("slowdash", "カドの一撃の形"), ("hot", "今節の勢い(2連勝・2走続けて大敗)"), ("penalty", "期末の事故率"), ("wind", "強い風の予報"), ("humid", "湿った空気"),
         ("formation", "前づけの常連"), ("a1in", "隠れA2の1号艇"), ("fixed", "進入固定"), ("final", "準優・優勝戦"), ("bangumi", "番組の癖"), ("flying", "フライング直後"),
         ("rest", "長い休み明け"), ("newmotor", "新モーター")]
WEEK = "月火水木金土日"


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


def build(day: dt.date, data: dict) -> dict | None:
    races = [r for r in data.get("races", []) if r.get("theories") is not None]
    if not races:
        return None
    n_notes = sum(len([n for n in r["theories"] if n["kind"] != "occult"]) for r in races)
    conf = [r for r in races if (r.get("th_sum") or {}).get("conflict")]
    conf.sort(key=lambda r: -len(r["theories"]))
    rich = sorted(races, key=lambda r: -len([n for n in r["theories"] if n["kind"] in ("edge", "trial", "real")]))[:5]
    idx = defaultdict(list)
    for r in races:
        for n in r["theories"]:
            idx[n["id"]].append((r, n))
    cal = _calendar(day)
    title = f"今日の理論ぶつけ {day.month}/{day.day}({WEEK[day.weekday()]})"
    lead = (f"今日の出走表{len(races)}レースに、検証ラボの理論をぶつけた。当てはまった理論は合計{n_notes}(オカルト枠はのぞく)。"
            f"インに追い風の理論と向かい風の理論がぶつかる『悩ましいレース』は{len(conf)}レース。買い目ではなく、考え方のヒント。どの理論に乗るかは、あなた次第")

    def race_name(r):
        return f"{r['venue']}{r['rno']}R({r.get('deadline') or '-'})"

    def note_html(n):
        lanes = "".join(f'<span class="ln l{x}">{x}</span>' for x in n.get("lanes") or [])
        return (f'<li class="th {e(n["kind"])}"><b>{e(n["title"])}</b>{lanes}<span class="bd">{e(n["badge"])}</span><p>{e(n["text"])}</p></li>')

    sec_conf = ""
    for r in conf[:6]:
        sm = r["th_sum"]
        sec_conf += (f'<div class="rc"><p class="rc-h">{e(race_name(r))}</p><p class="vs"><span class="p">インに追い風: {e("・".join(sm["plus"]))}</span>'
                     f'<span class="m">インに向かい風: {e("・".join(sm["minus"]))}</span></p><ul>{"".join(note_html(n) for n in r["theories"] if n["kind"] != "occult")}</ul></div>')
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
<p class="cv-kicker">買い目は言わない。考え方を並べる</p><h1 class="cv-h">{e(title)}</h1><p class="cv-deck">{e(lead)}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ / 暦とオカルト担当 ゲンさん<br>理論の数字は検証ラボ(公式の成績データを独自に集計)から</span></div></div></header>
<main class="mag">
<section><span class="label">今日の暦(オカルト枠)</span>
<p class="dlg"><b class="g">ゲンさん</b>「暦も名前もモーター番号も、レースに関係ねえのは分かってる。でもな、ワンチャン大いなる力が働いてるかもしれねえだろ?」<br>
<b class="m">ミカタ</b>「わかる。だから、データで差が出なかったものも『オカルト枠』として並べておくね。乗るかどうかは、気分しだい」</p><ul>{cal_html or "<li>今日は特別な暦の日ではない。……ふつうの日こそ、データの出番</li>"}</ul>
<p>名前・モーター番号のオカルト: {e(occ_txt or "今日は見当たらない")}</p></section>
<section><span class="label">今日の悩ましいレース</span><p>インに有利な理論と不利な理論が、同じレースでぶつかっている。どっちに乗る?</p>{sec_conf}</section>
<section><span class="label">理論がいちばん集まったレース</span>{sec_rich}</section>
<section><span class="label">理論別の索引</span>{sec_idx}</section>
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>理論は『正解』じゃなくて『見方』。いくつかの理論がぶつかるレースほど、自分の予想を立てる楽しさがあるよ</p></blockquote>
<blockquote class="ft-quote gen">{gull_svg(64, bg="#ffffff", cls="q", who="gen")}<p><small>ゲンさんの返し</small>理論にすがりたい日もあるさ。どの理論を信じるかで、レースの見え方が変わる。それが楽しいんだ</p></blockquote>
<section class="method"><h3>データについて</h3><p>理論の数字は、ミカタ検証ラボで公式の成績データ(2023年10月〜)を集計したもの。『データで本物』は偶然では出にくい差、『オッズも知ってる』はオッズにもう反映されている差、『オカルト枠』は差が出なかった理論。
朝の出走表の時点の情報で作っています(展示の情報は入っていません)。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ 理論ぶつけ ・ 毎朝更新。買い目は売りません。</span></footer></main></body></html>"""
    # note 本文
    lines = [f"【タイトル案】{title}|悩ましいレース{len(conf)}つ", "", lead, ""]
    if cal:
        lines += ["■今日の暦(オカルト枠)"] + [f"・{x}" for x in cal] + [""]
    lines += ["■今日の悩ましいレース"]
    for r in conf[:6]:
        sm = r["th_sum"]
        lines += [f"・{race_name(r)}", f"  インに追い風: {'・'.join(sm['plus'])}", f"  インに向かい風: {'・'.join(sm['minus'])}"]
    lines += ["", "■理論別の索引"]
    for tid, nm in INDEX:
        if tid in idx:
            lines.append(f"・{nm}: " + "、".join(race_name(r) for r, n in idx[tid][:8]))
    lines += ["", "この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"]
    # X
    if conf:
        r = conf[0]; sm = r["th_sum"]
        body = (f"【今日の理論ぶつけ】{day.month}/{day.day}\n\n今日の悩ましいレースは{race_name(r)}。\nインに追い風: {'・'.join(sm['plus'])}\nインに向かい風: {'・'.join(sm['minus'])}\n\n"
                f"ゲンさん「どっちの理論に乗るかで、レースの見え方が変わるんだよ」\n\nあなたはどっちに乗る?")
    else:
        body = f"【今日の理論ぶつけ】{day.month}/{day.day}\n\n今日の出走表{len(races)}レースに、検証ラボの理論をぶつけました。当てはまった理論は{n_notes}。\n\nゲンさん「理論にすがりたい日もあるさ」"
    if xlen(body) > 280:
        body = f"【今日の理論ぶつけ】{day.month}/{day.day}\n\n悩ましいレース{len(conf)}つ。インに追い風の理論と向かい風の理論がぶつかっています。\n\nあなたはどっちに乗る?"
    return {"title": title, "html": page, "note": "\n".join(lines), "x": f"--- 投稿1({xlen(body)}/280) ---\n{body}", "n_conf": len(conf), "n_races": len(races)}


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
