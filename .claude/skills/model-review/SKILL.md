---
name: model-review
description: 予想モデルの改良案を1件えらんで exp/ ブランチに実装し、experiment.yml で前後比較にかける。前の実験の結果も記録する。「モデルの見直し」「実験を回して」と言われたとき、と毎朝の定期タスクで使う
---
# モデルの見直し(1回で実験1件)

2026-10-07 ユーザー「サイクルが長い理由は?」→ 2週間に1〜2件から、毎日1件に。
公開リポジトリなので Actions は無料。実験は1件1〜2.5時間かかり、experiment.yml は同時に1本しか動かない(concurrency)ので、1回の見直しで出すのは1件。

## 1. 前の実験の結果を記録する
1. `git pull --rebase origin main`
2. `gh run list --workflow experiment.yml -L 5` で、終わった実験を見る。`reports/experiments/<ブランチ名の / を _ に>_result.json` が判定(adopt、各誤差の差と90%区間)
3. reports/ideas.md のその案の行に【採用 MM/DD: 数字】か【不採用 MM/DD: 理由と数字】を書く。採用は experiment.yml が自動で main に入れる(手で入れ直さない)
4. 実験がまだ動いていたら、今回は新しい実験を出さない(2の記録と3の準備だけして終わる)

## 2. 次の案をえらぶ(上ほど先)
1. 検証ラボで「本当にある」かつ「人気以上に来る」(edge=1)と出た理論(プロジェクト文書「検証ラボ_ストック」の【本当・人気以上 → 特徴量候補】で、まだ実験していないもの)
2. reports/data_catalog.md の「データを待っているアイデア」で「検証できる」になったもの
3. 毎日の予想の外れ方(reports/review/YYYY-MM-DD.md)から作った案
4. reports/ideas.md の、結果の書かれていない ◎ → ○
- 重い・手間が大きい案は、先に手元の scripts/model_lab.py や scripts/quick_eval.py でふるい分けてよい(手元は8GB・2コア。重いものは1本ずつ)

## 3. 実装して出す
1. `git switch -c exp/YYYYMMDD-<短い名前>`。特徴量は src/kyotei/features*.py、学習は scripts/train_eval.py
2. 未来の情報を混ぜない(過去成績は前日まで、当日は締切前に分かるものだけ)。直前予想の特徴量は scripts/predict.py でも同じ値が入るか確かめる
3. `python -m py_compile` → 手元で小さく動かして列が埋まるか確認 → commit → `git push origin exp/...`
4. `gh api -X POST repos/cfwjr7jbvh-ctrl/kyotei-yosou/actions/workflows/experiment.yml/dispatches -f ref=main -f 'inputs[branch]=exp/...'`(`gh workflow run` は使えない)
5. reports/ideas.md のその案に【実験中: exp/...(run番号)】と書いて main に commit → pull --rebase → push

## 採用の基準(scripts/compare.py が判定)
直前の3連単誤差が0.002以上、または1着誤差が0.001以上よくなり、その差のレース単位の90%区間が0をまたがない。ほかの誤差が0.002を超えて悪くならない。

## 4. 記録と報告
- 結果はプロジェクト文書「精度向上アイデア」(= reports/ideas.md の写し)にも反映(project_read → 直す → project_write)
- 採らなかった案も理由つきで残す
- ユーザーへの報告は3行まで(前の実験の結果・今日出した案・次の候補)。採用があったときと、edge_status.json が変わったときだけ通知
