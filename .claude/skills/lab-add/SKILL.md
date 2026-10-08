---
name: lab-add
description: 検証ラボ(scripts/lab.py)に理論を1本足すときの、builder の書き方と確認の手順。「検証ラボを足して」「lab.py に理論を追加」と言われたら使う
---
# 検証ラボを1本足す

- 手本: `t_a1in`(1号艇の1着・市場比)、`t_c1lose`(2着・3着の枠と市場比。3連単オッズから枠ごとの見込みを出す形)、`t_hot`(選手ごとの3着以内・no_market)、`t_lucky7`(オカルト枠・HOOKS に掛け合い)
- `measure(r, mask, ref=None, col="c1", qcol="q1")`: in1(率)・in1_ref・in1_ci・market_ratio(実際÷市場の見込み)・market_ref(比べる相手の比)・half(前半/後半の差)。選手単位で数えるときは `_adj(ent)` 系の列(res_own など)を見て、既存の builder と同じ列名を使う
- 返す dict の決まり:
  - `measures`: [(名前, m, verdicts(m)), ...]。名前は「条件」の名詞(「今節、2連勝中」「1号艇がA1」)。m に `ref_label`(比べる相手)、必要なら `subject`/`verb`/`unit`/`cu` を入れる
  - `lead`(くわしくの本文)/ `conclusion`([ハンコ, ひとこと])/ `use`(使いどころ。[0] は掛け合いで使われる)/ `rules`(ルールの説明)/ `faq`/ `mikata`(ミカタのひと言、X の最後の行にもなるので45字以内が望ましい)/ `gen`(ゲンさんの返し)/ `challenge`(今日のお題)
  - `x1`(任意): X の1行目。条件名が長い回だけ(例: slowdash)
  - オカルト枠は HOOKS[id] に掛け合い(lines)と X 用の2行(x)を足す
- **主語**: lead・conclusion の数字には「だれの・どのレースの」を毎回書く(「最終日の一般戦に出る選手は、その人のふだんとくらべて3着以内が…」)。1枚1ネタ(X 15:30)と投票に出すため、measures を足したら `NETA_SUBJ`(scripts/lab.py)に (id, かっこを除いた名前) → (主語つきの問い, 棒の名前, くらべる相手) を1行ずつ足す(無いと出ない)
- **6人みんなが同じ条件は選手全体で比べない**: 暑い日・初日・雨の日などはレースの6人とも同じなので、選手の3着以内は必ず半分になる(比べる意味がない)。1号艇の1着か、条件の中の一部のタイプ(50歳以上など)で比べる
- 数字の書き方: `_rate(v)`=「66%」、`_rate_change(this, ref, ref_label=...)`=「ふだんの51%→57%に上がる」、差だけしか無いときは「◯ポイント」。選手の数は `_n100` で「100人中◯人」。「100レースで◯回」は使わない
- 確認: `python -m py_compile scripts/lab.py` → `python scripts/lab.py --theory <id> --out /tmp/lab` → `/tmp/lab/lab_<id>.txt`(note)と `lab_<id>_x.txt`(X)を読む。文と数字の食い違い、「特定の1人」に読める表現、否定的な言い切りがないか
- 登録後、`reports/lab/<id>.json` ができる。theories.py(理論ぶつけ)に当てはめルールを足すなら `_m("<id>", i)` で measures の i 番目を読む
