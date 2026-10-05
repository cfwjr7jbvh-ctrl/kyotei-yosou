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


def gull_svg(size: int = 104, ring: str = "#c8141c", bg: str = "#eef1e4", cls: str = "gull") -> str:
    """カモメの記者のアイコン(赤い輪の中の顔)。公式のキャラとは無関係の自作。カード画像・下書き・アプリで共通。"""
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
    uid = f"g{size}{cls}"
    return (f'<svg class="{cls}" viewBox="0 0 300 300" width="{size}" height="{size}" role="img" aria-label="カモメの記者">'
            f'<defs><clipPath id="{uid}"><circle cx="150" cy="150" r="121"/></clipPath></defs>'
            f'<circle cx="150" cy="150" r="150" fill="{bg}"/>'
            f'<g clip-path="url(#{uid})"><g transform="translate(136 182) scale(1.45) translate(-188 -98)">{body}</g></g>'
            f'<circle cx="150" cy="150" r="128" fill="none" stroke="{ring}" stroke-width="13"/></svg>')


IMG_CSS = """
*{box-sizing:border-box}
body{margin:0;width:1080px;height:1350px;background:#eef1e4;color:#14212c;font-family:"Noto Sans CJK JP","BIZ UDPGothic",sans-serif}
.card{position:relative;width:1080px;height:1350px;padding:56px 64px 48px;display:grid;grid-template-rows:auto auto auto 1fr auto;gap:24px}
.top{display:flex;align-items:center;justify-content:space-between}
.kicker{font-size:30px;font-weight:700;letter-spacing:.06em;color:#56636e}
.seal{width:112px;height:112px;transform:rotate(-6deg)}
.seal svg{display:block;width:112px;height:112px}
.name{font:900 108px/1.05 "Noto Sans CJK JP Black","Noto Sans CJK JP",sans-serif;letter-spacing:.02em}
.sub{font-size:34px;color:#56636e;margin-top:12px}
.catch{background:#c8141c;color:#fff;border-radius:10px;padding:22px 30px}
.catch b{display:block;font:900 66px/1.15 "Noto Sans CJK JP Black","Noto Sans CJK JP",sans-serif}
.catch span{display:block;font-size:30px;margin-top:8px;opacity:.95}
.mid{display:grid;grid-template-columns:620px 1fr;gap:20px;align-items:center}
.rimg .rg{fill:none;stroke:#c7cfb8;stroke-width:1.2}
.rimg .rd{fill:#c8141c;fill-opacity:.2;stroke:#c8141c;stroke-width:3;stroke-linejoin:round}
.rimg text{font-size:19px;fill:#56636e;font-weight:700}
.rimg .rv{font-family:"DejaVu Sans Condensed","Noto Sans CJK JP",sans-serif;font-size:23px;fill:#14212c}
.cap{font-size:22px;color:#56636e;text-align:center;margin-top:-6px}
.kv{display:grid;gap:16px}
.kv div{background:#f8faf2;border-radius:10px;padding:14px 20px}
.kv span{display:block;font-size:24px;color:#56636e;font-weight:700}
.kv b{font:700 54px/1.1 "DejaVu Sans Condensed","Noto Sans CJK JP",sans-serif}
.kv small{font-size:22px;color:#56636e;margin-left:6px}
.tags{display:grid;gap:14px;align-content:start}
.tags>div:not(.crs){border-left:8px solid #c8141c;padding:4px 0 4px 18px}
.tags b{font-size:36px}
.tags span{display:block;font-size:24px;color:#3d4a54}
.crs h4{margin:0 0 10px;font-size:26px;color:#56636e}
.crs .row{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;align-items:end}
.crs .col{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px}
.crs .pct{font:700 26px "DejaVu Sans Condensed",sans-serif}
.crs .bar{width:56px;background:#14212c;border-radius:4px 4px 0 0}
.crs .ln{width:44px;height:40px;border-radius:5px;display:grid;place-items:center;font:700 26px "DejaVu Sans Condensed",sans-serif;margin-top:6px;box-shadow:inset 0 0 0 2px rgba(0,0,0,.25)}
.foot{font-size:21px;color:#56636e;line-height:1.5;border-top:2px solid #14212c;padding-top:14px}
"""


def card_image_html(c: dict, jcd: int | None = None, kicker: str = "データで見る選手カード", used: set | None = None) -> str:
    """1080×1350(4:5)の画像用 HTML。"""
    g = rc.GROUP_NAME.get(c["grp"], "")
    t0, why0 = catch(c, jcd, used)
    rest = [t for t in c["tags"] if t["t"] != t0 and not (jcd and t["cat"] == "venue" and t.get("jcd") != jcd)][:2]
    k1 = c["kim"]["nige"]
    nige = f"{k1['w'] / k1['n']:.0%}" if k1["n"] else "-"
    st = rc.st_fmt(c["st"]["avg"]) if c["st"]["avg"] is not None else "-"
    tags = "".join(f"<div><b>{e(t['t'])}</b><span>{e(t['why'])}</span></div>" for t in rest)
    if len(rest) <= 1:  # タグが少ない選手は、コース別の3着内率で下を埋める
        bg = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
        fg = ["#14212c", "#ffffff", "#ffffff", "#ffffff", "#14212c", "#ffffff"]
        pc = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
        cols = "".join(
            f'<div class="col"><span class="pct">{pc(x["top3"])}</span>'
            f'<span class="bar" style="height:{0 if x["top3"] is None else round(x["top3"] * 110)}px"></span>'
            f'<span class="ln" style="background:{bg[i]};color:{fg[i]}">{i + 1}</span></div>' for i, x in enumerate(c["courses"]))
        tags += f'<div class="crs"><h4>コース別の3着内率</h4><div class="row">{cols}</div></div>'

    return f"""<!doctype html><meta charset="utf-8"><style>{IMG_CSS}</style>
<div class="card">
  <div class="top"><div><div class="kicker">{e(kicker)}</div><div class="name">{e(c['name'])}</div>
    <div class="sub">{e(c['class'] or '')} ・ {e(c['branch'] or '')} ・ {int(c['age'] or 0)}歳</div></div><div class="seal">{gull_svg(112)}</div></div>
  <div class="catch"><b>{e(t0)}</b><span>{e(why0)}</span></div>
  <div class="mid"><div>{radar_svg(c['radar'], W=620, H=390, R=120, cls='rimg')}<div class="cap">{e(g)}の中での位置(100がトップ)</div></div>
    <div class="kv"><div><span>3着内率</span><b>{c['top3']:.0%}</b></div><div><span>1コース逃げ率</span><b>{nige}</b></div>
      <div><span>平均ST</span><b>{st}</b><small>{e(rc.top(c['st']['grp'])) if c['st']['grp'] is not None else ''}</small></div></div></div>
  <div class="tags">{tags}</div>
  <div class="foot">公式の成績データ({e(c['period'][0][:7].replace('-', '/'))}〜{e(c['asof'][:7].replace('-', '/'))}、{c['n']}走)を独自に集計。上位%とチャートは{e(g)}の中での位置。舟券は20歳になってから</div>
</div>"""
