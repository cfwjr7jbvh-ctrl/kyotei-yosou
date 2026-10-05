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
from kyotei import mag, nerai  # noqa: E402
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
    return "".join(parts)


# ---------------------------------------------------------------- 選定
def pick(cards: list[dict], n: int, venue_fit: dict, jcd: int | None = None) -> list[tuple[dict, dict]]:
    """タグの珍しさ(付いている選手の少なさ)と強さで点を付け、同じ型が続かないように選ぶ。
    場との相性・勝負駆け・大一番・荒れ水面は「型」として本物と言えない(trait_reliability.py)ので使わない。"""
    cand = []
    for c in cards:
        for t in c["tags"]:
            if jcd and t["cat"] == "venue" and t.get("jcd") != jcd:
                continue
            score = (1 - t.get("share", 0.1)) * 100 + t["score"] / 5
            cand.append((score, c, t))
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
    return (f"{bc['c']}コースが得意な型:{bc['n']}走で1着率{bc['win']:.0%}・3着内率{bc['top3']:.0%}"
            f"({g}の{bc['c']}コース平均は1着率{bc['avg_win']:.0%}・3着内率{bc['avg_top3']:.0%}。本人のほかのコースと比べても上)")


def stars(t: dict) -> str:
    """タグの強さ(同じ級別の中での位置)を★で。★★★=上位1%、★★=上位5%、★=上位10%。位置で決まらないタグは空。"""
    sc = t.get("score")
    if t.get("cat") in ("front", "growth", "exlate", "ex2") or sc is None:
        return ""
    return "★★★" if sc >= 99 else "★★" if sc >= 95 else "★" if sc >= 90 else ""


def big_stat(c: dict, t: dict) -> tuple[str, str]:
    """注目選手の一番大きく出す数字(タグの根拠と同じもの)。"""
    k, cat = c["kim"], t["cat"]
    if cat == "start":
        return rc.st_fmt(c["st"]["avg"]), "平均ST"
    if cat == "ex":
        return f"{c['ex']['mae']:.3f}", "展示と本番のSTのずれ(秒)"
    if cat == "ex2":
        return f"{c['ex']['delta']:+.2f}", "展示→本番のST(秒)"
    if cat == "nige":
        return f"{k['nige']['w'] / max(1, k['nige']['n']):.0%}", f"逃げ率(1コース{k['nige']['n']}走)"
    if cat in ("sashi", "makuri", "mz"):
        name = {"sashi": "差し", "makuri": "まくり", "mz": "まくり差し"}[cat]
        return f"{k[cat]['w']}", f"{name}で勝った回数"
    if cat == "out":
        return f"{c['out']['res'] * 100:+.0f}", "4〜6コースの3着内率(コース平均との差、ポイント)"
    if cat == "front":
        return f"{c['front']['rate']:.0%}", "枠より内のコースに入った割合"
    if cat == "growth":
        return f"{c['growth']['pts90']:.2f}", f"直近90日の勝率(前の1年 {c['growth']['prev']:.2f})"
    if cat == "exlate":
        return f"{c['exlate']['res'] * 100:+.0f}", "展示タイム4位以下のときの3着内率(普段との差、ポイント)"
    return f"{c['top3']:.0%}", "3着内率"


def card_block(c: dict, t: dict, heads: list[str], com: str, idx: int, bc: dict | None = None) -> str:
    k = c["kim"]
    pc = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
    crs = "".join(f"<tr><th>{lane_tile(x['c'] - 1)}</th><td>{x['n']}</td><td>{pc(x['win'])}</td><td>{pc(x['top3'])}</td></tr>" for x in c["courses"])
    tags = "".join(f"<li><b>{e(x['t'])}<i>{stars(x)}</i></b><span>{e(x['why'])}</span></li>" for x in c["tags"][:5])
    alt = "".join(f"<li>{e(h)}</li>" for h in heads[1:])
    g = rc.GROUP_NAME.get(c["grp"], "")
    num, lbl = big_stat(c, t)
    return f"""<article class="pick" id="r{c['id']}">
  <header class="pk-h"><span class="no">注目<b>{idx}</b></span><span class="nm">{e(c['name'])}</span>
    <span class="meta">{e(c['class'] or '')}・{e(c['branch'] or '')}・{int(c['age'] or 0)}歳</span></header>
  <div class="pk-main">
    <div class="pk-body">
      <div class="pk-tag"><span class="vt">{e(t['t'])}</span><span class="st">{stars(t)}</span></div>
      <h2><span class="mk">{e(heads[0])}</span></h2>
      <div class="pk-num"><b>{e(num)}</b><small>{e(lbl)}</small></div>
      <p class="com">{e(com)}</p>
      {f'<div class="mikata">{gull_svg(46, bg="#ffffff", cls="mg")}<p><b>ミカタのひと言</b>{e(hint(t))}</p></div>' if hint(t) else ''}
      {f'<p class="crs-hint"><b>狙い目のコース</b>{e(course_line(bc, c))}</p>' if bc else ''}
    </div>
  </div>
  <div class="pk-data">
    <figure>{radar_svg(c['radar'])}<figcaption>{e(g)}の中での位置(100がトップ)</figcaption></figure>
    <div><table class="mini"><tr><th>コース</th><th>走</th><th>1着</th><th>3着内</th></tr>{crs}</table>
      <p class="kim">逃げ {k['nige']['w']}/{k['nige']['n']}・差し {k['sashi']['w']}・まくり {k['makuri']['w']}・まくり差し {k['mz']['w']}</p></div>
  </div>
  <ul class="tags">{tags}</ul>
  {f'<details class="alt"><summary>見出しの別案</summary><ul>{alt}</ul></details>' if alt else ''}
</article>"""


CSS = """
/* 競艇新聞: 新聞紙の地に黒・赤・黄。見出しは極太、数字は掲示板の細長い書体。艇番の6色をそのまま使う */
:root{
  --paper:#f4efdf; --paper2:#ebe4cc; --ink:#111111; --mute:#5b5547; --rule:#111111; --red:#e60012; --yellow:#ffe100; --card:#fffdf5;
  --head:"Dela Gothic One","BIZ UDPGothic",system-ui,sans-serif; --body:"BIZ UDPGothic",system-ui,sans-serif;
  --num:"Oswald","Barlow Condensed","BIZ UDPGothic",sans-serif; --dots:rgba(17,17,17,.10);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#16140f; --paper2:#211e16; --ink:#f3eedf; --mute:#b5ad98; --rule:#f3eedf; --card:#1d1a13; --dots:rgba(243,238,223,.08); color-scheme:dark}}
:root[data-theme="dark"]{--paper:#16140f; --paper2:#211e16; --ink:#f3eedf; --mute:#b5ad98; --rule:#f3eedf; --card:#1d1a13; --dots:rgba(243,238,223,.08); color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.7 var(--body);padding:0 0 48px}
.wrap{max-width:880px;margin:0 auto;display:grid;gap:20px;padding:0 16px}
/* 題字 */
.mast{margin:0;background:#111;color:#fff;padding:14px 16px 12px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;align-items:center;border-bottom:6px solid var(--red)}
.mast .logo{display:flex;flex-direction:column;align-items:center;gap:2px}
.mast .logo svg{display:block;width:58px;height:58px}
.mast .ti{font:400 clamp(30px,8vw,52px)/1 var(--head);color:var(--yellow);letter-spacing:.04em}
.mast .ti small{font-size:.42em;color:#fff;margin-left:8px;letter-spacing:0;vertical-align:.35em}
.mast .ed{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin-top:6px;font-size:13px;color:#ddd}
.mast .gr{background:var(--red);color:#fff;font:400 16px/1 var(--head);padding:5px 9px;border-radius:2px}
.mast h1{margin:0;font:400 clamp(18px,4.6vw,26px)/1.25 var(--head);color:#fff}
/* 一面 */
.front{display:grid;grid-template-columns:auto minmax(0,1fr);border:3px solid var(--rule);background:var(--card)}
.front .vhead{writing-mode:vertical-rl;text-orientation:upright;background:var(--red);color:#fff;font:400 clamp(24px,6vw,36px)/1.15 var(--head);
  padding:12px 8px;letter-spacing:.04em;max-height:440px}
.front .fb{padding:14px 16px;display:grid;gap:8px;align-content:start;background-image:radial-gradient(var(--dots) 1px,transparent 1.2px);background-size:6px 6px}
.front .big{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.front .big b{font:700 clamp(64px,18vw,112px)/.95 var(--num);color:var(--red)}
.front .big span{font:400 18px var(--head)}
.front .big em{font-style:normal;font:700 26px var(--num);color:var(--mute)}
.front ul{margin:0;padding-left:1.1em;font-size:14px;display:grid;gap:4px}
.front .dist{height:110px}
/* 前文 */
.lead{margin:0;border-top:3px double var(--rule);border-bottom:3px double var(--rule);padding:10px 2px;font-size:14px}
.lead b{background:linear-gradient(transparent 55%,var(--yellow) 55%)}
.secthead{margin:6px 0 -6px;display:flex;align-items:center;gap:10px;font:400 22px/1 var(--head)}
.secthead::before{content:"";width:12px;height:26px;background:var(--red)}
.secthead::after{content:"";flex:1;height:3px;background:var(--rule)}
/* 注目選手 */
.pick{background:var(--card);border:3px solid var(--rule);display:grid;gap:0}
.pk-h{background:#111;color:#fff;display:flex;align-items:baseline;gap:10px;padding:8px 12px;flex-wrap:wrap}
.pk-h .no{background:var(--red);color:#fff;font:400 14px/1 var(--head);padding:5px 8px;align-self:center}
.pk-h .no b{font:700 20px/1 var(--num);margin-left:2px}
.pk-h .nm{font:400 clamp(24px,6vw,32px)/1.1 var(--head);color:#fff}
.pk-h .meta{font-size:13px;color:#ccc}
.pk-main{display:block}
.pk-tag{justify-self:start;background:var(--red);color:#fff;display:inline-flex;align-items:center;gap:10px;padding:6px 12px 7px;
  transform:skewX(-8deg);box-shadow:4px 4px 0 #111}
.pk-tag .vt{font:400 clamp(20px,5.4vw,28px)/1.1 var(--head);letter-spacing:.04em;transform:skewX(8deg)}
.pk-tag .st{color:var(--yellow);font-size:17px;line-height:1;white-space:nowrap;transform:skewX(8deg)}
.pk-tag .st:empty{display:none}
.pk-body{padding:14px 14px 12px;display:grid;gap:9px;align-content:start}
.pk-body h2{margin:0;font:400 clamp(20px,5vw,27px)/1.35 var(--head);text-wrap:balance}
.mk{background:linear-gradient(transparent 58%,var(--yellow) 58%);box-decoration-break:clone;-webkit-box-decoration-break:clone}
.pk-num{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;border-top:1px dashed var(--rule);border-bottom:1px dashed var(--rule);padding:2px 0}
.pk-num b{font:700 clamp(46px,12vw,64px)/1 var(--num);color:var(--red)}
.pk-num small{font-size:13px;color:var(--mute);font-weight:700}
.com{margin:0;font-size:15px}
.mikata{display:grid;grid-template-columns:46px minmax(0,1fr);gap:10px;align-items:start}
.mikata svg{display:block}
.mikata p{margin:0;position:relative;background:#fff;color:#111;border:2px solid #111;border-radius:12px;padding:8px 11px;font-size:14px}
.mikata p::before{content:"";position:absolute;left:-9px;top:14px;border:8px solid transparent;border-right-color:#111;border-left:0}
.mikata b{display:block;font-size:12px;color:var(--red)}
.crs-hint{margin:0;font-size:13.5px;background:var(--paper2);padding:7px 10px;border-left:6px solid #111}
.crs-hint b{display:block;font-size:12px;color:var(--red)}
.pk-data{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;padding:10px 14px;border-top:3px solid var(--rule);align-items:center}
@media (max-width:620px){.pk-data{grid-template-columns:1fr}}
.pk-data figure{margin:0;display:grid;justify-items:center;gap:2px}
.radar{width:100%;max-width:330px;height:auto}
.radar .rg{fill:none;stroke:var(--mute);stroke-opacity:.35;stroke-width:1}
.radar .rd{fill:var(--red);fill-opacity:.22;stroke:var(--red);stroke-width:2.2;stroke-linejoin:round}
.radar text{font-size:11px;fill:var(--mute);font-weight:700}
.radar .rv{font-family:var(--num);font-weight:700;fill:var(--ink);font-size:13px}
figcaption{font-size:11.5px;color:var(--mute)}
.mini{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;width:100%}
.mini th,.mini td{padding:3px 6px;border-bottom:1px solid var(--mute);text-align:right}
.mini tr:first-child th{background:#111;color:#fff;font-size:12px}
.mini th:first-child{text-align:center}
.mini td{font:600 15px var(--num)}
.kim{margin:6px 0 0;font-size:12px;color:var(--mute)}
.tags{list-style:none;margin:0;padding:10px 14px 12px;display:grid;gap:6px;border-top:1px dashed var(--rule)}
.tags li{display:grid;gap:0}
.tags b{font-size:14px}
.tags b i{font-style:normal;color:var(--red);margin-left:6px;letter-spacing:1px}
.tags span{font-size:12.5px;color:var(--mute)}
.alt{padding:0 14px 10px;font-size:12px;color:var(--mute)}
.alt ul{margin:4px 0 0;padding-left:1.2em}
/* 早見表・場の傾向 */
.nerai{background:var(--card);border:3px solid var(--rule);padding:0 0 12px;display:grid;gap:8px}
.nerai h3{margin:0;background:#111;color:var(--yellow);font:400 20px/1.3 var(--head);padding:8px 12px}
.nerai > p{margin:0 12px;font-size:12.5px;color:var(--mute)}
.waku{border-collapse:collapse;width:calc(100% - 24px);margin:0 12px}
.waku th,.waku td{padding:7px 6px;border-bottom:2px solid var(--rule);text-align:left;vertical-align:middle}
.waku th{white-space:nowrap;width:1%}
.waku th .lt{width:34px;height:38px;font-size:24px;border-radius:2px}
.waku th small{display:block;font-weight:700;color:var(--mute);font-size:11px;margin-top:2px}
.waku td span{display:inline-flex;align-items:baseline;gap:4px;margin:2px 14px 2px 0;white-space:nowrap;font-weight:700}
.waku td span:first-child{font-size:16px}
.waku td span:first-child em{color:var(--red);font-size:22px}
.waku td em{font-style:normal;font:700 18px var(--num)}
.waku td small{color:var(--mute);font-size:11px;font-weight:400}
.trend ul{margin:0 12px;padding-left:1.1em;display:grid;gap:4px;font-size:14px}
.dist{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;align-items:end;max-width:420px;height:130px;margin:4px 12px 0}
.dist div{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:3px;height:100%}
.dist i{display:block;width:70%;background:var(--ink)}
.dist div:first-child i{background:var(--red)}
.dist b{font:700 15px var(--num)}
.lt{display:inline-grid;place-items:center;width:22px;height:24px;border-radius:2px;font:700 15px var(--num);box-shadow:inset 0 0 0 1.5px rgba(0,0,0,.45)}
/* 囲み記事 */
.corners{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px}
.corner{background:var(--card);border:3px solid var(--rule);padding:0 0 12px}
.corner h3{margin:0 0 8px;background:var(--red);color:#fff;font:400 18px/1.35 var(--head);padding:7px 12px}
.corner ul{margin:0 12px;padding-left:1.1em;display:grid;gap:5px;font-size:14px}
.corner p{margin:6px 12px 0;color:var(--mute);font-size:12.5px}
.corner p:has(+ ul){color:var(--ink);font-weight:700;font-size:13.5px}
.scn{border-collapse:collapse;width:calc(100% - 24px);margin:0 12px;font-size:13px}
.scn th,.scn td{padding:5px 4px;border-bottom:1px solid var(--mute);text-align:right;white-space:nowrap}
.scn tr:first-child th{background:#111;color:#fff;font-size:11.5px;text-align:center}
.scn th:first-child{text-align:left}
.scn td{font:600 16px var(--num)}
.scn tr.hi td{color:var(--red)}
.basis{font-size:12.5px}
.basis h3{background:#111}
.basis dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;margin:0 12px}
.basis dt{font-weight:700}
.basis dd{margin:0;color:var(--mute)}
.foot{font-size:12px;color:var(--mute);border-top:3px double var(--rule);padding-top:10px;margin:0}
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
    out = f"""<section class="nerai"><h3>狙い目の早見表 コースが決まったらチェック</h3>
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
           nerai_block: str = "", front: str = "") -> str:
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
    grade = title.split(" ")[0] if title.split(" ")[0] in ("SG", "PG1", "G1", "G2", "G3") else ""
    name = title[len(grade):].strip() if grade else title
    return f"""<title>ミカタ新聞 {e(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=BIZ+UDPGothic:wght@400;700&family=Oswald:wght@600;700&display=swap">
<style>{CSS}</style>
<header class="mast"><div class="logo">{gull_svg(58, bg="#f4efdf")}</div><div>
<div class="ti">ミカタ新聞<small>競艇をいろんな角度から</small></div>
<div class="ed">{f'<span class="gr">{e(grade)}</span>' if grade else ''}<h1>{e(name)}</h1></div>
<div class="ed">{e(venue_name + ' ・ ' if venue_name else '')}出場{len(all_cards)}人 ・ 注目{len(picks)}人 ・ 集計 {e(meta['period'][0])}〜{e(meta['asof'])} ・ 下書き {today}</div></div></header>
<div class="wrap">
{front}
<p class="lead">{note}公式の予想紙・スポーツ紙とは別の切り口で、選手の「型」をデータで読む新聞です。<b>使っているのは、時期を変えても同じ選手に出ると確かめた本物の型だけ</b>(ジンクスの検証は後半)。数字はすべて公式の成績データを自分たちで集計したもので、見出しはどれも下の基準を満たした数字に基づいています。</p>
<h2 class="secthead">注目選手</h2>
{blocks}
<h2 class="secthead">狙い目と場の傾向</h2>
{nerai_block}
<h2 class="secthead">データの囲み</h2>
<div class="corners">{cor}</div>
<section class="corner basis"><h3>タグの基準</h3><dl>{basis}</dl>
<p>「上位X%」は同じ級別(A1・A2・B級)の中での位置。★★★は上位1%、★★は上位5%、★は上位10%。3着内率の「上積み」は、コースごとの全体の3着内率を差し引いた値。回数が少ない数字は全体や本人の普段の値に寄せて計算しています。</p></section>
<p class="foot">この新聞は選手の傾向を楽しむための読み物で、舟券の的中や利益を約束するものではありません。公式の成績データ(番組表・競走成績)を自分たちで集計した数字とグラフだけを使っています。舟券の購入は20歳になってから。</p>
</div>"""


def front_html(trend: dict | None, venue: str | None) -> str:
    """一面: 場の傾向の一番の数字を大きく(全国との差があるときだけ、言い方は title_ideas と同じ考え方)。"""
    if not trend or not venue:
        return ""
    tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
    nt = trend["nat_top"] if tp is trend["top"] else trend["nat_all"]
    lbl = "トップ級のレース" if tp is trend["top"] else "全レース"
    d = tp["c1"] - nt["c1"]
    head = f"{venue}の1号艇は絶対じゃない" if d <= -0.04 else f"{venue}はインが強い" if d >= 0.04 else f"{venue}の1号艇は全国なみ"
    bars = "".join(f'<div><b>{tp["dist"][k]:.0%}</b><i style="height:{round(tp["dist"][k] * 120)}px"></i>{lane_tile(k - 1)}</div>' for k in range(1, 7))
    lines = "".join(f"<li>{e(x)}</li>" for x in nerai.trend_lines(trend, venue)[1:])
    return f"""<section class="front"><div class="vhead">{e(head)}</div><div class="fb">
<div class="big"><span>1号艇の1着率</span><b>{tp['c1']:.0%}</b><em>全国 {nt['c1']:.0%}</em></div>
<p style="margin:0;font-size:13px;color:var(--mute)">{e(venue)}の{e(lbl)}({tp['n']}レース)。過去3年</p>
<div class="dist">{bars}</div><ul>{lines}</ul></div></section>"""


def title_ideas(title: str, venue: str | None, n_all: int, picks, trend: dict | None) -> list[str]:
    """note のタイトル案。考え方(発信方針): 先頭に「へえ」と思う具体的な数字のフック(場の傾向か注目1の数字)、
    大会名と場名(検索)、人数(保存版の価値)。スマホの一覧で切れるので、フックは20字前後・全体は45字以内を目安。
    「的中」「必勝」「儲かる」「裏」は使わない。"""
    import re as _re
    short = _re.sub(r"第[0-9０-９]+回", "", title)
    short = _re.sub(r"[(（].*?[)）]", "", short).replace("  ", " ").strip()
    c, t, heads, com, bc = picks[0]
    out = []
    if trend and venue:
        tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
        nt = trend["nat_top"] if tp is trend["top"] else trend["nat_all"]
        c1, nc1 = tp["c1"], nt["c1"]
        if c1 - nc1 <= -0.04:
            out.append(f"{venue}の1号艇は{c1:.0%}しか勝てない|{short} 出場{n_all}人をデータで読む")
            out.append(f"{venue}の1号艇、どこまで信じる?|{short} 全{n_all}人の“型”と狙い目のコース")
        elif c1 - nc1 >= 0.04:
            out.append(f"{venue}のインは{c1:.0%}で逃げる|{short} 出場{n_all}人をデータで読む")
            out.append(f"イン天国{venue}で、それでも崩す人は誰?|{short} 全{n_all}人の“型”")
        else:
            k = max(trend["kim_non1"].items(), key=lambda x: x[1])[0]
            out.append(f"{venue}でインが負けるときは{k}が{trend['kim_non1'][k]:.0%}|{short} 出場{n_all}人をデータで読む")
    out.append(f"{heads[0].split(' ')[0]}|{short} 全{n_all}人の“型”")
    out.append(f"「勝負駆けに強い」は本物か|{short} 全{n_all}人をデータで読む")
    out.append(f"【保存版】{short} 全{n_all}人のひと言タグとコース別の早見表")
    out.append(f"{short}の{n_all}人、データで見ると誰が何の“職人”か")
    return [f"{x}({len(x)}字)" for x in out[:5]]


USE_STEPS = mag.USE_STEPS


def note_text(title, venue_name, picks, sel, corners_txt, free_corner: list[str] | None = None,
              waku: list[str] | None = None, trend: list[str] | None = None, trend_raw: dict | None = None,
              next_issue: str | None = None) -> str:
    """note に貼る本文の下書き。買う人の心理(発信方針)に沿った順番:
    1) 数字のフック(巻頭リード)で「へえ」 → 2) 誰向けか・誰向けでないか(買い目は無いと先に言う=安心)
    → 3) 現地での使い方(使っている自分を想像できる) → 4) 無料で中身の質を証明(注目1・場の傾向・展示ST・早見表の1段だけ)
    → 5) 推しが載っているか(出場全員の名前)と有料の目次 → 線 → 有料。煽り・ニセの期限は使わない"""
    n_all, n_pick = len(sel), len(picks)
    trust = free_corner or []

    def pick_lines(i, x):
        c, t, heads, com, bc = x
        out = [f"■注目{i}{'(無料で公開)' if i == 1 else ''} {c['name']}({c['class']}・{c['branch']}支部・{int(c['age'] or 0)}歳)「{t['t']}」",
               f"〔画像:{c['id']}_{c['name']}.png〕", f"【{heads[0]}】", mag.deck(c, t), ""] + \
              [p for para in mag.body(c, t, bc) for p in (para, "")] + [f"ミカタのひと言:「{mag.mikata(t)}」"]
        if bc:
            out.append(f"狙い目のコース:{course_line(bc, c)}")
        return out + [""]

    out = ["【タイトル案】(先頭の数字がフック。スマホの一覧では40字くらいで切れるので、|より前が勝負)"] + \
          [f"{i}. {x}" for i, x in enumerate(title_ideas(title, venue_name, n_all, picks, trend_raw), 1)] + [
           "", "【見出し画像】表紙(ミカタ新聞の1面)か、注目1のカード画像", "",
           "――――――――――(ここから無料)――――――――――", "",
           *[x for p_ in mag.issue_lead(sel, picks, trend_raw, venue_name, title) for x in (p_, "")],
           "■このノートについて",
           "買い目は売っていません。あなたが自分で予想するときに「へえ、この人はこういう型なのか」と使える“材料”を集めたノートです。",
           "(もともとは、友達と現地で観戦するときに「この選手ってどんな型?」と話したくて集め始めたデータです)", "",
           "こんな人に向いています",
           "・現地や中継で、自分で予想するのが好きな人",
           "・推しの選手の“型”を、数字で知りたい人",
           "・出走表を見ても、どこを見ればいいか迷う人",
           "向いていない人",
           "・買い目だけがほしい人(このノートに買い目はありません)", "",
           "■現地での使い方(3ステップ)", *USE_STEPS, "",
           "■この記事でわかること",
           f"・注目{n_pick}人の“型”と、その根拠の数字",
           "・狙い目の早見表:コースが決まったら、そのコースで強い選手がすぐわかる(スマホの待ち受けサイズの画像つき)",
           "・展示STを信じていい選手" + (f"、{venue_name}の傾向" if trend else ""),
           "・いま伸びている選手(成長指数)、大一番はここが違う(優勝戦・準優の指数)",
           "・「勝負駆けに強い」「最終レースは荒れる」「3-2.5.6-2.5.6」は本物? ジンクス・オカルト検証",
           f"・保存版:出場{n_all}人全員のひと言タグ一覧", ""]
    out += pick_lines(1, picks[0])
    if trend:
        out += [f"■{venue_name}の傾向"] + [f"・{x}" for x in trend] + [""]
    if trust:
        out += trust + [""]
    if waku:
        out += ["■狙い目の早見表(1コースの段だけ公開)", waku[0], "→ 2〜6コースの段は有料パートで(まくり・差しの選手がどこに並ぶかが見えてきます)", ""]
    out += [f"■あなたの推しは載っている? 出場{n_all}人", "/".join(c["name"] for c in sel),
            "→ 全員の「ひと言タグ」は有料パートの保存版に", ""]
    out += ["■有料パートの中身"]
    out += [f"・注目{i} {pc['name']}「{pt['t']}」{mag.stars(pt)}" for i, (pc, pt, *_r) in enumerate(picks, 1) if i > 1]
    if waku:
        out.append("・狙い目の早見表(全段)+ スマホの待ち受けサイズの画像")
    out += [f"・{x[1:]}" for x in corners_txt if x.startswith("■") and not x.startswith("■展示ST")]
    out += [f"・保存版:出場{n_all}人のひと言タグ一覧", "",
            "数字はすべて、公式の成績データを自分たちで集計したものです。根拠の数字と判定の基準も全部載せています。", "",
            "――――――――――(ここから有料:note の有料エリアの線をここに)――――――――――", ""]
    for i, x in enumerate(picks, 1):
        if i > 1:
            out += pick_lines(i, x)
    if waku:
        out += ["■狙い目の早見表(コースが決まったらチェック)", "〔画像:早見表_待ち受け.png〕(保存してスマホの写真から見られます)",
                "出走表と展示の進入が出たら、得意なコースに入った選手を探してみてください。"] + waku + [f"※{WAKU_NOTE}", ""]
    out += [x for x in corners_txt if not x.startswith("■展示ST") and x not in trust] + [""]
    out += [f"■保存版:出場{n_all}人のひと言タグ一覧"]
    for c in sel:
        tags = [f"{t['t']}{mag.stars(t)}" for t in c["tags"][:2]]
        out.append(f"・{c['name']}({c['class']}・{c['branch']}){' / '.join(tags) if tags else '(目立つタグなし)'}")
    out += ["", "■現地での使い方(もう一度)", *USE_STEPS, "",
            "■この記事のデータについて",
            "・公式の成績データ(番組表・競走成績、2023年10月〜)を自分たちで集計しています。出走表・オッズの表・写真は使っていません",
            "・「上位◯%」は同じ級別(A1・A2・B級)の中での位置です。★★★は上位1%、★★は上位5%、★は上位10%",
            "・3着内率はコースの有利不利を差し引いた値で比べています。コースは枠番ではなく、実際に進入したコースです",
            "・タグは、時期を変えても同じ選手に出ると確かめた型だけに付けています(基準は全文を下書きに)",
            "・この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません",
            "・舟券の購入は20歳になってから。無理のない範囲で楽しみましょう", "",
            "■次号予告",
            (next_issue or "次のSG・G1の出場選手が発表されたら、また“材料”をまとめます。") + "フォローしておくと、出たときに通知が届きます。"]
    return "\n".join(out)


def x_text(title, venue_name, picks, sel, trust_names: list[str], venue_names: list[str], trend_head: str | None = None) -> str:
    """X の投稿案(3つのスレッド)。1投稿は X の数え方で280以内(全角2・英数1)に収める(超えるときは名前の数を減らす)。"""
    n_all = len(sel)
    import re as _re
    short = _re.sub(r"第[0-9０-９]+回", "", title)
    short = _re.sub(r"[(（].*?[)）]", "", short)
    short = _re.sub(r"^\s*(SG|PG1|G1|GⅠ|G2|GⅡ|G3|GⅢ)\s*", "", short).strip()
    tag = "#" + "".join(ch for ch in short if ch not in " 　・") if short else ""

    def fit(make, names):
        for k in range(min(3, len(names)), -1, -1):
            p = make(names[:k])
            if mag.xlen(p) <= 280:
                return p
        return make([])
    p1 = fit(lambda ns: f"{title}、出場予定{n_all}人をデータで読みました📰\n\n買い目ではなく、予想が楽しくなる“材料”をまとめています。"
                        + ("\n\nまずは「展示STを信じていい選手」👇\n" + "\n".join(f"・{x}" for x in ns) if ns else ""), trust_names)
    if trust_names and mag.xlen(p1 + "\n\nみんなは展示ST、どこまで信じる派?") <= 280:
        p1 += "\n\nみんなは展示ST、どこまで信じる派?"
    if trend_head:
        p2 = trend_head + f"\n\nみんなは{venue_name}の1号艇、どこまで信じる?"
    elif venue_names:
        p2 = fit(lambda ns: f"{venue_name}と相性がいい選手(3着内率が普段より上)\n" + "\n".join(f"・{x}" for x in ns), venue_names)
    else:
        p2 = f"注目選手のカードを1枚だけ先に公開。{picks[0][0]['name']}は「{picks[0][1]['t']}」"
    p3 = (f"注目{len(picks)}人の“型”、コースが決まったら使える狙い目の早見表、全{n_all}人のひと言タグ一覧はnoteにまとめました"
          f"(現地観戦のおともに)\n\n(noteのURL)\n\n#競艇 #ボートレース {tag}")
    extra = []
    for x in occult_data().get("occult", []):
        if x["key"] == "r12":
            extra.append(f"「最終レースは荒れる」って本当?\n\n過去3年で調べたら逆でした。人気薄で決まった割合は12Rが{x['value']:.0%}、ほかのレースは{x['ref']:.0%}。\n"
                         "12Rは強い選手が1号艇に入る番組が多いから、かも。\n\nみんなの「信じてるジンクス」教えてください")
        if x["key"] == "3256":
            extra.append(f"「3-2.5.6-2.5.6」は熱いのか、過去のオッズと結果で確かめました。\n\n人気のわりに来た割合は{x['value']:.2f}(1.0が人気どおり)。\n"
                         "熱くも冷たくもない、人気どおりでした。\n\nでも、信じて買うのも競艇の楽しみ。みんなの推し出目は?")
        if x["key"] == "home":
            extra.append(f"「地元の選手は強い」は本当でした。ただし小さめ。\n\n同じ選手で比べると、地元の3着内率は平均{x['value'] * 100:+.1f}ポイント。\n"
                         "一方で「誰が○○巧者か」は、時期を変えると顔ぶれが入れ替わる(参考程度)。\n\nみんなは地元選手、買う派?")
    out = []
    for i, p in enumerate((p1, p2, p3, *extra), 1):
        warn = "  ※長すぎます(Xの上限280)" if mag.xlen(p) > 280 else ""
        out += [f"--- 投稿{i}({mag.xlen(p)}/280){warn}{'  ※小ネタ(別の日に単独で)' if i > 3 else ''} ---", p, ""]
    out.append("画像: 投稿1に注目1人目のカードを添える。投稿2は文字だけでよい(場の傾向の数字が主役)")
    out.append("出し方: noteのリンクは最後の投稿だけ(本文にリンクがあると届きにくい)。平日の12時台か20〜23時、初日の前日の夜がおすすめ。"
               "返信が来たら返す(返信のやりとりがいちばん評価される)")
    return "\n".join(out)


JINX = [("kake", "勝負駆けに強い選手"), ("big", "準優・優勝戦に強い選手"), ("rough", "荒れ水面に強い選手"),
        ("venue", "場との相性(○○巧者)"), ("first", "節の初戦に強い選手"), ("late_y", "予選の後半に上げてくる選手")]
REAL = [("st", "平均ST"), ("front", "前づけ率"), ("makuri", "まくりで勝つ割合")]


def occult_data() -> dict:
    p = ROOT / "reports/occult.json"
    import json as _json
    return _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _st3(v: float) -> str:
    return f"{v:.3f}"[1:]


def scene_lines() -> list[str]:
    """場面ごとに「いつもとどう違うか」(予選と比べる。scripts/occult_check.py)。"""
    sc = occult_data().get("scenes", {})
    b = sc.get("予選")
    if not b:
        return []
    out = []
    for k in ("選抜・特選", "ドリーム戦", "準優勝戦", "優勝戦"):
        x = sc.get(k)
        if not x:
            continue
        out.append(f"{k}:1号艇の1着率{x['c1']:.0%}(予選{b['c1']:.0%})、平均ST{_st3(x['st'])}(予選{_st3(b['st'])})、"
                   f"進入が動いた{x['moved']:.0%}(予選{b['moved']:.0%})、まくり・まくり差しの決着{x['makuri']:.0%}(予選{b['makuri']:.0%})")
    rs = occult_data().get("racer_scene", {}).get("st_big", {})
    if rs.get("r") is not None:
        out.append(f"選手ごとの「大一番でSTを上げてくる度合い」は時期を変えると入れ替わりやすい(似ている度合い{rs['r']:.2f})。場面の違いは全員に共通、と見るのがよさそう")
    return out


def occult_lines() -> list[str]:
    """よく聞くオカルトの検証(scripts/occult_check.py)。お金の額は出さない。"""
    out = []
    for x in occult_data().get("occult", []):
        k, v, r = x["key"], x["value"], x["ref"]
        if k == "rain":
            out.append(f"「雨の日はインが弱い」→ {x['verdict']}。1号艇の1着率は雨{v:.1%}・晴れや曇り{r:.1%}({x['note']})")
        elif k == "r12":
            out.append(f"「最終レースは荒れる」→ {x['verdict']}。人気薄で決まった割合は12Rが{v:.0%}、ほかが{r:.0%}。"
                       f"12Rは強い選手が1号艇に入る番組が多いため({x['note']})")
        elif k == "home":
            out.append(f"「地元の選手は強い」→ {x['verdict']}。同じ選手で比べて3着内率が平均{v * 100:+.1f}ポイント。{x['note']}")
        elif k == "3256":
            out.append(f"「3-2.5.6-2.5.6は熱い」→ {x['verdict']}(人気のわりに来た割合{v:.2f}、1.0が人気どおり)。熱くも冷たくもない")
        elif k == "123":
            out.append(f"「1-2-3はよく来る」→ {x['verdict']}(人気のわりに来た割合{v:.2f})。いちばん来る出目({x['note']})。"
                       "ただし控除があるので、買い続けて得になるほどではない")
    return out


def jinx_lines() -> list[str]:
    """よく言われる「〇〇に強い」が本物かどうか(scripts/trait_reliability.py の結果)。"""
    p = ROOT / "reports/trait_reliability.json"
    if not p.exists():
        return []
    import json as _json
    t = _json.loads(p.read_text(encoding="utf-8"))["traits"]
    # 「似ている度合い」= 前半と後半の相関。1.00なら顔ぶれがそっくり、0なら無関係(読者には相関という言葉を使わない)
    out = [f"{label}:時期を変えると顔ぶれが入れ替わる(似ている度合い{t[k]['r']:.2f}、1.00でそっくり)。過去に強かった選手が次も強いとは限らない"
           for k, label in JINX if k in t and "r" in t[k]]
    real = "、".join(f"{label}{t[k]['r']:.2f}" for k, label in REAL if k in t and "r" in t[k])
    if real:
        out.append(f"(くらべると、本物の型は {real} と高く、同じ選手に何度も出る。この記事の注目選手の「型」はこちら側だけで選んでいます)")
    return out


def make(title: str, keys: list[str], jcd: int | None, n: int = 8, note: str = "", d=None, cards=None, meta=None,
         next_issue: str | None = None) -> dict:
    """下書き一式(HTML・note の本文・X の投稿案)と、画像にする注目選手を返す。d・cards・meta を渡せば集計を使い回す。"""
    if d is None:
        d = rc.load_table()
    if cards is None:
        cards, meta = rc.build(d)
    meta = {**meta, "rules": {r["tag"]: r["rule"] for r in meta["rules"]} if isinstance(meta["rules"], list) else dict(meta["rules"])}
    sel, missing = [], []
    for k in keys:
        c = rc.find(cards, k)
        if c and c["id"] not in {x["id"] for x in sel}:
            sel.append(c)
        elif not c:
            missing.append(k)
    vf: dict = {}   # 場との相性は使わない(偶然の幅が大きい)
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
    gr = sorted([c for c in sel if c["growth"]["n90"] >= 15 and c["growth"]["n_prev"] >= 30 and (c["growth"]["index"] or 0) >= 0.2],
                key=lambda c: -c["growth"]["index"])
    if gr:
        corners.append(("いま伸びている(成長指数)", "<ul>" + "".join(
            f"<li>{e(c['name'])} 成長指数 {c['growth']['index']:+.2f}(勝率{c['growth']['prev']:.2f}→{c['growth']['pts90']:.2f})</li>" for c in gr[:5])
            + "</ul><p>成長指数=直近90日の勝率の伸び×0.41。伸びの4割ほどは次の3か月も残る、という過去3年の平均から</p>"))
        txt += ["■いま伸びている(成長指数)"] + [f"・{c['name']} 成長指数 {c['growth']['index']:+.2f}(勝率{c['growth']['prev']:.2f}→{c['growth']['pts90']:.2f})" for c in gr[:5]] + \
               ["※成長指数=直近90日の勝率の伸び×0.41(伸びの4割ほどは次の3か月も残る、という過去3年の平均から)"]
    scn = scene_lines()
    if scn:
        sc = occult_data().get("scenes", {})
        rows = "".join(f"<tr class=\"{'hi' if k in ('準優勝戦', '優勝戦') else ''}\"><th>{e(k)}</th><td>{x['c1']:.0%}</td><td>{_st3(x['st'])}</td>"
                       f"<td>{x['moved']:.0%}</td><td>{x['makuri']:.0%}</td></tr>"
                       for k in ("予選", "選抜・特選", "ドリーム戦", "準優勝戦", "優勝戦") if (x := sc.get(k)))
        corners.append(("大一番はここが違う(場面ごとの指数)",
                        f"<table class=\"scn\"><tr><th>場面</th><th>1号艇の1着</th><th>平均ST</th><th>進入が動く</th><th>まくり系</th></tr>{rows}</table>"
                        f"<p>{e(scn[-1])}</p><p>過去3年の全レースを場面ごとに集計。まくり系=まくり・まくり差しで決まった割合</p>"))
        txt += ["■大一番はここが違う(場面ごとの指数)"] + [f"・{x}" for x in scn] + ["※過去3年の全レースを場面ごとに集計。予選と比べた違い"]
    jinx, occ = jinx_lines(), occult_lines()
    if jinx or occ:
        body = ""
        if jinx:
            body += "<p>選手の「○○に強い」は本物?</p><ul>" + "".join(f"<li>{e(x)}</li>" for x in jinx) + "</ul>"
        if occ:
            body += "<p style='margin-top:6px'>よく聞くオカルト</p><ul>" + "".join(f"<li>{e(x)}</li>" for x in occ) + "</ul>"
        body += ("<p style='margin-top:6px'>「似ている度合い」は、同じ選手を奇数月と偶数月に分けて、片方で強い選手がもう片方でも強いか(1.00でそっくり、0で無関係)。"
                 "データでは差が出なくても、信じて買うのも競艇の楽しみ。こういう見方もあるよ、ということで</p>")
        corners.append(("ジンクス・オカルト検証", body))
        txt += ["■ジンクス・オカルト検証", "(選手の「○○に強い」は本物?)"] + [f"・{x}" for x in jinx] + ["(よく聞くオカルト)"] + [f"・{x}" for x in occ] + \
               ["※「似ている度合い」は、同じ選手を奇数月と偶数月に分けて、片方で強い選手がもう片方でも強いか(1.00でそっくり、0で無関係)。",
                "データでは差が出なくても、信じて買うのも競艇の楽しみ。こういう見方もあるよ、ということで"]
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
    page = mag.page(title, vname, picks, sel, wt, trend, corners, meta["rules"], note, mag.cover_hook(trend, vname),
                    (meta["period"][0], meta["asof"]))
    trust_lines = ["■展示STを信じていい選手(展示と本番のSTのずれが小さい)"] + \
        [f"・{c['name']}(ずれ平均{c['ex']['mae']:.3f}秒、{c['ex']['n']}走)" for c in trust] if trust else []
    waku = [f"{crs}コース {label}:" + "、".join(xs) for crs, label, xs in waku_rows(wt) if xs]
    tl = nerai.trend_lines(trend, vname) if trend else None
    th = nerai.trend_headline(trend, vname) if trend else None
    return {"html": page, "note": note_text(title, vname, picks, sel, txt, trust_lines, waku, tl, trend, next_issue),
            "x": x_text(title, vname, picks, sel, [c["name"] for c in trust], [], th),
            "picks": picks, "sel": sel, "missing": missing, "jcd": jcd, "venue": vname, "wt": wt}


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
