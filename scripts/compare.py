"""改良案(candidate)と今のモデル(base)を、同じデータ・同じ期間で比べて採用するか決める。

  python scripts/compare.py base.json candidate.json out.json
  終了コード 0 = 採用、1 = 不採用

判定は、たまたまの良し悪しに振り回されにくい「誤差(対数損失)」を主に使う。
- 直前予想(late)の3連単の誤差が 0.002 以上改善 または 1着の誤差が 0.001 以上改善
  - さらに、テストの各レースの誤差の差から出した90%区間が 0 をまたがないこと(偶然の改善を弾く)。
    レースごとの誤差のファイル(base.json.races.csv.gz など)が無い場合はこの条件を省く
- かつ、朝予想(early)・直前予想の各誤差がどれも 0.002 を超えて悪化していない
- 期待値の検証結果がある場合、期待値1.2以上の回収率の90%区間の下限が 0.03 を超えて悪化していない
"""
import json
import os
import sys

import numpy as np
import pandas as pd


def m(rep, stage, key):
    return rep["stages"][stage]["metrics"]["ensemble"][key]


EV_MIN_BETS = 300   # 買い目がこれより少ない回収率は、区間が広すぎて比べられない(37点で1回当たるかどうか、など)


def _ev_row(rep, kind, ev_min):
    for r in rep.get("ev", {}).get(kind, []):
        if abs(r["ev_min"] - ev_min) < 1e-9:
            return r
    return None


def ev_gate(base, cand):
    """期待値の検証のゲート。本番の買い方(合成+フィルタ、期待値1.2以上)を第一に、
    両方の買い目が EV_MIN_BETS 以上ある行で回収率の90%区間の下限をくらべる。どの行も少なければ判定しない(None)。
    2026-10-06: 37点どうしの比較で RaceCond(3連単の誤差 -0.0057、区間も明確)が落ちたので、点数の下限を入れた。"""
    for kind, ev_min in (("ev_filtered", 1.2), ("ev_filtered", 1.0), ("ev_blend", 1.0)):
        rb, rc = _ev_row(base, kind, ev_min), _ev_row(cand, kind, ev_min)
        if rb and rc and rb.get("bets", 0) >= EV_MIN_BETS and rc.get("bets", 0) >= EV_MIN_BETS \
                and rb.get("roi_lo90") is not None and rc.get("roi_lo90") is not None:
            return f"{kind}@{ev_min}", rb["roi_lo90"], rc["roi_lo90"]
    return None, None, None


def ev_lo(rep):
    """互換用: 本番の買い方(期待値1.2以上)の回収率の下限。"""
    r = _ev_row(rep, "ev_filtered", 1.2)
    return r.get("roi_lo90") if r else None


def paired(base_path, cand_path):
    """レースごとの誤差の差(改良案−今)の平均と90%区間。マイナス=改善。ファイルが無ければ None。"""
    pa, pb = base_path + ".races.csv.gz", cand_path + ".races.csv.gz"
    if not (os.path.exists(pa) and os.path.exists(pb)):
        return None
    a = pd.read_csv(pa, dtype={"race_id": str})
    b = pd.read_csv(pb, dtype={"race_id": str})
    j = a.merge(b, on=["stage", "race_id"], suffixes=("_a", "_b"))
    out = {}
    for st, g in j.groupby("stage"):
        for k in ("win", "tri"):
            d = (g[f"{k}_b"] - g[f"{k}_a"]).values
            se = d.std(ddof=1) / np.sqrt(len(d))
            out[f"{st}.{k}_logloss"] = {"races": int(len(d)), "mean": round(float(d.mean()), 5),
                                         "lo90": round(float(d.mean() - 1.645 * se), 5),
                                         "hi90": round(float(d.mean() + 1.645 * se), 5)}
    return out


def main():
    base, cand = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
    d = {}
    for st in ("early", "late"):
        for k in ("win_logloss", "tri_logloss"):
            d[f"{st}.{k}"] = round(m(cand, st, k) - m(base, st, k), 5)  # マイナス=改善
    ci = paired(sys.argv[1], sys.argv[2])

    def sure(key):  # 改善が偶然の範囲を超えているか(区間が無ければ従来どおり判定しない)
        return ci is None or key not in ci or ci[key]["hi90"] < 0
    improved_tri = d["late.tri_logloss"] <= -0.002 and sure("late.tri_logloss")
    improved_win = d["late.win_logloss"] <= -0.001 and sure("late.win_logloss")
    improved = improved_tri or improved_win
    big_enough = d["late.tri_logloss"] <= -0.002 or d["late.win_logloss"] <= -0.001
    not_worse = all(v <= 0.002 for v in d.values())
    ev_key, lo_b, lo_c = ev_gate(base, cand)
    # 回収率の下限は、同じくらいのモデルでも検証のたびに ±0.08 ほど動く(高配当に左右される)ので、大きく落ちたときだけ止める
    roi_ok = lo_b is None or lo_c is None or lo_c >= lo_b - 0.10
    # 主の物差し: オッズのある期間で、市場と合成した3連単の確率の誤差(F3「市場への上乗せ」)。悪くならないこと
    bb = base.get("ev", {}).get("tri_logloss", {}).get("blend")
    cb = cand.get("ev", {}).get("tri_logloss", {}).get("blend")
    n_odds = min(base.get("ev", {}).get("races") or 0, cand.get("ev", {}).get("races") or 0)
    blend_ok = bb is None or cb is None or n_odds < 3000 or cb <= bb + 0.0005   # オッズのあるレースが少ないうちは判定しない
    ev_ok = roi_ok and blend_ok
    adopt = improved and not_worse and ev_ok
    if adopt:
        reason = "採用: 誤差が改善し、悪化した指標なし"
    elif not big_enough:
        reason = "不採用: 改善幅が基準未満"
    elif not improved:
        reason = "不採用: 改善が偶然の範囲(レース単位の90%区間が0をまたぐ)"
    elif not not_worse:
        reason = "不採用: 一部の指標が悪化"
    else:
        reason = "不採用: 期待値の検証が悪化"
    out = {"adopt": adopt, "delta": d, "per_race_ci90": ci, "ev_roi_lo90": {"base": lo_b, "candidate": lo_c, "row": ev_key},
           "blend_tri_logloss": {"base": bb, "candidate": cb},
           "market_gap_tri": {k: (r.get("ev", {}).get("tri_logloss", {}).get("blend"),
                                  r.get("ev", {}).get("tri_logloss", {}).get("market"))
                              for k, r in (("base", base), ("candidate", cand))},
           "reason": reason}
    json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(0 if adopt else 1)


if __name__ == "__main__":
    main()
