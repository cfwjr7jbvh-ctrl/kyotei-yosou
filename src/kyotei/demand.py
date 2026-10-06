"""注目度(買う人・見る人が多そうなレースの目安)。記事・X で「どのレースを出すか」を選ぶのに使う。

物差しは「3連単の売上の見込み」。過去4.3万レースの最終オッズから売上を逆算して(scripts/demand_fit.py)、
レースの種類・R・締切の時間・場・その日のA1の割合(大会の格の代わり)で学んだ式(reports/demand_model.json)。
分かったこと(2026-10-06): 夜の締切がいちばん効く(21時台は昼の4〜5倍)、A1ばかりの日は1.8倍、優勝戦は2倍、土日はほぼ関係なし。

score(...) → 売上の見込み(億円)。ふつうのレースで0.3前後、G1 のナイターの優勝戦で3〜7。
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import math
import pathlib

MODEL = pathlib.Path(__file__).resolve().parents[2] / "reports/demand_model.json"
A1_BINS = [0, .35, .45, .55, .65, .75, 1.01]
GRADE_A1 = {"SG": 0.95, "PG1": 0.8, "G1": 0.85, "G2": 0.7, "G3": 0.5}   # A1の割合が分からないときの、格からの目安


@functools.lru_cache(maxsize=1)
def _coef() -> dict:
    try:
        return json.loads(MODEL.read_text(encoding="utf-8"))["coef"]
    except Exception:  # noqa: BLE001
        return {}


def kind(race_type: str | None) -> str:
    t = str(race_type or "")
    if "優勝" in t and "準" not in t:
        return "優勝戦"
    if "準優" in t:
        return "準優"
    if "ドリーム" in t:
        return "ドリーム"
    if "選抜" in t and "特別" in t:
        return "特別選抜"
    return "ふつう"


def _a1b(a1: float) -> int:
    for i in range(len(A1_BINS) - 1):
        if A1_BINS[i] <= a1 < A1_BINS[i + 1]:
            return i
    return 0


def score(grade: str | None = None, race_type: str | None = None, rno: int | None = None, day: dt.date | None = None,
          deadline: str | None = None, jcd: int | None = None, a1: float | None = None) -> float:
    """3連単の売上の見込み(億円)。a1 = その日その場のA1の割合(無ければ格から)。day は使わない(土日の差はほぼ無かった)。"""
    c = _coef()
    if not c:
        return 0.0
    if a1 is None:
        a1 = GRADE_A1.get(str(grade or "").upper(), 0.3)
    try:
        hh = min(max(int(str(deadline).split(":")[0]), 8), 22)
    except (ValueError, IndexError):
        hh = 15
    lg = c.get("c", 0) + c.get(f"kind_{kind(race_type)}", 0) + c.get(f"rno_{int(rno or 6)}", 0) + c.get(f"hh_{hh}", 0) \
        + c.get(f"jcd_{int(jcd or 0)}", 0) + c.get(f"a1b_{_a1b(a1)}", 0)
    return round(10 ** lg / 1e8, 2)


def day_a1(races: list[dict], jcd: int) -> float | None:
    """その日のその場の出走表から、A1の割合。"""
    cl = [b.get("class") for r in races if r.get("jcd") == jcd for b in r.get("boats", [])]
    return sum(1 for x in cl if x == "A1") / len(cl) if cl else None


def series_score(grade: str | None, jcd: int | None = None, a1: float | None = None, final_day: dt.date | None = None) -> float:
    """節(大会)の注目度: 優勝戦(12R、夜ならナイター)の売上の見込み。"""
    night = int(jcd or 0) in NIGHTER
    return score(grade, "優勝戦", 12, final_day, "20:45" if night else "16:40", jcd, a1)


NIGHTER = {1, 7, 12, 15, 19, 20, 24}   # 桐生・蒲郡・住之江・丸亀・下関・若松・大村(ナイター開催の場)


def stars(s: float) -> str:
    """記事タブに出す目安(3連単の売上の見込み): ★★★ 3億以上、★★ 1億以上、★ それ以外。"""
    return "★★★" if s >= 3 else ("★★" if s >= 1 else "★")


def yen(s: float) -> str:
    return f"{s:.1f}億円" if s >= 1 else f"{round(s * 1e4):,}万円"
