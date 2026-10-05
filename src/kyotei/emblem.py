"""「型」の紋章(ワッペン)。選手カードのタグの横・画像・新聞に付ける、うち独自の小さなマーク。

本人の顔(写真・似顔絵)はパブリシティ権の問題があるので使わない。代わりに「型」を絵にして、推しの型を集める楽しさを出す。
線は1色(墨)+型ごとの差し色。viewBox 0 0 100 100、丸いワッペンの中に線画。
"""
from __future__ import annotations

INK = "#14212c"
COLORS = {
    "スタート職人": "#c8141c", "展示STを信じていい": "#0b5fb4", "本番で踏み込む": "#e8571a", "イン逃げ番長": "#14212c",
    "差し職人": "#0b7a3b", "まくり屋": "#c8141c", "まくり差しの職人": "#7b3fb8", "外からでも届く": "#0b5fb4",
    "前づけの仕掛け人": "#b8860b", "展示は控えめ、本番で化ける": "#7b3fb8", "上り調子": "#e8571a", "舟券に絡む安定感": "#0b7a3b",
}
SHORT = {"スタート職人": "ST", "展示STを信じていい": "展示", "本番で踏み込む": "踏込", "イン逃げ番長": "逃げ", "差し職人": "差し", "まくり屋": "まくり",
         "まくり差しの職人": "まく差", "外からでも届く": "外", "前づけの仕掛け人": "前づけ", "展示は控えめ、本番で化ける": "化け", "上り調子": "上昇",
         "舟券に絡む安定感": "安定"}

# 線画(stroke は {c}=差し色, {k}=墨)
_ART = {
    # ストップウォッチ、針は12時ぴったり
    "スタート職人": ('<circle cx="50" cy="56" r="24" fill="none" stroke="{k}" stroke-width="5"/><path d="M 50 32 L 50 24 M 42 24 L 58 24" stroke="{k}" stroke-width="5" stroke-linecap="round"/>'
                 '<path d="M 50 56 L 50 38" stroke="{c}" stroke-width="5" stroke-linecap="round"/><circle cx="50" cy="56" r="3.5" fill="{c}"/>'
                 '<path d="M 68 36 L 74 30" stroke="{k}" stroke-width="5" stroke-linecap="round"/>'),
    # 目とチェック(展示を見れば分かる)
    "展示STを信じていい": ('<path d="M 22 50 C 34 32 66 32 78 50 C 66 68 34 68 22 50 Z" fill="none" stroke="{k}" stroke-width="5" stroke-linejoin="round"/>'
                   '<circle cx="50" cy="50" r="9" fill="{k}"/><path d="M 58 70 L 66 78 L 82 60" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 舳先がスタートラインを突き抜ける、勢いの線
    "本番で踏み込む": ('<path d="M 60 22 L 60 78" stroke="{k}" stroke-width="4" stroke-dasharray="7 6"/>'
                 '<path d="M 24 50 L 56 50 L 76 44 L 56 38 Z" fill="{c}" stroke="{k}" stroke-width="4" stroke-linejoin="round" transform="translate(0 6)"/>'
                 '<path d="M 14 42 L 26 42 M 10 52 L 22 52 M 14 62 L 26 62" stroke="{k}" stroke-width="4" stroke-linecap="round"/>'),
    # ブイに最短で巻きつく線と「1」
    "イン逃げ番長": ('<circle cx="64" cy="50" r="8" fill="{c}"/><path d="M 14 70 L 52 70 A 20 20 0 0 0 52 30 L 30 30" fill="none" stroke="{k}" stroke-width="6" stroke-linecap="round"/>'
                 '<text x="30" y="56" font-family="Dela Gothic One, sans-serif" font-size="22" fill="{k}" text-anchor="middle">1</text>'),
    # 外の大きい弧の内側を、鋭い矢が刺す
    "差し職人": ('<path d="M 16 74 L 56 74 A 26 26 0 0 0 56 22 L 40 22" fill="none" stroke="{k}" stroke-width="4" stroke-opacity=".45" stroke-linecap="round"/>'
             '<path d="M 20 60 L 60 60 A 12 12 0 0 0 60 36 L 48 36" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
             '<path d="M 48 28 L 40 36 L 48 44" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 外から大きく回り込む矢
    "まくり屋": ('<path d="M 24 78 L 60 78 A 30 30 0 0 0 60 18 L 44 18" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M 50 10 L 40 18 L 50 26" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M 28 58 L 52 58 A 10 10 0 0 0 52 38" fill="none" stroke="{k}" stroke-width="4" stroke-opacity=".45" stroke-linecap="round"/>'),
    # 2艇の間をSの字で割って入る
    "まくり差しの職人": ('<path d="M 18 34 L 46 34 M 18 66 L 46 66" stroke="{k}" stroke-width="4" stroke-opacity=".45" stroke-linecap="round"/>'
                 '<path d="M 14 50 C 36 50 36 26 56 26 C 70 26 76 36 76 50 C 76 64 68 74 56 74" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
                 '<path d="M 64 68 L 54 74 L 62 82" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 6本のレーンのいちばん外から、真ん中に届く矢
    "外からでも届く": ('<path d="M 18 24 L 18 76 M 30 24 L 30 76 M 42 24 L 42 76 M 54 24 L 54 76 M 66 24 L 66 76" stroke="{k}" stroke-width="3" stroke-opacity=".4"/>'
                '<path d="M 80 76 L 80 42 L 24 42" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                '<path d="M 32 34 L 22 42 L 32 50" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 外の枠から内へ斜めに入る(スタート前の動き)
    "前づけの仕掛け人": ('<path d="M 20 30 L 80 30" stroke="{k}" stroke-width="4" stroke-dasharray="7 6" stroke-linecap="round"/>'
                 '<path d="M 76 74 L 36 46" stroke="{c}" stroke-width="7" stroke-linecap="round"/>'
                 '<path d="M 36 60 L 32 44 L 48 42" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
                 '<circle cx="78" cy="76" r="6" fill="{k}"/>'),
    # 小さな丸から、はじける星(本番で化ける)
    "展示は控えめ、本番で化ける": ('<circle cx="32" cy="64" r="8" fill="none" stroke="{k}" stroke-width="4" stroke-opacity=".5"/>'
                       '<path d="M 62 22 L 67 40 L 86 42 L 71 54 L 76 72 L 62 62 L 48 72 L 53 54 L 38 42 L 57 40 Z" fill="{c}" stroke="{k}" stroke-width="3" stroke-linejoin="round"/>'
                       '<path d="M 40 58 L 46 50" stroke="{k}" stroke-width="3" stroke-linecap="round"/>'),
    # 右肩上がりの折れ線と矢
    "上り調子": ('<path d="M 16 76 L 36 56 L 50 66 L 78 32" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="M 62 30 L 80 30 L 80 48" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="M 14 84 L 86 84" stroke="{k}" stroke-width="4" stroke-linecap="round"/>'),
    # 3段の台(3着以内)にチェック
    "舟券に絡む安定感": ('<path d="M 14 80 L 14 56 L 36 56 L 36 80 M 36 80 L 36 40 L 62 40 L 62 80 M 62 80 L 62 64 L 86 64 L 86 80 M 10 80 L 90 80" fill="none" stroke="{k}" stroke-width="4" stroke-linejoin="round"/>'
                 '<path d="M 40 24 L 48 32 L 64 16" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
}


def emblem_svg(tag: str, size: int = 40, cls: str = "emb", bg: str = "#f8f4e6") -> str:
    """型の紋章。知らないタグなら空文字。"""
    art = _ART.get(tag)
    if not art:
        return ""
    c = COLORS.get(tag, INK)
    return (f'<svg class="{cls}" viewBox="0 0 100 100" width="{size}" height="{size}" role="img" aria-label="{tag}の紋章">'
            f'<circle cx="50" cy="50" r="47" fill="{bg}" stroke="{INK}" stroke-width="4"/>'
            f'<circle cx="50" cy="50" r="41" fill="none" stroke="{c}" stroke-width="2" stroke-dasharray="3 4"/>'
            + art.format(c=c, k=INK) + "</svg>")


def sheet_html() -> str:
    """12個を並べた見本(確認用)。"""
    cells = "".join(f'<div class="cell">{emblem_svg(t, 120)}<b>{t}</b><span>{SHORT[t]}</span></div>' for t in _ART)
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@700&display=swap">'
            '<style>body{margin:0;background:#f4efdf;font-family:"Zen Kaku Gothic New",sans-serif;padding:24px}h1{font:400 26px "Dela Gothic One",sans-serif;margin:0 0 16px}'
            '.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.cell{background:#fff;border:3px solid #14212c;padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:6px}'
            '.cell b{font-size:14px;text-align:center}.cell span{font-size:11px;color:#56636e}</style></head><body><h1>ミカタの「型」の紋章 12種(案)</h1>'
            f'<div class="grid">{cells}</div></body></html>')
