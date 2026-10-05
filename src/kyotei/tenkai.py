"""展開予測(アプリ表示用): 決まり手の確率と、各選手の特性。

決まり手の確率 = Σ(各艇の1着確率 × その艇が勝つときの決まり手の割合)。
勝つときの決まり手の割合は、進入コースごとの実績(2023-10〜の全レース)を土台に、
選手の差し・まくり・まくり差しの得意度で傾ける。進入は直前予想なら展示の進入、朝は枠なりとみなす。
"""
from __future__ import annotations

import math

import numpy as np

KIMARITE = ["逃げ", "差し", "まくり", "まくり差し", "その他"]
# 1着艇の進入コース別の決まり手の割合(実データ、その他=抜き・恵まれ)
PRIOR = {1: [0.951, 0.0, 0.0, 0.0, 0.049], 2: [0.0, 0.642, 0.256, 0.0, 0.101],
         3: [0.0, 0.118, 0.404, 0.363, 0.114], 4: [0.0, 0.192, 0.451, 0.259, 0.097],
         5: [0.0, 0.068, 0.210, 0.595, 0.127], 6: [0.0, 0.141, 0.270, 0.422, 0.167]}
RATE_COLS = {1: ("sashi_rate", 0.024), 2: ("makuri_rate", 0.026), 3: ("makurizashi_rate", 0.021)}
# 選手特性としてアプリに渡す列(名前: 列)
TRAIT_COLS = {"nige": "nige_rate", "sashi": "sashi_rate", "makuri": "makuri_rate", "mz": "makurizashi_rate",
              "st": "rc_avgst", "st_sd": "rc_stsd", "st_pred": "st_pred", "front": "front_rate",
              "top3": "rc_top3", "rough": "rough_top3", "local": "rv_top3", "f": "rc_fcount",
              "motor": "mtx_beat", "series": "sx_beat", "growth": "rating_growth_90", "f_since": "f_since"}


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def traits(row) -> dict:
    out = {}
    for k, col in TRAIT_COLS.items():
        v = _num(row.get(col)) if hasattr(row, "get") else None
        if v is not None:
            out[k] = round(v, 4)
    return out


def tenkai(rows: list, p_win: dict, late: bool) -> dict:
    """rows: 各艇の特徴量(dict 風)。p_win: 枠番→1着確率。"""
    total = np.zeros(5)
    paths = []
    for b in rows:
        lane = int(b["lane"])
        c = _num(b.get("course")) if late else None
        c = int(c) if c and 1 <= c <= 6 else lane
        q = np.array(PRIOR[c], dtype=float)
        if c > 1:
            for k, (col, med) in RATE_COLS.items():
                r = _num(b.get(col))
                if r is not None and q[k] > 0:
                    q[k] *= ((r + 0.02) / (med + 0.02)) ** 0.7
            q /= q.sum()
        contrib = p_win.get(lane, 0.0) * q
        total += contrib
        for k in range(4):
            if contrib[k] > 0:
                paths.append({"lane": lane, "course": c, "type": KIMARITE[k], "p": round(float(contrib[k]), 4)})
    s = total.sum() or 1.0
    paths.sort(key=lambda x: -x["p"])
    return {"kimarite": {k: round(float(v / s), 4) for k, v in zip(KIMARITE, total)},
            "paths": paths[:4]}


def scenarios(P: np.ndarray, paths: list[dict], odds: np.ndarray | None = None, n: int = 3) -> list[dict]:
    """展開シナリオ: 「この艇が勝つ展開なら、2着・3着は誰か」。
    P: 3連単120通りの確率(COMBOS の順)。paths: tenkai() の勝ち筋(艇と決まり手)。
    勝ち筋の上位から艇が重ならないように最大 n 件。2着・3着は、その艇が1着になる組の確率から計算する
    (モデルは決まり手ごとには分けていないので、同じ艇なら決まり手が違っても2着・3着の見立ては同じ)。"""
    from .betting import COMBOS
    first = np.array([int(c[0]) for c in COMBOS])
    second = np.array([int(c[2]) for c in COMBOS])
    lanes, out = [], []
    for pth in paths:
        if pth["lane"] not in lanes:
            lanes.append(pth["lane"])
    for a in np.argsort(-np.array([P[first == l].sum() for l in range(1, 7)])) + 1:  # 勝ち筋が少なければ1着確率の順で補う
        if len(lanes) >= n:
            break
        if int(a) not in lanes:
            lanes.append(int(a))
    for a in lanes[:n]:
        m = first == a
        pa = float(P[m].sum())
        if pa <= 0:
            continue
        sec = sorted(({"lane": int(b), "p": round(float(P[m & (second == b)].sum() / pa), 3)}
                      for b in range(1, 7) if b != a), key=lambda x: -x["p"])[:2]
        i = int(np.argmax(np.where(m, P, -1)))
        best = {"combo": COMBOS[i], "p_cond": round(float(P[i] / pa), 3), "p": round(float(P[i]), 4)}
        if odds is not None and np.isfinite(odds[i]):
            best["odds"] = float(odds[i])
        typ = next((x["type"] for x in paths if x["lane"] == a), "逃げ" if a == 1 else None)
        out.append({"lane": int(a), "type": typ, "p_win": round(pa, 3), "second": sec, "best": best})
    return out
