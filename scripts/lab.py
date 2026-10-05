"""ミカタ検証ラボ: 世の中の「◯◯理論」を同じ3つの物差しで試し、記事(紙面・note・X)にする。

物差し: ①その現象は本当にあるか(率) ②みんな知っているか(オッズが見込んだ率との比、1.0=人気どおり)
        ③時期を変えても出るか(前半2年と後半1年で同じ向きか)
書き方: 分析として出し、「予想への活かし方」を添える(買い目は書かない。儲かるとは言わない)

python scripts/lab.py --list                      # 理論の一覧
python scripts/lab.py --theory bangumi --out DIR  # 1本作る(DIR/lab_<id>.html / .txt / _x.txt、reports/lab/<id>.json)
python scripts/lab.py --next --out DIR            # まだ作っていない理論を1本(毎週のジョブ用)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import mag  # noqa: E402
from kyotei.card_render import gull_svg  # noqa: E402
from kyotei.data import load_history  # noqa: E402
from kyotei.racer_card import VENUES  # noqa: E402
from kyotei.xtext import fun_rate, sim_words, xlen  # noqa: E402

e = html.escape
REP = ROOT / "reports/lab"
JST = dt.timezone(dt.timedelta(hours=9))


# ---------------------------------------------------------------- データ
def base():
    ent, r, odds = load_history()
    r = r.dropna(subset=["win_lane"]).copy()
    r["race_id"] = r["race_id"].astype(str)
    r["c1"] = (r["win_lane"] == 1).astype(float)
    r["upset"] = (pd.to_numeric(r["tri_pop"], errors="coerce") >= 30).astype(float)
    r["late"] = pd.to_datetime(r["date"]).dt.year >= 2025      # 後半(2025〜)/前半(2023〜24)
    q1 = None
    if odds is not None:
        o = odds[odds["odds"] > 0].copy()
        o["race_id"] = o["race_id"].astype(str)
        o["q"] = 1 / o["odds"]
        o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
        q1 = o[o["combo"].str.startswith("1-")].groupby("race_id")["q"].sum().rename("q1")
        r = r.merge(q1, on="race_id", how="left")
    ent = ent.copy()
    ent["race_id"] = ent["race_id"].astype(str)
    # 1コースに入った艇(前づけのレースでは1号艇とは限らない)の枠番と、その艇が勝ったか、オッズの見込み
    c1 = ent[ent["course"] == 1].drop_duplicates("race_id").set_index("race_id")
    r["lane_c1"] = r["race_id"].map(c1["lane"])
    r["cc1"] = (r["win_lane"] == r["lane_c1"]).astype(float)
    if odds is not None:
        ql = o.assign(l=o["combo"].str.split("-").str[0].astype(int)).groupby(["race_id", "l"])["q"].sum()
        key = pd.MultiIndex.from_arrays([r["race_id"], r["lane_c1"].fillna(1).astype(int)])
        r["qc1"] = ql.reindex(key).values
        for k in range(1, 7):   # 枠ごとの「1着になる見込み」(オッズから)
            r[f"q_l{k}"] = ql.reindex(pd.MultiIndex.from_arrays([r["race_id"], pd.Series(k, index=r.index)])).values
    return ent, r


def boot_ci(x: np.ndarray, n=400, seed=0):
    rng = np.random.default_rng(seed)
    m = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


def measure(r: pd.DataFrame, mask: pd.Series, ref: pd.Series | None = None, col: str = "c1", qcol: str = "q1") -> dict:
    """①率 ②市場との比 ③前半・後半。ref は比べる相手(無ければ全体)。col="cc1" なら「1コースの艇」(前づけ込み)で測る。"""
    x, y = r[mask], (r[ref] if ref is not None else r)
    if col != "c1":
        x, y = x.assign(c1=x[col], q1=x.get(qcol)), y.assign(c1=y[col], q1=y.get(qcol))
    m = {"n": int(len(x)), "in1": float(x["c1"].mean()), "in1_ref": float(y["c1"].mean()),
         "upset": float(x["upset"].mean()), "upset_ref": float(y["upset"].mean())}
    lo, hi = boot_ci(x["c1"].values)
    m["in1_ci"] = [lo, hi]
    xo = x.dropna(subset=["q1"]) if "q1" in x else x.iloc[0:0]
    if len(xo) >= 100:
        m["n_odds"] = int(len(xo))
        m["market_ratio"] = float(xo["c1"].mean() / xo["q1"].mean())
        g = xo.groupby(xo["date"].str[:10])[["c1", "q1"]].sum()
        rng = np.random.default_rng(1)
        bt = [float((k := g.iloc[rng.integers(0, len(g), len(g))])["c1"].sum() / k["q1"].sum()) for _ in range(300)]
        m["market_ci"] = [float(np.quantile(bt, 0.05)), float(np.quantile(bt, 0.95))]
        yo = y.dropna(subset=["q1"])  # 比べる相手(全体)の比。1号艇は人気のわりに来やすい(本命びいきの逆)ので、1.0 ではなくこれと比べる
        if len(yo) >= 100:
            m["market_ref"] = float(yo["c1"].mean() / yo["q1"].mean())
    a, b = x[~x["late"]], x[x["late"]]
    ya, yb = y[~y["late"]], y[y["late"]]
    if len(a) >= 50 and len(b) >= 50:
        m["half"] = [float(a["c1"].mean() - ya["c1"].mean()), float(b["c1"].mean() - yb["c1"].mean())]
    return m


def verdicts(m: dict) -> dict:
    """3つの物差しの答えを、ふだんの言葉で。統計の言い方(区間・相関)は読者に見せない。"""
    d = m["in1"] - m["in1_ref"]
    real = abs(d) >= 0.03 and not (m["in1_ci"][0] <= m["in1_ref"] <= m["in1_ci"][1])
    out = {"exists": ("本当にある(ふだんより" + ("多い" if d > 0 else "少ない") + ")") if real else "ふだんと同じ(差は出なかった)", "real": real}
    if "market_ratio" in m:
        lo, hi = m["market_ci"]
        ref = m.get("market_ref", 1.0)
        if lo <= ref <= hi:
            out["known"], out["edge"] = "みんな知っている(オッズに織り込み済み)", 0
        elif lo > ref and m.get("n_odds", 0) < 500:  # レース数が少ないうちは「追試中」にとどめる(8つ調べれば1つは偶然で出る)
            out["known"], out["edge"] = "オッズの見立てを上回って来ているが、まだレース数が少ない(追試中)", 0
        elif lo > ref:
            out["known"], out["edge"] = ("ほかのレースより、オッズの見立てを上回って来る。でも、ひかれる分(25%)を埋めるほどではない" if lo < 1.3 else "知られているより来る"), 1
        else:
            out["known"], out["edge"] = "オッズの見立てよりひかえめ", -1
    else:
        out["known"], out["edge"] = "オッズのデータがまだ足りない", None
    if "half" in m:
        a, b = m["half"]
        out["stable"] = "前の2年も最近の1年も同じ" if a * b > 0 and abs(a) >= 0.015 and abs(b) >= 0.015 else "年によって顔ぶれが変わる(毎年見直す)"
    return out


def conclusion(t: dict) -> tuple[str, str]:
    """記事の冒頭に置く結論(ハンコ)。(見出し, ひとこと)。理論側で決めてあればそれを使う。"""
    if t.get("conclusion"):
        return tuple(t["conclusion"])
    vs = [v for _, _, v in t["measures"] if not v.get("baseline")]
    real = any(v.get("real") for v in vs)
    edge = [v.get("edge") for v in vs if v.get("edge") is not None]
    if not real:
        return "ふだんと同じ", "差は出なかった。前後のレースに引っぱられず、そのレースの6人と水面を見る人が、いちばん楽しめる"
    if any(e == 1 for e in edge):
        return "本当。しかも見立て超え", "オッズの見立てより来ている。ひかれる分を埋めるほどではないが、追いかける価値あり(毎週更新)"
    if all(e == 0 for e in edge) and edge:
        return "本当。オッズにも織り込み済み", "差はしっかりある。みんな見ているぶん配当は堅め。だから1着は決め打ちして、2着・3着の並びで腕を見せる回"
    return "本当", "差はある。オッズとの関係はデータを集めて確かめる"


def ratio_words(r, ref=None):
    """オッズとの比を言葉で: 1.04 → 「オッズの見立てより +4%」。ref(全レースの比)があれば並べて書く。"""
    if r is None or r != r:
        return "-"
    d = round((r - 1) * 100)
    w = "オッズの見立てどおり" if d == 0 else f"オッズの見立てより {d:+d}%"
    if ref is not None and ref == ref:
        w += f"(全レースの平均は {round((ref - 1) * 100):+d}%)"
    return w


# ---------------------------------------------------------------- 理論
def t_bangumi(ent, r):
    """番組屋の癖: 場×レース番号で1号艇の強さは決まっているか。"""
    g = r.groupby(["jcd", "rno"]).agg(n=("c1", "size"), in1=("c1", "mean"), a=("late", lambda s: r.loc[s.index[~s], "c1"].mean()),
                                      b=("late", lambda s: r.loc[s.index[s], "c1"].mean())).query("n >= 200")
    corr = float(g["a"].corr(g["b"]))
    hard = g.sort_values("in1").tail(8)
    soft = g.sort_values("in1").head(8)
    rows = [{"venue": VENUES[j], "rno": int(k), "n": int(v["n"]), "in1": float(v["in1"])} for (j, k), v in hard.iloc[::-1].iterrows()]
    rows2 = [{"venue": VENUES[j], "rno": int(k), "n": int(v["n"]), "in1": float(v["in1"])} for (j, k), v in soft.iterrows()]
    # 市場との比: 枠の選び方と同じデータで測ると良く見えてしまう(選んだ側の偏り)ので、
    # 前半2年の成績で枠を選び、後半1年だけで測る
    ga = g.sort_values("a")
    hk, sk = set(ga.tail(8).index), set(ga.head(8).index)
    key = list(zip(r["jcd"], r["rno"]))
    late = r[r["late"]]
    key_l = list(zip(late["jcd"], late["rno"]))
    mh = measure(late, pd.Series([k in hk for k in key_l], index=late.index))
    ms = measure(late, pd.Series([k in sk for k in key_l], index=late.index))
    for m in (mh, ms):
        m.pop("half", None)
        m["note"] = "前半2年で選んだ枠を、後半1年で測定"
    return {
        "id": "bangumi", "title": "番組屋の癖は本物か", "belief": "「この場のこのレースはインが堅い」は番組を組む人の癖で、毎年同じ",
        "lead": f"場×レース番号ごとに1号艇が勝つ割合は、いちばん堅い枠で{g['in1'].max():.0%}({fun_rate(g['in1'].max())})、いちばん荒れる枠で{g['in1'].min():.0%}({fun_rate(g['in1'].min())})。"
                f"前の2年で堅かった枠は、最近の1年でも{sim_words(corr)}。番組の癖はたしかにあり、年をまたいでも続いている。",
        "tables": [("1号艇が堅い枠(上位8)", rows), ("1号艇が荒れる枠(下位8)", rows2)],
        "measures": [("前半2年で堅かった枠8つ→後半1年", mh, verdicts(mh)), ("前半2年で荒れた枠8つ→後半1年", ms, verdicts(ms))],
        "use": ["出走表を見る前に、その場のその番号の「ふだんの堅さ」を頭に入れる。堅い枠で1号艇が弱そうなら、それ自体がニュース",
                "ただし堅い枠はオッズも堅い。人気どおりなら、1号艇を軸にするかどうかは配当との相談(ここは読者の判断)",
                "荒れる枠は、2〜4号艇にまくり型・差し型の選手が入っているかを先に見る"],
        "mikata": "番組屋さんの気持ちになって出走表を読むと、レースがもう一段おもしろくなるよ。『この枠に、なぜこの人を置いた?』って",
        "gen": "だろ? 番組屋の癖は昔からあるんだ。堅い枠は黙って1号艇、荒れる枠は俺の出番だ",
        "challenge": "今日行く場の「堅い枠」と「荒れる枠」を1つずつ覚えておく。荒れる枠のレースで、2〜4号艇にまくり屋がいたら、友達より先に言ってみよう",
        "numbers": {"corr_half": corr, "max": float(g["in1"].max()), "min": float(g["in1"].min()), "n_cells": int(len(g))},
    }


def t_kikaku(ent, r):
    """企画レース(特別選抜戦・ドリーム戦など)のインは信じていいか。"""
    rows, measures = [], []
    for t in ["特別選抜戦", "ドリーム戦", "記者選抜戦", "予選特選", "準優勝戦", "優勝戦", "予選特賞", "一般戦"]:
        mask = r["race_title"] == t
        if mask.sum() < 150:
            continue
        m = measure(r, mask)
        v = verdicts(m)
        rows.append({"venue": t, "rno": "", "n": m["n"], "in1": m["in1"], "ratio": m.get("market_ratio")})
        measures.append((t, m, v))
    best = max((x for x in measures if "market_ratio" in x[1]), key=lambda x: x[1]["market_ratio"])
    return {
        "id": "kikaku", "title": "企画レースのインは信じていいか", "belief": "特別選抜戦やドリーム戦は強い選手が1号艇に来るので、インが堅い",
        "lead": f"1号艇が勝つのは、特別選抜戦で{dict((x[0], x[1]['in1']) for x in measures).get('特別選抜戦', 0):.0%}({fun_rate(dict((x[0], x[1]['in1']) for x in measures).get('特別選抜戦', 0))})、"
                f"ドリーム戦で{dict((x[0], x[1]['in1']) for x in measures).get('ドリーム戦', 0):.0%}、一般戦なら{dict((x[0], x[1]['in1']) for x in measures).get('一般戦', 0):.0%}({fun_rate(dict((x[0], x[1]['in1']) for x in measures).get('一般戦', 0))})。"
                f"堅いのは本当。ただし、どれもオッズの見立てどおりに来ていて、みんな知っている。"
                f"目立つのは{best[0]}({ratio_words(best[1]['market_ratio'])}、{best[1]['n_odds']}レース)。レース数がまだ少ないので追試中。",
        "tables": [],  # 結果の表と同じ中身なので出さない
        "measures": measures,
        "use": ["企画レースは「インが堅い」より「堅いことが知られている」レース。1号艇を買うなら配当は安い、を前提に考える",
                "堅いレースこそ、2着・3着の並びで差がつく。差し型・まくり差し型の選手が2〜3号艇にいるかを見る",
                "オッズの見立てを大きく超える企画レースが見つかったら追試する(ミカタは毎週ここを更新する)"],
        "mikata": "『堅い』と『おいしい』は別もの。堅いレースは、2着3着で遊ぶのがコツかも",
        "gen": "知ってたよ。でもな、堅いレースの2着探しがいちばんおもしろいんだ。そこが腕の見せどころ",
        "challenge": "企画レースを1つ選んで、1号艇は「来るもの」と決めてしまい、2着・3着だけを当てにいく。差し屋・まくり差しの人が2〜3号艇にいるかが勝負",
        "numbers": {},
    }


def t_streak(ent, r):
    """イン逃げが続いたあとは荒れる?(ギャンブラーの錯覚)"""
    r2 = r.sort_values(["date", "jcd", "rno"]).copy()
    prev = r2.groupby(["date", "jcd"])["c1"].shift(1)
    prev2 = r2.groupby(["date", "jcd"])["c1"].shift(2)
    prev3 = r2.groupby(["date", "jcd"])["c1"].shift(3)
    m3 = (prev == 1) & (prev2 == 1) & (prev3 == 1)
    m0 = (prev == 0) & (prev2 == 0)
    a, b = measure(r2, m3.fillna(False)), measure(r2, m0.fillna(False))
    return {
        "id": "streak", "title": "イン逃げが続いたあとは荒れるのか", "belief": "同じ場で1号艇が3連続で逃げたら、次は荒れる(そろそろ来る)",
        "lead": f"同じ日・同じ場で1号艇が3つ続けて勝ったあとのレースは{a['n']:,}レース。その次の1号艇の1着率は{a['in1']:.0%}で、全体の{a['in1_ref']:.0%}と"
                f"{'ほぼ同じ' if abs(a['in1'] - a['in1_ref']) < 0.03 else 'はっきり違う'}。逆に2つ続けて負けたあとは{b['in1']:.0%}。"
                "前のレースの結果は、次のレースには影響しない(それぞれ別のレース)。",
        "tables": [],
        "measures": [("1号艇が3連勝したあと", a, verdicts(a)), ("1号艇が2連敗したあと", b, verdicts(b))],
        "use": ["『そろそろ荒れる』『そろそろ来る』は、前のレースとは関係ない。見るべきはそのレースの6人と水面",
                "ただし同じ日の同じ場で風が強まっているなら話は別。それは『流れ』ではなく天気"],
        "mikata": "ルーレットで赤が続いたら次は黒、と同じやつ。レースは毎回まっさらだよ",
        "gen": "…そうは言っても、3つ続いたら次は荒れる気がするんだよ。気がするだけでも、買うのは楽しいだろ?",
        "challenge": "1号艇が3連勝したとき、友達が「そろそろ荒れる」と言ったら、この記事を見せる。そのうえで6人のSTと決まり手を見て、自分の予想を立てる",
        "numbers": {},
    }


def t_a1in(ent, r):
    """一般戦で1号艇にA1が置かれたレースは堅いか。"""
    cls = ent[ent["lane"] == 1].set_index("race_id")["racer_class"]
    r2 = r[r["race_title"].isin(["一般戦", "一般", "予選"])].copy()
    r2["c1cls"] = r2["race_id"].map(cls)
    a = measure(r2, r2["c1cls"] == "A1")
    b = measure(r2, r2["c1cls"] == "B1")
    return {
        "id": "a1in", "title": "1号艇がA1なら堅いのか", "belief": "予選・一般戦で1号艇にA1級が入ったレースは堅い",
        "lead": f"予選・一般戦で1号艇がA1級のレース({a['n']:,}レース)の1号艇の1着率は{a['in1']:.0%}、B1級なら{b['in1']:.0%}。"
                f"差は本物。ただしA1は{ratio_words(a.get('market_ratio'))}、B1は{ratio_words(b.get('market_ratio'))}で、どちらもオッズの見立てどおり。"
                "級別はみんな見ている。",
        "tables": [],
        "measures": [("1号艇がA1", a, verdicts(a)), ("1号艇がB1", b, verdicts(b))],
        "use": ["級別は出走表でいちばん目立つ情報なので、オッズにいちばん早く織り込まれる。級別『以外』の材料(ST・決まり手の型・今節の足)で差をつける",
                "B1の1号艇でも、平均STが速くて逃げ率が高い選手ならA1なみ。ミカタ新聞のカードはそこを見る"],
        "mikata": "A1かどうかは、みんな見てる。見てないところを見るのが、いろんな角度ってやつ",
        "gen": "A1は見りゃ分かる。俺が見てるのはスタートの構えだ。B1でもピタッと行くやつはいる",
        "challenge": "今日の出走表から、B1の1号艇で「平均STが速い・逃げ率が高い」人を1人見つける。A1なみに扱ってみて、結果を友達と答え合わせ",
        "numbers": {},
    }


def t_maezuke(ent, r):
    """前づけ: ルールの整理と「勝てるなら全員やればいい?」への答え。"""
    e = ent[ent["course"].between(1, 6) & ent["finish"].between(1, 6)].copy()
    full = e.groupby("race_id")["lane"].transform("size") == 6
    e = e[full]
    e["win"] = e["finish"] == 1
    e["front"] = e["course"] < e["lane"]
    rf = e.groupby("race_id")["front"].any()
    r2 = r[r["race_id"].isin(e["race_id"].unique())].copy()
    r2["has_front"] = r2["race_id"].map(rf).fillna(False).astype(bool)
    a = measure(r2, r2["lane_c1"] == 1, col="cc1", qcol="qc1")                      # 枠なりの1コース
    b = measure(r2, r2["lane_c1"].between(2, 3), ref=r2["lane_c1"] == 1, col="cc1", qcol="qc1")   # 2・3号艇が前づけで1コース
    c = measure(r2, r2["lane_c1"] >= 4, ref=r2["lane_c1"] == 1, col="cc1", qcol="qc1")            # 4〜6号艇が前づけで1コース
    for m, nm in ((a, "枠なり"), (b, "2・3号艇から"), (c, "4〜6号艇から")):
        m["note"] = nm
    va, vb, vc = verdicts(a), verdicts(b), verdicts(c)
    va["baseline"] = True
    # ST(助走の深さ)と、押し出された1号艇
    ok = e["st"].notna() & e["st_flag"].isna() & (e["st"] < 0.6)
    c1 = e[(e["course"] == 1) & ok]
    st_nari, st_front = float(c1[c1["lane"] == 1]["st"].mean()), float(c1[c1["lane"] > 1]["st"].mean())
    pushed = e[(e["lane"] == 1) & (e["course"] == 2)]
    base_c2 = float(e[(e["course"] == 2) & (e["lane"] == 2)]["win"].mean())
    fr = e[e["front"]]
    base_l = e[~e["race_id"].isin(rf[rf].index)].groupby("lane")["win"].mean()
    own = float(fr["win"].mean()); own_ref = float(fr["lane"].map(base_l).mean())
    reg = e[e["lane"] > 1].groupby("racer_id").agg(n=("front", "size"), f=("front", "mean")).query("n >= 150")
    n_reg = int((reg["f"] > 0.3).sum())
    vshare = e.groupby("jcd").apply(lambda d: d.groupby("race_id")["front"].any().mean()).sort_values(ascending=False)
    rows = [{"venue": VENUES[int(j)], "rno": "", "n": int(e[e["jcd"] == j]["race_id"].nunique()), "in1": float(v)} for j, v in vshare.head(6).items()]
    share = float(rf.mean())
    return {
        "id": "maezuke", "title": "前づけは本当に得なのか", "belief": "内のコースを取れば勝てる。なら、全員が前づけすればいいじゃないか",
        "lead": f"前づけがあるレースは全体の{share:.0%}。前づけで1コースに入った艇が勝つのは、2・3号艇からなら{b['in1']:.0%}、4〜6号艇からだと{c['in1']:.0%}。"
                f"枠なりの1コース({a['in1']:.0%})より低い。助走が短くなってスタートが平均{st_front - st_nari:.3f}秒遅れるから。"
                f"それでも本人には得({own_ref:.0%}→{own:.0%})。ただし押し出された1号艇は{pushed['win'].mean():.0%}まで下がり、取り合いになれば両方が深くなる。",
        "subject": "1コースの艇",
        "rules": ["コースは艇の番号(枠)で決まっていない。ピットを出てからスタートまでの「待機行動」の間に、各艇が自分で取る(内から1〜6コース)",
                  "枠より内のコースを取ることを「前づけ」と言う(2号艇が1コースへ、6号艇が2コースへ、など)。入られた艇は外へずれる",
                  "内のコースほど助走が短い(スロー勢)。外は長い助走で全速(ダッシュ勢)。前づけで割り込むと、自分も押し出された艇も助走が足りず「深い」スタートになりやすい",
                  "企画レースなど「進入固定」のレースは枠なりで固定。前づけはできない",
                  "待機行動には決まりがあり(内側のブイより内へ入らない、時間の制限など)、違反は減点などの対象。ここは公式のルールを確かめてほしい"],
        "tables": [("前づけが多い場", rows, "前づけがあるレースの割合")],
        "measures": [("枠なりの1号艇(基準)", a, va), ("2・3号艇が前づけで1コース", b, vb), ("4〜6号艇が前づけで1コース", c, vc)],
        "conclusion": ["本人は得。でも、全員はできない", f"前づけした本人の1着率は{own_ref:.0%}→{own:.0%}。ただし1コースの値打ちは下がり({a['in1']:.0%}→{b['in1']:.0%})、押し出された1号艇は{pushed['win'].mean():.0%}。取り合いになれば両方が深くなる"],
        "faq": [("勝てるなら、全員が前づけすればいい?",
                 f"本人だけ見れば得(枠なりなら{own_ref:.0%}の1着率が、前づけすると{own:.0%})。でも3つの壁がある。①1コースの値打ちが下がる: 助走が短くなってスタートが平均{st_front - st_nari:.3f}秒遅れ、"
                 f"1着率は枠なりの{a['in1']:.0%}が{c['in1']:.0%}(4〜6号艇から)まで落ちる。②押し出された1号艇は{pushed['win'].mean():.0%}(ふだんの2コースの{base_c2:.0%}より低い)。相手も譲らなければ取り合いになり、両方が深くなって外のダッシュ勢が得をする。"
                 f"③実際にやる人は少ない。前づけ率30%を超える選手は{n_reg}人(主にベテラン)。多くの選手は枠なりで走るのが暗黙の了解になっている"),
                ("前づけされた1号艇はどうなる?", f"2コースへ押し出されるのが大半で、1着率は{pushed['win'].mean():.0%}。ふだんの2コース({base_c2:.0%})より低いのは、助走が深くなるから"),
                ("前づけした艇は、オッズに織り込まれている?", f"2・3号艇が1コースに入ったレース({b.get('n_odds', 0)}レース)では、オッズの見立て({per100(b['in1'] / b['market_ratio']) if b.get('market_ratio') else '-'})より実際({per100(b['in1'])})がかなり多い。"
                 "ただし、集めているオッズは締切の少し前の値なので、進入が決まったあとの動きを取り切れていない可能性がある。レース数も少ないので追試中"),
                ("前づけが多いのはどんなとき?", f"場で差がある(上の表)。前づけの常連が出走表にいる日は、進入が決まるまでが最初のレース。ミカタ新聞のカードの「前づけの仕掛け人」の型がその目印")],
        "use": ["出走表に前づけの常連(カードの「前づけの仕掛け人」)がいたら、1号艇の1着率を55%ではなく50%前後で考える",
                "前づけで内に入った艇より、押し出されずに済んだ艇と、外で全速になれるダッシュ勢のほうが得をすることが多い",
                "進入が読めないレースは、展示航走(直前)の進入を見てから決める。アプリの直前予想は展示の進入で計算している"],
        "mikata": "前づけの常連がいる日は、スタート展示を見るまで予想を決めないのがコツ。進入が決まった瞬間、レースはもう半分始まってる",
        "gen": "取れりゃ勝てるが、取り合いになったら共倒れだ。前づけは仕掛ける相手を見てやるもんなんだよ",
        "challenge": "出走表から前づけ率の高い選手を1人見つけて、進入がどうなるか友達と当てっこ。展示航走で答え合わせ",
        "numbers": {"share": share, "st_nari": st_nari, "st_front": st_front, "own": own, "own_ref": own_ref, "pushed": float(pushed["win"].mean()), "n_regular": n_reg},
    }


def _entries(ent):
    """1行=1艇の表(着順のある走)。measure() に渡せる形(c1=3着以内, late, date)。"""
    e = ent[ent["finish"].between(1, 6)].copy()
    e["course"] = e["course"].fillna(e["lane"])
    e["c1"] = (e["finish"] <= 3).astype(float)
    e["upset"] = 0.0
    e["late"] = pd.to_datetime(e["date"]).dt.year >= 2025
    e["date"] = e["date"].astype(str)
    return e


def t_tenji(ent, r):
    """展示タイム番長は本物か。展示で調子は測れるか。"""
    e = _entries(ent)
    x = e[e["exhibit_time"].notna() & e["course"].between(1, 6)].copy()
    x["exr"] = x.groupby("race_id")["exhibit_time"].rank(method="min")
    base_ = x.groupby(["exr", "course"])["c1"].mean()
    x["res"] = x["c1"] - pd.MultiIndex.from_arrays([x["exr"], x["course"]]).map(base_).values
    x["res_own"] = x["res"] - x.groupby("racer_id")["res"].transform("mean")
    g = x.assign(t=(x["exr"] <= 2).astype(float)).groupby("racer_id").agg(n=("t", "size"), top=("t", "mean"), w=("weight", "mean"), tilt=("tilt", "mean"))
    g = g[g["n"] >= 50]
    th = float(g["top"].quantile(0.9))
    king = set(g.index[g["top"] >= th])
    x["king"] = x["racer_id"].isin(king)
    # 本人のふだんの展示順位と比べた今日の順位(調子)
    x = x.sort_values(["date", "race_id"])
    x["own_rank"] = x.groupby("racer_id")["exr"].transform(lambda q: q.shift(1).rolling(30, min_periods=10).mean())
    x["form"] = x["own_rank"] - x["exr"]
    m1 = measure(x, x["exr"] == 1)
    m6 = measure(x, x["exr"] == 6)
    up = measure(x, x["form"] >= 2, ref=x["form"].between(-0.5, 0.5))
    dn = measure(x, x["form"] <= -2, ref=x["form"].between(-0.5, 0.5))
    v1, v6, vu, vd = verdicts(m1), verdicts(m6), verdicts(up), verdicts(dn)
    # 番長が展示上位のときの上積み(本人のふだん比) vs ほかの選手
    kt = float(x[x["king"] & (x["exr"] <= 2)]["res_own"].mean()); ot = float(x[~x["king"] & (x["exr"] <= 2)]["res_own"].mean())
    kb = float(x[x["king"] & (x["exr"] >= 4)]["res_own"].mean()); ob = float(x[~x["king"] & (x["exr"] >= 4)]["res_own"].mean())
    cw = float(g["top"].corr(g["w"])); ct = float(g["top"].corr(g["tilt"]))
    n_k = len(king)
    return {
        "id": "tenji", "title": "展示タイム番長は本物か", "belief": "展示タイムがいつも速い選手がいる。でも、ああいうのは展示だけで本番は関係ないんだ",
        "subject": "その艇", "verb": "3着以内に入る", "no_market": True,
        "compare": "展示1位・6位の行はすべての艇、「ふだんより上・下」の行は展示の順位がふだん通りだった日",
        "lead": f"展示タイムが1位の艇が3着以内に入るのは100レースで{per100(m1['in1'])}({fun_rate(m1['in1'])})、6位だと{per100(m6['in1'])}。展示はちゃんと効く。"
                f"展示で1・2位になる割合は、同じ選手なら時期を変えてもほぼ同じ顔ぶれ(「展示タイム番長」は本物の型)。"
                f"そして番長が展示上位のときも、ほかの選手と同じだけ本番に効いていた。「展示だけの人」は、時期を変えると入れ替わる。",
        "conclusion": ["番長は本物。展示も、ちゃんと効く", f"展示1位は3着内{per100(m1['in1'])}、6位は{per100(m6['in1'])}。番長が展示上位のときの上積みも、ほかの選手とほぼ同じ。「展示だけ」の人は時期で入れ替わる"],
        "rules": ["展示航走: レース前に、6艇が本番と同じように走ってみせる。そのときの「1周の一部のタイム」が展示タイム(速いほど足がいい目安)",
                  "展示タイムは体重が軽いほど、チルト(エンジンの角度)を上げるほど速く出やすい。だから「いつも速い人」がいる",
                  "ミカタでは、展示タイムが1・2位になる割合が同じ級別で上位10%の選手に「展示タイム番長」の型を付けている"],
        "tables": [],
        "measures": [("展示タイム1位", m1, v1), ("展示タイム6位", m6, v6), ("展示の順位が、本人のふだんより2つ以上上", up, vu), ("本人のふだんより2つ以上下", dn, vd)],
        "faq": [("展示タイム番長って、展示だけじゃないの?",
                 f"本人のふだんと比べた上積みで見ると、番長が展示1・2位のときは{kt * 100:+.1f}ポイント、ほかの選手が展示1・2位のときは{ot * 100:+.1f}ポイント。ほぼ同じだけ効いている。"
                 f"番長が展示4位以下のときも{kb * 100:+.1f}ポイント(ほかの選手は{ob * 100:+.1f})。番長だから特別に崩れる、ということもない。展示の順位は誰にでも同じように効く"),
                ("「この人は展示が良くても意味ない」はある?",
                 "選手ごとに「展示上位のときの上積み」を奇数月と偶数月で比べると、顔ぶれがほとんど入れ替わる。つまり「展示だけの人」は、たまたまそう見えていただけのことが多い"),
                ("なぜいつも展示が速い人がいるの?",
                 f"番長の顔ぶれは体重が軽い選手やチルトを上げる選手が多い(展示上位率と体重の関係は{'はっきりある' if cw <= -0.3 else 'ややある'}、チルトとも{'はっきりある' if ct >= 0.3 else 'ややある'})。"
                 "軽さやチルトはそのまま本番の伸びにもつながるので、展示だけの見かけではない"),
                ("展示で「今日の調子」は測れる?",
                 f"測れる。展示の順位が本人のふだんより2つ以上上の日は、3着内が100レースで{per100(up['in1'])}(ふだん通りの日は{per100(up['in1_ref'])})、2つ以上下の日は{per100(dn['in1'])}。"
                 "ただしこれは「その日の展示順位」の効き目そのもの。ふだんとの比較は、出走表を見るときの目安として使うのがいい")],
        "use": ["展示タイム番長が展示4位以下 → 展示の順位が下がったぶんだけ、本番の見込みも下がる(番長だから特別、ではない)",
                "ふだん展示が下位の選手が1・2位 → 今日は仕上がっている合図",
                "展示が良くても意味ない人、と決めつけない。展示は誰にでも同じくらい効く"],
        "mikata": "展示タイムは、レース前にもらえるいちばん新しい情報。番長かどうかより、今日の順位がふだんとどう違うか。そこに目をつけると、予想が一段おもしろくなるよ",
        "gen": "俺はストップウォッチで展示を測る派だ。速いやつは速い。それが本番でも効くってんなら、文句はねえ",
        "challenge": "今日の展示で「ふだんより2つ以上上の選手」を1人見つけて、友達に先に言っておく。本番で3着以内に来たら、あなたの勝ち",
        "numbers": {"king_threshold": th, "n_king": n_k, "king_top_res": kt, "other_top_res": ot, "king_bot_res": kb, "other_bot_res": ob, "corr_weight": cw, "corr_tilt": ct},
    }


def t_flying(ent, r):
    """フライング(と失格・転覆)のあと、選手はどう変わるか。"""
    e = ent.copy()
    e["course"] = e["course"].fillna(e["lane"])
    e = e.sort_values(["racer_id", "date", "rno"]).reset_index(drop=True)
    e["k"] = e.groupby("racer_id").cumcount()
    F = ((e["st_flag"] == "F") | (e["result_code"] == "F"))
    DQ = e["result_code"].isin(["S0", "S1", "S2"])

    def since_until(flag):
        pos = e["k"].where(flag)
        last = pos.groupby(e["racer_id"]).ffill().groupby(e["racer_id"]).shift(1)   # 前の行までで最後の事故
        nxt = pos.groupby(e["racer_id"]).bfill().groupby(e["racer_id"]).shift(-1)   # 次の行から先で最初の事故
        return e["k"] - last, nxt - e["k"]
    fs, fu = since_until(F)
    ds, du = since_until(DQ)
    x = e[e["finish"].between(1, 6)].copy()
    x["c1"] = (x["finish"] <= 3).astype(float); x["upset"] = 0.0
    x["late"] = pd.to_datetime(x["date"]).dt.year >= 2025; x["date"] = x["date"].astype(str)
    x["fs"], x["fu"], x["ds"], x["du"] = fs, fu, ds, du
    before = x["fu"].between(1, 30) & ~x["fs"].between(1, 40)
    a10 = measure(x, x["fs"].between(1, 10), ref=before)
    a40 = measure(x, x["fs"].between(11, 40), ref=before)
    a120 = measure(x, x["fs"].between(41, 120), ref=before)
    d5 = measure(x, x["ds"].between(1, 5), ref=x["du"].between(1, 30) & ~x["ds"].between(1, 20))
    ok = x["st"].between(0, 0.5) & x["st_flag"].isna()
    stb = float(x[before & ok]["st"].mean())
    st10, st40, st120 = (float(x[m & ok]["st"].mean()) - stb for m in (x["fs"].between(1, 10), x["fs"].between(11, 40), x["fs"].between(41, 120)))
    std = float(x[x["ds"].between(1, 5) & ok]["st"].mean()) - float(x[x["du"].between(1, 30) & ok]["st"].mean())
    nF = int(F.sum()); nD = int(DQ.sum())
    return {
        "id": "flying", "title": "フライングのあと、選手はどう変わる?", "belief": "フライングを切った選手は、しばらくスタートを控える。だから狙い目が変わる",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True,
        "compare": "同じ選手のフライング前30走(失格の行は失格前30走)",
        "lead": f"フライング{nF:,}回のあとを追いかけた。直後の10走はスタートが平均{st10:+.3f}秒遅くなり、3着以内は100レースで{per100(a10['in1'])}(本人のフライング前は{per100(a10['in1_ref'])})。"
                f"11〜40走目でも{st40:+.3f}秒・{per100(a40['in1'])}。41走目あたりでほぼ元に戻る。失格(転覆・落水・エンストなど)のあとは、ほんの少し下がるだけ。",
        "conclusion": ["本当。F後40走はスタート控えめ", f"直後10走はSTが{st10:+.3f}秒、3着内が{(a10['in1'] - a10['in1_ref']) * 100:+.0f}ポイント。40走ほどで戻る。どれだけ控えるかは同じ選手でも毎回ちがう"],
        "rules": ["フライング(F): スタートの合図(大時計の0秒)より前にスタートラインを越えること。その艇は返還(舟券は払い戻し)になり、選手には休み(F休み)などの処分がある",
                  "Fを持っているあいだにもう一度Fを切ると処分が重くなるので、選手はしばらくスタートを慎重にする(「F持ち」)",
                  "公式の成績データでは、転覆・落水・エンストなどは「失格」としてまとめて記録されている。ここでは失格のあととして見ている",
                  "処分の細かい中身(休みの日数など)は時期で変わるので、公式のルールで確かめてほしい"],
        "tables": [],
        "measures": [("F直後の10走", a10, verdicts(a10)), ("F後11〜40走", a40, verdicts(a40)), ("F後41〜120走", a120, verdicts(a120)), ("失格(転覆など)直後の5走", d5, verdicts(d5))],
        "faq": [("スタートはどれくらい遅くなる?",
                 f"本人のフライング前と比べて、直後10走で{st10:+.3f}秒、11〜40走で{st40:+.3f}秒、41〜120走で{st120:+.3f}秒。0.03秒は、全速(秒速18〜22m)なら約60cm。艇の長さ(約3m)の5分の1ほどで、0.1秒の差がほぼ艇1つぶん"),
                ("慎重になりやすい選手はいる?",
                 "同じ選手の1回目と2回目のフライングで「どれだけ控えたか」を比べると、ほとんど関係がなかった(人ごとの差は時期で入れ替わる)。誰でも同じくらい控える、と考えるのがいい"),
                ("転覆したあとは?",
                 f"失格(転覆・落水・エンストなど){nD:,}回のあと5走は、3着内が{(d5['in1'] - d5['in1_ref']) * 100:+.0f}ポイント、スタートは{std:+.3f}秒。フライングほどは変わらない。多くの選手は翌日も走っている"),
                ("アプリではどう見える?", "選手カードに「F後◯走目」と出る(最後のフライングから40走以内、180日以内のとき)。直後10走なら「スタート控えめ」の目安")],
        "use": ["出走表で「F後◯走目」の選手がいたら、STは平均より0.02〜0.03秒遅く見積もる",
                "F後の選手が内のコースなら、外の艇がスタートで先に出る展開を考える",
                "F後10走を過ぎたら少しずつ戻る。40走を過ぎたら、ほぼいつも通り"],
        "mikata": "フライングのあとは、誰でもスタートが少し慎重になる。その「少し」が、まくりの入り口になったりするんだよね",
        "gen": "F持ちのインは信じるな、ってのは昔からの決まり文句だ。データでも本当だったか。よし",
        "challenge": "今日の出走表から「F後」の選手を探して、その選手の外にいる艇のスタートに注目。外がのぞいたら、ゲンさんの勝ち",
        "numbers": {"n_flying": nF, "n_dq": nD, "st10": st10, "st40": st40, "st120": st120, "st_dq": std},
    }


def t_combo(ent, r):
    """型と型の組み合わせで狙い目はあるか。型は前半2年で決め、後半1年のレースで測る(後出しにならないように)。"""
    e = ent[ent["finish"].between(1, 6) | ent["finish"].isna()].copy()
    e["course"] = e["course"].fillna(e["lane"])
    e["yr"] = pd.to_datetime(e["date"]).dt.year
    pre = e[(e["yr"] < 2025) & e["finish"].between(1, 6)]
    # 前半2年の型(全体の割合に寄せた率)
    def shrunk(w, n, prior, k=20):
        return (w + prior * k) / (n + k)
    c1 = pre[pre["course"] == 1].groupby("racer_id").agg(n=("finish", "size"), w=("finish", lambda q: (q == 1).sum()))
    p1 = float(c1["w"].sum() / c1["n"].sum())
    nige = shrunk(c1["w"], c1["n"], p1)
    out = pre[pre["course"] >= 2]
    kim = r.set_index("race_id")["kimarite"] if "kimarite" in r else None
    if kim is not None:   # 決まり手: 1逃げ 2差し 3まくり 4まくり差し 5抜き 6恵まれ
        out = out.assign(k=pd.to_numeric(out["race_id"].map(kim), errors="coerce"))
        mk = out.assign(m=(out["finish"] == 1) & (out["k"] == 3), s_=(out["finish"] == 1) & (out["k"] == 2))
    else:
        mk = out.assign(m=False, s_=False)
    g = mk.groupby("racer_id").agg(n=("m", "size"), m=("m", "sum"), s_=("s_", "sum"))
    makuri = shrunk(g["m"], g["n"], float(g["m"].sum() / g["n"].sum()))
    sashi = shrunk(g["s_"], g["n"], float(g["s_"].sum() / g["n"].sum()))
    st = pre[pre["st"].between(0, 0.5) & pre["st_flag"].isna()].groupby("racer_id")["st"].agg(["mean", "size"])
    stv = (st["mean"] * st["size"] + 0.16 * 20) / (st["size"] + 20)
    q = lambda x, a: float(x.quantile(a))  # noqa: E731
    weak_in, strong_in = set(nige.index[nige <= q(nige, .3)]), set(nige.index[nige >= q(nige, .7)])
    mk_set = set(makuri.index[makuri >= q(makuri, .8)]); sa_set = set(sashi.index[sashi >= q(sashi, .8)])
    fast = set(stv.index[stv <= q(stv, .3)])
    # 後半1年のレース: コースごとの選手
    late = e[e["yr"] >= 2025]
    who = late.pivot_table(index="race_id", columns="course", values="racer_id", aggfunc="first")
    lane_of = late.pivot_table(index="race_id", columns="course", values="lane", aggfunc="first")
    rr = r[r["race_id"].isin(who.index)].copy().set_index("race_id")
    for c in (1, 2, 3, 4):
        rr[f"r{c}"] = who[c].reindex(rr.index) if c in who else np.nan
        rr[f"l{c}"] = lane_of[c].reindex(rr.index) if c in lane_of else np.nan
    rr = rr.reset_index()
    inw, ins = rr["r1"].isin(weak_in), rr["r1"].isin(strong_in)
    atk3 = rr["r3"].isin(mk_set) & rr["r3"].isin(fast)
    atk4 = rr["r4"].isin(mk_set) & rr["r4"].isin(fast)
    sa2 = rr["r2"].isin(sa_set)
    known = rr["r1"].isin(set(nige.index))
    # 攻める艇(3コース)が勝つか、のための列
    rr["w3"] = (rr["win_lane"] == rr["l3"]).astype(float)
    if "q_l1" in rr:
        rr["q3"] = [rr.at[i, f"q_l{int(l)}"] if l == l else np.nan for i, l in zip(rr.index, rr["l3"])]
    mA = measure(rr, inw & atk3, ref=known, col="cc1", qcol="qc1")
    mB = measure(rr, ins & atk3, ref=known, col="cc1", qcol="qc1")
    mC = measure(rr, inw & sa2, ref=known, col="cc1", qcol="qc1")
    mD = measure(rr, inw & (atk3 | atk4) & sa2, ref=known, col="cc1", qcol="qc1")
    a3 = measure(rr, inw & atk3, ref=rr["l3"].notna(), col="w3", qcol="q3") if "q3" in rr else None
    ms = [("1コースが逃げ下手 × 3コースにまくり屋(ST速い)", mA, verdicts(mA)), ("1コースが逃げ上手 × 3コースにまくり屋(ST速い)", mB, verdicts(mB)),
          ("1コースが逃げ下手 × 2コースに差し屋", mC, verdicts(mC)), ("1コースが逃げ下手 × 差し屋と攻め屋の両方", mD, verdicts(mD))]
    lead = (f"1コースの艇が勝つのは、ふつう100レースで{per100(mA['in1_ref'])}。1コースが逃げ下手で3コースにスタートの速いまくり屋がいると{per100(mA['in1'])}、"
            f"逃げ上手なら同じ相手でも{per100(mB['in1'])}。逃げ下手の内に差し屋がいると{per100(mC['in1'])}、差し屋と攻め屋がそろうと{per100(mD['in1'])}。"
            "型の組み合わせは、1コースの強さをはっきり動かす。")
    a3txt = (f"そのとき3コースのまくり屋が勝つのは100レースで{per100(a3['in1'])}(3コースの艇のふだんは{per100(a3['in1_ref'])})。"
             + (f"オッズの見立ては{per100(a3['in1'] / a3['market_ratio'])}。" if a3 and a3.get("market_ratio") else "")) if a3 else ""
    return {
        "id": "combo", "title": "型と型の組み合わせで狙い目はあるか", "belief": "逃げ下手の1号艇の隣に、スタートの速いまくり屋。こういう並びは荒れる",
        "subject": "1コースの艇", "lead": lead,
        "conclusion": ["本当。並びで1コースは大きく変わる",
                       f"逃げ下手×スタートの速いまくり屋で、1コースは100レース中{per100(mA['in1'])}(ふだん{per100(mA['in1_ref'])})。オッズもそこまでは見込んでいない。逃げ上手なら{per100(mB['in1'])}で、こちらはオッズどおり"],
        "rules": ["型は、前の2年(2023〜2024年)の成績だけで決めた。測ったのは、そのあとの1年(2025年〜)のレース(後出しにならないように)",
                  "逃げ下手/上手: 1コースでの逃げ率が下から30%/上から30%。まくり屋・差し屋: 2コース以遠からまくり・差しで勝つ割合が上から20%。ST速い: 平均STが速い方から30%",
                  "コースは実際の進入で数えた(前づけで変わった場合も、入ったコースの選手で判定)"],
        "tables": [],
        "measures": ms,
        "faq": [("なら、その並びのとき3コースを買えばいい?", a3txt + "組み合わせはオッズにも、ある程度は映っている。①は本当でも、②の「みんな知ってる?」を見てから"),
                ("1号艇が強ければ、まくり屋がいても平気?", f"逃げ上手の1号艇なら、まくり屋(ST速い)が3コースにいても1コースは{per100(mB['in1'])}。ふだんの{per100(mB['in1_ref'])}と比べてどうかが、この表のいちばんの見どころ"),
                ("型はどこで見られる?", "ミカタの選手カードの型(イン逃げ番長・まくり屋・差し職人・スタート職人)と同じ考え方。出走表で、1コースと2〜4コースの型の並びを見る")],
        "use": ["出走表を見たら、まず1コースの逃げの強さ。次に、2コースに差し屋、3・4コースにスタートの速いまくり屋がいるか",
                "逃げ下手 × 攻め屋の並びは、1号艇を頭から外す候補。ただしオッズも少し動いているので、2着・3着で工夫する",
                "逃げ上手の1号艇は、攻め屋がいても崩れにくい。そこは素直に"],
        "mikata": "型は1人ずつ見るより、並びで見るともっとおもしろい。1コースと3コースの型を、指でなぞってみて",
        "gen": "昔から『逃げ下手の隣にまくり屋は買い』って言うんだよ。数字にしたら、やっぱりそうだろ?",
        "challenge": "今日の出走表から「逃げ下手の1号艇 × 3コースのまくり屋」のレースを1つ探す。見つけたら、そのレースだけ1号艇を外して予想してみる",
        "numbers": {"n_weak_in": len(weak_in), "n_makuri": len(mk_set), "n_sashi": len(sa_set), "n_fast": len(fast)},
    }


# ---------------------------------------------------------------- からだと暦(2026-10-05 追加)
# 体・疲れ・移動・暦の「よく言われること」を同じ物差しで。選手ごとの話は「本人のふだん」との差で見る
# (強い選手がどこでも良く見える、を避ける)。表の数字は「本人のふだんとの差を、全体の平均(100走で約50回)に足したもの」。
BRANCH_JCD = {"群馬": 1, "埼玉": 2, "東京": 4, "静岡": 6, "愛知": 8, "三重": 9, "福井": 10, "滋賀": 11, "大阪": 12, "兵庫": 13,
              "徳島": 14, "香川": 15, "岡山": 16, "広島": 17, "山口": 18, "福岡": 20, "佐賀": 23, "長崎": 24}
VENUE_XY = {1: (36.405, 139.312), 2: (35.814, 139.656), 3: (35.683, 139.870), 4: (35.579, 139.741), 5: (35.624, 139.591),
            6: (34.711, 137.593), 7: (34.827, 137.235), 8: (34.878, 136.837), 9: (34.698, 136.521), 10: (36.230, 136.146),
            11: (35.021, 135.886), 12: (34.609, 135.479), 13: (34.723, 135.433), 14: (34.185, 134.610), 15: (34.296, 133.790),
            16: (34.465, 133.814), 17: (34.318, 132.306), 18: (34.054, 131.796), 19: (33.967, 130.946), 20: (33.904, 130.819),
            21: (33.887, 130.671), 22: (33.595, 130.395), 23: (33.453, 129.972), 24: (32.916, 129.955)}
SAME = "本人のふだん(全体の平均にそろえてある)"


def _adj(ent):
    """1行=1艇。c1 = 全体の3着内率 + 本人のふだんとの差(コースの有利不利も差し引き)。"""
    x = ent[ent["finish"].between(1, 6)].copy()
    x["course"] = x["course"].fillna(x["lane"])
    x["top3"] = (x["finish"] <= 3).astype(float)
    x["res"] = x["top3"] - x.groupby("course")["top3"].transform("mean")
    x["res_own"] = x["res"] - x.groupby("racer_id")["res"].transform("mean")
    base_ = float(x["top3"].mean())
    x["c1"] = base_ + x["res_own"]
    x["upset"] = 0.0
    dd = pd.to_datetime(x["date"])
    x["late"] = dd.dt.year >= 2025
    x["month"], x["day"] = dd.dt.month, dd.dt.day
    x["dt"] = dd
    x["date"] = x["date"].astype(str)
    return x


def _gap(x, ca, cb, minn=15, by="month"):
    """「この人は◯◯に強い」が人ごとに続くか: 選手ごとの(条件aの上積み−条件bの上積み)を、月(日)の奇数・偶数で比べた相関。"""
    res = []
    for par in (1, 0):
        y = x[x[by] % 2 == par]
        a = y[ca.loc[y.index]].groupby("racer_id")["res_own"].agg(["size", "mean"])
        b = y[cb.loc[y.index]].groupby("racer_id")["res_own"].agg(["size", "mean"])
        j = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
        j = j[(j.size_a >= minn) & (j.size_b >= minn)]
        res.append(j.mean_a - j.mean_b)
    jj = pd.concat(res, axis=1, keys=["o", "e"]).dropna()
    return (float(jj.o.corr(jj.e)) if len(jj) > 30 else float("nan")), int(len(jj))


def _pp(m):
    """ふだんとの差をポイントで(+2.3)。"""
    return f"{(m['in1'] - m['in1_ref']) * 100:+.1f}"


def _person(r_):
    v, n = r_
    return f"時期を変えると{sim_words(v)}({n}人で確認)"


def t_rest(ent, r):
    """休み明け・連戦・忙しさ。"""
    x = _adj(ent).sort_values(["racer_id", "dt", "rno"]).reset_index(drop=True)
    days = x.groupby("racer_id")["dt"].diff().dt.days
    x["gap"] = days
    # 休み明け: 30日以上あいた後の最初の3走 / 連戦: 前の走から2日以内に別の場で走る(節をまたいだ連戦)
    first_after = x["gap"] >= 30
    x["k_after"] = first_after.groupby(x["racer_id"]).cumsum()
    x["n_in"] = x.groupby(["racer_id", "k_after"]).cumcount()
    back = (x["k_after"] > 0) & (x["n_in"] < 3) & x.groupby(["racer_id", "k_after"])["gap"].transform("first").ge(30)
    long_back = back & x.groupby(["racer_id", "k_after"])["gap"].transform("first").ge(90)
    x["prev_jcd"] = x.groupby("racer_id")["jcd"].shift(1)
    renzoku = (x["gap"] <= 2) & (x["prev_jcd"] != x["jcd"])
    # 直近7日の走数(忙しさ)
    busy = x.set_index("dt").groupby("racer_id")["c1"].transform(lambda s_: s_.rolling("7D").count())
    x["busy"] = busy.values
    normal = (~back) & (~renzoku)
    mb = measure(x, back, ref=normal)
    ml = measure(x, long_back, ref=normal)
    mr = measure(x, renzoku, ref=normal)
    mbz = measure(x, x["busy"] >= 12, ref=x["busy"].between(4, 8))
    pb = _gap(x, back, normal, 6)
    ms = [("30日以上の休み明け、最初の3走", mb, verdicts(mb)), ("90日以上の長い休み明け", ml, verdicts(ml)),
          ("前の節から中1日以内で別の場へ(連戦)", mr, verdicts(mr)), ("直近7日で12走以上(忙しい)", mbz, verdicts(mbz))]
    real_back = verdicts(mb)["real"] or verdicts(ml)["real"]
    con = (["休み明けは少し鈍る。連戦はむしろ好調", f"90日以上の休み明けは{_pp(ml)}ポイント、30日以上なら{_pp(mb)}。前の節から中1日以内の連戦は{_pp(mr)}で、疲れより勢いが勝っている"]
           if real_back else ["休み明けも連戦も、思ったより平気", f"休み明け{_pp(mb)}・連戦{_pp(mr)}ポイント。選手は思ったより、すぐ戻ってくる"])
    return {
        "id": "rest", "title": "休み明けと連戦、どっちが響く?", "belief": "休み明けは勘が戻ってない。連戦は疲れがたまる。どっちも買いにくい",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"休み明け(30日以上あいた後の最初の3走)は、本人のふだんと比べて{_pp(mb)}ポイント。90日以上の長い休みだと{_pp(ml)}。"
                f"前の節から中1日以内で別の場へ移る連戦は{_pp(mr)}、7日で12走以上の忙しい時期は{_pp(mbz)}。",
        "conclusion": con, "tables": [], "measures": ms,
        "rules": ["数字は、その選手の「ふだん」とくらべた差。強い選手も弱い選手も、自分自身とくらべている",
                  "休み明けの理由(けが、F休み、出産、ただの休み)はデータでは分からないので、まとめて見ている"],
        "faq": [("休み明けに弱い人はいる?", f"選手ごとの「休み明けの落ち方」は、{_person(pb)}"),
                ("長い休み明けは、何走で戻る?", "休み明けの最初の3走で見ている。4走目以降はふだんの数字とほとんど区別がつかない"),
                ("連戦がむしろ良いのはなぜ?", f"中1日で次の節に来るのは、前の節を最後まで走った(勝ち上がった)選手が多い。調子のいい選手が、そのまま次へ来ている。疲れは見えなかった"),
                ("忙しい週は落ちる?", f"7日で12走以上は{_pp(mbz)}ポイント。ただ、忙しい週は1日2走の日が多く、2走目は番組の作りで相手が強くなりやすい(『1走目と2走目』の回)。疲れとは分けられない")],
        "use": ["長い休み明け(前の節が3か月以上前)の選手は、最初の3走は少し割り引く",
                "連戦の選手を「疲れてそう」で外すのは、データ的にはもったいない。むしろ勢いがある"],
        "mikata": "休み明けはちょっとだけ鈍る、連戦はむしろ好調。勢いって、データにも出るんだね",
        "gen": "休み明けの選手には、俺は初日だけは目をつむる。2日目からが本番よ" if real_back else "休み明けでも走れるのか。プロってのはすげえな。でも俺は、なんとなく初日は外すね",
        "challenge": "今日の出走表で、前の節がいちばん昔の選手を探す。その人の1走目のスタートを見てみよう",
        "numbers": {"back": mb["in1"] - mb["in1_ref"], "long_back": ml["in1"] - ml["in1_ref"], "renzoku": mr["in1"] - mr["in1_ref"], "person_back": pb[0]},
    }


def t_travel(ent, r):
    """遠征の距離。"""
    x = _adj(ent)
    home = x["branch"].map(BRANCH_JCD)
    lat1 = home.map(lambda j: VENUE_XY.get(j, (np.nan, np.nan))[0]); lon1 = home.map(lambda j: VENUE_XY.get(j, (np.nan, np.nan))[1])
    lat2 = x["jcd"].map(lambda j: VENUE_XY[int(j)][0]); lon2 = x["jcd"].map(lambda j: VENUE_XY[int(j)][1])
    rad = np.pi / 180
    a_ = np.sin((lat2 - lat1) * rad / 2) ** 2 + np.cos(lat1 * rad) * np.cos(lat2 * rad) * np.sin((lon2 - lon1) * rad / 2) ** 2
    x["km"] = 6371 * 2 * np.arcsin(np.sqrt(a_))
    x = x[x["km"].notna()]
    near = x["km"] < 60
    mid = x["km"].between(60, 300)
    far = x["km"].between(300, 600)
    vfar = x["km"] >= 600
    m0, m1, m2, m3 = (measure(x, c) for c in (near, mid, far, vfar))
    pf = _gap(x, vfar | far, near | mid, 20)
    ms = [("地元の近く(60km未満)", m0, verdicts(m0)), ("60〜300km", m1, verdicts(m1)), ("300〜600km", m2, verdicts(m2)), ("600km以上の大遠征", m3, verdicts(m3))]
    return {
        "id": "travel", "title": "遠征は不利なのか", "belief": "地元は水面を知っているから強い。遠くから来た選手は、移動の疲れもあって不利だ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "その選手の全部の走(全体の平均にそろえてある)",
        "lead": f"所属する支部(住んでいる地域)から開催場までの距離で分けた。地元の近くは本人のふだんより{_pp(m0)}ポイント、"
                f"60〜300kmは{_pp(m1)}、300〜600kmは{_pp(m2)}、600km以上の大遠征は{_pp(m3)}。",
        "conclusion": ["地元は少しだけ強い。遠さは関係ない", f"地元の近くは{_pp(m0)}ポイント。60kmを超えると、隣の県でも九州から関東でも同じ({_pp(m1)}〜{_pp(m3)})。移動の疲れは見えなかった"],
        "tables": [], "measures": ms,
        "rules": ["距離は、所属支部の県にあるレース場から開催場までの直線距離(住所は使っていない)",
                  "数字は、その選手のふだんとくらべた差"],
        "faq": [("遠征に弱い人はいる?", f"選手ごとの「遠くでの落ち方」は、{_person(pf)}"),
                ("地元が強いのは、水面を知っているから?", "60kmを超えるとどれだけ遠くても同じなので、移動の疲れではなさそう。地元の水面に慣れている・応援がある、のほうが近い。データだけでは分けられない")],
        "use": ["地元の選手は、ほんの少しだけ上に見る。遠征の選手を『遠いから』で下げる必要はない",
                "差は小さいので、モーターや展示のほうを先に見る"],
        "mikata": "遠征は関係なかった。プロの体力ってすごい。地元の声援でちょっとだけ上がるのは、なんだかいい話だよね",
        "gen": "地元のファンの前で負けられねえ、って気持ちは数字じゃ測れねえよ。俺は地元を買う",
        "challenge": "今日の出走表で、いちばん遠くから来た選手を見つける。支部の場所と開催場を地図で見くらべてみよう",
        "numbers": {"near": m0["in1"] - m0["in1_ref"], "vfar": m3["in1"] - m3["in1_ref"], "person_far": pf[0]},
    }


def t_weight(ent, r):
    """当日の体重の増減と、夏の重量級。"""
    x = _adj(ent)
    x["dw"] = (x["weight_now"] - x["weight"]).where((x["weight_now"] - x["weight"]).abs() <= 6)
    x = x.sort_values(["racer_id", "dt", "rno"])
    wn = x["weight_now"].where(x["weight_now"] > 30)
    own = wn.groupby(x["racer_id"]).transform(lambda s_: s_.shift(1).rolling(30, min_periods=10).mean())   # 直近30走の平均(長い目の増減は除く)
    x["dwo"] = wn - own
    light = x["dwo"] <= -1.5; heavy = x["dwo"] >= 1.5; usual = x["dwo"].abs() < 0.5
    ml, mh = measure(x, light, ref=usual), measure(x, heavy, ref=usual)
    wq = x.groupby("racer_id")["weight_now"].transform("mean")
    big = wq >= wq.quantile(0.67); small = wq <= wq.quantile(0.33)
    hot, cold = x["air_temp"] >= 28, x["air_temp"] <= 12
    mbh, mbc = measure(x, big & hot, ref=big), measure(x, small & hot, ref=small)
    pw = _gap(x, hot, cold, 15, by="day")
    ms = [("当日の体重が本人のふだんより1.5kg以上軽い", ml, verdicts(ml)), ("1.5kg以上重い", mh, verdicts(mh)),
          ("重い選手(体重の重い方の3分の1)× 28℃以上", mbh, verdicts(mbh)), ("軽い選手 × 28℃以上", mbc, verdicts(mbc))]
    return {
        "id": "weight", "title": "夏は重い選手が不利って本当?", "belief": "暑いとエンジンの力が落ちる。だから夏は体重の軽い選手が有利だ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"28℃以上の暑い日、体重の重い選手は本人のふだんより{_pp(mbh)}ポイント、軽い選手は{_pp(mbc)}。向きは説のとおり、でも小さい。"
                f"それより効いていたのは当日の体重。直近30走の平均より1.5kg以上軽い日は{_pp(ml)}、重い日は{_pp(mh)}。",
        "conclusion": ["夏の重量級は少しだけ本当。もっと効くのは『当日の体重』",
                       f"暑い日の重い選手{_pp(mbh)}・軽い選手{_pp(mbc)}ポイントに対して、当日の体重がふだんより軽い日{_pp(ml)}・重い日{_pp(mh)}。体重計の数字は、出走表のなかでも見落とされがち"],
        "tables": [], "measures": ms,
        "rules": ["体重は直前情報の当日体重。登録の体重とのずれが6kgを超える記録は、入力ミスとみて外した",
                  "選手の体重は最低体重が決まっていて、足りない分はおもり(重量調整)を積む。だから軽すぎる選手の有利には上限がある"],
        "faq": [("暑さに強い・弱い選手はいる?", f"選手ごとの「暑い日−寒い日」の差は、{_person(pw)}"),
                ("当日の体重が軽いのは、調子がいいから?", "減量がうまくいった日なのか、体調で落ちたのかは、データだけでは分からない。ただ、軽い日のほうが成績がいい向きは、前の2年と最近の1年で同じだった"),
                ("どこで見られる?", "直前情報の『体重』。出走表の体重(登録)ではなく、当日の体重をふだんとくらべる")],
        "use": ["直前情報の体重が、その選手のふだんより1.5kg以上軽い → 少し上に。重い → 少し下に",
                "真夏の日中は、重い選手をほんの少しだけ下に"],
        "mikata": "説は正しかった、ほんの少しだけ。それより体重計の数字が効いていたのは、ちょっとした発見だね",
        "gen": "だろ? 夏は軽いのを買う。それに当日の体重か……体重計を見に行く楽しみが増えたな",
        "challenge": "暑い日の出走表で、いちばん重い選手といちばん軽い選手を見つけて、どっちが先にゴールするか見てみよう",
        "numbers": {"big_hot": mbh["in1"] - mbh["in1_ref"], "small_hot": mbc["in1"] - mbc["in1_ref"], "person_heat": pw[0]},
    }


def t_dayno(ent, r):
    """節の何日目に強い?(初日・中日・最終日)"""
    x = _adj(ent)
    last = x.groupby(["jcd", "racer_id"])["day_no"].transform("max")
    d1, d2, d4, dl = x["day_no"] == 1, x["day_no"].between(2, 3), x["day_no"] == 4, (x["day_no"] >= 5) & (x["day_no"] == last)
    title = x["race_type"].astype(str)
    fin = dl & ~title.str.contains("優勝|準優")      # 最終日の一般戦(予選落ちの選手が多い)
    m1, m2, m4, mf = (measure(x, c) for c in (d1, d2, d4, fin))
    p1 = _gap(x, d1, x["day_no"].between(2, 4), 12)
    pf = _gap(x, fin, x["day_no"].between(2, 4), 6)
    ms = [("節の初日", m1, verdicts(m1)), ("2・3日目", m2, verdicts(m2)), ("4日目", m4, verdicts(m4)), ("最終日の一般戦(予選で落ちた選手など)", mf, verdicts(mf))]
    return {
        "id": "dayno", "title": "節の何日目に強い?", "belief": "初日は様子見、最終日の一般戦は気が抜けてる。選手には得意な日がある",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"本人のふだんとくらべて、節の初日は{_pp(m1)}ポイント、2・3日目は{_pp(m2)}、4日目は{_pp(m4)}、"
                f"最終日の一般戦は{_pp(mf)}。",
        "conclusion": ["日によって少し違う。でも人ごとの得意はない", f"初日{_pp(m1)}、最終日の一般戦{_pp(mf)}ポイント。「初日に強い人」は{sim_words(p1[0])}"],
        "tables": [], "measures": ms,
        "rules": ["節(ひとつの大会)はふつう4〜6日間。前半は予選、終盤に準優勝戦・優勝戦。予選で落ちた選手は最終日に一般戦を走る",
                  "数字は、その選手のふだんとくらべた差"],
        "faq": [("初日に強い人、最終日に強い人はいる?", f"初日の得意は{_person(p1)}。最終日の一般戦の得意は{_person(pf)}"),
                ("最終日の一般戦は、気が抜けている?", f"最終日の一般戦は{_pp(mf)}ポイントで、気が抜けるどころか少し上。予選で落ちた選手どうしの組み合わせなので、相手もそれほど強くないから")],
        "use": ["「この人は初日に強い」は、あまり当てにしない", "最終日の一般戦は『気が抜ける』と決めつけない。相手も同じ予選落ちの選手"],
        "mikata": "得意な日、ありそうでなかった。毎日がまっさらなんだね",
        "gen": "それでも俺は初日だけは、エンジンの気配を見るために買わずに眺めるね。それが楽しいんだよ",
        "challenge": "初日の展示タイムをメモしておいて、3日目にもう一度くらべる。モーターの『育ち方』が見えるよ",
        "numbers": {"d1": m1["in1"] - m1["in1_ref"], "last_ippan": mf["in1"] - mf["in1_ref"], "person_d1": p1[0]},
    }


def t_twice(ent, r):
    """1日2走の日、1走目と2走目。朝昼夜。1走目を引きずる?"""
    x = _adj(ent).sort_values(["racer_id", "date", "rno"])
    x["nth"] = x.groupby(["racer_id", "date"]).cumcount() + 1
    two = x.groupby(["racer_id", "date"])["rno"].transform("size") == 2
    first = x[two & (x["nth"] == 1)].set_index(["racer_id", "date"])["finish"]
    x["first_fin"] = pd.MultiIndex.from_arrays([x["racer_id"], x["date"]]).map(first).values
    s2 = two & (x["nth"] == 2)
    m1, m2 = measure(x, two & (x["nth"] == 1), ref=two), measure(x, s2, ref=two)
    mg, mb = measure(x, s2 & (x["first_fin"] == 1), ref=s2), measure(x, s2 & (x["first_fin"] >= 4), ref=s2)
    hh = pd.to_numeric(x["deadline"].astype(str).str.extract(r"(\d{1,2}):")[0], errors="coerce")
    morning, night, noon = hh < 12, hh >= 18, hh.between(12, 15)
    pn = _gap(x, morning, noon, 20); pt = _gap(x, two & (x["nth"] == 1), s2, 15); pd_ = _gap(x[s2], (x["first_fin"] >= 4)[s2], (x["first_fin"] <= 3)[s2], 10)
    mm, mn = measure(x, morning), measure(x, night)
    ms = [("1日2走の日の1走目", m1, verdicts(m1)), ("2走目", m2, verdicts(m2)), ("1走目が1着だった日の2走目", mg, verdicts(mg)), ("1走目が4〜6着だった日の2走目", mb, verdicts(mb))]
    return {
        "id": "twice", "title": "1走目と2走目、どっちが得意?", "belief": "1走目で負けると引きずる。それに、朝に強い人・夜に強い人がいる",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "1日2走の日の全体(本人のふだんにそろえてある)",
        "lead": f"1日2走の日、1走目は{_pp(m1)}ポイント、2走目は{_pp(m2)}。1走目が1着の日の2走目は{_pp(mg)}、4〜6着の日は{_pp(mb)}。"
                f"時間帯では、朝(〜11時台)は{(mm['in1'] - mm['in1_ref']) * 100:+.1f}、夜(18時〜)は{(mn['in1'] - mn['in1_ref']) * 100:+.1f}。",
        "conclusion": ["差はある。でも「人ごとの得意」ではない", f"2走目が低いのは、後半のレースほど相手が強い番組の作りのせい。1走目が悪い日の2走目が低いのは、同じモーター・同じ調整の『その日の足』が両方に出ているから"],
        "tables": [], "measures": ms,
        "rules": ["1日に2回走る日がある(多くは前半と後半に1回ずつ)。後半のレースほど、強い選手同士の組み合わせが多い",
                  "時間帯は締切の時刻で分けた。朝の早いレース(モーニング)や夜のレース(ナイター)は場によって違う"],
        "faq": [("1走目と2走目、得意な人はいる?", f"選手ごとの差は{_person(pt)}"),
                ("朝に強い人・夜に強い人は?", f"朝−昼の得意は{_person(pn)}"),
                ("1走目を引きずる人は?", f"「悪かった日の2走目の落ち方」は{_person(pd_)}。引きずるかどうかは、その日の足しだい")],
        "use": ["1走目が悪かった選手の2走目は、気持ちではなく『足が弱い日』として少し割り引く",
                "朝型・夜型で選手を分けるのは、データ的にはおすすめしない"],
        "mikata": "引きずっているように見えるのは、足のせい。選手の気持ちは、たぶん切り替わってるよ",
        "gen": "いや、1走目で大負けしたやつの顔は、2走目のピットで分かるんだよ。……まあ、データがそう言うなら半分信じる",
        "challenge": "1日2走の選手を1人決めて、1走目の展示タイムと2走目の展示タイムを並べてみる。足の変化が見えたら上級者",
        "numbers": {"first": m1["in1"] - m1["in1_ref"], "second": m2["in1"] - m2["in1_ref"], "after_bad": mb["in1"] - mb["in1_ref"]},
    }


def t_tilt(ent, r):
    """チルトを跳ねた選手。"""
    x = _adj(ent)
    out = x["course"] >= 4
    hi, mid, low = x["tilt"] >= 1.5, x["tilt"].between(0.5, 1.0), x["tilt"] <= 0
    mh, mm, ml = measure(x, out & hi, ref=out & low), measure(x, out & mid, ref=out & low), measure(x, (x["course"] <= 2) & hi, ref=(x["course"] <= 2) & low)
    ms = [("4〜6コースでチルト1.5度以上(跳ねた)", mh, verdicts(mh)), ("4〜6コースでチルト0.5〜1度", mm, verdicts(mm)), ("1・2コースでチルト1.5度以上", ml, verdicts(ml))]
    return {
        "id": "tilt", "title": "チルトを跳ねた選手は来るのか", "belief": "チルトを上げた(跳ねた)選手は伸びる。外から一発がある",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "同じコースでチルトを上げていないとき(本人のふだんにそろえてある)",
        "lead": f"4〜6コースでチルトを1.5度以上に上げた選手は、上げていないときとくらべて{_pp(mh)}ポイント。0.5〜1度なら{_pp(mm)}。"
                f"内(1・2コース)で跳ねると{_pp(ml)}。",
        "conclusion": (["本当。跳ねた選手は来る。外ならなおさら", f"4〜6コースで1.5度以上は{_pp(mh)}ポイント、内でも{_pp(ml)}。跳ねるのは足に自信がある日、というのも混ざっていそう"]
                       if verdicts(mh)["real"] and mh["in1"] > mh["in1_ref"] else ["ふだんと同じ。跳ねても劇的には変わらない", f"4〜6コースで1.5度以上は{_pp(mh)}ポイント"]),
        "tables": [], "measures": ms,
        "rules": ["チルト: エンジンの取り付け角度。上げる(跳ねる)と直線の伸びが良くなるかわりに、ターンが流れやすくなる",
                  "ふだんは-0.5度か0度の選手が多い。1.5度以上は全体の1%ほど"],
        "faq": [("跳ねる選手はいつも跳ねる?", "チルトをよく上げる選手は決まっていて、展示タイム番長にも多い。直線の伸びで勝負するタイプ"),
                ("チルトを上げたから来るの? 足がいいから上げるの?", f"両方ありそう。内のコースで跳ねても{_pp(ml)}なので、『足に自信がある日に跳ねる』分も入っている。データだけでは分けられない")],
        "use": ["出走表の直前情報でチルトを見る。外のコースで1.5度以上なら、まくりの一発を頭に入れる"],
        "mikata": "チルトの数字を見るだけで、選手の作戦が分かる。直前情報のいちばん楽しい行かもしれないね",
        "gen": "跳ねたやつは、腹をくくってる。そういう選手は応援したくなるんだよな",
        "challenge": "今日の直前情報でチルトが一番高い選手を探して、1周目のバックストレッチで伸びるか見てみよう",
        "numbers": {"out_hi": mh["in1"] - mh["in1_ref"], "in_hi": ml["in1"] - ml["in1_ref"]},
    }


def _moon(dates: pd.Series) -> pd.Series:
    """月齢(0=新月、約14.8=満月)。2000-01-06 18:14 UTC の新月から朔望月 29.530589 日で数える。"""
    t = (pd.to_datetime(dates) + pd.Timedelta(hours=12) - pd.Timestamp("2000-01-06 18:14")).dt.total_seconds() / 86400
    return t % 29.530589


def t_moon(ent, r):
    """満月は荒れる?(オカルト枠)"""
    x = r.copy()
    age = _moon(x["date"])
    full, new = (age - 14.77).abs() <= 1.2, (age <= 1.2) | (age >= 28.3)
    mf, mn = measure(x, full), measure(x, new)
    uf, un, ua = float(x[full]["upset"].mean()), float(x[new]["upset"].mean()), float(x["upset"].mean())
    ms = [("満月の日(前後1日)", mf, verdicts(mf)), ("新月の日(前後1日)", mn, verdicts(mn))]
    return {
        "id": "moon", "title": "満月の夜は荒れるのか", "belief": "満月の日は潮も人も騒ぐ。だから荒れる",
        "lead": f"満月の日(前後1日)に1号艇が勝つのは100レースで{per100(mf['in1'])}、新月の日は{per100(mn['in1'])}、全体は{per100(mf['in1_ref'])}。"
                f"3連単で30番人気以下が来た割合は、満月{uf:.1%}・新月{un:.1%}・全体{ua:.1%}。",
        "conclusion": (["ふだんと同じ。月は関係なかった", "満月でも新月でも、1号艇の強さも荒れ方も、ふだんとほとんど同じ"]
                       if not (verdicts(mf)["real"] or verdicts(mn)["real"]) else ["差があった", f"満月{per100(mf['in1'])}・新月{per100(mn['in1'])}"]),
        "tables": [], "measures": ms,
        "rules": ["月齢は日付から計算(正午の月齢)。満月・新月の前後1日をまとめた",
                  "海の近くの場は、月で潮の満ち引きが変わる。でも潮は満月と新月の両方で大きくなるので、ここでは月の形そのものを見ている"],
        "faq": [("潮の影響はないの?", "潮位は満月・新月の両方で大きく動く(大潮)。どちらも1号艇の数字はふだん並みだった。潮の時間帯ごとの検証は、潮位のデータを集めてから別にやる")],
        "use": ["月で予想を変える必要はない。……でも満月の夜に1つだけ穴を買うのは、ありだと思う"],
        "mikata": "月は関係なかった。でも満月の夜のナイターって、それだけで特別な気分になるよね",
        "gen": "データがどう言おうが、満月の夜は穴を1点だけ買う。それが俺の流儀よ。外れたら月のせいにできるしな",
        "challenge": "次の満月の日を調べて、その日のナイターで1レースだけ『月の穴』を予想してみよう。外れても笑える",
        "numbers": {"in1_full": mf["in1"], "in1_new": mn["in1"], "upset_full": uf, "upset_new": un, "upset_all": ua},
    }


def t_manshu(ent, r):
    """万舟のあとは荒れる?(流れ)"""
    x = r.sort_values(["date", "jcd", "rno"]).copy()
    x["man"] = (pd.to_numeric(x["tri_pay"], errors="coerce") >= 10000).astype(float)
    prev = x.groupby(["date", "jcd"])["man"].shift(1)
    prev2 = x.groupby(["date", "jcd"])["man"].shift(2)
    a1, a2 = (prev == 1), (prev == 1) & (prev2 == 1)
    m1, m2, m0 = measure(x, a1.fillna(False)), measure(x, a2.fillna(False)), measure(x, (prev == 0).fillna(False))
    man1, man2, man0 = float(x[a1.fillna(False)]["man"].mean()), float(x[a2.fillna(False)]["man"].mean()), float(x[(prev == 0).fillna(False)]["man"].mean())
    ms = [("前のレースが万舟", m1, verdicts(m1)), ("2つ続けて万舟のあと", m2, verdicts(m2)), ("前のレースが万舟でない", m0, verdicts(m0))]
    real = abs(man1 - man0) >= 0.02
    return {
        "id": "manshu", "title": "万舟のあとは、また荒れる?", "belief": "万舟が出た日は『荒れる流れ』。次も穴を狙え",
        "lead": f"同じ日・同じ場で、前のレースが万舟(3連単1万円以上)だったとき、次のレースも万舟になったのは{man1:.1%}。"
                f"前が万舟でなかったときは{man0:.1%}、2つ続けて万舟のあとは{man2:.1%}。1号艇が勝つのは100レースで{per100(m1['in1'])}(全体{per100(m1['in1_ref'])})。",
        "conclusion": (["少しだけ本当。でも理由は『流れ』じゃない", f"万舟のあとの万舟は{man1:.1%}(ふだん{man0:.1%})。荒れやすい場・荒れやすい天気の日は続けて荒れる、というだけ"]
                       if real else ["ふだんと同じ。流れはなかった", f"万舟のあとの万舟は{man1:.1%}、ふだんは{man0:.1%}"]),
        "tables": [], "measures": ms,
        "rules": ["同じ日・同じ場の、ひとつ前のレースの結果で分けた", "万舟は3連単の払戻が1万円以上"],
        "faq": [("風が強い日は続けて荒れるのでは?", "そのとおりで、荒れやすい日(風・波・場)は1日を通して荒れやすい。前のレースが万舟だったことそのものが、次を荒らすわけではない"),
                ("じゃあ、荒れた日は穴を狙っていい?", "荒れた理由が天気なら、その日は穴を少し多めに。でも『流れ』だけを理由にするのは、データ的にはおすすめしない")],
        "use": ["万舟が続いたら、まず風と波を確認。原因が天気なら、次のレースも荒れ気味に見る",
                "原因が分からないなら、次のレースはまっさらに"],
        "mikata": "流れに見えるものの正体は、だいたい天気。でも流れに乗って穴を買う楽しさは、データじゃ消せないよね",
        "gen": "流れってのはあるんだよ。……天気のことだったのか。まあ、呼び方なんてどっちでもいい",
        "challenge": "万舟が出たら、その日の風と波をメモ。次のレースが荒れたら、天気のせいか流れのせいか友達と議論しよう",
        "numbers": {"man_after_man": man1, "man_after_not": man0, "man_after_2": man2},
    }


def t_lucky7(ent, r):
    """ラッキー7のモーター(オカルト枠)。"""
    x = _adj(ent)
    mno = pd.to_numeric(x["motor_no"], errors="coerce")
    seven = (mno % 10) == 7
    same = mno % 10 == x["lane"]
    m7, ms_ = measure(x, seven), measure(x, same)
    p7 = float(x[seven]["motor_2rate"].mean()); pa = float(x["motor_2rate"].mean())
    ms = [("モーター番号の末尾が7", m7, verdicts(m7)), ("モーター番号の末尾と艇番が同じ", ms_, verdicts(ms_))]
    return {
        "id": "lucky7", "title": "ラッキー7のモーターは当たり?", "belief": "モーター番号の末尾が7なら、なんかいい。艇番と同じ数字もツイてる",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"モーター番号の末尾が7の選手は、本人のふだんとくらべて{_pp(m7)}ポイント。末尾が艇番と同じ数字なら{_pp(ms_)}。"
                f"末尾7のモーターの2連率の平均は{p7:.1f}%(全体{pa:.1f}%)。",
        "conclusion": (["ふだんと同じ。7は普通の数字だった", "モーター番号の末尾で成績は変わらない。モーターの良し悪しは2連率と展示で見る"]
                       if not verdicts(m7)["real"] else ["差があった", f"末尾7は{_pp(m7)}ポイント"]),
        "tables": [], "measures": ms,
        "rules": ["モーターは節の前日に抽選で選手に割り当てられる。番号は場ごとの通し番号"],
        "faq": [("じゃあ何で選べばいい?", "モーターの2連率(出走表にある)と、今節の展示タイム。番号ではなく、数字の中身を見る")],
        "use": ["モーター番号は気にしない。でも推しが7番を引いたら、ちょっとうれしい、くらいで"],
        "mikata": "7は普通だった。でも、うれしい気持ちで見るレースは楽しいから、それでいいと思う",
        "gen": "7を引いたやつは顔が明るい。顔が明るいやつは、なんかやる。……データには出ねえけどな",
        "challenge": "今日の出走表で、末尾7のモーターの選手を探して『ラッキー7枠』として応援してみよう",
        "numbers": {"seven": m7["in1"] - m7["in1_ref"], "same": ms_["in1"] - ms_["in1_ref"], "motor2_seven": p7, "motor2_all": pa},
    }


def t_rain(ent, r):
    """雨の日はインが強い? 雨に強い選手はいる?"""
    x = r.copy()
    w = x["weather"].astype(str)
    rain, snow, fine = w == "雨", w == "雪", w == "晴"
    mr, ms_, mf = measure(x, rain, ref=fine), measure(x, snow, ref=fine), measure(x, w == "曇り", ref=fine)
    ur, uf = float(x[rain]["upset"].mean()), float(x[fine]["upset"].mean())
    e = _adj(ent)
    wmap = r.set_index("race_id")["weather"].astype(str)
    ew = e["race_id"].map(wmap)
    pr = _gap(e, ew == "雨", ew == "晴", 10, by="day")
    ms = [("雨の日", mr, verdicts(mr)), ("雪の日", ms_, verdicts(ms_)), ("曇りの日", mf, verdicts(mf))]
    return {
        "id": "rain", "title": "雨の日はインが強い?", "belief": "雨だと水面が重くなって、まくりが決まりにくい。だからインが強い。雨に強い選手もいる",
        "compare": "晴れの日",
        "lead": f"1号艇が勝つのは、雨の日に100レースで{per100(mr['in1'])}、晴れの日は{per100(mr['in1_ref'])}、雪の日は{per100(ms_['in1'])}。"
                f"3連単で30番人気以下が来た割合は、雨{ur:.1%}・晴れ{uf:.1%}。",
        "conclusion": (["ふだんと同じ。雨でもインは変わらない", f"雨{per100(mr['in1'])}・晴れ{per100(mr['in1_ref'])}。雨の日に強い選手も、時期を変えると{sim_words(pr[0])}"]
                       if not verdicts(mr)["real"] else [f"雨の日は1号艇が{'強い' if mr['in1'] > mr['in1_ref'] else '弱い'}", f"雨{per100(mr['in1'])}・晴れ{per100(mr['in1_ref'])}"]),
        "tables": [], "measures": ms,
        "rules": ["天候は公式の成績データの記録(レース時点)。雨の強さまでは分からない", "雨より、風と波のほうがレースを大きく動かす(『風とイン』の回)"],
        "faq": [("雨巧者はいる?", f"選手ごとの「雨の日−晴れの日」の差は、{_person(pr)}"),
                ("じゃあ雨の日は何を見る?", "風と波。雨そのものより、雨といっしょに吹く風のほうが効く")],
        "use": ["雨だからインを厚く、はしなくていい", "雨の日は風向きと風速を先に確認"],
        "mikata": "雨は関係なかった。でも雨のしぶきの中を走るボート、かっこいいよね",
        "gen": "雨の日のレースは客が少ねえ。静かなスタンドで見るのが最高なんだよ。それで十分だ",
        "challenge": "次の雨の日、カッパを着て現地へ。晴れの日とスタンドの景色を見くらべてみよう",
        "numbers": {"in1_rain": mr["in1"], "in1_fine": mr["in1_ref"], "upset_rain": ur, "upset_fine": uf, "person_rain": pr[0]},
    }


def t_age(ent, r):
    """何歳がいちばん強い? 年齢と成長・衰え(同じ選手の1年あたりの変化)。"""
    x = _adj(ent)
    base_ = float(x["top3"].mean())
    x["c1"] = base_ + x["res"]          # コースの有利不利だけ差し引いた3着内率(本人の強さは残す)
    bins = [(18, 24, "24歳以下"), (25, 29, "25〜29歳"), (30, 34, "30〜34歳"), (35, 39, "35〜39歳"), (40, 44, "40〜44歳"),
            (45, 49, "45〜49歳"), (50, 54, "50〜54歳"), (55, 80, "55歳以上")]
    # 同じ選手の「1年あたりの変化」: 3年間の上積み(コース差し引き)を時間で回帰した傾き(100走以上)
    t = (x["dt"] - pd.Timestamp("2025-01-01")).dt.days / 365.25
    g = pd.DataFrame({"r": x["racer_id"], "t": t, "y": x["res"], "age": x["age"]})
    g["tm"] = g.groupby("r")["t"].transform("mean"); g["ym"] = g.groupby("r")["y"].transform("mean")
    g["cov"] = (g["t"] - g["tm"]) * (g["y"] - g["ym"]); g["var"] = (g["t"] - g["tm"]) ** 2
    sl = g.groupby("r").agg(n=("y", "size"), cov=("cov", "sum"), var=("var", "sum"), age=("age", "median"))
    sl = sl[(sl["n"] >= 100) & (sl["var"] > 0)]
    sl["slope"] = sl["cov"] / sl["var"]
    rows, tbl = [], []
    for lo, hi, nm in bins:
        m_ = (x["age"] >= lo) & (x["age"] <= hi)
        s_ = sl[(sl["age"] >= lo) & (sl["age"] <= hi)]["slope"]
        a1 = float((x.loc[m_].drop_duplicates("racer_id")["racer_class"] == "A1").mean())
        rows.append({"nm": nm, "c1": float(x.loc[m_, "c1"].mean()), "a1": a1, "slope": float(s_.mean()) if len(s_) else float("nan"), "ns": int(len(s_))})
        tbl.append({"venue": nm, "rno": "", "n": int(m_.sum()), "in1": float(x.loc[m_, "c1"].mean())})
    best = max(rows, key=lambda q: q["c1"]); a1best = max(rows, key=lambda q: q["a1"])
    young, old = rows[0], rows[-1]
    peak = max(rows, key=lambda q: q["slope"])
    turn = next((q["nm"] for q in rows if q["slope"] < 0), None)
    ms = []
    for lo, hi, nm in ((18, 24, "24歳以下"), (35, 39, "35〜39歳"), (55, 80, "55歳以上")):
        m_ = (x["age"] >= lo) & (x["age"] <= hi)
        mm = measure(x, m_)
        ms.append((nm, mm, verdicts(mm)))
    slope_txt = "、".join(f"{q['nm']} {q['slope'] * 100:+.1f}" for q in rows if q["slope"] == q["slope"])
    return {
        "id": "age", "title": "ボートレーサーは何歳がいちばん強い?", "belief": "ボートは体重が軽くて反射神経がいい若手が有利。でも経験のベテランも強い。結局どっち?",
        "subject": "その年齢の選手", "verb": "3着以内に入る", "no_market": True, "compare": "全選手(コースの有利不利は差し引き)",
        "lead": f"コースの有利不利を差し引いた3着内率は{best['nm']}がいちばん高く{best['c1']:.0%}、A1級の割合も{a1best['nm']}が{a1best['a1']:.0%}でいちばん多い。"
                f"同じ選手が1年でどれだけ変わるかを見ると、24歳以下は1年に{young['slope'] * 100:+.1f}ポイント、55歳以上は{old['slope'] * 100:+.1f}ポイント。"
                + (f"伸びがマイナスに変わるのは{turn}から。" if turn else ""),
        "conclusion": [f"いちばん強いのは{best['nm']}。伸び盛りは{peak['nm']}",
                       f"若手は1年に{young['slope'] * 100:+.1f}ポイントずつ伸び、30代半ばでほぼ横ばい、そこからゆっくり下がる(55歳以上で1年に{old['slope'] * 100:+.1f})。"],
        "tables": [("年齢ごとの3着内率(コースの有利不利を差し引き)", tbl, "3着内率")],
        "measures": ms,
        "rules": ["年齢は出走表の年齢。3着内率はコースの有利不利をそろえた値",
                  "1年あたりの変化は、同じ選手の3年間(100走以上)の成績を時間で並べたときの傾き。年齢は3年間の真ん中あたり",
                  "弱い選手ほど早く引退するので、年齢が上の選手は『残っている強い人』が多い(生き残りの偏り)"],
        "faq": [("年齢ごとの1年あたりの変化は?", f"(ポイント/年){slope_txt}"),
                ("若手は狙い目?", f"24歳以下は1年に{young['slope'] * 100:+.1f}ポイント伸びている。出走表の勝率は過去の数字なので、伸び盛りの若手は勝率より強いことが多い(『上り調子』の型)"),
                ("ベテランはもう厳しい?", f"55歳以上は1年に{old['slope'] * 100:+.1f}ポイント。下がり方はゆっくりで、スタートや前づけなど、経験で戦う選手も多い")],
        "use": ["勝率が同じなら、若手を少し上に(勝率はこれから上がる)", "ベテランは『型』を見る。前づけ・スタート職人は経験の型"],
        "mikata": "若手はぐんぐん伸びて、ベテランは技で残る。どの年代にも見どころがあるね",
        "gen": "俺と同い年の選手が今日も走ってる。それだけで買う理由になるんだよ",
        "challenge": "今日の出走表で、いちばん若い選手といちばんベテランの選手を見つけて、どっちが先にゴールするか見てみよう",
        "numbers": {"best_age": best["nm"], "peak_growth": peak["nm"], "turn": turn, "slopes": {q["nm"]: q["slope"] for q in rows}},
    }


def t_zorome(ent, r):
    """ゾロ目の日は荒れる?(オカルト枠)"""
    x = r.copy()
    dd = pd.to_datetime(x["date"])
    zoro = dd.dt.month == dd.dt.day
    fri13 = (dd.dt.day == 13) & (dd.dt.dayofweek == 4)
    mz, mf = measure(x, zoro), measure(x, fri13)
    uz, uf, ua = float(x[zoro]["upset"].mean()), float(x[fri13]["upset"].mean()), float(x["upset"].mean())
    nd = int(dd[zoro].dt.date.nunique()); nf = int(dd[fri13].dt.date.nunique())
    ms = [("ゾロ目の日(1/1、2/2…12/12)", mz, verdicts(mz)), ("13日の金曜日", mf, verdicts(mf))]
    return {
        "id": "zorome", "title": "ゾロ目の日と13日の金曜日", "belief": "11月11日みたいなゾロ目の日は何かが起きる。13日の金曜日は大荒れだ",
        "lead": f"ゾロ目の日({nd}日分)に1号艇が勝つのは100レースで{per100(mz['in1'])}、13日の金曜日({nf}日分)は{per100(mf['in1'])}、全体は{per100(mz['in1_ref'])}。"
                f"30番人気以下の3連単が来た割合は、ゾロ目の日{uz:.1%}・13日の金曜日{uf:.1%}・全体{ua:.1%}。",
        "conclusion": (["ふだんと同じ。カレンダーは関係なかった", "ゾロ目の日も13日の金曜日も、ふだんどおりのレースだった"]
                       if not (verdicts(mz)["real"] or verdicts(mf)["real"]) else ["差があった……かも", "日数が少ないので、たまたまの幅も大きい"]),
        "tables": [], "measures": ms,
        "rules": ["日付だけで分けた。13日の金曜日は3年で数日しかないので、たまたまの幅が大きい"],
        "faq": [("ゾロ目の日に1-1-1は?", "同じ艇が2回来ることはないので、ゾロ目の出目は3連単にはない。2連複のゾロ目もない。ゾロ目の日に買えるのは、気持ちだけ")],
        "use": ["カレンダーで予想は変えなくていい。……でも記念日に推しの艇番を買うのは、とても良い"],
        "mikata": "カレンダーは関係なかった。でも『今日はゾロ目の日だから』って理由で現地に行くのは、最高の理由だと思う",
        "gen": "11月11日は1-1……は買えねえのか。じゃあ1-2-3でいい。ゾロ目気分で買うのが大事なんだよ",
        "challenge": "次のゾロ目の日(11月11日)に、自分の『記念日の出目』を決めて1点だけ買ってみよう",
        "numbers": {"days_zoro": nd, "days_fri13": nf, "upset_zoro": uz, "upset_fri13": uf, "upset_all": ua},
    }


def t_payday(ent, r):
    """給料日と週末、オッズはゆがむ?"""
    x = r.copy()
    dd = pd.to_datetime(x["date"])
    pay = dd.dt.day.isin([24, 25, 26]); end = dd.dt.day.isin([1, 2, 3, 4, 5]) | (dd.dt.day >= 28)
    wkend = dd.dt.dayofweek >= 5
    mp, me, mw, mwd = measure(x, pay), measure(x, dd.dt.day.between(15, 20)), measure(x, wkend), measure(x, ~wkend)
    ms = [("給料日あたり(24〜26日)", mp, verdicts(mp)), ("月の半ば(15〜20日)", me, verdicts(me)), ("土日", mw, verdicts(mw)), ("平日", mwd, verdicts(mwd))]
    rw, rd = mw.get("market_ratio"), mwd.get("market_ratio")
    return {
        "id": "payday", "title": "給料日と週末、オッズはゆがむ?", "belief": "給料日や週末は、ふだん買わない人が本命を買う。だから本命の配当がしぶくなる",
        "lead": f"1号艇の『オッズの見立て』と実際の差は、給料日あたりで{ratio_words(mp.get('market_ratio'))}、月の半ばで{ratio_words(me.get('market_ratio'))}、"
                f"土日で{ratio_words(rw)}、平日で{ratio_words(rd)}。",
        "conclusion": (["ふだんと同じ。オッズはしっかりしている", "給料日も週末も、1号艇のオッズの見立てはいつもとほとんど同じ。売れる量が増えても、ゆがみは小さい"]
                       if all(v.get("edge") in (0, None) for _, _, v in ms) else ["日によって少し違う", "くわしくは下の表"]),
        "tables": [], "measures": ms,
        "rules": ["オッズは締切の少し前に集めたもの(集めたレースの分だけ)。『見立て』は、ひかれる分(控除)を除いて逆算した1号艇の勝つ見込み",
                  "1号艇はどの日でも見立てより少し多く来る(全レースの平均)。その平均とくらべて、ずれが大きいかを見る"],
        "faq": [("週末は本命が売れすぎる?", "週末も平日も、本命のずれ方はほぼ同じ。ネット投票が中心なので、ふだんから買っている人の割合が大きいのかも")],
        "use": ["日付や曜日でオッズの読み方は変えなくていい"],
        "mikata": "オッズは思ったよりしっかりしていた。みんなの予想の集まりって、すごいんだね",
        "gen": "給料日に競艇場に行くのは、俺の数少ない楽しみなんだよ。オッズなんて関係ねえ",
        "challenge": "給料日の夜、ナイターで1レースだけ『ごほうびの1点』を決めてみよう",
        "numbers": {"ratio_pay": mp.get("market_ratio"), "ratio_mid": me.get("market_ratio"), "ratio_weekend": rw, "ratio_weekday": rd},
    }


THEORIES = {t["id"]: t for t in []}
BUILDERS = {"bangumi": t_bangumi, "kikaku": t_kikaku, "streak": t_streak, "a1in": t_a1in, "maezuke": t_maezuke, "tenji": t_tenji, "flying": t_flying, "combo": t_combo,
            "rest": t_rest, "travel": t_travel, "weight": t_weight, "dayno": t_dayno, "twice": t_twice, "tilt": t_tilt,
            "moon": t_moon, "manshu": t_manshu, "lucky7": t_lucky7,
            "rain": t_rain, "age": t_age, "zorome": t_zorome, "payday": t_payday}


# ---------------------------------------------------------------- 記事
def pc(v):
    return "-" if v is None or v != v else f"{v:.0%}"


def table_html(title, rows, label="1号艇の1着率"):
    if not rows:
        return ""
    has_ratio = any("ratio" in x for x in rows)
    head = f"<tr><th>場・レース名</th><th>R</th><th>レース数</th><th>{e(label)}</th>" + ("<th>オッズとの比</th>" if has_ratio else "") + "</tr>"
    body = "".join(f"<tr><td>{e(str(x['venue']))}</td><td>{x['rno']}</td><td>{x['n']:,}</td><td><b>{pc(x['in1'])}</b></td>"
                   + (f"<td>{x['ratio']:.2f}</td>" if has_ratio and x.get('ratio') else ("<td>-</td>" if has_ratio else "")) + "</tr>" for x in rows)
    return f'<h4>{e(title)}</h4><table class="scn lab cells">{head}{body}</table>'


def per100(v):
    return "-" if v is None or v != v else f"{round(v * 100)}回"


def mark(v):
    """表に入れる短い判定。"""
    if v.get("baseline"):
        return "基準", "○ みんな知ってる" if v.get("edge") == 0 else "-", "基準"
    ex = "○ 本当" if v.get("real") else "– ふだん並み"
    e_ = v.get("edge")
    kn = "○ みんな知ってる" if e_ == 0 and "追試中" not in v.get("known", "") else ("！ 見立て超え(追試中)" if "追試中" in v.get("known", "") else
                                                                       ("！ 見立て超え" if e_ == 1 else ("ひかえめ" if e_ == -1 else "- 集計中")))
    st = v.get("stable")
    sb = "-" if st is None else ("○ 同じ" if st.startswith("前の2年") else "年で変わる")
    return ex, kn, sb


def measures_html(ms, subject="1号艇", verb="勝つ", no_market=False, compare="全体"):
    ref = next((m["market_ref"] for _, m, _ in ms if "market_ref" in m), None)
    ref_w = f"(全レースの平均で {round((ref - 1) * 100):+d}%)" if ref is not None else ""
    rows = ""
    for name, m, v in ms:
        ex, kn, sb = mark(v)
        r = m.get("market_ratio")
        if r is None or r != r:
            rw, rs = "-", ""
        else:  # オッズの見立て(100レースで何回勝つと見ていたか)と実際
            rw = f"見立て{per100(m['in1'] / r)} → 実際{per100(m['in1'])}"
            rs = f"見立てより{round((r - 1) * 100):+d}%"
        rows += (f"<tr><th>{e(name)}<small>{m['n']:,}レース</small></th><td><b>{per100(m['in1'])}</b><small>{e(fun_rate(m['in1']))}。{e(ex)}</small></td>"
                 f"<td><b>{e(rw)}</b><small>{e(rs)}。{e(kn)}</small></td><td>{e(sb)}</td></tr>")
    if no_market:
        rows = ""
        for name, m, v in ms:
            ex, kn, sb = mark(v)
            rows += (f"<tr><th>{e(name)}<small>{m['n']:,}走</small></th><td><b>{per100(m['in1'])}</b><small>{e(fun_rate(m['in1']))}。くらべる相手は{per100(m['in1_ref'])}</small></td>"
                     f"<td>{e(ex)}</td><td>{e(sb)}</td></tr>")
        return ('<div class="tw"><table class="scn lab"><tr><th>条件</th><th>100走で</th><th>①本当?</th><th>③来年も?</th></tr>' + rows + "</table></div>"
                f"<p class=\"legend\">「100走で」は、100回走ったら{e(subject)}が{e(verb)}回数。くらべる相手は、{e(compare)}。③は前の2年と最近の1年で同じ向きか。</p>")
    legend = (f"<p class=\"legend\">①は「100レースで{e(subject)}が{e(verb)}回数」(ふだんは{per100(ms[0][1]['in1_ref'])}、{fun_rate(ms[0][1]['in1_ref'])})。"
              f"②は「オッズがみんなの予想として見立てていた回数」と実際の回数。1号艇はどのレースでも見立てより少し多く勝つ{e(ref_w)}ので、それと同じなら、みんな知っている=配当は堅め。③は前の2年と最近の1年で同じ向きか。</p>")
    return ('<div class="tw"><table class="scn lab"><tr><th>条件</th><th>①本当?</th><th>②知られてる?</th><th>③来年も?</th></tr>'
            + rows + "</table></div>" + legend)


def page(t: dict, asof: str) -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    con = conclusion(t)
    tables = "".join(table_html(*tb) for tb in t["tables"])
    use = "".join(f"<li>{e(x)}</li>" for x in t["use"])
    rules = ('<section class="side"><h3>まず、ルールをざっくり</h3><ol>' + "".join(f"<li>{e(x)}</li>" for x in t["rules"]) + "</ol></section>") if t.get("rules") else ""
    faq = ('<section><span class="label">よくある疑問</span>' + "".join(f'<h4>Q. {e(q)}</h4><p class="faq">{e(a)}</p>' for q, a in t["faq"]) + "</section>") if t.get("faq") else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex"><title>ミカタ検証ラボ {e(t['title'])}</title>{mag.FONTS}<style>{mag.CSS}
.mag section{{min-width:0}} .tw{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.lab{{width:100%;margin:0;min-width:0}} .legend{{font-size:12.5px;color:var(--mute);line-height:1.6;margin:8px 0 0}} .lab td,.lab th{{text-align:left;white-space:normal}} .lab td b{{font:700 17px var(--num);color:var(--red)}} .lab small{{display:block;font-size:11px;color:var(--mute);white-space:normal}}
.lab.cells{{min-width:0}} .lab.cells td,.lab.cells th{{white-space:nowrap}}
.belief{{margin:0;font:700 clamp(16px,4.2vw,20px)/1.7 var(--serif);border-left:6px solid var(--yellow);padding:4px 0 4px 14px;background:rgba(255,225,0,.18);flex:1 1 auto}}
.gen-say{{display:flex;gap:12px;align-items:flex-start}} .gen-say svg{{flex:0 0 64px}} .who{{margin:8px 0 0;font-size:12.5px;color:var(--mute);line-height:1.6}}
.ft-quote.gen p{{border-color:#0b5fb4}} .ft-quote.gen small{{color:#0b5fb4}}
.gauge{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:8px}} .gauge div{{background:var(--card);border:2px solid var(--rule);padding:10px 12px}}
.gauge b{{display:block;font:400 15px var(--head);color:var(--red)}} .gauge span{{font-size:13px}}
.td-box{{display:flex;gap:12px;align-items:flex-start;background:var(--yellow);padding:14px 16px;border:3px solid var(--ink)}} .td-box p{{margin:0;font:700 15.5px/1.7 var(--serif)}} .td-box svg{{flex:0 0 48px;width:48px;height:48px}}
.st-box{{background:var(--red);color:#fff;padding:14px 16px}} .st-box b{{display:block;font:400 clamp(20px,5.5vw,28px)/1.3 var(--head)}} .st-box p{{margin:6px 0 0;font-size:14px;line-height:1.6}}
.mag h4{{margin:14px 0 6px;font:400 17px var(--head)}} .side ul,.side ol{{font-size:14.5px}} .faq{{margin:0 0 10px;font-size:14.5px;line-height:1.8}}
</style></head><body>
<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ検証ラボ<small>「◯◯理論」を同じ物差しで試す</small></div><div class="issue"><b>LAB</b><br>{e(today)}</div></div>
<p class="cv-kicker">今週の理論</p><h1 class="cv-h">{e(t['title'])}</h1>
<p class="cv-deck">{e(t['lead'])}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ(カモメの記者)/ 説の持ち込み ゲンさん<br>公式の成績データ 2023-10〜{e(asof)} を独自に集計</span></div></div></header>
<main class="mag">
<section class="opener"><span class="label">ゲンさんの説</span><div class="gen-say">{gull_svg(64, bg="#ffffff", cls="gs", who="gen")}<p class="belief">{e(t['belief'])}</p></div>
<p class="who">ゲンさん=験かつぎ歴40年の大先輩。ストップウォッチ片手に展示を見る目は確か。その説、ミカタがデータで確かめます</p></section>
<section class="stamp"><span class="label">ミカタの結論</span><div class="st-box"><b>{e(con[0])}</b><p>{e(con[1])}</p></div></section>
<section><span class="label">3つの物差し</span><div class="gauge"><div><b>① 本当にある?</b><span>「ふだん」と比べて差があるか。同じ数のレースをサイコロで決めても出るくらいの差なら「ふだん並み」</span></div>
<div><b>② みんな知ってる?</b><span>{'この回は選手ごとの話なので、オッズでは測っていない' if t.get('no_market') else 'オッズは「みんなの予想」。1号艇はどのレースでもオッズの見立てより少し多く来るので、その「全レースの平均」と同じなら、知られている=配当は安い'}</span></div>
<div><b>③ 来年も同じ?</b><span>前の2年と最近の1年で、同じ向きに出るか。出なければ一時のもの</span></div></div></section>
{rules}<section><span class="label">結果</span>{measures_html(t['measures'], t.get('subject', '1号艇'), t.get('verb', '勝つ'), t.get('no_market', False), t.get('compare', '全体'))}{tables}</section>{faq}
<section class="side"><h3>予想に使うなら</h3><ul>{use}</ul></section>
<section class="todai"><span class="label">今日のお題</span><div class="td-box">{gull_svg(48, bg="#fff", cls="td")}<p>{e(t.get('challenge', '次に行く場で、この説が本当か自分の目で確かめてみよう'))}</p></div></section>
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>{e(t['mikata'])}</p></blockquote>
<blockquote class="ft-quote gen">{gull_svg(64, bg="#ffffff", cls="q", who="gen")}<p><small>ゲンさんの返し</small>{e(t.get('gen', 'ふーん。で、今日はどこが荒れるんだ?'))}</p></blockquote>
<section class="method"><h3>データについて</h3><p>公式の成績データ(番組表・競走成績)と、締切時のオッズ(集めたレース分)を自分たちで集計。「オッズの見立て」は、締切時のオッズから、ひかれる分(控除)を除いて逆算した1号艇の勝つ見込み。
「ふだん並み」かどうかは、同じ数のレースを何度も引き直したときに出るブレの幅(統計でいう90%区間)で判定。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ検証ラボ ・ 毎週1本。競艇をいろんな角度から。買い目は売りません。</span></footer></main></body></html>"""


def note_text(t: dict) -> str:
    con = conclusion(t)
    out = [f"【タイトル案】", f"1. {t['title']}|{t['belief'][:24]}…をデータで検証", f"2. 検証ラボ:{t['title']} 3つの物差しで確かめた", "",
           "■ゲンさんの説(験かつぎ歴40年の大先輩)", f"「{t['belief']}」", "", f"■ミカタの結論:{con[0]}", con[1], "", "■くわしく", t["lead"], "", "■3つの物差し",
           "①本当にある?(ふだんと比べて、はっきり差があるか) ②みんな知ってる?(オッズの見立てどおりなら知られている=配当は安い) ③来年も同じ?(前の2年と最近の1年で同じ向きか)", ""]
    for name, m, v in t["measures"]:
        ex, kn, sb = mark(v)
        r = m.get("market_ratio")
        odds = (f"オッズの見立ては{per100(m['in1'] / r)}、実際は{per100(m['in1'])}({round((r - 1) * 100):+d}%)" if r and r == r else "オッズのデータは集計中")
        subj, verb = t.get("subject", "1号艇"), t.get("verb", "勝つ")
        out.append(f"・{name}({m['n']:,}走): 100走で{subj}が{verb}のは{per100(m['in1'])}({fun_rate(m['in1'])}。くらべる相手は{per100(m['in1_ref'])})→ {ex}。"
                   + ("" if t.get("no_market") else f"{odds} → {kn}。") + f"来年も同じか: {sb}")
    for h, rows, *_lbl in t["tables"]:
        out += ["", f"■{h}"] + [f"・{x['venue']}{x['rno']}{'R' if x['rno'] != '' else ''} {pc(x['in1'])}({x['n']:,}レース)" for x in rows]
    if t.get("rules"):
        out += ["", "■まず、ルールをざっくり"] + [f"{i + 1}. {x}" for i, x in enumerate(t["rules"])]
    if t.get("faq"):
        out += ["", "■よくある疑問"] + [f"Q. {q}\n{a}" for q, a in t["faq"]]
    out += ["", "■予想に使うなら"] + [f"・{x}" for x in t["use"]] + ["", f"■今日のお題", t.get("challenge", ""), "", f"ミカタのひと言:「{t['mikata']}」", "",
            "■データについて", "公式の成績データと締切時のオッズを自分たちで集計。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"]
    return "\n".join(out)


def x_text(t: dict) -> str:
    m = t["measures"][0][1]
    con = conclusion(t)
    body = (f"【検証ラボ】{t['title']}\n\nゲンさん「{t['belief']}」\n\nミカタ「結論:{con[0]}。{t['lead'].split('。')[0]}」\n\n"
            f"ゲンさん「{t.get('gen', '')}」\n\nみんなはこの説、信じてた?")
    if xlen(body) > 280:  # 長いときは、数字の文を落として掛け合いだけ残す
        body = f"【検証ラボ】{t['title']}\n\nゲンさん「{t['belief']}」\n\nミカタ「結論:{con[0]}」\n\nゲンさん「{t.get('gen', '')}」\n\nみんなは信じてた?"
    if xlen(body) > 280:
        body = f"【検証ラボ】{t['title']}\n\nゲンさん「{t['belief']}」\n\nミカタ「結論:{con[0]}」\n\nみんなは信じてた?"
    return f"--- 投稿1({xlen(body)}/280) ---\n{body}\n\n画像: 紙面の上部のスクリーンショットか、表の部分"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theory", default=None)
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "out/lab"))
    a = ap.parse_args()
    if a.list:
        for k in BUILDERS:
            print(k, "済" if (REP / f"{k}.json").exists() else "")
        return
    if a.theory == "all":
        tids = list(BUILDERS)
    elif a.theory:
        tids = a.theory.split(",")
    else:
        tids = [next((k for k in BUILDERS if not (REP / f"{k}.json").exists()), None)] if a.next else []
    tids = [t_ for t_ in tids if t_]
    if not tids:
        print("作る理論がありません"); return
    ent, r = base()
    for tid in tids:
        try:
            build_one(tid, ent, r, a.out)
        except Exception as ex:  # noqa: BLE001  1本の失敗でほかを止めない
            import traceback
            print("失敗:", tid, ex); traceback.print_exc()


def build_one(tid, ent, r, outdir):
    t = BUILDERS[tid](ent, r)
    asof = str(r["date"].max())
    out = pathlib.Path(outdir); out.mkdir(parents=True, exist_ok=True)
    (out / f"lab_{tid}.html").write_text(page(t, asof), encoding="utf-8")
    (out / f"lab_{tid}.txt").write_text(note_text(t), encoding="utf-8")
    (out / f"lab_{tid}_x.txt").write_text(x_text(t), encoding="utf-8")
    REP.mkdir(parents=True, exist_ok=True)
    t["asof"], t["made"] = asof, dt.datetime.now(JST).strftime("%Y-%m-%d")
    (REP / f"{tid}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("wrote", out / f"lab_{tid}.html")
    print(t["lead"])


if __name__ == "__main__":
    main()
