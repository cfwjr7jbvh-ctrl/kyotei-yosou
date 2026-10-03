"""保存済みの過去データに、競走成績から「レースタイム」「全券種の払戻・人気」を追加する(成績だけ取り直す)。

  python scripts/refresh_results.py --time-limit 4.5

2026-10-04 より前に取得した日は、成績の読み取りがレースタイムや複勝・2連複・拡連複・3連複に
対応していなかったので、その日だけ競走成績(K)を取り直して列を足す。既存の値は変えない。
月ごとに保存するので、時間切れになっても取得済みの月は次回飛ばす。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_history import download_text  # noqa: E402
from kyotei.parse_lzh import parse_result  # noqa: E402


def todo_dates(ent: pd.DataFrame) -> list[str]:
    """レースタイムがほとんど無い日(=古い読み取りで取得した日)。1〜4着にはほぼ必ずタイムがある。"""
    if "race_time" not in ent:
        return sorted(ent["date"].unique())
    cov = ent.groupby("date")["race_time"].apply(lambda s: s.notna().mean())
    return sorted(cov[cov <= 0.3].index)


def is_new_race_col(c: str) -> bool:
    return c.startswith(("place", "qui_", "wide", "trio_")) or c in ("exa_pop", "tri_pop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=float, default=4.5, help="時間(h)で打ち切り")
    a = ap.parse_args()
    H = ROOT / "data/history"
    t0 = time.time()
    for p in sorted(H.glob("entries_*.csv.gz")):
        rp = H / p.name.replace("entries_", "races_")
        ent = pd.read_csv(p, dtype={"race_id": str})
        dates = todo_dates(ent)
        if not dates or not rp.exists():
            continue
        if time.time() - t0 > a.time_limit * 3600:
            print("time limit: 残りは次回", flush=True)
            break
        races = pd.read_csv(rp, dtype={"race_id": str})
        e_rows, r_rows = [], []
        for ds in dates:
            text = download_text("K", dt.date.fromisoformat(ds))
            if text:
                e, r = parse_result(text, ds)
                e_rows += e
                r_rows += r
            time.sleep(0.5)
        if not e_rows:
            continue
        e_new = pd.DataFrame(e_rows).drop_duplicates(["race_id", "lane"]).set_index(["race_id", "lane"])
        key = pd.MultiIndex.from_frame(ent[["race_id", "lane"]])
        rt = pd.Series(e_new["race_time"].reindex(key).values, index=ent.index)
        ent["race_time"] = ent["race_time"].fillna(rt) if "race_time" in ent else rt
        r_new = pd.DataFrame(r_rows).drop_duplicates("race_id").set_index("race_id")
        for c in [c for c in r_new.columns if is_new_race_col(c)]:
            v = races["race_id"].map(r_new[c])
            races[c] = races[c].fillna(v) if c in races else v
        ent.to_csv(p, index=False, compression="gzip")
        races.to_csv(rp, index=False, compression="gzip")
        print(p.name, f"days={len(dates)}", f"race_time={ent['race_time'].notna().mean():.2f}",
              f"place={races['place1_pay'].notna().mean():.2f}", f"{(time.time()-t0)/60:.0f}min", flush=True)


if __name__ == "__main__":
    main()
