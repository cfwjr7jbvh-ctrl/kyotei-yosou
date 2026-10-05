"""X(旧Twitter)の文字数の数え方(重い依存なし。投稿のジョブからも読む)。"""


def xlen(text: str) -> int:
    """全角などは2、英数字・記号(半角カナを含む)は1。上限は280。"""
    return sum(1 if ord(ch) < 0x1100 or 0xFF61 <= ord(ch) <= 0xFF9F else 2 for ch in text)


def sim_words(r) -> str:
    """前半と後半の相関を、数字を使わない言葉に(読者には 0.92 のような数字を見せない)。"""
    if r is None or r != r:
        return "まだ分からない"
    if r >= 0.8:
        return "ほぼ同じ顔ぶれ"
    if r >= 0.5:
        return "だいたい同じ顔ぶれ"
    if r >= 0.2:
        return "少しは重なる"
    return "ほとんど入れ替わる"


def fun_rate(v) -> str:
    """割合を「3回に2回」のような言い方に(楽しく読める数字)。"""
    if v is None or v != v:
        return ""
    for a, b, w in ((0.9, 1.01, "ほぼ毎回"), (0.72, 0.9, "4回に3回"), (0.6, 0.72, "3回に2回"), (0.44, 0.6, "2回に1回"),
                    (0.28, 0.44, "3回に1回"), (0.2, 0.28, "4回に1回"), (0.0, 0.2, "5回に1回以下")):
        if a <= v < b:
            return w
    return ""
