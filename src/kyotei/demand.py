"""注目度(買う人・見る人が多そうなレースの目安)。記事・X で「どのレースを出すか」を選ぶのに使う。

売上の数字はレースごとには取れないので、ふだん売上が大きいと言われる条件の掛け算で見積もる(自分たちの目安):
- 大会の格: SG > PG1 > G1 > G2 > G3 > 一般
- レースの種類: 優勝戦 > ドリーム戦 > 準優勝戦 > 12R > ほか
- 土日・祝日、夜(ナイター・ミッドナイト)の締切
点数は「一般戦のふつうのレース = 1」。

score(grade, race_type, rno, day, deadline) → 点数
pick(cands, top, min_score) → 点数の高い順に、しきい値以上を top 件
"""
from __future__ import annotations

import datetime as dt

GRADE_W = {"SG": 10.0, "PG1": 7.0, "G1": 4.0, "G2": 2.5, "G3": 1.5}
JP_HOLIDAYS_2026 = {"2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-11"}


def race_kind_w(race_type: str | None, rno: int | None) -> float:
    rt = str(race_type or "")
    if "優勝戦" in rt and "準" not in rt:
        return 3.0
    if "ドリーム" in rt:
        return 1.8
    if "準優" in rt:
        return 1.6
    if "選抜" in rt:
        return 1.3
    return 1.3 if rno == 12 else 1.0


def day_w(day: dt.date) -> float:
    return 1.4 if day.weekday() >= 5 or day.isoformat() in JP_HOLIDAYS_2026 else 1.0


def time_w(deadline: str | None) -> float:
    try:
        hh = int(str(deadline).split(":")[0])
    except (ValueError, IndexError):
        return 1.0
    return 1.2 if hh >= 17 else 1.0


def score(grade: str | None, race_type: str | None = None, rno: int | None = None, day: dt.date | None = None,
          deadline: str | None = None) -> float:
    g = GRADE_W.get(str(grade or "").upper(), 1.0)
    return round(g * race_kind_w(race_type, rno) * (day_w(day) if day else 1.0) * time_w(deadline), 2)


def series_score(grade: str | None, final_day: dt.date | None = None) -> float:
    """節(大会)全体の注目度: 格 × 優勝戦の日が土日祝か。"""
    return round(GRADE_W.get(str(grade or "").upper(), 1.0) * (day_w(final_day) if final_day else 1.0), 2)


def stars(s: float) -> str:
    """記事タブに出す目安: ★★★ SG・PG1 級、★★ G1 の大一番、★ それ以外。"""
    return "★★★" if s >= 7 else ("★★" if s >= 4 else "★")


def pick(cands: list, top: int, min_score: float, key=lambda c: c["score"]) -> list:
    return sorted([c for c in cands if key(c) >= min_score], key=lambda c: -key(c))[:top]
