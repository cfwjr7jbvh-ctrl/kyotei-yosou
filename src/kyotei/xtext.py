"""X(旧Twitter)の文字数の数え方(重い依存なし。投稿のジョブからも読む)。"""


def xlen(text: str) -> int:
    """全角などは2、英数字・記号(半角カナを含む)は1。上限は280。"""
    return sum(1 if ord(ch) < 0x1100 or 0xFF61 <= ord(ch) <= 0xFF9F else 2 for ch in text)
