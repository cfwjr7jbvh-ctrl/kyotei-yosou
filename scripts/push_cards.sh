#!/usr/bin/env bash
# cards ブランチ(履歴を積み上げない、1コミットだけのブランチ)に、DIR の中の指定した場所(cards/ や ura/)を上書きで置く。
# ほかの場所のファイルは、いまの cards ブランチのものをそのまま残す(選手カードと記事の下書きは別のジョブが書くため)。
# 使い方: bash scripts/push_cards.sh DIR [cards] [ura]   (場所を省くと DIR の中の全部)
set -eu
DIR=$1; shift
SUBS=("$@")
if [ ${#SUBS[@]} -eq 0 ]; then
  SUBS=()
  for d in "$DIR"/*/; do SUBS+=("$(basename "$d")"); done
fi
for i in 1 2 3; do
  idx=$(mktemp)
  if git fetch -q origin cards 2>/dev/null; then
    GIT_INDEX_FILE=$idx git read-tree FETCH_HEAD
    for s in "${SUBS[@]}"; do
      GIT_INDEX_FILE=$idx git ls-files --cached "$s/" | xargs -r -d '\n' env GIT_INDEX_FILE=$idx git rm -q --cached -- || true
    done
  else
    GIT_INDEX_FILE=$idx git read-tree --empty
  fi
  for s in "${SUBS[@]}"; do
    for f in "$DIR/$s"/*.json; do
      [ -e "$f" ] || continue
      GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$(git hash-object -w "$f"),$s/$(basename "$f")"
    done
  done
  tree=$(GIT_INDEX_FILE=$idx git write-tree)
  rm -f "$idx"
  c=$(echo "[CI Skip] cards $(TZ=Asia/Tokyo date +%m/%d) ${SUBS[*]}" | git commit-tree "$tree")
  if git push -q -f origin "$c:refs/heads/cards"; then echo "cards ブランチを更新(${SUBS[*]})"; exit 0; fi
  sleep $((i * 5))
done
exit 1
