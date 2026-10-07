"""選手カードの描画(裏新聞の下書きと、X・Instagram・note 用の画像で共通)。

数字はすべて racer_card.build() の集計。公式の写真・ロゴ・表は使わない。
"""
from __future__ import annotations

import html
import math

from . import racer_card as rc

e = html.escape


def radar_svg(vals: dict, W: int = 340, H: int = 236, R: float = 74, cls: str = "radar") -> str:
    """6軸のレーダーチャート。横長の枠に描いて、左右のラベル(「展示の信頼度 50」など)が切れないようにする。"""
    labels = rc.RADAR
    c, cy, n = W / 2, H / 2, len(labels)

    def pt(i, v):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return c + R * v * math.cos(a), cy + R * v * math.sin(a)
    ring = lambda v: " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i in range(n)))  # noqa: E731
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, max(0.03, (vals.get(l) or 0) / 100)) for i, l in enumerate(labels)))
    out = [f'<svg class="{cls}" viewBox="0 0 {W} {H}" role="img" aria-label="'
           + "、".join(f"{l} {round(vals[l]) if vals.get(l) is not None else '-'}" for l in labels) + '">']
    out += [f'<polygon class="rg" points="{ring(v)}"/>' for v in (0.25, 0.5, 0.75, 1)]
    out += [f'<line class="rg" x1="{c}" y1="{cy}" x2="{pt(i, 1)[0]:.1f}" y2="{pt(i, 1)[1]:.1f}"/>' for i in range(n)]
    out.append(f'<polygon class="rd" points="{poly}"/>')
    for i, l in enumerate(labels):
        x, y = pt(i, 1.17)
        anchor = "middle" if abs(x - c) < 4 else ("start" if x > c else "end")
        v = vals.get(l)
        out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}">{e(l)}'
                   f'<tspan class="rv" dx="3">{round(v) if v is not None else "-"}</tspan></text>')
    out.append("</svg>")
    return "".join(out)


def catch(c: dict, jcd: int | None = None, used: set | None = None) -> tuple[str, str]:
    """画像の一番大きいコピー(タグ名と根拠)。何枚かまとめて作るときは、ほかの選手と同じタグを避ける(used)。
    タグが無ければレーダーで一番高い項目。"""
    tags = [t for t in c["tags"] if not (jcd and t["cat"] == "venue" and t.get("jcd") != jcd)]
    if tags:
        t = next((x for x in tags if used is None or x["t"] not in used), tags[0])
        if used is not None:
            used.add(t["t"])
        return t["t"], t["why"]
    best = max(((k, v) for k, v in c["radar"].items() if v is not None), key=lambda x: x[1], default=None)
    g = rc.GROUP_NAME.get(c["grp"], "")
    if best and best[1] >= 70:
        return f"{best[0]}が持ち味", f"{g}の中で{rc.top(best[1])}"
    return "データで見る選手カード", f"{c['n']}走の成績から"


GEN_RING = "#0b5fb4"


def _emb(tag: str, size: int) -> str:
    from .emblem import emblem_svg
    return emblem_svg(tag, size, cls="emb")


# ゲンさんの紹介(2026-10-07 ユーザー「ゲンさんってなに?ってなることが無いように」): どの記事・投稿・画像でも、最初に出るところで添える
GEN_WHO = "ゲンかつぎ歴40年の大先輩"
GEN_NAME = f"ゲンさん({GEN_WHO})"


def gull_svg(size: int = 104, ring: str = "#c8141c", bg: str = "#eef1e4", cls: str = "gull", who: str = "mikata") -> str:
    """カモメのアイコン(輪の中の顔)。公式のキャラとは無関係の自作。カード画像・下書き・アプリで共通。

    who="mikata": 記者のミカタ(赤い輪、鉛筆は別のパターン)。who="gen": ゲンさん(ハンチング帽、青い輪。ゲンかつぎの大先輩)。
    """
    if who == "gen" and ring == "#c8141c":
        ring = GEN_RING
    body = ('<path d="M 58 200 L 90 182 C 102 152 125 139 146 133 C 134 110 140 70 176 58 C 206 48 229 72 227 100 '
            'C 226 118 219 130 213 138 C 241 160 246 205 221 232 C 196 258 141 262 111 245 C 99 238 93 229 89 221 Z" '
            'fill="#ffffff" stroke="#14212c" stroke-width="5" stroke-linejoin="round"/>'
            '<path d="M 105 170 C 130 150 185 155 207 186 C 217 206 202 228 172 232 C 142 236 110 225 92 212 Z" '
            'fill="#a9b4bb" stroke="#14212c" stroke-width="5" stroke-linejoin="round"/>'
            '<path d="M 223 92 C 242 91 259 95 271 102 C 266 108 257 108 249 106 L 223 108 Z" fill="#f2c230" stroke="#14212c" stroke-width="4" stroke-linejoin="round"/>'
            '<path d="M 223 108 L 250 107 C 256 111 254 118 246 118 C 236 117 229 115 223 114 Z" fill="#f2c230" stroke="#14212c" stroke-width="4" stroke-linejoin="round"/>'
            '<circle cx="246.5" cy="112" r="3.6" fill="#c8141c"/>'
            '<path d="M 224 109.5 Q 220.6 109.2 218.9 106.3" stroke="#14212c" stroke-width="2.6" stroke-linecap="round" fill="none"/>'
            '<circle cx="199" cy="90" r="5.8" fill="#14212c"/>'
            '<path d="M 192.4 87.6 A 6.6 6.6 0 0 1 205.6 87.6 Q 199 85.2 192.4 87.6 Z" fill="' + bg + '"/>'
            '<path d="M 192.2 87.8 Q 199 85.2 205.8 87.8" stroke="#14212c" stroke-width="3" stroke-linecap="round" fill="none"/>')
    if who == "gen":  # ハンチング帽と、目じりのしわ(ベテラン)
        body += ('<path d="M 139 86 C 143 56 172 40 202 44 C 221 47 233 59 236 72 L 256 79 C 252 86 238 87 226 85 C 200 79 168 80 140 91 Z" '
                 'fill="#14212c" stroke="#14212c" stroke-width="3" stroke-linejoin="round"/>'
                 '<path d="M 150 72 C 170 62 205 60 230 70" stroke="#56636e" stroke-width="2.5" fill="none" stroke-linecap="round"/>'
                 f'<circle cx="188" cy="44" r="4.5" fill="{ring}"/>'
                 '<path d="M 186 97 Q 190 100 194 98" stroke="#14212c" stroke-width="2.2" stroke-linecap="round" fill="none"/>')
    uid = f"g{size}{cls}{who[0]}"
    label = "カモメの記者ミカタ" if who == "mikata" else "ゲンかつぎの大先輩ゲンさん"
    return (f'<svg class="{cls}" viewBox="0 0 300 300" width="{size}" height="{size}" role="img" aria-label="{label}">'
            f'<defs><clipPath id="{uid}"><circle cx="150" cy="150" r="121"/></clipPath></defs>'
            f'<circle cx="150" cy="150" r="150" fill="{bg}"/>'
            f'<g clip-path="url(#{uid})"><g transform="translate(136 182) scale(1.45) translate(-188 -98)">{body}</g></g>'
            f'<circle cx="150" cy="150" r="128" fill="none" stroke="{ring}" stroke-width="13"/></svg>')


IMG_FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Shippori+Mincho:wght@700;800'
             '&family=Zen+Kaku+Gothic+New:wght@500;700;900&family=Oswald:wght@500;600;700&display=block">')
LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
LANE_FG = ["#111111", "#ffffff", "#ffffff", "#ffffff", "#111111", "#ffffff"]

IMG_CSS = """
*{box-sizing:border-box}
body{margin:0;width:1080px;height:1350px;background:#f4efdf;color:#111;font-family:"Zen Kaku Gothic New","Noto Sans CJK JP",sans-serif;font-feature-settings:"palt"}
.card{position:relative;width:1080px;height:1350px;display:grid;grid-template-rows:14px 96px auto auto auto 1fr 72px}
.lanebar{display:grid;grid-template-columns:repeat(6,1fr)}
.lanebar i:nth-child(1){background:#fff}.lanebar i:nth-child(2){background:#17191c}.lanebar i:nth-child(3){background:#e3141b}
.lanebar i:nth-child(4){background:#0b5fb4}.lanebar i:nth-child(5){background:#f5d00a}.lanebar i:nth-child(6){background:#12904a}
.top{background:#111;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 56px;border-bottom:8px solid #e60012}
.brand{font:400 48px/1 "Dela Gothic One",sans-serif;color:#ffe100;letter-spacing:.04em}
.kicker{font:700 26px/1.2 "Zen Kaku Gothic New",sans-serif;color:#fff;text-align:right}
.kicker b{display:inline-block;background:#e60012;color:#fff;font:400 26px/1 "Dela Gothic One",sans-serif;padding:6px 10px;margin-right:12px;vertical-align:2px}
.head{padding:28px 56px 0;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:end}
.meta{font:700 28px/1.2 "Zen Kaku Gothic New",sans-serif;color:#5e5848;letter-spacing:.06em}
.name{font:400 118px/1.02 "Dela Gothic One",sans-serif;letter-spacing:.02em;margin-top:6px}
.gull svg{display:block;width:132px;height:132px;transform:rotate(-6deg)}
.tagrow{padding:22px 56px 0}
.tagrow{display:flex;align-items:center;gap:22px}
.embs{margin-left:auto;display:flex;align-items:center;gap:6px;flex:0 0 auto} .embs small{display:none}
.tag{display:inline-flex;align-items:center;gap:18px;background:#e60012;color:#fff;padding:12px 26px 14px;transform:skewX(-10deg);box-shadow:8px 8px 0 #111}
.tag > *{transform:skewX(10deg)}
.tag b{font:400 50px/1.1 "Dela Gothic One",sans-serif;white-space:nowrap}
.tag i{font-style:normal;color:#ffe100;font-size:40px;letter-spacing:4px}
.why{padding:20px 56px 0;font:800 30px/1.5 "Shippori Mincho",serif;border-left:0}
.why span{background:linear-gradient(transparent 62%,#ffe100 62%)}
.mid{padding:14px 56px 0;display:grid;grid-template-columns:420px minmax(0,1fr);gap:30px;align-items:start}
.big{border-top:6px solid #111;border-bottom:3px solid #111;padding:8px 0 10px}
.big b{display:block;font:700 150px/.95 "Oswald",sans-serif;color:#e60012;letter-spacing:-.01em}
.big small{display:block;font:700 26px/1.35 "Zen Kaku Gothic New",sans-serif;color:#5e5848;margin-top:4px}
.mini{margin-top:16px;display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.mini div{background:#fffcf2;border:3px solid #111;padding:8px 14px}
.mini span{display:block;font:700 20px "Zen Kaku Gothic New",sans-serif;color:#5e5848}
.mini b{font:600 44px/1.05 "Oswald",sans-serif}
.rimg .rg{fill:none;stroke:#5e5848;stroke-opacity:.35;stroke-width:1.4}
.rimg .rd{fill:#e60012;fill-opacity:.22;stroke:#e60012;stroke-width:3.5;stroke-linejoin:round}
.rimg text{font-size:19px;fill:#5e5848;font-weight:700;font-family:"Zen Kaku Gothic New",sans-serif}
.rimg .rv{font-family:"Oswald",sans-serif;font-size:24px;fill:#111;font-weight:600}
.cap{font:700 19px "Zen Kaku Gothic New",sans-serif;color:#5e5848;text-align:center;margin-top:-4px}
.bars{padding:8px 56px 0;display:grid;gap:7px;align-content:start}
.bars h4{margin:0 0 2px;font:900 24px "Zen Kaku Gothic New",sans-serif;display:flex;justify-content:space-between}
.bars h4 span{color:#5e5848;font-weight:700;font-size:20px}
.cb{display:grid;grid-template-columns:52px minmax(0,1fr) 230px;gap:16px;align-items:center}
.lt{display:grid;place-items:center;width:48px;height:40px;font:700 28px "Oswald",sans-serif;box-shadow:inset 0 0 0 3px rgba(0,0,0,.55)}
.tr{position:relative;height:26px;background:rgba(17,17,17,.10)}
.tr i{position:absolute;left:0;top:0;bottom:0}
.tr .t3{background:#e60012;opacity:.35}.tr .w{background:#e60012}
.cn{font:500 26px "Oswald",sans-serif;text-align:right;white-space:nowrap}
.cn b{font-weight:700;font-size:31px}
.foot{background:#111;color:#ddd;display:flex;align-items:center;justify-content:space-between;padding:0 56px;font:700 19px/1.35 "Zen Kaku Gothic New",sans-serif}
.foot b{color:#ffe100;font:400 24px "Dela Gothic One",sans-serif}
"""


def card_image_html(c: dict, jcd: int | None = None, kicker: str = "データで見る選手カード", used: set | None = None) -> str:
    """1080×1350(4:5)の画像用 HTML。ミカタ新聞の紙面と同じ見た目。"""
    g = rc.GROUP_NAME.get(c["grp"], "")
    t0, why0 = catch(c, jcd, used)
    tag = next((t for t in c["tags"] if t["t"] == t0), None)
    sc = tag.get("score") if tag else None
    st_ = "" if not tag or tag.get("cat") in ("front", "growth", "exlate", "ex2") or sc is None else \
        ("★★★" if sc >= 99 else "★★" if sc >= 95 else "★" if sc >= 90 else "")
    from .mag import big_stat
    num, lbl = big_stat(c, tag) if tag else (f"{c['top3']:.0%}", "3着内率")
    k1 = c["kim"]["nige"]
    nige = f"{k1['w'] / k1['n']:.0%}" if k1["n"] else "-"
    stv = rc.st_fmt(c["st"]["avg"]) if c["st"]["avg"] is not None else "-"
    pc = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
    bars = "".join(
        f'<div class="cb"><span class="lt" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'
        f'<div class="tr"><i class="t3" style="width:{(x["top3"] or 0) * 100:.0f}%"></i><i class="w" style="width:{(x["win"] or 0) * 100:.0f}%"></i></div>'
        f'<span class="cn"><b>{pc(x["win"])}</b> / {pc(x["top3"])}</span></div>' for i, x in enumerate(c["courses"]))
    other_tags = [x["t"] for x in c["tags"] if x["t"] != t0 and _emb(x["t"], 10)][:4]
    others = (f'<div class="embs"><small>ほかの型</small>{"".join(_emb(x, 44) for x in other_tags)}</div>') if other_tags else ""
    import re as _re
    m = _re.match(r"(SG|PG1|G1|G2|G3)\s*(.*)", kicker)
    kick = f"<b>{e(m.group(1))}</b>{e(m.group(2))}" if m else e(kicker)
    return f"""<!doctype html><meta charset="utf-8">{IMG_FONTS}<style>{IMG_CSS}</style>
<div class="card">
  <div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div>
  <div class="top"><div class="brand">ミカタ新聞</div><div class="kicker">{kick}</div></div>
  <div class="head"><div><div class="meta">{e(c['class'] or '')} ・ {e(c['branch'] or '')}支部 ・ {int(c['age'] or 0)}歳</div><div class="name">{e(c['name'])}</div></div>
    <div class="gull">{gull_svg(132, bg="#f4efdf", cls="img")}</div></div>
  <div class="tagrow">{_emb(t0, 96)}<div class="tag"><b>{e(t0)}</b><i>{st_}</i></div>{others}</div>
  <div class="why"><span>{e(why0)}</span></div>
  <div>
    <div class="mid"><div><div class="big"><b>{e(num)}</b><small>{e(lbl)}</small></div>
      <div class="mini"><div><span>1コース逃げ率</span><b>{nige}</b></div><div><span>平均ST</span><b>{stv}</b></div></div></div>
      <div>{radar_svg(c['radar'], W=540, H=330, R=104, cls='rimg')}<div class="cap">{e(g)}の中での位置(100がトップ)</div></div></div>
    <div class="bars"><h4>コース別の成績<span>1着率 / 3着内率</span></h4>{bars}</div>
  </div>
  <div class="foot"><span>公式の成績データ({e(c['period'][0][:7].replace('-', '/'))}〜{e(c['asof'][:7].replace('-', '/'))}、{c['n']}走)を独自に集計<br>舟券は20歳になってから</span><b>競艇をいろんな角度から</b></div>
</div>"""
