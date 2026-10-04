#!/usr/bin/env bash
# main への push。ほかのジョブ(直前予想・学習・データ取得)と同時に push してもぶつからないよう、
# 取り込み直して数回やり直す。  使い方: bash scripts/push.sh
for i in 1 2 3 4 5 6; do
  if git pull --rebase -q origin main && git push -q origin HEAD:main; then
    exit 0
  fi
  git rebase --abort 2>/dev/null || true
  sleep $(( i * 5 + RANDOM % 5 ))
done
echo "push できませんでした" >&2
exit 1
