#!/usr/bin/env bash
# .py を Edit/Write したら、その場で構文を確かめる(PostToolUse)。失敗したら Claude に知らせる(exit 2)。
input=$(cat)
f=$(echo "$input" | jq -r '.tool_input.file_path // empty')
case "$f" in
  *.py)
    if ! out=$(python -m py_compile "$f" 2>&1); then
      echo "py_compile に失敗: $f" >&2
      echo "$out" >&2
      exit 2
    fi
    ;;
esac
exit 0
