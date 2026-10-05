"""「型」の紋章。選手カードのタグの横・画像・新聞に付ける、うち独自の小さなマーク。

本人の顔(写真・似顔絵)はパブリシティ権の問題があるので使わない。代わりに「型」を絵にして、推しの型を集める楽しさを出す。
第3案(2026-10-05): ピクトグラム。色の丸に白い太いシルエット1つ。道路標識のように、ぱっと見で分かることを最優先。
型ごとに色が決まっていて、集めると並べたくなる統一感。文字は入れない(名前はキャプションで)。viewBox 0 0 100 100。
"""
from __future__ import annotations

INK = "#14212c"
COLORS = {
    "スタート職人": "#d7191c", "展示STを信じていい": "#1f6fd1", "本番で踏み込む": "#f05a1a", "イン逃げ番長": "#14212c",
    "差し職人": "#1a9b4a", "まくり屋": "#c2185b", "まくり差しの職人": "#7b3fb8", "外からでも届く": "#0b8ca8",
    "前づけの仕掛け人": "#c98a00", "展示は控えめ、本番で化ける": "#9c27b0", "上り調子": "#e65100", "舟券に絡む安定感": "#2e7d32",
}
SHORT = {"スタート職人": "ST職人", "展示STを信じていい": "展示", "本番で踏み込む": "踏込", "イン逃げ番長": "逃げ", "差し職人": "差し", "まくり屋": "まくり",
         "まくり差しの職人": "まく差", "外からでも届く": "外伸び", "前づけの仕掛け人": "前づけ", "展示は控えめ、本番で化ける": "化け", "上り調子": "上昇",
         "舟券に絡む安定感": "安定"}
W = "#ffffff"
_S = f'fill="none" stroke="{W}" stroke-linecap="round" stroke-linejoin="round"'
BOAT = "M 18 50 L 34 42 L 70 44 L 86 50 L 70 56 L 34 58 Z"   # 舟のシルエット(舳先が右)

# 白いシルエット。線の太さは 9〜11 でそろえる
_ART = {
    # ストップウォッチ。針は12時
    "スタート職人": (f'<circle cx="50" cy="56" r="24" {_S} stroke-width="9"/><path d="M 50 32 L 50 22 M 40 22 L 60 22" {_S} stroke-width="9"/>'
                 f'<path d="M 50 56 L 50 40" {_S} stroke-width="9"/><circle cx="50" cy="56" r="5" fill="{W}"/>'),
    # 目(見たまま信じていい)
    "展示STを信じていい": (f'<path d="M 14 50 C 30 26 70 26 86 50 C 70 74 30 74 14 50 Z" {_S} stroke-width="9"/>'
                   f'<circle cx="50" cy="50" r="11" fill="{W}"/>'),
    # 舟がラインを突き抜ける、後ろに勢いの線
    "本番で踏み込む": (f'<path d="M 64 18 L 64 82" {_S} stroke-width="6" stroke-dasharray="9 8"/>'
                 f'<path d="{BOAT}" fill="{W}" transform="translate(8 0)"/>'
                 f'<path d="M 8 40 L 20 40 M 4 50 L 18 50 M 8 60 L 20 60" {_S} stroke-width="6"/>'),
    # 「1」が王冠をかぶっている
    "イン逃げ番長": (f'<path d="M 24 38 L 30 22 L 40 32 L 50 18 L 60 32 L 70 22 L 76 38 Z" fill="{W}"/>'
                 f'<path d="M 38 56 L 50 46 L 50 84 M 36 84 L 64 84" {_S} stroke-width="10"/>'),
    # 外の弧(細)の内側を、太い矢で刺す
    "差し職人": (f'<path d="M 14 80 L 54 80 A 24 24 0 0 0 54 32 L 44 32" {_S} stroke-width="5" stroke-opacity=".55"/>'
             f'<path d="M 18 64 L 54 64 A 10 10 0 0 0 54 44 L 44 44" {_S} stroke-width="10"/>'
             f'<path d="M 50 34 L 40 44 L 50 54" {_S} stroke-width="10"/>'),
    # 外から大きく回り込む太い矢
    "まくり屋": (f'<path d="M 18 82 L 56 82 A 30 30 0 0 0 56 22 L 44 22" {_S} stroke-width="11"/>'
            f'<path d="M 52 12 L 40 22 L 52 32" {_S} stroke-width="11"/>'
            f'<circle cx="50" cy="56" r="6" fill="{W}" fill-opacity=".7"/>'),
    # 2つの点の間を縫う S
    "まくり差しの職人": (f'<circle cx="30" cy="34" r="7" fill="{W}" fill-opacity=".7"/><circle cx="30" cy="66" r="7" fill="{W}" fill-opacity=".7"/>'
                 f'<path d="M 12 50 C 40 50 40 24 60 24 C 76 24 82 36 82 50 C 82 64 76 76 60 76" {_S} stroke-width="10"/>'
                 f'<path d="M 68 66 L 58 76 L 68 86" {_S} stroke-width="10"/>'),
    # 右端から真ん中の的へ、長い矢
    "外からでも届く": (f'<circle cx="30" cy="50" r="16" {_S} stroke-width="7"/><circle cx="30" cy="50" r="4" fill="{W}"/>'
                f'<path d="M 90 50 L 52 50" {_S} stroke-width="10"/><path d="M 62 38 L 50 50 L 62 62" {_S} stroke-width="10"/>'),
    # 外の枠から内へ、斜めに入る太い矢(上は点線のライン)
    "前づけの仕掛け人": (f'<path d="M 16 24 L 84 24" {_S} stroke-width="6" stroke-dasharray="9 8"/>'
                 f'<path d="M 78 82 L 36 46" {_S} stroke-width="11"/><path d="M 36 64 L 32 42 L 54 40" {_S} stroke-width="11"/>'),
    # ちょうちょ
    "展示は控えめ、本番で化ける": (f'<path d="M 50 50 C 36 26 12 30 24 50 C 12 70 36 74 50 50 Z" fill="{W}"/>'
                       f'<path d="M 50 50 C 64 26 88 30 76 50 C 88 70 64 74 50 50 Z" fill="{W}"/>'
                       f'<path d="M 50 30 L 50 72" {_S} stroke-width="7"/><path d="M 50 32 L 42 20 M 50 32 L 58 20" {_S} stroke-width="5"/>'),
    # 右肩上がりの矢
    "上り調子": (f'<path d="M 14 78 L 36 56 L 50 68 L 78 34" {_S} stroke-width="11"/>'
             f'<path d="M 60 32 L 80 32 L 80 52" {_S} stroke-width="11"/>'),
    # いかり
    "舟券に絡む安定感": (f'<circle cx="50" cy="22" r="8" {_S} stroke-width="7"/><path d="M 50 30 L 50 84 M 32 42 L 68 42" {_S} stroke-width="9"/>'
                 f'<path d="M 18 60 C 20 78 34 86 50 86 C 66 86 80 78 82 60 M 18 60 L 30 66 M 82 60 L 70 66" {_S} stroke-width="9"/>'),
}


ALIAS = {"急成長中": "上り調子"}


def emblem_svg(tag: str, size: int = 40, cls: str = "emb", ring: bool = True) -> str:
    """型の紋章。知らないタグなら空文字。"""
    tag = ALIAS.get(tag, tag)
    art = _ART.get(tag)
    if not art:
        return ""
    c = COLORS.get(tag, INK)
    return (f'<svg class="{cls}" viewBox="0 0 100 100" width="{size}" height="{size}" role="img" aria-label="{tag}の紋章">'
            f'<circle cx="50" cy="50" r="48" fill="{c}"/>'
            + (f'<circle cx="50" cy="50" r="44" fill="none" stroke="{W}" stroke-opacity=".35" stroke-width="2"/>' if ring else "")
            + art + "</svg>")


def sheet_html() -> str:
    """12個を並べた見本(確認用)。小さい表示も並べる。"""
    cells = "".join(f'<div class="cell">{emblem_svg(t, 128)}<b>{t}</b></div>' for t in _ART)
    small = "".join(emblem_svg(t, 28) for t in _ART)
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@700&display=swap">'
            '<style>body{margin:0;background:#f4efdf;font-family:"Zen Kaku Gothic New",sans-serif;padding:24px}h1{font:400 26px "Dela Gothic One",sans-serif;margin:0 0 16px}'
            '.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.cell{background:#fff;border:3px solid #14212c;padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:8px}'
            '.cell b{font-size:13.5px;text-align:center}.small{margin-top:18px;display:flex;gap:6px;align-items:center;background:#fff;padding:10px;border:3px solid #14212c}.small span{font-size:13px;margin-right:6px}</style></head><body>'
            '<h1>ミカタの「型」の紋章 12種(第3案: ピクトグラム)</h1>'
            f'<div class="grid">{cells}</div><div class="small"><span>タグの横の大きさ(28px):</span>{small}</div></body></html>')


def js_module() -> str:
    """アプリ用(docs/emblems.js)。window.EMBLEM(tag, size) で同じ絵を出す。"""
    import json
    data = {t: {"c": COLORS[t], "a": _ART[t]} for t in _ART}
    return ("// 自動生成: python -c 'from kyotei.emblem import js_module; print(js_module())' > docs/emblems.js\n"
            f"const EMBLEMS = {json.dumps(data, ensure_ascii=False)};\nconst EMBLEM_ALIAS = {json.dumps(ALIAS, ensure_ascii=False)};\n"
            "function emblem(tag, size = 22) {\n  tag = EMBLEM_ALIAS[tag] || tag;\n  const d = EMBLEMS[tag];\n  if (!d) return \"\";\n"
            "  return `<svg class=\"emb\" viewBox=\"0 0 100 100\" width=\"${size}\" height=\"${size}\" role=\"img\" aria-label=\"${tag}の紋章\"><circle cx=\"50\" cy=\"50\" r=\"48\" fill=\"${d.c}\"/>${d.a}</svg>`;\n}\n")
