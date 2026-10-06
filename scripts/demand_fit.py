"""3連単の売上(賭けられた総額)を、最終オッズから逆算して、何が売上を動かすかを学ぶ(注目度の物差し)。

逆算の考え方: 3連単のオッズ = 総額 × 0.75 ÷ その組の票数(100円単位、オッズは0.1倍・1000倍以上は1倍単位で切り捨て)。
人気のない組は票数が1票・2票…と整数で刻まれるので、全部の組が整数の票数になる「総額」を探す(9999倍は上限なので使わない)。
学ぶ: log10(総額) ~ レースの種類 + R + 締切の時間 + 場 + その日のA1の割合(大会の格の代わり)。
→ reports/demand_model.json(src/kyotei/demand.py が読む)

python scripts/demand_fit.py
"""
import pandas as pd, numpy as np, glob
def est(odds, vmax=800, n=40, need=0.95, pts=40):
    o=np.sort(np.asarray(odds,float))[::-1]
    o=o[np.isfinite(o)&(o>0)&(o<9999)][:n]   # 9999 は上限(本当のオッズではない)
    if len(o)<20: return None
    u=np.where(o>=1000,1.0,0.1)
    o1,u1=o[0],u[0]
    for v1 in range(1,vmax+1):
        Cs=v1*o1+np.linspace(0,v1*u1,pts,endpoint=False)
        v=np.floor(Cs[:,None]/o[None,:])
        ok=(v>=1)&(Cs[:,None]<v*(o+u)[None,:])
        fit=ok.mean(1)
        j=fit.argmax()
        if fit[j]>=need:
            return Cs[j]*100/0.75, v1, fit[j]
    return None


def _pools(f):
    o = pd.read_csv(f, dtype={"race_id": str})
    out = []
    for r, x in o.groupby("race_id"):
        e = est(x.odds.values, vmax=1500)
        if e:
            out.append((r, e[0]))
    return out


def kind(t) -> str:
    t = str(t)
    if "優勝" in t and "準" not in t:
        return "優勝戦"
    if "準優" in t:
        return "準優"
    if "ドリーム" in t:
        return "ドリーム"
    if "選抜" in t and "特別" in t:
        return "特別選抜"
    return "ふつう"


A1_BINS = [0, .35, .45, .55, .65, .75, 1.01]


def main():
    import json
    import pathlib
    from multiprocessing import Pool
    root = pathlib.Path(__file__).resolve().parents[1]
    fs = sorted(glob.glob(str(root / "data/odds/odds3t_*.csv.gz")))
    with Pool(4) as p:
        res = p.map(_pools, fs)
    p_ = pd.DataFrame([r for rr in res for r in rr], columns=["race_id", "pool"])
    ms = sorted(set(p_.race_id.str[:6]))
    R = pd.concat([pd.read_csv(f, dtype={"race_id": str}, usecols=["race_id", "date", "jcd", "rno", "race_title"])
                   for f in glob.glob(str(root / "data/history/races_*.csv.gz")) if f[-13:-7] in ms])
    E = pd.concat([pd.read_csv(f, dtype={"race_id": str}, usecols=["race_id", "date", "jcd", "racer_class", "deadline"])
                   for f in glob.glob(str(root / "data/history/entries_*.csv.gz")) if f[-13:-7] in ms])
    a1 = E.assign(a=(E.racer_class == "A1")).groupby(["date", "jcd"]).a.mean().rename("day_a1")
    d = p_.merge(R, on="race_id").join(E.groupby("race_id").deadline.first(), on="race_id").join(a1, on=["date", "jcd"])
    d["hh"] = pd.to_numeric(d.deadline.astype(str).str[:2], errors="coerce").clip(8, 22).fillna(15).astype(int)
    ref = d.groupby(["date", "jcd"]).pool.transform("median")
    d = d[(d.pool / ref <= 4) & (d.pool / ref >= 0.25)]   # 逆算に失敗した1%ほどを外す
    d["kind"] = d.race_title.map(kind)
    d["a1b"] = pd.cut(d.day_a1, A1_BINS, labels=False).fillna(0).astype(int)
    X = pd.get_dummies(d[["kind", "rno", "hh", "jcd", "a1b"]].astype(str)).astype(float)
    X.insert(0, "c", 1.0)
    y = np.log10(d.pool.values)
    A = X.values
    b = np.linalg.solve(A.T @ A + np.eye(A.shape[1]), A.T @ y)
    pr = A @ b
    r2 = 1 - ((y - pr) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    out = {"coef": dict(zip(X.columns, map(float, b))), "n": int(len(d)), "asof": str(d.date.max()), "r2": round(float(r2), 3),
           "median_pool": float(np.median(d.pool)), "a1_bins": A1_BINS}
    (root / "reports/demand_model.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("レース", len(d), "R2", round(r2, 3), "総額の中央値(万円)", round(np.median(d.pool) / 1e4))


if __name__ == "__main__":
    main()
