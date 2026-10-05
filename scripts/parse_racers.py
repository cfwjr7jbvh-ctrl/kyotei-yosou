"""data/racers/fanYYMM.txt(公式のレーサー期別成績)を読んで data/racers/racers.csv(1行=1選手×1期)に。

固定長(元の文字コード cp932 でのバイト位置)。実物から確かめた並び:
  0-4 登番 / 4-20 氏名 / 20-35 カナ / 35-39 支部 / 39-41 級別 / 41 年号(S昭和・H平成) / 42-48 生年月日(YYMMDD)
  48 性別(1男・2女) / 49-51 年齢 / 51-54 身長 / 54-56 体重 / 56-58 血液型 / 58-62 勝率(×100) / 62-66 複勝率(×10)
  … / 「年(4)期(1)算出期間の自(8)至(8)養成期(3)」が級別3期分のあとに続く / 末尾6バイト 出身地
使い方の決まり: 個人の生年月日・血液型などを1人ずつ載せない(集計にだけ使う)。
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIR = ROOT / "data/racers"
ERA = {"S": 1925, "H": 1988, "R": 2018}


def parse_line(line: str, period: str) -> dict | None:
    b = line.encode("cp932", errors="replace")
    if len(b) < 120 or not b[:4].isdigit():
        return None
    s = lambda i, j: b[i:j].decode("cp932", errors="replace").strip()  # noqa: E731
    era, ymd = s(41, 42), s(42, 48)
    birth = None
    if era in ERA and ymd.isdigit():
        try:
            birth = dt.date(ERA[era] + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        except ValueError:
            birth = None
    # 前期・前々期・前々々期の級別(各2バイト、空白のこともある)→ 能力指数2つ(各4)→ 年(4)期(1)→ 算出期間(8+8)→ 養成期(3)
    m = re.search(rb"(?:[AB][12]|\s\s){3}\d{4}\d{4}(20\d{2})([12])(20\d{6})(20\d{6})(\d{3})", b)
    num = lambda v: int(v) if v.isdigit() else None  # noqa: E731
    return {
        "period": period, "racer_id": int(s(0, 4)), "name": re.sub(r"\s+", "", s(4, 20).replace("　", "")),
        "branch": s(35, 39), "class": s(39, 41), "birth": birth.isoformat() if birth else None,
        "sex": {"1": "男", "2": "女"}.get(s(48, 49)), "age": num(s(49, 51)), "height": num(s(51, 54)), "weight": num(s(54, 56)),
        "blood": s(56, 58) or None, "win_rate": (num(s(58, 62)) or 0) / 100,
        "term": int(m.group(5)) if m else None,                   # 養成期(何期生か)
        "hometown": b[-6:].decode("cp932", errors="replace").replace("　", "").strip(),
    }


def main():
    rows = []
    for f in sorted(DIR.glob("fan*.txt")):
        period = f.stem[3:]
        for ln in f.read_text(encoding="utf-8").splitlines():
            r = parse_line(ln, period)
            if r:
                rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(DIR / "racers.csv", index=False)
    last = df.sort_values("period").groupby("racer_id").tail(1)
    print(f"{len(df):,}行 / 選手 {df['racer_id'].nunique():,}人 / 期 {sorted(df['period'].unique())}")
    print("性別", last["sex"].value_counts().to_dict())
    print("血液型", last["blood"].value_counts().to_dict())
    print("身長", last["height"].describe().round(1).to_dict())
    print("出身地(上位)", last["hometown"].value_counts().head(6).to_dict())
    print("養成期", last["term"].describe().round(0).to_dict())
    print(last[last["racer_id"].isin([3024, 4320])][["racer_id", "name", "birth", "sex", "height", "weight", "blood", "term", "hometown"]].to_string())


if __name__ == "__main__":
    main()
