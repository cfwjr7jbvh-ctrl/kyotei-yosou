"""学習と検証(バックテスト)をまとめて実行する。

  python scripts/train_eval.py --synthetic   # サンプルデータで動作確認
  python scripts/train_eval.py               # data/history の実データ

- 期間を「学習60% / 検証20% / テスト20%」に時系列で分割(未来で過去を予想しない)
- 2段階のモデルを作る
    early: 朝の予想(番組表+過去成績だけ)
    late : 直前予想(展示タイム・進入コース・風・波も使う)
- 各モデル → アンサンブル → 3連単確率 の順に評価し、docs/data/report.json に保存
- オッズがある期間では、市場確率との合成と「期待値で買った場合」の回収率も検証
"""
from __future__ import annotations

import argparse
import json
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyotei import features  # noqa: E402
from kyotei.betting import (COMBOS, backtest_ev, blend, fit_blend, market_probs,  # noqa: E402
                            model_tri_probs, odds_matrix)
from kyotei.ensemble import Stacker, evaluate  # noqa: E402
from kyotei.models import available_models, race_softmax  # noqa: E402
from kyotei.publish import write_json  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_history():
    H = ROOT / "data/history"
    ent = pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in sorted(H.glob("entries_*.csv.gz"))])
    races = pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in sorted(H.glob("races_*.csv.gz"))])
    odds_files = sorted((ROOT / "data/odds").glob("odds3t_*.csv.gz"))
    odds = (pd.concat([pd.read_csv(p, dtype={"race_id": str}) for p in odds_files])
            if odds_files else None)
    return ent, races, odds


def lane_baseline(train, df):
    rate = train.assign(w=(train["finish"] == 1)).groupby(["jcd", "lane"])["w"].mean()
    p = df.set_index(["jcd", "lane"]).index.map(rate).to_numpy(dtype=float)
    return race_softmax(np.log(np.nan_to_num(p, nan=1 / 6) + 1e-6), df["race_id"].values)


def win_matrix(df, p, race_ids):
    d = df[["race_id", "lane"]].assign(p=p)
    return (d.pivot(index="race_id", columns="lane", values="p")
            .reindex(index=race_ids, columns=range(1, 7)).fillna(1e-6).values)


def run_stage(stage, df, races, tr, va, te, report, log):
    feats = features.feature_columns(df, stage)
    log(f"[{stage}] features={len(feats)}")
    models = {}
    for M in available_models():
        models[M.name] = M(feats).fit(tr)
        log(f"  fitted {M.name}")
    pv = {k: m.predict_proba(va) for k, m in models.items()}
    pt = {k: m.predict_proba(te) for k, m in models.items()}
    stack = Stacker().fit(va, pv)
    res = {}
    ev = te[["race_id", "lane", "finish"]].copy()
    ev["p"] = lane_baseline(tr, te)
    res["baseline_lane"] = evaluate(ev, races, "p")
    for k, p in pt.items():
        ev["p"] = p
        res[k] = evaluate(ev, races, "p")
    p_ens = stack.predict(te, pt)
    ev["p"] = p_ens
    res["ensemble"] = evaluate(ev, races, "p", stack.lam2, stack.lam3)
    report["stages"][stage] = {
        "n_features": len(feats), "metrics": res,
        "ensemble_weights": {k: float(v) for k, v in stack.weights().items()},
        "lam2": stack.lam2, "lam3": stack.lam3}
    gb = models.get("gbdt_win")
    if gb is not None and hasattr(gb.m, "feature_importances_"):
        imp = pd.Series(gb.m.feature_importances_, index=feats).sort_values(ascending=False)
        report["stages"][stage]["top_features"] = {k: int(v) for k, v in imp.head(20).items()}
    show = ["win_logloss", "win_hit", "tri_logloss", "tri_hit_top1", "tri_hit_top5",
            "roi_win_top1", "roi_tri_top1", "roi_tri_top5"]
    log(pd.DataFrame(res).T[show].to_string())
    return feats, models, stack, p_ens


def ev_analysis(te, p_ens, stack, races, odds, report, log):
    rids = np.sort(te["race_id"].unique())
    O = odds_matrix(odds, rids)
    has = np.isfinite(O).sum(1) >= 100
    rc = races.set_index("race_id").reindex(rids)
    ok = has & rc["tri_combo"].isin(COMBOS).values & rc["tri_pay"].notna().values
    if ok.sum() < 300:
        log(f"odds races in test: {ok.sum()} (too few for EV analysis)")
        return None
    rids, O = rids[ok], O[ok]
    rc = rc.loc[rids]
    W = win_matrix(te, p_ens, rids)
    PM = np.array([model_tri_probs(w, stack.lam2, stack.lam3) for w in W])
    PK = np.array([market_probs(o) for o in O])
    y = np.array([COMBOS.index(c) for c in rc["tri_combo"]])
    pay = rc["tri_pay"].values.astype(float)
    half = len(rids) // 2  # 前半でブレンド係数を推定、後半で検証
    a, b = fit_blend(PM[:half], PK[:half], y[:half])
    PB = blend(PM, PK, a, b)
    r = np.arange(len(y))
    sl = slice(half, None)
    out = {"races": int(len(rids) - half), "period": [str(rids[half][:8]), str(rids[-1][:8])],
           "blend_a_model": round(a, 3), "blend_b_market": round(b, 3),
           "tri_logloss": {"model": float(-np.log(PM[r, y] + 1e-12)[sl].mean()),
                           "market": float(-np.log(PK[r, y] + 1e-12)[sl].mean()),
                           "blend": float(-np.log(PB[r, y] + 1e-12)[sl].mean())},
           "ev_model": backtest_ev(PM[sl], O[sl], y[sl], pay[sl]),
           "ev_blend": backtest_ev(PB[sl], O[sl], y[sl], pay[sl])}
    log(json.dumps(out, ensure_ascii=False, indent=1))
    report["ev"] = out
    return a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--days", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "models"))
    args = ap.parse_args()
    t0 = time.time()

    def log(*a):
        print(f"[{time.time()-t0:5.0f}s]", *a, flush=True)

    if args.synthetic:
        from kyotei.synthetic import generate
        ent, races = generate(n_days=args.days, seed=1)
        odds = None
    else:
        ent, races, odds = load_history()
    df = features.build(ent, races)
    ok_races = df.groupby("race_id")["finish"].apply(lambda s: (s <= 3).sum() == 3)
    df = df[df["race_id"].isin(ok_races[ok_races].index)].reset_index(drop=True)
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    tr, va, te = df[df.date < d1], df[(df.date >= d1) & (df.date < d2)], df[df.date >= d2]
    log(f"rows={len(df)} races train={tr.race_id.nunique()} val={va.race_id.nunique()} "
        f"test={te.race_id.nunique()}")
    report = {"generated_at": pd.Timestamp.now(tz="Asia/Tokyo").isoformat(timespec="minutes"),
              "synthetic": bool(args.synthetic),
              "period": {"train": [str(tr.date.min()), str(tr.date.max())],
                         "val": [str(va.date.min()), str(va.date.max())],
                         "test": [str(te.date.min()), str(te.date.max())]},
              "stages": {}}
    bundle = {"stages": {}, "blend": None}
    for stage in ("early", "late"):
        feats, models, stack, p_ens = run_stage(stage, df, races, tr, va, te, report, log)
        if stage == "late" and odds is not None:
            bundle["blend"] = ev_analysis(te, p_ens, stack, races, odds, report, log)
        # 本番用: 学習+検証期間で学習し直す(アンサンブル重み・補正は検証で決めた値)
        full = pd.concat([tr, va])
        for k in models:
            models[k] = type(models[k])(feats).fit(full)
        bundle["stages"][stage] = {"feats": feats, "models": models, "stack": stack}
        log(f"[{stage}] refit done")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bundle["built_at"] = report["generated_at"]
    with open(out / "bundle.pkl", "wb") as f:
        pickle.dump(bundle, f)
    rep = ROOT / "docs/data/report.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    write_json(rep, report)
    log("done")


if __name__ == "__main__":
    main()
