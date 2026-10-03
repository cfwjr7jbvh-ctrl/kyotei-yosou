"""保存済みデータの読み込み(番組表+結果+直前情報)。"""
from __future__ import annotations

import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREVIEW_COLS = ["ex_st", "weight_now", "tilt", "wind_dir"]


def _read(pattern: str, since: str | None):
    files = sorted((ROOT / "data").glob(pattern))
    if since:
        files = [p for p in files if p.stem.split("_")[-1].split(".")[0] >= since]
    if not files:
        return None
    return pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in files], ignore_index=True)


def load_history(since: str | None = None):
    """since: 'YYYYMM' 以降だけ読む。直前情報は公式成績と突き合わせて、合わないレースは捨てる。"""
    ent = _read("history/entries_*.csv.gz", since)
    races = _read("history/races_*.csv.gz", since)
    pv = _read("previews/previews_*.csv.gz", since)
    if pv is not None and ent is not None:
        m = ent[["race_id", "lane", "exhibit_time", "course"]].merge(pv, on=["race_id", "lane"])
        bad = m[((m["exhibit_time"] - m["ex_time_p"]).abs() > 0.015)
                & m["exhibit_time"].notna() & m["ex_time_p"].notna()]["race_id"].unique()
        pv = pv[~pv["race_id"].isin(bad)]
        ent = ent.merge(pv[["race_id", "lane"] + PREVIEW_COLS], on=["race_id", "lane"], how="left")
        print(f"previews merged: {pv['race_id'].nunique()} races (dropped {len(bad)} mismatched)")
    odds = _read("odds/odds3t_*.csv.gz", since)
    return ent, races, odds
