"""確率モデルの「試し部屋」。いろいろな案を手元でざっと比べる(改良案 J・D18・D19 の下ごしらえ)。

  python scripts/model_lab.py build                 # 特徴量を1回作って保存(2分ほど)
  python scripts/model_lab.py run <実験名> [...]     # 実験を走らせる(下の EXPERIMENTS)
  python scripts/model_lab.py list

仕組み: 本番と同じ期間分割(日付で 60/20/20。学習+検証で学び、テストで測る)。
直前予想(late)の GBDT 1本(乱数1回)を「今の特徴量」と「案の特徴量」で学び、
テストの各レースの1着の対数損失の差と、その90%区間を出す(区間が0をまたがなければ偶然ではなさそう)。
本番の train_eval.py(アンサンブル・3連単)より荒いが、数分で答えが出る。見込みのある案だけ exp/ ブランチに。
結果は非公開の mikata-lab の model_lab/<実験名>.json に残す(無ければ out/model_lab)。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import features  # noqa: E402

CACHE = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "build" else None
CACHE_DIR = pathlib.Path(__import__("os").environ.get("MODEL_LAB_CACHE", "/tmp/model_lab"))
# 結果はノウハウなので公開リポジトリに置かない(2026-10-07)。非公開の mikata-lab があればそこへ、無ければ out/(commit されない)
_LAB = pathlib.Path(__import__("os").environ.get("MIKATA_LAB", "/home/claude/mikata-lab"))
OUT = pathlib.Path(__import__("os").environ.get("MODEL_LAB_OUT") or (_LAB / "model_lab" if _LAB.exists() else ROOT / "out/model_lab"))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def build():
    from kyotei.data import load_history
    ent, races, _ = load_history()
    df = features.build(ent, races)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_pickle(CACHE_DIR / "feat.pkl")
    races.to_pickle(CACHE_DIR / "races.pkl")
    log("saved", df.shape)


def load():
    df = pd.read_pickle(CACHE_DIR / "feat.pkl")
    ok = (df["finish"] <= 3).groupby(df["race_id"]).transform("sum") == 3
    df = df[ok].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    days = np.sort(df["date"].unique())
    d1, d2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    df["split"] = np.where(df["date"] <= d1, "train", np.where(df["date"] <= d2, "valid", "test"))
    df["win"] = (df["finish"] == 1).astype(int)
    # メモリを節約(8GB の手元でも動くように): 使わない文字列の列を落とし、小数は32ビットに
    keep_obj = {"race_id", "racer_id", "split", "st_flag", "racer_class", "deadline", "result_code"}
    df = df[[c for c in df.columns if c in keep_obj or c == "date" or pd.api.types.is_numeric_dtype(df[c])]]
    for c in df.columns:
        if df[c].dtype == np.float64:
            df[c] = df[c].astype(np.float32)
    log("rows", len(df), "races", df["race_id"].nunique(), "test from", str(pd.Timestamp(d2).date()))
    return df


def gbdt(seed=0, **kw):
    p = dict(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=50, l2_regularization=1.0, random_state=seed)
    p.update(kw)
    return HistGradientBoostingClassifier(**p)


def race_probs(df, score):
    s = pd.Series(np.asarray(score, dtype=float), index=df.index)
    m = s.groupby(df["race_id"]).transform("max")
    e = np.exp(s - m)
    return (e / e.groupby(df["race_id"]).transform("sum")).values


def win_logloss_per_race(df, p):
    d = df.assign(p=np.clip(p, 1e-6, 1))
    w = d[d["win"] == 1].groupby("race_id")["p"].first()  # 同着は先の枠
    return -np.log(w)


def fit_predict(df, feats, label="win", seed=0):
    tr = df[df["split"] != "test"]
    te = df[df["split"] == "test"]
    m = gbdt(seed).fit(tr[feats], tr[label])
    logit = m.decision_function(te[feats])
    return te, race_probs(te, logit)


def base_predict(df, feats):
    """今の特徴量での予測は毎回同じなので、1回だけ学んでキャッシュに置く(特徴量の一覧が同じときだけ使う)。"""
    import hashlib
    key = hashlib.md5(("|".join(feats) + str(len(df))).encode()).hexdigest()[:10]
    f = CACHE_DIR / f"base_{key}.pkl"
    if f.exists():
        pb = pd.read_pickle(f)
        return df[df["split"] == "test"], pb.values
    te, pb = fit_predict(df, feats)
    pd.Series(pb, index=te.index).to_pickle(f)
    return te, pb


def compare(name, df, base_feats, cand_feats, note=""):
    te, pb = base_predict(df, base_feats)
    _, pc = fit_predict(df, cand_feats)
    lb, lc = win_logloss_per_race(te, pb), win_logloss_per_race(te, pc)
    return summarize(name, te, lb, lc, note, {"base_feats": len(base_feats), "cand_feats": len(cand_feats),
                                                 "added": sorted(set(cand_feats) - set(base_feats))[:40]})


def summarize(name, te, lb, lc, note="", extra=None):
    d = (lc - lb).reindex(lb.index).values
    se = d.std(ddof=1) / np.sqrt(len(d))
    res = {"name": name, "note": note, "races": int(len(d)), "base_logloss": round(float(lb.mean()), 4),
           "cand_logloss": round(float(lc.mean()), 4), "delta": round(float(d.mean()), 5),
           "lo90": round(float(d.mean() - 1.645 * se), 5), "hi90": round(float(d.mean() + 1.645 * se), 5),
           "verdict": "改善(偶然ではなさそう)" if d.mean() + 1.645 * se < 0 else ("悪化" if d.mean() - 1.645 * se > 0 else "差なし(偶然の範囲)"),
           "made": time.strftime("%Y-%m-%d %H:%M"), **(extra or {})}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log(json.dumps({k: res[k] for k in ("name", "races", "base_logloss", "cand_logloss", "delta", "lo90", "hi90", "verdict")}, ensure_ascii=False))
    return res


def base_feats(df):
    return [c for c in features.feature_columns(df, "late") if c not in ("win",)]


# ---------------------------------------------------------------- 案ごとの特徴量 -----------------
def add_formation(df, stcol, prefix):
    """予想STからの隊形: スリットの順位、先頭との差、内・外との差(sim_st.py の formation と同じ考え)。"""
    pos = df["course"].where(df["course"].notna(), df["lane"]).astype(int)
    d = df[["race_id", stcol]].assign(pos=pos.values).sort_values(["race_id", "pos"])
    g = d.groupby("race_id")[stcol]
    d[prefix + "rank"] = g.rank(method="min")
    d[prefix + "lead"] = d[stcol] - g.transform("min")
    d[prefix + "vs_in"] = (g.shift(1) - d[stcol]).fillna(0)
    d[prefix + "vs_out"] = (g.shift(-1) - d[stcol]).fillna(0)
    d[prefix + "inside_faster"] = (g.cummin() < d[stcol] - 0.005).astype(float)  # 自分より内に速い艇がいる(壁)
    for c in (prefix + "rank", prefix + "lead", prefix + "vs_in", prefix + "vs_out", prefix + "inside_faster"):
        df[c] = d[c].reindex(df.index)
    return df


def st_regressor(df):
    """本番STを回帰で予想する(選手の展示→本番の癖、コース、風、場、節の日目まで入れる)。学習期間だけで学ぶ。"""
    feats = [c for c in ("ex_st", "st_bias", "rc_avgst", "st_sd", "rc_stsd", "course", "lane", "course_st_hist", "wind", "wind_x", "wind_y",
                         "wave", "jcd", "rno", "class_num", "race_grade", "day_no", "tilt", "exhibit_time", "exhibit_gap_best",
                         "age", "series_rank_pct", "kachikake", "rc_fcount", "st_ex_n", "in_rc_avgst", "out_rc_avgst", "course_shift",
                         "motor_2rate", "nat_win_rate", "rating") if c in df]
    okst = df["st"].notna() & (df["st_flag"].isna() | (df["st_flag"] == "")) if "st_flag" in df else df["st"].notna()
    tr = df[(df["split"] != "test") & okst & df["ex_st"].notna()]
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=100, random_state=0).fit(tr[feats], tr["st"])
    pred = pd.Series(m.predict(df[feats]), index=df.index)
    te = df[(df["split"] == "test") & okst & df["ex_st"].notna()]
    mae_old = float((te["st_pred"] - te["st"]).abs().mean())
    mae_new = float((pred[te.index] - te["st"]).abs().mean())
    mae_ex = float((te["ex_st"] - te["st"]).abs().mean())
    mae_avg = float((te["rc_avgst"] - te["st"]).abs().mean())
    log(f"ST予想の誤差(テスト, 平均絶対誤差): 展示そのまま {mae_ex:.4f} / 普段の平均 {mae_avg:.4f} / いまの st_pred {mae_old:.4f} / 回帰 {mae_new:.4f}")
    return pred.where(df["ex_st"].notna(), df["st_pred"]), {"mae_ex": mae_ex, "mae_avg": mae_avg, "mae_st_pred": mae_old, "mae_reg": mae_new}


def add_bangumi(df):
    """番組の癖(J1): その場・そのレース番号で、過去にそのコースがどれだけ勝ったか(前日までの累積、縮めあり)。"""
    d = df[["date", "jcd", "rno", "lane", "win"]].copy()
    d["c1"] = (d["lane"] == 1) & (d["win"] == 1)
    day = d[d["lane"] == 1].groupby(["jcd", "rno", "date"])["c1"].sum().reset_index()
    day = day.sort_values("date")
    g = day.groupby(["jcd", "rno"])
    day["n"] = g.cumcount()
    day["s"] = g["c1"].cumsum() - day["c1"]
    prior = float(d.loc[d["lane"] == 1, "win"].mean())
    day["bg_in1"] = (day["s"] + prior * 30) / (day["n"] + 30)
    df = df.merge(day[["jcd", "rno", "date", "bg_in1"]], on=["jcd", "rno", "date"], how="left")
    # 枠ごと
    lane = d.groupby(["jcd", "rno", "lane", "date"])["win"].sum().reset_index().sort_values("date")
    g = lane.groupby(["jcd", "rno", "lane"])
    lane["n"] = g.cumcount()
    lane["s"] = g["win"].cumsum() - lane["win"]
    lp = d.groupby("lane")["win"].mean()
    lane["bg_lane"] = (lane["s"] + lane["lane"].map(lp) * 30) / (lane["n"] + 30)
    df = df.merge(lane[["jcd", "rno", "lane", "date", "bg_lane"]], on=["jcd", "rno", "lane", "date"], how="left")
    df["bg_lane_rel"] = df["bg_lane"] / df["lane"].map(lp)
    return df


def add_embed(df):
    """選手・モーター・(場×コース)の埋め込み(D19 の最小版): 疎なロジスティック回帰の係数を、学習期間だけで学び、特徴量に。"""
    from scipy import sparse
    from sklearn.linear_model import LogisticRegression
    pos = df["course"].where(df["course"].notna(), df["lane"]).astype(int)
    keys = {"racer": df["racer_id"].astype(str), "motor": df["jcd"].astype(str) + "_" + df["motor_no"].astype(str) + "_" + df["date"].dt.year.astype(str),
            "vc": df["jcd"].astype(str) + "_" + pos.astype(str), "rc": df["racer_id"].astype(str) + "_" + pos.astype(str)}
    tr = df["split"] != "test"
    mats, names = [], []
    for k, s in keys.items():
        cats = s[tr].astype("category").cat.categories
        code = pd.Categorical(s, categories=cats).codes
        m = sparse.csr_matrix((np.ones(len(df)), (np.arange(len(df)), np.where(code < 0, 0, code))), shape=(len(df), len(cats)))
        m = m.multiply((code >= 0)[:, None])
        mats.append(sparse.csr_matrix(m)); names.append(k)
    X = sparse.hstack(mats).tocsr()
    lr = LogisticRegression(C=0.3, max_iter=300, solver="saga").fit(X[tr.values], df.loc[tr, "win"])
    off = 0
    for k, m in zip(names, mats):
        w = lr.coef_[0][off: off + m.shape[1]]; off += m.shape[1]
        df["emb_" + k] = np.asarray(m @ w).ravel()
    df["emb_all"] = lr.decision_function(X)
    return df


def race_level_model(df, feats, k=12):
    """レースを1つの標本にして6艇ぶんの特徴量を横に並べ、6クラス(どの枠が勝つか)を直接学ぶ。"""
    feats = feats[:k]
    d = df.sort_values(["race_id", "lane"])
    full = d.groupby("race_id")["lane"].transform("size") == 6
    d = d[full]
    wide = d.pivot(index="race_id", columns="lane", values=feats)
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    y = d[d["win"] == 1].groupby("race_id")["lane"].first().reindex(wide.index)  # 同着は先の枠
    sp = d.groupby("race_id")["split"].first().reindex(wide.index)
    ok = y.notna()
    wide, y, sp = wide[ok], y[ok].astype(int), sp[ok]
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=50, random_state=0)
    m.fit(wide[sp != "test"], y[sp != "test"])
    P = m.predict_proba(wide[sp == "test"])
    te = pd.DataFrame(P, index=wide.index[sp == "test"], columns=m.classes_)
    return te, y[sp == "test"]


# ---------------------------------------------------------------- 実験 -----------------
def exp_formation(df):
    base = base_feats(df)
    df = add_formation(df, "st_pred", "fm_")
    return compare("formation_from_st_pred", df, base, base + ["fm_rank", "fm_lead", "fm_vs_in", "fm_vs_out", "fm_inside_faster"],
                   "予想ST(st_pred)からスリットの隊形(順位・先頭との差・内外との差・内に速い艇)を作って足す")


def exp_st_reg(df):
    base = base_feats(df)
    pred, maes = st_regressor(df)
    df["st_pred2"] = pred
    df = add_formation(df, "st_pred2", "fm2_")
    pos = df["course"].where(df["course"].notna(), df["lane"]).astype(int)
    key = df["race_id"].astype(str) + "_" + pos.astype(str)
    mp = pd.Series(df["st_pred2"].values, index=key).groupby(level=0).first()
    df["st_pred2_adv_in"] = (df["race_id"].astype(str) + "_" + (pos - 1).astype(str)).map(mp).values - df["st_pred2"]
    df["st_pred2_adv_out"] = (df["race_id"].astype(str) + "_" + (pos + 1).astype(str)).map(mp).values - df["st_pred2"]
    df["st_pred2_diff"] = df["st_pred2"] - df.groupby("race_id")["st_pred2"].transform("mean")
    cand = base + ["st_pred2", "st_pred2_diff", "st_pred2_adv_in", "st_pred2_adv_out", "fm2_rank", "fm2_lead", "fm2_vs_in", "fm2_vs_out", "fm2_inside_faster"]
    r = compare("st_regressor", df, base, cand, "本番STを回帰で予想(st_pred2)し、その隊形の特徴量を足す")
    r.update(maes); (OUT / "st_regressor.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def exp_bangumi(df):
    base = base_feats(df)
    df = add_bangumi(df)
    return compare("bangumi_habit", df, base, base + ["bg_in1", "bg_lane", "bg_lane_rel"],
                   "番組の癖(J1): 場×レース番号の過去のイン勝率・枠別勝率(前日まで)を足す")


def exp_embed(df):
    base = base_feats(df)
    df = add_embed(df)
    return compare("embed_sparse", df, base, base + ["emb_racer", "emb_motor", "emb_vc", "emb_rc", "emb_all"],
                   "選手・モーター・場×コース・選手×コースの埋め込み(疎ロジスティックの係数)を足す(D19 の最小版)")


def exp_drop_noise(df):
    base = base_feats(df)
    noisy = [c for c in base if c.startswith(("kachikake", "series_rank", "border_gap", "rough_top3", "vl_", "vw_win", "loc_"))]
    return compare("drop_noise", df, base, [c for c in base if c not in noisy], f"ノイズと分かった状況の特徴量を外す: {noisy}")


def exp_race_level(df):
    base = base_feats(df)
    te, pb = base_predict(df, base)
    lb = win_logloss_per_race(te, pb)
    imp_order = ["st_pred", "rating", "rc_win", "nat_win_rate", "motor_2rate", "exhibit_time", "course", "class_num", "rl_win",
                 "course_win_hist", "mtx_top2", "st_pred_adv_in", "nige_rate", "makuri_rate", "sashi_rate", "ex_st", "rc_avgst", "wind_x"]
    P, y = race_level_model(df, [c for c in imp_order if c in df], k=18)
    p_true = P.values[np.arange(len(P)), y.values - 1]
    lc = pd.Series(-np.log(np.clip(p_true, 1e-6, 1)), index=P.index)
    common = lb.index.intersection(lc.index)
    # 単体と、艇ごとモデルとの平均(対数で)
    pb_s = te.assign(p=pb)
    Pb = pb_s.pivot(index="race_id", columns="lane", values="p").reindex(index=common, columns=range(1, 7)).fillna(1e-6)
    Pm = np.exp((np.log(Pb.values) + np.log(P.reindex(common).values)) / 2); Pm /= Pm.sum(1, keepdims=True)
    lm = pd.Series(-np.log(Pm[np.arange(len(common)), y.reindex(common).values - 1]), index=common)
    summarize("race_level_single", te, lb[common], lc[common], "レースを1標本にした6クラスモデル(単体)")
    return summarize("race_level_blend", te, lb[common], lm, "6クラスモデルと艇ごとGBDTの対数平均")


def add_embed_asof(df):
    """埋め込みの as-of 版: 半年ごとに「その前までのデータ」で疎ロジスティックを学び、その半年の行に係数を付ける(学習行が答えを知らない)。"""
    from scipy import sparse
    from sklearn.linear_model import LogisticRegression
    pos = df["course"].where(df["course"].notna(), df["lane"]).astype(int)
    keys = {"racer": df["racer_id"].astype(str), "motor": df["jcd"].astype(str) + "_" + df["motor_no"].astype(str) + "_" + df["date"].dt.year.astype(str),
            "vc": df["jcd"].astype(str) + "_" + pos.astype(str), "rc": df["racer_id"].astype(str) + "_" + pos.astype(str)}
    half = df["date"].dt.year * 2 + (df["date"].dt.month > 6).astype(int)
    for k in list(keys) + ["all"]:
        df["emb_" + k] = np.nan
    for per in sorted(half.unique()):
        rows, tr = (half == per).values, (half < per).values
        if tr.sum() < 100000:
            continue
        mats = []
        for k, sr in keys.items():
            cats = pd.Index(sr[tr].unique())
            code = cats.get_indexer(sr)
            m = sparse.csr_matrix((np.where(code >= 0, 1.0, 0.0), (np.arange(len(df)), np.where(code < 0, 0, code))), shape=(len(df), len(cats)))
            mats.append(m)
        X = sparse.hstack(mats).tocsr()
        lr = LogisticRegression(C=0.3, max_iter=200, solver="saga").fit(X[tr], df.loc[tr, "win"])
        off = 0
        for k, m in zip(keys, mats):
            w = lr.coef_[0][off: off + m.shape[1]]; off += m.shape[1]
            df.loc[rows, "emb_" + k] = np.asarray(m[rows] @ w).ravel()
        df.loc[rows, "emb_all"] = lr.decision_function(X[rows])
        log(f"  embed as-of: 期間 {per} 学習 {int(tr.sum())} 行")
    return df


def exp_embed_asof(df):
    base = base_feats(df)
    df = add_embed_asof(df)
    return compare("embed_asof", df, base, base + ["emb_racer", "emb_motor", "emb_vc", "emb_rc", "emb_all"],
                   "選手・モーター・場×コース・選手×コースの埋め込みを as-of(半年ごと学び直し)で作って足す(D19)")


def exp_recent(df):
    """学習を直近18か月に絞る(古いデータが邪魔をしていないか)。"""
    base = base_feats(df)
    te, pb = base_predict(df, base)
    cut = df.loc[df["split"] != "test", "date"].max() - pd.Timedelta(days=548)
    d2 = df[(df["split"] == "test") | (df["date"] >= cut)]
    _, pc = fit_predict(d2, base)
    return summarize("recent_18m", te, win_logloss_per_race(te, pb), win_logloss_per_race(d2[d2["split"] == "test"], pc),
                     "学習データを直近18か月だけに絞る")


def exp_pairwise(df):
    """ペアごとのモデル(ブラッドリー・テリー風): 2艇の特徴量の差から「どちらが先着するか」を学び、レース内の総当たりで強さにする。"""
    base = base_feats(df)
    te, pb = base_predict(df, base)
    feats = [c for c in ("st_pred", "rating", "rc_win", "nat_win_rate", "motor_2rate", "exhibit_time", "course", "class_num", "rl_win",
                         "course_win_hist", "mtx_top2", "nige_rate", "makuri_rate", "sashi_rate", "rc_avgst", "lane", "mt_top2", "rc_top3",
                         "winrate_growth_180", "tilt", "weight") if c in df]
    d = df.sort_values(["race_id", "lane"])
    full = d.groupby("race_id")["lane"].transform("size") == 6
    d = d[full]
    X = d[feats].values.astype(np.float32).reshape(-1, 6, len(feats))
    fin = d["finish"].values.reshape(-1, 6)
    rid = d["race_id"].values.reshape(-1, 6)[:, 0]
    sp = d["split"].values.reshape(-1, 6)[:, 0]
    i, j = np.triu_indices(6, 1)
    Xp = np.concatenate([X[:, i, :] - X[:, j, :], X[:, i, :]], axis=2).astype(np.float32)  # 差 + 自分
    yp = (fin[:, i] < fin[:, j]).astype(int)
    tr = sp != "test"
    tr_idx = np.where(tr)[0][-60000:]  # メモリのため直近6万レース(=90万ペア)で学ぶ
    m = gbdt(0, max_iter=300).fit(Xp[tr_idx].reshape(-1, Xp.shape[2]), yp[tr_idx].ravel())
    del X
    s = m.decision_function(Xp[~tr].reshape(-1, Xp.shape[2])).reshape(-1, 15)
    strength = np.zeros((s.shape[0], 6))
    for k, (a, b) in enumerate(zip(i, j)):
        strength[:, a] += s[:, k]; strength[:, b] -= s[:, k]
    strength /= 5
    P = np.exp(strength - strength.max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
    win_lane = np.argmin(fin[~tr], axis=1)
    lc = pd.Series(-np.log(np.clip(P[np.arange(len(P)), win_lane], 1e-6, 1)), index=rid[~tr])
    lb = win_logloss_per_race(te, pb)
    common = lb.index.intersection(lc.index)
    summarize("pairwise_single", te, lb[common], lc[common], "ペアモデル単体(2艇の差を学び、総当たりの平均を強さに)")
    Pb = te.assign(p=pb).pivot(index="race_id", columns="lane", values="p").reindex(index=common, columns=range(1, 7)).fillna(1e-6)
    Pc = pd.DataFrame(P, index=rid[~tr]).reindex(common)
    Pm = np.exp((np.log(Pb.values) + np.log(Pc.values)) / 2); Pm /= Pm.sum(1, keepdims=True)
    wl = pd.Series(win_lane, index=rid[~tr]).reindex(common).values
    lm = pd.Series(-np.log(Pm[np.arange(len(common)), wl]), index=common)
    return summarize("pairwise_blend", te, lb[common], lm, "ペアモデルと艇ごとGBDTの対数平均")


def exp_race_level_variants(df):
    """RaceLevel(models.py)の形を変えて比べる: 特徴量の数 k、枠順ではなく進入コース順に並べる。基準は k=24 枠順。"""
    import importlib.util, os
    # RaceLevel がまだ main に無いときは、環境変数 RL_MODELS に改良案ブランチの models.py の場所を指定する
    spec = importlib.util.spec_from_file_location("kyotei.rl_models", os.environ.get("RL_MODELS", ROOT / "src/kyotei/models.py"))
    rl_models = importlib.util.module_from_spec(spec); spec.loader.exec_module(rl_models)
    base = base_feats(df)
    te = df[df["split"] == "test"]

    def run(k, by_course):
        RaceLevel = rl_models.RaceLevel
        RaceLevel.k = k
        d = df
        if by_course:  # 進入コース順に並べ替える(lane 列を一時的にコースに)
            d = df.copy()
            pos = d["course"].where(d["course"].notna(), d["lane"]).astype(int)
            dup = d.assign(pos=pos).duplicated(["race_id", "pos"], keep=False)
            d.loc[~dup, "lane"] = pos[~dup]  # 同じコースが2艇いるレースは枠順のまま
        m = RaceLevel(base).fit(d[d["split"] != "test"])
        p = m.predict_proba(d[d["split"] == "test"])
        return win_logloss_per_race(te.assign(lane=d.loc[te.index, "lane"]) if by_course else te, p)

    lb = run(24, False)
    out = {}
    import os
    ks = [int(x) for x in os.environ.get("RL_KS", "12,36,48").split(",")]
    for k, bc in [(k, False) for k in ks] + ([(24, True)] if "RL_COURSE" in os.environ else []):
        lc = run(k, bc)
        r = summarize(f"race_level_k{k}{'_course' if bc else ''}", te, lb, lc, f"RaceLevel k={k} {'進入コース順' if bc else '枠順'} vs k=24 枠順")
        out[r["name"]] = r["delta"]
    return out


def add_wx(df):
    """過去の天気(締切の時刻): 湿度・気圧の平年差・3時間の気圧変化・暑さ指数・気温(scripts/lab.py の _with_wx と同じ)。"""
    import lab
    x = df[["date", "jcd", "deadline"]].copy()
    x["date"] = x["date"].dt.strftime("%Y-%m-%d")
    w = lab._with_wx(x, cols=("relative_humidity_2m", "p_anom", "p_3h", "wbgt", "temperature_2m"))
    for c in ("relative_humidity_2m", "p_anom", "p_3h", "wbgt", "temperature_2m"):
        df["wx_" + c] = w[c].values.astype("float32")
    return df


def add_body(df):
    """からだ: 当日体重の直近30走との差、前の走からの日数(休み明け)、最後のフライングから何走目か。"""
    o = df.sort_values(["racer_id", "date", "rno"]).index
    d = df.loc[o, ["racer_id", "date", "weight_now", "st_flag"]].copy()
    wn = d["weight_now"].where(d["weight_now"] > 30)
    d["w_dev"] = wn - wn.groupby(d["racer_id"]).transform(lambda s_: s_.shift(1).rolling(30, min_periods=10).mean())
    d["rest_days"] = d.groupby("racer_id")["date"].diff().dt.days
    f = (d["st_flag"] == "F")
    k = d.groupby("racer_id").cumcount()
    last = k.where(f).groupby(d["racer_id"]).ffill().groupby(d["racer_id"]).shift(1)
    d["f_since"] = (k - last).clip(upper=200).fillna(200)
    for c in ("w_dev", "rest_days", "f_since"):
        df[c] = d[c].reindex(df.index).astype("float32")
    return df


def exp_wx(df):
    base = base_feats(df)
    df = add_wx(df)
    return compare("weather_feats", df, base, base + [c for c in df.columns if c.startswith("wx_")], "締切の時刻の天気(湿度・気圧の平年差・気圧変化・暑さ指数・気温)を足す")


def exp_body(df):
    base = base_feats(df)
    df = add_body(df)
    return compare("body_feats", df, base, base + ["w_dev", "rest_days", "f_since"], "当日体重の直近30走との差・休み明けの日数・F後の走数を足す")


def exp_wx_body(df):
    base = base_feats(df)
    df = add_body(add_wx(df))
    return compare("weather_body_feats", df, base, base + [c for c in df.columns if c.startswith("wx_")] + ["w_dev", "rest_days", "f_since"], "天気+からだの両方")


def exp_exst(df):
    """J11: 今日の展示STは本番の調子とほぼ無関係(検証ラボ exst)。展示STから作った特徴量を外しても損しないか。"""
    base = base_feats(df)
    exf = [c for c in base if "ex_st" in c or "st_pred" in c]
    return compare("drop_ex_st", df, base, [c for c in base if c not in exf], f"展示STから作った特徴量を外す: {exf}")


def exp_body_exst(df):
    """からだ(体重のずれ・休み・F後)を足し、展示STの特徴量を外す(exp/20261006-body-exst と同じ組み合わせ)。"""
    base = base_feats(df)
    df = add_body(df)
    exf = [c for c in base if "ex_st" in c or "st_pred" in c]
    cand = [c for c in base if c not in exf] + ["w_dev", "rest_days", "f_since"]
    return compare("body_drop_exst", df, base, cand, "からだの特徴量を足し、展示STの特徴量を外す")


def add_accident(df):
    """J15: 今期の事故率の目安(その走より前)、期末までの日数、期末×事故率。"""
    rc = df["result_code"].astype(str)
    dt = pd.to_datetime(df["date"])
    mo, yr = dt.dt.month, dt.dt.year
    per = np.where(mo.between(5, 10), yr.astype(str) + "A", (yr + (mo >= 11)).astype(str) + "B")
    d = pd.DataFrame({"r": df["racer_id"].values, "per": per, "dt": dt.values, "rno": df["rno"].values,
                      "pts": rc.map({"F": 20, "L1": 20, "K1": 10, "S1": 10, "S2": 15}).fillna(0).values,
                      "cnt": rc.isin(["01", "02", "03", "04", "05", "06", "1", "2", "3", "4", "5", "6", "F", "L1", "K1", "S1", "S2"]).astype(float).values},
                     index=df.index).sort_values(["r", "dt", "rno"])
    g = d.groupby(["r", "per"])
    cp, cc = g["pts"].cumsum() - d["pts"], g["cnt"].cumsum() - d["cnt"]
    d["acc_rate"] = (cp / cc.where(cc >= 10)).astype("float32")
    end = pd.to_datetime(np.where(pd.Series(d["per"]).str.endswith("A").values, pd.Series(d["per"]).str[:4] + "-10-31", pd.Series(d["per"]).str[:4] + "-04-30"))
    d["days_left"] = (pd.Series(end, index=d.index) - pd.to_datetime(d["dt"])).dt.days.astype("float32")
    for c in ("acc_rate", "days_left"):
        df[c] = d[c].reindex(df.index).values
    df["acc_end"] = (df["acc_rate"] * (df["days_left"] <= 42)).astype("float32")
    return df


def add_kado(df):
    """J16: カドの一撃。4号艇のふだんのST(rc_avgst)と、1〜3号艇の最速のふだんのSTの差(レース全体に配る)。"""
    piv = df.pivot_table(index="race_id", columns="lane", values="rc_avgst", aggfunc="first")
    gap = piv.get(4) - piv[[c for c in (1, 2, 3) if c in piv]].min(axis=1)
    df["kado_gap"] = df["race_id"].map(gap).astype("float32")
    df["kado_self"] = df["kado_gap"].where(df["lane"] == 4).astype("float32")
    return df


def exp_accident(df):
    base = base_feats(df)
    df = add_accident(df)
    return compare("accident_rate", df, base, base + ["acc_rate", "days_left", "acc_end"], "今期の事故率の目安・期末までの日数・期末×事故率を足す(J15)")


def exp_kado(df):
    base = base_feats(df)
    df = add_kado(df)
    return compare("kado_gap", df, base, base + ["kado_gap", "kado_self"], "カド(4号艇)のふだんのSTと内3艇の最速の差を足す(J16)")


EXPERIMENTS = {"accident": exp_accident, "kado": exp_kado, "body_exst": exp_body_exst, "exst": exp_exst, "wx": exp_wx, "body": exp_body, "wx_body": exp_wx_body, "rl_variants": exp_race_level_variants, "embed_asof": exp_embed_asof, "recent": exp_recent, "pairwise": exp_pairwise, "formation": exp_formation, "st_reg": exp_st_reg, "bangumi": exp_bangumi, "embed": exp_embed,
               "drop_noise": exp_drop_noise, "race_level": exp_race_level}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "build":
        build(); return
    if cmd == "list":
        print("\n".join(EXPERIMENTS)); return
    df = load()
    for name in sys.argv[2:]:
        log("==", name)
        EXPERIMENTS[name](df.copy())


if __name__ == "__main__":
    main()
