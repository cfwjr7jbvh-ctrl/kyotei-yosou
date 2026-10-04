#!/usr/bin/env bash
# 選手カード(DIR/cards/*.json、暗号化済み)だけの1コミットを cards ブランチに上書きで置く(履歴を積み上げない)。
# 使い方: bash scripts/push_cards.sh DIR
set -eu
DIR=$1
idx=$(mktemp)
GIT_INDEX_FILE=$idx git read-tree --empty
for f in "$DIR"/cards/*.json; do
  GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$(git hash-object -w "$f"),cards/$(basename "$f")"
done
tree=$(GIT_INDEX_FILE=$idx git write-tree)
rm -f "$idx"
c=$(echo "[CI Skip] cards $(TZ=Asia/Tokyo date +%m/%d)" | git commit-tree "$tree")
for i in 1 2 3; do
  if git push -q -f origin "$c:refs/heads/cards"; then echo "cards ブランチを更新"; exit 0; fi
  sleep $((i * 5))
done
exit 1
