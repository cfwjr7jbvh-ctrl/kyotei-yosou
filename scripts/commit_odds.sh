#!/usr/bin/env bash
# data/odds を main に反映する。朝の予想と過去オッズ取得が同じ月のファイルに書くため、
# git の取り込み(rebase)だと圧縮ファイル同士がぶつかって push できず、取ったオッズが消えていた。
# 最新の main に取り直してから、手元で取ったオッズを足し合わせて push する。
# 使い方: bash scripts/commit_odds.sh "コミットの見出し"
set -u
SNAP=$(mktemp -d)
cp data/odds/odds3t_*.csv.gz "$SNAP/" 2>/dev/null || { echo "オッズなし"; exit 0; }
for i in 1 2 3 4 5 6; do
  if git fetch -q origin main && git reset -q --hard origin/main; then
    N=$(python scripts/fetch_odds.py --merge-from "$SNAP")
    git add data/odds
    if ! git commit -q -m "[CI Skip] data: ${1:-過去オッズ} +${N}レース"; then echo "no changes"; exit 0; fi
    if git push -q origin HEAD:main; then echo "pushed +${N} races"; exit 0; fi
  fi
  sleep $(( i * 5 + RANDOM % 5 ))
done
echo "push できませんでした" >&2
exit 1
