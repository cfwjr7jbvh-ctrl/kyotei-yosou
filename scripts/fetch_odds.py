"""過去レースの締切時3連単オッズを公式サイトから集める(期待値の検証用)。

新しい日付から順に、まだオッズが無いレースを取得する。1秒に1回以下のアクセス。
保存先: data/odds/odds3t_YYYYMM.csv.gz (race_id, combo, odds)
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyotei.scrape import fetch, parse_odds3t  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ODDS = ROOT / "data/odds"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="直近何日分を対象にするか")
    ap.add_argument("--time-limit", type=float, default=5.0)
    a = ap.parse_args()
    ODDS.mkdir(parents=True, exist_ok=True)
    races = pd.concat([pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id", "date", "jcd", "rno"])
                       for p in sorted((ROOT / "data/history").glob("races_*.csv.gz"))])
    dates = sorted(races["date"].unique())[-a.days:]
    races = races[races["date"].isin(dates)].sort_values("race_id", ascending=False)
    have = set()
    for p in ODDS.glob("odds3t_*.csv.gz"):
        have |= set(pd.read_csv(p, dtype={"race_id": str}, usecols=["race_id"])["race_id"])
    todo = races[~races["race_id"].isin(have)]
    print(f"todo {len(todo)} races")
    t0 = time.time()
    buf = []

    def flush():
        if not buf:
            return
        df = pd.DataFrame(buf)
        for ym, g in df.groupby(df["race_id"].str[:6]):
            p = ODDS / f"odds3t_{ym}.csv.gz"
            if p.exists():
                g = pd.concat([pd.read_csv(p, dtype={"race_id": str}), g])
            g.drop_duplicates(["race_id", "combo"]).sort_values(["race_id", "combo"]).to_csv(
                p, index=False, compression="gzip")
        buf.clear()

    for i, r in enumerate(todo.itertuples()):
        if time.time() - t0 > a.time_limit * 3600:
            break
        html = fetch("odds3t", int(r.jcd), int(r.rno), r.race_id[:8], wait=1.0)
        odds = parse_odds3t(html) if html else {}
        if not odds:  # 中止レースなど。空行を入れて再取得を防ぐ
            odds = {"none": float("nan")}
        buf += [{"race_id": r.race_id, "combo": c, "odds": v} for c, v in odds.items()]
        if (i + 1) % 300 == 0:
            flush()
            print(i + 1, "races", f"{(time.time()-t0)/60:.0f}min", flush=True)
    flush()


if __name__ == "__main__":
    main()
