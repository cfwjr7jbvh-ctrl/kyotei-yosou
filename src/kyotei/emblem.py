"""「型」の紋章。選手カードのタグの横・画像・新聞に付ける、うち独自の小さなマーク。

本人の顔(写真・似顔絵)はパブリシティ権の問題があるので使わない。代わりに「型」を絵にして、推しの型を集める楽しさを出す。
第4案(2026-10-05 ユーザー指定: 舟の動きで表す・かわいい寄り): 角丸の色タイルに、上から見た小さな舟(白、墨の縁取り)と、
その型らしい動き(スリット・ターン・航跡・ブイ)を1場面で描く。ほかの舟は薄く、主役の舟は白。
型ごとに色が決まっていて、集めると並べたくなる。文字は入れない(名前はキャプションで)。viewBox 0 0 100 100。
"""
from __future__ import annotations

INK = "#14212c"
W = "#ffffff"
COLORS = {
    "スタート職人": "#e8453c", "展示STを信じていい": "#3b82e6", "本番で踏み込む": "#f2772b", "イン逃げ番長": "#2c3e50",
    "差し職人": "#2eaa5e", "まくり屋": "#d6336c", "まくり差しの職人": "#8e5bd6", "外からでも届く": "#1aa3b8",
    "前づけの仕掛け人": "#d99a1e", "展示は控えめ、本番で化ける": "#b04fc9", "上り調子": "#f06a3a", "舟券に絡む安定感": "#3a9c6c",
}
SHORT = {"スタート職人": "ST職人", "展示STを信じていい": "展示", "本番で踏み込む": "踏込", "イン逃げ番長": "逃げ", "差し職人": "差し", "まくり屋": "まくり",
         "まくり差しの職人": "まく差", "外からでも届く": "外伸び", "前づけの仕掛け人": "前づけ", "展示は控えめ、本番で化ける": "化け", "上り調子": "上昇",
         "舟券に絡む安定感": "安定"}
ALIAS = {"急成長中": "上り調子"}


def boat(x: float, y: float, rot: float = 0, scale: float = 1.0, faint: bool = False, fill: str = W) -> str:
    """上から見た小さな舟(舳先が右)。faint なら薄く(脇役)。"""
    op = ' opacity=".38"' if faint else ""
    return (f'<g transform="translate({x} {y}) rotate({rot}) scale({scale})"{op}>'
            f'<path d="M -11 -6 L 9 -4.6 Q 16 0 9 4.6 L -11 6 Q -14.5 0 -11 -6 Z" fill="{fill}" stroke="{INK}" stroke-width="2.6" stroke-linejoin="round"/>'
            f'<rect x="-13" y="-3" width="4" height="6" rx="1.2" fill="{INK}"/>'
            f'<circle cx="0" cy="0" r="3" fill="{INK}"/></g>')


def buoy(x: float, y: float) -> str:
    return f'<circle cx="{x}" cy="{y}" r="5" fill="#ff5a36" stroke="{W}" stroke-width="2.2"/>'


def trail(d: str, width: float = 4, dash: str | None = None, op: float = .85) -> str:
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<path d="{d}" fill="none" stroke="{W}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" stroke-opacity="{op}"{da}/>'


def line(x: float, y1: float, y2: float) -> str:
    return f'<path d="M {x} {y1} L {x} {y2}" stroke="{W}" stroke-width="3" stroke-dasharray="5 4" stroke-linecap="round" stroke-opacity=".9"/>'


def spark(x: float, y: float, s: float = 1.0) -> str:
    return (f'<g transform="translate({x} {y}) scale({s})"><path d="M 0 -9 L 2 -2 L 9 0 L 2 2 L 0 9 L -2 2 L -9 0 L -2 -2 Z" fill="#ffe34d" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/></g>')


# 場面(各型の動き)。舟は大きめ(scale 1.4 前後)、要素は少なく
_ART = {
    # スタートライン(点線)に舳先がぴたり。時計は12時
    "スタート職人": line(66, 18, 82) + trail("M 10 50 L 30 50", 4) + boat(46, 50, 0, 1.45) + spark(78, 30, 1.0)
                 + f'<circle cx="78" cy="76" r="11" fill="{W}" stroke="{INK}" stroke-width="2.6"/><path d="M 78 76 L 78 68" stroke="{INK}" stroke-width="3" stroke-linecap="round"/><circle cx="78" cy="76" r="1.8" fill="{INK}"/>',
    # 展示(点線の舟)と本番(白い舟)が同じ場所=信じていい。チェック
    "展示STを信じていい": line(70, 18, 82) + f'<g opacity=".6" transform="translate(52 50) scale(1.45)"><path d="M -11 -6 L 9 -4.6 Q 16 0 9 4.6 L -11 6 Q -14.5 0 -11 -6 Z" fill="none" stroke="{W}" stroke-width="2" stroke-dasharray="3 3"/></g>'
                   + trail("M 8 50 L 28 50", 4) + boat(48, 50, 0, 1.45) + f'<path d="M 64 24 L 72 32 L 88 16" fill="none" stroke="#ffe34d" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
    # ラインを突き抜けて、しぶきと勢いの線
    "本番で踏み込む": line(40, 18, 82) + trail("M 6 40 L 22 40 M 2 50 L 20 50 M 6 60 L 22 60", 4) + boat(60, 50, 0, 1.6)
                 + f'<path d="M 80 30 C 88 30 92 36 90 44 M 82 70 C 90 70 94 64 92 56" fill="none" stroke="{W}" stroke-width="4" stroke-linecap="round"/>',
    # ブイのすぐそばを小さく回る。王冠つき
    "イン逃げ番長": buoy(66, 56) + trail("M 8 76 L 44 76 C 62 76 70 66 64 54 C 60 46 50 42 42 48", 5) + boat(42, 44, -160, 1.4)
                 + f'<g transform="translate(26 14) scale(.9)"><path d="M 0 16 L 4 4 L 11 11 L 18 2 L 25 11 L 32 4 L 36 16 Z" fill="#ffe34d" stroke="{INK}" stroke-width="2" stroke-linejoin="round"/></g>',
    # 外の舟は大きく膨らみ(薄い)、主役は内側を小さく差す
    "差し職人": buoy(56, 34) + f'<g opacity=".4">{trail("M 8 86 L 46 86 C 70 86 84 70 82 50", 4)}</g>' + boat(78, 42, -105, 1.0, faint=True)
             + trail("M 8 68 L 38 68 C 56 68 62 58 54 48", 5) + boat(50, 44, -150, 1.4),
    # 外から大きく回り込んで前へ。内の舟は薄く
    "まくり屋": buoy(48, 52) + boat(40, 66, 0, 1.1, faint=True) + trail("M 6 86 L 52 86 C 88 86 94 50 78 34 C 70 26 58 28 50 32", 5.5)
            + boat(48, 30, -170, 1.45),
    # 2艇(薄い)の間をSの字で割って入る
    "まくり差しの職人": buoy(68, 32) + boat(34, 34, 0, 1.1, faint=True) + boat(34, 70, 0, 1.1, faint=True)
                 + trail("M 4 52 C 26 52 30 50 46 50 C 62 50 64 40 74 40", 5) + boat(74, 40, -8, 1.4),
    # いちばん外(6本目のレーン)から、長い航跡でブイまで届く
    "外からでも届く": "".join(line(x, 14, 26) for x in (18, 30, 42, 54, 66, 78)) + buoy(22, 68)
                + trail("M 92 88 C 74 88 60 86 48 80 C 40 76 36 72 30 70", 5) + boat(50, 76, -165, 1.4),
    # ラインの手前で、外の枠から内へ斜めに入る。元いた場所は点線の舟
    "前づけの仕掛け人": line(78, 16, 84) + f'<g opacity=".55" transform="translate(26 78) scale(1.2)"><path d="M -11 -6 L 9 -4.6 Q 16 0 9 4.6 L -11 6 Q -14.5 0 -11 -6 Z" fill="none" stroke="{W}" stroke-width="2.2" stroke-dasharray="3 3"/></g>'
                 + trail("M 30 68 C 38 60 44 50 50 40", 4.5, dash="1 7") + boat(58, 32, -28, 1.4),
    # 小さな薄い舟(展示)が、大きな白い舟(本番)に。きらきら
    "展示は控えめ、本番で化ける": boat(24, 70, 0, .8, faint=True) + trail("M 36 64 C 44 58 50 54 58 50", 3, dash="1 6")
                       + boat(64, 44, -12, 1.55) + spark(86, 22, 1.0) + spark(42, 26, .7),
    # 波を登る舟と、上向きの矢
    "上り調子": trail("M 6 80 C 28 80 32 62 52 62 C 68 62 72 46 90 42", 4.5) + boat(54, 56, -24, 1.4)
             + f'<path d="M 68 20 L 88 20 L 88 40" fill="none" stroke="#ffe34d" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
    # 表彰台の3段目まで、舟がちゃんと乗っている
    "舟券に絡む安定感": f'<path d="M 10 88 L 10 70 L 34 70 L 34 88 M 34 88 L 34 54 L 62 54 L 62 88 M 62 88 L 62 64 L 90 64 L 90 88 M 6 88 L 94 88" fill="none" stroke="{W}" stroke-width="3.5" stroke-linejoin="round"/>'
                 + boat(48, 42, 0, 1.25) + f'<path d="M 70 34 L 78 42 L 92 26" fill="none" stroke="#ffe34d" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
}


def emblem_svg(tag: str, size: int = 40, cls: str = "emb", ring: bool = True) -> str:
    """型の紋章。知らないタグなら空文字。"""
    tag = ALIAS.get(tag, tag)
    art = _ART.get(tag)
    if not art:
        return ""
    c = COLORS.get(tag, INK)
    return (f'<svg class="{cls}" viewBox="0 0 100 100" width="{size}" height="{size}" role="img" aria-label="{tag}の紋章">'
            f'<rect x="2" y="2" width="96" height="96" rx="24" fill="{c}" stroke="{INK}" stroke-width="3"/>'
            + (f'<rect x="8" y="8" width="84" height="84" rx="19" fill="none" stroke="{W}" stroke-opacity=".28" stroke-width="2"/>' if ring else "")
            + art + "</svg>")


def sheet_html() -> str:
    """12個を並べた見本(確認用)。小さい表示も並べる。"""
    cells = "".join(f'<div class="cell">{emblem_svg(t, 128)}<b>{t}</b></div>' for t in _ART)
    small = "".join(emblem_svg(t, 28) for t in _ART)
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@700&display=swap">'
            '<style>body{margin:0;background:#f4efdf;font-family:"Zen Kaku Gothic New",sans-serif;padding:24px}h1{font:400 26px "Dela Gothic One",sans-serif;margin:0 0 16px}'
            '.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.cell{background:#fff;border:3px solid #14212c;padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:8px}'
            '.cell b{font-size:13.5px;text-align:center}.small{margin-top:18px;display:flex;gap:6px;align-items:center;background:#fff;padding:10px;border:3px solid #14212c}.small span{font-size:13px;margin-right:6px}</style></head><body>'
            '<h1>ミカタの「型」の紋章 12種(第4案: 舟の動きで)</h1>'
            f'<div class="grid">{cells}</div><div class="small"><span>タグの横の大きさ(28px):</span>{small}</div></body></html>')


def js_module() -> str:
    """アプリ用(docs/emblems.js)。window.emblem(tag, size) で同じ絵を出す。"""
    import json
    data = {t: {"c": COLORS[t], "a": _ART[t]} for t in _ART}
    return ("// 自動生成: python -c 'from kyotei.emblem import js_module; print(js_module())' > docs/emblems.js\n"
            f"const EMBLEMS = {json.dumps(data, ensure_ascii=False)};\nconst EMBLEM_ALIAS = {json.dumps(ALIAS, ensure_ascii=False)};\n"
            "function emblem(tag, size = 22) {\n  tag = EMBLEM_ALIAS[tag] || tag;\n  const d = EMBLEMS[tag];\n  if (!d) return \"\";\n"
            "  return `<svg class=\"emb\" viewBox=\"0 0 100 100\" width=\"${size}\" height=\"${size}\" role=\"img\" aria-label=\"${tag}の紋章\">"
            "<rect x=\"2\" y=\"2\" width=\"96\" height=\"96\" rx=\"24\" fill=\"${d.c}\" stroke=\"#14212c\" stroke-width=\"3\"/>${d.a}</svg>`;\n}\n")
