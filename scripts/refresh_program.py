"""保存済みの過去データに、番組表から得点率などの列を追加する(番組表だけ取り直す)。

  python scripts/refresh_program.py
追加する列: series_str(今節成績), series_races, series_rate(得点率), day_no(節の何日目)
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_history import download_text  # noqa: E402
from kyotei.parse_lzh import parse_program  # noqa: E402

NEW = ["series_str", "series_races", "series_rate", "day_no"]


def main():
    H = ROOT / "data/history"
    t0 = time.time()
    for p in sorted(H.glob("entries_*.csv.gz")):
        ent = pd.read_csv(p, dtype={"race_id": str})
        if all(c in ent for c in NEW) and ent["day_no"].notna().mean() > 0.95:
            continue
        rows = []
        for ds in sorted(ent["date"].unique()):
            text = download_text("B", dt.date.fromisoformat(ds))
            if text:
                rows += parse_program(text, ds)
            time.sleep(0.5)
        if not rows:
            continue
        prog = pd.DataFrame(rows)[["race_id", "lane"] + NEW]
        ent = ent.drop(columns=[c for c in NEW if c in ent]).merge(prog, on=["race_id", "lane"], how="left")
        ent.to_csv(p, index=False, compression="gzip")
        print(p.name, f"{ent['day_no'].notna().mean():.3f}", f"{(time.time()-t0)/60:.0f}min", flush=True)


if __name__ == "__main__":
    main()
