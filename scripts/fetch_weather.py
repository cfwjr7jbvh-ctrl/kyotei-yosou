"""24場の天気予報(1時間ごと)を毎朝ためる(Open-Meteo、無料・鍵なし)。

python scripts/fetch_weather.py [--days 2]
→ data/weather/forecast_YYYYMM.csv.gz に追記(取得日時・場・時刻・風速・風向・突風・気温・降水・気圧)
使い道: レース前に分かる「予報」と、結果に残る「実際の風」(data/history の wind・wind_dir)を突き合わせ、
予報からイン・まくりの傾向を読む記事と、朝の予想の特徴量(いまは当日の風は直前情報でしか分からない)に。
座標はレース場のおおよその位置(天気の精度には十分)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import pathlib
import sys
import time

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.racer_card import VENUES  # noqa: E402

OUT = ROOT / "data/weather"
JST = dt.timezone(dt.timedelta(hours=9))
COORD = {1: (36.405, 139.312), 2: (35.814, 139.656), 3: (35.683, 139.870), 4: (35.579, 139.741), 5: (35.624, 139.591),
         6: (34.711, 137.593), 7: (34.827, 137.235), 8: (34.878, 136.837), 9: (34.698, 136.521), 10: (36.230, 136.146),
         11: (35.021, 135.886), 12: (34.609, 135.479), 13: (34.723, 135.433), 14: (34.185, 134.610), 15: (34.296, 133.790),
         16: (34.465, 133.814), 17: (34.318, 132.306), 18: (34.054, 131.796), 19: (33.967, 130.946), 20: (33.904, 130.819),
         21: (33.887, 130.671), 22: (33.595, 130.395), 23: (33.453, 129.972), 24: (32.916, 129.955)}
VARS = "wind_speed_10m,wind_direction_10m,wind_gusts_10m,temperature_2m,precipitation,surface_pressure,weather_code"


def fetch(days: int) -> pd.DataFrame:
    rows = []
    now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    for jcd, (lat, lon) in COORD.items():
        for k in range(3):
            try:
                r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
                    "latitude": lat, "longitude": lon, "hourly": VARS, "wind_speed_unit": "ms", "timezone": "Asia/Tokyo",
                    "forecast_days": days})
                r.raise_for_status()
                h = r.json()["hourly"]
                for i, t in enumerate(h["time"]):
                    rows.append({"fetched": now, "jcd": jcd, "venue": VENUES[jcd], "time": t,
                                 **{v: h[v][i] for v in VARS.split(",")}})
                break
            except Exception as e:  # noqa: BLE001
                print(VENUES[jcd], "retry", k, e)
                time.sleep(3 * (k + 1))
        time.sleep(0.3)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    a = ap.parse_args()
    df = fetch(a.days)
    if df.empty:
        raise SystemExit("取れませんでした")
    OUT.mkdir(parents=True, exist_ok=True)
    ym = dt.datetime.now(JST).strftime("%Y%m")
    path = OUT / f"forecast_{ym}.csv.gz"
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old, df], ignore_index=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(df.to_csv(index=False).encode("utf-8"))
    path.write_bytes(buf.getvalue())
    print(f"天気予報 {df['fetched'].nunique()} 回分 / {len(df)} 行 → {path}")


if __name__ == "__main__":
    main()
