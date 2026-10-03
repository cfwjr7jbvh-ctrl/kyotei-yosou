"""Boatrace Open API(有志)の結果データから、過去レースの決まり手を集める。

  python scripts/fetch_kimarite.py --start 2023-10-01
保存先: data/kimarite/kimarite_YYYYMM.csv.gz (race_id, kimarite)
番号: 1=逃げ 2=差し 3=まくり 4=まくり差し 5=抜き 6=恵まれ
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import time

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/kimarite"
URL = "https://boatraceopenapi.github.io/results/v3/{y}/{ymd}.json"


def fetch_day(d: dt.date):
    for attempt in range(3):
        try:
            r = requests.get(URL.format(y=d.year, ymd=d.strftime("%Y%m%d")), timeout=60)
            if r.status_code == 404:
                return []
            if r.ok:
                data = r.json()
                break
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (attempt + 1))
    else:
        return []
    races = data.get("results", data.get("races", [])) if isinstance(data, dict) else data
    rows = []
    for race in races or []:
        if not isinstance(race, dict):
            continue
        try:
            rid = f"{d:%Y%m%d}{int(race['stadium_number']):02d}{int(race['number']):02d}"
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"race_id": rid, "kimarite": race.get("technique_number")})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    done_p = OUT / "done.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    d, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    buf: dict[str, list] = {}

    def flush():
        for ym, rows in buf.items():
            p = OUT / f"kimarite_{ym}.csv.gz"
            df = pd.DataFrame(rows)
            if p.exists():
                old = pd.read_csv(p, dtype={"race_id": str})
                df = pd.concat([old[~old["race_id"].isin(df["race_id"])], df])
            df.sort_values("race_id").to_csv(p, index=False, compression="gzip")
        buf.clear()
        done_p.write_text("\n".join(sorted(done)))

    while d <= end:
        if d.isoformat() not in done:
            rows = fetch_day(d)
            if rows:
                buf.setdefault(d.strftime("%Y%m"), []).extend(rows)
                done.add(d.isoformat())
            print(d, len(rows), flush=True)
            time.sleep(0.3)
        nxt = d + dt.timedelta(days=1)
        if nxt.month != d.month:
            flush()
        d = nxt
    flush()


if __name__ == "__main__":
    main()
