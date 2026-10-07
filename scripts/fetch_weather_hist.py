"""24場の「過去の天気」(1時間ごと)を取る。気温・体感温度・湿度・露点・気圧・日射・雲・風・突風・雨。
「からだと競艇」の検証(気圧・湿度・暑さと選手の成績)と、モデルの特徴量のため。

python scripts/fetch_weather_hist.py [--start 2023-10-01] [--end 昨日]
→ data/weather/archive.csv.gz(場・時刻・気温・湿度・気圧(海面/地上)・風速・風向・降水)。既にある日は取り直さない(足りない期間だけ取る)

取得元: Open-Meteo の過去データ(ERA5 などの再解析。地点はレース場のおおよその位置、scripts/fetch_weather.py と同じ座標)。
注意: Open-Meteo の無料の API は非商用向け。記事を有料で売る段階になったら、気象庁の過去データ(出典を書けば商用も可)に
切り替えるか、Open-Meteo の有料プランにする(改良案の一覧 A12)。いまは分析用。
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
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_weather import COORD  # noqa: E402
from kyotei.racer_card import VENUES  # noqa: E402

OUT = ROOT / "data/weather/archive.csv.gz"
# 人のからだと舟の両方に効きそうなもの: 気温・体感温度・湿度・露点・気圧・日射・雲・風・突風・雨
VARS = ("temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,pressure_msl,surface_pressure,"
        "shortwave_radiation,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation")
JST = dt.timezone(dt.timedelta(hours=9))


def fetch(jcd: int, start: str, end: str) -> pd.DataFrame:
    lat, lon = COORD[jcd]
    for k in range(4):
        try:
            r = requests.get("https://archive-api.open-meteo.com/v1/archive", timeout=120, params={
                "latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "hourly": VARS,
                "wind_speed_unit": "ms", "timezone": "Asia/Tokyo"})
            r.raise_for_status()
            h = r.json()["hourly"]
            df = pd.DataFrame(h).rename(columns={"time": "time"})
            df.insert(0, "jcd", jcd)
            return df
        except Exception as e:  # noqa: BLE001
            print(VENUES[jcd], "retry", k, e)
            time.sleep(10 * (k + 1))
    return pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-10-01")
    ap.add_argument("--end", default=(dt.datetime.now(JST).date() - dt.timedelta(days=6)).isoformat(),
                    help="過去データは数日遅れで確定するので、既定は6日前まで")
    a = ap.parse_args()
    old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    parts = [old] if len(old) else []
    for jcd in COORD:
        start = a.start
        if len(old):
            have = old[old["jcd"] == jcd]["time"]
            if len(have):
                start = max(a.start, (pd.Timestamp(have.max()) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        if start > a.end:
            continue
        df = fetch(jcd, start, a.end)
        print(VENUES[jcd], start, "→", a.end, len(df), "行")
        if len(df):
            parts.append(df)
        time.sleep(1.5)
    if not parts:
        raise SystemExit("取れませんでした")
    df = pd.concat(parts, ignore_index=True).drop_duplicates(["jcd", "time"], keep="last").sort_values(["jcd", "time"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(df.to_csv(index=False).encode("utf-8"))
    OUT.write_bytes(buf.getvalue())
    print(f"過去の天気 {df['jcd'].nunique()}場 / {len(df):,}行 → {OUT}({OUT.stat().st_size / 1e6:.1f}MB)")


if __name__ == "__main__":
    main()
