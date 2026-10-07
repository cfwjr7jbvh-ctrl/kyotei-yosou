"""潮位(data/tide、scripts/fetch_tide.py が気象庁の潮位表から集める)を、レースの締切時刻に当てる。

tide_for(df) は df(jcd, date, deadline)に次の列を足す:
  tide_cm      締切時刻の潮位(cm、観測点の基準面から。場ごとに高さの基準が違うので、比べるときは tide_rel を使う)
  tide_rel     その日の満潮と干潮のあいだで、どのあたりか(0=干潮の高さ、1=満潮の高さ)
  tide_trend   1時間あたりの変化(cm/時。+ は満ちている、- は引いている)
  tide_range   その日の潮の満ち引きの大きさ(最高−最低、cm)。大きい日が大潮のころ
  tide_kind    「満ち潮」「引き潮」「満潮のころ」「干潮のころ」(満潮・干潮の前後1時間はそのころ)
淡水の場(data/tide/stations.json の water)と、近くに観測点が無い場は空のまま。
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
TIDE = ROOT / "data/tide"


def load() -> tuple[pd.DataFrame, dict]:
    fs = sorted(TIDE.glob("tide_*.csv.gz"))
    st = json.loads((TIDE / "stations.json").read_text(encoding="utf-8")) if (TIDE / "stations.json").exists() else {}
    if not fs:
        return pd.DataFrame(), st
    return pd.concat([pd.read_csv(f) for f in fs], ignore_index=True).drop_duplicates(["date", "code"]), st


def tide_for(df: pd.DataFrame, include_fresh: bool = False) -> pd.DataFrame:
    t, st = load()
    out = df.copy()
    for c in ("tide_cm", "tide_rel", "tide_trend", "tide_range"):
        out[c] = np.nan
    out["tide_kind"] = None
    if t.empty or not st:
        return out
    code = {int(j): v.get("code") for j, v in st.items() if v.get("code") and (include_fresh or v.get("water") != "淡水")}
    out["_code"] = out["jcd"].astype(int).map(code)
    hcols = [f"h{i:02d}" for i in range(24)]
    tt = t.set_index(["date", "code"])
    key = list(zip(out["date"].astype(str).str[:10], out["_code"]))
    ok = [k in tt.index for k in key]
    if not any(ok):
        return out.drop(columns="_code")
    sub = tt.loc[[k for k, o in zip(key, ok) if o]]
    H = sub[hcols].to_numpy(dtype=float)
    dl = out.loc[ok, "deadline"].astype(str)
    mins = dl.str.slice(0, 2).astype(float).to_numpy() * 60 + dl.str.slice(3, 5).astype(float).to_numpy()
    x = np.clip(mins / 60.0, 0, 23)
    i0 = np.floor(x).astype(int)
    i1 = np.minimum(i0 + 1, 23)
    w = x - i0
    r = np.arange(len(H))
    h = H[r, i0] * (1 - w) + H[r, i1] * w
    trend = H[r, i1] - H[r, i0]
    lo, hi = H.min(axis=1), H.max(axis=1)
    idx = np.where(ok)[0]
    out.iloc[idx, out.columns.get_loc("tide_cm")] = h
    out.iloc[idx, out.columns.get_loc("tide_trend")] = trend
    out.iloc[idx, out.columns.get_loc("tide_range")] = hi - lo
    out.iloc[idx, out.columns.get_loc("tide_rel")] = (h - lo) / np.maximum(hi - lo, 1)
    # 満潮・干潮のころ(前後60分)
    kinds = []
    for (_, row), m in zip(sub.iterrows(), mins):
        k = None
        for kind, word in (("hi", "満潮のころ"), ("lo", "干潮のころ")):
            for n in range(1, 5):
                tv = row.get(f"{kind}{n}_t")
                if isinstance(tv, str) and ":" in tv:
                    tm = int(tv[:2]) * 60 + int(tv[3:5])
                    if abs(tm - m) <= 60:
                        k = word
        kinds.append(k)
    kk = np.array(kinds, dtype=object)
    tr = trend
    kk = np.where(kk == None, np.where(tr > 0, "満ち潮", "引き潮"), kk)  # noqa: E711
    out.iloc[idx, out.columns.get_loc("tide_kind")] = kk
    return out.drop(columns="_code")
