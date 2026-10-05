"""旧暦と六曜(大安・仏滅など)。外部ライブラリなし。

新月は Meeus『Astronomical Algorithms』49章(惑星の補正は省略、誤差は数分)、
太陽の黄経は25章の簡易式(誤差 0.01度≒15分)。日付は日本時間。
旧暦の月は、新月の日を1日として、その月に入る中気(太陽黄経が30度の倍数)で月番号を決め、
中気の無い月は閏月(前の月と同じ番号)。六曜は (月 + 日) を6で割った余りで決まる。
"""
from __future__ import annotations

import datetime as dt
import math
from functools import lru_cache

ROKUYO = ["大安", "赤口", "先勝", "友引", "先負", "仏滅"]
_JD_UNIX = 2440587.5
_JST = 9 / 24


def _sin(d):
    return math.sin(math.radians(d))


def new_moon_jde(k: int) -> float:
    T = k / 1236.85
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T ** 2 - 0.000000150 * T ** 3 + 0.00000000073 * T ** 4
    E = 1 - 0.002516 * T - 0.0000074 * T ** 2
    M = 2.5534 + 29.10535670 * k - 0.0000014 * T ** 2 - 0.00000011 * T ** 3
    Mp = 201.5643 + 385.81693528 * k + 0.0107582 * T ** 2 + 0.00001238 * T ** 3 - 0.000000058 * T ** 4
    F = 160.7108 + 390.67050284 * k - 0.0016118 * T ** 2 - 0.00000227 * T ** 3 + 0.000000011 * T ** 4
    Om = 124.7746 - 1.56375588 * k + 0.0020672 * T ** 2 + 0.00000215 * T ** 3
    c = (-0.40720 * _sin(Mp) + 0.17241 * E * _sin(M) + 0.01608 * _sin(2 * Mp) + 0.01039 * _sin(2 * F)
         + 0.00739 * E * _sin(Mp - M) - 0.00514 * E * _sin(Mp + M) + 0.00208 * E * E * _sin(2 * M)
         - 0.00111 * _sin(Mp - 2 * F) - 0.00057 * _sin(Mp + 2 * F) + 0.00056 * E * _sin(2 * Mp + M)
         - 0.00042 * _sin(3 * Mp) + 0.00042 * E * _sin(M + 2 * F) + 0.00038 * E * _sin(M - 2 * F)
         - 0.00024 * E * _sin(2 * Mp - M) - 0.00017 * _sin(Om) - 0.00007 * _sin(Mp + 2 * M)
         + 0.00004 * _sin(2 * Mp - 2 * F) + 0.00004 * _sin(3 * M) + 0.00003 * _sin(Mp + M - 2 * F)
         + 0.00003 * _sin(2 * Mp + 2 * F) - 0.00003 * _sin(Mp + M + 2 * F) + 0.00003 * _sin(Mp - M + 2 * F)
         - 0.00002 * _sin(Mp - M - 2 * F) - 0.00002 * _sin(3 * Mp + M) + 0.00002 * _sin(4 * Mp))
    return jde + c - 69 / 86400   # TT → UT(ΔT 約69秒)


def sun_longitude(jd: float) -> float:
    T = (jd - 2451545.0) / 36525
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T ** 2
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T ** 2
    C = ((1.914602 - 0.004817 * T - 0.000014 * T ** 2) * _sin(M) + (0.019993 - 0.000101 * T) * _sin(2 * M)
         + 0.000289 * _sin(3 * M))
    om = 125.04 - 1934.136 * T
    return (L0 + C - 0.00569 - 0.00478 * _sin(om)) % 360


def _jst_date(jd: float) -> dt.date:
    return (dt.datetime(1970, 1, 1) + dt.timedelta(days=jd + _JST - _JD_UNIX)).date()


def _jd(d: dt.date) -> float:
    return (dt.datetime(d.year, d.month, d.day) - dt.datetime(1970, 1, 1)).total_seconds() / 86400 + _JD_UNIX - _JST


def _term_date(lon: float, jd0: float) -> dt.date:
    """jd0 の近く(前後20日)で太陽黄経が lon 度になる日(日本時間)。"""
    def f(j):
        return (sun_longitude(j) - lon + 180) % 360 - 180
    a, b = jd0 - 20, jd0 + 20
    for _ in range(60):
        m = (a + b) / 2
        if f(a) * f(m) <= 0:
            b = m
        else:
            a = m
    return _jst_date((a + b) / 2)


@lru_cache(maxsize=None)
def _months(year: int):
    """year の前後を含む旧暦の月の表: [(初日, 月番号, 閏か)]。"""
    k0 = math.floor((year - 1 - 2000) * 12.3685)
    starts = [_jst_date(new_moon_jde(k)) for k in range(k0, k0 + 40)]
    # 中気(黄経 0,30,...,330)の日付
    terms = []
    jd = _jd(dt.date(year - 1, 1, 1))
    end = _jd(starts[-1])
    j = jd
    while j < end + 40:
        lon = sun_longitude(j)
        nxt = (math.floor(lon / 30) + 1) * 30 % 360
        guess = j + ((nxt - lon) % 360) / 0.9856
        d = _term_date(nxt, guess)
        terms.append((d, nxt))
        j = _jd(d) + 5
    out = []
    for a, b in zip(starts, starts[1:]):
        inside = [lon for d, lon in terms if a <= d < b]
        if inside:
            mon = (int(inside[0] // 30) + 2 - 1) % 12 + 1   # 0度(春分)→2月、330度(雨水)→1月
            out.append((a, mon, False))
        else:
            out.append((a, None, True))
    for i, (a, mon, leap) in enumerate(out):   # 閏月は前の月の番号
        if leap and i > 0:
            out[i] = (a, out[i - 1][1], True)
    return out


def kyureki(d: dt.date) -> tuple[int, int, bool]:
    """(旧暦の月, 日, 閏月か)"""
    for a, mon, leap in reversed(_months(d.year)):
        if a <= d:
            return mon, (d - a).days + 1, leap
    raise ValueError(d)


def rokuyo(d: dt.date) -> str:
    m, day, _ = kyureki(d)
    return ROKUYO[(m + day) % 6]
