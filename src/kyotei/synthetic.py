"""動作確認用のサンプルデータ生成。

公式データと同じ列構成(entries / races)で、コース有利・選手実力・モーター性能・
場ごとの癖・市場オッズの歪みを持つ疑似レースを作る。モデルや評価コードを
実データ無しでテストするためだけに使う。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .plackett import pl_trifecta_matrix, pl_exacta_matrix

LANE_BASE = np.array([1.75, 0.55, 0.45, 0.30, -0.05, -0.40])
CLASSES = ["A1", "A2", "B1", "B2"]


def generate(n_days: int = 300, venues_per_day: int = 8, races_per_venue: int = 12,
             n_racers: int = 1600, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    skill = rng.normal(0, 0.55, n_racers)
    st_skill = rng.normal(0.15, 0.02, n_racers)
    weight = rng.normal(52, 3, n_racers)
    q = np.quantile(skill, [0.8, 0.6, 0.15])
    cls = np.where(skill > q[0], "A1", np.where(skill > q[1], "A2", np.where(skill > q[2], "B1", "B2")))
    venue_in = rng.normal(0, 0.25, 25)
    motor_q = {v: rng.normal(0, 0.3, 60) for v in range(1, 25)}
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")

    ent_rows, race_rows = [], []
    for d in dates:
        venues = rng.choice(np.arange(1, 25), venues_per_day, replace=False)
        for jcd in venues:
            wind = float(np.clip(rng.gamma(2, 1.2), 0, 12))
            for rno in range(1, races_per_venue + 1):
                rid = f"{d:%Y%m%d}{jcd:02d}{rno:02d}"
                ids = rng.choice(n_racers, 6, replace=False)
                # 1号艇に上位級が入りやすい番組編成
                if rno >= 9:
                    ids = ids[np.argsort(-skill[ids] + rng.normal(0, 0.4, 6))]
                motors = rng.choice(60, 6, replace=False)
                mq = motor_q[jcd][motors]
                ex_time = 6.80 - 0.05 * mq - 0.01 * (weight[ids] - 52) / 3 + rng.normal(0, 0.035, 6)
                st = np.clip(st_skill[ids] + rng.normal(0, 0.04, 6), 0.01, 0.40)
                lane_eff = LANE_BASE.copy()
                lane_eff[0] += venue_in[jcd] - 0.04 * wind
                true_s = lane_eff + 1.0 * skill[ids] + 0.6 * mq - 3.0 * (st - 0.15) + rng.normal(0, 0.15, 6)
                g = rng.gumbel(size=6)
                order = np.argsort(-(true_s + g))
                finish = np.empty(6, int)
                finish[order] = np.arange(1, 7)
                # 市場(オッズ)は真の強さをノイズ+人気バイアス付きで見積もる
                mkt_s = true_s + rng.normal(0, 0.35, 6) + 0.25 * (cls[ids] == "A1")
                p_win = np.exp(mkt_s) / np.exp(mkt_s).sum()
                tri = pl_trifecta_matrix(p_win)
                exa = pl_exacta_matrix(p_win)
                a, b, c = order[:3]
                race_rows.append(dict(
                    race_id=rid, date=d.strftime("%Y-%m-%d"), jcd=int(jcd), rno=rno,
                    wind=round(wind, 1), wave=int(wind // 2),
                    tri_combo=f"{a+1}-{b+1}-{c+1}", tri_pay=int(max(100, round(75 / tri[a, b, c], -1))),
                    exa_combo=f"{a+1}-{b+1}", exa_pay=int(max(100, round(75 / exa[a, b], -1))),
                    win_lane=int(a + 1), win_pay=int(max(100, round(75 / p_win[a], -1))),
                ))
                for k in range(6):
                    r = ids[k]
                    ent_rows.append(dict(
                        race_id=rid, date=d.strftime("%Y-%m-%d"), jcd=int(jcd), rno=rno, lane=k + 1,
                        racer_id=int(4000 + r), racer_class=cls[r], weight=round(weight[r], 1),
                        nat_win_rate=round(float(np.clip(5.5 + 2.2 * skill[r] + rng.normal(0, 0.3), 1, 9)), 2),
                        nat_2rate=round(float(np.clip(35 + 25 * skill[r] + rng.normal(0, 4), 0, 90)), 2),
                        loc_win_rate=round(float(np.clip(5.5 + 2.2 * skill[r] + rng.normal(0, 0.9), 0, 10)), 2),
                        loc_2rate=round(float(np.clip(35 + 25 * skill[r] + rng.normal(0, 10), 0, 100)), 2),
                        motor_no=int(motors[k] + 1),
                        motor_2rate=round(float(np.clip(33 + 20 * mq[k] + rng.normal(0, 5), 0, 80)), 2),
                        boat_2rate=round(float(np.clip(33 + rng.normal(0, 6), 0, 80)), 2),
                        exhibit_time=round(float(ex_time[k]), 2),
                        course=k + 1, st=round(float(st[k]), 2),
                        finish=int(finish[k]),
                    ))
    return pd.DataFrame(ent_rows), pd.DataFrame(race_rows)
