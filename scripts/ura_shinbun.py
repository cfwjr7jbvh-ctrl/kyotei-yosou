"""裏新聞の下書きを作る: 大会の出場選手一覧から、注目選手の選定・見出し案・ひと言コメント・選手カードをまとめる。

python scripts/ura_shinbun.py --title "SG ボートレースダービー" --venue 尼崎 --racers 峰竜太,4238,池田浩二 --out out/ura.html
python scripts/ura_shinbun.py --title "..." --venue 13 --file 出場選手.txt --out out/ura.html   # 1行に1人(登番か名前)

方針(設計メモ「今後の目標」):
- 数字はすべて公式の成績データを自分たちで集計したもの(出走表・オッズの表・写真は使わない)
- 見出しはネタっぽくてよいが、必ずタグ(基準を満たした数字)か集計の数字に裏付けがあるものだけ。選手をけなす書き方はしない
- 下書きなので、出す前に人が読んで直す。根拠の数字と基準は本文の下にすべて残す
出力: HTML(見た目の確認・画像化用)と、同じ名前の .txt(note に貼る本文の下書き)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import nerai  # noqa: E402
from kyotei import racer_card as rc  # noqa: E402
from kyotei.card_render import gull_svg, radar_svg  # noqa: E402

LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
LANE_FG = ["#102230", "#ffffff", "#ffffff", "#ffffff", "#102230", "#ffffff"]
e = html.escape


# ---------------------------------------------------------------- 見出しとコメント
def _v(c, path, default=None):
    x = c
    for k in path:
        x = x.get(k) if isinstance(x, dict) else None
        if x is None:
            return default
    return x


def headlines(c: dict, t: dict) -> list[str]:
    """タグ1つにつき見出し案を2つ。数字はタグの根拠と同じもの。"""
    n, k = c["name"], c["kim"]
    g = rc.GROUP_NAME.get(c["grp"], "")
    cat = t["cat"]
    if cat == "start":
        return [f"スリットの主役は{n} 平均ST{rc.st_fmt(c['st']['avg'])}は{g}{rc.top(c['st']['grp'])}",
                f"{n}、スタートで先手を取る{c['st']['n']}走の平均ST{rc.st_fmt(c['st']['avg'])}"]
    if cat == "ex":
        return [f"展示STは信じていい {n}のずれは平均{c['ex']['mae']:.3f}秒",
                f"{n}は「展示どおり」 本番STとのずれ{g}{rc.top(c['ex']['grp'])}の小ささ"]
    if cat == "ex2":
        return [f"本番でひと踏み込み {n} 展示→本番のST差{c['ex']['delta']:+.2f}秒(全体の中央値{c['ex']['pop_delta']:+.2f}秒)",
                f"{n}は本番に合わせてくる 展示→本番のST差が{g}{rc.top(c['ex']['d_grp'])}の小ささ"]
    if cat == "nige":
        x = k["nige"]
        return [f"インに入れば鉄板級 {n}の逃げ率{x['w'] / x['n']:.0%}",
                f"{n}、1コース{x['n']}走で{x['w']}回逃げ切り"]
    if cat == "sashi":
        x = k["sashi"]
        return [f"差しのスペシャリスト{n} 2コース以遠から差し{x['w']}勝",
                f"{n}の差しは{g}{rc.top(x['grp'])} 内が流れたら飛び込む"]
    if cat == "makuri":
        x = k["makuri"]
        return [f"まくり一撃の{n} まくりで{x['w']}勝", f"{n}が外から攻める まくり勝ち{g}{rc.top(x['grp'])}"]
    if cat == "mz":
        x = k["mz"]
        return [f"まくり差しの職人{n} 3コース以遠から{x['w']}勝",
                f"{n}、ハンドル一閃のまくり差しは{g}{rc.top(x['grp'])}"]
    if cat == "out":
        return [f"外枠でも消せない{n} 4〜6コースで3着内率がコース平均{rc.pts(c['out']['res'])}",
                f"{n}は枠を選ばない 外からの上積み{g}{rc.top(c['out']['grp'])}"]
    if cat == "front":
        return [f"動く{n} 2枠以上の{c['front']['rate']:.0%}で内のコースへ", f"進入から目が離せない{n}"]
    if cat == "rough":
        return [f"荒れ水面ほど頼れる{n} 波・風がある日は3着内率{rc.pts(c['rough']['res'])}",
                f"{n}、水面が荒れたら出番"]
    if cat == "kake":
        return [f"勝負駆けで本領の{n} 予選最終日は3着内率{rc.pts(c['kake']['res'])}",
                f"崖っぷちに強い{n} 予選最終日の{c['kake']['n']}走"]
    if cat == "big":
        return [f"大一番で崩れない{n} 準優・優勝戦でも3着内率をキープ", f"{n}、ここ一番の{c['big']['n']}走"]
    if cat == "exlate":
        return [f"展示で判断は禁物 {n}は本番で化ける", f"{n}、展示タイム下位でも3着内率はほぼ普段どおり"]
    if cat == "growth":
        gr = c["growth"]
        word = "急成長" if t["t"] == "急成長中" else "上り調子"
        return [f"{word}の{n} 勝率{gr['prev']:.2f}→{gr['pts90']:.2f}", f"今いちばん勢いがある{n}? 直近90日の勝率{gr['pts90']:.2f}"]
    if cat == "stable":
        return [f"とにかく舟券に絡む{n} 3着内率{c['top3']:.0%}", f"{n}の安定感はコース平均{rc.pts(c['res3'])}"]
    if cat == "venue":
        v = next((x for x in c["venues"] if x.get("jcd") == t.get("jcd")), c["venues"][0])
        return [f"{v['name']}は庭? {n}、{v['name']}で3着内率{rc.pts(v['res'])}", f"{n}と{v['name']}の好相性"]
    return [f"{n}の{t['t']}"]


# 予想のヒント: 買い目ではなく「この材料をどう使うと予想が楽しくなるか」。断定や的中をうたう言い方はしない
HINT = {
    "start": "スタート勝負になりそうな並びなら主役候補。展示のSTも合わせて見ておきたい",
    "ex": "展示のSTがそのまま本番に出やすいタイプ。展示で速ければ、信じてみる価値あり",
    "ex2": "展示より本番で踏み込むタイプ。展示のSTが遅めでも、慌てなくていいかも",
    "nige": "1号艇のときは素直に信頼するか、あえて崩れる筋を探すか。考えどころ",
    "sashi": "2コースに入ったら差しの筋を一考。内の艇が流れる展開を想像してみて",
    "makuri": "3〜4コースに入ったら一撃に注意。内の艇のスタートと合わせて考えたい",
    "mz": "3コースより外ならまくり差しの筋。1マークで内の艇の間が空くかがカギ",
    "out": "外枠でも3着内に残すことが多い。ヒモに入れるかどうか、悩みどころ",
    "front": "進入が動きやすい。展示の進入を見てから組み立てると楽しい",
    "rough": "風や波がある日に出番。当日の水面の情報をチェック",
    "kake": "予選の最終日にボーダー付近なら注目",
    "big": "準優・優勝戦でも崩れにくい。大会の後半が本番かも",
    "exlate": "展示タイムが平凡でも、評価を下げすぎないのが吉",
    "growth": "いま勢いがある。直近の着順もあわせてチェック",
    "stable": "とにかく舟券に絡む。3着までに入れるかどうかの判断材料に",
    "venue": "この水面との相性は数字に出ている。当地での走りに注目",
}


def hint(t: dict) -> str:
    return HINT.get(t["cat"], "")


def comment(c: dict, picked: dict, venue: dict | None) -> str:
    """ひと言コメント: 一番の特徴の根拠 + 2つ目の特徴(なければコース別の数字)。数字はカードのまま。"""
    parts = [picked["why"] + "。"]
    rest = [t for t in c["tags"] if t["t"] != picked["t"] and not (venue and t["cat"] == "venue" and t.get("jcd") != venue.get("jcd"))]
    if rest:
        parts.append(f"「{rest[0]['t']}」の顔もあり、{rest[0]['why']}。")
    else:
        c1 = c["courses"][0]
        if c1["n"]:
            parts.append(f"1コースでは{c1['n']}走で3着内率{c1['top3']:.0%}。")
    if venue and picked["cat"] != "venue" and venue.get("n", 0) >= 10 and venue["res"] is not None and venue["res"] >= 0.05:
        parts.append(f"今回の{venue['name']}では{venue['n']}走で3着内率が普段より{rc.pts(venue['res'])}。")
    return "".join(parts)


# ---------------------------------------------------------------- 選定
def pick(cards: list[dict], n: int, venue_fit: dict, jcd: int | None = None) -> list[tuple[dict, dict]]:
    """タグの珍しさ(付いている選手の少なさ)と強さで点を付け、同じ型が続かないように選ぶ。
    大会の場が決まっているときは、ほかの場の「巧者」タグは見出しに使わない(今回のレースと関係が薄い)。"""
    cand = []
    for c in cards:
        for t in c["tags"]:
            if jcd and t["cat"] == "venue" and t.get("jcd") != jcd:
                continue
            score = (1 - t.get("share", 0.1)) * 100 + t["score"] / 5
            if t["cat"] == "venue" and venue_fit.get(c["id"]):
                score += 10
            cand.append((score, c, t))
    v_tag = []
    for c in cards:  # 今回の場で相性が良い選手は、タグがなくても候補に
        v = venue_fit.get(c["id"])
        if v and v["n"] >= 10 and v["res"] is not None and v["res"] >= 0.08:
            t = {"t": f"{v['name']}と好相性", "cat": "venue", "jcd": v["jcd"], "score": 60 + 300 * v["res"],
                 "why": f"{v['name']}の{v['n']}走で、3着内率が普段より{rc.pts(v['res'])}", "share": 0.05}
            c = {**c, "venues": [v] + [x for x in c["venues"] if x["jcd"] != v["jcd"]]}
            v_tag.append(((1 - 0.05) * 100 + t["score"] / 5 + 5, c, t))
    cand += v_tag
    cand.sort(key=lambda x: -x[0])
    out, used_racer, used_cat = [], set(), {}
    while cand and len(out) < n:
        best = max(cand, key=lambda x: x[0] - 15 * used_cat.get(x[2]["cat"], 0))
        cand = [x for x in cand if x[1]["id"] != best[1]["id"]]
        out.append((best[1], best[2]))
        used_racer.add(best[1]["id"])
        used_cat[best[2]["cat"]] = used_cat.get(best[2]["cat"], 0) + 1
    return out


def venue_fit(d, ids: list[int], jcd: int | None) -> dict:
    """今回の場での、選手ごとの3着内の上積み(本人の普段との差、回数が少ないほど普段に寄せる)。"""
    if not jcd:
        return {}
    s = d[d["racer_id"].isin(ids) & d["finish"].between(1, 6)].copy()
    top3 = (s["finish"] <= 3).astype(float)
    pop = d[d["finish"].between(1, 6)].assign(t3=lambda x: (x["finish"] <= 3).astype(float)).groupby("course")["t3"].mean()
    s["res3"] = top3 - s["course"].map(pop)
    out = {}
    for rid, g in s.groupby("racer_id"):
        own = g["res3"].mean()
        v = g[g["jcd"] == jcd]
        if len(v):
            res = (v["res3"].sum() + rc.SHRINK * own) / (len(v) + rc.SHRINK) - own
            out[int(rid)] = {"jcd": jcd, "name": rc.VENUES.get(jcd, ""), "n": int(len(v)), "res": round(float(res), 3)}
    return out


# ---------------------------------------------------------------- 描画
def lane_tile(i: int) -> str:
    return f'<span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'


def course_line(bc: dict | None, c: dict) -> str:
    """選手ごとの「狙い目のコース」(同じ級別の平均より3着内率が一番上回るコース)。"""
    if not bc:
        return ""
    g = rc.GROUP_NAME.get(c["grp"], "")
    return (f"{bc['c']}コースに入ったら注目:{bc['n']}走で1着率{bc['win']:.0%}・3着内率{bc['top3']:.0%}"
            f"({g}の{bc['c']}コース平均は1着率{bc['avg_win']:.0%}・3着内率{bc['avg_top3']:.0%})")


def card_block(c: dict, t: dict, heads: list[str], com: str, idx: int, bc: dict | None = None) -> str:
    k = c["kim"]
    pc = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
    crs = "".join(f"<tr><th>{x['c']}</th><td>{x['n']}</td><td>{pc(x['win'])}</td><td>{pc(x['top3'])}</td></tr>" for x in c["courses"])
    tags = "".join(f"<li><b>{e(x['t'])}</b><span>{e(x['why'])}</span></li>" for x in c["tags"][:5])
    alt = "".join(f"<li>{e(h)}</li>" for h in heads[1:])
    g = rc.GROUP_NAME.get(c["grp"], "")
    return f"""<article class="pick" id="r{c['id']}">
  <div class="pick-head"><span class="no">注目{idx}</span><span class="who">{e(c['name'])}<small>{e(c['class'] or '')}・{e(c['branch'] or '')}・{int(c['age'] or 0)}歳</small></span></div>
  <h2>{e(heads[0])}</h2>
  {f'<ul class="alt"><li class="lbl">見出しの別案</li>{alt}</ul>' if alt else ''}
  <div class="pick-body">
    <div class="pick-text"><p class="com">{e(com)}</p>
      {f'<p class="hint"><b>予想のヒント</b>{e(hint(t))}</p>' if hint(t) else ''}
      {f'<p class="hint"><b>狙い目のコース</b>{e(course_line(bc, c))}</p>' if bc else ''}
      <ul class="tags">{tags}</ul></div>
    <figure class="pick-card">{radar_svg(c['radar'])}
      <figcaption>{e(g)}の中での位置(100がトップ)</figcaption>
      <table class="mini"><tr><th>コース</th><th>走</th><th>1着</th><th>3着内</th></tr>{crs}</table>
      <p class="kim">逃げ {k['nige']['w']}/{k['nige']['n']}・差し {k['sashi']['w']}・まくり {k['makuri']['w']}・まくり差し {k['mz']['w']}</p>
    </figure>
  </div>
</article>"""


CSS = """
/* 予想紙の紙と朱の印。見出しは太いゴシック、数字はレース場の掲示板の細身の書体 */
:root{
  --paper:#eef1e4; --paper2:#e2e7d3; --ink:#14212c; --mute:#56636e; --rule:#c7cfb8; --stamp:#c8141c; --card:#f8faf2;
  --head:"Dela Gothic One","BIZ UDPGothic",system-ui,sans-serif; --body:"BIZ UDPGothic",system-ui,sans-serif;
  --num:"Barlow Condensed","BIZ UDPGothic",sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#141b1f; --paper2:#1c252a; --ink:#e8ede4; --mute:#9aa7a0; --rule:#2f3b40; --stamp:#ff5a5f; --card:#182126; color-scheme:dark}}
:root[data-theme="dark"]{--paper:#141b1f; --paper2:#1c252a; --ink:#e8ede4; --mute:#9aa7a0; --rule:#2f3b40; --stamp:#ff5a5f; --card:#182126; color-scheme:dark}
body{background:var(--paper);color:var(--ink);font:15px/1.7 var(--body);padding-inline:16px;padding-block:20px 48px}
.wrap{max-width:860px;margin:0 auto;display:grid;gap:22px}
.mast{display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;align-items:center;border-bottom:3px solid var(--ink);padding-bottom:12px}
.seal{width:64px;height:64px;transform:rotate(-6deg)}
.seal svg{display:block;width:64px;height:64px}
.mast h1{margin:0;font:400 clamp(24px,5vw,38px)/1.15 var(--head);text-wrap:balance}
.mast p{margin:4px 0 0;color:var(--mute);font-size:13px}
.lead{background:var(--paper2);border-radius:6px;padding:12px 14px;font-size:14px}
.lead b{color:var(--stamp)}
.pick{background:var(--card);border-radius:8px;padding:16px 16px 18px;display:grid;gap:10px;border-top:6px solid var(--ink)}
.pick-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.no{font:400 13px/1 var(--head);color:#fff;background:var(--stamp);padding:5px 8px;border-radius:3px}
.who{font-weight:700;font-size:18px}
.who small{font-weight:400;color:var(--mute);font-size:12px;margin-left:8px}
.pick h2{margin:0;font:400 clamp(20px,4.2vw,28px)/1.3 var(--head);text-wrap:balance}
.alt{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12.5px;color:var(--mute)}
.alt .lbl{font-weight:700}
.alt li:not(.lbl)::before{content:"・"}
.pick-body{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:640px){.pick-body{grid-template-columns:1fr}}
.com{margin:0;font-size:15px}
.hint{margin:10px 0 0;font-size:14px;background:var(--paper2);border-radius:6px;padding:8px 10px}
.hint b{display:inline-block;color:var(--stamp);margin-right:8px;font-size:12.5px}
.tags{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:6px}
.tags li{display:grid;gap:1px;padding-left:10px;border-left:3px solid var(--stamp)}
.tags b{font-size:14px}
.tags span{font-size:12.5px;color:var(--mute)}
.pick-card{margin:0;display:grid;gap:6px;justify-items:center}
.radar{width:100%;max-width:360px;height:auto}
.radar .rg{fill:none;stroke:var(--rule);stroke-width:1}
.radar .rd{fill:var(--stamp);fill-opacity:.18;stroke:var(--stamp);stroke-width:2;stroke-linejoin:round}
.radar text{font-size:11px;fill:var(--mute)}
.radar .rv{font-family:var(--num);font-weight:700;fill:var(--ink);font-size:12.5px}
figcaption{font-size:11.5px;color:var(--mute)}
.mini{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;width:100%;max-width:260px}
.mini th,.mini td{padding:3px 6px;border-bottom:1px solid var(--rule);text-align:right}
.mini th:first-child{text-align:center}
.kim{margin:0;font-size:12px;color:var(--mute);text-align:center}
.corner{background:var(--card);border-radius:8px;padding:14px 16px}
.corner h3{margin:0 0 8px;font:400 19px/1.3 var(--head)}
.corner ul{margin:0;padding-left:1.1em;display:grid;gap:4px}
.corner p{margin:0;color:var(--mute);font-size:13px}
.corners{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:14px}
.lt{display:inline-grid;place-items:center;width:20px;height:22px;border-radius:3px;font:700 14px var(--num);box-shadow:inset 0 0 0 1px rgba(0,0,0,.25)}
.basis{font-size:12.5px;color:var(--mute)}
.basis h3{font:400 16px var(--head);color:var(--ink);margin:0 0 6px}
.basis dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;margin:0}
.basis dt{font-weight:700;color:var(--ink)}
.basis dd{margin:0}
.foot{font-size:12px;color:var(--mute);border-top:1px solid var(--rule);padding-top:10px}
.nerai{background:var(--card);border-radius:8px;padding:14px 16px;border-top:6px solid var(--stamp);display:grid;gap:10px}
.nerai h3{margin:0;font:400 21px/1.3 var(--head)}
.nerai > p{margin:0;font-size:13px;color:var(--mute)}
.waku{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
.waku th,.waku td{padding:6px 6px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
.waku th{white-space:nowrap;font-weight:700}
.waku th small{display:block;font-weight:400;color:var(--mute);font-size:11.5px}
.waku td span{display:inline-block;margin-right:12px;white-space:nowrap}
.waku td em{font-style:normal;font:700 15px var(--num)}
.waku td small{color:var(--mute);font-size:11.5px}
.trend ul{margin:0;padding-left:1.1em;display:grid;gap:4px;font-size:14px}
.dist{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;align-items:end;max-width:420px;height:120px;margin-top:4px}
.dist div{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:3px;height:100%}
.dist i{display:block;width:70%;background:var(--ink);border-radius:3px 3px 0 0}
.dist b{font:700 13px var(--num)}
"""


WAKU_NOTE = "進入したコースごとの成績(過去3年、その出場選手の中で上位3人)。1〜4コースは1着率、5・6コースは3着内率。"\
            f"{nerai.MIN_N}走以上の選手から、回数が少ない選手は同じ級別の平均に寄せて順位を付けています"


def waku_rows(wt: dict) -> list[tuple[int, str, list[str]]]:
    rows = []
    for crs in range(1, 7):
        m = nerai.METRIC[crs]
        label = "逃げ切り(1着率)" if crs == 1 else nerai.METRIC_NAME[m] + ("(頭まで)" if m == "win" else "(3着の候補)")
        rows.append((crs, label, [f"{r['name']} {r['rate']:.0%}({r['k']}/{r['n']})" for r in wt.get(crs, [])]))
    return rows


def nerai_html(wt: dict, trend: dict | None, venue: str | None) -> str:
    rows = "".join(
        f"<tr><th>{lane_tile(crs - 1)} コース<small>{e(label)}</small></th><td>"
        + "".join(f"<span>{e(r['name'])} <em>{r['rate']:.0%}</em><small>({r['k']}/{r['n']})</small></span>" for r in wt.get(crs, []))
        + "</td></tr>" for crs, label, _ in waku_rows(wt))
    out = f"""<section class="nerai"><h3>狙い目の早見表(コースが決まったらチェック)</h3>
<p>出走表と展示の進入が出たら、得意なコースに入った選手を探してみてください。{e(WAKU_NOTE)}</p>
<table class="waku">{rows}</table></section>"""
    if trend and venue:
        tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
        lbl = "トップ級のレース" if tp is trend["top"] else "全レース"
        bars = "".join(f'<div><b>{tp["dist"][k]:.0%}</b><i style="height:{round(tp["dist"][k] * 130)}px"></i>{lane_tile(k - 1)}</div>'
                       for k in range(1, 7))
        out += f"""<section class="nerai trend"><h3>{e(venue)}の傾向</h3>
<ul>{''.join(f'<li>{e(x)}</li>' for x in nerai.trend_lines(trend, venue))}</ul>
<p>1着になったコースの割合({e(lbl)}、{tp['n']}レース)</p><div class="dist">{bars}</div></section>"""
    return out


def render(title: str, venue_name: str | None, picks, all_cards, corners: list[tuple[str, str]], meta: dict, note: str,
           nerai_block: str = "") -> str:
    blocks = "\n".join(card_block(c, t, heads, com, i + 1, bc) for i, (c, t, heads, com, bc) in enumerate(picks))
    cor = "".join(f'<section class="corner"><h3>{e(h)}</h3>{body}</section>' for h, body in corners)
    def rule_key(name):
        if name.endswith("好相性"):
            return "(今回の場)と好相性"
        if name.endswith("巧者"):
            return "(場名)巧者"
        return "上り調子" if name == "急成長中" else name
    shown = [x["t"] for c, *_ in picks for x in c["tags"][:5]] + [t["t"] for _, t, *_ in picks]
    rules = meta["rules"]
    keys = list(dict.fromkeys(rule_key(x) for x in shown))
    basis = "".join(f"<dt>{e(k)}</dt><dd>{e(rules[k])}</dd>" for k in keys if k in rules)
    today = dt.date.today().isoformat()
    return f"""<title>{e(title)} 出場選手をデータで読む</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=BIZ+UDPGothic:wght@400;700&family=Barlow+Condensed:wght@600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header class="mast"><div class="seal">{gull_svg(64, bg="#f8faf2")}</div><div><h1>{e(title)} 出場選手をデータで読む</h1>
<p>{e(venue_name + '開催 ・ ' if venue_name else '')}注目選手 {len(picks)}人 ・ 集計 {e(meta['period'][0])}〜{e(meta['asof'])} ・ 下書き {today}</p></div></header>
<p class="lead">{note}公式の予想紙・スポーツ紙とは別の切り口で、選手の「型」と「相性」をデータで読む下書きです。数字はすべて公式の成績データを自分たちで集計したもので、<b>見出しはどれも下の基準を満たした数字に基づいています</b>。</p>
{blocks}
{nerai_block}
<div class="corners">{cor}</div>
<section class="corner basis"><h3>タグの基準</h3><dl>{basis}</dl>
<p style="margin-top:8px">「上位X%」は同じ級別(A1・A2・B級)の中での位置。3着内率の「上積み」は、コースごとの全体の3着内率を差し引いた値。回数が少ない数字は全体や本人の普段の値に寄せて計算しています。</p></section>
<p class="foot">この下書きは選手の傾向を楽しむための読み物で、舟券の的中や利益を約束するものではありません。公式の成績データ(番組表・競走成績)を自分たちで集計した数字とグラフだけを使っています。舟券の購入は20歳になってから。</p>
</div>"""


def note_text(title, venue_name, picks, sel, corners_txt, free_corner: list[str] | None = None,
              waku: list[str] | None = None, trend: list[str] | None = None) -> str:
    """note に貼る本文の下書き。考え方(発信方針): 答え(買い目)ではなく、読んだ人が自分で予想するのが楽しくなる「材料」を届ける。
    無料部分で1人分を丸ごとと場の傾向を見せて中身の質を伝え、有料部分の中身は見出しで見せる。"""
    n_all, n_pick = len(sel), len(picks)
    fi = next((i for i, (_, t, *_r) in enumerate(picks) if t["cat"] == "venue"), 0)
    picks = [picks[fi]] + [x for k, x in enumerate(picks) if k != fi]  # 無料で見せる1人を注目1に
    trust = free_corner or []

    def pick_lines(i, x):
        c, t, heads, com, bc = x
        out = [f"■注目{i}{'(無料で公開)' if i == 1 else ''} {c['name']}({c['class']}・{c['branch']})",
               f"〔画像:{c['id']}_{c['name']}.png〕", f"【{heads[0]}】", com]
        if hint(t):
            out.append(f"予想のヒント:{hint(t)}")
        if bc:
            out.append(f"狙い目のコース:{course_line(bc, c)}")
        return out + [""]

    out = ["【タイトル案】",
           f"1. 【データで読む】{title}|出場{n_all}人の“型”と狙い目のコース 予想が楽しくなる材料集",
           f"2. {title}の出場{n_all}人、データで分かる“型”と狙い目のコース",
           f"3. 【保存版】{title} 全{n_all}人のひと言タグとコース別の早見表",
           "", "――――――――――(ここから無料)――――――――――", "",
           f"{title}{'(' + venue_name + ')' if venue_name else ''}の出場予定{n_all}人を、過去3年・約17万レースの成績から読みました。",
           "このノートは買い目を売るものではありません。あなたが自分で予想するときに「へえ、この人はこういう型なのか」と使える材料を集めたものです。",
           "(もともとは、友達と現地で観戦するときに「この選手ってどんな型?」と話したくて集め始めたデータです)",
           "", "■この記事でわかること",
           f"・データで目立つ注目{n_pick}人と、それぞれの“型”",
           "・狙い目の早見表:コースが決まったら、誰がそのコースで強いかがすぐわかる",
           "・展示STを信じていい選手" + (f"、{venue_name}の傾向" if trend else ""),
           f"・{venue_name + 'と' if venue_name else ''}相性のいい選手、勝負駆けや荒れ水面に強い選手、よく当たるライバル",
           f"・保存版:出場{n_all}人全員のひと言タグ一覧(現地観戦のおともに)", ""]
    out += pick_lines(1, picks[0])
    if trend:
        out += [f"■{venue_name}の傾向"] + [f"・{x}" for x in trend] + [""]
    if trust:
        out += trust + [""]
    out += ["■有料パートの中身"]
    out += [f"・注目{i} {pc['name']}({pt['t']})" for i, (pc, pt, *_r) in enumerate(picks, 1) if i > 1]
    if waku:
        out.append("・狙い目の早見表(コースが決まったらチェック)")
    out += [f"・{x[1:]}" for x in corners_txt if x.startswith("■") and not x.startswith("■展示ST")]
    out += [f"・保存版:出場{n_all}人のひと言タグ一覧", "",
            "数字はすべて、公式の成績データを自分たちで集計したものです。根拠の数字と判定の基準も全部載せています。", "",
            "――――――――――(ここから有料:note の有料エリアの線をここに)――――――――――", ""]
    for i, x in enumerate(picks, 1):
        if i > 1:
            out += pick_lines(i, x)
    if waku:
        out += ["■狙い目の早見表(コースが決まったらチェック)",
                "出走表と展示の進入が出たら、得意なコースに入った選手を探してみてください。"] + waku + [f"※{WAKU_NOTE}", ""]
    out += [x for x in corners_txt if not x.startswith("■展示ST") and x not in trust] + [""]
    out += [f"■保存版:出場{n_all}人のひと言タグ一覧"]
    for c in sel:
        tags = [t["t"] for t in c["tags"][:2]]
        out.append(f"・{c['name']}({c['class']}・{c['branch']}){' / '.join(tags) if tags else '(目立つタグなし)'}")
    out += ["", "■この記事のデータについて",
            "・公式の成績データ(番組表・競走成績、2023年10月〜)を自分たちで集計しています。出走表・オッズの表・写真は使っていません",
            "・「上位◯%」は同じ級別(A1・A2・B級)の中での位置です。3着内率はコースの有利不利を差し引いた値で比べています",
            "・コースは枠番ではなく、実際に進入したコースで集計しています",
            "・タグは決まった基準を満たした選手だけに付けています(基準は画像の下と下書きのHTMLに全文)",
            "・この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません",
            "・舟券の購入は20歳になってから。無理のない範囲で楽しみましょう", "",
            "■次回予告",
            "次のSG・G1の出場選手が発表されたら、また“材料”をまとめます。フォローしておくと見逃しません。"]
    return "\n".join(out)


def x_text(title, venue_name, picks, sel, trust_names: list[str], venue_names: list[str], trend_head: str | None = None) -> str:
    """X の投稿案(3つのスレッド)。1投稿は全角140字以内に収める(超えるときは名前の数を減らす)。"""
    n_all = len(sel)
    import re as _re
    short = _re.sub(r"第[0-9０-９]+回", "", title)
    short = _re.sub(r"[(（].*?[)）]", "", short)
    short = _re.sub(r"^\s*(SG|PG1|G1|GⅠ|G2|GⅡ|G3|GⅢ)\s*", "", short).strip()
    tag = "#" + "".join(ch for ch in short if ch not in " 　・") if short else ""

    def fit(make, names):
        for k in range(min(3, len(names)), -1, -1):
            p = make(names[:k])
            if len(p) <= 140:
                return p
        return make([])
    p1 = fit(lambda ns: f"{title}、出場予定{n_all}人をデータで読みました📰\n\n買い目ではなく、予想が楽しくなる“材料”をまとめています。"
                        + ("\n\nまずは「展示STを信じていい選手」👇\n" + "\n".join(f"・{x}" for x in ns) if ns else ""), trust_names)
    if trust_names and len(p1 + "\n\nみんなは展示ST、どこまで信じる派?") <= 140:
        p1 += "\n\nみんなは展示ST、どこまで信じる派?"
    if trend_head:
        q = f"\n\nみんなは{venue_name}の1号艇、どこまで信じる?"
        p2 = fit(lambda ns: trend_head + ("\n\n" + f"{venue_name}と相性がいい選手👇\n" + "\n".join(f"・{x}" for x in ns) if ns else "") + q,
                 venue_names)
    elif venue_names:
        p2 = fit(lambda ns: f"{venue_name}と相性がいい選手(3着内率が普段より上)\n" + "\n".join(f"・{x}" for x in ns), venue_names)
    else:
        p2 = f"注目選手のカードを1枚だけ先に公開。{picks[0][0]['name']}は「{picks[0][1]['t']}」"
    p3 = (f"注目{len(picks)}人の“型”、コースが決まったら使える狙い目の早見表、全{n_all}人のひと言タグ一覧はnoteにまとめました"
          f"(現地観戦のおともに)\n\n(noteのURL)\n\n#競艇 #ボートレース {tag}")
    out = []
    for i, p in enumerate((p1, p2, p3), 1):
        warn = "  ※140字を超えています" if len(p) > 140 else ""
        out += [f"--- 投稿{i}({len(p)}字){warn} ---", p, ""]
    out.append("画像: 投稿1に注目1人目のカード、投稿2に今回の場と相性のいい選手のカードを添える")
    out.append("出し方: noteのリンクは最後の投稿だけ(本文にリンクがあると届きにくい)。平日の12時台か20〜23時、初日の前日の夜がおすすめ。"
               "返信が来たら返す(返信のやりとりがいちばん評価される)")
    return "\n".join(out)


def make(title: str, keys: list[str], jcd: int | None, n: int = 8, note: str = "", d=None, cards=None, meta=None) -> dict:
    """下書き一式(HTML・note の本文・X の投稿案)と、画像にする注目選手を返す。d・cards・meta を渡せば集計を使い回す。"""
    if d is None:
        d = rc.load_table()
    if cards is None:
        cards, meta = rc.build(d)
    meta = {**meta, "rules": {r["tag"]: r["rule"] for r in meta["rules"]} if isinstance(meta["rules"], list) else dict(meta["rules"])}
    meta["rules"]["(今回の場)と好相性"] = "今回の場での3着内の上積みが、本人の普段より+8ポイント以上(その場で10走以上。回数が少ないほど普段の値に寄せて計算)"
    sel, missing = [], []
    for k in keys:
        c = rc.find(cards, k)
        if c and c["id"] not in {x["id"] for x in sel}:
            sel.append(c)
        elif not c:
            missing.append(k)
    vf = venue_fit(d, [c["id"] for c in sel], jcd)
    base = nerai.course_base(d)
    chosen = pick(sel, min(n, len(sel)), vf, jcd)
    picks = [(c, t, headlines(c, t), comment(c, t, vf.get(c["id"])), nerai.best_course(c, base)) for c, t in chosen]
    wt = nerai.waku_table(sel, base)
    vname = rc.VENUES.get(jcd) if jcd else None
    trend = nerai.venue_trend(d, jcd) if jcd else None
    # コーナー
    corners, txt = [], []
    trust = sorted([c for c in sel if c["ex"]["n"] >= 30 and (c["ex"]["grp"] or 0) >= 85], key=lambda c: c["ex"]["mae"])[:5]
    adjust = sorted([c for c in sel if c["ex"]["n"] >= 30 and (c["ex"]["grp"] or 100) <= 25], key=lambda c: -c["ex"]["mae"])[:3]
    if trust or adjust:
        body = ""
        if trust:
            body += "<p>展示STを信じていい</p><ul>" + "".join(f"<li>{e(c['name'])}(ずれ平均{c['ex']['mae']:.3f}秒、{c['ex']['n']}走)</li>" for c in trust) + "</ul>"
        if adjust:
            body += "<p style='margin-top:6px'>展示STは参考程度(本番で合わせてくるタイプ)</p><ul>" + "".join(
                f"<li>{e(c['name'])}(ずれ平均{c['ex']['mae']:.3f}秒、{c['ex']['n']}走)</li>" for c in adjust) + "</ul>"
        corners.append(("展示STを信じていい選手", body))
        txt += ["■展示STを信じていい選手"] + [f"・{c['name']}(ずれ平均{c['ex']['mae']:.3f}秒)" for c in trust] + \
               (["(展示STは参考程度)"] + [f"・{c['name']}(ずれ平均{c['ex']['mae']:.3f}秒)" for c in adjust] if adjust else [])
    vv = []
    if jcd:
        # 相性が良い選手だけ載せる(普段より下がる選手の名前は出さない)
        vv = sorted([(vf[c["id"]], c) for c in sel if c["id"] in vf and vf[c["id"]]["n"] >= 10 and vf[c["id"]]["res"] >= 0.03],
                    key=lambda x: -x[0]["res"])
        if vv:
            corners.append((f"{vname}との相性", "<ul>" + "".join(
                f"<li>{e(c['name'])} {rc.pts(v['res'])}({v['n']}走)</li>" for v, c in vv[:5]) + "</ul><p>3着内率の普段との差</p>"))
            txt += [f"■{vname}との相性"] + [f"・{c['name']} {rc.pts(v['res'])}({v['n']}走)" for v, c in vv[:5]]
    for key, label, n_min in (("kake", "勝負駆けに強い", 15), ("rough", "荒れ水面に強い", 20)):
        xs = sorted([c for c in sel if c[key]["n"] >= n_min and (c[key]["res"] or 0) >= 0.03], key=lambda c: -c[key]["res"])
        if xs:
            corners.append((label, "<ul>" + "".join(f"<li>{e(c['name'])} {rc.pts(c[key]['res'])}({c[key]['n']}走)</li>" for c in xs[:5])
                            + "</ul><p>3着内率の普段との差</p>"))
            txt += [f"■{label}"] + [f"・{c['name']} {rc.pts(c[key]['res'])}({c[key]['n']}走)" for c in xs[:5]]
    gr = sorted([c for c in sel if c["growth"]["n90"] >= 15 and (c["growth"]["diff"] or 0) >= 0.3], key=lambda c: -c["growth"]["diff"])
    if gr:
        corners.append(("いま勢いがある", "<ul>" + "".join(
            f"<li>{e(c['name'])} 勝率{c['growth']['prev']:.2f}→{c['growth']['pts90']:.2f}</li>" for c in gr[:5]) + "</ul><p>前の1年 → 直近90日</p>"))
        txt += ["■いま勢いがある"] + [f"・{c['name']} 勝率{c['growth']['prev']:.2f}→{c['growth']['pts90']:.2f}" for c in gr[:5]]
    # 選手同士の相性: 対戦の多い組(よく当たるライバル)を、両方の先着数で並べる(負けた側だけを強調しない)
    h2h = rc.head_to_head(d, [c["id"] for c in sel], min_meet=10)
    name = {c["id"]: c["name"] for c in sel}
    if h2h:
        rows = sorted(h2h, key=lambda x: -x["n"])[:5]

        def line(x):
            a_, b_ = (x["a"], x["b"]) if x["a_ahead"] >= x["b_ahead"] else (x["b"], x["a"])
            wa, wb = max(x["a_ahead"], x["b_ahead"]), min(x["a_ahead"], x["b_ahead"])
            return f"{name[a_]}と{name[b_]}は{x['n']}回の対戦で{wa}対{wb}({name[a_]}の先着が多い)" if wa != wb else \
                f"{name[a_]}と{name[b_]}は{x['n']}回の対戦で{wa}対{wb}の五分"
        corners.append(("よく当たるライバル", "<ul>" + "".join(f"<li>{e(line(x))}</li>" for x in rows)
                        + "</ul><p>同じレースで両方に着順がついた対戦の、先着した回数</p>"))
        txt += ["■よく当たるライバル"] + [f"・{line(x)}" for x in rows]
    page = render(title, vname, picks, sel, corners, meta, note, nerai_html(wt, trend, vname))
    trust_lines = ["■展示STを信じていい選手(展示と本番のSTのずれが小さい)"] + \
        [f"・{c['name']}(ずれ平均{c['ex']['mae']:.3f}秒、{c['ex']['n']}走)" for c in trust] if trust else []
    waku = [f"{crs}コース {label}:" + "、".join(xs) for crs, label, xs in waku_rows(wt) if xs]
    tl = nerai.trend_lines(trend, vname) if trend else None
    th = nerai.trend_headline(trend, vname) if trend else None
    return {"html": page, "note": note_text(title, vname, picks, sel, txt, trust_lines, waku, tl),
            "x": x_text(title, vname, picks, sel, [c["name"] for c in trust], [c["name"] for v, c in vv[:3]], th),
            "picks": picks, "sel": sel, "missing": missing, "jcd": jcd, "venue": vname}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--venue", default=None, help="場名か場コード")
    ap.add_argument("--racers", default="", help="カンマ区切り(登番か名前)")
    ap.add_argument("--file", default=None, help="1行に1人(登番か名前)")
    ap.add_argument("--assen", default=None, help="出場選手一覧 data/assen/assen_YYYYMM.json:場コード:初日(scripts/fetch_assen.py)")
    ap.add_argument("--n", type=int, default=6, help="注目選手の数")
    ap.add_argument("--note", default="", help="冒頭に添える一文(試作であることなど)")
    ap.add_argument("--out", default=str(ROOT / "out/ura.html"))
    a = ap.parse_args()
    keys = [x for x in a.racers.split(",") if x.strip()]
    if a.file:
        keys += [x.strip() for x in pathlib.Path(a.file).read_text(encoding="utf-8").splitlines() if x.strip()]
    jcd = None
    if a.assen:
        import json as _json
        path, j, hd = a.assen.rsplit(":", 2)
        ser = next((x for x in _json.loads(pathlib.Path(path).read_text(encoding="utf-8")) if x["jcd"] == int(j) and x["hd"] == hd), None)
        if not ser:
            raise SystemExit(f"見つかりません: {a.assen}")
        keys += [str(r["id"]) for r in ser.get("racers", [])]
        jcd = int(j)
    if a.venue:
        jcd = int(a.venue) if str(a.venue).isdigit() else next((k for k, v in rc.VENUES.items() if v == a.venue), None)
    r = make(a.title, keys, jcd, a.n, a.note)
    for k in r["missing"]:
        print("見つからない", k)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r["html"], encoding="utf-8")
    out.with_suffix(".txt").write_text(r["note"], encoding="utf-8")
    out.with_name(out.stem + "_x.txt").write_text(r["x"], encoding="utf-8")
    print("wrote", out, out.with_suffix(".txt"), out.with_name(out.stem + "_x.txt"), f"({len(r['sel'])}人、注目{len(r['picks'])}人)")


if __name__ == "__main__":
    main()
