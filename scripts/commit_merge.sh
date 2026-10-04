#!/usr/bin/env bash
# 月ごとのデータファイル(過去オッズ・コンピュータ予想など)を main に反映する。
# 同じ月のファイルをほかのジョブも書くので、最新の main に取り直してから、取った分を足し合わせて push する。
# 使い方: bash scripts/commit_merge.sh "見出し" data/pcexpect "python scripts/fetch_pcexpect.py --merge-from"
set -u
MSG=$1; DIR=$2; MERGE=$3
SNAP=$(mktemp -d)
cp "$DIR"/*.csv.gz "$SNAP/" 2>/dev/null || { echo "データなし"; exit 0; }
for i in 1 2 3 4 5 6; do
  if git fetch -q origin main && git reset -q --hard origin/main; then
    N=$($MERGE "$SNAP")
    git add "$DIR"
    if ! git commit -q -m "[CI Skip] data: ${MSG} +${N}レース"; then echo "no changes"; exit 0; fi
    if git push -q origin HEAD:main; then echo "pushed +${N} races"; exit 0; fi
  fi
  sleep $(( i * 5 + RANDOM % 5 ))
done
echo "push できませんでした" >&2
exit 1
