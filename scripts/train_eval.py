"""学習と検証(バックテスト)をまとめて実行する。

使い方:
  python scripts/train_eval.py --synthetic        # サンプルデータで動作確認
  python scripts/train_eval.py                    # data/entries.csv.gz, data/races.csv.gz を使用

期間を「学習 60% / 検証 20%(アンサンブル重み・補正の学習)/ テスト 20%」に
時系列で分け、未来のデータで過去を予想しないようにして評価する。
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
from kyotei.ensemble import Stacker, evaluate  # noqa: E402
from kyotei.models import available_models, race_softmax  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(args):
    if args.synthetic:
        from kyotei.synthetic import generate
        return generate(n_days=args.days, seed=1)
    ent = pd.read_csv(ROOT / "data/entries.csv.gz", dtype={"race_id": str})
    races = pd.read_csv(ROOT / "data/races.csv.gz", dtype={"race_id": str})
    return ent, races


def lane_baseline(train: pd.DataFrame, df: pd.DataFrame) -> np.ndarray:
    rate = train.assign(w=(train["finish"] == 1)).groupby(["jcd", "lane"])["w"].mean()
    p = df.set_index(["jcd", "lane"]).index.map(rate).to_numpy(dtype=float)
    p = np.nan_to_num(p, nan=1 / 6)
    return race_softmax(np.log(p + 1e-6), df["race_id"].values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--days", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "models"))
    args = ap.parse_args()
    t0 = time.time()

    ent, races = load(args)
    df = features.build(ent, races)
    rating_model = df.attrs.get("rating_model")
    df = df[df["finish"].notna()].reset_index(drop=True)
    feats = features.feature_columns(df)
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    tr, va, te = df[df.date < d1], df[(df.date >= d1) & (df.date < d2)], df[df.date >= d2]
    print(f"rows={len(df)} feats={len(feats)} train={tr.race_id.nunique()} "
          f"val={va.race_id.nunique()} test={te.race_id.nunique()} races")

    models = {}
    for M in available_models():
        m = M(feats).fit(tr)
        models[m.name] = m
        print(f"  fitted {m.name} ({time.time()-t0:.0f}s)")

    pv = {k: m.predict_proba(va) for k, m in models.items()}
    pt = {k: m.predict_proba(te) for k, m in models.items()}
    stack = Stacker().fit(va, pv)
    print("  stack weights:", stack.weights(), "lam:", round(stack.lam2, 3), round(stack.lam3, 3))

    report = {"generated_at": pd.Timestamp.now(tz="Asia/Tokyo").isoformat(timespec="minutes"),
              "synthetic": bool(args.synthetic),
              "period": {"train": [str(tr.date.min()), str(tr.date.max())],
                         "test": [str(te.date.min()), str(te.date.max())]},
              "models": {}}
    ev = te[["race_id", "lane", "finish"]].copy()
    ev["p"] = lane_baseline(tr, te)
    report["models"]["baseline_lane"] = evaluate(ev, races, "p")
    for k, p in pt.items():
        ev["p"] = p
        report["models"][k] = evaluate(ev, races, "p")
    ev["p"] = stack.predict(te, pt)
    report["models"]["ensemble"] = evaluate(ev, races, "p", stack.lam2, stack.lam3)
    report["ensemble"] = {"weights": {k: float(v) for k, v in stack.weights().items()},
                          "lam2": stack.lam2, "lam3": stack.lam3}

    show = ["win_logloss", "win_hit", "tri_logloss", "tri_hit_top1", "tri_hit_top5",
            "roi_win_top1", "roi_tri_top1", "roi_tri_top5", "roi_tri_top1_confident"]
    print(pd.DataFrame(report["models"]).T[show].to_string())

    # 本番用: 学習+検証期間で各モデルを学習し直す(重みと補正は検証で決めたものを使う)
    full = pd.concat([tr, va])
    for k in models:
        models[k] = type(models[k])(feats).fit(full)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "bundle.pkl", "wb") as f:
        pickle.dump({"feats": feats, "models": models, "stack": stack,
                     "rating": rating_model}, f)
    rep_path = ROOT / "docs/data/report.json"
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
