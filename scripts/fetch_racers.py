"""公式の「レーサー期別成績」(年2回、前期・後期)を取って、そのまま文字に直して保存する。

python scripts/fetch_racers.py [--periods 2304,2310,2404,2410,2504,2510,2604]
→ data/racers/fanYYMM.txt(UTF-8 に直しただけの固定長テキスト)。読み込みは scripts/parse_racers.py(中身を見てから作る)
中身: 登番・氏名・支部・級別・生年月日・性別・身長・体重・血液型・出身地・期の成績 など。
使い方の決まり: 公式のデータは自分たちで集計した数字にして使う。個人の血液型・生年月日などを1人ずつ載せることはしない(集計のみ)。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import tempfile
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/racers"
CANDIDATES = ["https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/fan{p}.lzh",
              "https://www.boatrace.jp/owpc/pc/extra/data/static_extra/pc_static/download/data/kibetsu/fan{p}.lzh"]


def get(period: str) -> str | None:
    for tpl in CANDIDATES:
        url = tpl.format(p=period)
        for k in range(3):
            try:
                r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (kyotei-yosou research)"})
                print(url, r.status_code, len(r.content))
                if r.status_code == 404:
                    break
                if r.ok and len(r.content) > 1000:
                    with tempfile.TemporaryDirectory() as tmp:
                        p = pathlib.Path(tmp) / "a.lzh"
                        p.write_bytes(r.content)
                        subprocess.run(["7z", "x", "-y", f"-o{tmp}/x", str(p)], check=True, capture_output=True)
                        files = sorted(f for f in (pathlib.Path(tmp) / "x").rglob("*") if f.is_file())
                        return "".join(f.read_bytes().decode("cp932", errors="replace") for f in files)
            except Exception as e:  # noqa: BLE001
                print(url, "error", e)
            time.sleep(3 * (k + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", default="2304,2310,2404,2410,2504,2510,2604,2610")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for p in a.periods.split(","):
        f = OUT / f"fan{p}.txt"
        if f.exists():
            continue
        t = get(p)
        if not t:
            print(p, "なし"); continue
        f.write_text(t, encoding="utf-8")
        lines = t.splitlines()
        print(p, len(lines), "行。先頭:")
        for ln in lines[:3]:
            print(repr(ln))
        time.sleep(2)


if __name__ == "__main__":
    main()
