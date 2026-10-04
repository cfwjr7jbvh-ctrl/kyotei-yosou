#!/usr/bin/env bash
# 直前予想を一定間隔で更新し続ける。GitHub の定期実行は遅れたり飛んだりするので、1回の起動で長く動かす。
#   bash scripts/live_loop.sh [最長の分数=340] [間隔の秒数=300]
#
# - 予想ファイル(当日分)は live ブランチに上書きで置く(履歴を積み上げない・サイトを作り直さない)。
#   サイトは /api/data 経由で live ブランチ → main の順に読む
# - 直前情報・締切前オッズ(日ごとのファイル)は、1時間ごとと最後に main へ保存する
# - main の朝の予想が作り直されたら、それに live ブランチの直前予想を重ねてから更新する
set -u
MAX_MIN=${1:-340}
INTERVAL=${2:-300}
END=$(( $(date +%s) + MAX_MIN * 60 ))
SAVE_EVERY=3600
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
KEEP=$(mktemp -d)
MODEL_SHA=$(git ls-remote origin refs/heads/model | cut -f1)  # setup で読み込み済みのモデル
LAST_SAVE=$(date +%s)

jst() { TZ=Asia/Tokyo date "$@"; }

keep_files() {   # このジョブが書く日ごとのデータを退避(main に合わせ直しても消えないように)
  local d; d=$(jst +%Y%m%d)
  cp -f "data/previews/own_$d.csv.gz" "$KEEP/" 2>/dev/null || true
  cp -f "data/odds_live/live_$d.csv.gz" "$KEEP/" 2>/dev/null || true
}
restore_files() {
  local d; d=$(jst +%Y%m%d)
  mkdir -p data/previews data/odds_live
  cp -f "$KEEP/own_$d.csv.gz" data/previews/ 2>/dev/null || true
  cp -f "$KEEP/live_$d.csv.gz" data/odds_live/ 2>/dev/null || true
}
history_finishing() {  # 過去データ取得の最後の保存(やり直しなし)とぶつからないよう、終わり際は main への保存を控える
  gh run list --workflow history.yml --status in_progress --json createdAt \
    --jq "[.[] | select((now - (.createdAt | fromdateiso8601)) > 18000)] | length" 2>/dev/null | grep -qv '^0$'
}
save_data() {
  local d; d=$(jst +%Y%m%d)
  if history_finishing; then echo "過去データ取得の終わり際なので保存は次回"; return; fi
  git add "data/previews/own_$d.csv.gz" "data/odds_live/live_$d.csv.gz" 2>/dev/null || true
  if git commit -qm "[CI Skip] data: 直前情報・締切前オッズ $(jst +%H:%M)"; then
    bash scripts/push.sh && LAST_SAVE=$(date +%s)
  else
    LAST_SAVE=$(date +%s)
  fi
}
publish_live() {  # 当日(と前日)の予想ファイルだけの1コミットを live ブランチに上書き
  local today=$1 yday=$2 idx tree c
  idx=$(mktemp)
  GIT_INDEX_FILE=$idx git read-tree --empty
  if git cat-file -e "origin/live:days/$yday.json" 2>/dev/null; then
    GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$(git rev-parse "origin/live:days/$yday.json"),days/$yday.json"
  fi
  GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$(git hash-object -w "docs/data/days/$today.json"),days/$today.json"
  tree=$(GIT_INDEX_FILE=$idx git write-tree)
  rm -f "$idx"
  c=$(echo "[CI Skip] live $(jst +%H:%M)" | git commit-tree "$tree")
  git push -q -f origin "$c:refs/heads/live" && echo "live: $(jst +%H:%M) を公開"
}

while [ "$(date +%s)" -lt "$END" ]; do
  T0=$(date +%s)
  if [ "$(jst +%H%M)" -ge 2340 ]; then echo "今日のレースは終了"; break; fi
  TODAY=$(jst +%F)
  YDAY=$(jst -d '1 day ago' +%F)

  # 最新の main に合わせる(朝の予想の作り直し・コードの更新を取り込む)。自分のデータは退避して戻す
  keep_files
  git fetch -q origin main && git reset -q --hard origin/main
  git fetch -q origin live 2>/dev/null && git update-ref refs/remotes/origin/live FETCH_HEAD
  restore_files

  # 新しいモデルが学習されていたら読み込み直す
  SHA=$(git ls-remote origin refs/heads/model | cut -f1)
  if [ -n "$SHA" ] && [ "$SHA" != "$MODEL_SHA" ]; then
    git fetch -q --depth 1 origin model && git show FETCH_HEAD:bundle.pkl.enc > "$KEEP/bundle.pkl.enc" \
      && python src/kyotei/publish.py decrypt "$KEEP/bundle.pkl.enc" models/bundle.pkl && MODEL_SHA=$SHA \
      && echo "新しいモデルを読み込みました"
  fi

  # 朝の予想・当日の特徴量が無ければ作る(朝のジョブが遅れている場合。作ったものは使い回す)
  if [ ! -f "docs/data/days/$TODAY.json" ]; then
    if [ -f "$KEEP/morning_$TODAY.json" ]; then
      cp "$KEEP/morning_$TODAY.json" "docs/data/days/$TODAY.json"
    else
      python scripts/predict.py morning && cp "docs/data/days/$TODAY.json" "$KEEP/morning_$TODAY.json" || true
    fi
  fi
  if [ ! -f "data/cache/features_$TODAY.pkl" ]; then
    python scripts/predict.py features || true
  fi

  if [ -f "docs/data/days/$TODAY.json" ]; then
    if git cat-file -e "origin/live:days/$TODAY.json" 2>/dev/null; then
      git show "origin/live:days/$TODAY.json" > "$KEEP/prev.json"
      python scripts/predict.py merge-live "$KEEP/prev.json" || true
    fi
    python scripts/predict.py live || true
    publish_live "$TODAY" "$YDAY" || echo "live ブランチへの公開に失敗(次回やり直し)"
  fi

  if [ $(( $(date +%s) - LAST_SAVE )) -ge "$SAVE_EVERY" ]; then
    keep_files
    git fetch -q origin main && git reset -q --hard origin/main
    restore_files
    save_data
  fi

  WAIT=$(( INTERVAL - ($(date +%s) - T0) ))
  [ "$WAIT" -gt 0 ] && [ $(( $(date +%s) + WAIT )) -lt "$END" ] && sleep "$WAIT"
done

# 最後に日ごとのデータを main に保存
keep_files
git fetch -q origin main && git reset -q --hard origin/main
restore_files
save_data
