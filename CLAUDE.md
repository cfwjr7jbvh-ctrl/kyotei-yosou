# ミカタ(kyotei-yosou)— Claude への申し送り

競艇(ボートレース)を「いろんな角度から」見る材料を作るプロジェクト。予想モデル・毎日の記事・X の自動投稿・検証ラボ(ネットの「◯◯理論」をデータで確かめる)・note の特集号。
ゴールは、予想モデルを毎日よくして、いずれ**自信を持って買い目を出す**こと(2026-10-07 ユーザー)。それまで(reports/edge_status.json の edge が false の間)は、外に出すのは買い目ではなく「予想が楽しくなる材料」。合格ライン・出し方は下の「買い目を出す条件」。くわしい方針は claude.ai のプロジェクト「ミカタ」の文書(発信方針・検証ラボ_ストック・精度向上アイデア・市場分析_毎日)。セッションの最初に、関係する文書を読む。

## 回し方(PDCA。ユーザー: 「ネットの舟券理論を片っ端から検証してモデル改善に」「毎日分析」)
1. **Plan**: `reports/review/candidates.md`(プロジェクト文書「検証ラボ_ストック」の候補と同じ)の上から未着手を1本。市場の言葉(reports/market/latest.json)で急に増えた言葉も候補に
2. **Do**: scripts/lab.py に builder `t_<id>` を足し BUILDERS に登録 → `python scripts/lab.py --theory <id> --out /tmp/lab`(2〜3分)→ 文面と数字を確認
3. **Check**: 3つの物差し ①本当にある(real) ②人気どおりか(edge: 0=人気どおり、1=人気以上、-1=ひかえめ) ③来年も同じか(stable)。①かつ②=1 のときだけ src/kyotei/features.py の特徴量候補にして experiment.yml(train_eval の前後比較、90%区間が0をまたがないこと)で試す。①だけなら記事のネタ
4. **Act**: 結果を検証ラボ_ストック(候補の行に【本当/ウソ/人気どおり】)と精度向上アイデア(J 系)に書く。記事は火・金 20:00 の X と記事タブに自動で出る
- 1周したら次の候補へ。止まらない。判断に迷うことだけユーザーに聞く(取り返しのつかないこと以外は進めて、あとで報告)
- 検証ラボのネタだけでなく、毎日の予想の外れ方(reports/review/YYYY-MM-DD.md)からも改善候補を作る。採らなかった案も理由つきで精度向上アイデアに残す

## 買い目を出す条件(ゴール。2026-10-07 ユーザー「ゆくゆくは自信を持って買い目も出したい」)
- 合格ライン: `scripts/edge_check.py` → `reports/edge_status.json` の edge が true(学習に使っていない期間で、本番の買い方の回収率の90%区間の下限が100%超え、300点以上。荒れ狙いは追試合格+同じ条件)
- 合格しても自動では出さない。ユーザーに数字を見せて OK をもらってから切り替える
- 出すときの約束: 合格した買い方の条件のレースだけ/出した買い目は外れも含めて全部、出す前の時刻つきで残して公開(後から消さない・選ばない)/見込みは幅で/「必ず」「儲かる」「高配当」は合格後も使わない(公営競技の広告指針)/edge が false に戻ったらすぐ止めて、そう書く
- 合格前の準備としてやってよいこと: 本番の買い方での追跡(中だけ)、記録の仕組み、公開リポジトリの扱いの見直し案

## よく使うコマンド
- 検証ラボ1本: `python scripts/lab.py --theory a1in --out /tmp/lab` / 一覧: `--list` / 全部: `--theory all`(約40分。Actions の lab.yml は毎週火曜 7:50 に全部作り直す)
- X の文面の確認(JSON から): `python -c "import sys;sys.path+=['scripts','src'];import lab;from kyotei.publish import load_private;t=load_private('reports/lab/a1in.json');print(lab.x_text(t,[{'venue':'住之江','rno':11,'lanes':[1],'deadline':'20:15'}]))"`
- 予想屋の回収率: `python scripts/tipster_track.py --luck`(運だけの表)/ `data/tipsters/picks.csv` を書いて `python scripts/tipster_track.py`
- 市場の言葉(Actions でだけ動く。手元は外に出られない): `python scripts/market_words.py`
- 構文確認: `python -m py_compile scripts/lab.py`(.py を編集したらフックが自動で走る)
- モデルの前後比較: Actions の experiment.yml(手元は8GB・2コアなので重い実験は1本ずつ)
- 新しい/直した理論を本番(暗号化された reports/lab)に出す: builder を push してから `gh api -X POST repos/cfwjr7jbvh-ctrl/kyotei-yosou/actions/workflows/lab.yml/dispatches -f ref=main -f 'inputs[theory]=<id>'`(`gh workflow run` は GraphQL が使えず失敗する。REST で)。ワークフローの起動・確認は `gh api` / `gh run list --workflow <file>`
- PDCA の待ち行列: `reports/review/candidates.md`(回したら [x] と結果)。毎朝の振り返り: `reports/review/YYYY-MM-DD.md`

## 場所
- `scripts/lab.py`(312KB、Read で全部は開けない → Grep で関数を探してから Read offset/limit): 検証ラボ。`measure()` が率・市場比・前半後半、`verdicts()` が3つの物差し、`page()/note_text()/x_text()/neta_text()` が出力。数字の書き方は `_rate/_rate_change/_is_rate`
- `scripts/ura_auto.py`: 毎朝7:40、記事タブと「今日のX投稿」(ura/xpost_YYYYMMDD.json の queue)を作る。`theory_hits()` が「今日なら◯◯R」
- `scripts/x_post.py`: 時間ごとに queue を X に投げる(8:20 理論ぶつけ / 12:10 荒れそう / 15:30 1枚1ネタ / 20:00 検証ラボ or 注目選手 / 21:30 投票 / ミカタ新聞は締切前)。`x_due.py` が時間の判定
- `scripts/theory_daily.py` + `src/kyotei/theories.py`: 毎日の「理論ぶつけ」(レースに検証ラボの理論を札つきで当てる。数字は reports/lab/*.json から)
- `scripts/predict.py`(予想) / `scripts/train_eval.py`(学習と検証) / `src/kyotei/features*.py`(特徴量) / `scripts/compare.py`(採否の判定)
- `scripts/market_words.py` → `reports/market/`(毎朝6:05)。`scripts/tipster_track.py`(予想屋の追跡)
- データ: `data/history/{entries,races}_YYYYMM.csv.gz`(2023-10〜)、`data/odds/odds3t_YYYYMM.csv.gz`(3連単の最終オッズ、2025-12〜ほぼ全部)、`data/weather`、`data/previews`
- 出力: `reports/lab/*.json`(検証ラボの本文。**2026-10-07 から暗号化**(パクられ対策)。読み書きは必ず `kyotei.publish.load_private / save_private`。手元は鍵が無いので、手元で作った分は `out/private/reports/lab/` にだけ入る=commit されない。新しい理論を本番に出すには builder を push して Actions の lab.yml を theory 指定で回す)、`reports/x_drafts/`(X の下書きと posted.json)、`docs/data/days/*.json`(その日の予想。**暗号化。手元では読めない**: SITE_PASSWORD は GitHub Secrets だけ。`InvalidTag` はそれが原因で、バグではない)

## 言葉の決まり(記事・X・アプリ全部)
- レースの結果は **「◯%」**。差は **「47%→66%に上がる」**(何%が何%まで)。両方の値が無いときだけ「◯ポイント」。選手の数は「100人中◯人」。出目など、めったに無いことは「1000レースで◯回」。「100レースで◯回」はもう使わない
- 「特定の1人」に読まれない書き方: 「〜な人がいる」ではなく「〜なタイプ(条件)」+割合(「B1の1号艇のうち3%」)
- オッズの話は「人気」の言葉で: 人気どおり(配当は安め)/人気以上に来る/人気のわりにひかえめ/人気から考えると◯%→実際◯%。「オッズに織り込み済み」は使わない
- 統計の言葉(信頼区間・相関・有意・ノイズ)は読者に見せない。「ブレの幅」「たまたまでも出るくらいの幅」「ほぼ同じ顔ぶれ」
- 表記: ゲンかつぎ(験担ぎは×)、3着以内(3着内は×)、インに有利/不利(追い風・向かい風は風の話とまぎれるので×)、ST は「.15」でもよい(市場の表記)
- 否定的な言い切りはしない: 「気のせい」「あてにならない」→「ふだんと同じ(差は出なかった)」「参考程度」。選手をけなさない(不利な話は名前を出さず艇番だけ)
- **出さないもの(いま。買い目は上の条件を満たしてユーザーが OK するまで)**: 買い目(3連単の組)・的中・回収率・配当の額・「必ず」「儲かる」。「狙い目かも(見込み◯%、ふだんの◯倍)」は可。公式の出走表・オッズ・写真の転載はしない。X の投稿の本文は公開リポジトリに残さない(言葉の回数だけ)
- **X の画像は記事の紙面を撮らない**(スマホで文字が5pxになる。2026-10-07 ユーザー「画像にすると読みづらい」)。`src/kyotei/xcard.py` の専用カード(1080×1350、いちばん小さい文字34px、主役の数字64px以上、載せるのは場名+R/結論/数字2つ/問いまで)。新しい投稿の種類を足すときもカードを作り、`python -c` で描いてスマホの実寸(幅375)に縮めて目で確かめる
- X の作り(市場に合わせる): 1行目は数字つきの言い切り(ミカタの口調にしない)→ 結論 → 今日なら◯◯R(締切)→ 最後だけミカタのひと言(「こういう見方もあるよ」)。ゲンさんのセリフは画像の中。場名+R+締切は市場の1行目の型。タグは #競艇 #ボートレース(+場名)

## キャラ
- **ミカタ**: カモメの記者(赤い輪)。データにくわしい、舟券はよく外す、選手の悪口は言わない、予想は押しつけない。口ぐせ「こういう見方もあるよ」
- **ゲンさん**: ゲンかつぎ歴40年の大先輩(青い輪、ハンチングとストップウォッチ)。「だろ?」「〜なんだよ」。説を持ち込み、ミカタが数える。オカルトは楽しみ方として肯定的に

## 作業の約束
- 変更したら `py_compile` → 1本だけ再生成して文面を目で確認 → commit → `git pull --rebase origin main` → push。Actions のジョブも main に書くので、push が拒否されたら rebase(force push はしない)。止まる前に未コミットがあると stop フックが止める
- Actions 側のファイル(reports/, data/)は `scripts/commit_files.sh` がジョブごとに上書き commit する。手元で同じファイルを触るときは最新の main に合わせてから
- 「未来の情報を混ぜない」(過去成績は前日まで、当日は締切前に分かるものだけ)。直前予想の特徴量は predict.py でも同じ値が入るか確認
- バックグラウンドの `python scripts/lab.py ...` の生死は `pgrep -f "python scripts/lab.py"` ではなく出力ファイルの数で見る(pgrep は自分のシェルに当たる)
- 大きな書き換えは Python の文字列置換スクリプトでまとめて(Edit を何十回も叩かない)。置換前に `assert a in s` で取りこぼしを見つける
- 返事は短く、決めてほしいことは最後に番号で。ユーザーは夜に短いメッセージをたくさん送る。途中で来た指示は、いまの作業を壊さない形で取り込む
