"""公式の番組表・競走成績(LZH)を日付範囲でダウンロードして、月ごとのCSVに保存する。

  python scripts/fetch_history.py --start 2023-10-01 --end 2026-09-30

保存先:
  data/history/entries_YYYYMM.csv.gz  1行=1艇(番組表+結果)
  data/history/races_YYYYMM.csv.gz    1行=1レース(気象・払戻)
取得済みの日は data/history/done.txt に記録し、再実行時はスキップする。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys
import tempfile
import time

import pandas as pd
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyotei.parse_lzh import parse_program, parse_result  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
HIST = ROOT / "data/history"
URL = "http://www1.mbrace.or.jp/od2/{k}/{ym}/{f}{ymd}.lzh"


def download_text(kind: str, d: dt.date) -> str | None:
    url = URL.format(k=kind, ym=d.strftime("%Y%m"), f=kind.lower(), ymd=d.strftime("%y%m%d"))
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            if r.ok and len(r.content) > 200:
                break
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    else:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "a.lzh"
        p.write_bytes(r.content)
        subprocess.run(["7z", "x", "-y", f"-o{tmp}/x", str(p)], check=True, capture_output=True)
        files = [f for f in (pathlib.Path(tmp) / "x").iterdir() if f.is_file()]
        return "".join(f.read_bytes().decode("cp932", errors="replace") for f in files)


def fetch_day(d: dt.date):
    ds = d.isoformat()
    b, k = download_text("B", d), download_text("K", d)
    if not b or not k:
        return None
    prog = pd.DataFrame(parse_program(b, ds))
    res, races = parse_result(k, ds)
    res, races = pd.DataFrame(res), pd.DataFrame(races)
    if prog.empty or res.empty:
        return None
    ent = prog.merge(res.drop(columns=["racer_id"]), on=["race_id", "lane"], how="left")
    return ent, races


def append_month(kind: str, ym: str, df: pd.DataFrame):
    p = HIST / f"{kind}_{ym}.csv.gz"
    if p.exists():
        old = pd.read_csv(p, dtype={"race_id": str})
        df = pd.concat([old[~old["race_id"].isin(df["race_id"])], df])
    df.sort_values("race_id").to_csv(p, index=False, compression="gzip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--max-days", type=int, default=10000)
    ap.add_argument("--time-limit", type=float, default=5.0, help="時間(h)で打ち切り")
    a = ap.parse_args()
    HIST.mkdir(parents=True, exist_ok=True)
    done_p = HIST / "done.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    t0 = time.time()
    d, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    buf: dict[str, list] = {}
    n = 0
    while d <= end and n < a.max_days and time.time() - t0 < a.time_limit * 3600:
        if d.isoformat() not in done:
            out = fetch_day(d)
            ym = d.strftime("%Y%m")
            if out is not None:
                buf.setdefault(ym, []).append(out)
                print(d, len(out[1]), "races", flush=True)
            else:
                print(d, "no data", flush=True)
            done.add(d.isoformat())
            n += 1
            time.sleep(1.0)
        nxt = d + dt.timedelta(days=1)
        if nxt.strftime("%Y%m") != d.strftime("%Y%m") or nxt > end:
            for ym, items in buf.items():
                append_month("entries", ym, pd.concat([x[0] for x in items]))
                append_month("races", ym, pd.concat([x[1] for x in items]))
            buf.clear()
            done_p.write_text("\n".join(sorted(done)))
        d = nxt
    for ym, items in buf.items():
        append_month("entries", ym, pd.concat([x[0] for x in items]))
        append_month("races", ym, pd.concat([x[1] for x in items]))
    done_p.write_text("\n".join(sorted(done)))
    print("fetched days:", n)


if __name__ == "__main__":
    main()
