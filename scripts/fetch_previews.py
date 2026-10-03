"""Boatrace Open API(有志による公開データ)から過去の直前情報を集める。

  python scripts/fetch_previews.py --start 2023-10-01

https://boatraceopenapi.github.io/previews/v2/YYYY/YYYYMMDD.json を1日1ファイル取得し、
data/previews/previews_YYYYMM.csv.gz に保存する。
スタート展示のフライングはマイナスのST、欠場は null で入っている。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import time

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/previews"
URL = "https://boatraceopenapi.github.io/previews/v2/{y}/{ymd}.json"


def fetch_day(d: dt.date) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            r = requests.get(URL.format(y=d.year, ymd=d.strftime("%Y%m%d")), timeout=60)
            if r.status_code == 404:
                return None
            if r.ok:
                break
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    else:
        return None
    try:
        data = r.json()
    except ValueError:
        print(d, "invalid json", flush=True)
        return None
    races = data.get("previews", []) if isinstance(data, dict) else []
    rows = []
    for race in races:
        if not isinstance(race, dict):
            continue
        rid = f"{d:%Y%m%d}{int(race['race_stadium_number']):02d}{int(race['race_number']):02d}"
        boats = race.get("boats") or []
        if isinstance(boats, dict):
            boats = list(boats.values())
        for b in boats:
            if not isinstance(b, dict):
                continue
            rows.append({
                "race_id": rid, "lane": b.get("racer_boat_number"),
                "ex_course": b.get("racer_course_number"), "ex_st": b.get("racer_start_timing"),
                "ex_time_p": b.get("racer_exhibition_time"), "weight_now": b.get("racer_weight"),
                "weight_adj": b.get("racer_weight_adjustment"), "tilt": b.get("racer_tilt_adjustment"),
                "wind_dir": race.get("race_wind_direction_number"), "p_wind": race.get("race_wind"),
                "p_wave": race.get("race_wave"), "weather_no": race.get("race_weather_number"),
                "air_temp": race.get("race_temperature"), "water_temp": race.get("race_water_temperature"),
            })
    return pd.DataFrame(rows) if rows else None


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
        for ym, items in buf.items():
            p = OUT / f"previews_{ym}.csv.gz"
            df = pd.concat(items, ignore_index=True)
            if p.exists():
                old = pd.read_csv(p, dtype={"race_id": str})
                df = pd.concat([old[~old["race_id"].isin(df["race_id"])], df], ignore_index=True)
            df.sort_values(["race_id", "lane"]).to_csv(p, index=False, compression="gzip")
        buf.clear()
        done_p.write_text("\n".join(sorted(done)))

    while d <= end:
        if d.isoformat() not in done:
            try:
                df = fetch_day(d)
            except Exception as e:  # noqa: BLE001  壊れたデータの日は飛ばす
                print(d, "error", repr(e)[:200], flush=True)
                df = None
            if df is not None and len(df):
                buf.setdefault(d.strftime("%Y%m"), []).append(df)
                done.add(d.isoformat())
                print(d, len(df), flush=True)
            else:
                print(d, "no data", flush=True)
            time.sleep(0.3)
        nxt = d + dt.timedelta(days=1)
        if nxt.month != d.month:
            flush()
        d = nxt
    flush()


if __name__ == "__main__":
    main()
