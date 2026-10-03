"""公式の番組表(B)・競走成績(K)テキストのパーサー。

ファイルは Shift_JIS(cp932)の固定長テキストで、場ごとに「NNBBGN」「NNKBGN」
(NN=場コード)で区切られている。
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")

_B_ROW = re.compile(
    r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12]) *"
    r"(\d+\.\d\d) +(\d+\.\d\d) +(\d+\.\d\d) +(\d+\.\d\d) +(\d+) +(\d+\.\d\d) *(\d+) +(\d+\.\d\d)(.*)$")
_B_RACE = re.compile(r"^\s*([０-９\d]+)Ｒ\s+(\S+).*?Ｈ([０-９\d]+)ｍ.*?締切予定([０-９\d]+)：([０-９\d]+)")
_K_RACE = re.compile(r"^\s+(\d+)R\s+(.+?)\s+H(\d+)m\s+(\S+)\s+風\s+(\S+)\s+(\d+)m\s+波\s+(\d+)cm")
_K_ROW = re.compile(r"^  (\S\S?) +([1-6]) (\d{4}) (.{8})(.*)$")
_K_VAL = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d\.\d\d)\s+([1-6])\s+([FL]?\d?\.\d\d)")


def _split_venues(text: str, kind: str) -> dict[int, str]:
    parts = re.split(rf"^(\d\d){kind}BGN\s*$", text, flags=re.M)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def parse_program(text: str, date: str) -> list[dict]:
    """番組表 → 1行1艇の出走表。"""
    text = text.replace("\r", "")
    rows = []
    for jcd, body in _split_venues(text, "B").items():
        rno = None
        meta = {}
        for line in body.split("\n"):
            m = _B_RACE.match(line)
            if m:
                rno = int(m.group(1).translate(Z2H))
                meta = {"race_type": m.group(2).replace("　", ""),
                        "fixed_entry": int("進入固定" in line),
                        "distance": int(m.group(3).translate(Z2H)),
                        "deadline": f"{int(m.group(4).translate(Z2H)):02d}:{m.group(5).translate(Z2H)}"}
                continue
            m = _B_ROW.match(line)
            if not m or rno is None:
                continue
            g = m.groups()
            series = g[15][1:13] if len(g[15]) > 1 else ""
            fins = [int(c) for c in series.translate(Z2H) if c in "123456"]
            rows.append(dict(
                race_id=f"{date.replace('-', '')}{jcd:02d}{rno:02d}", date=date, jcd=jcd, rno=rno,
                lane=int(g[0]), racer_id=int(g[1]), racer_name=g[2].replace("　", ""),
                age=int(g[3]), branch=g[4].replace("　", ""), weight=float(g[5]),
                racer_class=g[6], nat_win_rate=_f(g[7]), nat_2rate=_f(g[8]),
                loc_win_rate=_f(g[9]), loc_2rate=_f(g[10]), motor_no=int(g[11]),
                motor_2rate=_f(g[12]), boat_no=int(g[13]), boat_2rate=_f(g[14]),
                series_n=len(fins), series_avg=float(np.mean(fins)) if fins else np.nan,
                series_flag=int(bool(re.search(r"[FLKS]", series))), **meta))
    return rows


def parse_result(text: str, date: str) -> tuple[list[dict], list[dict]]:
    """競走成績 → (各艇の結果, レースごとの気象・払戻)。"""
    text = unicodedata.normalize("NFKC", text.replace("\r", ""))
    ent, races = [], []
    for jcd, body in _split_venues(text, "K").items():
        cur = None
        for line in body.split("\n"):
            m = _K_RACE.match(line)
            if m:
                rno = int(m.group(1))
                cur = dict(race_id=f"{date.replace('-', '')}{jcd:02d}{rno:02d}", date=date, jcd=jcd,
                           rno=rno, race_title=m.group(2).replace("進入固定", "").strip(),
                           weather=m.group(4), wind_dir=m.group(5), wind=int(m.group(6)),
                           wave=int(m.group(7)))
                races.append(cur)
                continue
            if cur is None:
                continue
            m = _K_ROW.match(line)
            if m:
                code, lane, regno, _name, rest = m.groups()
                v = _K_VAL.match(rest)
                ent.append(dict(race_id=cur["race_id"], lane=int(lane), racer_id=int(regno),
                                finish=int(code) if code.isdigit() else np.nan, result_code=code,
                                exhibit_time=_f(v.group(3)) if v else np.nan,
                                course=int(v.group(4)) if v else np.nan,
                                st=_f(v.group(5).lstrip("FL")) if v else np.nan,
                                st_flag=v.group(5)[0] if v and v.group(5)[0] in "FL" else ""))
                continue
            s = line.strip()
            for key, col, n in (("単勝", "win", 1), ("2連単", "exa", 2), ("3連単", "tri", 3)):
                if s.startswith(key) and f"{col}_pay" not in cur:
                    mm = re.match(rf"{key}\s+([1-6](?:-[1-6]){{{n-1}}})\s+(\d+)", s)
                    if mm:
                        cur[f"{col}_combo"] = mm.group(1)
                        cur[f"{col}_pay"] = int(mm.group(2))
                    else:
                        cur[f"{col}_pay"] = np.nan
    for r in races:
        if isinstance(r.get("win_combo"), str):
            r["win_lane"] = int(r["win_combo"])
    return ent, races
