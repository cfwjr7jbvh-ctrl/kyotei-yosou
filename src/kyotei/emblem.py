"""「型」の紋章(ワッペン)。選手カードのタグの横・画像・新聞に付ける、うち独自の小さなマーク。

本人の顔(写真・似顔絵)はパブリシティ権の問題があるので使わない。代わりに「型」を絵にして、推しの型を集める楽しさを出す。
形: 盾型のワッペン。上の帯に型の短い名前、真ん中に絵(2色)、太い縁取り(刺繍っぽく)。viewBox 0 0 100 112。
"""
from __future__ import annotations

INK = "#14212c"
CREAM = "#f8f2df"
SHIELD = "M 50 4 L 92 14 L 92 58 C 92 84 72 100 50 108 C 28 100 8 84 8 58 L 8 14 Z"
# 型ごとの差し色(帯)と、絵の2色目
STYLE = {
    "スタート職人": ("#c8141c", "#ffd23f"), "展示STを信じていい": ("#0b5fb4", "#8ed0ff"), "本番で踏み込む": ("#e8571a", "#ffd23f"),
    "イン逃げ番長": ("#14212c", "#ffd23f"), "差し職人": ("#0b7a3b", "#bfe5c0"), "まくり屋": ("#c8141c", "#8ed0ff"),
    "まくり差しの職人": ("#7b3fb8", "#e6d3ff"), "外からでも届く": ("#0b5fb4", "#ffd23f"), "前づけの仕掛け人": ("#b8860b", "#fff0b3"),
    "展示は控えめ、本番で化ける": ("#7b3fb8", "#ffd23f"), "上り調子": ("#e8571a", "#8ed0ff"), "舟券に絡む安定感": ("#0b7a3b", "#ffd23f"),
}
SHORT = {"スタート職人": "ST職人", "展示STを信じていい": "展示", "本番で踏み込む": "踏込", "イン逃げ番長": "逃げ", "差し職人": "差し", "まくり屋": "まくり",
         "まくり差しの職人": "まく差", "外からでも届く": "外伸び", "前づけの仕掛け人": "前づけ", "展示は控えめ、本番で化ける": "化け", "上り調子": "上昇",
         "舟券に絡む安定感": "安定"}

# 絵(中央 50,66 のあたり、幅60くらい)。{c}=差し色 {c2}=2色目 {k}=墨
_ART = {
    # ストップウォッチ。針は12時ぴったり、まわりに「ピタッ」の火花
    "スタート職人": ('<circle cx="50" cy="68" r="21" fill="{c2}" stroke="{k}" stroke-width="4"/><circle cx="50" cy="68" r="15" fill="#fff" stroke="{k}" stroke-width="2.5"/>'
                 '<path d="M 50 47 L 50 40 M 43 40 L 57 40" stroke="{k}" stroke-width="4.5" stroke-linecap="round"/>'
                 '<path d="M 50 68 L 50 56" stroke="{c}" stroke-width="4" stroke-linecap="round"/><circle cx="50" cy="68" r="3" fill="{c}"/>'
                 '<path d="M 22 52 L 28 56 M 20 64 L 27 64 M 78 52 L 72 56 M 80 64 L 73 64" stroke="{c}" stroke-width="3.5" stroke-linecap="round"/>'),
    # 虫めがねで舟を見る(展示を見れば分かる)+チェック
    "展示STを信じていい": ('<circle cx="44" cy="64" r="17" fill="{c2}" stroke="{k}" stroke-width="4"/>'
                   '<path d="M 32 66 L 48 66 L 56 62 L 48 58 Z" fill="{k}"/>'
                   '<path d="M 57 76 L 70 89" stroke="{k}" stroke-width="7" stroke-linecap="round"/>'
                   '<path d="M 62 46 L 68 52 L 80 40" fill="none" stroke="{c}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 舟がラインを突き抜ける、後ろに炎
    "本番で踏み込む": ('<path d="M 58 44 L 58 90" stroke="{k}" stroke-width="3.5" stroke-dasharray="6 5" stroke-linecap="round"/>'
                 '<path d="M 24 60 C 30 58 36 56 42 56 L 46 56 L 46 76 L 42 76 C 36 76 30 74 24 72 Z" fill="{c}" stroke="{k}" stroke-width="3"/>'
                 '<path d="M 46 56 L 70 60 L 80 66 L 70 72 L 46 76 Z" fill="{c2}" stroke="{k}" stroke-width="3.5" stroke-linejoin="round"/>'
                 '<path d="M 24 66 L 10 60 L 18 66 L 8 72 L 22 70 Z" fill="{c}"/>'),
    # 王冠をのせた「1」がブイのそばで小さく回る
    "イン逃げ番長": ('<circle cx="70" cy="70" r="8" fill="{c2}" stroke="{k}" stroke-width="3"/>'
                 '<path d="M 20 84 L 52 84 A 14 14 0 0 0 52 56 L 40 56" fill="none" stroke="{k}" stroke-width="6" stroke-linecap="round"/>'
                 '<path d="M 40 48 L 34 56 L 40 64" fill="none" stroke="{k}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                 '<path d="M 20 48 L 24 34 L 32 42 L 38 30 L 44 42 L 52 34 L 56 48 Z" fill="{c2}" stroke="{k}" stroke-width="3" stroke-linejoin="round"/>'),
    # 外の艇が膨らんだ内側を、刃のような矢で刺す
    "差し職人": ('<path d="M 18 86 L 54 86 A 24 24 0 0 0 54 38 L 44 38" fill="none" stroke="{c2}" stroke-width="7" stroke-linecap="round"/>'
             '<path d="M 18 86 L 54 86 A 24 24 0 0 0 54 38 L 44 38" fill="none" stroke="{k}" stroke-width="3" stroke-dasharray="1 7" stroke-linecap="round"/>'
             '<path d="M 22 72 L 54 72 A 10 10 0 0 0 54 52 L 46 52" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
             '<path d="M 50 44 L 40 52 L 50 60 Z" fill="{c}" stroke="{c}" stroke-width="2" stroke-linejoin="round"/>'),
    # 大きな波しぶきの矢で外から一気に
    "まくり屋": ('<path d="M 24 86 L 58 86 A 26 26 0 0 0 58 34 L 46 34" fill="none" stroke="{c}" stroke-width="8" stroke-linecap="round"/>'
            '<path d="M 50 24 L 40 34 L 50 44" fill="none" stroke="{c}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M 26 70 L 50 70 A 10 10 0 0 0 50 50" fill="none" stroke="{k}" stroke-width="3.5" stroke-opacity=".5" stroke-linecap="round"/>'
            '<path d="M 72 38 C 78 40 82 46 80 52 M 78 30 C 86 34 90 42 88 50" fill="none" stroke="{c2}" stroke-width="3.5" stroke-linecap="round"/>'),
    # 2艇の間を縫う S の線
    "まくり差しの職人": ('<path d="M 18 48 L 44 48 M 18 80 L 44 80" stroke="{k}" stroke-width="7" stroke-opacity=".35" stroke-linecap="round"/>'
                 '<path d="M 14 64 C 36 64 36 40 56 40 C 72 40 78 50 78 64 C 78 78 70 86 56 86" fill="none" stroke="{c}" stroke-width="6.5" stroke-linecap="round"/>'
                 '<path d="M 64 78 L 54 86 L 64 94" fill="none" stroke="{c}" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/>'
                 '<circle cx="56" cy="40" r="4" fill="{c2}" stroke="{k}" stroke-width="2"/>'),
    # 6本のレーン、いちばん外の「6」から真ん中へ長く届く矢
    "外からでも届く": ('<path d="M 20 40 L 20 88 M 31 40 L 31 88 M 42 40 L 42 88 M 53 40 L 53 88 M 64 40 L 64 88" stroke="{k}" stroke-width="2.5" stroke-opacity=".35"/>'
                '<circle cx="74" cy="80" r="9" fill="{c2}" stroke="{k}" stroke-width="3"/><text x="74" y="85" font-family="Dela Gothic One, sans-serif" font-size="13" fill="{k}" text-anchor="middle">6</text>'
                '<path d="M 74 70 L 74 54 L 26 54" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                '<path d="M 34 46 L 24 54 L 34 62" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'),
    # 外の枠から内へ、スタート前に斜めに入る(点線のラインの手前で)
    "前づけの仕掛け人": ('<path d="M 18 40 L 82 40" stroke="{k}" stroke-width="3.5" stroke-dasharray="6 5" stroke-linecap="round"/>'
                 '<circle cx="76" cy="84" r="7" fill="{c2}" stroke="{k}" stroke-width="3"/>'
                 '<path d="M 70 80 L 38 58" stroke="{c}" stroke-width="7" stroke-linecap="round"/>'
                 '<path d="M 38 72 L 34 55 L 51 54" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
                 '<circle cx="26" cy="48" r="7" fill="{c}" stroke="{k}" stroke-width="3"/>'),
    # さなぎ(小さい丸)から、ちょうちょ
    "展示は控えめ、本番で化ける": ('<ellipse cx="26" cy="80" rx="6" ry="9" fill="{c2}" stroke="{k}" stroke-width="3"/>'
                       '<path d="M 32 72 C 40 64 48 60 56 58" fill="none" stroke="{k}" stroke-width="2.5" stroke-dasharray="3 4" stroke-linecap="round"/>'
                       '<path d="M 62 56 C 50 40 36 48 46 58 C 36 66 50 76 62 62 Z" fill="{c}" stroke="{k}" stroke-width="3" stroke-linejoin="round"/>'
                       '<path d="M 62 56 C 74 40 88 48 78 58 C 88 66 74 76 62 62 Z" fill="{c}" stroke="{k}" stroke-width="3" stroke-linejoin="round"/>'
                       '<path d="M 62 50 L 62 68" stroke="{k}" stroke-width="4" stroke-linecap="round"/><circle cx="56" cy="52" r="3" fill="{c2}"/><circle cx="68" cy="52" r="3" fill="{c2}"/>'),
    # ロケットみたいに右肩上がり
    "上り調子": ('<path d="M 14 88 L 86 88" stroke="{k}" stroke-width="3.5" stroke-linecap="round"/>'
             '<path d="M 18 82 L 34 66 L 46 74 L 64 50" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="M 56 42 L 76 36 L 70 56 Z" fill="{c}" stroke="{k}" stroke-width="3" stroke-linejoin="round"/>'
             '<path d="M 22 50 L 30 50 M 18 58 L 26 58" stroke="{c2}" stroke-width="4" stroke-linecap="round"/>'),
    # いかり(安定)と3段の台
    "舟券に絡む安定感": ('<path d="M 14 88 L 14 70 L 34 70 L 34 88 M 34 88 L 34 56 L 58 56 L 58 88 M 58 88 L 58 76 L 80 76 L 80 88 M 10 88 L 88 88" fill="none" stroke="{k}" stroke-width="3.5" stroke-linejoin="round"/>'
                 '<path d="M 46 30 L 46 50 M 38 36 L 54 36 M 34 44 C 36 52 42 54 46 54 C 50 54 56 52 58 44" fill="none" stroke="{c}" stroke-width="4.5" stroke-linecap="round"/>'
                 '<circle cx="46" cy="27" r="3.5" fill="none" stroke="{c}" stroke-width="3"/>'
                 '<path d="M 66 40 L 72 46 L 84 34" fill="none" stroke="{c2}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'),
}


def emblem_svg(tag: str, size: int = 40, cls: str = "emb") -> str:
    """型の紋章。知らないタグなら空文字。size は幅(高さは 1.12 倍)。"""
    art = _ART.get(tag)
    if not art:
        return ""
    c, c2 = STYLE.get(tag, (INK, "#ffd23f"))
    uid = f"em{abs(hash(tag)) % 100000}{size}"
    return (f'<svg class="{cls}" viewBox="0 0 100 112" width="{size}" height="{round(size * 1.12)}" role="img" aria-label="{tag}の紋章">'
            f'<defs><clipPath id="{uid}"><path d="{SHIELD}"/></clipPath></defs>'
            f'<path d="{SHIELD}" fill="{CREAM}" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
            f'<g clip-path="url(#{uid})"><rect x="0" y="0" width="100" height="30" fill="{c}"/>'
            f'<text x="50" y="25" font-family="Dela Gothic One, sans-serif" font-size="15" fill="#fff" text-anchor="middle">{SHORT.get(tag, "")}</text>'
            + art.format(c=c, c2=c2, k=INK) + "</g>"
            f'<path d="{SHIELD}" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
            f'<path d="M 50 9 L 87 18 L 87 57 C 87 80 69 95 50 102 C 31 95 13 80 13 57 L 13 18 Z" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="3 3" stroke-opacity=".9"/>'
            "</svg>")


def sheet_html() -> str:
    """12個を並べた見本(確認用)。"""
    cells = "".join(f'<div class="cell">{emblem_svg(t, 128)}<b>{t}</b></div>' for t in _ART)
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@700&display=swap">'
            '<style>body{margin:0;background:#f4efdf;font-family:"Zen Kaku Gothic New",sans-serif;padding:24px}h1{font:400 26px "Dela Gothic One",sans-serif;margin:0 0 16px}'
            '.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.cell{background:#fff;border:3px solid #14212c;padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:8px}'
            '.cell b{font-size:13.5px;text-align:center}</style></head><body><h1>ミカタの「型」の紋章 12種(第2案: 盾のワッペン)</h1>'
            f'<div class="grid">{cells}</div></body></html>')
