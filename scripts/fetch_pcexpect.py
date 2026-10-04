"""公式サイトの「コンピュータ予想」(各艇の印・自信度・予想フォーカス)を過去レースの分も集める。

狙い(改良案 E1): 公式の予想フォーカスに入った組は、気軽に買う人が乗りやすく、オッズが下がりすぎている(買われすぎ)かもしれない。
過去オッズと突き合わせて確かめ、期待値の計算や買い目の選び方に活かす。印は特徴量の候補にもなる。

新しい日から順に、まだ取っていないレースを取得(1秒に1回以下)。保存先: data/pcexpect/pcx_YYYYMM.csv.gz
  列: race_id, marks(「枠:印」を「,」区切り。印 1=◎ 2=○ 3=▲ 4=△), conf(自信度 1〜5), focus2, focus3(「;」区切り)
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.scrape import fetch, parse_pcexpect  # noqa: E402

DIR = ROOT / "data/pcexpect"


def _load(p: pathlib.Path) -> pd.DataFrame:
    return pd.read_csv(p, dtype={"race_id": str, "marks": str, "focus2": str, "focus3": str})


def merge_from(src: pathlib.Path) -> int:
    added = 0
    for p in sorted(src.glob("pcx_*.csv.gz")):
        new = _load(p)
        dst = DIR / p.name
        old = _load(dst) if dst.exists() else new.iloc[:0]
        n = len(set(new["race_id"]) - set(old["race_id"]))
        if n == 0:
            continue
        added += n
        pd.concat([old, new]).drop_duplicates("race_id").sort_values("race_id").to_csv(dst, index=False, compression="gzip")
    return added


def todo_races(days: int) -> pd.DataFrame:
    races = pd.concat([pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id", "date", "jcd", "rno"])
                       for p in sorted((ROOT / "data/history").glob("races_*.csv.gz"))])
    dates = sorted(races["date"].unique())[-days:]
    races = races[races["date"].isin(dates)].sort_values("race_id", ascending=False)
    have = set()
    for p in DIR.glob("pcx_*.csv.gz"):
        have |= set(_load(p)["race_id"])
    return races[~races["race_id"].isin(have)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1200)
    ap.add_argument("--time-limit", type=float, default=3.0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--merge-from", default=None)
    ap.add_argument("--left", action="store_true")
    a = ap.parse_args()
    DIR.mkdir(parents=True, exist_ok=True)
    if a.merge_from:
        print(merge_from(pathlib.Path(a.merge_from)))
        return
    if a.left:
        print(len(todo_races(a.days)))
        return
    k, n = map(int, a.shard.split("/"))
    todo = todo_races(a.days).iloc[k::n]
    print(f"todo {len(todo)} races (shard {a.shard})")
    t0, buf = time.time(), []

    def flush():
        if not buf:
            return
        df = pd.DataFrame(buf)
        for ym, g in df.groupby(df["race_id"].str[:6]):
            p = DIR / f"pcx_{ym}.csv.gz"
            if p.exists():
                g = pd.concat([_load(p), g])
            g.drop_duplicates("race_id", keep="last").sort_values("race_id").to_csv(p, index=False, compression="gzip")
        buf.clear()

    for i, r in enumerate(todo.itertuples()):
        if time.time() - t0 > a.time_limit * 3600:
            break
        html = fetch("pcexpect", int(r.jcd), int(r.rno), r.race_id[:8], wait=1.0)
        x = parse_pcexpect(html) if html else None
        x = x or {"marks": {}, "conf": None, "focus2": [], "focus3": []}  # 取れなくても空行を入れて取り直さない
        buf.append({"race_id": r.race_id, "marks": ",".join(f"{l}:{m}" for l, m in sorted(x["marks"].items())),
                    "conf": x["conf"], "focus2": ";".join(x["focus2"]), "focus3": ";".join(x["focus3"])})
        if (i + 1) % 300 == 0:
            flush()
            print(i + 1, "races", f"{(time.time()-t0)/60:.0f}min", flush=True)
    flush()


if __name__ == "__main__":
    main()
