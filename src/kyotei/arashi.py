"""荒れ度: 1号艇が負ける確率と、万舟(3連単の払戻1万円以上)になる確率。

- 1号艇が負ける確率 = 1 − (1号艇の1着確率)
- 万舟になる確率 = オッズ100倍以上の組が来る確率の合計。
  オッズが無い(朝の予想)ときは、払戻 ≒ 0.75 ÷ 確率 とみなして「確率0.75%以下の組」の合計で見積もる。

study() は「荒れ度が高いレースだけ期待値で買う」と「全レースで期待値で買う」の回収率を
レース単位のブートストラップで比べる(scripts/upset_eval.py から使う)。
"""
from __future__ import annotations

import json

import numpy as np

from .betting import COMBOS, blend, fit_blend, market_probs, select_bets

MANSHU_ODDS = 100.0  # 万舟 = 100倍(1万円)以上
TAKE = 0.75          # 3連単の払戻率
FIRST1 = np.array([c[0] == "1" for c in COMBOS])


def manshu_prob(P: np.ndarray, O: np.ndarray | None = None) -> np.ndarray:
    """P: (..., 120) 3連単確率。O: 同じ形のオッズ(無ければ確率から払戻を見積もる)。"""
    est = (P * (P <= TAKE / MANSHU_ODDS)).sum(-1)
    if O is None:
        return est
    has = np.isfinite(O).sum(-1) >= 100
    real = (P * (np.nan_to_num(O, nan=0) >= MANSHU_ODDS)).sum(-1)
    return np.where(has, real, est)


def arashi(p_win: np.ndarray, P: np.ndarray, O: np.ndarray | None = None) -> dict:
    """1レース分(アプリ表示用)。p_win: 枠番順の1着確率(6)。"""
    return {"in_lose": round(float(1 - p_win[0]), 4), "manshu": round(float(manshu_prob(P, O)), 4)}


# ---------------------------------------------------------------- 荒れ狙い(追試中)
# 2026-10-04 の検証で見つけた条件: 1号艇が負ける確率が 0.63 以上(テスト期間の上位20%)のレースに限ると、
# モデルの期待値100%以上の買い目の回収率が全レースより高かった(125% 対 76%、オッズのある12日・1,776レース)。
# 24通り試した中で一番良かった条件なので、偶然の可能性が残る。見つけた12日を除いた新しいオッズで追試し、
# 合格したら本番の買い目をこの条件に絞る(train_eval.py が判定し、bundle["bet_rule"] に入れる)。
IN_LOSE_MIN = 0.63
DISCOVERY_DAYS = {"20250128", "20250129", "20250130", "20250131", "20250201", "20250202", "20250203",
                  "20250204", "20260930", "20261001", "20261002", "20261003"}
CONFIRM_MIN_RACES = 600  # 条件に合うレースがこれだけたまるまでは判定しない(少ないうちに何度も判定すると偶然の合格が増える)


def confirm(rids, W, PM, O, y, pay, n_boot=4000, seed=0) -> dict:
    """事前に決めた条件の追試(見つけた12日は使わない)。

    「1号艇が負ける確率 ≥ IN_LOSE_MIN のレースだけ、モデルの確率で期待値100%以上を買う」と
    「全レースで同じ買い方」の回収率の差を、日ごとにまとめて引き直すブートストラップ(同じ日のレースは似るため)で比べる。
    合格: 条件に合うレースが CONFIRM_MIN_RACES 以上あり、差の90%区間の下限が0より上。
    """
    day = np.array([r[:8] for r in rids])
    ok = (np.isfinite(O).sum(1) >= 100) & ~np.isin(day, list(DISCOVERY_DAYS))
    hi = (1 - W[:, 0]) >= IN_LOSE_MIN
    out = {"rule": f"1号艇が負ける確率 ≥ {IN_LOSE_MIN} のレースだけ、モデルの期待値100%以上を買う",   # wording: ok(中の検証)
           "races": int(ok.sum()), "hi_races": int((ok & hi).sum()), "passed": False}
    if ok.sum() == 0:
        return out
    cost, ret = _bets(PM[ok], O[ok], y[ok], pay[ok], 1.0)
    m, d = hi[ok], day[ok]
    out["period"] = [str(min(d)), str(max(d))]
    out["roi_all"] = round(float(ret.sum() / max(cost.sum(), 1)), 4)
    out["roi_hi"] = round(float(ret[m].sum() / max(cost[m].sum(), 1)), 4)
    out["bets_hi"] = int(cost[m].sum() // 100)
    if out["hi_races"] < CONFIRM_MIN_RACES:
        out["note"] = f"条件に合うレースが{CONFIRM_MIN_RACES}未満のため判定待ち"
        return out
    g, gid = np.unique(d, return_inverse=True)
    Ca, Ra = np.bincount(gid, cost, len(g)), np.bincount(gid, ret, len(g))
    Ch, Rh = np.bincount(gid, cost * m, len(g)), np.bincount(gid, ret * m, len(g))
    idx = np.random.default_rng(seed).integers(0, len(g), (n_boot, len(g)))
    ra = Ra[idx].sum(1) / np.maximum(Ca[idx].sum(1), 1)
    rh = Rh[idx].sum(1) / np.maximum(Ch[idx].sum(1), 1)
    lo, hi90 = (float(np.quantile(rh - ra, q)) for q in (0.05, 0.95))
    out.update({"days": int(len(g)), "diff_ci90": [round(lo, 4), round(hi90, 4)],
                "roi_hi_ci90": [round(float(np.quantile(rh, q)), 4) for q in (0.05, 0.95)],
                "passed": bool(lo > 0)})
    return out


# ---------------------------------------------------------------- 検証

def _bets(P, O, y, pay, ev_min, p_min=0.01, max_bets=5):
    cost, ret = np.zeros(len(P)), np.zeros(len(P))
    for i in range(len(P)):
        for s in select_bets(P[i], O[i], ev_min, p_min, max_bets):
            cost[i] += 100
            if COMBOS.index(s["combo"]) == y[i]:
                ret[i] += pay[i]
    return cost, ret


def _topk(P, y, pay, k):
    top = np.argsort(-P, axis=1)[:, :k]
    hit = (top == y[:, None]).any(1)
    return np.full(len(P), 100.0 * k), np.where(hit, pay, 0.0)


def _compare(cost, ret, A, cuts, idx):
    """全レース vs 荒れ度が高いレースだけ(と、それ以外)。idx: ブートストラップの引き直し (B, n)。"""
    def roi(c, r):
        return r.sum(-1) / np.maximum(c.sum(-1), 1)
    cb, rb = cost[idx], ret[idx]
    all_b = roi(cb, rb)
    out = {"all": _row(cost, ret, all_b)}
    for name, th in cuts.items():
        m = A >= th
        mb = m[idx]
        hi_b, lo_b = roi(cb * mb, rb * mb), roi(cb * ~mb, rb * ~mb)
        row = _row(cost[m], ret[m], hi_b)
        row["threshold"] = round(float(th), 4)
        row["share_races"] = round(float(m.mean()), 3)
        d, d2 = hi_b - all_b, hi_b - lo_b
        row["diff_vs_all"] = round(float(row["roi"] - out["all"]["roi"]), 4) if row["roi"] is not None else None
        row["diff_vs_all_ci90"] = [round(float(np.quantile(d, q)), 4) for q in (0.05, 0.95)]
        row["p_better_than_all"] = round(float((d > 0).mean()), 3)
        rest = _row(cost[~m], ret[~m], lo_b)
        row["rest_roi"] = rest["roi"]
        row["diff_vs_rest_ci90"] = [round(float(np.quantile(d2, q)), 4) for q in (0.05, 0.95)]
        out[name] = row
    return out


def _row(c, r, boot):
    bets = int(c.sum() // 100)
    return {"races": int((c > 0).sum()), "bets": bets,
            "hits": int((r > 0).sum()), "roi": round(float(r.sum() / c.sum()), 4) if bets else None,
            "profit_yen": int(r.sum() - c.sum()),
            "roi_ci90": [round(float(np.quantile(boot, q)), 4) for q in (0.05, 0.95)] if bets >= 30 else None}


def _calib(pred, actual, bins=10):
    q = np.unique(np.quantile(pred, np.linspace(0, 1, bins + 1)))
    b = np.clip(np.searchsorted(q, pred, side="right") - 1, 0, len(q) - 2)
    return [{"pred": round(float(pred[b == i].mean()), 4), "actual": round(float(actual[b == i].mean()), 4),
             "n": int((b == i).sum())} for i in range(len(q) - 1) if (b == i).any()]


EV_BANDS = [(1.0, 1.2), (1.2, 1.5), (1.5, 2.0), (2.0, np.inf)]


def _day_ci(cost, ret, days, rng, n_boot=2000):
    """日ごとに引き直した回収率の90%区間(同じ日のレースはまとめて引く)。"""
    u, inv = np.unique(days, return_inverse=True)
    c = np.bincount(inv, weights=cost, minlength=len(u))
    r = np.bincount(inv, weights=ret, minlength=len(u))
    if c.sum() < 3000 or len(u) < 5:
        return None
    w = rng.poisson(1.0, (n_boot, len(u)))
    b = (w @ r) / np.maximum(w @ c, 1)
    return [round(float(np.quantile(b, q)), 4) for q in (0.05, 0.95)]


def _ev_row(cost, ret, days, rng):
    n = int(cost.sum() // 100)
    return {"bets": n, "races": int((cost > 0).sum()), "hits": int((ret > 0).sum()),
            "roi": round(float(ret.sum() / cost.sum()), 4) if n else None, "profit_yen": int(ret.sum() - cost.sum()),
            "roi_ci90": _day_ci(cost, ret, days, rng) if n else None}


def ev_detail(P, O, y, pay, rids, PB=None, n_boot=2000, seed=1) -> dict:
    """モデルの確率×確定オッズの期待値で買った場合の内訳(サイトの成績タブ用)。
    - 期待値の帯ごと(確率1%以上の組を全部、帯ごとに分けて)
    - サイトの「AIの狙い目」と同じ買い方(期待値100%以上・確率1%以上の組を、期待値の高い順に1レース3点まで)
    - 比べる買い方: 期待値100〜150%の組だけを期待値の高い順に3点まで(高すぎる期待値は見積もり違いが多いかを見る)
    - 本物の期待値(モデル×市場の合成)で100%以上になった組の数
    いずれも前半・後半に分けても出す。"""
    rng = np.random.default_rng(seed)
    days = np.array([r[:8] for r in rids])
    n = len(y)
    EV = P * np.nan_to_num(O, nan=0.0)
    ok = (P >= 0.01) & (EV >= 1.0)
    hit = np.zeros_like(ok)
    hit[np.arange(n), y] = True
    payout = np.where(hit, pay[:, None], 0.0)

    def rule(lo, hi, k):
        m = ok & (EV >= lo) & (EV < hi)
        cost, ret = np.zeros(n), np.zeros(n)
        for i in np.where(m.any(1))[0]:
            j = np.where(m[i])[0]
            j = j[np.argsort(-EV[i, j])][:k]
            cost[i] = 100.0 * len(j)
            ret[i] = payout[i, j].sum()
        return cost, ret

    def summarize(sl):
        out = {"period": [str(days[sl][0]), str(days[sl][-1])], "races": int(len(days[sl]))}
        bands = []
        for lo, hi in EV_BANDS:
            m = ok[sl] & (EV[sl] >= lo) & (EV[sl] < hi)
            row = _ev_row(100.0 * m.sum(1), (payout[sl] * m).sum(1), days[sl], rng)
            row["band"] = [lo, None if not np.isfinite(hi) else hi]
            bands.append(row)
        out["bands"] = bands
        out["all_ev100"] = _ev_row(100.0 * ok[sl].sum(1), (payout[sl] * ok[sl]).sum(1), days[sl], rng)
        c, r = rule(1.0, np.inf, 3)
        out["pick_rule"] = _ev_row(c[sl], r[sl], days[sl], rng)
        c, r = rule(1.0, 1.5, 3)
        out["pick_mid"] = _ev_row(c[sl], r[sl], days[sl], rng)
        if PB is not None:
            EB = PB[sl] * np.nan_to_num(O[sl], nan=0.0)
            mb = (PB[sl] >= 0.01) & (EB >= 1.0)
            out["blend_ev100"] = _ev_row(100.0 * mb.sum(1), (payout[sl] * mb).sum(1), days[sl], rng)
        return out

    h = n // 2
    return {"all": summarize(slice(0, n)), "first_half": summarize(slice(0, h)), "second_half": summarize(slice(h, n))}


SWEEP_SHARES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, "fit", "ai")
SWEEP_TH = (1.0, 1.1, 1.2, 1.3, 1.5, 2.0)


def blend_sweep(Pm, PK, O, y, pay, rids, seed=2, max_bets=5, min_bets=300) -> dict:
    """「期待値のある買い目」の、AIと人気をまぜる割合と期待値のしきい値を振ったらどうなるか
    (2026-10-07 ユーザー「いろいろ割合変えてもだめ?」)。
    - share: AIの割合(0.1=ほぼ人気だけ … 0.9=ほぼAIだけ)。まぜる強さ(a+b)は、もう半分の期間で当てはめた値のまま割合だけ変える。
      "fit" は当てはめたままの割合(いまの本番)、"ai" はAIの確率そのまま(=AIの狙い目と同じ考え方、5点まで)
    - th: 期待値のしきい値(1.0=100%以上 … 2.0=200%以上)。1レース5点まで(本番と同じ)
    前半・後半で別々に出し、「片方でいちばん良かった組み合わせが、もう片方でも100%を超えるか」を chosen に入れる
    (たくさん試すとたまたま良い組み合わせが出るので、選んだ期間とは別の期間で確かめる)。"""
    rng = np.random.default_rng(seed)
    days = np.array([r[:8] for r in rids])
    n = len(y)
    h = n // 2
    halves = {"first": (slice(h, None), slice(0, h)), "second": (slice(0, h), slice(h, None))}
    fits = {k: fit_blend(Pm[f], PK[f], y[f]) for k, (f, _) in halves.items()}
    On = np.nan_to_num(O, nan=0.0)
    rows = []
    for sh in SWEEP_SHARES:
        P_by = {}
        for k, (_, app) in halves.items():
            a, b = fits[k]
            if sh == "ai":
                P_by[k] = Pm[app]
            elif sh == "fit":
                P_by[k] = blend(Pm[app], PK[app], a, b)
            else:
                P_by[k] = blend(Pm[app], PK[app], sh * (a + b), (1 - sh) * (a + b))
        for th in SWEEP_TH:
            row = {"share": sh, "th": th}
            for k, (_, app) in halves.items():
                P = P_by[k]
                EV = P * On[app]
                m = (P >= 0.01) & (EV >= th)
                idx = np.argsort(-np.where(m, EV, -1.0), axis=1)[:, :max_bets]
                sel = np.zeros_like(m)
                np.put_along_axis(sel, idx, True, axis=1)
                sel &= m
                yy = y[app]
                cost = 100.0 * sel.sum(1)
                ret = np.where(sel[np.arange(len(yy)), yy], pay[app], 0.0)
                row[k] = _ev_row(cost, ret, days[app], rng)
            rows.append(row)

    def pick(src, dst):
        ok = [r for r in rows if r[src]["bets"] >= min_bets and r[src]["roi"] is not None]
        if not ok:
            return None
        best = max(ok, key=lambda r: r[src]["roi"])
        return {"chosen_on": src, "share": best["share"], "th": best["th"], "roi_chosen": best[src]["roi"],
                "check_on": dst, "check": best[dst]}
    return {"fits": {k: {"a": round(float(a), 3), "b": round(float(b), 3), "share": round(float(a / (a + b)), 3)} for k, (a, b) in fits.items()},
            "periods": {k: [str(days[app][0]), str(days[app][-1])] for k, (_, app) in halves.items()},
            "rows": rows, "chosen": [pick("first", "second"), pick("second", "first")]}


def study(rids, W, PM, O, y, pay, log=print, n_boot=2000, seed=0) -> dict:
    rng = np.random.default_rng(seed)
    n = len(y)
    in_lose = ~FIRST1[y]
    manshu = pay >= MANSHU_ODDS * 100
    A = {"in_lose": 1 - W[:, 0], "manshu": manshu_prob(PM)}
    # 上位50% / 30% / 20% を「荒れ度が高い」とする(しきい値は予想だけから決め、結果は見ない)
    cuts = {k: {f"top{int(round((1 - q) * 100))}": float(np.quantile(v, q)) for q in (0.5, 0.7, 0.8)}
            for k, v in A.items()}
    days = sorted({r[:8] for r in rids})
    res = {"period": [days[0], days[-1]], "races": n,
           "actual": {"in_lose_rate": round(float(in_lose.mean()), 4), "manshu_rate": round(float(manshu.mean()), 4)},
           "calibration": {"in_lose": _calib(A["in_lose"], in_lose), "manshu": _calib(A["manshu"], manshu)},
           "cuts": cuts}
    log(json.dumps({k: res[k] for k in ("period", "races", "actual")}, ensure_ascii=False))

    # 1) オッズ不要: モデルの上位5点を買う(全レースで比べられるので数が多い)
    idx = rng.integers(0, n, (n_boot, n))
    res["top5_all_races"] = {k: _compare(*_topk(PM, y, pay, 5), A[k], cuts[k], idx) for k in A}

    # 2) オッズのあるレース: 期待値100%以上を買う(本番と同じ条件: 確率1%以上、1レース5点まで)
    has = np.isfinite(O).sum(1) >= 100
    res["odds_races"] = int(has.sum())
    if has.sum() >= 300:
        Pm, Oo, yy, pp = PM[has], O[has], y[has], pay[has]
        PK = np.array([market_probs(o) for o in Oo])
        # 合成(モデル×市場)の係数は、前半で決めて後半に、後半で決めて前半に使う(答えを見ずに当てはめる)
        h = len(yy) // 2
        PB = np.empty_like(Pm)
        for fit, app in ((slice(h, None), slice(0, h)), (slice(0, h), slice(h, None))):
            a, b = fit_blend(Pm[fit], PK[fit], yy[fit])
            PB[app] = blend(Pm[app], PK[app], a, b)
        Ao = {k: v[has] for k, v in A.items()}
        Ao["manshu_odds"] = manshu_prob(PB, Oo)
        Ao["in_lose_market"] = 1 - (PK * FIRST1).sum(1)
        cuts_o = dict(cuts)
        for k in ("manshu_odds", "in_lose_market"):
            cuts_o[k] = {f"top{int(round((1 - q) * 100))}": float(np.quantile(Ao[k], q)) for q in (0.5, 0.7, 0.8)}
        res["cuts_odds"] = {k: cuts_o[k] for k in ("manshu_odds", "in_lose_market")}
        res["calibration"]["manshu_odds"] = _calib(Ao["manshu_odds"], manshu[has])
        idx = rng.integers(0, len(yy), (n_boot, len(yy)))
        ev = {}
        for src, P in (("model", Pm), ("blend", PB)):
            for th in (1.0, 1.2):
                c, r = _bets(P, Oo, yy, pp, th)
                ev[f"{src}_ev{int(th * 100)}"] = {k: _compare(c, r, Ao[k], cuts_o[k], idx) for k in Ao}
        res["ev_odds_races"] = ev
        # 時期で分けても同じ向きか(2つの期間で別々に)
        halves = {}
        for name, sl in (("first_half", slice(0, h)), ("second_half", slice(h, None))):
            c, r = _bets(Pm[sl], Oo[sl], yy[sl], pp[sl], 1.0)
            ii = rng.integers(0, len(c), (n_boot, len(c)))
            halves[name] = {"period": [rids[has][sl][0][:8], rids[has][sl][-1][:8]],
                            **{k: _compare(c, r, Ao[k][sl], cuts_o[k], ii) for k in ("in_lose", "manshu_odds")}}
        res["ev_model_by_half"] = halves
        res["ev_detail"] = ev_detail(Pm, Oo, yy, pp, np.asarray(rids)[has], PB)
        try:
            res["blend_sweep"] = blend_sweep(Pm, PK, Oo, yy, pp, np.asarray(rids)[has])
            log("blend_sweep", json.dumps(res["blend_sweep"]["chosen"], ensure_ascii=False))
        except Exception as ex:  # noqa: BLE001  ふり幅の検証が失敗しても本体の検証は残す
            log("blend_sweep failed", ex)
        log("ev_detail", json.dumps({k: res["ev_detail"]["all"][k] for k in ("all_ev100", "pick_rule", "pick_mid")}, ensure_ascii=False))
    res["confirm"] = confirm(rids, W, PM, O, y, pay)
    return res


