"""言葉の決まり(CLAUDE.md「言葉の決まり」・発信方針)の見張り。

2026-10-07 ユーザー「これ言い回し直ってなくない?」「なんでそういうことがおこるの?」:
決まりを変えたとき、共通の関数(lab._rate など)を通る文は直ったが、各ファイルに直接書いた文(ミカタ新聞の画像など)が古いまま残った。
→ 読者に見せる文字列(コメント・説明文字列を除く)を全部見て、決まりに合わない言い回しを見つける。

  python scripts/wording_check.py                  # scripts/ と src/kyotei/ を全部
  python scripts/wording_check.py scripts/foo.py   # 1ファイル(編集したときにフックが自動で走る)
  check_text(本文) → 問題のリスト(X に出す直前の確認にも使う)

その行だけ見逃すときは、行末に  # wording: ok  と書く(社内向けのログなど)。
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (正規表現, 直し方)。読者に見せる文字列に出てはいけない言い回し
RULES = [
    (r"100(回|レース|走)(中|で|あたり)", "率は「◯%」、差は「47%→66%に上がる」(「100レースで◯回」はもう使わない)"),
    (r"(ふつう|いつも)は\s*\{", "比べる相手は「ふだん」にそろえる(ふだんは◯%)"),
    (r"(ふつう|いつも)は\d", "比べる相手は「ふだん」にそろえる(ふだんは◯%)"),
    (r"こういう選手は|な人がいる|な選手がいる", "「特定の1人」に読まれない書き方: 「〜なタイプ(条件)は」+割合"),
    (r"験担ぎ|験かつぎ", "表記は「ゲンかつぎ」"),
    (r"3着内(?!容)", "表記は「3着以内」"),
    (r"織り込み済み|織り込まれ", "人気の言葉で: 人気どおり(配当は安め)"),
    (r"不安材料|凹み|凹む|弱点|弱いところ|苦手|不調|大敗|が負ける|負けたとき|負け方", "ネガティブな言い方はしない(2026-10-07 ユーザー)。挑む側の強み・「1号艇以外が勝つ」の言葉で"),
    (r"信頼区間|有意差|有意に|ノイズ", "統計の言葉は読者に見せない(「ブレの幅」「たまたまでも出るくらいの幅」)"),
    (r"あてにならない|(?<!天)気のせい", "否定的な言い切りはしない(「ふだんと同じ(差は出なかった)」「参考程度」)"),
]
# X など外に出す文だけの決まり(サイトの成績タブは自分たち用なので見ない)
PUBLIC_RULES = [
    (r"回収率|的中|儲かる|必ず|稼げる|高配当", "外に出す文には出さない(買い目を出す条件を満たしてユーザーが OK するまで)"),
]
SKIP_FILES = {"wording_check.py", "model_lab.py", "train_eval.py", "compare.py", "sim_st.py"}   # 社内向けの検証(読者に見せない)


def check_text(text: str, public: bool = True) -> list[str]:
    """本文に決まりに合わない言い回しがあれば、その説明のリスト(空なら問題なし)。"""
    out = []
    for pat, why in RULES + (PUBLIC_RULES if public else []):
        m = re.search(pat, text)
        if m:
            out.append(f"「{m.group(0)}」→ {why}")
    return out


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def check_file(path: pathlib.Path) -> list[str]:
    """ファイルの中の文字列(説明文字列とコメントは除く)を見る。"""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    docs = _docstring_ids(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        ln = getattr(node, "lineno", 0)
        if ln and "wording: ok" in lines[ln - 1]:
            continue
        # f文字列は部品に分かれるので、行そのもので確かめる(「{x}回(ふつうは{y}回)」のような書き方も拾う)
        text = lines[ln - 1] if isinstance(getattr(node, "parent", None), ast.JoinedStr) else node.value
        for msg in check_text(node.value, public=False):
            found.append(f"{path.relative_to(ROOT)}:{ln}: {msg}")
    for i, line in enumerate(lines, 1):   # f文字列の「{…}回(ふつうは{…}回)」は部品に分かれて拾えないので、行でも見る
        if "wording: ok" in line or line.lstrip().startswith("#"):
            continue
        if re.search(r"f[\"'].*\}回\((ふつう|いつも)は|f[\"'].*(ふつう|いつも)は\{", line):
            found.append(f"{path.relative_to(ROOT)}:{i}: 比べる相手は「ふだん」、率は「◯%」に")
    return sorted(set(found))


def check_js(path: pathlib.Path) -> list[str]:
    """アプリ(docs/*.js)の読者に見える文字。コメント(// の後ろ)は見ない。成績タブは中だけなので、外に出さない言葉は「儲か」だけ足して見る
    (2026-10-07: 荒れそうなレースの説明に「オッズに織り込まれて」「儲かるわけでは」が残っていた)。"""
    found = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code = re.sub(r"(^|[^:\\])//.*$", r"\1", line)
        if not code.strip() or "wording: ok" in line:
            continue
        for msg in check_text(code, public=False) + (["「儲か」→ 外に出す文には出さない"] if "儲か" in code else []):
            found.append(f"{path.relative_to(ROOT)}:{i}: {msg}")
    return found


def main(argv: list[str]) -> int:
    files = [pathlib.Path(a).resolve() for a in argv] if argv else \
        sorted(list((ROOT / "scripts").glob("*.py")) + list((ROOT / "src/kyotei").glob("*.py")))
    issues = []
    if not argv:
        files += sorted((ROOT / "docs").glob("*.js"))
    for f in files:
        if f.suffix == ".py" and f.name not in SKIP_FILES and f.exists():
            issues += check_file(f)
        elif f.suffix == ".js" and f.exists():
            issues += check_js(f)
    for x in issues:
        print(x)
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
