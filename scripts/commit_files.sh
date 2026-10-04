#!/usr/bin/env bash
# そのジョブだけが書くファイル(レポートなど)を main に反映する。
# 取り込み(rebase)だと、別のジョブが同じファイルを同時に書き換えたときにぶつかって push できず、結果が消える。
# 最新の main に取り直してから、このジョブの結果で上書きして push する(最大6回やり直し)。
# 使い方: bash scripts/commit_files.sh "コミットの見出し" ファイル...
set -u
MSG=$1; shift
SNAP=$(mktemp -d)
for f in "$@"; do
  [ -e "$f" ] && mkdir -p "$SNAP/$(dirname "$f")" && cp -a "$f" "$SNAP/$f"
done
for i in 1 2 3 4 5 6; do
  if git fetch -q origin main && git reset -q --hard origin/main; then
    for f in "$@"; do
      [ -e "$SNAP/$f" ] && mkdir -p "$(dirname "$f")" && cp -a "$SNAP/$f" "$f" && git add "$f"
    done
    if ! git commit -q -m "$MSG"; then echo "no changes"; exit 0; fi
    if git push -q origin HEAD:main; then echo "pushed"; exit 0; fi
  fi
  sleep $(( i * 5 + RANDOM % 5 ))
done
echo "push できませんでした" >&2
exit 1
