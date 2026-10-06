"""予想屋(X・note)の買い目を追いかけて、回収率が本物かを自分たちの結果データで確かめる。

使い方:
  1. data/tipsters/picks.csv に、締切前に公開された買い目を1行ずつ書く(手でコピーでよい)
       tipster,posted_at,race_id,combos,stake
       わさび,2026-10-06 14:55,202610061210,1-3-2 1-3-4 1-2-3,100
     - race_id は YYYYMMDD + 場コード2桁 + レース番号2桁
     - combos は3連単をスペース区切り。stake は1点あたりの金額(省略なら100円)
     - posted_at は投稿の時刻(後出しを見分けるための記録。締切後なら数えない)
  2. python scripts/tipster_track.py            → 予想屋ごとの回収率と「運だけで出る幅」を表示
     python scripts/tipster_track.py --luck     → 買い目データなしで、運だけで130%を超える確率の表を出す

見るところ:
  - 回収率と、その「ブレの幅」(同じ買い方を同じ回数くりかえしたとき、運だけでこのくらい上下する)
  - 「人気から考えると◯本 → 実際◯本」: 市場(オッズ)の見立てより当てているか。ここがプラスなら本物の可能性
  - 300レースを超えるまでは「追試中」。100レース前後の回収率は、運だけで60%〜190%くらい動く
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.data import _read  # noqa: E402

PICKS = ROOT / "data/tipsters/picks.csv"


def load_market(since: str | None = None):
    """レースごとの3連単オッズ(人気順位つき)と結果。"""
    odds = _read("odds/odds3t_*.csv.gz", since)
    races = _read("history/races_*.csv.gz", since)
    races = races.dropna(subset=["tri_combo", "tri_pay"]).drop_duplicates("race_id")
    odds = odds[odds["race_id"].isin(races["race_id"])].drop_duplicates(["race_id", "combo"])
    odds = odds.sort_values(["race_id", "odds"]).reset_index(drop=True)
    odds["rank"] = odds.groupby("race_id").cumcount() + 1
    inv = odds.groupby("race_id")["odds"].transform(lambda s: (1 / s).sum())
    odds["p_market"] = (1 / odds["odds"]) / inv            # 控除を除いた、市場の見立て(確率)
    win = races.set_index("race_id")[["tri_combo", "tri_pay"]]
    odds = odds.join(win, on="race_id")
    odds["hit"] = odds["combo"] == odds["tri_combo"]
    return odds, races


def luck_table(odds: pd.DataFrame, rng=None):
    """買い目データなしで、「同じ人気順位を機械的に買う」人の1年の回収率が運だけでどう散るか。"""
    rng = rng or np.random.default_rng(0)
    piv = odds.pivot(index="race_id", columns="rank", values="odds")
    hitrank = odds[odds["hit"]].set_index("race_id")["rank"].reindex(piv.index).values
    pay = odds.drop_duplicates("race_id").set_index("race_id")["tri_pay"].reindex(piv.index).values
    strats = {"1番人気だけ(1点)": [1], "1〜3番人気(3点)": [1, 2, 3], "1〜5番人気(5点)": [1, 2, 3, 4, 5],
              "6〜15番人気(10点)": list(range(6, 16)), "10番人気を1点": [10], "20番人気を1点": [20], "40番人気を1点": [40]}
    rows = []
    for name, rk in strats.items():
        hit = np.isin(hitrank, rk)
        ret = np.where(hit, pay, 0.0)
        inv = np.full(len(hitrank), 100.0 * len(rk))
        for n in (100, 300, 1000):
            idx = rng.integers(0, len(hitrank), (3000, n))
            sims = ret[idx].sum(axis=1) / inv[idx].sum(axis=1)
            p130 = (sims >= 1.3).mean()
            rows.append({"買い方": name, "1年のレース数": n, "回収率(全体)": f"{ret.sum() / inv.sum() * 100:.0f}%",
                         "運だけのブレ(SD)": f"{sims.std() * 100:.0f}pt", "130%超え": f"{p130 * 100:.1f}%",
                         "100人いれば誰か130%超え": f"{(1 - (1 - p130) ** 100) * 100:.0f}%",
                         "上位5%の人の回収率": f"{np.percentile(sims, 95) * 100:.0f}%"})
    return pd.DataFrame(rows)


def evaluate(picks: pd.DataFrame, odds: pd.DataFrame, rng=None) -> pd.DataFrame:
    rng = rng or np.random.default_rng(0)
    picks = picks.copy()
    picks["race_id"] = picks["race_id"].astype(str)
    picks["stake"] = pd.to_numeric(picks.get("stake", 100), errors="coerce").fillna(100)
    rows = []
    for _, p in picks.iterrows():
        for c in str(p["combos"]).replace(",", " ").split():
            rows.append({"tipster": p["tipster"], "race_id": p["race_id"], "combo": c.strip(), "stake": p["stake"],
                         "posted_at": p.get("posted_at", "")})
    bets = pd.DataFrame(rows).merge(odds[["race_id", "combo", "odds", "rank", "p_market", "hit", "tri_pay"]],
                                    on=["race_id", "combo"], how="left")
    missing = bets["odds"].isna().sum()
    if missing:
        print(f"注意: オッズか結果が見つからない買い目が {missing} 点(レースIDか組番を確認)")
    bets = bets.dropna(subset=["odds"])
    bets["ret"] = np.where(bets["hit"], bets["tri_pay"] * bets["stake"] / 100, 0.0)
    out = []
    for name, g in bets.groupby("tipster"):
        n_race = g["race_id"].nunique()
        inv, ret = g["stake"].sum(), g["ret"].sum()
        roi = ret / inv if inv else float("nan")
        # ブレの幅: レース単位でブートストラップ
        per_race = g.groupby("race_id").agg(inv=("stake", "sum"), ret=("ret", "sum"))
        idx = rng.integers(0, len(per_race), (3000, len(per_race)))
        sims = per_race["ret"].values[idx].sum(axis=1) / per_race["inv"].values[idx].sum(axis=1)
        lo, hi = np.percentile(sims, [5, 95])
        # 市場の見立て(人気から考えると何本当たるか)
        exp_hits = g["p_market"].sum()
        hits = int(g["hit"].sum())
        # 運だけでこの回収率になる確率: 同じ人気順位を、ランダムなレースで買ったら
        ranks = g["rank"].astype(int).values
        pool = odds.groupby("rank")
        sim_roi = []
        for _ in range(1000):
            tot = 0.0
            for rk in ranks:
                grp = pool.get_group(rk) if rk in pool.groups else None
                if grp is None or len(grp) == 0:
                    continue
                row = grp.iloc[rng.integers(0, len(grp))]
                tot += row["tri_pay"] if row["hit"] else 0.0
            sim_roi.append(tot / (100.0 * len(ranks)))
        sim_roi = np.array(sim_roi)
        p_luck = (sim_roi >= roi).mean()
        verdict = "追試中(300レース未満)" if n_race < 300 else ("本物の可能性あり" if p_luck < 0.05 and hits > exp_hits else "運の幅の中")
        out.append({"予想屋": name, "レース数": n_race, "点数": len(g), "的中": hits, "回収率": f"{roi * 100:.0f}%",
                    "ブレの幅(90%)": f"{lo * 100:.0f}〜{hi * 100:.0f}%", "人気から考えると→実際": f"{exp_hits:.1f}本→{hits}本",
                    "運だけでこうなる確率": f"{p_luck * 100:.1f}%", "いまの見立て": verdict})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", default=str(PICKS))
    ap.add_argument("--since", default="202512", help="オッズを読む最初の月(YYYYMM)")
    ap.add_argument("--luck", action="store_true", help="買い目なしで、運だけの表を出す")
    a = ap.parse_args()
    odds, _ = load_market(a.since)
    pd.set_option("display.width", 200)
    pd.set_option("display.unicode.east_asian_width", True)
    if a.luck:
        print(luck_table(odds).to_string(index=False))
        return
    p = pathlib.Path(a.picks)
    if not p.exists():
        print(f"{p} がありません。先頭行: tipster,posted_at,race_id,combos,stake")
        return
    picks = pd.read_csv(p, dtype={"race_id": str})
    print(evaluate(picks, odds).to_string(index=False))


if __name__ == "__main__":
    main()
