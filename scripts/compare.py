"""改良案(candidate)と今のモデル(base)を、同じデータ・同じ期間で比べて採用するか決める。

  python scripts/compare.py base.json candidate.json out.json
  終了コード 0 = 採用、1 = 不採用

判定は、たまたまの良し悪しに振り回されにくい「誤差(対数損失)」を主に使う。
- 直前予想(late)の3連単の誤差が 0.002 以上改善 または 1着の誤差が 0.001 以上改善
- かつ、朝予想(early)・直前予想の各誤差がどれも 0.002 を超えて悪化していない
- 期待値の検証結果がある場合、期待値1.2以上の回収率の90%区間の下限が 0.03 を超えて悪化していない
"""
import json
import sys


def m(rep, stage, key):
    return rep["stages"][stage]["metrics"]["ensemble"][key]


def ev_lo(rep):
    for r in rep.get("ev", {}).get("ev_filtered", []):
        if abs(r["ev_min"] - 1.2) < 1e-9:
            return r.get("roi_lo90")
    return None


def main():
    base, cand = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
    d = {}
    for st in ("early", "late"):
        for k in ("win_logloss", "tri_logloss"):
            d[f"{st}.{k}"] = round(m(cand, st, k) - m(base, st, k), 5)  # マイナス=改善
    improved = d["late.tri_logloss"] <= -0.002 or d["late.win_logloss"] <= -0.001
    not_worse = all(v <= 0.002 for v in d.values())
    lo_b, lo_c = ev_lo(base), ev_lo(cand)
    ev_ok = lo_b is None or lo_c is None or lo_c >= lo_b - 0.03
    adopt = improved and not_worse and ev_ok
    out = {"adopt": adopt, "delta": d, "ev_roi_lo90": {"base": lo_b, "candidate": lo_c},
           "reason": ("採用: 誤差が改善し、悪化した指標なし" if adopt else
                      "不採用: " + ("改善幅が基準未満" if not improved else
                                  "一部の指標が悪化" if not not_worse else "期待値の検証が悪化"))}
    json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(0 if adopt else 1)


if __name__ == "__main__":
    main()
