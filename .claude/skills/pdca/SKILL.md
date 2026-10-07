---
name: pdca
description: 検証ラボ_ストックの候補から理論を1本選び、数えて、モデルに入れるか決め、記録する。PDCA を1周回す。「次の理論を回して」「PDCA」と言われたら使う
---
# PDCA を1周回す

## Plan
0. まず reports/data_catalog.md の「データを待っているアイデア」で「検証できる」になったものがあれば、それを先に回す(データがそろうのを待っていた分)
1. プロジェクト文書「検証ラボ_ストック」の「候補(ネットの舟券理論から)」を読み、結果の書かれていない一番上の理論を選ぶ(ユーザーが指定したらそれ)
2. 必要なデータがあるか reports/data_catalog.md で確かめる。**無ければスキップしないで、集め始める**(2026-10-07 ユーザー「検証に追加のデータが必要なら収集をはじめ、過去に遡及して集められるなら集める」):
   - 出どころを決める(公式・気象庁・Open-Meteo など、読むだけの決まりを守れる所。ボートレース日和・住之江の公式・X は取らない)
   - scripts/fetch_<名前>.py と .github/workflows/<名前>.yml を作る(手本: scripts/fetch_tide.py と tide.yml。Actions のログは手元から読めないので、失敗の中身は `::warning::` の注釈と data/<名前>/_debug.txt に残す)。さかのぼれるなら 2023-10〜 を一括で、以後は定期で
   - scripts/data_catalog.py の DATASETS に1行、WAITING に「そろう条件」と判定を1行足す
   - 候補の行に【データ収集中: <名前>】と書いて、今日は次の候補へ(データがそろったら手順0で戻ってくる)
   - さかのぼれない(その場でしか取れない)ものは、保存だけ始めて「数か月後」と書く
3. 数え方を1〜3行で決める: 条件(mask)・比べる相手(ref)・何を数えるか(1号艇の1着 / その選手の3着以内 / 2着の枠 など)

## Do
4. scripts/lab.py の似た builder を Grep で探して読む(`^def t_` で一覧)。`measure()` と `verdicts()` の使い方は t_a1in / t_c1lose が手本
5. `t_<id>(ent, r)` を書き、BUILDERS に登録。返す dict の必須キー: id, title, belief, lead, conclusion, measures, rules, faq, use, mikata, gen, challenge。数字は `_rate()` / `_rate_change()` で(「100レースで◯回」は使わない)。読み手に「特定の1人の話」と思わせない(タイプ+割合)
6. `python -m py_compile scripts/lab.py` → `python scripts/lab.py --theory <id> --out /tmp/lab` → `/tmp/lab/lab_<id>.txt` と `_x.txt` を読んで、文がおかしくないか・数字が文と合っているかを確認

## Check
7. measures の verdicts を読む: real(本当にある)、edge(0 人気どおり / 1 人気以上 / -1 ひかえめ / None データ不足)、stable(前の2年と最近の1年で同じ向きか)
8. real かつ edge==1 なら: どの特徴量なら同じ情報になるかを src/kyotei/features.py で探す。無ければ特徴量の案を書く(exp/ ブランチで experiment.yml にかける。採用基準: 3連単の誤差の差の90%区間が0をまたがない)。すでにあるなら「校正の確認」を次の課題に
9. real だが edge==0 なら記事だけ。real でなければ「ふだんと同じ」の記事(オカルト枠の書き方: 掛け合いから入る HOOKS)

## Act
10. 検証ラボ_ストックの候補の行末に【本当・人気以上 → 特徴量候補】【本当・人気どおり → 記事】【ふだんと同じ】を書き、「そのあとのストック」か「オカルト枠」に1行足す。精度向上アイデアの J 系にも1項目
11. commit(reports/lab/<id>.json と lab.py)→ pull --rebase → push。ユーザーには3行で報告(結論・数字1つ・次に回す理論)
