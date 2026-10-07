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
from kyotei.publish import load_private, private_exists, save_private  # noqa: E402
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
    # 3ポイント以上の差。もともと少ないこと(20%未満)は、2割以上の増減でもよい(10回→13回など)
    big = abs(d) >= 0.03 or (min(m["in1"], m["in1_ref"]) < 0.2 and m["in1_ref"] > 0 and abs(d) / m["in1_ref"] >= 0.2)
    real = big and not (m["in1_ci"][0] <= m["in1_ref"] <= m["in1_ci"][1])
    out = {"exists": ("本当にある(ふだんより" + ("多い" if d > 0 else "少ない") + ")") if real else "ふだんと同じ(差は出なかった)", "real": real}
    if "market_ratio" in m:
        lo, hi = m["market_ci"]
        ref = m.get("market_ref", 1.0)
        if lo <= ref <= hi:
            out["known"], out["edge"] = "人気どおり(みんな知っている)", 0
        elif lo > ref and m.get("n_odds", 0) < 500:  # レース数が少ないうちは「追試中」にとどめる(8つ調べれば1つは偶然で出る)
            out["known"], out["edge"] = "人気以上に来ている。ただ、まだレース数が少ない(追試中)", 0
        elif lo > ref:
            out["known"], out["edge"] = ("人気以上に来る(ただし差は小さめ)" if lo < 1.3 else "人気以上に来る"), 1
        else:
            out["known"], out["edge"] = "人気のわりにひかえめ", -1
    else:
        out["known"], out["edge"] = "人気とのくらべは、データを集め中", None
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
        return "本当。しかも人気以上", "人気から考えるより多く来ている。差は小さめだが、追いかける価値あり(毎週更新)"
    if all(e == 0 for e in edge) and edge:
        return "本当。ただし人気どおり", "差はしっかりある。みんな知っているぶん配当は安め。だから1着は決め打ちして、2着・3着の並びで腕を見せる回"
    return "本当", "差はある。人気とのくらべは、データを集めて確かめる"


def odds_words(m):
    """オッズから見込める回数と実際(100レースあたり)。いつものずれ(全体の平均)で直した見込み。"""
    r_ = m.get("market_ratio")
    if not r_ or r_ != r_:
        return "人気とのくらべはデータを集め中"
    exp_ = m["in1"] / r_ * (m.get("market_ref") or 1.0)
    return f"人気から考えると{_rate(exp_)}のところ、実際は{_rate(m['in1'])}"


def odds_pair(m):
    """人気から考えられる確率→実際(「59%→68%」)。短く並べたいとき用。"""
    r_ = m.get("market_ratio")
    if not r_ or r_ != r_:
        return "(データを集め中)"
    return f"{_rate(m['in1'] / r_ * (m.get('market_ref') or 1.0))}→{_rate(m['in1'])}"


def ratio_words(r, ref=None):
    """オッズとの比を言葉で: 1.04 → 「オッズの見立てより +4%」。ref(全レースの比)があれば並べて書く。"""
    if r is None or r != r:
        return "-"
    d = round((r - 1) * 100)
    w = "人気どおり" if d == 0 else f"人気から考えるより{abs(d)}%{'多い' if d > 0 else '少ない'}"
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
    # 最大値と最小値の落差を倍率で表現
    gap_phrase = _ratio_phrase(g['in1'].max(), g['in1'].min())
    return {
        "id": "bangumi", "title": "番組屋の癖は本物か", "belief": "「この場のこのレースはインが堅い」は番組を組む人の癖で、毎年同じ",
        "x1": f"『インが堅い場×レース番号』は毎年同じ。前の2年で堅かった8枠は、最近の1年も1号艇の1着{_rate(mh['in1'])}(全体{_rate(mh['in1_ref'])})。",
        "lead": f"出走表を前に『この場のこのレース番号はインが堅い』。それって、本当なのか?　"
                f"データで調べた。\n\n"
                f"場×レース番号ごとに見ると、1号艇が勝つ確率は、いちばん堅いところで{_rate(g['in1'].max())}。"
                f"いちばん荒れるところは{_rate(g['in1'].min())}。{gap_phrase}。"
                f"\n\nその『堅さ』は、年を変えても続く。前の2年で堅かった場所は、最近の1年でも{sim_words(corr)}。"
                f"つまり、番組屋さんが『ここは1号艇に強い選手を置く』という習性は、昨年も今年も同じ。"
                f"それが、出走表の読み方を変える。",
        "tables": [("1号艇が堅い枠(上位8)", rows), ("1号艇が荒れる枠(下位8)", rows2)],
        "measures": [("前の2年でインが強かった『場とレース番号』8つの、最近の1年", mh, verdicts(mh)), ("前の2年で荒れた『場とレース番号』8つの、最近の1年", ms, verdicts(ms))],
        "use": ["出走表を見る前に、その場のその番号の「ふだんの堅さ」を頭に入れる。堅い枠で1号艇が弱そうなら、それ自体がニュース",
                "ただし堅い枠は人気も集まる(配当は安め)。1号艇を軸にするかどうかは、配当との相談(ここは読者の判断)",
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
        "lead": f"1号艇が勝つ確率は、特別選抜戦なら{_rate(dict((x[0], x[1]['in1']) for x in measures).get('特別選抜戦', 0))}({fun_rate(dict((x[0], x[1]['in1']) for x in measures).get('特別選抜戦', 0))})、"
                f"ドリーム戦で{_rate(dict((x[0], x[1]['in1']) for x in measures).get('ドリーム戦', 0))}、一般戦なら{_rate(dict((x[0], x[1]['in1']) for x in measures).get('一般戦', 0))}({fun_rate(dict((x[0], x[1]['in1']) for x in measures).get('一般戦', 0))})。"
                f"堅いのは本当。ただし、どれも人気どおりで、みんな知っている。"
                f"目立つのは{best[0]}({odds_words(best[1])}。{best[1]['n_odds']}レース分)。レース数がまだ少ないので追試中。",
        "tables": [],  # 結果の表と同じ中身なので出さない
        "measures": measures,
        "use": ["企画レースは「インが堅い」より「堅いことが知られている」レース。1号艇を買うなら配当は安い、を前提に考える",
                "堅いレースこそ、2着・3着の並びで差がつく。差し型・まくり差し型の選手が2〜3号艇にいるかを見る",
                "人気よりずっと来る企画レースが見つかったら追試する(ミカタは毎週ここを更新する)"],
        "mikata": "『堅い』と『おいしい』は別もの。堅いレースは、2着3着で遊ぶのがコツかも",
        "gen": "知ってたよ。でもな、堅いレースの2着探しがいちばんおもしろいんだ。そこが腕の見せどころ",
        "challenge": "企画レースを1つ選んで、1号艇は「来るもの」と決めてしまい、2着・3着だけを当てにいく。差し屋・まくり差しの人が2〜3号艇にいるかが勝負",
        "numbers": {},
    }


def t_streak(ent, r):
    """イン逃げが続いたあとは荒れる?(ギャンブラーの錯覚)。実際は『その日の水面』で続きやすい。"""
    r2 = r.sort_values(["date", "jcd", "rno"]).copy()
    gk = r2.groupby(["date", "jcd"])["c1"]
    prev, prev2, prev3 = gk.shift(1), gk.shift(2), gk.shift(3)
    m3 = ((prev == 1) & (prev2 == 1) & (prev3 == 1)).fillna(False)
    m0 = ((prev == 0) & (prev2 == 0)).fillna(False)
    a, b = measure(r2, m3), measure(r2, m0)
    a["ref_label"] = b["ref_label"] = "全レース"
    # 何で説明できるか: 場と季節 → +レース番号(番組) → +1号艇の級 → +風と波 を順にそろえて、差がどこまで縮むか
    r2["mon"] = pd.to_datetime(r2["date"]).dt.month
    r2["cls1"] = r2["race_id"].map(ent[ent["lane"] == 1].drop_duplicates("race_id").set_index("race_id")["racer_class"])
    r2["wb"], r2["vb"] = pd.cut(r2["wind"], [-1, 2, 4, 99]), pd.cut(r2["wave"], [-1, 2, 5, 99])
    steps = [("場と季節", ["jcd", "mon"]), ("+ レース番号(番組)", ["jcd", "mon", "rno"]), ("+ 1号艇の級", ["jcd", "mon", "rno", "cls1"]),
             ("+ 風と波", ["jcd", "mon", "rno", "cls1", "wb", "vb"])]
    dec = []
    for nm, keys in steps:
        dev = r2["c1"] - r2.groupby(keys, observed=True)["c1"].transform("mean")
        dec.append((nm, float(dev[m3].mean()) * 100, float(dev[m0].mean()) * 100))
    adj3, adj0 = dec[0][1], dec[0][2]
    res3, res0 = dec[-1][1], dec[-1][2]
    w3, w0, wall = float(r2.loc[m3, "wind"].mean()), float(r2.loc[m0, "wind"].mean()), float(r2["wind"].mean())
    sg = lambda v: f"{abs(v):.0f}ポイント{'高い' if v > 0 else '低い'}" if abs(v) >= 0.5 else "ほぼ同じ"  # noqa: E731
    dtbl = [["そろえたもの", "3連勝のあと", "2連敗のあと"], *[[nm, sg(x3), sg(x0)] for nm, x3, x0 in dec]]
    va = verdicts(a)
    return {
        "id": "streak", "title": "イン逃げが続いたあとは荒れるのか", "belief": "同じ場で1号艇が3連続で逃げたら、次は荒れる(そろそろ来る)",
        "lead": f"同じ日・同じ場で1号艇が3つ続けて勝ったあとのレースは{a['n']:,}レース。その次に1号艇が勝つのは{_rate(a['in1'])}。"
                f"全レースの{_rate(a['in1_ref'])}より多い。荒れるどころか、続きやすい。逆に2つ続けて負けたあとは{_rate(b['in1'])}。"
                f"でも、レース番号(番組の組み方)・1号艇の級・風と波を順にそろえると、3連勝のあとの差は{abs(res3):.0f}ポイントほどまで縮む。『流れ』の正体は、おもに番組の組み方。それに、その日の水面が少し。",
        "conclusion": ["ウソ。荒れるどころか続きやすい", f"1号艇が3連勝した日は、次も{_rate(a['in1'])}の確率で勝つ。理由の多くは、1号艇に強い選手を置く番組が続く時間帯。それに、静かな水面が少し。"
                       + ("人気どおり(みんな知っている)" if va.get("edge") == 0 else "")],
        "subject": "1号艇",
        "tables": [("『流れ』の正体さがし(全レースとくらべた差(ポイント)。そろえるほど縮む)", dtbl[1:], dtbl[0])],
        "measures": [("1号艇が3連勝したあと", a, va), ("1号艇が2連敗したあと", b, verdicts(b))],
        "rules": ["同じ日・同じ場の、前のレースの結果で分けた(1Rから順に)",
                  "『そろえる』は、同じ場・同じ月・同じレース番号…の平均からのずれでくらべること。そろえて差が消えれば、その分はそれが理由",
                  f"風の平均は、3連勝のあと{w3:.1f}m、2連敗のあと{w0:.1f}m、全レース{wall:.1f}m。風が強い日はインが弱い(検証ラボ『風が強い日は、インが弱い?』)"],
        "faq": [("ルーレットの『赤が続いたら次は黒』と同じ?", "ルーレットは毎回まっさら。でも競艇は、同じ日の番組の組み方や、水面・風が続く。だから『流れ』は、ある意味で本当にある"),
                ("番組の組み方って?", "場によっては、午前や特定のレース番号に、1号艇に強い選手を置く番組を続けて組む。だからインの勝ちが続く時間帯がある(検証ラボ『番組屋の癖は本物か』)"),
                ("連敗のあとは?", f"2連敗のあとは、1号艇が勝つのは{_rate(b['in1'])}。荒れた日は、荒れたまま")],
        "use": ["インが続いているのは、たいてい番組のせい。次のレースも、番組(1号艇の級)と風を見れば、続くかどうか見当がつく",
                "荒れている日は、風と波を直前情報で確かめる。それが荒れの正体のことが多い"],
        "mikata": "『そろそろ荒れる』はギャンブラーの錯覚。でも『今日はインの日』には、ちゃんと理由があったよ",
        "gen": "3つ続いたら次は荒れる、ってずっと言ってきたんだがなあ……。まあ、今日はインの日って言い方なら、明日から使えるな",
        "challenge": "次に現地に行ったら、1Rから順に1号艇が勝ったかどうかをメモ。3連勝したら『今日はインの日』と宣言して、次のレースを見守ろう",
        "numbers": {"adj3": adj3, "adj0": adj0, "wind3": w3, "wind0": w0, "decompose": dec},
    }


def t_a1in(ent, r):
    """一般戦で1号艇にA1が置かれたレースは堅いか。B1でもスタートが速く1コースで勝てる人は?"""
    e_ = ent.sort_values(["racer_id", "date", "rno"])
    st = e_["st"].where((e_["st"] >= 0) & (e_["st"] < 0.6) & (e_["st_flag"] != "F"))
    g = e_["racer_id"]
    st_prev = st.groupby(g).transform(lambda q: q.shift(1).rolling(60, min_periods=20).mean())
    w1 = (e_["finish"] == 1).astype(float).where(e_["course"] == 1)
    ng_prev = w1.groupby(g).transform(lambda q: q.shift(1).rolling(400, min_periods=8).mean())   # 1コースに入ったときの勝率(それまでの成績)
    l1 = pd.DataFrame({"race_id": e_["race_id"], "lane": e_["lane"], "cls": e_["racer_class"], "st": st_prev, "ng": ng_prev})
    l1 = l1[l1["lane"] == 1].drop_duplicates("race_id").set_index("race_id")
    r2 = r[r["race_title"].isin(["一般戦", "一般", "予選"])].copy()
    for c in ("cls", "st", "ng"):
        r2[c] = r2["race_id"].map(l1[c])
    b1 = r2["cls"] == "B1"
    good = b1 & (r2["st"] <= 0.15) & (r2["ng"] >= 0.55)
    a, a2, b, bg = (measure(r2, r2["cls"] == "A1"), measure(r2, r2["cls"] == "A2"), measure(r2, b1 & ~good), measure(r2, good, ref=b1 & ~good))
    bg["ref_label"] = "ほかのB1"
    vbg = verdicts(bg)
    odds_w = {1: "しかも人気以上に勝っている", 0: ("しかも人気以上に勝っている(まだレース数が少ないので追試中)" if "追試中" in vbg.get("known", "") else "人気どおり(みんな知っている)"),
              -1: "人気のわりにひかえめ"}.get(vbg.get("edge"), "")
    # 「特定の1人の話」に読まれないように、タイプ(条件)として書き、レース数を添える
    b1_n, good_n = int(b1.sum()), int(good.sum())
    a1_frac = _frac(a["in1"])
    a1_frac = f"({a1_frac})" if a1_frac else ""
    return {
        "id": "a1in", "title": "1号艇がA1なら堅いのか", "belief": "予選・一般戦で1号艇にA1級が入ったレースは堅い",
        "lead": f"出走表でまず目に入るのが『級別』。予選・一般戦で1号艇がA1なら、勝つ確率は{_pct(a['in1'])}{a1_frac}。"
                f"A2なら{_pct(a2['in1'])}、B1だと{_pct(b['in1'])}まで下がる。"
                f"\n\nここまでは「級別って大事だね」で終わる話。面白いのはここから。"
                f"\n\nB1を2つに分けてみる。『平均スタート0.15秒以下』で『1コースに入ると2回に1回以上勝ってきた』B1と、それ以外のB1。"
                f"前のタイプは少数派で、B1の1号艇のうち{_pct(good_n / b1_n) if b1_n else '-'}({round(b1_n / good_n) if good_n else '-'}レースに1レースほど)。"
                f"でも、こういうB1が1号艇のときの勝率は{_pct(bg['in1'])}。ほかのB1の{_pct(b['in1'])}から、{_vs_phrase(bg['in1'], a2['in1'], 'A2')}上がる。"
                f"\n\nつまり見るべきなのは級別じゃなく、『スタート』と『1コースの成績』。この2つがそろっているB1は、A2として扱っていい。{odds_w}。",
        "conclusion": ["本当。でもB1にも『隠れA2』がいる", f"A1の1号艇の勝率は{_pct(a['in1'])}。堅いが、人気どおり。スタートが速く1コースで勝ってきたB1の1号艇は{_pct(bg['in1'])}で、ほかのB1({_pct(b['in1'])})より級別ひとつ分強い。ミカタ新聞の選手カード、スタートと逃げの欄を見ながら出走表を読むと、『このB1は違う』が見えてくる。{odds_w}。"],
        "subject": "1号艇",
        "tables": [],
        "measures": [("1号艇がA1", a, verdicts(a)), ("1号艇がA2", a2, verdicts(a2)), ("1号艇がB1(下のB1をのぞく)", b, verdicts(b)),
                     ("B1でも、スタートが速く1コースで勝ってきた人", bg, vbg)],
        "rules": ["級別は半年ごとの成績で決まる(A1がいちばん上、A2・B1・B2)。出走表でいちばん目立つ情報",
                  "『スタートが速い』は、その日より前の60走の平均ST(フライングをのぞく)。『1コースで勝ってきた』は、その日より前に1コースに入ったときの勝率(8回以上)"],
        "faq": [("A1の1号艇は買い?", "堅いのは本当。でも、みんな知っているので配当も堅い。1着は決め打ちして、2着・3着で腕を見せる"),
                ("隠れA2はどうやって見つける?", "ミカタ新聞の選手カードの『スタート』と『逃げ』の型を見る。B1でも、この2つがそろっていれば1号艇で強い")],
        "use": ["級別は出走表でいちばん目立つ情報なので、いちばん人気に出やすい。級別『以外』の材料(ST・逃げの実績・今節の足)で差をつける",
                f"B1の1号艇でも、平均STが速くて1コースの勝率が高いタイプは、勝率{_pct(bg['in1'])}(A2の{_pct(a2['in1'])}とほぼ同じ)"],
        "mikata": "A1かどうかは、みんな見てる。見てないところを見るのが、いろんな角度ってやつ",
        "gen": "A1は見りゃ分かる。俺が見てるのはスタートの構えだ。B1でもピタッと行くやつはいる。ほらな、言ったとおりだろ",
        "challenge": "今日の出走表から、B1の1号艇で「平均STが速い・1コースで勝ってきた」人を1人見つける。A2なみに扱ってみて、結果を友達と答え合わせ",
        "numbers": {"b1_good_n": int(good.sum())},
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
        "lead": f"前づけがあるのは{_rate(share)}のレース。前づけで1コースに入った艇が勝つのは、2・3号艇からなら{_rate(b['in1'])}、4〜6号艇からだと{_rate(c['in1'])}。"
                f"枠なりの1コース({_rate(a['in1'])})より低い。助走が短くなってスタートが平均{st_front - st_nari:.3f}秒遅れるから。"
                f"それでも本人には得({_rate(own_ref)}→{_rate(own)})。ただし押し出された1号艇は{_rate(pushed['win'].mean())}まで下がり、取り合いになれば両方が深くなる。",
        "subject": "1コースの艇",
        "rules": ["コースは艇の番号(枠)で決まっていない。ピットを出てからスタートまでの「待機行動」の間に、各艇が自分で取る(内から1〜6コース)",
                  "枠より内のコースを取ることを「前づけ」と言う(2号艇が1コースへ、6号艇が2コースへ、など)。入られた艇は外へずれる",
                  "内のコースほど助走が短い(スロー勢)。外は長い助走で全速(ダッシュ勢)。前づけで割り込むと、自分も押し出された艇も助走が足りず「深い」スタートになりやすい",
                  "企画レースなど「進入固定」のレースは枠なりで固定。前づけはできない",
                  "待機行動には決まりがあり(内側のブイより内へ入らない、時間の制限など)、違反は減点などの対象。ここは公式のルールを確かめてほしい"],
        "tables": [("前づけが多い場", rows, "前づけがあるレースの割合")],
        "measures": [("枠なりの1号艇(基準)", a, va), ("2・3号艇が前づけで1コース", b, vb), ("4〜6号艇が前づけで1コース", c, vc)],
        "conclusion": ["本人は得。でも、全員はできない", f"前づけした本人の1着は{_rate(own_ref)}→{_rate(own)}。ただし1コースの値打ちは下がり({_rate(a['in1'])}→{_rate(b['in1'])})、押し出された1号艇は{_rate(pushed['win'].mean())}。取り合いになれば両方が深くなる"],
        "faq": [("勝てるなら、全員が前づけすればいい?",
                 f"本人だけ見れば得(1着の確率が、枠なりなら{_rate(own_ref)}、前づけすると{_rate(own)})。でも3つの壁がある。①1コースの値打ちが下がる: 助走が短くなってスタートが平均{st_front - st_nari:.3f}秒遅れ、"
                 f"1着の確率は、枠なりの{_rate(a['in1'])}が{_rate(c['in1'])}(4〜6号艇から)まで落ちる。②押し出された1号艇は{_rate(pushed['win'].mean())}(ふだんの2コースの{_rate(base_c2)}より低い)。相手も譲らなければ取り合いになり、両方が深くなって外のダッシュ勢が得をする。"
                 f"③実際にやる人は少ない。前づけ率30%を超える選手は{n_reg}人(主にベテラン)。多くの選手は枠なりで走るのが暗黙の了解になっている"),
                ("前づけされた1号艇はどうなる?", f"2コースへ押し出されるのが大半で、1着は{_rate(pushed['win'].mean())}。ふだんの2コース({_rate(base_c2)})より低いのは、助走が深くなるから"),
                ("前づけした艇は、人気どおり?", f"2・3号艇が1コースに入ったレース({b.get('n_odds', 0)}レース)では、人気から考えると{per100(b['in1'] / b['market_ratio']) if b.get('market_ratio') else '-'}のところ、実際は{per100(b['in1'])}とかなり多い。"
                 "ただし、集めているオッズは締切の少し前の値。進入が決まったあとの人気の動きは入っていないかもしれない。レース数も少ないので追試中"),
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
        "lead": f"展示タイムが1位の艇が3着以内に入るのは{per100(m1['in1'])}({fun_rate(m1['in1'])})、6位だと{per100(m6['in1'])}。展示はちゃんと効く。"
                f"展示で1・2位になる割合は、同じ選手なら時期を変えてもほぼ同じ顔ぶれ(「展示タイム番長」は本物の型)。"
                f"そして番長が展示上位のときも、ほかの選手と同じだけ本番に効いていた。「展示だけの人」は、時期を変えると入れ替わる。",
        "conclusion": ["番長は本物。展示も、ちゃんと効く", f"展示1位は3着以内{per100(m1['in1'])}、6位は{per100(m6['in1'])}。番長が展示上位のときの上積みも、ほかの選手とほぼ同じ。「展示だけ」の人は時期で入れ替わる"],
        "rules": ["展示航走: レース前に、6艇が本番と同じように走ってみせる。そのときの「1周の一部のタイム」が展示タイム(速いほど足がいい目安)",
                  "展示タイムは体重が軽いほど、チルト(エンジンの角度)を上げるほど速く出やすい。だから「いつも速い人」がいる",
                  "ミカタでは、展示タイムが1・2位になる割合が同じ級別で上位10%の選手に「展示タイム番長」の型を付けている"],
        "tables": [],
        "measures": [("展示タイム1位", m1, v1), ("展示タイム6位", m6, v6), ("展示の順位が、本人のふだんより2つ以上上", up, vu), ("本人のふだんより2つ以上下", dn, vd)],
        "faq": [("展示タイム番長って、展示だけじゃないの?",
                 f"本人のふだんとくらべた3着以内は、番長が展示1・2位のとき{_dw(kt * 100)}、ほかの選手が展示1・2位のとき{_dw(ot * 100)}。ほぼ同じだけ効いている。"
                 f"番長が展示4位以下のときも{_dw(kb * 100)}(ほかの選手は{_dw(ob * 100)})。番長だから特別に崩れる、ということもない。展示の順位は誰にでも同じように効く"),
                ("「この人は展示が良くても意味ない」はある?",
                 "選手ごとに「展示上位のときの上積み」を奇数月と偶数月で比べると、顔ぶれがほとんど入れ替わる。つまり「展示だけの人」は、たまたまそう見えていただけのことが多い"),
                ("なぜいつも展示が速い人がいるの?",
                 f"番長の顔ぶれは体重が軽い選手やチルトを上げる選手が多い(展示上位率と体重の関係は{'はっきりある' if cw <= -0.3 else 'ややある'}、チルトとも{'はっきりある' if ct >= 0.3 else 'ややある'})。"
                 "軽さやチルトはそのまま本番の伸びにもつながるので、展示だけの見かけではない"),
                ("展示で「今日の調子」は測れる?",
                 f"測れる。展示の順位が本人のふだんより2つ以上上の日は、3着以内が{per100(up['in1'])}(ふだん通りの日は{per100(up['in1_ref'])})、2つ以上下の日は{per100(dn['in1'])}。"
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
        "lead": f"フライング{nF:,}回のあとを追いかけた。直後の10走はスタートが平均{st10:.3f}秒遅くなり、3着以内は{per100(a10['in1'])}(本人のフライング前は{per100(a10['in1_ref'])})。"
                f"11〜40走目でも{st40:.3f}秒遅く、3着以内は{per100(a40['in1'])}。41走目あたりでほぼ元に戻る。失格(転覆・落水・エンストなど)のあとは、ほんの少し下がるだけ。",
        "conclusion": ["本当。F後40走はスタート控えめ", f"直後10走はSTが{st10:.3f}秒遅く、3着以内は{_rate_change(a10['in1'], a10['in1_ref'], ref_label='フライング前の')}。40走ほどで戻る。どれだけ控えるかは同じ選手でも毎回ちがう"],
        "rules": ["フライング(F): スタートの合図(大時計の0秒)より前にスタートラインを越えること。その艇は返還(舟券は払い戻し)になり、選手には休み(F休み)などの処分がある",
                  "Fを持っているあいだにもう一度Fを切ると処分が重くなるので、選手はしばらくスタートを慎重にする(「F持ち」)",
                  "公式の成績データでは、転覆・落水・エンストなどは「失格」としてまとめて記録されている。ここでは失格のあととして見ている",
                  "処分の細かい中身(休みの日数など)は時期で変わるので、公式のルールで確かめてほしい"],
        "tables": [],
        "measures": [("F直後の10走", a10, verdicts(a10)), ("F後11〜40走", a40, verdicts(a40)), ("F後41〜120走", a120, verdicts(a120)), ("失格(転覆など)直後の5走", d5, verdicts(d5))],
        "faq": [("スタートはどれくらい遅くなる?",
                 f"本人のフライング前と比べて、スタートは直後10走で{st10:.3f}秒、11〜40走で{st40:.3f}秒、41〜120走で{st120:.3f}秒遅い。0.03秒は、全速(秒速18〜22m)なら約60cm。艇の長さ(約3m)の5分の1ほどで、0.1秒の差がほぼ艇1つぶん"),
                ("慎重になりやすい選手はいる?",
                 "同じ選手の1回目と2回目のフライングで「どれだけ控えたか」を比べると、ほとんど関係がなかった(人ごとの差は時期で入れ替わる)。誰でも同じくらい控える、と考えるのがいい"),
                ("転覆したあとは?",
                 f"失格(転覆・落水・エンストなど){nD:,}回のあと5走は、3着以内は{_rate_change(d5['in1'], d5['in1_ref'], ref_label='ふだんの')}、スタートは{abs(std):.3f}秒{'遅い' if std > 0 else '早い'}。フライングほどは変わらない。多くの選手は翌日も走っている"),
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
    lead = (f"1コースの艇が勝つのは、ふつう{per100(mA['in1_ref'])}。1コースが逃げ下手で3コースにスタートの速いまくり屋がいると{per100(mA['in1'])}、"
            f"逃げ上手なら同じ相手でも{per100(mB['in1'])}。逃げ下手の内に差し屋がいると{per100(mC['in1'])}、差し屋と攻め屋がそろうと{per100(mD['in1'])}。"
            "型の組み合わせは、1コースの強さをはっきり動かす。")
    a3txt = (f"そのとき3コースのまくり屋が勝つのは{per100(a3['in1'])}(3コースの艇のふだんは{per100(a3['in1_ref'])})。"
             + (f"人気から考えると{per100(a3['in1'] / a3['market_ratio'])}。" if a3 and a3.get("market_ratio") else "")) if a3 else ""
    return {
        "id": "combo", "title": "型と型の組み合わせで狙い目はあるか", "belief": "逃げ下手の1号艇の隣に、スタートの速いまくり屋。こういう並びは荒れる",
        "subject": "1コースの艇", "lead": lead,
        "conclusion": ["本当。並びで1コースは大きく変わる",
                       f"逃げ下手×スタートの速いまくり屋で、1コースは100レース中{per100(mA['in1'])}(ふだん{per100(mA['in1_ref'])})。人気のわりにひかえめ。逃げ上手なら{per100(mB['in1'])}で、こちらは人気どおり"],
        "rules": ["型は、前の2年(2023〜2024年)の成績だけで決めた。測ったのは、そのあとの1年(2025年〜)のレース(後出しにならないように)",
                  "逃げ下手/上手: 1コースでの逃げ率が下から30%/上から30%。まくり屋・差し屋: 2コース以遠からまくり・差しで勝つ割合が上から20%。ST速い: 平均STが速い方から30%",
                  "コースは実際の進入で数えた(前づけで変わった場合も、入ったコースの選手で判定)"],
        "tables": [],
        "measures": ms,
        "faq": [("なら、その並びのとき3コースを買えばいい?", a3txt + "この並びは人気にも、ある程度は出ている。①は本当でも、②の「みんな知ってる?」を見てから"),
                ("1号艇が強ければ、まくり屋がいても平気?", f"逃げ上手の1号艇なら、まくり屋(ST速い)が3コースにいても1コースは{per100(mB['in1'])}。ふだんの{per100(mB['in1_ref'])}と比べてどうかが、この表のいちばんの見どころ"),
                ("型はどこで見られる?", "ミカタの選手カードの型(イン逃げ番長・まくり屋・差し職人・スタート職人)と同じ考え方。出走表で、1コースと2〜4コースの型の並びを見る")],
        "use": ["出走表を見たら、まず1コースの逃げの強さ。次に、2コースに差し屋、3・4コースにスタートの速いまくり屋がいるか",
                "逃げ下手 × 攻め屋の並びは、1号艇を頭から外す候補。ただし人気も少し動いているので、2着・3着で工夫する",
                "逃げ上手の1号艇は、攻め屋がいても崩れにくい。そこは素直に"],
        "mikata": "型は1人ずつ見るより、並びで見るともっとおもしろい。1コースと3コースの型を、指でなぞってみて",
        "gen": "昔から『逃げ下手の隣にまくり屋は買い』って言うんだよ。数字にしたら、やっぱりそうだろ?",
        "challenge": "今日の出走表から「逃げ下手の1号艇 × 3コースのまくり屋」のレースを1つ探す。見つけたら、そのレースだけ1号艇を外して予想してみる",
        "numbers": {"n_weak_in": len(weak_in), "n_makuri": len(mk_set), "n_sashi": len(sa_set), "n_fast": len(fast)},
    }


# ---------------------------------------------------------------- からだと暦(2026-10-05 追加)
# 体・疲れ・移動・暦の「よく言われること」を同じ物差しで。選手ごとの話は「本人のふだん」との差で見る
# (強い選手がどこでも良く見える、を避ける)。表の数字は「本人のふだんとの差を、全体の平均(約50%)に足したもの」。
BRANCH_JCD = {"群馬": 1, "埼玉": 2, "東京": 4, "静岡": 6, "愛知": 8, "三重": 9, "福井": 10, "滋賀": 11, "大阪": 12, "兵庫": 13,
              "徳島": 14, "香川": 15, "岡山": 16, "広島": 17, "山口": 18, "福岡": 20, "佐賀": 23, "長崎": 24}
VENUE_XY = {1: (36.405, 139.312), 2: (35.814, 139.656), 3: (35.683, 139.870), 4: (35.579, 139.741), 5: (35.624, 139.591),
            6: (34.711, 137.593), 7: (34.827, 137.235), 8: (34.878, 136.837), 9: (34.698, 136.521), 10: (36.230, 136.146),
            11: (35.021, 135.886), 12: (34.609, 135.479), 13: (34.723, 135.433), 14: (34.185, 134.610), 15: (34.296, 133.790),
            16: (34.465, 133.814), 17: (34.318, 132.306), 18: (34.054, 131.796), 19: (33.967, 130.946), 20: (33.904, 130.819),
            21: (33.887, 130.671), 22: (33.595, 130.395), 23: (33.453, 129.972), 24: (32.916, 129.955)}
SAME = "本人のふだん(全体の平均にそろえてある)"


def _adj(ent):
    """1行=1艇。c1 = 全体の3着以内率 + 本人のふだんとの差(コースの有利不利も差し引き)。"""
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


def _dw(d):
    """確率の差(ポイント)を言葉に: 1.8 → 「1.8ポイント高い」。両方の値があるときは _rate_change を使う。"""
    return "ほぼ同じ" if abs(d) < 0.5 else f"{abs(d):.1f}ポイント{'高い' if d > 0 else '低い'}"


def _pp(m):
    """ふだんとの差を「51%→53%に上がる」の形で(ふだん→この条件。差が小さいときは「ほぼ同じ(51%)」)。"""
    return _rate_change(m["in1"], m["in1_ref"], fine=_fine(m))


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
    con = (["休み明けは少し鈍る。連戦はむしろ好調", f"3着以内は、90日以上の休み明けは{_pp(ml)}、30日以上なら{_pp(mb)}。前の節から中1日以内の連戦は{_pp(mr)}。疲れより勢いが勝っている"]
           if real_back else ["休み明けも連戦も、思ったより平気", f"3着以内は、休み明けは{_pp(mb)}、連戦は{_pp(mr)}。選手は思ったより、すぐ戻ってくる"])
    return {
        "id": "rest", "title": "休み明けと連戦、どっちが響く?", "belief": "休み明けは勘が戻ってない。連戦は疲れがたまる。どっちも買いにくい",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"休み明け(30日以上あいた後の最初の3走)は、本人のふだんとくらべて、3着以内は{_pp(mb)}。90日以上の長い休みだと{_pp(ml)}。"
                f"前の節から中1日以内で別の場へ移る連戦は{_pp(mr)}、7日で12走以上の忙しい時期は{_pp(mbz)}。",
        "conclusion": con, "tables": [], "measures": ms,
        "rules": ["数字は、その選手の「ふだん」とくらべた差。強い選手も弱い選手も、自分自身とくらべている",
                  "休み明けの理由(けが、F休み、出産、ただの休み)はデータでは分からないので、まとめて見ている"],
        "faq": [("休み明けに弱い人はいる?", f"選手ごとの「休み明けの落ち方」は、{_person(pb)}"),
                ("長い休み明けは、何走で戻る?", "休み明けの最初の3走で見ている。4走目以降はふだんの数字とほとんど区別がつかない"),
                ("連戦がむしろ良いのはなぜ?", f"中1日で次の節に来るのは、前の節を最後まで走った(勝ち上がった)選手が多い。調子のいい選手が、そのまま次へ来ている。疲れは見えなかった"),
                ("忙しい週は落ちる?", f"7日で12走以上は、3着以内が{_pp(mbz)}。ただ、忙しい週は1日2走の日が多く、2走目は番組の作りで相手が強くなりやすい(『1走目と2走目』の回)。疲れとは分けられない")],
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
        "lead": f"所属する支部(住んでいる地域)から開催場までの距離で分けた。3着以内は、地元の近くで本人のふだんより{_pp(m0)}、"
                f"60〜300kmは{_pp(m1)}、300〜600kmは{_pp(m2)}、600km以上の大遠征は{_pp(m3)}。",
        "conclusion": ["地元は少しだけ強い。遠さは関係ない", f"地元の近くは3着以内が{_pp(m0)}。60kmを超えると、隣の県でも九州から関東でも同じ。移動の疲れは見えなかった"],
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
        "lead": f"28℃以上の暑い日、3着以内を本人のふだんとくらべると、体重の重い選手は{_pp(mbh)}、軽い選手は{_pp(mbc)}。"
                + ("向きは説のとおり、でも小さい。" if mbh["in1"] < mbh["in1_ref"] and mbc["in1"] >= mbc["in1_ref"] else "")
                + f"それより効いていたのは当日の体重。直近30走の平均より1.5kg以上軽い日は{_pp(ml)}、重い日は{_pp(mh)}。",
        "conclusion": ["夏の重量級は少しだけ本当。もっと効くのは『当日の体重』",
                       f"3着以内は、暑い日の重い選手が{_pp(mbh)}・軽い選手が{_pp(mbc)}。いっぽう当日の体重がふだんより軽い日は{_pp(ml)}・重い日は{_pp(mh)}。体重計の数字は、出走表のなかでも見落とされがち"],
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
        "lead": f"本人のふだんとくらべた3着以内は、節の初日が{_pp(m1)}、2・3日目が{_pp(m2)}、4日目が{_pp(m4)}、"
                f"最終日の一般戦が{_pp(mf)}。",
        "conclusion": ["日によって少し違う。でも人ごとの得意はない", f"3着以内は、初日が{_pp(m1)}、最終日の一般戦が{_pp(mf)}。「初日に強い人」は{sim_words(p1[0])}"],
        "tables": [], "measures": ms,
        "rules": ["節(ひとつの大会)はふつう4〜6日間。前半は予選、終盤に準優勝戦・優勝戦。予選で落ちた選手は最終日に一般戦を走る",
                  "数字は、その選手のふだんとくらべた差"],
        "faq": [("初日に強い人、最終日に強い人はいる?", f"初日の得意は{_person(p1)}。最終日の一般戦の得意は{_person(pf)}"),
                ("最終日の一般戦は、気が抜けている?", f"最終日の一般戦は、3着以内が{_pp(mf)}。気が抜けるどころか少し上。予選で落ちた選手どうしの組み合わせなので、相手もそれほど強くないから")],
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
        "lead": f"1日2走の日、本人のふだんとくらべた3着以内は、1走目が{_pp(m1)}、2走目が{_pp(m2)}。1走目が1着の日の2走目は{_pp(mg)}、4〜6着の日は{_pp(mb)}。"
                f"時間帯では、朝(〜11時台)は{_dw((mm['in1'] - mm['in1_ref']) * 100)}、夜(18時〜)は{_dw((mn['in1'] - mn['in1_ref']) * 100)}。",
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
        "lead": f"4〜6コースでチルトを1.5度以上に上げた選手は、上げていないときより3着以内に入るのが{_pp(mh)}。0.5〜1度なら{_pp(mm)}。"
                f"内(1・2コース)で跳ねると{_pp(ml)}。",
        "conclusion": (["本当。跳ねた選手は来る。外ならなおさら", f"4〜6コースで1.5度以上は、3着以内が{_pp(mh)}。内でも{_pp(ml)}。跳ねるのは足に自信がある日、というのも混ざっていそう"]
                       if verdicts(mh)["real"] and mh["in1"] > mh["in1_ref"] else ["ふだんと同じ。跳ねても劇的には変わらない", f"4〜6コースで1.5度以上は、3着以内が{_pp(mh)}"]),
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
        "lead": f"満月の日(前後1日)に1号艇が勝つのは{per100(mf['in1'])}、新月の日は{per100(mn['in1'])}、全体は{per100(mf['in1_ref'])}。"
                f"3連単で30番人気以下が来たのは、満月{_rate(uf)}・新月{_rate(un)}・全体{_rate(ua)}。",
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
        "lead": f"同じ日・同じ場で、前のレースが万舟(3連単1万円以上)だったとき、次のレースも万舟になったのは{_rate(man1)}。"
                f"前が万舟でなかったときは{_rate(man0)}、2つ続けて万舟のあとは{_rate(man2)}。1号艇が勝つのは{per100(m1['in1'])}(全体{per100(m1['in1_ref'])})。",
        "conclusion": (["少しだけ本当。でも理由は『流れ』じゃない", f"万舟のあとの万舟は{_rate(man1)}(ふだん{_rate(man0)})。荒れやすい場・荒れやすい天気の日は続けて荒れる、というだけ"]
                       if real else ["ふだんと同じ。流れはなかった", f"万舟のあとの万舟は{_rate(man1)}、ふだんは{_rate(man0)}"]),
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
        "lead": f"モーター番号の末尾が7の選手は、本人のふだんとくらべて、3着以内は{_pp(m7)}。末尾が艇番と同じ数字なら{_pp(ms_)}。"
                f"末尾7のモーターの2連率の平均は{p7:.1f}%(全体{pa:.1f}%)。",
        "conclusion": (["ふだんと同じ。7は普通の数字だった", "モーター番号の末尾で成績は変わらない。モーターの良し悪しは2連率と展示で見る"]
                       if not verdicts(m7)["real"] else ["差があった", f"末尾7は、3着以内が{_pp(m7)}"]),
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
        "lead": f"1号艇が勝つのは、雨の日に{per100(mr['in1'])}、晴れの日は{per100(mr['in1_ref'])}、雪の日は{per100(ms_['in1'])}。"
                f"3連単で30番人気以下が来たのは、雨{_rate(ur)}・晴れ{_rate(uf)}。",
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
    x["c1"] = base_ + x["res"]          # コースの有利不利だけ差し引いた3着以内率(本人の強さは残す)
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
    slope_txt = "、".join(f"{q['nm']} {_dw(q['slope'] * 100)}" for q in rows if q["slope"] == q["slope"])
    return {
        "id": "age", "title": "ボートレーサーは何歳がいちばん強い?", "belief": "ボートは体重が軽くて反射神経がいい若手が有利。でも経験のベテランも強い。結局どっち?",
        "subject": "その年齢の選手", "verb": "3着以内に入る", "no_market": True, "compare": "全選手(コースの有利不利は差し引き)",
        "lead": f"コースの有利不利を差し引いて3着以内に入るのは、{best['nm']}がいちばん多く{_rate(best['c1'])}。A1級の人も{a1best['nm']}がいちばん多く、100人に{_n100(a1best['a1'])}人。"
                f"同じ選手が1年でどれだけ変わるかを見ると、3着以内の確率が、24歳以下は1年に{abs(young['slope'] * 100):.1f}ポイント{'ふえ' if young['slope'] > 0 else 'へり'}、55歳以上は{abs(old['slope'] * 100):.1f}ポイント{'ふえる' if old['slope'] > 0 else 'へる'}。"
                + (f"伸びがマイナスに変わるのは{turn}から。" if turn else ""),
        "conclusion": [f"いちばん強いのは{best['nm']}。伸び盛りは{peak['nm']}",
                       f"若手は3着以内が1年に{abs(young['slope'] * 100):.1f}ポイントずつ伸び、30代半ばでほぼ横ばい、そこからゆっくり下がる(55歳以上で1年に{abs(old['slope'] * 100):.1f}ポイント)。"],
        "tables": [("年齢ごとの3着以内率(コースの有利不利を差し引き)", tbl, "3着以内率")],
        "measures": ms,
        "rules": ["年齢は出走表の年齢。3着以内率はコースの有利不利をそろえた値",
                  "1年あたりの変化は、同じ選手の3年間(100走以上)の成績を時間で並べたときの傾き。年齢は3年間の真ん中あたり",
                  "弱い選手ほど早く引退するので、年齢が上の選手は『残っている強い人』が多い(生き残りの偏り)"],
        "faq": [("年齢ごとの1年あたりの変化は?", f"3着以内の確率が1年でどれだけ変わるか(ポイント): {slope_txt}"),
                ("若手は狙い目?", f"24歳以下は、3着以内が1年に{abs(young['slope'] * 100):.1f}ポイント伸びている。出走表の勝率は過去の数字なので、伸び盛りの若手は勝率より強いことが多い(『上り調子』の型)"),
                ("ベテランはもう厳しい?", f"55歳以上は、1年に{abs(old['slope'] * 100):.1f}ポイント。下がり方はゆっくりで、スタートや前づけなど、経験で戦う選手も多い")],
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
        "lead": f"ゾロ目の日({nd}日分)に1号艇が勝つのは{per100(mz['in1'])}、13日の金曜日({nf}日分)は{per100(mf['in1'])}、全体は{per100(mz['in1_ref'])}。"
                f"30番人気以下の3連単が来たのは、ゾロ目の日{_rate(uz)}・13日の金曜日{_rate(uf)}・全体{_rate(ua)}。",
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
        "id": "payday", "title": "給料日と週末は、本命の配当がしぶくなる?", "belief": "給料日や週末は、ふだん買わない人が本命を買う。だから本命の配当がしぶくなる",
        "lead": f"1号艇が勝つ確率を、人気から考えられる値→実際でくらべた。給料日あたり{odds_pair(mp)}、月の半ば{odds_pair(me)}、"
                f"土日{odds_pair(mw)}、平日{odds_pair(mwd)}。" + ("どの日も、人気とのずれ方はいつもと同じ。" if all(v.get("edge") in (0, None) for _, _, v in ms) else ""),
        "conclusion": (["ふだんと同じ。配当はしぶくならない", "給料日も週末も、1号艇の人気のつき方はいつもとほとんど同じ。売れる量が増えても、本命に人気が集まりすぎることはない"]
                       if all(v.get("edge") in (0, None) for _, _, v in ms) else ["日によって少し違う", "くわしくは下の表"]),
        "tables": [], "measures": ms,
        "rules": ["オッズは締切の少し前に集めたもの(集めたレースの分だけ)。オッズから、1号艇が勝つ見込みを逆算した(払い戻しに回らない25%の分は除く)",
                  "1号艇はどの日でも、人気から考えるより少し多く来る。そのいつもの差とくらべて、給料日や週末だけ差が大きいかを見る"],
        "faq": [("週末は本命が売れすぎる?", "週末も平日も、本命の人気とのずれ方はほぼ同じ。ネット投票が中心なので、ふだんから買っている人の割合が大きいのかも")],
        "use": ["給料日や週末でも、本命の配当の見方は変えなくていい"],
        "mikata": "人気は思ったよりしっかりしていた。みんなの予想の集まりって、すごいんだね",
        "gen": "給料日に競艇場に行くのは、俺の数少ない楽しみなんだよ。配当なんて関係ねえ",
        "challenge": "給料日の夜、ナイターで1レースだけ『ごほうびの1点』を決めてみよう",
        "numbers": {"ratio_pay": mp.get("market_ratio"), "ratio_mid": me.get("market_ratio"), "ratio_weekend": rw, "ratio_weekday": rd},
    }


def _profiles():
    """公式の期別成績から、選手ごとの生年月日・性別・身長・血液型・出身地(最新の期)。個人の値は記事に出さない。"""
    import parse_racers
    rows = []
    for f in sorted((ROOT / "data/racers").glob("fan*.txt")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            q = parse_racers.parse_line(ln, f.stem[3:])
            if q:
                rows.append(q)
    df = pd.DataFrame(rows)
    return df.sort_values("period").groupby("racer_id").tail(1).set_index("racer_id")


ZODIAC = [((1, 20), "やぎ座"), ((2, 19), "みずがめ座"), ((3, 21), "うお座"), ((4, 20), "おひつじ座"), ((5, 21), "おうし座"), ((6, 22), "ふたご座"),
          ((7, 23), "かに座"), ((8, 23), "しし座"), ((9, 23), "おとめ座"), ((10, 24), "てんびん座"), ((11, 23), "さそり座"), ((12, 22), "いて座"), ((12, 32), "やぎ座")]


def _zodiac(b):
    if not isinstance(b, str):
        return None
    m, d = int(b[5:7]), int(b[8:10])
    for (mm, dd), nm in ZODIAC:
        if (m, d) < (mm, dd):
            return nm
    return "やぎ座"


def t_birthday(ent, r):
    """誕生日の週は強い?"""
    pr = _profiles()
    x = _adj(ent)
    b = pd.to_datetime(x["racer_id"].map(pr["birth"]), errors="coerce")
    x = x[b.notna()].copy(); b = b[b.notna()]
    this = pd.to_datetime(dict(year=x["dt"].dt.year, month=b.dt.month, day=b.dt.day.clip(upper=28)), errors="coerce")
    diff = (x["dt"] - this).dt.days
    diff = diff.where(diff.abs() <= 183, diff - np.sign(diff) * 365)
    bw, bd = diff.abs() <= 3, diff == 0
    mw, md = measure(x, bw), measure(x, bd)
    ms = [("誕生日の前後3日", mw, verdicts(mw)), ("誕生日の当日", md, verdicts(md))]
    return {
        "id": "birthday", "title": "誕生日の選手は強い?", "belief": "誕生日に走る選手は気合いが入る。ファンの声援もある。だから来る",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"誕生日の前後3日に走った選手は、本人のふだんとくらべて、3着以内は{_pp(mw)}。誕生日の当日({md['n']:,}走)は{_pp(md)}。",
        "conclusion": (["ふだんと同じ。誕生日もいつもどおり", f"3着以内は、前後3日が{_pp(mw)}、当日が{_pp(md)}。プロは誕生日でも平常心"]
                       if not (verdicts(mw)["real"] or verdicts(md)["real"]) else [f"誕生日は{'強い' if md['in1'] > md['in1_ref'] else '弱い'}……かも", f"当日は3着以内が{_pp(md)}(走数が少ないので幅は大きい)"]),
        "tables": [], "measures": ms,
        "rules": ["生年月日は公式の『レーサー期別成績』から。個人の誕生日はここには載せない",
                  "当日の走数は少ないので、たまたまの幅が大きい"],
        "faq": [("誕生日に勝つと、ニュースになるのは?", "めずらしいから記憶に残る。勝った日だけが話題になるので、『誕生日は強い』と感じやすい")],
        "use": ["誕生日で予想は変えなくていい。でも推しの誕生日に現地で応援するのは、それだけで最高の1日"],
        "mikata": "誕生日もいつもどおり走るのがプロ。でも、おめでとうの声は届いてると思う",
        "gen": "誕生日に1着取った選手を見たことがある。あれは忘れられねえ。だから俺は買うんだよ",
        "challenge": "推しの誕生日を調べて(公式の選手ページに載っている)、その週の出走予定を見てみよう",
        "numbers": {"week": mw["in1"] - mw["in1_ref"], "day": md["in1"] - md["in1_ref"], "n_day": md["n"]},
    }


def t_blood(ent, r):
    """血液型と星座(オカルト枠)。"""
    pr = _profiles()
    x = _adj(ent)
    base_ = float(x["top3"].mean())
    x["c1"] = base_ + x["res"]            # 本人の強さを残した(コースだけ差し引いた)数字。型の「強さ」をくらべるので
    x["blood"] = x["racer_id"].map(pr["blood"]); x["zod"] = x["racer_id"].map(pr["birth"].map(_zodiac))
    st = x[x["st"].between(0, 0.5) & x["st_flag"].isna()].groupby("blood")["st"].mean()
    ms = [(f"{b}型", measure(x, x["blood"] == b), None) for b in ("A", "B", "O", "AB")]
    ms = [(n, m, verdicts(m)) for n, m, _ in ms]
    zs = x.groupby("zod")["c1"].agg(["mean", "size"]).sort_values("mean", ascending=False)
    a1 = pr.groupby("blood")["class"].apply(lambda s_: float((s_ == "A1").mean()))
    top, bot = zs.index[0], zs.index[-1]
    spread = float(zs["mean"].max() - zs["mean"].min())
    btxt = "、".join(f"{b}型 {per100(m['in1'])}" for b, m in ((n[:-1], m) for n, m, _ in ms))
    return {
        "id": "blood", "title": "血液型と星座で、強い選手は分かる?", "belief": "A型は几帳面でスタートが正確、B型はまくり屋、O型は大らかで差し……星座だって関係あるはずだ",
        "subject": "その血液型の選手", "verb": "3着以内に入る", "no_market": True, "compare": "全選手(コースの有利不利は差し引き)",
        "lead": f"コースの有利不利を差し引いた3着以内は、{btxt}。平均STは A型{st.get('A', np.nan):.3f}・B型{st.get('B', np.nan):.3f}・O型{st.get('O', np.nan):.3f}・AB型{st.get('AB', np.nan):.3f}。"
                f"星座ではいちばん高い{top}といちばん低い{bot}の差は{spread * 100:.1f}ポイント。",
        "conclusion": (["ふだんと同じ。血液型も星座も関係なかった", "どの血液型も、どの星座も、ほとんど同じ数字。スタートの正確さも変わらない"]
                       if not any(v["real"] for _, _, v in ms) else ["少し差があった……けど", "血液型ごとの人数のかたよりで出る程度の差"]),
        "tables": [("星座ごとの3着以内率(コースを差し引き)", [{"venue": z, "rno": "", "n": int(zs.loc[z, "size"]), "in1": float(zs.loc[z, "mean"])} for z in zs.index], "3着以内率")],
        "measures": ms,
        "rules": ["血液型・生年月日は公式の『レーサー期別成績』から。個人の血液型はここには載せない(集計だけ)",
                  "選手の強さを残したまま、コースの有利不利だけそろえてくらべた"],
        "faq": [("A1級の人は?", "100人あたり、" + "、".join(f"{b}型 {_n100(a1.get(b, np.nan))}人" for b in ("A", "B", "O", "AB")) + "。ここも、ほぼ同じ"),
                ("星座で4回近くも差があるのは?", f"12個に分けると、たまたまでもこのくらいの差は出る(1つの星座あたり選手は150人ほど)。強い選手が何人か入るだけで動く。いちばん上の{top}もいちばん下の{bot}も、来年は入れ替わっているはず"),
                ("じゃあ占いは意味ない?", "成績を当てる道具にはならない。でも、推しの星座の運勢を見てから現地に行くのは、ぜんぜんありだと思う")],
        "use": ["血液型や星座で予想は変えなくていい", "……でも今日の運勢が1位の星座の選手を1人だけ応援する、くらいなら楽しい"],
        "mikata": "血液型も星座も、ボートの上ではみんな同じだった。でも占いを見てから出かける朝って、ちょっとわくわくするよね",
        "gen": "俺はO型だから大らかに穴を買う。それでいいじゃねえか。血液型で外れたことにすりゃ、気も楽だしな",
        "challenge": "今朝の星占いで1位の星座を見て、その星座の選手を出走表から探してみよう(選手の誕生日は公式の選手ページに)",
        "numbers": {"blood": {n: m["in1"] for n, m, _ in ms}, "st": {k: float(v) for k, v in st.items()}, "zodiac_spread": spread},
    }


def t_height(ent, r):
    """背の高さは有利? 不利?"""
    pr = _profiles()
    x = _adj(ent)
    base_ = float(x["top3"].mean())
    x["c1"] = base_ + x["res"]
    h = x["racer_id"].map(pr["height"]); sex = x["racer_id"].map(pr["sex"])
    x = x[(sex == "男") & h.notna()].copy(); h = h.loc[x.index]
    lo, hi = h.quantile(.2), h.quantile(.8)
    short, tall, mid = h <= lo, h >= hi, h.between(lo + 1, hi - 1)
    msh, mta = measure(x, short, ref=mid), measure(x, tall, ref=mid)
    st = x[x["st"].between(0, 0.5) & x["st_flag"].isna()]
    sts, stt = float(st[short.loc[st.index]]["st"].mean()), float(st[tall.loc[st.index]]["st"].mean())
    ms = [(f"背が低め(男子{int(lo)}cm以下)", msh, verdicts(msh)), (f"背が高め(男子{int(hi)}cm以上)", mta, verdicts(mta))]
    return {
        "id": "height", "title": "背が高い選手は不利?", "belief": "ボートは小さいほうが風の抵抗も少なくて有利。背が高いと不利だ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "真ん中の背の高さの選手(コースの有利不利は差し引き)",
        "lead": f"男子選手で、背が低め({int(lo)}cm以下)は{per100(msh['in1'])}、高め({int(hi)}cm以上)は{per100(mta['in1'])}、真ん中は{per100(msh['in1_ref'])}。"
                f"平均STは低め{sts:.3f}・高め{stt:.3f}。",
        "conclusion": (["ふだんと同じ。背の高さは関係なかった", "体重には最低体重の決まりがあるので、背の高さの差はレースではあまり出ない"]
                       if not (verdicts(msh)["real"] or verdicts(mta)["real"]) else [f"背が{'低い' if msh['in1'] > mta['in1'] else '高い'}ほうが少し有利", f"低め{per100(msh['in1'])}・高め{per100(mta['in1'])}"]),
        "tables": [], "measures": ms,
        "rules": ["身長は公式の『レーサー期別成績』から。男女で体格がちがうので男子選手だけでくらべた",
                  "体重には最低体重(足りない分はおもりを積む)の決まりがある"],
        "faq": [("体重のほうが大事?", "体重は『夏は重い選手が不利って本当?』の回へ。当日の体重がふだんより重い日は、はっきり成績が下がっていた")],
        "use": ["背の高さで予想は変えなくていい"],
        "mikata": "背の高さは関係なかった。小さな体で大きなボートを操るのも、大きな体で小さく構えるのも、どっちもかっこいい",
        "gen": "背の高いやつがボートに伏せる姿、あれは美しいんだよ。数字じゃねえんだ",
        "challenge": "ピットに戻ってくる選手を見て、背の高さとボートの上での構え方をくらべてみよう",
        "numbers": {"short": msh["in1"], "tall": mta["in1"], "mid": msh["in1_ref"], "st_short": sts, "st_tall": stt},
    }


def t_furusato(ent, r):
    """生まれ故郷の場で走ると強い?(支部の地元とは別に)"""
    pr = _profiles()
    x = _adj(ent)
    pref_of_jcd = {1: "群馬", 2: "埼玉", 3: "東京", 4: "東京", 5: "東京", 6: "静岡", 7: "愛知", 8: "愛知", 9: "三重", 10: "福井", 11: "滋賀",
                   12: "大阪", 13: "兵庫", 14: "徳島", 15: "香川", 16: "岡山", 17: "広島", 18: "山口", 19: "山口", 20: "福岡", 21: "福岡",
                   22: "福岡", 23: "佐賀", 24: "長崎"}
    vp = x["jcd"].map(pref_of_jcd)
    home = x["racer_id"].map(pr["hometown"])
    furu = (home == vp)
    branch_home = x["branch"] == vp
    m_both, m_furu, m_br = measure(x, furu & branch_home), measure(x, furu & ~branch_home), measure(x, branch_home & ~furu)
    ms = [("生まれ故郷で、しかも所属支部の地元", m_both, verdicts(m_both)), ("生まれ故郷だけど、所属支部は別の県", m_furu, verdicts(m_furu)),
          ("所属支部の地元だけど、生まれは別の県", m_br, verdicts(m_br))]
    return {
        "id": "furusato", "title": "生まれ故郷の水面では燃える?", "belief": "地元が強いのは支部だからじゃない。生まれ育った故郷の水面だからだ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"本人のふだんとくらべた3着以内は、生まれ故郷かつ所属支部の地元で走ると{_pp(m_both)}。故郷だけど別の支部に所属している選手が故郷で走ると{_pp(m_furu)}、"
                f"支部の地元だけど生まれは別の県なら{_pp(m_br)}。",
        "conclusion": [("故郷はちょっとだけ燃える" if m_furu["in1"] > m_furu["in1_ref"] else "故郷より、ふだん走る水面"),
                       f"3着以内は、故郷だけが{_pp(m_furu)}・支部の地元だけが{_pp(m_br)}・両方が{_pp(m_both)}。差は小さい"],
        "tables": [], "measures": ms,
        "rules": ["出身地は公式の『レーサー期別成績』の出身地(都道府県)。県にレース場があるときだけ数えた",
                  "支部は、ふだん所属して練習している地域。結婚や引っ越しで、生まれと支部がちがう選手もいる"],
        "faq": [("地元が強いのは、水面に慣れているから?", "支部の地元(ふだん練習する水面)と、生まれ故郷を分けると、どちらが効いているかが少し見える。上の3行をくらべてみて")],
        "use": ["故郷に帰ってきた選手は、少しだけ気にかける。でもモーターと展示が先"],
        "mikata": "故郷に帰ってきた選手を見ると、なんだか応援したくなる。数字の差は小さくても、物語は大きいよね",
        "gen": "故郷の水面で走るやつの背中は、いつもよりでかく見えるんだよ",
        "challenge": "出走表の選手名から公式の選手ページを開いて、出身地が開催場の県の選手を探してみよう",
        "numbers": {"both": m_both["in1"] - m_both["in1_ref"], "furusato_only": m_furu["in1"] - m_furu["in1_ref"], "branch_only": m_br["in1"] - m_br["in1_ref"]},
    }


_WX = None


def _wx():
    """過去の天気(data/weather/archive.csv.gz)を (場, 時刻) で引けるように。暑さ指数(WBGT)は気温・湿度・日射・風からの近似式。"""
    global _WX
    if _WX is None:
        w = pd.read_csv(ROOT / "data/weather/archive.csv.gz")
        w["time"] = pd.to_datetime(w["time"])
        ta, rh, sr, ws = w["temperature_2m"], w["relative_humidity_2m"], w["shortwave_radiation"] / 1000, w["wind_speed_10m"]
        # 小野・登内(2014)の近似式(環境省の暑さ指数の推定に使われている形)
        w["wbgt"] = 0.735 * ta + 0.0374 * rh + 0.00292 * ta * rh + 7.619 * sr - 4.557 * sr ** 2 - 0.0572 * ws - 4.064
        w = w.sort_values(["jcd", "time"])
        w["p_anom"] = w["surface_pressure"] - w.groupby(["jcd", w["time"].dt.month])["surface_pressure"].transform("mean")
        w["p_3h"] = w.groupby("jcd")["surface_pressure"].diff(3)          # 3時間の気圧の変化(下がっている途中か)
        _WX = w.set_index(["jcd", "time"])
    return _WX


def _with_wx(df, cols=("wbgt", "p_anom", "p_3h", "relative_humidity_2m", "surface_pressure", "temperature_2m")):
    """df(date・jcd・deadline を持つ)に、締切の時刻(時で切り捨て)の天気を付ける。"""
    w = _wx()
    hh = df["deadline"].astype(str).str.extract(r"(\d{1,2}):(\d{2})")
    t = pd.to_datetime(df["date"].astype(str)) + pd.to_timedelta(pd.to_numeric(hh[0], errors="coerce"), unit="h")
    key = pd.MultiIndex.from_arrays([df["jcd"].astype(int), t])
    out = df.copy()
    for c in cols:
        out[c] = w[c].reindex(key).values
    return out


def _races_wx(ent, r):
    dl = ent.drop_duplicates("race_id").set_index("race_id")["deadline"]
    x = r.copy(); x["deadline"] = x["race_id"].map(dl)
    return _with_wx(x)


def t_pressure(ent, r):
    """低気圧の日は荒れる? 気圧に弱い選手はいる?(気象病)"""
    x = _races_wx(ent, r)
    lowp, highp = x["p_anom"] <= -8, x["p_anom"] >= 8
    falling = x["p_3h"] <= -2
    ml, mh, mf = measure(x, lowp), measure(x, highp), measure(x, falling)
    ul, uh, ua = float(x[lowp]["upset"].mean()), float(x[highp]["upset"].mean()), float(x["upset"].mean())
    e = _with_wx(_adj(ent))
    pe = _gap(e, e["p_anom"] <= -6, e["p_anom"].abs() <= 3, 8, by="day")
    me = measure(e, e["p_anom"] <= -8, ref=e["p_anom"].abs() <= 3)
    ms = [("ふだんよりかなり低い気圧(-8hPa以下)", ml, verdicts(ml)), ("ふだんよりかなり高い気圧(+8hPa以上)", mh, verdicts(mh)), ("3時間で2hPa以上下がっている途中", mf, verdicts(mf))]
    return {
        "id": "pressure", "title": "低気圧の日は荒れる? 頭が痛い選手は?", "belief": "低気圧の日はエンジンが回らないし、体もだるい。だから荒れる",
        "lead": f"その場・その月のふだんの気圧より8hPa以上低い日、1号艇が勝つのは{per100(ml['in1'])}(全体{per100(ml['in1_ref'])})、高い日は{per100(mh['in1'])}。"
                f"30番人気以下が来たのは、低い日{_rate(ul)}・高い日{_rate(uh)}・全体{_rate(ua)}。",
        "conclusion": ([f"低気圧の日は1号艇が{'少し弱い' if ml['in1'] < ml['in1_ref'] else '少し強い'}", f"低い日{per100(ml['in1'])}・全体{per100(ml['in1_ref'])}。ただ、低気圧の日は風も強いことが多い"]
                       if verdicts(ml)["real"] else ["ふだんと同じ。気圧だけでは荒れない", f"低い日{per100(ml['in1'])}・高い日{per100(mh['in1'])}・全体{per100(ml['in1_ref'])}。荒れるのは気圧より風のせい"]),
        "tables": [], "measures": ms,
        "rules": ["気圧はレース場のおおよその位置の、締切の時刻の値(過去の気象データの再解析。場の気圧計の記録ではない)",
                  "『ふだん』は、その場のその月の平均気圧。季節と標高の差を除くため"],
        "faq": [("低気圧に弱い選手(気象病)はいる?", f"気圧が低い日の3着以内は{_rate_change(me['in1'], me['in1_ref'], ref_label='本人のふだんの')}。人ごとの差は{_person(pe)}"),
                ("エンジンは気圧で変わる?", "空気がうすいと出力は下がる。でも6艇とも同じ空気なので、順位にはあまり出ない。差がつくのは、それに合わせた調整のうまさ")],
        "use": ["低気圧の日は、まず風を見る。風が弱ければ、ふだんどおりに", "頭が痛い日は、無理せず家で見るのもあり"],
        "mikata": "気圧そのものは、レースをあまり動かさなかった。でも低気圧の日にスタンドで食べる熱いうどんは、たぶん最高",
        "gen": "低気圧の日は膝が痛むんだよ。だから俺は内を買う。膝が教えてくれるのさ",
        "challenge": "天気予報で気圧の谷が来る日を見つけて、その日の1マークの攻防が荒れるかどうか見てみよう",
        "numbers": {"in1_low": ml["in1"], "in1_high": mh["in1"], "upset_low": ul, "upset_high": uh, "person_low": pe[0]},
    }


def t_humid(ent, r):
    """湿気の多い日は、インが強い?(エンジンの出力と空気)"""
    x = _races_wx(ent, r)
    x["wind"] = pd.to_numeric(x["wind"], errors="coerce")
    hum = x["relative_humidity_2m"]
    wet, dry, mid = hum >= 75, hum <= 55, hum.between(56, 74)
    mw, md = measure(x, wet, ref=dry), measure(x, dry)
    calm = x["wind"] <= 3
    mcw, mcd = measure(x, wet & calm, ref=dry & calm), measure(x, dry & calm, ref=calm)
    mw["ref_label"], mcw["ref_label"] = "乾いた日", "風の弱い乾いた日"
    # 場×月の差を除いた「湿−乾」、場ごとに同じ向きか
    xv = x[hum.notna()].copy()
    xv["c1vm"] = xv["c1"] - xv.groupby(["jcd", pd.to_datetime(xv["date"]).dt.month])["c1"].transform("mean")
    gap_vm = float(xv[xv["relative_humidity_2m"] >= 75]["c1vm"].mean() - xv[xv["relative_humidity_2m"] <= 55]["c1vm"].mean())
    d = xv.assign(hb=np.where(xv["relative_humidity_2m"] >= 75, "w", np.where(xv["relative_humidity_2m"] <= 55, "d", "m"))).groupby(["jcd", "hb"])["c1"].mean().unstack()
    n_pos, n_v = int(((d["w"] - d["d"]) > 0).sum()), int(d[["w", "d"]].dropna().shape[0])
    temps = []
    for lo, hi in ((0, 12), (12, 20), (20, 27), (27, 45)):
        m_ = calm & x["temperature_2m"].between(lo, hi)
        temps.append(f"{lo}〜{hi}℃で{per100(float(x[m_ & dry]['c1'].mean()))}→{per100(float(x[m_ & wet]['c1'].mean()))}")
    e = _with_wx(_adj(ent))
    ph = _gap(e, e["relative_humidity_2m"] >= 75, e["relative_humidity_2m"] <= 55, 10, by="day")
    ms = [("湿度75%以上の日(乾いた日=湿度55%以下とくらべて)", mw, verdicts(mw)), ("風3m以下の日だけでくらべても", mcw, verdicts(mcw))]
    return {
        "id": "humid", "title": "湿気の多い日は、インが強い", "belief": "湿気が多いとエンジンが回らない。伸びがなくなって、外からのまくりが届かない",
        "lead": f"湿度75%以上の時間に1号艇が勝つのは{per100(mw['in1'])}、湿度55%以下の乾いた空気だと{per100(mw['in1_ref'])}。"
                f"同じ場・同じ月の中でくらべても{abs(gap_vm * 100):.1f}ポイントの差があり、{n_v}場のうち{n_pos}場で同じ向き。"
                f"風が弱い日だけ、気温をそろえて見ても同じだった({'、'.join(temps)})。",
        "conclusion": ["本当。湿気の日はインが強い(人気どおり)", f"乾いた空気{per100(mw['in1_ref'])}→湿った空気{per100(mw['in1'])}。場・季節・風・気温をそろえても残る。湿った空気はうすくてエンジンの力が少し落ち、外からのまくりが届きにくい……と考えられる。人気もそれをちゃんと映している"],
        "tables": [], "measures": ms,
        "rules": ["湿度は、レース場のおおよその位置の締切の時刻の値(過去の気象データの再解析。場の観測値ではない)",
                  "湿った空気は、乾いた空気より少し軽い(水蒸気は軽い)。そのぶん酸素がうすく、エンジンの出力が少し下がる",
                  "冬の乾いた日は風も強いので、風の弱い日だけ・同じ気温どうしでもくらべた"],
        "faq": [("人気どおり?", f"人気どおり。人気から考えられる値→実際は、湿った日{odds_pair(mw)}、乾いた日{odds_pair(md)}。展示タイムなどを通して、湿気の影響は人気に出ているみたい"),
                ("湿気に強い選手はいる?", f"選手ごとの「湿った日−乾いた日」は、{_person(ph)}。選手より、空気そのものの話"),
                ("どこで見ればいい?", "天気予報の湿度。朝の予報でだいたい分かる。ミカタは毎朝、全場の予報を集めている")],
        "use": ["湿度は『なぜ今日はインが強いのか』を読むための材料。配当はそのぶん堅いので、2着・3着で工夫する", "乾いた冬の日は、外のまくり屋の一発を頭に入れておく"],
        "mikata": "肌で感じるジメジメが、1マークの攻防まで変えていた。空気って、ちゃんとレースの一部なんだね",
        "gen": "だろ? 梅雨どきのエンジンは重てえんだよ。俺の体も重てえけどな",
        "challenge": "今日の天気予報で湿度を見てから現地へ。ジメジメの日は1号艇、カラッとした日は外を応援してみよう",
        "numbers": {"in1_wet": mw["in1"], "in1_dry": md["in1"], "gap_venue_month": gap_vm, "venues_same_dir": n_pos, "venues": n_v,
                    "ratio_wet": mw.get("market_ratio"), "ratio_dry": md.get("market_ratio")},
    }


def t_heat(ent, r):
    """暑さ指数(WBGT)が危険な日、選手はどうなる?"""
    e = _with_wx(_adj(ent))
    w = e["wbgt"]
    danger, warn, cool = w >= 31, w.between(28, 31), w < 21
    md, mw_ = measure(e, danger, ref=cool), measure(e, warn, ref=cool)
    old, young = e["age"] >= 50, e["age"] <= 29
    mo, my = measure(e, danger & old, ref=old & cool), measure(e, danger & young, ref=young & cool)
    wq = e.groupby("racer_id")["weight_now"].transform("mean")
    big = wq >= wq.quantile(0.67)
    mb = measure(e, danger & big, ref=big & cool)
    pe = _gap(e, w >= 28, w < 21, 10, by="day")
    st = e[e["st"].between(0, 0.5) & e["st_flag"].isna()]
    std_, stc = float(st[st["wbgt"] >= 31]["st"].mean()), float(st[st["wbgt"] < 21]["st"].mean())
    ms = [("暑さ指数31以上(危険)", md, verdicts(md)), ("28〜31(厳重警戒)", mw_, verdicts(mw_)), ("50歳以上 × 危険な暑さ", mo, verdicts(mo)),
          ("29歳以下 × 危険な暑さ", my, verdicts(my)), ("体重の重い選手 × 危険な暑さ", mb, verdicts(mb))]
    return {
        "id": "heat", "title": "危険な暑さの日、選手は?", "belief": "真夏の昼は選手もバテる。ベテランや体の大きい選手は特にきつい",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "同じ人たちの、涼しい日(暑さ指数21未満)(本人のふだんにそろえてある)",
        "lead": f"暑さ指数(WBGT)31以上の危険な暑さの時間、選手が3着以内に入るのは、涼しい日より{_pp(md)}。50歳以上は{_pp(mo)}、29歳以下は{_pp(my)}、"
                f"体重の重い選手は{_pp(mb)}。平均STは危険な暑さで{std_:.3f}、涼しい日で{stc:.3f}。",
        "conclusion": (["暑さで成績は落ちない。プロのからだはすごい", f"危険な暑さでも、3着以内は{_pp(md)}。ベテランは{_pp(mo)}・若手は{_pp(my)}・重い選手は{_pp(mb)}"]
                       if not any(v["real"] and m["in1"] < m["in1_ref"] for _, m, v in ms) else ["暑さは効く。特に効く人がいる", f"危険な暑さで3着以内が{_pp(md)}。ベテランは{_pp(mo)}・重い選手は{_pp(mb)}"]),
        "tables": [], "measures": ms,
        "rules": ["暑さ指数(WBGT)は、気温・湿度・日射・風からの近似式で計算した推定値(小野・登内の式)。実際の観測値ではない",
                  "31以上は『危険』、28〜31は『厳重警戒』(環境省の区分)。レースは日中の暑い時間にも行われる"],
        "faq": [("暑さに弱い選手はいる?", f"選手ごとの「暑い日−涼しい日」は、{_person(pe)}"),
                ("スタートは鈍る?", f"危険な暑さの平均STは{std_:.3f}、涼しい日は{stc:.3f}。ほとんど変わらない")],
        "use": ["暑さで選手を割り引く必要はほとんどない", "暑いのは見ているこっち。水分と日陰を忘れずに"],
        "mikata": "選手は暑さに強かった。危ないのは、むしろスタンドで夢中になっているわたしたちのほう。水を飲もうね",
        "gen": "真夏の昼間にビール片手に見るレース。これが最高なんだよ。……水も飲めって? 分かってるよ",
        "challenge": "真夏の現地観戦は、暑さ指数の予報を見てから。日陰の席を先に確保するのが、いちばんの勝ち",
        "numbers": {"danger": md["in1"] - md["in1_ref"], "old": mo["in1"] - mo["in1_ref"], "young": my["in1"] - my["in1_ref"], "big": mb["in1"] - mb["in1_ref"], "st_hot": std_, "st_cool": stc},
    }


def t_lane6(ent, r):
    """6号艇の大穴は、いつ来る?(オッズは知ってる?)"""
    x = r.copy()
    x["c6"] = (x["win_lane"] == 6).astype(float)
    e6 = ent[ent["lane"] == 6].drop_duplicates("race_id").set_index("race_id")
    e1 = ent[ent["lane"] == 1].drop_duplicates("race_id").set_index("race_id")
    x["cls6"], x["cls1"] = x["race_id"].map(e6["racer_class"]), x["race_id"].map(e1["racer_class"])
    x["tilt6"], x["crs6"] = x["race_id"].map(e6["tilt"]), x["race_id"].map(e6["ex_course"])   # 展示の進入(オッズが締まる前に分かる)
    x["wind"] = pd.to_numeric(x["wind"], errors="coerce")
    q = "q_l6" if "q_l6" in x else None
    m_all = measure(x, x["c6"].notna(), col="c6", qcol=q) if q else None
    conds = [("6号艇がA1、1号艇がB級", (x["cls6"] == "A1") & x["cls1"].isin(["B1", "B2"])),
             ("6号艇がチルト1度以上(跳ねた)", x["tilt6"] >= 1.0),
             ("6号艇がスタート展示で前づけ(5コース以内)", x["crs6"] <= 5),
             ("風5m以上", x["wind"] >= 5)]
    ms = [(nm, measure(x, c, col="c6", qcol=q), None) for nm, c in conds]
    ms = [(nm, m, verdicts(m)) for nm, m, _ in ms]
    base6 = float(x["c6"].mean())
    best = max(ms, key=lambda q_: q_[1]["in1"])
    hid = [q_ for q_ in ms if q_[2].get("edge") == 1 and q_[2].get("real")]   # オッズの見込みより来ている、本物の差
    return {
        "id": "lane6", "title": "6号艇の大穴は、いつ来る?", "belief": "6号艇はめったに来ない。でも来るときは来る。その『とき』が分かれば夢がある",
        "subject": "6号艇", "lead": f"6号艇が勝つのは、ふだんは{base6 * 100:.1f}%。"
                + "。".join(f"{nm}なら{m['in1'] * 100:.1f}%" for nm, m, _ in ms) + "。",
        "conclusion": ([f"「{hid[0][0]}」は、人気以上に来る", f"{hid[0][1]['in1'] * 100:.1f}%(ふだん{base6 * 100:.1f}%)。人気から考えるより多い。いちばん多く来るのは「{best[0]}」の{best[1]['in1'] * 100:.1f}%だけど、こちらは人気どおり"]
                       if hid else [f"いちばん来るのは「{best[0]}」", f"ふだん{base6 * 100:.1f}%が{best[1]['in1'] * 100:.1f}%に。ただし人気どおり(みんな知っている)"]),
        "tables": [], "measures": ms,
        "rules": ["6号艇=6枠の艇。ふだんは6コース(いちばん外)から、長い助走のダッシュでスタートする",
                  "チルトを跳ねる(上げる)と直線が伸びる。前づけは外の枠から内のコースを取ること"],
        "faq": [("どれがいちばん『おいしい』?", "『人気以上に来る』のしるしが付いた行が、みんながまだ気づいていない大穴。『人気どおり』の行は、来る回数に見合った配当"),
                ("6号艇は、そもそも人気どおりに来る?", "6号艇は、人気から考えるより、いつも少しだけひかえめ(人気薄が買われすぎる、よくある傾向)。その分を差し引いてから、くらべている"),
                ("前づけの6号艇は、なぜ人気以上に来る?", "オッズを集めたのは締切の少し前で、スタート展示の進入はもう分かっている時間。それでも人気以上に来ているのは、『6号艇は来ない』という思い込みが強いからかも。レース数は5,000ほどで、ミカタは追いかけて確かめ続ける"),
                ("6号艇を毎回買ったら?", "ふだんの割合では、配当がよくても控除の分だけ負ける計算。条件がそろったときだけ、夢を見るのがいい")],
        "use": ["6号艇の大穴は『A1の6号艇 × B級の1号艇』『チルトを跳ねた6号艇』から探す", "風の強い日は、外の艇にも出番がある"],
        "mikata": "6号艇が1着でゴールする瞬間って、スタンドがどよめくよね。条件がそろったときだけ、その夢を見よう",
        "gen": "6号艇の頭は男のロマンだ。チルトを跳ねたA1の6号艇なんて見たら、俺は黙って買うね",
        "challenge": "今日の出走表から『A1の6号艇』を探して、そのレースだけ6号艇の頭で予想してみよう",
        "numbers": {"base6": base6, **{nm: m["in1"] for nm, m, _ in ms}},
    }


def t_motor(ent, r):
    """モーター2連率は信じていい?"""
    x = _adj(ent)
    mr = pd.to_numeric(x["motor_2rate"], errors="coerce")
    top, mid, low = mr >= 45, mr.between(30, 36), mr <= 25
    mt, ml = measure(x, top, ref=mid), measure(x, low, ref=mid)
    ex = x["exhibit_time"].notna()
    x["exr"] = x.groupby("race_id")["exhibit_time"].rank(method="min")
    me1 = measure(x, ex & (x["exr"] == 1), ref=ex & x["exr"].between(3, 4))
    me6 = measure(x, ex & (x["exr"] == 6), ref=ex & x["exr"].between(3, 4))
    # 2連率が高いのに展示が下位、低いのに展示が1位
    mhb = measure(x, top & ex & (x["exr"] >= 5), ref=mid & ex & x["exr"].between(3, 4))
    mlg = measure(x, low & ex & (x["exr"] == 1), ref=mid & ex & x["exr"].between(3, 4))
    ms = [("モーター2連率45%以上", mt, verdicts(mt)), ("2連率25%以下", ml, verdicts(ml)), ("展示タイム1位", me1, verdicts(me1)), ("展示タイム6位", me6, verdicts(me6)),
          ("2連率45%以上なのに展示5・6位", mhb, verdicts(mhb)), ("2連率25%以下なのに展示1位", mlg, verdicts(mlg))]
    return {
        "id": "motor", "title": "モーター2連率は信じていい?", "belief": "モーターは2連率がすべて。40%超えの『エース機』を引いた選手を買えばいい",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": "2連率30〜36%のふつうのモーター(本人のふだんにそろえてある)",
        "lead": f"本人のふだんとくらべた3着以内は、モーター2連率45%以上で{_pp(mt)}、25%以下で{_pp(ml)}。いっぽう展示タイム1位は{_pp(me1)}、6位は{_pp(me6)}。"
                f"2連率が高いのに展示5・6位なら{_pp(mhb)}、2連率が低いのに展示1位なら{_pp(mlg)}。",
        "conclusion": ["2連率より、今日の展示", f"2連率45%以上でも、3着以内は{_pp(mt)}どまり。展示タイム1位は{_pp(me1)}。数字のいいモーターでも、展示が悪ければ{_pp(mhb)}"],
        "tables": [], "measures": ms,
        "rules": ["モーター2連率: そのモーターが今までのレースで2着以内に入った割合(出走表に載っている)。乗った選手の腕も混ざる",
                  "モーターは年に1回くらい新しくなり、そのあとしばらくは2連率の数字があてにならない",
                  "数字は、その選手のふだんとくらべた差。強い選手もふだんの自分とくらべている"],
        "faq": [("なぜ2連率は効きが弱い?", "2連率には、前に乗っていた選手の腕も入っている。強い選手が続けて乗ったモーターは、数字が高めに出る。展示タイムは今日の、その選手とモーターの組み合わせそのもの"),
                ("ミカタのモデルは?", "モーターは2連率のほかに、乗り手の腕を差し引いた『モーターの力』と、今節の展示・成績を使っている")],
        "use": ["2連率は目安。最後は展示タイムで決める", "2連率が低いモーターで展示1位なら、その選手が仕上げてきた合図"],
        "mikata": "モーターの数字は過去の話、展示は今日の話。今日の話のほうが、やっぱり強いね",
        "gen": "エース機を引いたやつの顔は明るいんだよ。……でも展示で遅けりゃ、そりゃ買えねえな",
        "challenge": "今日の出走表で2連率がいちばん高いモーターを探して、その選手の展示タイムの順位を見てみよう",
        "numbers": {"top": mt["in1"] - mt["in1_ref"], "low": ml["in1"] - ml["in1_ref"], "ex1": me1["in1"] - me1["in1_ref"], "ex6": me6["in1"] - me6["in1_ref"],
                    "top_but_slow": mhb["in1"] - mhb["in1_ref"], "low_but_fast": mlg["in1"] - mlg["in1_ref"]},
    }


def t_entry(ent, r):
    """展示の進入と本番の進入は同じ?(スタート展示を信じていい?)"""
    e = ent[ent["course"].between(1, 6) & ent["ex_course"].between(1, 6)]
    diff_boat = (e["course"] != e["ex_course"])
    rd = diff_boat.groupby(e["race_id"]).any()
    ex_front = (e["ex_course"] < e["lane"]).groupby(e["race_id"]).any()
    x = r[r["race_id"].isin(rd.index)].copy()
    x["chg"] = x["race_id"].map(rd).astype(bool); x["exfront"] = x["race_id"].map(ex_front).astype(bool)
    share = float(x["chg"].mean())
    keep = float((~x.loc[x["exfront"], "chg"]).mean())
    mc, mn = measure(x, x["chg"], ref=~x["chg"]), measure(x, x["exfront"] & ~x["chg"], ref=~x["exfront"])
    uc, un = float(x[x["chg"]]["upset"].mean()), float(x[~x["chg"]]["upset"].mean())
    ms = [("展示と本番で進入が変わったレース", mc, verdicts(mc)), ("展示で前づけがあり、本番も同じ進入", mn, verdicts(mn))]
    return {
        "id": "entry", "title": "スタート展示の進入は信じていい?", "belief": "スタート展示はあくまで練習。本番では進入が変わる。展示の並びは当てにならない",
        "compare": "進入が変わらなかったレース",
        "lead": f"展示と本番で進入(コースの並び)がひとつでも変わったのは、{_rate(share)}のレース。展示で前づけがあったレースでも、本番で同じ並びだったのは100回に{_rate(keep)}。"
                f"進入が変わったレースで1号艇が勝つのは{per100(mc['in1'])}(変わらなかったレースは{per100(mc['in1_ref'])})、30番人気以下が来たのは{_rate(uc)}(変わらない{_rate(un)})。",
        "conclusion": [f"信じていい。{_rate(1 - share)}は展示どおり", f"ただし進入が変わったレースは荒れやすい(1号艇{per100(mc['in1'])}・大穴{_rate(uc)})。変わったときは、ひと波乱の合図"],
        "tables": [], "measures": ms,
        "rules": ["スタート展示: レースの前に、本番と同じようにスタートの練習をする。そこでの進入が『展示の進入』",
                  "ミカタの直前予想は、展示の進入でコースを決めている"],
        "faq": [("進入が変わるのは、どんなとき?", "前づけの仕掛け人がいるレース。展示では様子を見て、本番で動く選手もいる。選手カードの『前づけの仕掛け人』の型が目印"),
                ("本番の進入が決まるのはいつ?", "スタートの直前、ピットを出てからの待機行動で決まる。現地ならピット離れから目が離せない")],
        "use": ["展示の進入は信じていい。直前予想もそれで計算している", "本番で進入が変わったら、その場で『荒れるかも』と身構える"],
        "mikata": "展示の並びはほとんどそのまま。でも変わったときのざわざわ感は、現地のいちばんの見どころかも",
        "gen": "ピット離れで動くやつがいると、スタンドが一瞬ざわつく。あの空気がたまらねえんだよ",
        "challenge": "現地では、スタート展示の並びをメモしておいて、本番の待機行動で変わるかどうかを見てみよう",
        "numbers": {"share_changed": share, "keep_after_exfront": keep, "upset_changed": uc, "upset_same": un},
    }


# 新燃料 E30(エタノール30%配合ガソリン)の導入日(BOAT RACE振興会の発表と、各場の告知のまとめ)。びわこ・大村は2025年から試験導入
E30 = {6: "2026-04-09", 21: "2026-04-16", 13: "2026-04-17", 5: "2026-04-18", 18: "2026-04-20", 19: "2026-04-29", 3: "2026-05-11",
       4: "2026-06-18", 2: "2026-08-06", 7: "2026-08-11", 23: "2026-09-16", 15: "2026-09-17", 8: "2026-10-06"}
E30_EARLY = {11, 24}


def t_e30(ent, r):
    """新燃料E30で、レースは変わった?(導入した場と、まだの場を同じ時期でくらべる)"""
    W = 90
    end = pd.to_datetime(r["date"]).max()
    e = ent.copy(); e["dt"] = pd.to_datetime(e["date"])
    e["course"] = e["course"].fillna(e["lane"])
    e["F"] = (e["st_flag"] == "F").astype(float)
    win = e[e["finish"] == 1].drop_duplicates("race_id").set_index("race_id")
    x = r.copy(); x["dt"] = pd.to_datetime(x["date"])
    x["wcourse"] = x["race_id"].map(win["course"])
    x["in1c"] = (x["wcourse"] == 1).astype(float)
    x["mk"] = pd.to_numeric(x["kimarite"], errors="coerce").isin([3, 4]).astype(float)   # まくり・まくり差し
    rf = e.groupby("race_id").agg(F=("F", "sum"), st=("st", lambda q: q[(q >= 0) & (q < 0.6)].mean()), ex=("exhibit_time", "mean"))
    x = x.join(rf, on="race_id")
    rows, ctl = [], []
    for j, d0 in E30.items():
        d0 = pd.Timestamp(d0)
        if d0 + pd.Timedelta(days=30) > end:
            continue
        lo, hi = d0 - pd.Timedelta(days=W), min(d0 + pd.Timedelta(days=W), end)
        win_ = x["dt"].between(lo, hi)
        pre, post = x["dt"] < d0, x["dt"] >= d0
        t_ = win_ & (x["jcd"] == j)
        not_yet = x["jcd"].map(lambda k: k not in E30_EARLY and (k not in E30 or pd.Timestamp(E30[k]) > hi))
        c_ = win_ & not_yet
        for k, (tm, cm) in {"t": (t_ & pre, t_ & post), "c": (c_ & pre, c_ & post)}.items():
            for nm in ("in1c", "F", "st", "ex", "mk", "upset"):
                (rows if k == "t" else ctl).append({"jcd": j, "m": nm, "pre": float(x.loc[tm, nm].mean()), "post": float(x.loc[cm, nm].mean()),
                                                    "n_pre": int(tm.sum()), "n_post": int(cm.sum())})
    T, C = pd.DataFrame(rows), pd.DataFrame(ctl)
    if T.empty:
        raise SystemExit("E30 の前後のデータがまだありません")
    agg = lambda D: D.groupby("m").apply(lambda g: pd.Series({"pre": np.average(g["pre"], weights=g["n_pre"]), "post": np.average(g["post"], weights=g["n_post"])}))  # noqa: E731
    TA, CA = agg(T), agg(C)
    did = (TA["post"] - TA["pre"]) - (CA["post"] - CA["pre"])
    n_v = T["jcd"].nunique(); n_t = int(T[T["m"] == "in1c"]["n_post"].sum())
    # カード: 1コースの勝ち(導入した場の前後、まだの場の同じ時期の前後)
    x["is_t"] = False; x["is_c"] = False; x["post_t"] = False; x["post_c"] = False
    for j, d0 in E30.items():
        d0 = pd.Timestamp(d0)
        if d0 + pd.Timedelta(days=30) > end:
            continue
        lo, hi = d0 - pd.Timedelta(days=W), min(d0 + pd.Timedelta(days=W), end)
        m_ = x["dt"].between(lo, hi) & (x["jcd"] == j)
        x.loc[m_, "is_t"] = True; x.loc[m_ & (x["dt"] >= d0), "post_t"] = True
    xc = x.assign(c1=x["in1c"])
    mt = measure(xc, xc["is_t"] & xc["post_t"], ref=xc["is_t"] & ~xc["post_t"])
    mt["ref_label"] = "導入の前90日"
    ms = [("新燃料を入れた場: 導入のあと90日", mt, verdicts(mt))]
    # 場ごとの差(導入した場の前後 − 同じ時期のまだの場の前後)。「10場中◯場」で向きをそろえて見る
    pv = T.pivot(index="jcd", columns="m", values="post") - T.pivot(index="jcd", columns="m", values="pre")
    pc = C.pivot_table(index="jcd", columns="m", values="post") - C.pivot_table(index="jcd", columns="m", values="pre")
    vd = pv - pc.reindex(pv.index)
    up = lambda k: int((vd[k] > 0).sum())  # noqa: E731
    dt_in1 = did["in1c"] * 100
    f_pre, f_post = TA.loc["F", "pre"] * 1000, TA.loc["F", "pre"] * 1000 + did["F"] * 1000
    claim_in1 = TA.loc["in1c", "post"] < 0.50
    in1_w = "ほぼ変わらず" if abs(dt_in1) < 1 else (f"{abs(dt_in1):.1f}ポイント{'へった' if dt_in1 < 0 else 'ふえた'}")
    f_w = (f"1000レースで{f_pre:.0f}回 → {f_post:.0f}回くらい" if abs(f_post - f_pre) >= 0.5 else "ほぼ同じ")
    f_sure = up("F") >= n_v * 0.8 or up("F") <= n_v * 0.2
    st_n = n_v - up("st") if did["st"] < 0 else up("st")
    st_w = "ほぼ同じ" if abs(did["st"]) < 0.005 else (f"平均{abs(did['st']):.3f}秒(約{abs(did['st']) * 2000:.0f}cm分){'早く' if did['st'] < 0 else '遅く'}なった"
                                                     f"({n_v}場中{st_n}場で同じ向き)")
    ex_n = up("ex") if did["ex"] > 0 else n_v - up("ex")
    ex_w = "ほぼ同じ" if abs(did["ex"]) < 0.01 else f"{abs(did['ex']):.2f}秒{'遅く' if did['ex'] > 0 else '速く'}なった({n_v}場中{ex_n}場)"
    mk_w = "ほぼ同じ" if abs(did["mk"] * 100) < 1 else f"{abs(did['mk'] * 100):.1f}ポイント{'増えた' if did['mk'] > 0 else '減った'}"
    return {
        "id": "e30", "title": "新燃料E30で、レースは変わった?",
        "x1": f"新燃料E30のあと、1コースの1着は{_rate(mt['in1'])}。入れる前は{_rate(mt['in1_ref'])}。", "belief": "新しい燃料(E30)になってから、インが弱くなった。フライングも増えた。出足が鈍って、伸びが強くなった",
        "subject": "1コースの艇", "compare": "同じ場の導入前90日",
        "lead": f"2026年4月から順に入った新燃料E30。導入した{n_v}場で『入れる前の90日』と『入れたあとの90日』をくらべ、季節の変化の分は、同じ時期にまだ入れていない場の変化を引いて取りのぞいた。"
                f"1コースの1着率は{in1_w}。スタートのタイミングは{st_w}。フライングは{f_w}({n_v}場中{up('F')}場で増加)。展示タイムは{ex_w}、まくりで決まる割合は{mk_w}。",
        "conclusion": ([f"インは{'少し弱くなった' if dt_in1 <= -1 else '弱くなっていない'}。『50%割れ』も{'本当' if claim_in1 else 'まだない'}",
                        f"季節の分を取りのぞくと、1コースの1着率は{in1_w}。フライングは{f_w}で、{'ほとんどの場で同じ向き' if f_sure else '場によってばらばら(偶然の範囲かも)'}。噂ほど大きな変化ではない(まだ半年分)"]),
        "tables": [], "measures": ms,
        "rules": ["E30: エタノール(植物からつくるアルコール)を30%まぜたガソリン。CO2を減らすため、2026年4月から場ごとに順番に入れている",
                  "季節でレースは変わる(夏は出力が落ちる、など)。だから導入した場の『前と後』から、同じ時期のまだの場の『前と後』を引いて、燃料の分だけを取り出した",
                  "びわこ・大村は2025年から試験的に使っているので外した。導入日は振興会の発表と各場の告知から"],
        "faq": [("フライングは増えた?", f"季節の分を取りのぞいて、{f_w}。{n_v}場のうち増えたのは{up('F')}場。{'少し増えた、と言ってよさそう' if f_sure and did['F'] > 0 else 'はっきり増えたとは言えない(場によって増えたり減ったり)'}"),
                ("出足が鈍って伸びが強くなった?", f"展示タイム(まっすぐ走る速さの目安)は{ex_w}。スタートのタイミングは{st_w}。まくり・まくり差しで決まる割合は{mk_w}。『伸びが強くなった』は数字には出ていない"),
                ("1コースの1着率が50%を割った?", f"導入した場の、入れたあとの1コース1着率は{TA.loc['in1c', 'post'] * 100:.0f}%(入れる前は{TA.loc['in1c', 'pre'] * 100:.0f}%)。季節の分を取りのぞくと{in1_w}。{n_v}場のうち下がったのは{n_v - up('in1c')}場"),
                ("いつまで追いかける?", "導入のあとのデータはまだ半年分。ミカタは毎週、数字を作り直している(この記事も自動で更新される)")],
        "use": ["新燃料の場だからとインを大きく下げる必要は、いまのところない", "スタートがほんの少し早くなった場が多い。展示のSTも、いつもの感覚より少し早めに出ているかも、と見ておくと楽しい"],
        "mikata": "燃料が変わるって、競艇の歴史の中でも大きな出来事。噂を数字で追いかけられるのは、いまだけの楽しみだね",
        "gen": "新しい燃料のエンジン音、ちょっと違うんだよ。……耳じゃ数字は分からねえけどな",
        "challenge": "新燃料を入れたばかりの場の初日、展示タイムがいつもよりばらつくか見てみよう",
        "numbers": {"did": {k: float(v) for k, v in did.items()}, "treated": TA.to_dict(), "control": CA.to_dict(), "venues": n_v, "races_after": n_t,
                    "venue_up": {k: up(k) for k in vd.columns}},
    }


def t_boat(ent, r):
    """ボート(艇)って何が違うの? ボート2連率は意味ある?"""
    x = _adj(ent)
    br = pd.to_numeric(x["boat_2rate"], errors="coerce"); mr = pd.to_numeric(x["motor_2rate"], errors="coerce")
    bt, bl, bm = br >= 42, br <= 26, br.between(31, 37)
    mt, ml_, mm = mr >= 45, mr <= 25, mr.between(30, 36)
    m_bt, m_bl, m_mt, m_ml = measure(x, bt, ref=bm), measure(x, bl, ref=bm), measure(x, mt, ref=mm), measure(x, ml_, ref=mm)
    for m_ in (m_bt, m_bl):
        m_["ref_label"] = "ふつうのボート"
    for m_ in (m_mt, m_ml):
        m_["ref_label"] = "ふつうのモーター"
    ms = [("ボート2連率42%以上", m_bt, verdicts(m_bt)), ("ボート2連率26%以下", m_bl, verdicts(m_bl)), ("(くらべ)モーター2連率45%以上", m_mt, verdicts(m_mt)), ("(くらべ)モーター2連率25%以下", m_ml, verdicts(m_ml))]
    return {
        "id": "boat", "title": "ボートって何が違うの?", "belief": "モーターだけじゃない。ボート(船体)にも当たり外れがある。ボート2連率も見ろ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "compare": SAME,
        "lead": f"本人のふだんとくらべた3着以内は、ボート2連率42%以上で{_pp(m_bt)}、26%以下で{_pp(m_bl)}。モーターは45%以上で{_pp(m_mt)}、25%以下で{_pp(m_ml)}。",
        "conclusion": (["ボートの差は、モーターよりずっと小さい", f"3着以内は、ボート2連率が高いと{_pp(m_bt)}、低いと{_pp(m_bl)}。モーターは高いと{_pp(m_mt)}、低いと{_pp(m_ml)}。ボートは船体なので、性能の差が出にくい"]
                       if abs(m_bt["in1"] - m_bt["in1_ref"]) < abs(m_mt["in1"] - m_mt["in1_ref"]) else ["ボートにも差がある", f"ボート2連率42%以上で、3着以内が{_pp(m_bt)}"]),
        "tables": [], "measures": ms,
        "rules": ["ボート: 選手が乗る船体。モーター: 船体の後ろに付けるエンジン。どちらも節の前日に抽選で選手に割り当てられる",
                  "ボートもモーターも場の持ち物で、年に1回くらい新しくなる。2連率は、そのボート(モーター)で2着以内に入った割合",
                  "数字は、その選手のふだんとくらべた差"],
        "faq": [("ボートで何が変わるの?", "船体の形や重さのちょっとした差、傷み具合。でも同じ規格でつくられているので、エンジンほど差は出ない"),
                ("じゃあボート2連率は見なくていい?", "見なくても困らない。迷ったら、モーター2連率と展示タイムを先に")],
        "use": ["ボート2連率は、モーター・展示のあとで余裕があれば見る、くらいで"],
        "mikata": "ボートは同じ規格の船体だから、差はちょっぴり。主役はやっぱりエンジンと選手だね",
        "gen": "船底の傷まで見えるわけじゃねえからな。俺はボートの番号の語呂で買うことにしてる",
        "challenge": "出走表でボート2連率がいちばん高い選手と低い選手を見つけて、どっちが先にゴールするか見てみよう",
        "numbers": {"boat_top": m_bt["in1"] - m_bt["in1_ref"], "boat_low": m_bl["in1"] - m_bl["in1_ref"], "motor_top": m_mt["in1"] - m_mt["in1_ref"], "motor_low": m_ml["in1"] - m_ml["in1_ref"]},
    }


def t_deme(ent, r):
    """場ごとの代表的な出目は? 前の2年で場の『らしい出目』を選び、最近の1年で本当に多いか・オッズは知っているかを測る。"""
    from kyotei.data import _read
    x = r[r["tri_combo"].astype(str).str.match(r"^[1-6]-[1-6]-[1-6]$")].copy()
    x["tri_combo"] = x["tri_combo"].astype(str)
    early, late = x[~x["late"]], x[x["late"]]
    nat_e, nat_l = early["tri_combo"].value_counts(normalize=True), late["tri_combo"].value_counts(normalize=True)
    nat_all = x["tri_combo"].value_counts(normalize=True)
    sig, rows = {}, []
    for j, g in early.groupby("jcd"):
        vc = g["tri_combo"].value_counts()
        expn = len(g) * nat_e.reindex(vc.index)
        lift_s = ((vc + 10) / (expn + 10)).where(vc >= 20).dropna()   # 回数の少ない出目は1倍に寄せる(偶然の当たりを選ばない)
        sig[j] = lift_s.idxmax()
    for j, g in x.groupby("jcd"):
        s_ = sig.get(j)
        if s_ is None:
            continue
        ga, gb = g[~g["late"]], g[g["late"]]
        top = g["tri_combo"].value_counts(normalize=True)
        le = float((ga["tri_combo"] == s_).mean() / nat_e.get(s_, np.nan))
        ll = float((gb["tri_combo"] == s_).mean() / nat_l.get(s_, np.nan)) if len(gb) else np.nan
        rows.append({"jcd": int(j), "venue": VENUES[int(j)], "n": len(g), "top": top.index[0], "top_r": float(top.iloc[0]),
                     "top2": top.index[1], "top2_r": float(top.iloc[1]), "sig": s_, "sig_r": float((g["tri_combo"] == s_).mean()),
                     "nat_r": float(nat_all.get(s_, np.nan)), "lift_e": le, "lift_l": ll})
    D = pd.DataFrame(rows).sort_values("lift_e", ascending=False)
    keep = D["lift_l"] >= 1.2
    # オッズ: 最近の1年で、その場の『らしい出目』のオッズからの見込み
    o = _read("odds/odds3t_*.csv.gz", None)
    combos = set(sig.values())
    o = o[o["odds"] > 0].copy(); o["race_id"] = o["race_id"].astype(str)
    o["q"] = 1 / o["odds"]; o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
    oq = o[o["combo"].isin(combos)].set_index(["race_id", "combo"])["q"]
    del o
    parts = []
    for j, s_ in sig.items():
        z = late[["race_id", "jcd", "date", "late", "upset"]].copy()
        z["hit"] = (late["tri_combo"] == s_).astype(float)
        z["qh"] = oq.reindex(pd.MultiIndex.from_arrays([z["race_id"], pd.Series(s_, index=z.index)])).values
        z["own"] = z["jcd"] == j
        parts.append(z)
    Z = pd.concat(parts, ignore_index=True)
    m = measure(Z, Z["own"], ref=~Z["own"], col="hit", qcol="qh")
    m["ref_label"] = "同じ出目・ほかの場"
    v = verdicts(m)
    v["real"] = bool(m["in1"] / m["in1_ref"] >= 1.2 and not (m["in1_ci"][0] <= m["in1_ref"] <= m["in1_ci"][1]))
    v["exists"] = "本当にある(ほかの場より多い)" if v["real"] else "ふだんと同じ"
    times = m["in1"] / m["in1_ref"]
    n123 = float(nat_all.get("1-2-3", 0))
    best = D.iloc[0]
    tops = D["top"].value_counts()
    all123 = bool((D["top"] == "1-2-3").all())
    head = ["場", "1-2-3" if all123 else "いちばん多い出目", "らしい出目", "全国の", "最近の1年も多い?"]
    tbl = [[q.venue, f"{_n100(q.top_r, 1000)}回" if all123 else f"{q.top} {_n100(q.top_r, 1000)}回", q.sig, f"{q.lift_e:.1f}倍",
            "○" if q.lift_l >= 1.2 else "–"] for q in D.itertuples()]
    edge_w = {0: "人気どおり(配当はそのぶん安め)", 1: "人気以上に出ている", -1: "人気のわりにひかえめ"}.get(v.get("edge"), "人気とのくらべはデータを集め中")
    exp_ = m["in1"] / m["market_ratio"] * (m.get("market_ref") or 1.0) if m.get("market_ratio") else None
    return {
        "id": "deme", "title": "場ごとの『らしい出目』はある?", "belief": "場には決まった出目がある。この場はこの出目、という『場の顔』がある",
        "subject": "その場のらしい出目", "verb": "出る", "unit": "レース", "per": 1000, "no_market": False,
        "lead": f"3連単は120通り。全国でいちばん多いのは1-2-3で、1000レースで{_n100(n123, 1000)}回。"
                + ("24場すべてで、いちばん多いのも1-2-3。" if int(tops.get('1-2-3', 0)) == len(D) else f"{len(D)}場中{int(tops.get('1-2-3', 0))}場で、いちばん多いのも1-2-3。") +
                f"そこで『全国より何倍よく出るか』で場の顔を探した。前の2年で選んだ出目が、最近の1年でも多かった場は{int(keep.sum())}場。"
                f"いちばん個性が強いのは{best.venue}の{best.sig}(全国の{best.lift_e:.1f}倍)。",
        "conclusion": [("ある。場ごとに『らしい出目』がある" if v["real"] else "場の顔はある。でも、思ったより入れかわる"),
                       f"前の2年で目立った『らしい出目』は、最近の1年もほかの場の{times:.1f}倍出ている。はっきり続いているのは{len(D)}場中{int(keep.sum())}場"
                       f"({'、'.join(f'{q.venue}の{q.sig}' for q in D[keep].sort_values('lift_l', ascending=False).head(3).itertuples())}など)。{edge_w}"],
        "tables": [("場ごとの出目の顔(回数は1000レースあたり。『全国の』は前の2年で全国より何倍出たか)", tbl, head)],
        "measures": [("前の2年で選んだ『らしい出目』→ 最近の1年で出た回数", m, v)],
        "rules": ["3連単の組み合わせは120通り。2023年10月からの全レースで数えた",
                  "『らしい出目』の選び方: 前の2年(2023年10月〜2024年)で、その場での出る回数が全国の何倍かを出し、いちばん倍率の高い出目を選んだ(20回以上出たものだけ。回数の少ない出目は控えめに見積もる)",
                  "選んだあとの『最近の1年』で、本当に多いままかを確かめた。選んだデータと確かめるデータを分けるのは、たまたまの当たりを見抜くため"],
        "faq": [("らしい出目を買えばいい?", f"{edge_w}。よく出る出目は、みんなも知っていれば配当が安い。『場の顔』は、予想の出発点として使うのがおすすめ"),
                ("なぜ場ごとにくせがある?", "水面の広さ、1マークまでの距離、風の向き、潮の満ち引きが関係していると言われる。インが強い場は1号艇の頭、外が伸びる場は外の艇がからむ出目が増えやすい"),
                ("全国で多い出目は?", f"1000レースで、1-2-3が{_n100(n123, 1000)}回、1-3-2が{_n100(float(nat_all.get('1-3-2', 0)), 1000)}回、1-2-4が{_n100(float(nat_all.get('1-2-4', 0)), 1000)}回。上位はどこも1号艇の頭")],
        "use": ["初めて行く場は、まず『らしい出目』を見て、場の性格をつかむ", "場の顔は年で入れかわる。去年のくせより、今節のモーターと選手を優先", "らしい出目は『予想の出発点』。そこから選手とモーターで動かす"],
        "mikata": "出目のくせは、その場の水面と風がつくった『顔』みたいなもの。旅打ちのおみやげ話にもなるよ",
        "gen": "どこの場にも、昔から言われてる出目ってのがあるんだよ。数字で出るとうれしいもんだな",
        "challenge": "次に行く場の『らしい出目』を1つ覚えて、その日の12レースで何回出るか数えてみよう",
        "numbers": {"n123": n123, "times_late": float(times), "keep": int(keep.sum()), "expected_by_odds": exp_,
                    "venues": D[["venue", "top", "sig", "lift_e", "lift_l"]].to_dict("records")},
    }


def t_wind(ent, r):
    """風が強い日はインが弱い? 向きと強さ、どっちが効く? 決まり手は? オッズは知ってる?"""
    DIRS = {"北": 0, "北東": 45, "東": 90, "南東": 135, "南": 180, "南西": 225, "西": 270, "北西": 315}
    NAMES = {v: k for k, v in DIRS.items()}
    x = r.copy()
    x["ang"] = x["wind_dir"].map(DIRS)
    km = pd.to_numeric(x["kimarite"], errors="coerce")
    x["mk"], x["sashi"] = km.isin([3, 4]).astype(float), (km == 2).astype(float)
    calm, strong, gale = x["wind"] <= 2, x["wind"] >= 5, x["wind"] >= 7
    m5, m7 = measure(x, strong, ref=calm), measure(x, gale, ref=calm)
    for m_ in (m5, m7):
        m_["ref_label"] = "風2m以下"
    mw = measure(x, x["wave"] >= 5, ref=x["wave"] <= 2); mw["ref_label"] = "波2cm以下"
    # 場と季節をそろえる(場×月の平均からのずれ)
    mon = pd.to_datetime(x["date"]).dt.month
    dev = x["c1"] - x.groupby(["jcd", mon])["c1"].transform("mean")
    adj = float(dev[strong].mean() - dev[calm].mean()) * 100
    # 場ごと: 風5m以上と2m以下の差。前の2年と最近の1年で、風に弱い場の顔ぶれは同じか
    pv = (x[strong].groupby("jcd")["c1"].mean() - x[calm].groupby("jcd")["c1"].mean())
    n_low = int((pv < 0).sum())
    ha = x[~x["late"]]; hb = x[x["late"]]
    da = ha[ha["wind"] >= 5].groupby("jcd")["c1"].mean() - ha[ha["wind"] <= 2].groupby("jcd")["c1"].mean()
    db = hb[hb["wind"] >= 5].groupby("jcd")["c1"].mean() - hb[hb["wind"] <= 2].groupby("jcd")["c1"].mean()
    corr = float(pd.concat([da, db], axis=1).corr().iloc[0, 1])
    ns = x[strong].groupby("jcd").size()
    tbl = []
    for j in pv.sort_values().index:
        g = x[x["jcd"] == j]
        tbl.append([VENUES[int(j)], _rate(g.loc[g['wind'] <= 2, 'c1'].mean()), _rate(g.loc[g['wind'] >= 5, 'c1'].mean()),
                    _diff_words({"in1": g.loc[g["wind"] >= 5, "c1"].mean(), "in1_ref": g.loc[g["wind"] <= 2, "c1"].mean()}, "勝つ"), f"{int(ns.get(j, 0)):,}"])
    # 決まり手(風の強さ別)
    wb = pd.cut(x["wind"], [-1, 2, 4, 6, 99], labels=["2m以下", "3〜4m", "5〜6m", "7m以上"])
    kt = x.groupby(wb, observed=True).agg(n=("c1", "size"), in1=("c1", "mean"), mk=("mk", "mean"), sashi=("sashi", "mean"))
    ktbl = [[str(k), f"{_rate(q.in1)}", f"{_rate(q.mk)}", f"{_rate(q.sashi)}", f"{int(q.n):,}"] for k, q in kt.iterrows()]
    # 向き: 前の2年で場ごとに「インが弱い向き/強い向き」(風3m以上)を選び、最近の1年で確かめる
    early, late = x[~x["late"]], x[x["late"]]
    keep_dir, n_dir = 0, 0
    for j, g in early.groupby("jcd"):
        s_ = g[(g["wind"] >= 3) & g["ang"].notna()]
        t_ = s_.groupby("ang")["c1"].agg(["size", "mean"])
        t_ = t_[t_["size"] >= 40]
        if len(t_) < 2:
            continue
        sh = (t_["mean"] * t_["size"] + s_["c1"].mean() * 30) / (t_["size"] + 30)
        w_, b_ = sh.idxmin(), sh.idxmax()
        gl = late[(late["jcd"] == j) & (late["wind"] >= 3)]
        a_, c_ = gl[gl["ang"] == w_]["c1"], gl[gl["ang"] == b_]["c1"]
        if len(a_) >= 30 and len(c_) >= 30:
            n_dir += 1; keep_dir += int(a_.mean() < c_.mean())
    # 向きのくせ全体: 場×8方位(風3m以上)の「その場の強風の平均からのずれ」が、前の2年と最近の1年で似ているか
    cells = []
    for h_, part in ((0, early), (1, late)):
        s_ = part[(part["wind"] >= 3) & part["ang"].notna()]
        g_ = s_.groupby(["jcd", "ang"])["c1"].agg(["size", "mean"])
        g_["dev"] = g_["mean"] - s_.groupby("jcd")["c1"].mean().reindex(g_.index.get_level_values(0)).values
        cells.append(g_[g_["size"] >= 40]["dev"].rename(h_))
    cc = pd.concat(cells, axis=1).dropna()
    corr_dir = float(cc[0].corr(cc[1])) if len(cc) > 20 else float("nan")
    d5 = (m5["in1"] - m5["in1_ref"]) * 100
    v5 = verdicts(m5)
    edge_w = {-1: "しかも、風の日の1号艇は人気のわりにひかえめ", 0: "人気どおり(みんな知っている)",
              1: "しかも人気以上に来ている"}.get(v5.get("edge"), "")
    mk_c, mk_g = kt["mk"].iloc[0] * 100, kt["mk"].iloc[-1] * 100
    sa_c, sa_g = kt["sashi"].iloc[0] * 100, kt["sashi"].iloc[-1] * 100
    return {
        "id": "wind", "title": "風が強い日は、インが弱い?", "belief": "風が強い日はインが危ない。向かい風ならまくり、追い風なら差し。風向きを見れば分かる",
        "subject": "1号艇", "compare": "風2m以下",
        "lead": f"風2m以下のレースでは、1号艇が勝つのは{_rate(m5['in1_ref'])}。風5m以上だと{_rate(m5['in1'])}、7m以上だと{_rate(m7['in1'])}まで減る。"
                f"場と季節をそろえても{abs(adj):.0f}ポイントほど低く、24場中{n_low}場で同じ向き。{edge_w}。"
                f"いっぽう『この場はこの風向きでインが弱い』は、前の2年で選んだ向きが最近の1年も弱かったのが{n_dir}場中{keep_dir}場。向きより、まず強さ。",
        "conclusion": [f"本当。風が強いほどインは弱い。{'しかも人気のわりにひかえめ' if v5.get('edge') == -1 else ''}",
                       f"風5m以上で1号艇の勝ちは{_rate_change(m5['in1'], m5['in1_ref'], ref_label='風2m以下の')}。決まり手は、まくりが{mk_c:.0f}%→{mk_g:.0f}%、差しが{sa_c:.0f}%→{sa_g:.0f}%に増える(7m以上)。風向きのくせは年で入れかわりやすい"],
        "tables": [("風の強さと決まり手(%)", ktbl, ["風", "1号艇の1着", "まくり・まくり差し", "差し", "レース数"]),
                   ("場ごとの、風に弱いイン(1号艇が勝つ回数/100レース)", tbl, ["場", "風2m以下", "風5m以上", "差", "5m以上のレース"])],
        "measures": [("風5m以上", m5, v5), ("風7m以上", m7, verdicts(m7)), ("波5cm以上(波2cm以下とくらべて)", mw, verdicts(mw))],
        "rules": ["風速と波の高さは、公式の競走成績に載るレース時の記録。風速はm(メートル毎秒)、波はcm",
                  "強い風は、ボートの浮き上がりや、1マークでの流れ方に効くと言われる。インの艇は風を正面から受けやすい",
                  "『場と季節をそろえて』は、同じ場・同じ月の平均からのずれでくらべたということ(風の強い場・季節がもともとインが弱い、という見かけの差を取りのぞく)",
                  "風向きは公式記録の8方位。場ごとに水面の向きがちがうので、『追い風・向かい風』ではなく方位のままで調べた"],
        "faq": [("向かい風はまくり、追い風は差し?", f"風が強くなると、まくりも差しも両方増える。場ごとの風向きのくせは、前の2年と最近の1年で{sim_words(corr_dir)}。"
                                                 f"『いちばんインが弱い向き』を1つ選んでも、最近の1年でも弱かったのは{n_dir}場中{keep_dir}場。向きは参考ていど、まずは強さ"),
                ("どの場がいちばん風に弱い?", f"結果の表のとおり。風に弱い場の顔ぶれは、前の2年と最近の1年で{sim_words(corr)}"),
                ("波は?", f"波5cm以上だと、1号艇の勝ちは{_rate(mw['in1'])}(波2cm以下は{_rate(mw['in1_ref'])})。波は風といっしょに高くなるので、風と波は同じ話の表と裏"),
                ("風の日の人気は?", f"風が強いと1号艇の人気は少し下がる。でも、下がり方が足りない。風5m以上だと、人気から考えると1号艇の勝ちは{_rate(m5['in1'] / m5['market_ratio'] * (m5.get('market_ref') or 1.0)) if m5.get('market_ratio') else '-'}、実際は{_rate(m5['in1'])}")],
        "use": ["直前情報の風速が5mを超えたら、1号艇の頭は少し疑ってみる", "強風の日は、まくり屋と差し屋の両方に出番。2〜4号艇の型を見る",
                "風向きのくせは年で入れかわる。去年の『この風ならこの出目』より、今日の風の強さ"],
        "mikata": "風の日は、展示から目が離せない。旗のなびき方を見て『今日は荒れるぞ』って構えるの、現地ならではの楽しみだね",
        "gen": "風の日の水面はな、白い波がキラキラして、それだけでドキドキするんだよ。インの選手はいちばん怖いはずさ",
        "challenge": "次の風の強い日、場内の旗を見て風速を当ててみよう。直前情報と答え合わせ。5mを超えたら1号艇の頭を疑う日",
        "numbers": {"adj": adj, "venues_lower": n_low, "corr_half": corr, "dir_keep": [keep_dir, n_dir], "corr_dir": corr_dir,
                    "kimarite": kt.reset_index().astype({"wind": str}).to_dict("records")},
    }


def t_exst(ent, r):
    """スタート展示のSTは、本番の参考になる? 今日の展示がいつもより速いと? 人ごとのずれは?"""
    x = _adj(ent).sort_values(["racer_id", "date", "rno"])
    ex = x["ex_st"].where(x["ex_st"].between(-0.3, 0.6))
    st = x["st"].where(x["st"].between(0, 0.6) & (x["st_flag"] != "F"))
    g = x["racer_id"]
    roll = lambda q: q.groupby(g).transform(lambda s_: s_.shift(1).rolling(60, min_periods=20).mean())  # noqa: E731
    x["ex_dev"], x["st_dev"] = ex - roll(ex), st - roll(st)
    fast, usual, slow = x["ex_dev"] <= -0.05, x["ex_dev"].abs() < 0.02, x["ex_dev"] >= 0.05
    mf, msl = measure(x, fast, ref=usual), measure(x, slow, ref=usual)
    for m_ in (mf, msl):
        m_["ref_label"] = "いつもどおりの展示"
        m_["subject"], m_["verb"] = "その選手", "3着以内に入る"
    sd_f, sd_u, sd_s = (float(x.loc[k, "st_dev"].mean()) for k in (fast, usual, slow))
    ok = x["ex_dev"].notna() & x["st_dev"].notna()
    c_day = float(x.loc[ok, "ex_dev"].corr(x.loc[ok, "st_dev"]))
    # 展示→本番のずれ(人ごと)。奇数月と偶数月で同じ人は同じずれか
    d = (st - ex)
    mon = x["dt"].dt.month
    o = d[mon % 2 == 1].groupby(g[mon % 2 == 1]).agg(["size", "mean"]); v_ = d[mon % 2 == 0].groupby(g[mon % 2 == 0]).agg(["size", "mean"])
    j = o.join(v_, lsuffix="_o", rsuffix="_e", how="inner"); j = j[(j["size_o"] >= 40) & (j["size_e"] >= 40)]
    c_person = float(j["mean_o"].corr(j["mean_e"]))
    d_all = float(d.mean())
    pq = j[["mean_o", "mean_e"]].mean(axis=1)
    lo_, hi_ = float(pq.quantile(0.1)), float(pq.quantile(0.9))
    # 展示でいちばん速かった艇は、本番でもいちばん速い?
    e2 = ent[ent["ex_st"].notna() & ent["st"].between(0, 0.6) & (ent["st_flag"] != "F")].copy()
    e2["exr"] = e2.groupby("race_id")["ex_st"].rank(method="min")
    e2["str_"] = e2.groupby("race_id")["st"].rank(method="min")
    p11 = float((e2.loc[e2["exr"] == 1, "str_"] == 1).mean())
    # オッズ: 展示STいちばんの3・4号艇は、人気ほど来る?(レース単位)
    er = ent[ent["ex_st"].notna()].copy()
    er["exr"] = er.groupby("race_id")["ex_st"].rank(method="min")
    parts = []
    for k in (3, 4):
        rk = er[er["lane"] == k].drop_duplicates("race_id").set_index("race_id")["exr"]
        z = r[["race_id", "date", "late", "upset", "jcd"]].copy()
        z["exr"] = r["race_id"].map(rk).values
        z["w"] = (r["win_lane"] == k).astype(float).values
        z["q"] = r[f"q_l{k}"].values
        parts.append(z)
    Z = pd.concat(parts, ignore_index=True)
    m34 = measure(Z, Z["exr"] == 1, ref=Z["exr"] > 1, col="w", qcol="q")
    m34.update({"ref_label": "展示STがいちばんではない", "subject": "その艇", "verb": "1着になる"})
    v34 = verdicts(m34)
    over = v34.get("edge") == -1
    return {
        "id": "exst", "title": "スタート展示のSTは信じていい?", "belief": "スタート展示でSTが速かった選手は、本番も速い。展示を見れば今日の調子が分かる",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": False, "unit": "走",
        "lead": f"本番のSTは、展示より平均{d_all:.2f}秒遅い(展示はフライングしても罰がないので、みんな攻める)。"
                f"では、今日の展示がその人のいつもより0.05秒以上速かったら? 本番のSTは{abs(sd_f - sd_u) * 1000:.0f}/1000秒しか変わらず、3着以内に入る回数も{_diff_words(mf, '3着以内に入る')}。"
                f"今日の展示STは、本番の調子の目安にはほとんどならない。いっぽう『展示から本番へのずれ』は人ごとにほぼ決まっていて、時期を変えても{sim_words(c_person)}。"
                + ("それなのに、展示STがいちばん速い3・4号艇の1着は、人気のわりにひかえめ。" if over else ""),
        "conclusion": ["ほぼウソ。今日の展示STより、その人の『いつものずれ』", f"今日の展示がいつもより速くても、本番のSTはほとんど変わらない。見るべきは、展示から本番へ何秒ずれる人か(人ごとにほぼ決まっている)。"
                       + ("展示STの速さに、みんな少し引っぱられすぎ" if over else "")],
        "tables": [],
        "measures": [("今日の展示が、いつもより0.05秒以上速い", mf, verdicts(mf)), ("今日の展示が、いつもより0.05秒以上遅い", msl, verdicts(msl)),
                     ("展示STがいちばん速かった3・4号艇(1着)", m34, v34)],
        "rules": ["スタート展示: 本番の前に、本番と同じようにスタートを試す。ここでのフライングは罰がないので、本番より攻めた数字が出やすい",
                  "『いつもの展示』は、その選手の直前60回の展示STの平均(20回以上ある人だけ)。そこからのずれで『今日は速い・遅い』を決めた",
                  "結果のカードの上2つは『その選手のふだんの3着以内』とくらべている(コースの有利不利も差し引き)。3つめはレース単位で、人気とくらべた"],
        "faq": [("展示でいちばん速かった艇は、本番でもいちばん速い?", f"{fun_rate(p11)}({_rate(p11)})。でたらめなら6回に1回なので、少しは当たる。でもそれは『もともとスタートが速い人』が展示でも速いから"),
                ("じゃあ展示STは見なくていい?", f"『人ごとのずれ』で直して見るのが正解。本番が展示より{lo_:.2f}秒遅いだけの人もいれば、{hi_:.2f}秒遅い人もいる(真ん中の8割)。ミカタの予想は、この『人ごとのずれ』を使って本番のSTを見積もっている"),
                ("展示でフライングした人は?", "展示のフライングは罰がない。本番のSTも、本番でフライングする率も、ほかの人とほとんど同じだった")],
        "use": ["今日の展示STが『いつもより速い・遅い』は気にしすぎない。その人のいつもの本番STと、展示から本番へのずれで見る",
                "展示STがいちばん速い外の艇に飛びつかない。人気になっているぶん、配当とのバランスを見る"],
        "mikata": "展示のSTって、見ていていちばんワクワクするところ。だからこそ、数字の正体を知っておくともっと楽しいよ",
        "gen": "展示でピタッと決めると、こっちまで『今日は来る!』って思っちまうんだよなあ。……まあ、ほどほどにしとくか",
        "challenge": "次のレースで、展示STがいちばん速い艇を予想してから展示を見よう。そのあと本番のSTと答え合わせ。ずれる人、ずれない人を見つけよう",
        "numbers": {"d_all": d_all, "c_day": c_day, "c_person": c_person, "p11": p11, "st_dev": [sd_f, sd_u, sd_s], "q10_90": [lo_, hi_]},
    }


def _motor_renewals(ent):
    """場ごとの新モーターの初日(その日の出走表で、モーター2連率がほぼ全部0%になった日)。"""
    e = ent[["date", "jcd", "motor_2rate"]].copy()
    e["m"] = pd.to_numeric(e["motor_2rate"], errors="coerce")
    d = e.groupby(["jcd", "date"])["m"].agg(mean="mean", zero=lambda q: (q == 0).mean()).reset_index().sort_values(["jcd", "date"])
    d["prev"] = d.groupby("jcd")["mean"].shift(1)
    ren = d[(d["zero"] >= 0.95) & (d["prev"] > 20)][["jcd", "date"]].copy()
    ren["rd"] = pd.to_datetime(ren["date"])
    return ren


def t_newmotor(ent, r):
    """新モーター、2連率はいつから信じていい? 新モーターの直後は荒れる?"""
    ren = _motor_renewals(ent).sort_values("rd")
    x = _adj(ent).sort_values("dt")
    x["m"] = pd.to_numeric(x["motor_2rate"], errors="coerce")
    x = pd.merge_asof(x, ren[["jcd", "rd"]], left_on="dt", right_on="rd", by="jcd", direction="backward")
    x["since"] = (x["dt"] - x["rd"]).dt.days
    y = x[x["m"] > 0].copy()
    y["pct"] = y.groupby(["jcd", "date"])["m"].rank(pct=True)
    top, bot = y["pct"] >= 0.8, y["pct"] <= 0.2
    pers = [("新モーターから8〜14日(2節目)", y["since"].between(7, 14)), ("15〜30日", y["since"].between(15, 30)), ("4か月より後", y["since"] > 120)]
    ms = []
    for nm, pm in pers:
        m_ = measure(y, top & pm, ref=bot & pm)
        m_["ref_label"] = "2連率が下位2割"
        ms.append((f"{nm}: 2連率が上位2割のモーター", m_, verdicts(m_)))
    zero1 = float((x.loc[x["since"].between(0, 6), "m"] == 0).mean())
    # 新モーターの直後は荒れる?(場と季節をそろえて)
    r2 = r.copy(); r2["dt"] = pd.to_datetime(r2["date"])
    r2 = pd.merge_asof(r2.sort_values("dt"), ren[["jcd", "rd"]], left_on="dt", right_on="rd", by="jcd", direction="backward")
    r2["since"] = (r2["dt"] - r2["rd"]).dt.days
    mon = r2["dt"].dt.month
    dev = r2["c1"] - r2.groupby(["jcd", mon])["c1"].transform("mean")
    new_dev = float(dev[r2["since"].between(0, 30)].mean()) * 100
    # 場ごとの、新モーターの時期(毎年だいたい何月)
    ren["mon"] = ren["rd"].dt.month
    tbl = []
    for j, g in ren.groupby("jcd"):
        last = g["rd"].max()
        tbl.append([VENUES[int(j)], f"{int(g['mon'].mode().iloc[0])}月ごろ", last.strftime("%Y年%-m月%-d日")])
    tbl.sort(key=lambda q: int(q[1].split("月")[0]))
    d_early, d_mid, d_late = ((m_["in1"] - m_["in1_ref"]) * 100 for _, m_, _ in ms)
    return {
        "id": "newmotor", "title": "新モーター、2連率はいつから信じていい?", "belief": "新モーターになったばかりのころは、2連率なんて当てにならない。しばらくは荒れる",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True,
        "lead": f"どの場も1年に1回、モーターを全部入れかえる。最初の1週間は、出走表のモーター2連率が{fun_rate(zero1)}0%(まだ走っていない)。"
                f"2節目(8〜14日)は、2連率が上位2割のモーターと下位2割の差が、3着以内で{abs(d_early):.0f}ポイントほど。"
                f"2週間をすぎると{abs(d_mid):.0f}ポイント、4か月より後は{abs(d_late):.0f}ポイント。つまり、2週間たてば、もうベテランのモーターと同じくらい信じていい。"
                f"新モーター直後の1か月、1号艇の勝ちは場と季節をそろえて{'ほぼ同じ' if abs(new_dev) < 1 else _dw(new_dev)}。荒れるわけではない。",
        "conclusion": ["半分本当。2週間だけ待って", f"2節目までは2連率の差がほとんど出ない。2週間をすぎれば、上位と下位の差は{abs(d_mid):.0f}ポイントほどになり、半年後と変わらない。新モーターだから荒れる、はない"],
        "tables": [("場ごとの新モーターの時期(このデータで見つけた入れかえ日)", tbl, ["場", "毎年", "いちばん最近"])],
        "measures": ms,
        "rules": ["モーター2連率: そのモーターが2着までに入った割合。新モーターになると0%から数えなおす",
                  "新モーターの初日は、出走表のモーター2連率がほぼ全部0%になった日として見つけた",
                  "結果は『その選手のふだんの3着以内』とくらべた差(コースの有利不利も差し引き)。2連率は同じ日・同じ場のモーターの中での順位で、上位2割・下位2割に分けた"],
        "faq": [("2節目は、なぜ当てにならない?", "まだ1節ぶん(6〜8走)しか走っていないから。たまたま強い選手が乗ったモーターも上位に来てしまう"),
                ("新モーターの最初の節は何を見る?", "2連率は0%なので、展示タイムと、選手のいつもの力。検証ラボ『モーター2連率は信じていい?』では、今日の展示のほうが2連率より効いていた"),
                ("新モーターの時期は?", "結果の表のとおり。場ごとにだいたい毎年同じ月")],
        "use": ["新モーターから2週間は、2連率より展示タイムと選手の力で考える", "2週間をすぎたら、2連率を素直に使ってよい"],
        "mikata": "新モーターの初下ろしって、ちょっとお祭りみたい。どのモーターが『当たり』か、みんなで探す2週間がいちばん楽しいかも",
        "gen": "新ペラ・新モーターの季節はな、整備士さんたちも大忙しなんだ。2週間で数字が落ちつくってのは、なるほどな",
        "challenge": "新モーターになったばかりの場を1つ選んで、2週間ごとに上位のモーター番号をメモしよう。『当たり』が固まっていくのが見える",
        "numbers": {"zero1": zero1, "new_dev": new_dev, "diffs": [d_early, d_mid, d_late], "renewals": int(len(ren))},
    }


def t_rokuyo(ent, r):
    """大安は堅い? 仏滅は荒れる? 友引は?(六曜。旧暦は kyotei.koyomi で計算)"""
    from kyotei.koyomi import ROKUYO, rokuyo
    x = r.copy()
    ds = pd.to_datetime(x["date"])
    mp = {d: rokuyo(d.date()) for d in ds.drop_duplicates()}
    x["rk"] = ds.map(mp)
    x["pay"] = pd.to_numeric(x["tri_pay"], errors="coerce")
    ma, mb = measure(x, x["rk"] == "大安", ref=x["rk"] != "大安"), measure(x, x["rk"] == "仏滅", ref=x["rk"] != "仏滅")
    # 6つの六曜で、いちばん強い日とよわい日の差は偶然でも出る? 日ごとに六曜をシャッフルして確かめる(同じ日のレースはまとめて動かす)
    day = x.assign(d=ds).groupby("d").agg(s=("c1", "sum"), n=("c1", "size"), l=("rk", "first")).reset_index()
    def _rng(lbl):
        g_ = day.assign(l=lbl).groupby("l")[["s", "n"]].sum()
        v_ = g_["s"] / g_["n"]
        return float(v_.max() - v_.min())
    obs = _rng(day["l"].values)
    rs = np.random.default_rng(0)
    p_perm = float(np.mean([_rng(rs.permutation(day["l"].values)) >= obs for _ in range(1000)]))
    halves = {k: x[x["late"] == k].groupby("rk")["c1"].mean() for k in (False, True)}
    same_top = halves[False].idxmax() == halves[True].idxmax()
    same_bot = halves[False].idxmin() == halves[True].idxmin()
    odd = p_perm <= 0.05
    mu = measure(x, x["rk"] == "仏滅", ref=x["rk"] != "仏滅", col="upset", qcol="_none")
    mt = measure(x, x["rk"] == "友引", ref=x["rk"] != "友引", col="upset", qcol="_none")
    for m_ in (ma, mb, mu, mt):
        m_["ref_label"] = "ほかの日"
    for m_ in (mu, mt):
        m_["subject"], m_["verb"] = "万舟", "出る"
    g = x.groupby("rk").agg(n=("c1", "size"), in1=("c1", "mean"), up=("upset", "mean"), pay=("pay", "median"))
    order = ["先勝", "友引", "先負", "仏滅", "大安", "赤口"]
    tbl = [[k, _rate(g.loc[k, 'in1']), _rate(g.loc[k, 'up']), f"{g.loc[k, 'pay']:,.0f}円", f"{int(g.loc[k, 'n']):,}"] for k in order if k in g.index]
    vs = [verdicts(m_) for m_ in (ma, mb, mu, mt)]
    lo, hi = g["in1"].idxmin(), g["in1"].idxmax()
    mh = measure(x, x["rk"] == hi, ref=x["rk"] != hi); mh["ref_label"] = "ほかの日"
    one_in = max(int(round(1 / max(p_perm, 0.001))), 2)
    return {
        "id": "rokuyo", "title": "大安は堅い? 仏滅は荒れる?", "belief": "大安の日は本命が来る。仏滅は荒れる。友引は……友を引くから、2着も同じ型の選手が来る",
        "subject": "1号艇", "compare": "ほかの日",
        "lead": f"カレンダーの六曜(大安・仏滅など)ごとに、2023年10月からの{len(x):,}レースを数えた。1号艇が勝つのは、大安で{_rate(ma['in1'])}、仏滅で{_rate(mb['in1'])}。"
                f"万舟(3連単で30番人気より下)は、仏滅で{_rate(mu['in1'])}、ほかの日で{_rate(mu['in1_ref'])}。"
                + (f"ところが、いちばん1号艇が強い{hi}({g.loc[hi, 'in1'] * 100:.1f}%)と、いちばん弱い{lo}({g.loc[lo, 'in1'] * 100:.1f}%)の差は、"
                   f"偶然なら{one_in}回に1回しか出ない大きさ。" + ("しかも前の2年も最近の1年も同じ顔ぶれ。" if same_top and same_bot else "") +
                   "理由は見つからない(月の満ち欠け・節の何日目・レース番号をそろえても残る)。"
                   if odd else f"いちばん1号艇が強いのは{hi}、弱いのは{lo}だけど、その差は偶然でも出る大きさ。"),
        "conclusion": ([f"ほぼ同じ。でも{hi}だけ、ちょっと気になる", f"大安も仏滅も、ほかの日とほぼ同じ。ただ{hi}と{lo}の差({abs(g.loc[hi, 'in1'] - g.loc[lo, 'in1']) * 100:.1f}ポイント)は偶然では出にくい。"
                        "ミカタはこれまで10個以上のオカルトを試したので、1つくらい偶然で当たることもある。来年も同じか、追試中"] if odd else
                       ["ふだんと同じ。六曜は水面を気にしない", f"大安も仏滅も、1号艇の勝ちも万舟も、ほかの日と同じ。でも、大安の日にちょっといい気分で舟券を買うのは、それはそれで楽しい"]),
        "tables": [("六曜ごとの成績(%。配当は3連単の真ん中の値)", tbl, ["六曜", "1号艇の1着", "万舟", "3連単の配当", "レース数"])],
        "measures": ([(hi, mh, verdicts(mh))] if hi not in ("大安", "仏滅") else []) + [("大安", ma, vs[0]), ("仏滅", mb, vs[1]), ("仏滅の万舟", mu, vs[2]), ("友引の万舟", mt, vs[3])],
        "rules": ["六曜: 先勝・友引・先負・仏滅・大安・赤口の6つ。旧暦の月と日の数で決まる(旧暦の1月1日は先勝、のように)",
                  "旧暦は、月の満ち欠け(新月の日が1日)と太陽の動きから、ミカタが自分で計算した(市販のカレンダーと照らし合わせ済み)",
                  "万舟: 3連単の払戻しが1万円以上の大穴。ここでは『3連単で30番人気より下』で数えた"],
        "faq": [("なぜ大安と仏滅?", "大安は『大いに安し』で何をしてもよい日、仏滅は何事もよくない日、と昔から言われる。結婚式の日取りでいまも気にする人は多い"),
                ("友引は?", f"友引の万舟は{_rate(mt['in1'])}(ほかの日は{_rate(mt['in1_ref'])})。友を引っぱって大穴が来る、ということもなかった"),
                ("赤口は?", "赤口は正午だけ吉、と言われる日。" + (f"なのに、六曜でいちばん1号艇が勝っていたのは{hi}。オカルトはわからない" if odd and hi == "赤口" else "ナイターの多い今の競艇には、ちょっと気の毒な日")),
                ("偶然かどうか、どうやって確かめた?", "日ごとの六曜を1000回シャッフルして、同じくらいの差が出る回数を数えた。同じ日のレースはまとめて動かしている(その日の水面のくせを、六曜のせいにしないため)")],
        "use": ["六曜で予想を変える必要はない。でも『今日は大安だから本命』と決めて遊ぶのは、立派な楽しみ方", "負けた日を仏滅のせいにするのは、数字的にはぬれぎぬ"],
        "mikata": "六曜は水面には関係なかった。でも、大安の朝にちょっと背すじが伸びる感じ、わたしは好きだよ",
        "gen": ("赤口が強いだって? ほらみろ、暦は生きてるんだよ! ……追試中? わかったわかった、来年まで黙っとく" if odd and hi == "赤口" else
                "俺は大安の日しか遠征しないって決めてるんだ。……数字は関係ないって? いいんだよ、気分が大事なんだ"),
        "challenge": "次の大安の日に、1号艇から1点だけ買ってみよう。仏滅の日には、思いきって万舟を1点。どっちが楽しかったか、自分の記録をつけよう",
        "p_perm": p_perm, "same_halves": [bool(same_top), bool(same_bot)],
        "numbers": {k: {"n": int(g.loc[k, "n"]), "in1": float(g.loc[k, "in1"]), "up": float(g.loc[k, "up"]), "pay": float(g.loc[k, "pay"])} for k in g.index},
    }


def t_name(ent, r):
    """名前に『勝』が入る選手は勝つ? 水の字は水面と相性がいい?(名前は出走表に載る公開情報。人の名前は出さず、まとめた数字だけ)"""
    x = _adj(ent)
    x["age"] = pd.to_numeric(x["age"], errors="coerce")
    x["ab"] = pd.cut(x["age"], [0, 25, 30, 35, 40, 45, 50, 55, 80])
    x["cres"] = x["res"] - x.groupby("racer_class")["res"].transform("mean")                       # コースと級をそろえた3着以内のずれ
    x["cares"] = x["res"] - x.groupby(["racer_class", "ab"], observed=True)["res"].transform("mean")  # さらに年齢もそろえる
    nm = x["racer_name"].astype(str)
    groups = [("勝", "勝"), ("水の字(海・波・川・湖・沢など)", "[海波浪洋湊汐潮渚港湖河川水泳流澄渡沢池泉浜津]"), ("舟の字(舟・船・航・帆・艇)", "[舟船航帆艇]"),
              ("龍・竜", "[龍竜]"), ("翔・飛", "[翔飛]")]
    base_ = float(x["top3"].mean())
    age_all = float(x.groupby("racer_id")["age"].mean().mean())
    rs = np.random.default_rng(0)
    ms, tbl, info = [], [], {}
    for label, pat in groups:
        mk = nm.str.contains(pat)
        per = x[mk].groupby("racer_id").agg(n=("cares", "size"), v=("cares", "mean"), v0=("cres", "mean"), age=("age", "mean"))
        if len(per) < 5:
            continue
        w = per["n"].values
        v = float(np.average(per["v"], weights=w)); v0 = float(np.average(per["v0"], weights=w))
        bt = [np.average(per["v"].values[i], weights=w[i]) for i in [rs.integers(0, len(per), len(per)) for _ in range(500)]]
        ha = x[mk & ~x["late"]]["cares"].mean(); hb = x[mk & x["late"]]["cares"].mean()
        m_ = {"n": int(mk.sum()), "in1": base_ + v, "in1_ref": base_, "upset": 0.0, "upset_ref": 0.0,
              "in1_ci": [base_ + float(np.quantile(bt, 0.05)), base_ + float(np.quantile(bt, 0.95))], "half": [float(ha), float(hb)],
              "ref_label": "名前に入っていない人"}
        ms.append((f"名前に『{label.split('(')[0]}』({len(per)}人)", m_, verdicts(m_)))
        dd = lambda q: "ほぼ同じ" if abs(q) < 0.005 else f"{abs(q) * 100:.1f}%{'多い' if q > 0 else '少ない'}"  # noqa: E731
        tbl.append([label, f"{len(per)}人", f"{per['age'].mean():.0f}歳", dd(v0), dd(v)])
        info[label] = {"people": int(len(per)), "age": float(per["age"].mean()), "class_adj": v0, "class_age_adj": v}
    any_real = any(v_["real"] for _, _, v_ in ms)
    sho = info.get("翔・飛", {})
    return {
        "id": "name", "title": "名前に『勝』が入る選手は、勝つ?", "belief": "名前に『勝』の字がある選手は勝負強い。水の字は水面と相性がいい。龍は水の神さまだから強い",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True,
        "lead": f"出走表の選手名を字で分けて、コースの有利不利と級(A1〜B2)をそろえて3着以内に入る回数をくらべた。"
                f"『勝』の字が入る{info.get('勝', {}).get('people', 0)}人は、ほかの人と{_diff_words(ms[0][1], 'x') if ms else '-'}。水の字も、舟の字も、龍も、ほぼ同じ。"
                + (f"ひとつおもしろいのは『翔・飛』。級をそろえると3着以内が{sho['class_adj'] * 100:.1f}ポイント高いけれど、平均{sho['age']:.0f}歳と若い(全体は{age_all:.0f}歳)。"
                   f"年齢もそろえると{sho['class_age_adj'] * 100:.1f}%で、偶然の範囲。名前の流行りが、世代を映していた。" if sho else ""),
        "conclusion": (["ちょっと差がある。でも追試中", "名前で差が出たけれど、理屈はない。来年も同じか追いかける"] if any_real else
                       ["ふだんと同じ。名前より、スタートとターン", "『勝』も水の字も龍も、ほかの人と同じだけ3着に入っている。『翔』が少し強く見えるのは、若い人に多い名前だから"]),
        "tables": [("名前の字ごとのまとめ(3着以内の差、ポイント)", tbl, ["名前の字", "人数", "平均年齢", "級をそろえると", "年齢もそろえると"])],
        "measures": ms,
        "rules": ["名前は出走表に載る登録名(名字も入る。『川』の字の名字の人も水の字に入る)。この記事では、まとめた数字だけを出し、個人の名前は出さない",
                  "くらべ方: コース(1〜6コース)の有利不利と級を差し引いた『3着以内に入る回数のずれ』を、名前にその字がある人とない人でくらべた",
                  "人数が少ないので、『偶然かどうか』は人を入れかえて何度も引き直して確かめた(同じ人の何百走をまとめて動かす)"],
        "faq": [("なぜ『翔』は若い人に多い?", "『翔太』は平成の30年間でいちばん多くつけられた男の子の名前(明治安田生命の名前調査)。『翔』の字は1990年代から人気で、いまの20〜30代に多い"),
                ("じゃあ若い人は強い?", "同じ級の中なら、若い人ほど伸びざかりで少し上(検証ラボ『ボートレーサーは何歳がいちばん強い?』)。名前ではなく、年齢の話だった"),
                ("自分の名前に『勝』があるけど?", "舟券の当たりやすさも、たぶん関係ない。でも勝の字の選手を応援すると、ちょっと気合いが入るよね")],
        "use": ["名前で舟券を選ぶのは、数字的には意味がない。でも『推しの字』を決めて応援するのは、立派な楽しみ方",
                "若い選手が多いレースは、級の数字より少し強めに見てもいい(年齢の記事を参照)"],
        "mikata": "名前の字で強さは変わらなかった。でも『翔』の話みたいに、数字の裏から世代が見えてくるのは楽しいね",
        "gen": "俺の名前には『勝』も『龍』もないけどな、40年負けずに通ってるぞ。……勝ってはいないけどな",
        "challenge": "今日の出走表で、名前に水の字がある選手を探してみよう。見つけたら、その人だけ応援する『水の字レース』のはじまり",
        "numbers": {"groups": info, "age_all": age_all},
    }


def t_hot(ent, r):
    """今節2連勝中の選手は、次も来る?(ホットハンド)。2走続けて5・6着なら?"""
    x = _adj(ent).sort_values(["racer_id", "dt", "rno"])
    g = x.groupby("racer_id")
    p1, p2, p3 = g["finish"].shift(1), g["finish"].shift(2), g["finish"].shift(3)
    same = (g["jcd"].shift(1) == x["jcd"]) & (g["jcd"].shift(2) == x["jcd"]) & ((x["dt"] - g["dt"].shift(2)).dt.days <= 4)   # 同じ節の前の2走
    w2, l2 = same & (p1 == 1) & (p2 == 1), same & (p1 >= 5) & (p2 >= 5)
    w3 = w2 & (p3 == 1) & (g["jcd"].shift(3) == x["jcd"])
    ms = []
    for nm, mk in (("今節、2連勝中", w2), ("今節、3連勝中", w3), ("今節、2走続けて5・6着", l2)):
        m_ = measure(x, mk, ref=same & ~mk)
        m_["ref_label"] = "その人のふだん"
        ms.append((nm, m_, verdicts(m_)))
    # レース単位: 1号艇が今節2連勝中なら、オッズは知っている?
    e = ent.copy(); e["dt"] = pd.to_datetime(e["date"]); e = e.sort_values(["racer_id", "dt", "rno"]); ge = e.groupby("racer_id")
    hot = ((ge["jcd"].shift(1) == e["jcd"]) & (ge["jcd"].shift(2) == e["jcd"]) & ((e["dt"] - ge["dt"].shift(2)).dt.days <= 4)
           & (ge["finish"].shift(1) == 1) & (ge["finish"].shift(2) == 1))
    h1 = e[(e["lane"] == 1)].assign(h=hot[e["lane"] == 1].astype(int)).drop_duplicates("race_id").set_index("race_id")["h"]
    xr = r.copy(); xr["hot1"] = xr["race_id"].map(h1)
    mr = measure(xr, xr["hot1"] == 1, ref=xr["hot1"] == 0)
    mr.update({"ref_label": "ほかの1号艇", "subject": "1号艇", "verb": "1着になる", "unit": "レース"})
    vr = verdicts(mr)
    ms.append(("1号艇が今節2連勝中(1着)", mr, vr))
    d2, dl = (ms[0][1]["in1"] - ms[0][1]["in1_ref"]) * 100, (ms[2][1]["in1"] - ms[2][1]["in1_ref"]) * 100
    known = vr.get("edge") == 0
    return {
        "id": "hot", "title": "今節2連勝中の選手は、次も来る?", "belief": "勢いのある選手は止まらない。連勝中の選手は次も買い。逆に、続けて大敗している選手は今節はダメ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": False, "unit": "走",
        "lead": f"同じ節で前の2走を続けて1着だった選手は、次のレースで3着以内に入る確率は、{_rate_change(ms[0][1]['in1'], ms[0][1]['in1_ref'], ref_label='その人のふだんの')}。"
                f"3連勝中ならさらに上。逆に2走続けて5・6着だと{round(abs(dl))}ポイント低い。コースの有利不利を差し引いても、前の2年でも最近の1年でも同じ向き。"
                f"1号艇が今節2連勝中なら、1着は{_rate(mr['in1'])}(ほかの1号艇は{_rate(mr['in1_ref'])})。" + ("ただし、人気どおり(みんな知っている)。" if known else ""),
        "conclusion": ["本当。勢いはある" + ("。でも人気どおり" if known else ""),
                       f"今節2連勝中は、3着以内が{_rate_change(ms[0][1]['in1'], ms[0][1]['in1_ref'], ref_label='ふだんの')}。モーターは節の間ずっと同じなので、『今節の足』と『調子』がそのまま出る。"
                       + ("みんなも見ているので配当は堅め。勢いのある選手を2着・3着にどう置くかが腕の見せどころ" if known else "")],
        "tables": [],
        "measures": ms,
        "rules": ["同じ節: 同じ場で、前の2走が4日以内。節の中では、選手は同じモーター・同じボートに乗り続ける",
                  "くらべる相手は、同じ節で前の2走が別の結果だった『その人のふだん』(コースの有利不利も差し引き)"],
        "faq": [("ギャンブラーの錯覚(ホットハンド)じゃないの?", "バスケのシュートでは『錯覚』と言われてきたけれど、競艇では本当に続く。理由ははっきりしていて、節の間はモーターが同じだから。いいモーターを引いた人は、節の間ずっといい"),
                ("大敗が続いた人は、今節はもうダメ?", f"3着以内が{_rate_change(ms[2][1]['in1'], ms[2][1]['in1_ref'], ref_label='ふだんの')}。『今節は足がない』サイン。それでも{_rate(ms[2][1]['in1'])}は3着に入っている(コースをならした数字)。見限るのは早い"),
                ("じゃあ連勝中の人を買えばいい?", "連勝中の人は人気になる。配当とのバランスで考える")],
        "use": ["節の途中のレースは、今節の着順を必ず見る。2連勝中の人は、3着までのどこかに置く", "2走続けて大敗の人は、今節は足が来ていないかも。展示タイムで確かめる"],
        "mikata": "勢いって、本当にあるんだね。モーターと人がかみ合ったときの強さは、見ていて気持ちいい",
        "gen": "ほらな、乗れてるやつは乗れてるんだよ。……人気どおり? みんな見る目があるってことだな",
        "challenge": "今日の出走表で、今節2連勝中の選手を探そう。その人が何着に来るか、レースのたびに追いかけてみよう",
        "numbers": {"d2": d2, "dl": dl},
    }


def t_c1lose(ent, r):
    """1号艇(1コース)が負けるとき、どう負ける? 誰が勝って、1号艇は何着に残る? 1号艇の2着・3着はオッズの予想どおり?"""
    from kyotei.data import _read
    KM = {1: "逃げ", 2: "差し", 3: "まくり", 4: "まくり差し", 5: "抜き", 6: "恵まれ"}
    c1 = ent[ent["course"] == 1].drop_duplicates("race_id").set_index("race_id")
    win = ent[ent["finish"] == 1].drop_duplicates("race_id").set_index("race_id")
    x = r.copy()
    x["c1fin"] = x["race_id"].map(c1["finish"]); x["wcourse"] = x["race_id"].map(win["course"])
    x["km"] = pd.to_numeric(x["kimarite"], errors="coerce").map(KM)
    lose = x[(x["wcourse"] != 1) & x["wcourse"].notna() & x["c1fin"].notna()]
    p_lose = len(lose) / int(x["wcourse"].notna().sum())
    t1 = []
    for k in ("差し", "まくり", "まくり差し", "抜き"):
        g = lose[lose["km"] == k]
        if len(g) < 100:
            continue
        f = g["c1fin"]
        t1.append([k, f"{_rate(len(g) / len(lose))}", f"{_rate((f == 2).mean())}", f"{_rate((f == 3).mean())}", f"{_rate((f >= 4).mean())}"])
    t2 = []
    for k in ("差し", "まくり", "まくり差し"):
        g = lose[lose["km"] == k]["wcourse"].value_counts(normalize=True)
        t2.append([k] + [_rate(g.get(c, 0.0)) for c in range(2, 7)])
    wc = lose["wcourse"].value_counts(normalize=True)
    sashi_2 = float((lose.loc[lose["km"] == "差し", "c1fin"] == 2).mean())
    mak_top3 = float((lose.loc[lose["km"] == "まくり", "c1fin"] <= 3).mean())
    sas_top3 = float((lose.loc[lose["km"] == "差し", "c1fin"] <= 3).mean())
    # オッズ: 枠ごとの2着・3着の見込み(3連単のオッズから)と実際
    o = _read("odds/odds3t_*.csv.gz", None)
    o = o[o["odds"] > 0].copy(); o["race_id"] = o["race_id"].astype(str)
    o["q"] = 1 / o["odds"]; o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
    sp = o["combo"].str.split("-", expand=True).astype(int)
    o["s"], o["t"] = sp[1].values, sp[2].values
    q2 = o.groupby(["race_id", "s"])["q"].sum(); q3 = o.groupby(["race_id", "t"])["q"].sum()
    del o
    tri = x[x["tri_combo"].astype(str).str.match(r"^[1-6]-[1-6]-[1-6]$")].copy()
    tc = tri["tri_combo"].astype(str).str.split("-", expand=True).astype(int)
    parts = []
    for k in range(1, 7):
        z = tri[["race_id", "date", "late", "upset"]].copy()
        z["lane"] = k
        z["h2"], z["h3"] = (tc[1] == k).astype(float).values, (tc[2] == k).astype(float).values
        key = pd.MultiIndex.from_arrays([z["race_id"], pd.Series(k, index=z.index)])
        z["q2"], z["q3"] = q2.reindex(key).values, q3.reindex(key).values
        parts.append(z)
    Z = pd.concat(parts, ignore_index=True)
    m2 = measure(Z, Z["lane"] == 1, ref=Z["lane"] != 1, col="h2", qcol="q2")
    m3 = measure(Z, Z["lane"] == 1, ref=Z["lane"] != 1, col="h3", qcol="q3")
    m2.update({"ref_label": "2〜6号艇の2着", "subject": "1号艇", "verb": "2着になる"})
    m3.update({"ref_label": "2〜6号艇の3着", "subject": "1号艇", "verb": "3着になる"})
    v2, v3 = verdicts(m2), verdicts(m3)
    exp3 = m3["in1"] / m3["market_ratio"] * (m3.get("market_ref") or 1.0) if m3.get("market_ratio") else None
    under3 = v3.get("edge") == -1
    return {
        "id": "c1lose", "title": "1号艇が負けるとき、どう負ける?", "belief": "1号艇が負けたら、もう3着にも残らない。インが飛んだら総崩れ",
        "subject": "1号艇", "unit": "レース",
        "lead": f"1コースの艇が負けるのは、{_rate(p_lose)}。負けたとき、勝つのは2コースが{_rate(wc.get(2, 0))}・3コースが{_rate(wc.get(3, 0))}・4コースが{_rate(wc.get(4, 0))}(負けたレースのうち)。"
                f"負け方で、そのあとが大きく変わる。差されたときは、1コースが2着に残るのが{_rate(sashi_2)}、3着までなら{_rate(sas_top3)}。"
                f"まくられたときは、3着までに残るのは{_rate(mak_top3)}だけ。"
                + (f"そして、1号艇の3着は、人気から考えると{_rate(exp3)}のところ、実際は{_rate(m3['in1'])}と少ない。" if under3 and exp3 else ""),
        "conclusion": ["半分ウソ。差されたら2着に残る、まくられたら沈む",
                       f"1コースが差されたときは、2回に1回は2着に残る。まくられたときは、3着までに残るのは{_rate(mak_top3)}。総崩れになるのは『まくられたとき』"
                       + ("。それと、1号艇の3着づけは、みんなが思うより来ない" if under3 else "")],
        "tables": [("1コースが負けたときの、決まり手と1コースの着順(負けたレースのうち何%か)", t1, ["決まり手", "負けのうち", "1コース2着", "1コース3着", "4着以下"]),
                   ("決まり手ごとの、勝ったコース(%)", t2, ["決まり手", "2コース", "3コース", "4コース", "5コース", "6コース"])],
        "measures": [("1号艇の2着", m2, v2), ("1号艇の3着", m3, v3)],
        "rules": ["差し: 1マークで1コースの内側をすくって抜く(2コースが多い)。まくり: 外から1コースの上を握って回る。まくり差し: 外から内へ切り込んで差す",
                  "1コースの艇の着順は、前づけで1コースに入った艇も含む",
                  "結果のカードは、1号艇の2着・3着を、2〜6号艇の2着・3着とくらべた。『人気から考えると』は、3連単のオッズから計算した『その枠が2着(3着)になる見込み』"],
        "faq": [("なぜ差されると2着に残る?", "差しは1コースの内側をすくう走り。1コースの艇はそのまま外を回っているので、すぐ後ろに残りやすい。まくりは上から押さえこまれるので、流れて後ろの艇にも抜かれる"),
                ("じゃあ1号艇を2着に置くのはどんなとき?", "表から言えるのは『差されたときは2着に残りやすい』ということ。だから、2コースに差しの型の選手がいて、3・4コースにまくりの型がいないレースは、1号艇の2着を考えてみる価値がある(ここはまだミカタの考えで、検証はこれから)"),
                ("1号艇の3着づけが来ないのはなぜ?", "『1号艇は3着くらいには残るだろう』と、おさえで買う人が多いからかも。理由ははっきりしない。追いかける")],
        "use": ["1号艇が危ない日は、『差される』か『まくられる』かを考える。差されそうなら1号艇は2着に、まくられそうなら3着以内から外す",
                "1号艇の3着づけは、思ったより来ない。おさえで買うなら少なめに"],
        "mikata": "負け方にも型があるんだね。1マークで差しが入った瞬間、『1号艇は2着に残れ!』って叫ぶのが楽しくなりそう",
        "gen": "インが飛んだらおしまいだと思ってたよ。差されたなら2着、まくられたら沈む。……これは使えるな",
        "challenge": "次のレースで1号艇が負けたら、決まり手と1号艇の着順をメモしよう。差しなら2着に残ったか、答え合わせ",
        "numbers": {"p_lose": p_lose, "sashi_2": sashi_2, "mak_top3": mak_top3, "sas_top3": sas_top3},
    }


def t_suji(ent, r):
    """スジ舟券(2026-10-07 ネットの理論から): 2コース差しなら2着は1コース(2-1)、まくりなら2着はその外、4コース差しは4-1、5コースは5-4。
    1着の枠と決まり手ごとに「2着の枠」を数え、市場(3連単オッズから計算した、1着がその枠のときの2着の見込み)と比べる。枠なりのレースだけ。"""
    from kyotei.data import _read
    KM = {1: "逃げ", 2: "差し", 3: "まくり", 4: "まくり差し", 5: "抜き", 6: "恵まれ"}
    # 枠なり(進入=枠)のレースだけ(オッズは枠番につくので、コース=枠のレースで見る)
    e6 = ent[ent["course"].between(1, 6)]
    nari = e6.groupby("race_id").apply(lambda g: bool((g["course"] == g["lane"]).all()) and len(g) == 6)
    nari_ids = set(nari[nari].index)
    x = r[r["race_id"].isin(nari_ids) & r["tri_combo"].astype(str).str.match(r"^[1-6]-[1-6]-[1-6]$")].copy()
    tc = x["tri_combo"].astype(str).str.split("-", expand=True).astype(int)
    x["w"], x["s"] = tc[0].values, tc[1].values
    x["km"] = pd.to_numeric(x["kimarite"], errors="coerce").map(KM)
    # 市場: 1着が w のときの「2着が d」の見込み(3連単オッズから。控除を除いて正規化)
    o = _read("odds/odds3t_*.csv.gz", None)
    o = o[o["odds"] > 0].copy(); o["race_id"] = o["race_id"].astype(str)
    o["q"] = 1 / o["odds"]; o["q"] = o["q"] / o.groupby("race_id")["q"].transform("sum")
    sp = o["combo"].str.split("-", expand=True).astype(int)
    o["w"], o["s"] = sp[0].values, sp[1].values
    qws = o.groupby(["race_id", "w", "s"])["q"].sum()
    qw = o.groupby(["race_id", "w"])["q"].sum()
    del o
    parts = []
    for d in range(1, 7):
        z = x[["race_id", "date", "late", "upset", "w", "s", "km"]].copy()
        z = z[z["w"] != d]
        z["d"] = d
        z["h"] = (z["s"] == d).astype(float)
        key = pd.MultiIndex.from_arrays([z["race_id"], z["w"], pd.Series(d, index=z.index)])
        kw = pd.MultiIndex.from_arrays([z["race_id"], z["w"]])
        z["q"] = (qws.reindex(key).values / qw.reindex(kw).values)
        parts.append(z)
    Z = pd.concat(parts, ignore_index=True)
    def M(mask, ref, label, subj):
        m = measure(Z, mask, ref=ref, col="h", qcol="q")
        m.update({"ref_label": label, "subject": subj, "verb": "2着になる", "unit": "レース"})
        return m
    W, S, D, K = Z["w"], Z["s"], Z["d"], Z["km"]
    # 市場とくらべる物差しは、決まり手を使わない「1着の枠→2着の枠」(買える形。決まり手はレース後にしか分からない)。
    # 比べる相手は「その枠が2着になる割合(1着がほかの枠のとき全部)」
    specs = [("2-1: 2号艇が1着のとき、2着が1号艇", (W == 2) & (D == 1), (W != 1) & (D == 1), "1号艇以外が1着のとき", "1号艇"),
             ("3-1: 3号艇が1着のとき、2着が1号艇", (W == 3) & (D == 1), (W != 1) & (D == 1), "1号艇以外が1着のとき", "1号艇"),
             ("3-4: 3号艇が1着のとき、2着が4号艇", (W == 3) & (D == 4), (W != 4) & (D == 4), "4号艇以外が1着のとき", "4号艇"),
             ("4-1: 4号艇が1着のとき、2着が1号艇", (W == 4) & (D == 1), (W != 1) & (D == 1), "1号艇以外が1着のとき", "1号艇"),
             ("4-5: 4号艇が1着のとき、2着が5号艇", (W == 4) & (D == 5), (W != 5) & (D == 5), "5号艇以外が1着のとき", "5号艇"),
             ("5-4: 5号艇が1着のとき、2着が4号艇", (W == 5) & (D == 4), (W != 4) & (D == 4), "4号艇以外が1着のとき", "4号艇"),
             ("6-1: 6号艇が1着のとき、2着が1号艇", (W == 6) & (D == 1), (W != 1) & (D == 1), "1号艇以外が1着のとき", "1号艇")]
    ms = [(nm, M(mk, rf, lb, sj), None) for nm, mk, rf, lb, sj in specs]
    ms = [(nm, m, verdicts(m)) for nm, m, _ in ms]
    # 決まり手ごとの筋(しくみの説明用。市場とは比べない)
    def share(w, k, d):
        g = x[(x["w"] == w) & (x["km"] == k)]
        return float((g["s"] == d).mean()) if len(g) else float("nan")
    k21, k41, k34, k45, k54 = share(2, "差し", 1), share(4, "差し", 1), share(3, "まくり", 4), share(4, "まくり", 5), share(5, "まくり差し", 4)
    # 表: 1着の枠×決まり手 → 2着の枠(%)。レース数100以上の組だけ
    tbl = []
    for w in range(2, 7):
        for k in ("差し", "まくり", "まくり差し"):
            g = x[(x["w"] == w) & (x["km"] == k)]
            if len(g) < 100:
                continue
            vc = g["s"].value_counts(normalize=True)
            top = vc.index[0]
            tbl.append([f"{w}号艇", k, f"{len(g):,}", f"{top}号艇 {_rate(vc.iloc[0])}", f"{vc.index[1]}号艇 {_rate(vc.iloc[1])}" if len(vc) > 1 else "-",
                        _rate(vc.get(1, 0.0)) if w != 1 else "-"])
    # 市場との差をまとめる: スジが人気以上か、ひかえめか
    edges = {nm: v.get("edge") for nm, _, v in ms}
    over = [nm for nm, e_ in edges.items() if e_ == 1]
    under = [nm for nm, e_ in edges.items() if e_ == -1]
    m21, m31, m34, m41, m45, m54, m61 = (m for _, m, _ in ms)
    real_suji = sum(1 for _, m, v in ms if v.get("real") and m["in1"] > m["in1_ref"])
    con_head = ("本当。スジは本物。でも人気どおり" if real_suji >= 4 and not over and not under else
                ("本当。スジは本物。しかも一部は人気以上に来る" if over else ("本当。スジは本物。ただ買われすぎの筋もある" if under else "半分本当。筋によって違う")))
    return {
        "id": "suji", "title": "スジ舟券は本当か。差しなら1号艇が残り、まくりなら外が来る?",
        "belief": "2コースが差したら2着は1コース(2-1)。まくりが決まったら2着はその外(3まくりなら4、4まくりなら5)。4コースの差しは4-1、5コースは5-4",
        "subject": "2着の枠", "verb": "2着になる", "unit": "レース", "compare": "同じ枠が1着のときの全部",
        "x1": f"2号艇が差して1着なら、2着が1号艇なのは{_rate(k21)}。4号艇がまくって1着なら、2着が5号艇なのは{_rate(k45)}。",
        "lead": f"枠なり(進入が枠のとおり)のレースで、1着の枠と決まり手ごとに『2着は誰か』を数えた。"
                f"2号艇が差して1着のとき、2着が1号艇なのは{_rate(k21)}(2号艇が1着のとき全部では{_rate(m21['in1'])})。"
                f"4号艇が差して1着なら、2着が1号艇なのは{_rate(k41)}。差しは1コースの内側をすくうので、1コースの艇はすぐ後ろに残る。"
                f"\n\nまくりは逆。3号艇がまくって1着のとき、2着が4号艇なのは{_rate(k34)}(3号艇が1着のとき全部では{_rate(m34['in1'])})。"
                f"4号艇がまくって1着なら、2着が5号艇なのは{_rate(k45)}。まくられた内の艇は引き波に沈み、まくった艇のすぐ外が付いてくる。"
                f"\n\n問題は、みんなもこれを知っているか。決まり手はレースが終わるまで分からないので、買える形の『1着の枠→2着の枠』で、"
                f"3連単のオッズから出した『1着がその枠のときの2着の見込み』と比べると、"
                + (f"人気以上に来ているのは{'・'.join(over)}。" if over else "")
                + (f"人気のわりにひかえめなのは{'・'.join(under)}。" if under else "")
                + ("どの筋も、だいたい人気どおり。" if not over and not under else ""),
        "conclusion": [con_head,
                       "。".join([f"差されたら1号艇が2着に残る({_rate(k21)})、まくられたら外が続く(4まくり→5号艇 {_rate(k45)})。筋は本物"]
                                + ([f"人気以上に来る筋: {'、'.join(over)}"] if over else [])
                                + ([f"買われすぎの筋: {'、'.join(under)}(差しのイメージで1号艇を2着に置く人が多いが、4号艇の1着の6割はまくり。まくられた1号艇は沈む)"] if under else []))],
        "tables": [("1着の枠×決まり手ごとの、2着の枠(枠なりのレース、%)", tbl, ["1着", "決まり手", "レース数", "2着で多い枠", "2番目", "2着が1号艇"])],
        "measures": ms,
        "rules": ["スジ舟券: 1着の艇の決まり手から、2着に来やすい艇を決める買い方。差し→1コースが残る、まくり→まくった艇のすぐ外、が基本の筋",
                  "枠なり(スタート展示と本番の進入が枠のとおり)のレースだけで数えた。前づけがあると枠とコースがずれて、筋が読めないため",
                  "『人気から考えると』は、3連単のオッズから計算した『1着がその枠のとき、2着がその枠になる見込み』(控除を除いた値)"],
        "faq": [("決まり手はレースが終わるまで分からないのでは?", "そのとおり。だからスジは『どう勝つと思うか』を先に決めてから使う。2号艇の差しを本線にするなら2-1、4号艇のまくりなら4-5、という順番"),
                ("5-4の『反転』って?", f"5号艇がまくり差しで1着のとき、4号艇が2着になるのは{_rate(k54)}。4号艇がまくりに行って内が空き、5号艇が差して、4号艇がそのまま続く形"),
                ("6号艇が勝ったら2着は?", f"6号艇が1着のとき、2着が1号艇なのは{_rate(m61['in1'])}。大外がまくり切ると、内の5艇は引き波で崩れ、いちばん内の1号艇が残りやすい")],
        "use": ["1着を決めたら、次は『どう勝つか』。差しなら1号艇を2着に、まくりならすぐ外を2着に。筋は本物",
                "人気との差が出た筋だけ、2着の候補の順番を入れかえる(人気以上なら厚めに、ひかえめなら薄めに)"],
        "mikata": "1着の次は『どう勝つか』。差しなら1号艇が残り、まくりなら外が続く。筋って、ちゃんとあるんだね",
        "gen": "スジ舟券は昔からの基本だ。2-1、4-5。……で、どの筋がオッズより来るんだ? そこを教えろよ",
        "challenge": "次のレースで、本命の『勝ち方』を先に決めてから2着を選ぶ。差しなら1号艇、まくりなら外。結果と答え合わせ",
        "numbers": {"n_nari": int(len(x)), "edges": edges, "k21": k21, "k41": k41, "k34": k34, "k45": k45, "k54": k54},
    }


VENUE_LL = {1: (36.39, 139.33), 2: (35.81, 139.66), 3: (35.69, 139.87), 4: (35.58, 139.74), 5: (35.62, 139.52), 6: (34.72, 137.60),
            7: (34.82, 137.23), 8: (34.88, 136.84), 9: (34.72, 136.54), 10: (36.21, 136.14), 11: (35.03, 135.88), 12: (34.61, 135.47),
            13: (34.72, 135.42), 14: (34.17, 134.61), 15: (34.29, 133.79), 16: (34.47, 133.81), 17: (34.31, 132.32), 18: (34.05, 131.80),
            19: (33.95, 130.94), 20: (33.90, 130.81), 21: (33.89, 130.66), 22: (33.59, 130.40), 23: (33.46, 129.97), 24: (32.92, 129.96)}


def _sunset_min(dates: pd.Series, jcd: pd.Series) -> pd.Series:
    """日の入りの時刻(JST、0時からの分)。NOAA の近似式(誤差2〜3分)。"""
    d = pd.to_datetime(dates)
    doy = d.dt.dayofyear.values.astype(float)
    lat = jcd.map({k: v[0] for k, v in VENUE_LL.items()}).values.astype(float)
    lon = jcd.map({k: v[1] for k, v in VENUE_LL.items()}).values.astype(float)
    g = 2 * np.pi / 365 * (doy - 1 + 0.5)
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
            - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    la = np.radians(lat)
    ha = np.degrees(np.arccos(np.clip(np.cos(np.radians(90.833)) / (np.cos(la) * np.cos(decl)) - np.tan(la) * np.tan(decl), -1, 1)))
    sunset_utc_min = 720 + 4 * (ha - lon) - eqt
    return pd.Series(sunset_utc_min + 9 * 60, index=dates.index)


def t_night(ent, r):
    """日没後はインが強い(ナイターの法則)? 時間帯(モーニング・デイ・ナイター・ミッドナイト)でインの強さは違う?
    同じ場・同じレース番号で、締切が日の入りの前か後か(季節で入れかわる)をくらべる。"""
    dl = ent.drop_duplicates("race_id").set_index("race_id")["deadline"]
    x = r.copy()
    x["dl"] = x["race_id"].map(dl)
    hm = x["dl"].astype(str).str.extract(r"^(\d{1,2}):(\d{2})")
    x["tmin"] = pd.to_numeric(hm[0], errors="coerce") * 60 + pd.to_numeric(hm[1], errors="coerce")
    x = x[x["tmin"].notna() & x["jcd"].isin(VENUE_LL)].copy()
    x["sunset"] = _sunset_min(x["date"], x["jcd"]).values
    x["after"] = x["tmin"] >= x["sunset"] + 15          # 日の入りの15分後より遅い締切 = 暗くなってからのレース
    x["before"] = x["tmin"] <= x["sunset"] - 30
    band = pd.cut(x["tmin"], [0, 10 * 60 + 30, 15 * 60, 18 * 60, 20 * 60 + 30, 24 * 60],
                  labels=["モーニング(〜10:30)", "デイ(〜15:00)", "夕方(〜18:00)", "ナイター(〜20:30)", "ミッドナイト(20:30〜)"])
    x["band"] = band
    # ナイター場(同じ日に日没の前後のレースがある場)だけで、同じレース番号どうしをくらべる。
    # 日の入り前のレースは夏の7・8Rにかたよる(9R以降はほぼ暗い)ので、前後の両方がある 7・8R だけで数える(番号の違いを混ぜない)
    nv = x.groupby("jcd")["after"].mean()
    night_venues = set(nv[nv > 0.15].index)
    both = x["jcd"].isin(night_venues) & x["rno"].isin([7, 8])
    m_after = measure(x, both & x["after"], ref=both & x["before"])
    m_after.update({"ref_label": "同じ場の7・8Rで、日の入り前", "subject": "1号艇", "verb": "勝つ", "unit": "レース"})
    # レース番号ごと(7〜9R)の前後
    tbl_r = []
    for rn in (7, 8, 9):
        g = x[x["jcd"].isin(night_venues) & (x["rno"] == rn)]
        a, b_ = g[g["after"]], g[g["before"]]
        if len(a) >= 50 and len(b_) >= 50:
            tbl_r.append([f"{rn}R", _rate(b_["c1"].mean()), f"{len(b_):,}", _rate(a["c1"].mean()), f"{len(a):,}", _rate_change(a["c1"].mean(), b_["c1"].mean())])
    # 時間帯ごと(全体とくらべる)
    ms_band = []
    for b in band.cat.categories:
        mb = x["band"] == b
        if mb.sum() < 500:
            continue
        m = measure(x, mb)
        m.update({"ref_label": "全レース", "subject": "1号艇", "verb": "勝つ", "unit": "レース"})
        ms_band.append((f"{b}の締切", m, verdicts(m)))
    v_after = verdicts(m_after)
    # 表: 場ごと(ナイター場)の日没前後
    tbl = []
    for j in sorted(night_venues):
        g = x[(x["jcd"] == j) & x["rno"].isin([7, 8])]
        a, b_ = g[g["after"]], g[g["before"]]
        if len(a) >= 60 and len(b_) >= 60:
            tbl.append([VENUES[j], _rate(b_["c1"].mean()), _rate(a["c1"].mean()), _rate_change(a["c1"].mean(), b_["c1"].mean()), f"{len(a):,}"])
    tbl2 = [[b, f"{int((x['band'] == b).sum()):,}", _rate(x.loc[x['band'] == b, 'c1'].mean()), _rate(x.loc[x['band'] == b, 'upset'].mean())] for b in band.cat.categories
            if (x["band"] == b).sum() >= 500]
    d_after = (m_after["in1"] - m_after["in1_ref"]) * 100
    real = v_after["real"]
    head = ("本当。暗くなるとインは少し強い" if real and d_after > 0 else ("ほぼ同じ。暗さより『場と番組』" if not real else "逆。暗くなるとインは少し弱い"))
    mid = next((m for nm, m, v in ms_band if nm.startswith("ミッドナイト")), None)
    mor = next((m for nm, m, v in ms_band if nm.startswith("モーニング")), None)
    return {
        "id": "night", "title": "日が沈むと、インは強くなる?", "belief": "ナイターは日没後に1号艇の1着率が上がる。夜は水面が静かで、視界も変わるから",
        "subject": "1号艇", "unit": "レース", "compare": "同じ場・同じレース番号の、日の入り前のレース",
        "x1": f"ナイター場の7・8R、日の入り後の締切なら1号艇が勝つのは{_rate(m_after['in1'])}。同じ場の7・8Rで日の入り前は{_rate(m_after['in1_ref'])}。",
        "lead": f"ナイターの場では、同じ7・8Rでも、夏は明るいうちに締切、秋冬は暗くなってから締切になる。それを使って『同じ場・同じレース番号』で、"
                f"日の入りの前と後をくらべた。1号艇が勝つのは、日の入り後{_rate(m_after['in1'])}、日の入り前{_rate(m_after['in1_ref'])}({_rate_change(m_after['in1'], m_after['in1_ref'])})。"
                + (f"ナイター場{len(tbl)}場のうち、暗くなってインが上がったのは{sum(1 for t in tbl if '上がる' in t[3])}場。" if tbl else "")
                + f"レース番号をそろえないで数えると差はもっと大きく見える(日の入り後のレースは10R・11Rにかたより、そこは番組が1号艇に強い人を置くため)。"
                + f"\n\n時間帯で切ると、1号艇が勝つのは" + "、".join(f"{nm.replace('の締切', '')}{_rate(m['in1'])}" for nm, m, v in ms_band) + "。"
                + (f"ミッドナイト(20:30以降の締切)は{_rate(mid['in1'])}で、" + ("人気以上に来る" if verdicts(mid).get("edge") == 1 else ("人気のわりにひかえめ" if verdicts(mid).get("edge") == -1 else "人気どおり")) + "。" if mid else "")
                + f"ただし時間帯の差の多くは『場』の差(ナイターをやる場・モーニングをやる場が決まっている)と『番組』の差(12Rは1号艇に強い人を置く)。"
                f"それを除いた純粋な『暗さ』の効き目が、上の{_rate_change(m_after['in1'], m_after['in1_ref'])}。",
        "conclusion": [head, f"同じ場・同じレース番号でくらべると、日の入り後の1号艇は{_rate(m_after['in1'])}、日の入り前は{_rate(m_after['in1_ref'])}。"
                       + ("差は本物だが小さい。" if real else "差は小さく、たまたまでも出るくらいの幅。") + "ナイターのイン勝率が高く見えるのは、暗さより『場と番組』"],
        "tables": [("ナイター場ごとの、日の入り前後の1号艇(7・8R)", tbl, ["場", "日の入り前", "日の入り後", "差", "日の入り後のレース数"]),
                   ("レース番号ごとの、日の入り前後の1号艇(ナイター場)", tbl_r, ["レース", "日の入り前", "レース数", "日の入り後", "レース数", "差"]),
                   ("締切の時間帯ごとの数字(全場)", tbl2, ["時間帯", "レース数", "1号艇の1着", "万舟(30番人気以下)"])],
        "measures": [("日の入り後の締切(ナイター場の7・8R)", m_after, v_after)] + ms_band,
        "rules": ["日の入りの時刻は、場の緯度経度と日付から計算(誤差2〜3分)。『日の入り後』は日の入りの15分より後の締切、『前』は30分より前の締切",
                  "ナイター場: 同じ日に日の入りの前後どちらのレースもある場(桐生・蒲郡・住之江・丸亀・若松・下関・大村)。7・8Rだけでくらべたのは、9R以降は一年中ほぼ暗く『前』のレースが無いのと、12Rは番組の作りが特別だから。夏と秋冬の季節の差(夏はインが1〜2ポイント弱い)は混ざっている",
                  "時間帯の区切りは締切の時刻: モーニング(〜10:30)・デイ(〜15:00)・夕方(〜18:00)・ナイター(〜20:30)・ミッドナイト(20:30〜)"],
        "faq": [("なぜ『同じ場・同じレース番号』でくらべる?", "ナイターの場は昼の場より1号艇が強い場が多く、12Rは1号艇に強い人を置く番組が多い。場と番組の差を『暗さの効き目』と取りちがえないため"),
                ("ミッドナイトは堅い?", f"20:30以降の締切の1号艇は{_rate(mid['in1']) if mid else '-'}。ただしミッドナイトをやる場(大村・下関・若松など)はもともとインが強い場。場を除いた暗さの効き目は上の数字"),
                ("モーニングは?", f"10:30までの締切の1号艇は{_rate(mor['in1']) if mor else '-'}。モーニングの1〜2Rは企画レース(1号艇にA級)が多く、番組の効き目が大きい")],
        "use": ["『ナイターだからイン』は、場と番組の話。暗さそのものの効き目は小さいので、1号艇の判断はいつもどおり選手と展示で",
                "ミッドナイトの1号艇は、場の性格(大村・下関・若松はもともとイン有利)を先に頭に入れる"],
        "mikata": "夜の水面はきれいで、インが強く見える。でも数えてみると、強いのは『夜』じゃなくて『場と番組』だったみたい",
        "gen": "ナイターは堅いって、みんな言うだろ。……場と番組か。まあ、堅いことに変わりはねえな",
        "challenge": "ナイターの場で、日の入りの前の7Rと後の11Rの1号艇を見くらべてみて。暗さより『誰が1号艇か』で決まってるはず",
        "numbers": {"night_venues": sorted(VENUES[j] for j in night_venues), "d_after": d_after},
    }


def _same_pop(x, mask, col="c1", qcol="q1", nb=10, n=300):
    """人気の高さをそろえたくらべ: mask のレースで実際に来た数 ÷『同じくらい人気を集めた、ほかのレースの艇』から見込む数。(比, 下, 上) を返す。
    人気を集めた艇ほど人気どおりに来やすい(人気薄は買われすぎる)。条件で分けると人気の高さも変わるので、全レースの比とそのままくらべると取りちがえる
    (night の教訓の、人気版)。ブレの幅は日ごとに引き直して出す。"""
    if qcol not in x:
        return None
    d = x.dropna(subset=[qcol]).copy()
    d["_m"] = mask.reindex(d.index).fillna(False).astype(bool)
    if d["_m"].sum() < 500 or (~d["_m"]).sum() < 500:
        return None
    cut = [-1.0] + list(np.quantile(d.loc[d["_m"], qcol], np.linspace(0, 1, nb + 1))[1:-1]) + [2.0]
    d["_b"] = pd.cut(d[qcol], sorted(set(cut)), labels=False)
    d["_d"] = d["date"].astype(str).str[:10]
    t = d.groupby(["_d", "_b", "_m"]).agg(a=(col, "sum"), q=(qcol, "sum")).reset_index()
    days = {k: i for i, k in enumerate(t["_d"].unique())}
    A = np.zeros((len(days), int(t["_b"].max()) + 1, 2)); Q = np.zeros_like(A)
    for dd, b, mm, a, q in t.itertuples(index=False):
        A[days[dd], int(b), int(mm)] = a; Q[days[dd], int(b), int(mm)] = q

    def _ratio(a, q):
        ok = q[:, 0] > 0
        return float(a[ok, 1].sum() / (a[ok, 0] / q[ok, 0] * q[ok, 1]).sum())
    rng = np.random.default_rng(2)
    bt = [_ratio(A[s].sum(0), Q[s].sum(0)) for s in (rng.integers(0, len(days), len(days)) for _ in range(n))]
    return _ratio(A.sum(0), Q.sum(0)), float(np.quantile(bt, 0.05)), float(np.quantile(bt, 0.95))


def t_power(ent, r):
    """力の逆転(2026-10-07 ネットの理論から): 1号艇より勝率の高い選手が2・3号艇にいると荒れる?
    出走表の全国勝率で分ける。1号艇の勝率が低いだけの話と混ざらないよう、1号艇の勝率が同じ(5点台)レースどうしでもくらべる。
    人気とのくらべは、同じくらい人気を集めた艇どうしで(_same_pop)。"""
    w = ent.pivot_table(index="race_id", columns="lane", values="nat_win_rate", aggfunc="first").reindex(columns=range(1, 7))
    w = w[w.notna().all(axis=1)]
    x = r[r["race_id"].isin(w.index)].copy()
    W = w.loc[x["race_id"]].values
    x["w1"] = W[:, 0]
    up2, up3 = W[:, 1] > W[:, 0], W[:, 2] > W[:, 0]
    upout = (W[:, 3:] > W[:, [0]]).any(axis=1)
    x["both"], x["none"] = up2 & up3, ~up2 & ~up3
    x["rank1"] = (W > W[:, [0]]).sum(axis=1) + 1
    x["gmin"] = np.minimum(W[:, 1], W[:, 2]) - W[:, 0]
    x["w23"] = x["win_lane"].isin([2, 3]).astype(float)
    x["q_23"] = x[["q_l2", "q_l3"]].sum(axis=1, min_count=2) if "q_l2" in x else np.nan
    band = (x["w1"] >= 5.0) & (x["w1"] < 6.0)          # 1号艇の勝率が5点台。同じ強さの1号艇どうしでくらべる

    def _pop(m, mask, col, qcol):
        """人気とのくらべを『同じくらい人気を集めた艇』に直す。前後に分けてどちらもはっきりしなければ、追試中にとどめる。"""
        sp = _same_pop(x, mask, col, qcol)
        if not sp or not m.get("market_ratio"):
            return verdicts(m), None
        m["market_ref"] = m["market_ratio"] / sp[0]
        m["market_ci"] = [m["market_ref"] * sp[1], m["market_ref"] * sp[2]]
        v = verdicts(m)
        if v.get("edge") in (1, -1):
            xo = x[mask & x[qcol].notna()]
            mid = xo["date"].astype(str).sort_values().iloc[len(xo) // 2]
            hs = [_same_pop(x[(x["date"].astype(str) < mid) == first], mask, col, qcol) for first in (True, False)]
            if not all(h and (h[1] > 1 if v["edge"] == 1 else h[2] < 1) for h in hs):
                v["known"] = ("人気以上に来ている気配。" if v["edge"] == 1 else "人気のわりにひかえめの気配。") + "ただ差は小さく、期間を前後に分けるとブレの幅に入る(追試中)"
                v["edge"] = 0
        return v, sp

    m_both = measure(x, x["both"])
    v_both, sp1 = _pop(m_both, x["both"], "c1", "q1")
    m_band = measure(x, band & x["both"], ref=band & x["none"])
    m_band["ref_label"] = "同じ5点台で、2・3号艇がどちらも下"
    v_band = verdicts(m_band)
    m23 = measure(x, x["both"], col="w23", qcol="q_23")
    m23.update({"subject": "2・3号艇のどちらか", "verb": "勝つ", "ref_label": "全レースの2・3号艇"})
    v23, sp23 = _pop(m23, x["both"], "w23", "q_23")
    m_top = measure(x, x["rank1"] == 1)
    v_top = verdicts(m_top)
    # 強い選手が「どこにいるか」(全レースと、1号艇が5点台のレース)
    cats = [("1号艇より上がいない(1号艇がトップ)", ~up2 & ~up3 & ~upout), ("上は4〜6号艇にだけ", ~up2 & ~up3 & upout), ("上は2号艇だけ", up2 & ~up3),
            ("上は3号艇だけ", ~up2 & up3), ("2・3号艇がどちらも上", up2 & up3)]
    c5, t1 = {}, []
    for nm, mk in cats:
        g, g5 = x[mk], x[mk & band]
        c5[nm] = float(g5["c1"].mean())
        t1.append([nm, _rate(len(g) / len(x)), _rate(g["c1"].mean()), _rate(g5["c1"].mean()), _rate(g["upset"].mean())])
    t2 = [[f"{k}位", f"{int((x['rank1'] == k).sum()):,}", _rate(x.loc[x["rank1"] == k, "c1"].mean())] for k in range(1, 7)]
    t3 = []
    for lo, hi, nm in ((0, 0.5, "0.5未満"), (0.5, 1.0, "0.5〜1.0"), (1.0, 1.5, "1.0〜1.5"), (1.5, 99, "1.5以上")):
        g = x[x["both"] & (x["gmin"] >= lo) & (x["gmin"] < hi)]
        if len(g) >= 300:
            t3.append([nm, f"{len(g):,}", _rate(g["c1"].mean()), _rate(g["w23"].mean())])
    # 場とレース番号までそろえた差(5点台の1号艇。逆転のレースは10〜12Rに多いので、番組の差を混ぜない)
    cg = x[band & (x["both"] | x["none"])].groupby(["jcd", "rno", "both"])["c1"].agg(["mean", "size"]).unstack().dropna()
    wt = np.minimum(cg[("size", True)], cg[("size", False)])
    d_cell = float(((cg[("mean", True)] - cg[("mean", False)]) * wt).sum() / wt.sum()) if len(cg) else float("nan")
    share = float(x["both"].mean())
    exp1 = m_both["in1"] / sp1[0] if sp1 else None
    real = v_both["real"]
    if not real:
        head = "ふだんと同じ"
    elif v_both.get("edge") == 1:
        head = "本当。しかも1号艇は人気以上に残る"
    elif v_both.get("edge") == -1:
        head = "本当。人気が思うより1号艇は苦しい"
    else:
        head = "本当。ただし人気どおり"
    trial = "追試中" in (v_both.get("known") or "")
    pop1 = (f"1号艇は、同じくらい人気を集めたほかのレースの1号艇から考えると{_rate(exp1, True)}のところ、実際は{_rate(m_both['in1'], True)}。"
            + ("少し多く残っている気配はあるが、差は小さく、期間を前後に分けるとブレの幅に入る。いまは『人気どおり』としておいて、追いかける。" if trial
               else ("人気より多く残っている。" if v_both.get("edge") == 1 else ("人気より少ない。" if v_both.get("edge") == -1 else "人気どおり。")))) if exp1 else ""
    pop23 = (f"2・3号艇のどちらかが勝つのは{_rate(m23['in1'])}(全レースは{_rate(m23['in1_ref'])})まで上がるが、"
             + {1: "人気より多く来ている", -1: "人気のわりにひかえめ"}.get(v23.get("edge"), "人気もそのぶん集まっていて、人気どおり") + "。")
    n_top, n_out, n_2, n_3, n_both = (c[0] for c in cats)
    return {
        "id": "power", "title": "1号艇より強い選手が2・3号艇にいると、荒れる?", "belief": "1号艇より勝率の高い選手が2・3号艇にいるレースは荒れる。力の逆転ってやつだ",
        "subject": "1号艇", "unit": "レース",
        "x1": f"2・3号艇の勝率がどちらも1号艇より上なら、1号艇が勝つのは{_rate(m_both['in1'])}。全レースは{_rate(m_both['in1_ref'])}。",
        "lead": f"出走表の『全国勝率』で、1号艇より上の選手が2号艇にも3号艇にもいる。そんな『力の逆転』のレースは、全体の{_rate(share)}。"
                f"1号艇が勝つのは{_rate(m_both['in1'])}で、全レースの{_rate(m_both['in1_ref'])}から大きく下がる。万舟(30番人気以下の決着)は{_rate(m_both['upset'])}(全レースは{_rate(m_both['upset_ref'])})。"
                f"\n\nただ、これだけだと『1号艇の勝率がもともと低いレース』を数えているだけかもしれない。そこで1号艇の強さをそろえた。"
                f"1号艇の勝率が5点台のレースだけで見ると、2・3号艇がどちらも下なら{_rate(m_band['in1_ref'])}、どちらも上なら{_rate(m_band['in1'])}。"
                f"同じ強さの1号艇でも、すぐ外に強い選手が並ぶと勝ちにくくなる。"
                + (f"場とレース番号までそろえても、{abs(d_cell) * 100:.0f}ポイントの差が残る。" if d_cell == d_cell else "")
                + f"\n\n強い選手が『どこにいるか』でも変わる。同じ5点台の1号艇で、自分より上が1人もいなければ{_rate(c5[n_top])}。上の選手が4〜6号艇にだけいると{_rate(c5[n_out])}、"
                f"2号艇だけが上なら{_rate(c5[n_2])}、3号艇だけが上なら{_rate(c5[n_3])}、2・3号艇がどちらも上なら{_rate(c5[n_both])}。"
                f"外に格上がいるだけでも下がるが、隣(2・3号艇)にいると、もう一段下がる。"
                f"\n\n人気とのくらべ。{pop1}{pop23}",
        "conclusion": [head, f"2・3号艇の勝率がどちらも1号艇より上のレースは、1号艇が勝つのは{_rate(m_both['in1'])}(全レースは{_rate(m_both['in1_ref'])})。"
                             f"1号艇の強さが同じ(勝率5点台)でも{_rate_change(m_band['in1'], m_band['in1_ref'])}。"
                             f"格上が4〜6号艇にだけいるなら{_rate(c5[n_out])}、隣の2・3号艇にいると、もう一段下がる。"
                             + ("出走表でみんな見ているので、人気もそのとおりに動く" if v_both.get("edge") == 0 else "")],
        "tables": [("1号艇より勝率の高い選手が、どこにいるか", t1, ["強い選手の場所", "全レースのうち", "1号艇の1着", "1号艇の1着(1号艇が5点台)", "万舟(30番人気以下)"]),
                   ("1号艇の勝率の順位(6人中)と、1号艇の1着", t2, ["1号艇の順位", "レース数", "1号艇の1着"]),
                   ("2・3号艇がどちらも上のレース: 低いほうとの勝率の差で分ける", t3, ["2・3号艇の低いほう − 1号艇", "レース数", "1号艇の1着", "2・3号艇のどちらかが1着"])],
        # 物差しの名前は、1号艇が主語になる形に(measure_line は名前に主語があると「勝つのは◯%」と書く。だれが勝つのか分かるように)
        "measures": [("1号艇の勝率が、2・3号艇のどちらよりも下", m_both, v_both), ("勝率5点台の1号艇で、2・3号艇がどちらも上", m_band, v_band),
                     ("2・3号艇がどちらも1号艇より上のとき", m23, v23), ("1号艇の勝率が6人中いちばん上", m_top, v_top)],
        "rules": ["全国勝率は出走表にのっている数字(着順ごとの点数の平均。1着10点・2着8点…)。レースの前に分かる",
                  "『力の逆転』= 2号艇と3号艇の勝率が、どちらも1号艇より高いレース。6人とも勝率が出ているレースだけで数えた",
                  "人気とのくらべは、『同じくらい人気を集めた、ほかのレースの艇』と。人気を集めた艇ほど人気どおりに来やすいので、人気の高さがちがう相手とくらべると取りちがえるため"],
        "faq": [("1号艇の勝率が低いだけでは?", f"それも大きい。だから1号艇の勝率が同じ5点台のレースだけでもくらべた。それでも{_rate_change(m_band['in1'], m_band['in1_ref'])}"),
                ("2号艇と3号艇、どっちが上だと効く?", f"ほぼ同じ。1号艇が5点台のとき、2号艇だけが上なら{_rate(c5[n_2])}、3号艇だけが上なら{_rate(c5[n_3])}"),
                ("2・3号艇は人気以上に来る?", pop23.rstrip("。"))],
        "use": [f"1号艇は、勝率そのものより『2・3号艇とくらべて上か下か』で見る。どちらも上なら、同じ5点台の1号艇でも1着は{_rate(m_band['in1'])}まで下げて考える",
                f"格上が『どこにいるか』で1号艇の見込みを一段ずつ動かす。5点台の1号艇なら、上がいない{_rate(c5[n_top])}→4〜6号艇にだけ{_rate(c5[n_out])}→2・3号艇がどちらも上{_rate(c5[n_both])}",
                "人気もそのとおりに動くので、これだけで人気の裏はかけない。2・3号艇のどちらが先に攻めるかを、展示で見て決める"],
        "mikata": "強い人が『どこにいるか』で、同じ1号艇でも景色が変わる。こういう見方もあるよ",
        "gen": "格上が2・3号艇にいたらインは苦しい。昔からそうだ。……外にいるのと隣にいるのとで、もう一段違うのか。そこまでは数えてなかったな",
        "challenge": "今日の出走表で、2号艇と3号艇の全国勝率がどちらも1号艇より上のレースを1つ探す。1号艇が残るか、2・3号艇のどちらが先に攻めるか、展示を見て決めてみて",
        "numbers": {"share": share, "d_cell": d_cell, "same_pop_1": list(sp1) if sp1 else None, "same_pop_23": list(sp23) if sp23 else None,
                    "c5": c5, "upset": m_both["upset"], "upset_ref": m_both["upset_ref"]},
    }


def t_season(ent, r):
    """夏はインが弱い? 季節で決まり手は変わる? 展示タイムは?"""
    x = r.copy()
    ds = pd.to_datetime(x["date"]); x["mon"] = ds.dt.month
    km = pd.to_numeric(x["kimarite"], errors="coerce")
    x["mk"], x["sa"] = km.isin([3, 4]).astype(float), (km == 2).astype(float)
    exm = ent.assign(mon=pd.to_datetime(ent["date"]).dt.month).groupby("mon")["exhibit_time"].mean()
    summer, spring = x["mon"].isin([7, 8]), x["mon"].isin([3, 4])
    m1 = measure(x, summer, ref=spring); m1["ref_label"] = "3・4月"
    m2 = measure(x, summer, ref=spring, col="mk", qcol="_none"); m2.update({"ref_label": "3・4月", "subject": "まくり・まくり差し", "verb": "決まる"})
    v1, v2 = verdicts(m1), verdicts(m2)
    g = x.groupby("mon").agg(in1=("c1", "mean"), mk=("mk", "mean"), sa=("sa", "mean"), n=("c1", "size"))
    tbl = [[f"{mo}月", f"{_rate(q.in1)}", f"{_rate(q.mk)}", f"{_rate(q.sa)}", f"{exm.get(mo, np.nan):.2f}秒"] for mo, q in g.iterrows()]
    lo_m, hi_m = int(g["in1"].idxmin()), int(g["in1"].idxmax())
    ex_gap = float(exm.max() - exm.min())
    d1 = (m1["in1"] - m1["in1_ref"]) * 100
    known = v1.get("edge") == 0
    return {
        "id": "season", "title": "夏はインが弱い?", "belief": "夏はモーターのパワーが落ちて、インが残せない。まくりが決まるのは夏",
        "subject": "1号艇", "compare": "3・4月",
        "lead": f"月ごとに数えると、1号艇がいちばん勝つのは{hi_m}月({_rate(g.loc[hi_m, 'in1'])})、いちばん勝てないのは{lo_m}月({_rate(g.loc[lo_m, 'in1'])})。"
                f"7・8月と3・4月をくらべると、1号艇の勝ちは{_diff_words(m1, '勝つ')}、まくり・まくり差しは{_diff_words(m2, '決まる')}。"
                f"展示タイムは、いちばん速い月といちばん遅い月で{ex_gap:.2f}秒ちがう(夏は空気が薄く、エンジンの力が落ちる)。",
        "conclusion": [("本当。夏はインが少し弱い" if d1 <= -1 else "ほぼ同じ。季節の差は小さい") + ("。でも人気どおり" if known else ""),
                       f"夏(7・8月)は春(3・4月)より、1号艇の勝ちが{_rate_change(m1['in1'], m1['in1_ref'], ref_label='春の')}、まくりが少し増える。展示タイムも夏は遅い。ただ、風や波のほうが差はずっと大きい"],
        "tables": [("月ごとの成績(%。展示タイムは全艇の平均)", tbl, ["月", "1号艇の1着", "まくり・まくり差し", "差し", "展示タイム"])],
        "measures": [("夏(7・8月)の1号艇", m1, v1), ("夏(7・8月)のまくり・まくり差し", m2, v2)],
        "rules": ["展示タイム: 直線をまっすぐ走るタイム。小さいほど速い。季節(気温・湿度・気圧)でエンジンの力が変わる",
                  "月の差は、どの月もすべての場で開かれているので、場のちがいはほぼならされている"],
        "faq": [("なぜ夏はインが弱い?", "暑いと空気が薄くなって、エンジンの力が落ちる。1コースは1マークで減速しすぎると外から握られやすい……と言われる。数字で言えるのは『夏は展示タイムが遅く、まくりが少し増える』まで"),
                ("冬は?", f"冬は展示タイムが速い。1号艇の勝ちは、1年の真ん中くらい"),
                ("季節と風、どっちが大きい?", "風のほうがずっと大きい。風5m以上だと1号艇の勝ちは8ポイントほど下がる(検証ラボ『風が強い日は、インが弱い?』)。季節は1〜2ポイント")],
        "use": ["夏はインを少しだけ疑う。でも風と波を見るほうが先", "展示タイムは季節で全体が速く・遅くなる。くらべるときは同じ日のほかの艇と"],
        "mikata": "夏の水面はキラキラして、まくりが決まるとほんとに気持ちいい。季節で少しずつ顔が変わるの、おもしろいね",
        "gen": "夏はパワーが落ちる、ってのは昔からの常識よ。数字でもちゃんと出てるじゃねえか",
        "challenge": "同じ選手の展示タイムを、夏と冬でくらべてみよう(ミカタの選手カードで)。季節でどれくらい変わるかな",
        "numbers": {"by_month": {int(k): {"in1": float(q.in1), "mk": float(q.mk), "sa": float(q.sa)} for k, q in g.iterrows()}, "ex_gap": ex_gap},
    }


def _accident(ent):
    """選手ごと・審査期間ごとの『事故率の目安』(その走より前の事故点÷出走回数)。
    事故点は非公式の目安(F・選手責任の出遅れ20、選手責任の欠場・失格10、妨害失格15)。待機行動違反などの点はデータに無いので入らない。
    審査期間: 5/1〜10/31(A)、11/1〜4/30(B)。期末=期の最後の6週間。"""
    e = ent.copy(); e["rc"] = e["result_code"].astype(str); e["dt"] = pd.to_datetime(e["date"])
    mo, yr = e["dt"].dt.month, e["dt"].dt.year
    e["per"] = np.where(mo.between(5, 10), yr.astype(str) + "A", (yr + (mo >= 11)).astype(str) + "B")
    e["pts"] = e["rc"].map({"F": 20, "L1": 20, "K1": 10, "S1": 10, "S2": 15}).fillna(0)
    e["cnt"] = e["rc"].isin(["01", "02", "03", "04", "05", "06", "F", "L1", "K1", "S1", "S2"]).astype(float)
    e = e.sort_values(["racer_id", "dt", "rno"])
    g = e.groupby(["racer_id", "per"])
    cp, cc = g["pts"].cumsum() - e["pts"], g["cnt"].cumsum() - e["cnt"]
    e["acc_rate"] = cp / cc.where(cc >= 20)
    end = pd.to_datetime(np.where(e["per"].str.endswith("A"), e["per"].str[:4] + "-10-31", e["per"].str[:4] + "-04-30"))
    e["days_left"] = (end - e["dt"]).dt.days
    e["per_end"] = e["days_left"].between(0, 42)
    k = e.groupby("racer_id").cumcount()
    last = k.where(e["rc"].isin(["F", "L1"])).groupby(e["racer_id"]).ffill().groupby(e["racer_id"]).shift(1)
    e["f_since"] = (k - last).fillna(999)
    st = e["st"].where(e["st"].between(0, 0.6) & (e["st_flag"] != "F"))
    e["st_dev"] = st - st.groupby(e["racer_id"]).transform("mean")
    return e


def t_penalty(ent, r):
    """減点と失格ってなに? 期末の事故率は予想を変える?"""
    e = _accident(ent)
    nr = r["race_id"].nunique()
    per1000 = lambda c: (e["rc"] == c).sum() / nr * 1000  # noqa: E731
    codes = e.groupby("race_id")["rc"].agg(lambda q: set(q))
    xr = r.copy(); cs = xr["race_id"].map(codes)
    xr["hasS"] = cs.map(lambda q: isinstance(q, set) and bool(q & {"S0", "S1", "S2"}))
    mu = measure(xr, xr["hasS"], ref=~xr["hasS"], col="upset", qcol="_none")
    mu.update({"ref_label": "失格のないレース", "subject": "万舟", "verb": "出る", "unit": "レース"})
    # 選手単位: 期末×事故率(F後40走は除く。F直後の慎重さと分けるため)
    x = _adj(ent).join(e.set_index(["race_id", "lane"])[["acc_rate", "per_end", "f_since", "st_dev"]], on=["race_id", "lane"])
    ok = x["f_since"] > 40
    hi_end, lo_end = ok & x["per_end"] & (x["acc_rate"] >= 0.5), ok & x["per_end"] & (x["acc_rate"] < 0.3)
    hi_mid, lo_mid = ok & ~x["per_end"] & (x["acc_rate"] >= 0.5), ok & ~x["per_end"] & (x["acc_rate"] < 0.3)
    me, mm = measure(x, hi_end, ref=lo_end), measure(x, hi_mid, ref=lo_mid)
    me.update({"ref_label": "期末・事故率が低い人", "subject": "その選手", "verb": "3着以内に入る", "unit": "走"})
    mm.update({"ref_label": "期の途中・低い人", "subject": "その選手", "verb": "3着以内に入る", "unit": "走"})
    st_e = float(x.loc[hi_end, "st_dev"].mean() - x.loc[lo_end, "st_dev"].mean())
    st_m = float(x.loc[hi_mid, "st_dev"].mean() - x.loc[lo_mid, "st_dev"].mean())
    tbl = []
    for lo, hi, nm in ((0, 0.2, "0.2未満"), (0.2, 0.4, "0.2〜0.4"), (0.4, 0.55, "0.4〜0.55"), (0.55, 0.7, "0.55〜0.7"), (0.7, 99, "0.7以上")):
        a = ok & x["per_end"] & x["acc_rate"].between(lo, hi, inclusive="left")
        b = ok & ~x["per_end"] & x["acc_rate"].between(lo, hi, inclusive="left")
        sd = lambda m_: (lambda v: "ほぼ同じ" if abs(v) < 0.003 else f"{abs(v):.3f}秒{'遅い' if v > 0 else '早い'}")(x.loc[m_, "st_dev"].mean())  # noqa: E731
        tbl.append([nm, sd(a), _rate(x.loc[a, 'c1'].mean()), sd(b), _rate(x.loc[b, 'c1'].mean())])
    ctbl = [["フライング(F)", f"{per1000('F') / 10:.1f}回", "返還。休み(1本目30日)と事故点"], ["選手の責任の失格(転覆・落水など)", f"{per1000('S1') / 10:.1f}回", "返還なし。減点5点(実例)"],
            ["妨害失格", f"{per1000('S2') / 10:.1f}回", "返還なし。賞典除外(実例)"], ["責任のない失格(ぶつけられた等)", f"{per1000('S0') / 10:.1f}回", "返還なし。減点なし"],
            ["欠場", f"{(per1000('K0') + per1000('K1')) / 10:.1f}回", "返還"], ["出遅れ(L)", f"{(per1000('L0') + per1000('L1')) / 10:.1f}回", "返還"]]
    d_e = (me["in1"] - me["in1_ref"]) * 100
    return {
        "id": "penalty", "title": "減点と失格ってなに? 期末の『事故率』は予想を変える?",
        "belief": "失格や減点なんて、たまにしか起きねえ。予想にはほとんど関係ないだろ",
        "subject": "その選手", "verb": "3着以内に入る", "no_market": True, "unit": "走",
        "lead": f"失格は100レースに約{(per1000('S0') + per1000('S1') + per1000('S2')) / 10:.0f}回、フライングは約{per1000('F') / 10:.0f}回。失格が出たレースは万舟が{_rate(mu['in1'])}(ほかは{_rate(mu['in1_ref'])})。"
                f"そして予想に効くのは『事故率』。いまは10月=審査期間の終わり。事故率がボーダー(0.70)に近い選手は、期末になると本人のふだんよりスタートが{abs(st_e):.3f}秒遅く、"
                f"3着以内も{_rate_change(me['in1'], me['in1_ref'], ref_label='期の途中の')}(フライングの直後の人は除いて)。期の途中では、差はずっと小さい。",
        "conclusion": ["ウソ。期末は事故率が予想を変える",
                       f"10月・4月の終わりは、事故率が0.5を超えた選手が安全運転になる。スタートは{abs(st_e):.3f}秒(約{abs(st_e) * 2000:.0f}cm)遅く、3着以内は{_rate_change(me['in1'], me['in1_ref'])}。"
                       "B2級に落ちないための、もっともな作戦"],
        "tables": [("失格・欠場は、100レースに何回?", ctbl, ["できごと", "100レースあたり", "舟券と罰"]),
                   ("事故率の目安ごとの、スタート(本人のふだんとくらべて)と3着以内。F直後の人は除く", tbl, ["事故率", "期末のST", "期末の3着以内(100走)", "期の途中のST", "期の途中の3着以内"])],
        "measures": [("期末に、事故率が0.5以上", me, verdicts(me)), ("期の途中で、事故率が0.5以上", mm, verdicts(mm)), ("失格が出たレースの万舟", mu, verdicts(mu))],
        "rules": ["欠場: スタートまでの理由(フライング・出遅れ・待機行動中の転覆・病気など)で走らなかった艇。その艇がからむ舟券はお金が返ってくる(返還)",
                  "失格: スタートしたあとの理由(転覆・落水・エンスト・周回の間違い・妨害など)。舟券は返ってこない",
                  "減点: 節の得点(予選の成績)から引かれる点。待機行動違反と不良航法は7点、選手の責任の転覆・落水は5点(公式の実例)。妨害失格は、その節の優勝争いから外される(賞典除外)",
                  "待機行動: ピットを出てからスタートまでの動き(コース取りを含む)。蛇行や他艇のじゃま、モーターを止めることなどが禁止。破ると待機行動違反",
                  "事故率: 半年(5/1〜10/31、11/1〜4/30)の事故点の合計÷出走回数。0.70を超えると、勝率に関係なくB2級に落ちる(公式)。事故点はF・出遅れが20点など。この記事の事故率は成績から計算した目安(待機行動違反などの点は入っていない)"],
        "faq": [("待機行動違反って、どんなとき?", "ピットを出てからスタートまでの間に、ほかの艇の進路をふさぐ、決められた動きをしない、モーターを止める、など。節の得点から7点引かれる。舟券は返ってこないし、失格にもならない"),
                ("失格した艇の舟券は?", "返ってこない。フライングや出遅れ(欠場)は返ってくる。だから失格が出たレースは、残った艇で決まって高い配当になりやすい"),
                ("賞典除外って?", "その節の準優勝戦・優勝戦に進めなくなること。妨害失格などで起きる。除外されても、残りのレースは走る"),
                ("期末の事故率はどこで分かる?", "いちばんの手がかりは、出走表の『F1』『F2』などのフライングの数(Fは1本で20点ほど)。今期の出走回数が少ない人ほど、1本のFで事故率が大きく上がる。10月と4月の終わりは、そういう人のスタートを少し控えめに見る")],
        "use": ["10月・4月の終わりは、今期にFや失格がある選手(事故率0.5以上が目安)のスタートを控えめに見る", "失格・減点はレース前には分からない。分かるのは『今期のFの数』と『F持ち』。こっちを見る"],
        "mikata": "期末の安全運転は、選手が級を守るための大事な作戦。数字の裏に、ちゃんと理由があるのがおもしろいね",
        "gen": "期末のベテランは無理しねえ、ってのは知ってたけどよ。数字で出ると、なるほどってなるな",
        "challenge": "10月の終わりまで、出走表で事故率の高い選手を1人見つけて、その人のスタート(ST)を毎レース見てみよう",
        "numbers": {"per1000": {c: float(per1000(c)) for c in ("F", "S0", "S1", "S2", "K0", "K1", "L0", "L1")}, "st_end": st_e, "st_mid": st_m},
    }


def _st_usual(ent):
    """その走より前の60走の平均ST(フライングを除く、20走以上)。レースID×枠の表で返す。"""
    e = ent.copy(); e["dt"] = pd.to_datetime(e["date"]); e = e.sort_values(["racer_id", "dt", "rno"])
    st = e["st"].where(e["st"].between(0, 0.6) & (e["st_flag"] != "F"))
    e["stu"] = st.groupby(e["racer_id"]).transform(lambda q: q.shift(1).rolling(60, min_periods=20).mean())
    return e.drop_duplicates(["race_id", "lane"]).set_index(["race_id", "lane"])["stu"]


def t_slowdash(ent, r):
    """なんでスローとダッシュがあるの? 『カド』って? カドの一撃はいつ来る?"""
    KM = {1: "逃げ", 2: "差し", 3: "まくり", 4: "まくり差し", 5: "抜き", 6: "恵まれ"}
    e = ent[ent["finish"].notna() & ent["course"].notna()].copy()
    e["st_ok"] = e["st"].where(e["st"].between(0, 0.6) & (e["st_flag"] != "F"))
    e["win"] = (e["finish"] == 1).astype(float)
    e["slit1"] = (e.groupby("race_id")["st_ok"].rank(method="min") == 1).astype(float)
    e["km"] = pd.to_numeric(e["race_id"].map(r.set_index("race_id")["kimarite"]), errors="coerce").map(KM)
    nari_act = e.groupby("race_id").apply(lambda g: bool((g["course"] == g["lane"]).all()))
    en = e[e["race_id"].map(nari_act)]
    g = en.groupby("course").agg(st=("st_ok", "mean"), slit1=("slit1", "mean"), win=("win", "mean"))
    tbl = []
    for c in range(1, 7):
        top = en[(en["win"] == 1) & (en["course"] == c)]["km"].value_counts(normalize=True)
        tbl.append([f"{c}" + ("スロー" if c <= 3 else "ダッシュ"), f"{g.loc[c, 'st']:.3f}", _rate(g.loc[c, 'slit1']), _rate(g.loc[c, 'win']),
                    f"{top.index[0]} {_rate(top.iloc[0])}" if len(top) else "-"])
    mk4 = float(en[(en["win"] == 1) & (en["course"] == 4)]["km"].isin(["まくり", "まくり差し"]).mean())
    # カドの一撃: 展示で枠なり(=ふつうの3対3が多い)のレースで、4コースの選手のふだんのSTが内の3人より速いとき
    stu = _st_usual(ent)
    exn = ent.groupby("race_id").apply(lambda q: bool((q["ex_course"] == q["lane"]).all() and len(q) == 6))
    x = r.copy(); x["nari"] = x["race_id"].map(exn).fillna(False).astype(bool)
    for k in range(1, 5):
        x[f"stu{k}"] = stu.reindex(pd.MultiIndex.from_arrays([x["race_id"], pd.Series(k, index=x.index)])).values
    x["w4"] = (x["win_lane"] == 4).astype(float)
    gap = x["stu4"] - x[["stu1", "stu2", "stu3"]].min(axis=1)       # マイナス=カドが内の誰よりも速い
    gap3 = x["stu4"] - x["stu3"]
    fast, even = x["nari"] & (gap <= -0.02), x["nari"] & (gap3.abs() < 0.01)
    m4 = measure(x, fast, ref=even, col="w4", qcol="q_l4")
    m4.update({"ref_label": "カドとカド受けが同じくらい", "subject": "4コース(カド)", "verb": "1着になる"})
    m1 = measure(x, fast, ref=even)
    m1.update({"ref_label": "カドとカド受けが同じくらい", "subject": "1号艇", "verb": "1着になる"})
    v4, v1 = verdicts(m4), verdicts(m1)
    beat = v4.get("edge") == 1
    return {
        "id": "slowdash", "title": "なんでスローとダッシュがあるの? 『カド』って?",
        "belief": "内の艇は助走が短くて損してる。ダッシュのほうが勢いがあって有利だろ。4カドからの一撃がいちばん気持ちいい",
        "subject": "4コース(カド)", "unit": "レース",
        "x1": f"4号艇のSTが内の3人より速い『カドの一撃』の形なら、カドの1着は{_rate(m4['in1'])}。ふだんは{_rate(m4['in1_ref'])}。",
        "lead": f"競艇のスタートは、大時計の針が0〜1秒の間に、走りながらスタートラインを越える『フライングスタート』。モーターは止められないので、"
                f"内のコースを取りたい艇は早めに位置について助走が短い『スロー』、外の艇は大きく後ろに下がって助走をとる『ダッシュ』になる。ダッシュのいちばん内側が『カド』。"
                f"ふつうの並び(1〜3コースがスロー、4〜6コースがダッシュ)で、4コース=カドが勝つのは{_rate(g.loc[4, 'win'])}。勝つときの10回に{round(mk4 * 10)}回は、まくりかまくり差し。"
                f"そして、カドの選手のふだんのスタートが内の3人より速いとき、カドの1着は{_rate(m4['in1'])}にはね上がる"
                + ("。しかも人気以上に来る。" if beat else "。"),
        "conclusion": [("本当。カドの一撃は、条件がそろうと人気以上に来る" if beat else "本当。カドの一撃は、条件がそろうと来る"),
                       f"ふだんは1コースがいちばん強い({_rate(g.loc[1, 'win'])})。でも、カドの選手のスタートが内の3人より速いと、カドが{_rate(m4['in1'])}、1号艇は{_rate(m1['in1'])}。"
                       "スリットでカドがのぞいた瞬間が、いちばん熱い"],
        "tables": [("ふつうの並び(枠なり)のときの、コースごとの数字(%)。勝ち方は勝ったときのうち何%か", tbl, ["コース", "平均ST(秒)", "スリット一番前", "1着", "多い勝ち方"])],
        "measures": [("カドの選手のふだんのSTが、内の3人の誰よりも0.02秒以上速い", m4, v4), ("そのときの1号艇", m1, v1)],
        "rules": ["フライングスタート: 大時計の針が0〜1秒を指す間にスタートラインを通る。0秒より早いとフライング、1秒より遅いと出遅れで、どちらも欠場(舟券は返還)",
                  "スロー: スタートの向きに近い位置から、短い助走で出る。インコースを主張する艇が多い。ダッシュ: スタートと反対向きに大きく引っぱって、長い助走で出る(公式の用語解説)",
                  "カド: ダッシュの艇のうち、いちばん内側。まくり・まくり差しを最初に打ちやすい場所。ふつうは4コースで『4カド』。カドのひとつ内(ふつうは3コース)は『カド受け』と呼ばれる",
                  "ST(スタートタイミング): 0秒からスタートラインを通るまでの時間。小さいほど早い。ダッシュの艇は、STが同じでも勢い(スピード)がついた状態でラインを越える",
                  "『ふだんのST』は、その選手の直前60走の平均(フライングを除く)。展示の進入が枠なりのレースで調べた"],
        "faq": [("なんでわざわざ助走が短いスローにするの?", "内のコースを取るため。内ほど1マークまでの距離が短く、まわって先頭に立ちやすい。そのかわり、内を取り合うと助走がどんどん短くなる(深くなる)"),
                ("STは1コースがいちばん早いのに、ダッシュが有利?", f"STはタイミングの数字。1コースの平均は{g.loc[1, 'st']:.3f}秒、4コースは{g.loc[4, 'st']:.3f}秒でほぼ同じ。でもダッシュの艇は全速でラインを越えるので、スリットのあと伸びて前に出やすい。だからカドはまくりが多い"),
                ("カド受けって?", "カドのすぐ内側の艇(ふつうは3コース)。カドが伸びてくると最初に叩かれる位置なので、カド受けのスタートが遅いと、カドの一撃が決まりやすい"),
                ("人気どおり?", ("カドの選手のスタートが速いレースでは、カドの1着は人気以上、1号艇は人気のわりにひかえめだった。" if beat else "だいたい人気どおり。") + "スタートの速さの『差』は、出走表のぱっと見では気づきにくいのかも")],
        "use": ["出走表で、4号艇の平均STと、1〜3号艇の平均STをくらべる。4号艇がいちばん速ければ『カドの一撃』に注意",
                "展示の進入が枠なりかどうかも見る。4号艇がカドにいないと、この話は使えない"],
        "mikata": "大時計の針が回って、スリットでカドがスッと出てくる瞬間。競艇でいちばん鳥肌が立つところだよね",
        "gen": "4カドのまくりこそ競艇の華よ! スタートの速いやつがカドにいたら、俺はそこから買う。……数字のお墨付きまでもらったな",
        "challenge": "次のレースで、展示の前に『カドの選手のふだんのST』と『カド受けのふだんのST』をくらべて予想。スリットで答え合わせ",
        "numbers": {"by_course": {int(c): {"st": float(q.st), "slit1": float(q.slit1), "win": float(q.win)} for c, q in g.iterrows()}, "mk4": mk4},
    }


def t_formation(ent, r):
    """オールスロー・オールダッシュって何が起きてる? 隊形がくずれたら?(隊形そのものの記録はないので、外の艇が内に入ったレースで見る)"""
    e = ent[ent["course"].notna()].copy()
    e["st_ok"] = e["st"].where(e["st"].between(0, 0.6) & (e["st_flag"] != "F"))
    exc = e.pivot_table(index="race_id", columns="lane", values="ex_course", aggfunc="first")
    six_in = exc.get(6)
    five_in = exc.get(5)
    x = r.copy()
    x["six"] = x["race_id"].map(six_in); x["five"] = x["race_id"].map(five_in)
    nari = exc.eq(pd.Series(range(1, 7), index=range(1, 7)), axis=1).all(axis=1) if exc.shape[1] == 6 else None
    x["nari"] = x["race_id"].map(nari).fillna(False).astype(bool)
    deep = (x["six"] <= 3) | (x["five"] <= 2)
    mid = ((x["six"] == 4) | (x["five"] == 3)) & ~deep
    win = ent[ent["finish"] == 1].drop_duplicates("race_id").set_index("race_id")["course"]
    x["wc"] = x["race_id"].map(win)
    x["c4win"] = (x["wc"] == 4).astype(float)
    x["c56win"] = x["wc"].isin([5, 6]).astype(float)
    c1st = e[e["course"] == 1].drop_duplicates("race_id").set_index("race_id")["st_ok"]
    x["c1st"] = x["race_id"].map(c1st)
    m1 = measure(x, deep, ref=x["nari"], col="cc1", qcol="qc1")
    m1.update({"ref_label": "枠なり", "subject": "1コースの艇", "verb": "1着になる"})
    mu = measure(x, deep, ref=x["nari"], col="upset", qcol="_none")
    mu.update({"ref_label": "枠なり", "subject": "万舟", "verb": "出る"})
    m4 = measure(x, deep, ref=x["nari"], col="c4win", qcol="_none")
    m4.update({"ref_label": "枠なり", "subject": "4コース", "verb": "1着になる"})
    rows = []
    for nm, mk in (("枠なり", x["nari"]), ("少し内へ", mid), ("深く内へ", deep)):
        q = x[mk]
        rows.append([nm, f"{len(q):,}", _rate(q['cc1'].mean()), _rate(q['c4win'].mean()), f"{q['c1st'].mean():.3f}", _rate(q['upset'].mean())])
    share_deep = float(deep.mean())
    st_gap = float(x.loc[deep, "c1st"].mean() - x.loc[x["nari"], "c1st"].mean())
    return {
        "id": "formation", "title": "オールスロー・オールダッシュって何が起きてる?",
        "belief": "前づけ合戦でみんながスローになったら、インの艇は助走がなくなってボロボロ。外のダッシュが一気にくる",
        "subject": "1コースの艇", "unit": "レース",
        "lead": f"ふつうは1〜3コースがスロー、4〜6コースがダッシュの『3対3』。外の艇が前づけで内に入ってくると、スローの艇が増えて4対2、5対1、全員がスローの『オールスロー(6対0)』になることがある。"
                f"隊形そのものの記録は公式の成績に無いので、スタート展示で外の艇が深く内に入ったレース({_rate(share_deep)}のレース)で調べた。"
                f"このとき1コースの艇の1着は{_rate(m1['in1'])}(枠なりは{_rate(m1['in1_ref'])})、1コースのSTは{abs(st_gap):.3f}秒遅くなり、4コースの1着が{_rate(m4['in1'])}(枠なり{_rate(m4['in1_ref'])})に増える。",
        "conclusion": ["本当。インが深くなると、1コースは苦しい",
                       f"外の艇が内に入ってスローが増えると、1コースは助走が短くなってSTが遅れ、1着は{_rate(m1['in1'])}まで下がる。代わりに4コースの1着が増え、万舟も増える({_rate(mu['in1'])})。ここは、だいたい人気どおり"],
        "tables": [("展示の進入ごとの数字(%。STは1コースの艇の平均)", rows, ["展示の進入", "レース数", "1コース1着", "4コース1着", "1コースST(秒)", "万舟"])],
        "measures": [("外の艇が深く内へ: 1コースの艇", m1, verdicts(m1)), ("外の艇が深く内へ: 4コース", m4, verdicts(m4)), ("外の艇が深く内へ: 万舟", mu, verdicts(mu))],
        "rules": ["進入隊形は『3対3』のように書き、最初の数字がスローの艇の数(公式の用語解説)",
                  "4対2: スローが4艇、ダッシュが2艇(5コースがカド)。5対1: ダッシュは6コースだけ。オールスロー(6対0): 全員スロー。どれも、外の艇の前づけで内を取り合うと起きやすい",
                  "オールダッシュ: 全員が大きく下がる形。1コースの艇には下がる理由がないので、ふつうは見ない。内の艇も下がって『2対4』(3コースがカド)になることはある",
                  "この記事の『深く内へ』は、スタート展示で6号艇が3コースより内、または5号艇が2コースに入ったレース。『少し内へ』は6号艇が4コース、または5号艇が3コース。本番の進入は展示とちがうこともある(展示どおりは約9割)"],
        "faq": [("オールスローだと誰が得をする?", "全員が助走の短いスタートになるので、短い助走でもスタートを決められる人が有利、と言われる。データで言えるのは、外の艇が深く入るとインのSTが遅れ、1コースの1着が減ること"),
                ("どんなときに起きる?", "前づけが得意な選手が外の枠にいるとき。どうしても内が欲しい場面(予選の勝負どころなど)で起きやすいと言われる。前づけする選手は、時期を変えてもほぼ同じ顔ぶれ(検証ラボ『前づけは本当に得なのか』)"),
                ("展示で深くなったら、本番も?", "展示と本番の進入がちがうのは約1割。展示で前づけがあったレースでも、本番で同じ並びは3回に2回ほど(検証ラボ『スタート展示の進入は信じていい?』)")],
        "use": ["スタート展示で外の艇が深く入ってきたら、1号艇の頭を少し疑う。4コースに入った艇と、助走をとれる外の艇を見る", "万舟が増えるレース。人気の1号艇から買うなら、配当とのバランスで"],
        "mikata": "ピットを出てから進入が決まるまでの数十秒、どの艇がどこに入るかを見守るのも競艇の楽しみ。展示で並びが崩れたら、もう一段ワクワクしていいよ",
        "gen": "オールスローなんて見た日には、もう手に汗にぎるよ。インの選手、助走ほとんどねえんだぞ",
        "challenge": "スタート展示で、外の艇が内に入ってくるレースを見つけたら、本番の並びと1コースのSTを予想してみよう",
        "numbers": {"share_deep": share_deep, "st_gap": st_gap},
    }


def t_samefin(ent, r):
    """同じ着順が続くと買いたくなる。3着がずっと6号艇……に理由はある? 選手の気持ちは?"""
    x = r[r["tri_combo"].astype(str).str.match(r"^[1-6]-[1-6]-[1-6]$")].copy().sort_values(["date", "jcd", "rno"])
    tc = x["tri_combo"].astype(str).str.split("-", expand=True).astype(int)
    x["p3"], x["p2"] = tc[2].values, tc[1].values
    x["mon"] = pd.to_datetime(x["date"]).dt.month
    g = x.groupby(["date", "jcd"])
    x["p3_prev"], x["p3_prev2"] = g["p3"].shift(1), g["p3"].shift(2)
    cell = pd.crosstab([x["jcd"], x["mon"], x["rno"]], x["p3"], normalize="index")
    P = cell.reindex(pd.MultiIndex.from_arrays([x["jcd"], x["mon"], x["rno"]])).values
    ok = x["p3_prev"].notna().values
    idx = x["p3_prev"].fillna(1).astype(int).values - 1
    expv = P[np.arange(len(x)), idx]
    act = (x["p3"] == x["p3_prev"]).astype(float).values
    ok2 = ok & (x["p3_prev"] == x["p3_prev2"]).values

    def _m(mask, label):
        a_, e_ = act[mask], expv[mask]
        d = a_ - e_
        rng = np.random.default_rng(0)
        bt = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(300)]
        late = x["late"].values[mask]
        m_ = {"n": int(mask.sum()), "in1": float(a_.mean()), "in1_ref": float(e_.mean()), "upset": 0.0, "upset_ref": 0.0,
              "in1_ci": [float(e_.mean() + np.quantile(bt, 0.05) + (a_.mean() - e_.mean() - d.mean())), float(e_.mean() + np.quantile(bt, 0.95) + (a_.mean() - e_.mean() - d.mean()))],
              "half": [float(d[~late].mean()), float(d[late].mean())], "ref_label": label, "subject": "前と同じ枠", "verb": "3着になる", "unit": "レース"}
        return m_
    m1, m2 = _m(ok, "見込み(番組と場・季節から)"), _m(ok2, "見込み(番組と場・季節から)")
    # 1日12レースのどこかで、同じ枠が3レース続けて3着になる日は?
    run3 = x.assign(s1=(x["p3"] == x["p3_prev"]) & (x["p3"] == x["p3_prev2"])).groupby(["date", "jcd"])["s1"].any()
    days12 = x.groupby(["date", "jcd"]).size() >= 12
    share_run3 = float(run3[days12].mean())
    # 選手: 同じ節で2走続けて同じ着順 → 次も?
    e = ent[ent["finish"].between(1, 6)].copy(); e["dt"] = pd.to_datetime(e["date"]); e = e.sort_values(["racer_id", "dt", "rno"])
    gg = e.groupby("racer_id")
    same = (gg["jcd"].shift(1) == e["jcd"]) & (gg["jcd"].shift(2) == e["jcd"]) & ((e["dt"] - gg["dt"].shift(2)).dt.days <= 4)
    e["late"] = e["dt"].dt.year >= 2025; e["upset"] = 0.0; e["date"] = e["date"].astype(str)
    rows, ms_r = [], []
    for f in (1, 3, 6):
        hit = (e["finish"] == f).astype(float)
        res = hit - hit.groupby(e["course"]).transform("mean")
        e[f"c{f}"] = float(hit.mean()) + res - res.groupby(e["racer_id"]).transform("mean")
        mk = same & (gg["finish"].shift(1) == f) & (gg["finish"].shift(2) == f)
        m_ = measure(e, mk, ref=same & ~mk, col=f"c{f}", qcol="_none")
        m_.update({"ref_label": "その人のふだん", "subject": "その選手", "verb": f"{f}着になる", "unit": "走"})
        ms_r.append((f"同じ選手が、今節2走続けて{f}着", m_, verdicts(m_)))
    d1 = (m1["in1"] - m1["in1_ref"]) * 100
    v1, v2 = verdicts(m1), verdicts(m2)
    return {
        "id": "samefin", "title": "同じ着順が続くと、つい買いたくなる。理由はある?",
        "belief": "3着がずっと6号艇の日がある。そういう日は流れが来てるんだ。次も6を3着に置けば当たる",
        "subject": "前と同じ枠", "verb": "3着になる", "no_market": True, "unit": "レース",
        "lead": f"同じ日・同じ場で、前のレースと同じ枠が3着に来るのは{m1['in1'] * 100:.1f}%。レース番号(番組)と場・季節から見込めるのは{m1['in1_ref'] * 100:.1f}%で、ほぼ同じ。"
                f"2レース続けて同じ枠が3着だったあとも{m2['in1'] * 100:.1f}%(見込み{m2['in1_ref'] * 100:.1f}%)。ところが、1日12レースのどこかで『同じ枠が3レース続けて3着』になる日は、{fun_rate(share_run3)}ある。"
                "続くのは、偶然でもよく起きることだった。",
        "conclusion": ["ほぼ偶然。でも『続いて見える』のは当たり前",
                       f"3着の枠が続いても、次のレースで同じ枠が3着になる回数は見込みとほぼ同じ。そもそも、どこかで3連続が起きる日は{fun_rate(share_run3)}。人の目は『続き』を見つけるのが得意なだけ"],
        "tables": [],
        "measures": [("前のレースと同じ枠が3着", m1, v1), ("2レース続けて同じ枠が3着のあと", m2, v2)] + ms_r,
        "rules": ["くらべ方: レース番号ごとの番組のくせ(検証ラボ『番組屋の癖は本物か』)と、場・月で、その枠が3着になる見込みを出し、実際とくらべた",
                  "レースごとに出る選手はちがう。同じ選手が続けて走ることはほとんどない",
                  "選手の欄は、同じ節で前の2走が同じ着順だった選手の、次の走(コースの有利不利を差し引き、本人のふだんとくらべた)"],
        "faq": [("選手の気持ちで続くことはある?", "3着が続く日は、レースごとに選手がちがうので、気持ちはつながらない。同じ選手で見ると、2走続けて3着の人が次も3着になるのはふだんとほぼ同じ。"
                 "ただ、2走続けて6着の人は次も6着が多い。気持ちというより、その節のモーターの足が足りないサイン(検証ラボ『今節2連勝中の選手は、次も来る?』)"),
                ("じゃあ続いている枠は買わないほうがいい?", "買っても買わなくても、来る確率はふだんと同じ。『流れ』で買うのは、当たっても外れても楽しい遊び方としてならアリ"),
                ("1着も続かない?", "1着(イン逃げ)は少し続く。理由はおもに番組の組み方(検証ラボ『イン逃げが続いたあとは荒れるのか』)")],
        "use": ["3着の枠が続いても、次のレースの見方は変えなくていい", "見るべきは同じ選手の『今節の着順』。大敗が続く人は、足が足りないかも"],
        "mikata": "続きを見つけると、人はつい物語を作りたくなる。でもそれが競艇の楽しさでもあるよね。数字は『偶然でもよくあるよ』って教えてくれる",
        "gen": "ずっと6が3着に来てたら、そりゃ乗るだろ! ……え、ふつうの日でも、どこかでは3回続くのか。なんだ、俺がたまたま見てただけか",
        "challenge": "次に現地に行ったら、1Rから3着の枠をメモしよう。3回続いたら、それは『よくある偶然』。次の3着を当ててみて",
        "numbers": {"share_run3": share_run3, "same_prev": [m1["in1"], m1["in1_ref"]], "same_prev2": [m2["in1"], m2["in1_ref"]]},
    }


def _series_types(ent):
    """節(同じ場の連続した開催)ごとに、出場選手の顔ぶれで大会の種類を分ける。過去の大会名・グレードの記録が無いための代わり。"""
    pr = _profiles()
    e = ent.copy()
    d = e.drop_duplicates(["jcd", "date"])[["jcd", "date", "day_no"]].sort_values(["jcd", "date"])
    d["dt"] = pd.to_datetime(d["date"])
    gap = d.groupby("jcd")["dt"].diff().dt.days
    d["new"] = (d["day_no"].fillna(0) <= 1) | (gap > 1) | gap.isna()
    d["sid"] = d["jcd"].astype(str) + "_" + d.groupby("jcd")["new"].cumsum().astype(str)
    e = e.merge(d[["jcd", "date", "sid"]], on=["jcd", "date"])
    p = e.drop_duplicates(["sid", "racer_id"])[["sid", "racer_id", "racer_class", "age"]]
    p["sex"] = p["racer_id"].map(pr["sex"]).astype(str)
    s = p.groupby("sid").agg(acls=("racer_class", lambda q: q.isin(["A1", "A2"]).mean()), fem=("sex", lambda q: (q == "女").mean()),
                             age_max=("age", "max"), age_min=("age", "min"))
    s["type"] = np.select([s["fem"] >= 0.95, s["age_min"] >= 45, s["age_max"] <= 30, s["acls"] >= 0.95],
                          ["女子だけ", "45歳以上だけ", "30歳以下だけ", "A級だけ"], "ふつうの一般戦")
    return d[["jcd", "date", "sid"]], s


def t_series(ent, r):
    """大会ってなにがちがう? SG・G1・女子戦・マスターズ・若手。大会で予想は変わる?"""
    d, s = _series_types(ent)
    x = r.merge(d, on=["jcd", "date"], how="left")
    x["type"] = x["sid"].map(s["type"]).fillna("ふつうの一般戦")
    km = pd.to_numeric(x["kimarite"], errors="coerce")
    x["mk"], x["sa"] = km.isin([3, 4]).astype(float), (km == 2).astype(float)
    base = x["type"] == "ふつうの一般戦"
    order = ["A級だけ", "ふつうの一般戦", "女子だけ", "45歳以上だけ", "30歳以下だけ"]
    g = x.groupby("type").agg(n=("c1", "size"), in1=("c1", "mean"), up=("upset", "mean"), mk=("mk", "mean"), sa=("sa", "mean"))
    tbl = [[t, f"{int(g.loc[t, 'n']):,}", _rate(g.loc[t, "in1"]), _rate(g.loc[t, "up"]), _rate(g.loc[t, "mk"]), _rate(g.loc[t, "sa"])] for t in order if t in g.index]
    ma = measure(x, x["type"] == "A級だけ", ref=base); ma["ref_label"] = "ふつうの一般戦"
    mf = measure(x, x["type"] == "女子だけ", ref=base, col="upset", qcol="_none")
    mf.update({"ref_label": "ふつうの一般戦", "subject": "万舟", "verb": "出る"})
    mm = measure(x, x["type"] == "45歳以上だけ", ref=base); mm["ref_label"] = "ふつうの一般戦"
    va, vf, vm = verdicts(ma), verdicts(mf), verdicts(mm)
    concept = [["SG(年8回)", "その年のトップが集まる最高峰。ダービー・グランプリなど", "勝率・賞金・前の大会の成績などで選ばれる。グランプリは賞金上位18人だけ"],
               ["プレミアムG1", "テーマのある特別な大会", "ヤングダービーは30歳未満、マスターズチャンピオンはベテラン、レディースチャンピオンとクイーンズクライマックスは女子"],
               ["G1", "各場の周年記念、地区選手権など", "原則A級だけ"],
               ["G2・G3", "G1に準じる大会、企業杯、オールレディース(女子)、マスターズリーグ(45歳以上)、イースタン/ウエスタンヤング(30歳未満)", "大会ごとに条件"],
               ["一般戦", "毎日どこかで開催。ルーキーシリーズ(登録6年未満)、ヴィーナスシリーズ(女子)など", "級はいろいろ混ざる"]]
    return {
        "id": "series", "title": "大会ってなにがちがう? SG・G1・女子戦・マスターズ",
        "belief": "大きな大会ほど強い選手どうしで荒れる。女子戦は荒れる。マスターズはベテランぞろいで堅い",
        "subject": "1号艇", "unit": "レース", "compare": "ふつうの一般戦",
        "lead": f"競艇の大会には、SGを頂点にグレードがあり、それぞれにテーマ(コンセプト)がある。過去の大会名の記録は手元に無いので、出場選手の顔ぶれで分けてくらべた。"
                f"全員がA級の大会(G1以上にあたる)では、1号艇が勝つのは{_rate(ma['in1'])}(ふつうの一般戦は{_rate(ma['in1_ref'])})。"
                f"女子だけの大会の万舟は{_rate(mf['in1'])}で、一般戦の{_rate(mf['in1_ref'])}より少ないくらい。45歳以上だけの大会の1号艇は{_rate(mm['in1'])}"
                + ((f"で、人気のわりにひかえめ(オッズのあるレースが{mm.get('n_odds', 0)}レースと少ないので追試中)。" if mm.get("n_odds", 0) < 1500 else "で、人気のわりにひかえめ。") if vm.get("edge") == -1 else "。"),
        "conclusion": ["大きな大会ほどインが堅い。女子戦は荒れない",
                       f"全員A級の大会は1号艇{_rate(ma['in1'])}(一般戦{_rate(ma['in1_ref'])})。スタートも速い(平均で0.03秒ほど)。実力の近い選手どうしだと、1コースの有利さがそのまま出やすいのかも。"
                       f"『女子戦は荒れる』は数字には出ない(万舟は{_rate(mf['in1'])})。どれも、だいたい人気どおり"],
        "tables": [("大会のグレードとコンセプト(公式の用語解説などから)", concept, ["グレード", "どんな大会", "出られる人"]),
                   ("出場選手の顔ぶれ別の数字(%)", tbl, ["大会の顔ぶれ", "レース数", "1号艇の1着", "万舟", "まくり系", "差し"])],
        "measures": [("全員A級の大会(G1以上にあたる)", ma, va), ("女子だけの大会の万舟", mf, vf), ("45歳以上だけの大会", mm, vm)],
        "rules": ["顔ぶれの分け方: 節ごとの出場選手が、全員A級=『A級だけ』(G1以上の大会にあたる)、ほぼ全員女子=『女子だけ』(オールレディース・ヴィーナスシリーズなど)、"
                  "全員45歳以上=『45歳以上だけ』(マスターズ系)、全員30歳以下=『30歳以下だけ』(ヤング系の一部)。それ以外を『ふつうの一般戦』とした",
                  "SGは年8回。グレードはSG・G1・G2・G3・一般の5つ(公式の用語解説)",
                  "これから: G1トーキョー・ベイ・カップ(平和島 10/13〜18)、G1全日本王者決定戦(唐津 10/18〜23)、SGボートレースダービー(尼崎 10/27〜11/1)"],
        "faq": [("ダービーってどんな大会?", "SGのひとつで、長い歴史を持つ大会。今年は尼崎で、52人が出場する(開催場の公式サイトより)。勝率の上位など、1年を通して強かった選手が集まる"),
                ("大きな大会は荒れる?", f"万舟は{_rate(g.loc['A級だけ', 'up'])}と、一般戦({_rate(g.loc['ふつうの一般戦', 'up'])})より少し多い。ただ、1号艇はむしろ堅い。実力が近いぶん、2着・3着がばらけやすいのかも"),
                ("女子戦は荒れるって聞くけど?", f"このデータでは、女子だけの大会の1号艇は{_rate(g.loc['女子だけ', 'in1'])}、万舟は{_rate(g.loc['女子だけ', 'up'])}。一般戦とほぼ同じか、むしろ荒れない"),
                ("マスターズは?", f"1号艇は{_rate(mm['in1'])}。前づけなど進入の駆け引きが増えると言われる。1号艇は{'人気のわりにひかえめかも(追試中)' if vm.get('edge') == -1 else 'だいたい人気どおり'}")],
        "use": ["G1以上の大会は、1号艇の信頼度が上がる。ただし人気どおりなので、2着・3着の組み立てで勝負", "女子戦だからと荒れ目を狙う必要はない"],
        "mikata": "大会ごとにテーマがあって、出る選手もがらっと変わる。大会のコンセプトを知ると、出走表を見るのがもっと楽しくなるよ",
        "gen": "ダービーの季節だな! でかい大会は、やっぱり1号艇の重みがちがう。……数字でもそうなってるのか",
        "challenge": "次のG1の出走表を見て、1号艇に誰が入っているか確認しよう。強い選手が内に来る番組が、何レースあるか数えてみて",
        "numbers": {"by_type": {t: {k: float(g.loc[t, k]) for k in ("in1", "up", "mk", "sa")} | {"n": int(g.loc[t, "n"])} for t in g.index},
                    "series_counts": s["type"].value_counts().to_dict()},
    }


def t_fixed(ent, r):
    """進入固定レースってなに? インは強くなる? それとも番組で強い選手を1号艇に置いているだけ?"""
    fx = ent.drop_duplicates("race_id").set_index("race_id")["fixed_entry"]
    x = r.copy(); x["fx"] = x["race_id"].map(fx) == 1
    vs = x.loc[x["fx"], "jcd"].unique()
    x = x[x["jcd"].isin(vs)].copy()
    gap = ent.groupby("race_id").apply(lambda g: g.loc[g["lane"] == 1, "nat_win_rate"].mean() - g.loc[g["lane"] != 1, "nat_win_rate"].mean())
    x["gap"] = x["race_id"].map(gap)
    nari = ent.groupby("race_id").apply(lambda g: bool((g["course"] == g["lane"]).all()))
    x["nari"] = x["race_id"].map(nari)
    m1 = measure(x, x["fx"], ref=~x["fx"]); m1["ref_label"] = "同じ場の、固定でないレース"
    same = x["gap"].between(1, 2, inclusive="right")
    m2 = measure(x, x["fx"] & same, ref=~x["fx"] & same); m2["ref_label"] = "固定でない(同じくらいの力の差)"
    v1, v2 = verdicts(m1), verdicts(m2)
    bins = [(-9, 0, "1号艇のほうが弱い"), (0, 1, "少し強い(勝率+0〜1)"), (1, 2, "強い(+1〜2)"), (2, 9, "とても強い(+2以上)")]
    tbl = []
    for lo, hi, nm in bins:
        b = x["gap"].between(lo, hi, inclusive="right")
        a_, c_ = x[b & x["fx"]], x[b & ~x["fx"]]
        tbl.append([nm, _rate(a_["c1"].mean()), _rate(c_["c1"].mean()), f"{len(a_):,}"])
    venues = x.loc[x["fx"], "jcd"].map(lambda j: VENUES[int(j)]).value_counts()
    gap_f, gap_n = float(x.loc[x["fx"], "gap"].mean()), float(x.loc[~x["fx"], "gap"].mean())
    nari_n = float(x.loc[~x["fx"], "nari"].mean())
    beat = v1.get("edge") == 1
    return {
        "id": "fixed", "title": "進入固定レースってなに? インは強くなる?",
        "belief": "進入固定は1号艇が堅い。でもそれは、番組で強い選手を1号艇に置いているからだろ。固定そのものは関係ねえ",
        "subject": "1号艇", "unit": "レース",
        "lead": f"進入固定は、1〜6号艇が必ず枠番どおりのコースに入るレース。前づけができない。このデータでは{len(venues)}場が使っていて、多いのは{'・'.join(venues.index[:3])}。"
                f"1号艇が勝つのは{_rate(m1['in1'])}(同じ場の固定でないレースは{_rate(m1['in1_ref'])})。たしかに固定のレースは1号艇に強い選手が置かれやすい"
                f"(1号艇とほかの5人の勝率の差: 固定{gap_f:+.1f}、固定でない{gap_n:+.1f})。でも、力の差が同じくらいのレースどうしでくらべても、固定のほうが{_diff_words(m2, '勝つ')}。"
                + ("しかも人気以上に来ている(追試中)。" if beat else ""),
        "conclusion": ["半分ウソ。番組もあるけど、固定そのものでも1号艇は強くなる",
                       f"力の差が同じくらいでも、固定のレースは1号艇が{_diff_words(m2, '勝つ')}。前づけがないので、1号艇は助走を十分にとれる"],
        "tables": [("1号艇とほかの5人の力の差(全国勝率の差)ごとの、1号艇の1着(%)", tbl, ["1号艇の強さ", "固定", "固定でない", "固定のレース数"])],
        "measures": [("進入固定のレースの1号艇", m1, v1), ("力の差が同じくらい(勝率+1〜2)で、進入固定", m2, v2)],
        "rules": ["進入固定競走: 1〜6号艇が枠番どおりに進入することが決まっているレース。出走表や新聞に前もって書かれる(公式の用語解説)",
                  "ふつうのレースでは、外の艇が内に入る『前づけ』ができる。固定のレースではできない",
                  f"くらべたのは、進入固定を使っている場の中だけ。固定でないレースでも、枠なりは{_rate(nari_n)}",
                  "力の差: 1号艇の全国勝率から、ほかの5人の全国勝率の平均を引いた数"],
        "faq": [("どの場が進入固定をやっている?", f"このデータでは{'・'.join(venues.index)}。朝のレースや企画レースなど、場ごとに決まったレースで使われることが多い"),
                ("なぜ固定だと1号艇が強い?", "前づけで内に入ってくる艇がいないので、1号艇は深くならず、助走を十分にとれる。スタートも速くなる(1コースの平均STが早い)"),
                ("固定のレースは買い?", "1号艇は強いけど、人気も集まる。人気以上に来るかは、レース数が少ないので追いかけ中")],
        "use": ["出走表の『進入固定』の文字を見たら、1号艇の信頼度を一段上げる", "力の差があまりない固定レースこそ、1号艇がいつもより来る"],
        "mikata": "前づけのドキドキはないけど、そのぶん1号艇がのびのび走れる。レースの性格がはっきりしているのも、予想しやすくて楽しいね",
        "gen": "固定は強い選手を1号艇に置いてるだけだと思ってたよ。並びが決まってるだけで、そんなに変わるもんなんだな",
        "challenge": "次に進入固定のレースを見つけたら、1号艇のスタートが他のレースより速いか、展示から見てみよう",
        "numbers": {"venues": venues.to_dict(), "gap": [gap_f, gap_n], "nari_nonfixed": nari_n},
    }


def _race_kind(t):
    t = str(t)
    if "優勝戦" in t and "準" not in t:
        return "優勝戦"
    if "準優" in t:
        return "準優勝戦"
    if "予選" in t:
        return "予選"
    return "その他"


def t_final(ent, r):
    """準優・優勝戦ならではの考え方と数字。枠の決まり方、1号艇の強さ、スタートは控える? 準優は2着でいい?"""
    x = r.copy(); x["kind"] = x["race_title"].map(_race_kind)
    kinds = x.set_index("race_id")["kind"]
    e = ent.copy(); e["kind"] = e["race_id"].map(kinds); e["dt"] = pd.to_datetime(e["date"])
    st = e["st"].where(e["st"].between(0, 0.6) & (e["st_flag"] != "F"))
    e["st_dev"] = st - st.groupby(e["racer_id"]).transform("mean")
    e["F"] = (e["result_code"].astype(str) == "F").astype(float)
    pre = x["kind"] == "予選"
    ms_, mf_ = measure(x, x["kind"] == "準優勝戦", ref=pre), measure(x, x["kind"] == "優勝戦", ref=pre)
    for m_ in (ms_, mf_):
        m_["ref_label"] = "予選"
    vs, vf = verdicts(ms_), verdicts(mf_)
    # 優勝戦の枠: 前の日の準優で何着だったか
    semi = e[e["kind"] == "準優勝戦"][["jcd", "dt", "racer_id", "finish", "lane"]].copy(); semi["dt"] = semi["dt"] + pd.Timedelta(days=1)
    fin = e[e["kind"] == "優勝戦"][["jcd", "dt", "racer_id", "lane"]]
    j = fin.merge(semi, on=["jcd", "dt", "racer_id"], how="inner", suffixes=("", "_semi"))
    in13 = float((j.loc[j["lane"] <= 3, "finish"] == 1).mean()); out46 = float((j.loc[j["lane"] >= 4, "finish"] == 2).mean())
    f1_from1 = float((j.loc[j["lane"] == 1, "lane_semi"] == 1).mean())
    # 1号艇が負けたときの2着残り(同じくらいの人気でくらべる)
    c1 = ent[ent["lane"] == 1].drop_duplicates("race_id").set_index("race_id")["finish"]
    x["f1"] = x["race_id"].map(c1)
    lose = x[(x["f1"] > 1) & x["f1"].notna() & x["q1"].between(0.65, 0.8)]
    sec_semi = float((lose.loc[lose["kind"] == "準優勝戦", "f1"] == 2).mean()); sec_pre = float((lose.loc[lose["kind"] == "予選", "f1"] == 2).mean())
    tbl = []
    for k in ("予選", "準優勝戦", "優勝戦"):
        g = x[x["kind"] == k]; ge = e[e["kind"] == k]
        sd = float(ge["st_dev"].mean())
        tbl.append([k, _rate(g["c1"].mean()), _rate(g["upset"].mean()), "ほぼ同じ" if abs(sd) < 0.003 else f"{abs(sd):.3f}秒{'早い' if sd < 0 else '遅い'}", f"{ge['F'].mean() * 1000:.1f}回"])
    lanes = x[x["kind"] == "優勝戦"]["win_lane"].value_counts(normalize=True).sort_index()
    ltbl = [[f"{int(k)}号艇", _rate(v)] for k, v in lanes.items()]
    st_f = float(e.loc[e["kind"] == "優勝戦", "st_dev"].mean()); f_f = float(e.loc[e["kind"] == "優勝戦", "F"].mean() * 1000); f_p = float(e.loc[e["kind"] == "予選", "F"].mean() * 1000)
    return {
        "id": "final", "title": "準優・優勝戦ならではの考え方",
        "belief": "優勝戦はフライングの罰が重いから、みんなスタートを控える。準優は2着でいいから、1号艇も無理はしない",
        "subject": "1号艇", "unit": "レース",
        "lead": f"予選の上位18人が準優勝戦(3レース)に進み、各レースの1着と2着が優勝戦へ。データで見ると、優勝戦の1〜3号艇は準優の1着の人({fun_rate(in13)})、4〜6号艇は準優の2着の人({fun_rate(out46)})。"
                f"1号艇が勝つのは、予選{_rate(ms_['in1_ref'])}、準優{_rate(ms_['in1'])}、優勝戦{_rate(mf_['in1'])}。"
                f"そして『罰が重いから控える』はウソ。優勝戦のスタートは本人のふだんより{abs(st_f):.3f}秒早く、フライングも1000走で{f_f:.1f}回(予選は{f_p:.1f}回)。大一番は攻める。",
        "conclusion": ["ウソ。大一番は、むしろ攻める",
                       f"準優・優勝戦はスタートがふだんより早く、フライングも多い。1号艇は準優で{_rate(ms_['in1'])}、優勝戦で{_rate(mf_['in1'])}勝つ(人気どおり)。"
                       f"『準優は2着でいい』は数字には出ない(1号艇が負けたときの2着残りは、同じくらいの人気なら予選とほぼ同じ)"],
        "tables": [("レースの種類ごとの数字(1号艇の1着・万舟は%、STは本人のふだんとくらべて)", tbl, ["レース", "1号艇1着", "万舟", "ST", "F(1000走)"]),
                   ("優勝戦の、枠ごとの1着(%)", ltbl, ["枠", "1着"])],
        "measures": [("準優勝戦の1号艇", ms_, vs), ("優勝戦の1号艇", mf_, vf)],
        "rules": ["準優勝戦: 予選の得点の上位(ふつう18人)が3レースに分かれて走り、各レースの1着・2着が優勝戦に進む(公式の用語解説)",
                  f"枠の決まり方(このデータで確認): 準優は予選の順位が上の人ほど内の枠。優勝戦は、準優1着の人が1〜3号艇、2着の人が4〜6号艇。優勝戦の1号艇の{fun_rate(f1_from1)}は、準優を1号艇から勝った人",
                  "フライングの罰: 優勝戦・準優勝戦のフライングは、大きな大会(SG・G1・G2)に出られない期間が長くなる。SGの優勝戦なら24か月(公式のお知らせ、令和5年度から)。事故点も優勝戦は重い"],
        "faq": [("準優は2着でいいから、1号艇は2着に残りやすい?", f"1号艇の人気が同じくらい(勝つ見込み65〜80%)のレースで、1号艇が負けたときの2着残りは、準優{_rate(sec_semi)}・予選{_rate(sec_pre)}(100回あたり)。『2着でいい走り』は数字には出なかった"),
                ("優勝戦の外枠は?", f"6号艇の優勝は{_rate(lanes.get(6, 0))}。4〜6号艇は準優2着の人なので、内の3人より予選の成績が下のことが多い"),
                ("なぜ大一番で攻める?", "優勝すれば賞金も名誉も大きい。上位の選手はもともとスタートが得意で、ここ一番で踏み込む。罰が重くても、勝ちに行く気持ちのほうが強いのかも")],
        "use": ["優勝戦は1号艇が強い(人気どおり)。勝負は2着・3着の並び", "大一番はスタートが早くなる。ふだんのSTが近い選手が並んでいたら、スリットの差は小さいと見る",
                "準優の枠は予選の順位で決まる。予選の最終日は、上位の人が『準優の内枠』を取りに行く勝負駆けにも注目"],
        "mikata": "優勝戦の6人がピットを出る瞬間は、何度見てもドキドキする。罰が重くても踏み込む、それが大一番なんだね",
        "gen": "優勝戦はFが怖くて控えると思ってたけどな……。違うのか。やっぱり勝負師だな、あいつらは",
        "challenge": "次の優勝戦で、6人のふだんのSTと、本番のSTをくらべてみよう。何人が『ふだんより早い』かな",
        "numbers": {"in13": in13, "out46": out46, "f1_from1": f1_from1, "sec": [sec_semi, sec_pre], "st_final": st_f, "F": [f_f, f_p]},
    }


THEORIES = {t["id"]: t for t in []}
def t_saying(ent, r):
    """コメントでよく見る「◯号艇の◯◯」「◯◯は◯◯巧者」「◯◯のまくり」は本当か(scripts/saying_lab.py の結果を読む)。"""
    S = json.loads((ROOT / "reports/saying.json").read_text(encoding="utf-8"))
    T, ex = S["traits"], S["examples"]

    def m_(k, name):
        x = T[k]
        m = {"n": x["n"], "in1": x["keep"], "in1_ref": x["chance"], "unit": "組" if k in ("course", "venue") else "人", "cu": "人", "ref_label": "偶然なら"}
        real = x["lo"] > x["chance"] + 0.03
        v = {"real": real, "exists": "その人の性質" if real else "偶然とほぼ同じ"}
        return (name, m, v)
    ms = [m_("st", "スタートが速い人"), m_("out", "外からでも届く人"), m_("front", "前づけする人"), m_("nige", "インが強い人"),
          m_("makuri", "まくり屋"), m_("sashi", "差し屋"), m_("course", "「◯コースの◯◯」(その人のふだんより、そのコースだけ強い)"),
          m_("venue", "「◯◯巧者」(その人のふだんより、その場だけ強い)"), m_("rough", "「荒れ水面の◯◯」"), m_("big", "「大一番の◯◯」")]
    n100 = lambda k: round(T[k]["keep"] * 100)  # noqa: E731
    mine = S.get("mine", {})
    c4 = (mine.get("course") or {}).get("4") or [[None, 0], [None, 0]]
    mine_txt = (f"峰竜太の4コース(カド)は、2つの期間とも本人のふだんより上({c4[0][0]:+.0f}ポイント・{c4[1][0]:+.0f}ポイント)。"
                if c4[0][0] is not None and c4[1][0] is not None and c4[0][0] > 0 and c4[1][0] > 0 else "")
    tbl = [["スタートが速い", "、".join(ex["st"][:5])], ["インが強い", "、".join(ex["nige"][:5])], ["まくり屋", "、".join(ex["makuri"][:5])],
           ["差し屋", "、".join(ex["sashi"][:5])], ["外からでも届く", "、".join(ex["out"][:5])], ["前づけ", "、".join(ex["front"][:5])]]
    tbl2 = [[x] for x in ex["course"][:8]]
    return {
        "id": "saying", "title": "「4号艇の◯◯」「◯◯巧者」は本当? コメントでよく見る言い回しを数えた",
        "belief": "◯◯は大村巧者、峰は4カド、荒れ水面なら◯◯。選手には得意な水面とコースがあるんだよ",
        "subject": "上位2割の人", "verb": "もう一方の期間も上位2割に入る", "no_market": True, "unit": "人", "ref_label": "偶然なら",
        "howto": "数字は「片方の期間で上位2割だった100人のうち、もう片方の期間も上位2割に入った人数」。偶然なら20人。多いほど、その人の性質(たまたまではない)",
        "key_line": f"『◯◯巧者』は100人中{n100('venue')}人(偶然なら20人)。スタートの速い人は{n100('st')}人、まくり屋は{n100('makuri')}人が上位のまま",
        "lead": (f"同じ選手を2つの期間(月の奇数・偶数)に分けて、片方で上位2割だった人が、もう片方でも上位2割に入るかを数えた。偶然なら100人中20人。"
                 f"スタートが速い人は{n100('st')}人、外からでも届く人は{n100('out')}人、インが強い人は{n100('nige')}人、まくり屋は{n100('makuri')}人と、"
                 f"その人の性質としてはっきり残る。ところが『その人のふだんより、この場だけ強い』(◯◯巧者)は{n100('venue')}人で、偶然とほぼ同じ。"
                 f"『このコースだけ強い』は{n100('course')}人で、少しだけある。{mine_txt}"),
        "conclusion": ["半分本当。『その人の型』は本物、『◯◯巧者』はほぼ偶然",
                       f"スタート・イン・まくり・前づけは、期間を分けても同じ顔ぶれ(100人中{n100('makuri')}〜{n100('st')}人)。"
                       f"『この場だけ強い』は100人中{n100('venue')}人で、偶然(20人)とほぼ同じ"],
        "tables": [("期間を分けても上位だったA1(その型の本物)", tbl, ["型", "選手(例)"]),
                   ("『◯コースの◯◯』で、2つの期間とも上位1割だったA1(例)", tbl2, ["コースと選手"])],
        "measures": ms,
        "rules": ["2つの期間は、月の奇数(1・3・5…月)と偶数(2・4・6…月)。季節や時期のかたよりが出にくい分け方",
                  "『その人のふだんより』は、コースの有利不利を差し引いた3着以内の回数を、その人自身の平均とくらべたもの(もともと強い人がどこでも強いのは除く)",
                  "各期間で一定の走数(コース・場は10走以上)がある人と組だけを数えた"],
        "faq": [("じゃあ『◯◯巧者』は気にしなくていい?", f"『この場だけ強い』は、期間を分けると顔ぶれがほぼ入れかわる(100人中{n100('venue')}人)。走った回数が少ないと、たまたまの好成績が目立つため。場の相性より、その人のスタートと型を見るほうが確か"),
                ("『4号艇の◯◯』は?", f"『このコースだけ強い』は100人中{n100('course')}人(偶然は20人)。少しはあるが、多くは入れかわる。"
                 f"ただ、まくり屋・外からでも届く人のような『型』は本物なので、『4カドの◯◯』はその人がまくり屋かどうかで確かめるのがいい。{mine_txt}"),
                ("大一番に強い人は?", f"準優・優勝戦だけ強い人は100人中{n100('big')}人、荒れ水面だけ強い人は{n100('rough')}人で、どちらも偶然とほぼ同じ。大一番でも、ふだんの強さどおり")],
        "use": ["コメントの『◯◯巧者』より、その人の平均STと型(まくり・差し・イン)を見る",
                "『4カドの◯◯』は、その人がまくり屋かどうかで確かめる(まくり屋は期間を分けても100人中" + str(n100("makuri")) + "人が上位のまま)",
                "前づけする人は、ほぼ毎回する(100人中" + str(n100("front")) + "人)。進入の予想に使える"],
        "mikata": "『その人の型』はうそをつかない。でも『この場だけ』は、思い出に残った1回かも",
        "gen": "大村巧者は気のせいだったか……。でも、まくり屋のまくりは本物だろ? 4カドはやっぱり熱いんだよ",
        "challenge": "次に『◯◯巧者』とコメントで見かけたら、その人の平均STと型をアプリの選手カードで見てみよう",
    }


BUILDERS = {"bangumi": t_bangumi, "kikaku": t_kikaku, "streak": t_streak, "a1in": t_a1in, "maezuke": t_maezuke, "tenji": t_tenji, "flying": t_flying, "combo": t_combo,
            "rest": t_rest, "travel": t_travel, "weight": t_weight, "dayno": t_dayno, "twice": t_twice, "tilt": t_tilt,
            "moon": t_moon, "manshu": t_manshu, "lucky7": t_lucky7,
            "rain": t_rain, "age": t_age, "zorome": t_zorome, "payday": t_payday,
            "birthday": t_birthday, "blood": t_blood, "height": t_height, "furusato": t_furusato,
            "pressure": t_pressure, "humid": t_humid, "heat": t_heat,
            "lane6": t_lane6, "motor": t_motor, "entry": t_entry,
            "e30": t_e30, "boat": t_boat, "deme": t_deme, "wind": t_wind, "exst": t_exst, "newmotor": t_newmotor, "rokuyo": t_rokuyo, "name": t_name, "hot": t_hot, "c1lose": t_c1lose, "season": t_season, "penalty": t_penalty, "slowdash": t_slowdash, "formation": t_formation, "samefin": t_samefin, "series": t_series, "fixed": t_fixed, "final": t_final, "saying": t_saying, "suji": t_suji, "night": t_night, "power": t_power}


# ---------------------------------------------------------------- 記事
def pc(v):
    return "-" if v is None or v != v else f"{v:.0%}"


def table_html(title, rows, label="1号艇の1着率"):
    if not rows:
        return ""
    if isinstance(rows[0], (list, tuple)):
        head = "<tr>" + "".join(f"<th>{e(h)}</th>" for h in label) + "</tr>"
        body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in x) + "</tr>" for x in rows)
        return f'<h4>{e(title)}</h4><div class="tw"><table class="scn lab">{head}{body}</table></div>'
    rows = [{k: v for k, v in x.items() if k != "ratio"} for x in rows]   # 「オッズとの比」の小数は読者に見せない
    has_ratio = any("ratio" in x for x in rows)
    head = f"<tr><th>場・レース名</th><th>R</th><th>レース数</th><th>{e(label)}</th>" + ("<th>人気とくらべて</th>" if has_ratio else "") + "</tr>"
    body = "".join(f"<tr><td>{e(str(x['venue']))}</td><td>{x['rno']}</td><td>{x['n']:,}</td><td><b>{_rate(x['in1'])}</b></td>"
                   + (f"<td>{x['ratio']:.2f}</td>" if has_ratio and x.get('ratio') else ("<td>-</td>" if has_ratio else "")) + "</tr>" for x in rows)
    return f'<h4>{e(title)}</h4><table class="scn lab cells">{head}{body}</table>'


def per100(v):
    """(古い名前)レースの結果の確率を「66%」で。"""
    return _rate(v)


# ---- 数字の書き方(2026-10-06 ユーザー判断: 「100レースで◯回」より「◯%」のほうが、目の前の1レースの話として読める)
#   レースの結果(勝つ・3着以内に入る)= 「66%」。差は「47%→66%に上がる」(何%が何%まで、が見える)
#   選手の数(「巧者」と言われる人のうち何人など)= 「100人中◯人」のまま。1000レースに1回のようなめったに無いこと(出目)も回数のまま
def _is_rate(unit=None, cu="回", per=100) -> bool:
    return per == 100 and cu == "回" and unit not in ("人", "組")


def _rate(v, fine=False):
    """確率を「66%」。1%未満は小数2桁、10%未満か差が小さいとき(fine)は小数1桁。"""
    if v is None or v != v:
        return "-"
    x = v * 100
    if x < 1:
        return f"{x:.2f}%"
    return f"{x:.1f}%" if (x < 10 or fine) else f"{round(x)}%"


def _rate_change(this, ref, fine=False, ref_label=None):
    """「47%→66%に上がる」「47%→39%に下がる」「ほぼ同じ(47%)」。ref_label を渡すと「ふだん47%→66%に上がる」。"""
    if this is None or ref is None or this != this or ref != ref:
        return "-"
    d = (this - ref) * 100
    head = f"{ref_label}" if ref_label else ""
    if abs(d) < 0.5:
        return f"ほぼ同じ({head}{_rate(ref, fine)})"
    return f"{head}{_rate(ref, fine)}→{_rate(this, fine)}に{'上がる' if d > 0 else '下がる'}"


def mark(v):
    """表に入れる短い判定。"""
    if v.get("baseline"):
        return "基準", "○ みんな知ってる" if v.get("edge") == 0 else "-", "基準"
    ex = "○ 本当" if v.get("real") else "– ふだん並み"
    e_ = v.get("edge")
    kn = "○ 人気どおり" if e_ == 0 and "追試中" not in v.get("known", "") else ("！ 人気以上(追試中)" if "追試中" in v.get("known", "") else
                                                                       ("！ 人気以上" if e_ == 1 else ("人気のわりにひかえめ" if e_ == -1 else "- 集め中")))
    st = v.get("stable")
    sb = "-" if st is None else ("○ 同じ" if st.startswith("前の2年") else "年で変わる")
    return ex, kn, sb


def _n100(v, per=100):
    """100(per)あたりの回数。10未満は小数1桁(6号艇など)。"""
    if v is None or v != v:
        return "-"
    x = v * per
    return f"{x:.1f}" if x < 10 else f"{round(x)}"


def _pct(v):
    """1レースあたりの確率を「66%」で。10%未満は小数1桁(6号艇など)。
    レースの結果(勝つ・3着に入る)は「◯%」、選手の数は「100人中◯人」で書き分ける。"""
    if v is None or v != v:
        return "-"
    x = v * 100
    return f"{x:.1f}%" if x < 10 else f"{round(x)}%"


def _frac(v):
    """確率の感覚をつかむための「3回に2回」。きれいに言えるときだけ返す(言えなければ空文字)。"""
    if v is None or v != v:
        return ""
    table = [(0.78, 0.84, "5回に4回"), (0.71, 0.78, "4回に3回"), (0.62, 0.71, "3回に2回"), (0.45, 0.55, "2回に1回"),
             (0.30, 0.37, "3回に1回"), (0.22, 0.28, "4回に1回"), (0.17, 0.22, "5回に1回"), (0.08, 0.12, "10回に1回")]
    for lo, hi, s in table:
        if lo <= v < hi:
            return s
    return ""


def _vs_phrase(this, ref, ref_label):
    """this を ref と比べて「A2(58%)と同じところまで」「A2(58%)を超える」「A2(58%)に近づく」。"""
    d = (this - ref) * 100
    tag = f"{ref_label}({_pct(ref)})"
    if abs(d) < 3:
        return f"{tag}と同じところまで"
    if d > 0:
        return f"{tag}を超えるところまで"
    return f"{tag}のすぐ下まで"


def _fine(m, per=100):
    """差が小さい(3回未満)ときは、回数を小数1桁で見せる(55回と54回で『2回少ない』のような食い違いを防ぐ)。"""
    return abs(m["in1"] - m["in1_ref"]) * per < 3


def _diff_words(m, verb, per=100):
    """差を、表示している数字どうしで(棒の横の数字と食い違わないように)。100あたりの確率なら「47%→66%に上がる」、それ以外は回数の差。"""
    fine = _fine(m, per)
    if _is_rate(m.get("unit"), m.get("cu", "回"), per):
        return _rate_change(m["in1"], m["in1_ref"], fine)
    disp = lambda v: round(v, 1) if (v < 10 or fine) else round(v)  # noqa: E731
    a, b = disp(m["in1"] * per), disp(m["in1_ref"] * per)
    d = round(a - b, 1)
    if abs(d) < 0.5:
        return "ほぼ同じ"
    n = f"{abs(d):.0f}" if float(d).is_integer() else f"{abs(d):.1f}"
    return f"{n}回{'多い' if d > 0 else '少ない'}"


def _ratio_phrase(this, ref, label1="", label2="", per=100):
    """2つの値の倍率・差を、比較表現に変える。「◯倍」「◯%多い」など。
    例: _ratio_phrase(0.42, 0.28) → "50%多い" (42回 vs 28回)
    label1="特別選抜戦", label2="一般戦" なら "一般戦の50%多い" も可能。
    """
    if ref is None or ref == 0 or ref != ref:
        return _rate(this)
    a, b = this * per, ref * per
    if abs(a - b) < 0.5:
        return "ほぼ同じ"
    # 倍率で表現するか、差で表現するか
    ratio = a / b if b > 0 else 1
    diff_pct = round((ratio - 1) * 100)
    if abs(diff_pct) >= 30:  # 30%以上なら倍率を言う
        return f"{ratio:.1f}倍" if ratio >= 1.5 else f"{_rate(this)}({diff_pct:+d}%)"
    else:  # 30%未満なら差分(ポイント)を言う
        diff = round(a - b, 1)
        diff_str = f"{abs(diff):.0f}" if float(diff).is_integer() else f"{abs(diff):.1f}"
        return f"{diff_str}ポイント{'高い' if diff > 0 else '低い'}"


def _story_lead(setup, data_points, conclusion=""):
    """記事の導入を「問い→データ展開→推測」の構造で作成。
    setup: 「なぜこれを調べたか」を示す問いかけ（例: "フライングすると、スタートって変わるんだろうか?")
    data_points: [{"finding": "スタートが0.123秒遅くなり", "this": value, "ref": ref_value, "label": "直後の10走"},...]
    conclusion: 最後につなげる一文（例: "その日の心理状態が、そのまま出ている。"）
    """
    if not data_points:
        return setup
    lines = [setup]
    for point in data_points:
        finding = point.get("finding", "")
        label = point.get("label", "")
        if label:
            lines.append(f"{label}、{finding}。")
        else:
            lines.append(f"{finding}。")
    if conclusion:
        lines.append(conclusion)
    return "".join(lines)


def measures_html(ms, subject="1号艇", verb="勝つ", no_market=False, compare="全体", ref_label=None, unit=None, per=100):
    """結果を1行=1枚のカードで。棒2本(くらべる相手/この条件)と差、ふだんの言葉のバッジ。per=1000 はめったに無いこと(出目など)用。"""
    unit = unit or ("走" if no_market else "レース")
    n_ = lambda v: _n100(v, per)  # noqa: E731
    default_ref = ref_label or ("ふだん" if no_market else "全レース")
    top = max([max(m["in1"], m["in1_ref"]) for _, m, _ in ms] + [0.01])
    cards = ""
    for name, m, v in ms:
        n_ = (lambda v_: f"{v_ * per:.1f}" if v_ == v_ and v_ is not None else "-") if _fine(m, per) else (lambda v_: _n100(v_, per))  # noqa: E731
        refl = m.get("ref_label") or default_ref
        cu = m.get("cu", "回")   # 数える単位(ふつうは「回」。選手を数えるときは「人」)
        rate = _is_rate(m.get("unit", unit), cu, per)   # レースの結果は「66%」で(回数は選手の数や出目だけ)
        if rate:
            fine_ = _fine(m, per)
            n_ = lambda v_: _rate(v_, fine_)  # noqa: E731
            cu = ""
        w1, w2 = m["in1_ref"] / top * 100, m["in1"] / top * 100
        d = (m["in1"] - m["in1_ref"]) * per
        tone = "up" if d >= 0.5 else ("down" if d <= -0.5 else "flat")
        badges = []
        if v.get("baseline"):
            badges.append('<span class="bd base">基準</span>')
        else:
            badges.append('<span class="bd ok">○ 本物の差</span>' if v.get("real") else '<span class="bd mute">– 差は小さい(ふだん並み)</span>')
            st_ = v.get("stable")
            if st_:
                badges.append('<span class="bd ok">○ 前の2年も最近の1年も同じ向き</span>' if st_.startswith("前の2年") else '<span class="bd mute">– 年によって変わる</span>')
        odds = ""
        r_ = m.get("market_ratio")
        if not no_market and r_ and r_ == r_:
            e_ = v.get("edge")
            if "追試中" in v.get("known", ""):
                badges.append('<span class="bd warn">！ 人気以上に来る(追試中)</span>')
            elif e_ == 0:
                badges.append('<span class="bd mute">人気どおり</span>')
            elif e_ == 1:
                badges.append('<span class="bd warn">！ 人気以上に来る</span>')
            elif e_ == -1:
                badges.append('<span class="bd warn">人気のわりにひかえめ</span>')
            exp_ = m["in1"] / r_ * (m.get("market_ref") or 1.0)   # オッズの見込みを、いつものずれ(全体の平均)で直した回数
            odds = f'<p class="rc-odds">人気から考えると {n_(exp_)}{cu} → 実際 {n_(m["in1"])}{cu}</p>'
        head_d = (f'{e(m.get("subject", subject))}が{e(m.get("verb", verb))}のは' if rate
                  else f'{per}{e(m.get("unit", unit))}で{e(m.get("subject", subject))}が{e(m.get("verb", verb))}のは')
        dw = _diff_words(m, m.get("verb", verb), per) if rate else _diff_words(m, m.get("verb", verb), per).replace("回", cu)
        cards += (f'<div class="rc"><p class="rc-h">{e(name)}<small>{m["n"]:,}{e(m.get("unit", unit))}</small></p>'
                  f'<div class="rc-row"><span>{e(refl)}</span><div class="bar"><i style="width:{w1:.0f}%"></i></div><b>{n_(m["in1_ref"])}{cu}</b></div>'
                  f'<div class="rc-row this {tone}"><span>この条件</span><div class="bar"><i style="width:{w2:.0f}%"></i></div><b>{n_(m["in1"])}{cu}</b></div>'
                  f'<p class="rc-d {tone}">{head_d} <b>{e(dw)}</b></p>'
                  f'{odds}<div class="rc-b">{"".join(badges)}</div></div>')
    return f'<div class="rcs">{cards}</div>'


# オカルト枠の導入(2026-10-06 ユーザー: 関係ないのはわかってる。でもギャンブラーなら確かめたくなるだろ? ワンチャン大いなる力が働いてるかも。
# 掛け合いで読み手の気持ちをつかむ)。(話す人, せりふ) の並び。g=ゲンさん、m=ミカタ。x は X の投稿に入れる短い版
HOOKS = {
    "lucky7": {"lines": [("g", "モーターの番号なんて、レースに関係ねえ。それくらい分かってるよ"), ("g", "でもな、出走表で『77号機』を見つけると、つい買いたくなっちまうんだ"),
                         ("m", "わかる。7が並んでるだけで、なんかいいことありそうだもんね"), ("g", "だろ? ワンチャン、大いなる力が働いてるかもしれねえ"),
                         ("m", "……よし、確かめよう。ギャンブラーなら、一度は白黒つけたいよね")],
               "x": ("番号なんて関係ねえのは分かってる。でも77号機は買いたくなるだろ?", "わかる。ワンチャンあるかも。確かめよう")},
    "moon": {"lines": [("g", "月で選手が速くなるわけがねえ。分かってるさ"), ("g", "でも満月の夜のナイターって、なんか荒れそうな気がしねえか?"),
                       ("m", "する。水面がキラキラして、いつもとちがう感じがするよね"), ("g", "潮だって月で動くんだ。ワンチャン、大いなる力が働いてるかもしれねえ"),
                       ("m", "そこまで言うなら、確かめるしかないね")],
             "x": ("月で速くなるわけねえ。でも満月のナイターは荒れそうだろ?", "ワンチャン大いなる力が……確かめよう")},
    "zorome": {"lines": [("g", "11月11日は1-1-1……は買えねえのか。まあいい"), ("g", "ゾロ目の日とか、13日の金曜日とか。関係ねえのは分かってても、気になるんだよ"),
                         ("m", "カレンダーを見るだけで、ちょっとワクワクする日ってあるよね"), ("g", "ワンチャン、その日だけ何かが起きるかもしれねえだろ?"),
                         ("m", "じゃあ、その『何か』があるのか、数えてみよう")],
               "x": ("ゾロ目の日、13日の金曜日。関係ねえのは分かってるけど気になるだろ?", "ワンチャンあるかも。数えてみた")},
    "payday": {"lines": [("g", "給料日は財布が温かいからな。つい本命をドカンと買いたくなる"), ("m", "みんなが同じことをしたら、本命の配当が下がってそうだよね"),
                         ("g", "だろ? 関係ねえようで、ワンチャンあるかもしれねえ"), ("m", "本命に人気が集まりすぎてるかは、数字で見える。確かめてみよう")],
               "x": ("給料日は本命を買いたくなる。みんな同じなら配当がしぶくなるだろ?", "ワンチャンあるかも。確かめた")},
    "birthday": {"lines": [("g", "誕生日だからってボートが速くなるわけじゃねえ。分かってる"), ("g", "でもな、誕生日に走る推しを見つけたら、応援したくなるのが人情だろ"),
                           ("m", "わかる。その日に勝ったら、一生の思い出になりそう"), ("g", "ワンチャン、その日だけは大いなる力が背中を押してくれるかもしれねえ"),
                           ("m", "じゃあ、誕生日の前後のレースを全部集めてみよう")],
                 "x": ("誕生日だから速くなるわけねえ。でも推しの誕生日は応援したくなるだろ?", "ワンチャンあるかも。全部集めてみた")},
    "blood": {"lines": [("g", "血液型で人が決まる、なんて話はいったん置いとくよ"), ("g", "でも『A型のスタートは几帳面』って聞くと、なんか分かる気がするんだよな"),
                        ("m", "一度は聞いたことあるよね、そういう話"), ("g", "ワンチャン、あるかもしれねえだろ?"), ("m", "星座もいっしょに、確かめちゃおう")],
              "x": ("血液型の話はいったん置いとく。でもA型のスタートは几帳面な気がするだろ?", "ワンチャンあるかも。確かめた")},
    "manshu": {"lines": [("g", "前のレースが万舟だと、次も荒れる気がするんだよ。流れってやつだ"), ("m", "前のレースと次のレースは、別のレース……なんだけどね"),
                         ("g", "頭では分かってる。でも、ワンチャン大いなる流れが来てるかもしれねえだろ?"), ("m", "その気持ち、すごくわかる。じゃあ流れがあるか、数えてみよう")],
               "x": ("万舟のあとは、また荒れる気がするんだよ。流れってやつだ", "頭では分かってても気になるよね。数えてみた")},
    "rokuyo": {"lines": [("g", "大安だの仏滅だので、水面が変わるわけがねえ。分かってるさ"), ("g", "でもカレンダーに『大安』とあると、本命で勝負したくなるんだよな"),
                         ("m", "わかる。なんか背中を押してもらえる気がするよね"), ("g", "ワンチャン、暦の大いなる力が働いてるかもしれねえ"),
                         ("m", "それなら、六曜ごとに全部のレースを数えてみよう")],
               "x": ("大安で水面が変わるわけねえ。でも大安の日は本命で勝負したくなるだろ?", "ワンチャンあるかも。全部数えた")},
    "name": {"lines": [("g", "名前に『勝』が入ってるから勝つ。そんなわけねえよな"), ("g", "……でも出走表で見つけると、ちょっと気になるんだよ"),
                       ("m", "わかる。名前で応援したくなる選手っているよね"), ("g", "ワンチャン、名前に大いなる力が宿ってるかもしれねえだろ?"),
                       ("m", "じゃあ、名前の字ごとに成績を並べてみよう")],
             "x": ("名前に『勝』で勝つわけねえ。でも出走表で見つけると気になるだろ?", "ワンチャンあるかも。字ごとに並べた")},
    "samefin": {"lines": [("g", "今日は3着がずっと6号艇だ。次も6を3着に置きたくなるだろ?"), ("m", "すごくわかる。もう、そういう日なんじゃないかって思うよね"),
                          ("g", "前のレースと関係ねえのは分かってる。でもワンチャン、今日は大いなる流れが来てるかもしれねえ"), ("m", "じゃあ、その流れが本当にあるのか確かめよう")],
                "x": ("今日は3着がずっと6号艇。次も6を置きたくなるだろ?", "わかる。流れが本当にあるか確かめた")},
    "streak": {"lines": [("g", "イン逃げが3つ続いた。そろそろ荒れるぞ"), ("m", "ルーレットの赤と黒みたいに、前とは関係ない……って言うよね"),
                         ("g", "分かってるよ。でもワンチャン、水面の大いなる力が働いてるかもしれねえだろ?"), ("m", "それなら確かめてみよう。結果は、ちょっと意外だったよ")],
               "x": ("イン逃げが3つ続いた。そろそろ荒れるだろ?", "ワンチャンあるかも。確かめたら意外だった")},
    "height": {"lines": [("g", "背の高さで勝ち負けが決まるなら、選手はみんな同じ背になってるはずだ"), ("g", "でも『小柄な選手はボートが軽い』って聞くと、ワンチャンあるかもって思っちまう"),
                         ("m", "わかる。体のことって、なんとなく効きそうだもんね"), ("m", "よし、身長ごとに分けて確かめよう")],
               "x": ("背の高さで決まるわけねえ。でも小柄なほうが軽くて有利な気がするだろ?", "ワンチャンあるかも。確かめた")},
}


def _hook(t):
    return t.get("hook") or HOOKS.get(t.get("id"))


# 記事の組み立て(2026-10-06 決定。読み物の型の調査: 答えは早めに出す。ネタバレでも楽しさは減らず、記事の中ほどで半分が離れるため)
#   オカルト枠: 表紙は問いだけ → 掛け合い → 「あなたはどっち?」→ すぐ結論+数字1行 → ゲンさんの返し → くわしく
#   実用の説  : 表紙に結論 → 結論+数字1行 → 説と短い掛け合い → 予想に使うなら・お題 → くわしく(結果・表)
def _main_measure(t):
    """見出しの物差し。記事は大事な物差しを先頭に置いているので、基準をのぞいた最初の1つ(t["key"] で番号を指定もできる)。"""
    ms = [x for x in t["measures"] if not x[2].get("baseline")] or t["measures"]
    return ms[t.get("key", 0)]


def key_line(t) -> str:
    """結論のすぐ下に置く数字の1行(いちばん大事な物差し)。"""
    if t.get("key_line"):
        return t["key_line"]
    name, m, _ = _main_measure(t)
    return f"{name}: {measure_line(t, m, name)}"


def measure_line(t, m, name) -> str:
    """物差し1つぶんの数字の1行。レースの結果は「1号艇が勝つのは66%(全レースは47%)」、
    選手の数や1000あたりのことは「100人中21人(偶然なら20人)」のように回数で。"""
    unit = m.get("unit") or t.get("unit") or ("走" if t.get("no_market") else "レース")
    refl = m.get("ref_label") or t.get("ref_label") or ("ふだん" if t.get("no_market") else "全レース")
    per = t.get("per", 100)
    cu = m.get("cu", "回")
    subj = m.get("subject", t.get("subject", "1号艇"))
    sv = ("" if subj.startswith("その") or subj in name else f"{subj}が") + m.get("verb", t.get("verb", "勝つ"))
    if _is_rate(unit, cu, per):
        fine = _fine(m, per)
        ha = "" if refl.endswith("なら") else "は"
        return f"{sv}のは{_rate(m['in1'], fine)}({refl}{ha}{_rate(m['in1_ref'], fine)})"
    nn = (lambda v: f"{v * per:.1f}") if _fine(m, per) else (lambda v: _n100(v, per))  # noqa: E731
    ha = "" if refl.endswith("なら") else "は"
    return f"{per}{unit}で{sv}のは{nn(m['in1'])}{cu}({refl}{ha}{nn(m['in1_ref'])}{cu})"


def neta_items(labs: list[dict]) -> list[dict]:
    """「1枚1ネタ」: 検証ラボの物差し1つ = X の1投稿。差がはっきりしたもの(本物の差)を先に、説ごとに交互に並べる。"""
    rows = []
    for t in sorted(labs, key=lambda t: t["id"]):
        if t.get("key_line") and t["id"] == "saying":   # 人数で数える回は別の書き方なので、結論の1行だけ
            continue
        for i, (name, m, v) in enumerate(t.get("measures") or []):
            if v.get("baseline") or m.get("in1") is None or m.get("in1_ref") is None:
                continue
            per = t.get("per", 100)
            d = round((m["in1"] - m["in1_ref"]) * per, 1)
            ans = "ほぼ同じ" if abs(d) < 0.5 or not v.get("real") else ("多い" if d > 0 else "少ない")
            rows.append({"id": f"{t['id']}:{i}", "lab": t["id"], "title": t["title"], "name": name, "real": bool(v.get("real")),
                         "line": measure_line(t, m, name), "answer": ans, "occult": t["id"] in HOOKS,
                         "a": round(m["in1"] * per, 1), "b": round(m["in1_ref"] * per, 1),
                         "refl": m.get("ref_label") or t.get("ref_label") or ("ふだん" if t.get("no_market") else "全レース"),
                         "q": f"{name}。" + measure_line(t, m, name).split("のは")[0] + "のは、ふだんより?"})
    # 本物の差を先に。同じ説が続かないよう、説ごとの何番目かで並べる
    seen: dict = {}
    for r in rows:
        k = seen.get(r["lab"], 0)
        r["_o"] = (not r["real"], k)
        seen[r["lab"]] = k + 1
    pr = ["lucky7", "hot", "manshu", "tilt", "moon", "lane6", "flying", "name", "humid", "series", "c1lose", "blood", "rest", "maezuke",
          "formation", "zorome", "birthday", "e30", "motor", "a1in", "fixed",
          "exst", "streak", "wind", "slowdash", "tenji", "rokuyo", "final"]   # 固定ポストで出した7本は後ろに
    rows.sort(key=lambda r: (r["_o"][1], pr.index(r["lab"]) if r["lab"] in pr else 99, r["_o"][0], r["id"]))
    return rows


def neta_use(r: dict) -> str:
    """1枚1ネタの「だから予想ではどうする?」の1行(答えと、数えたもの(1号艇の1着か、その選手の3着以内か)から)。"""
    line = r.get("line", "")
    if r["answer"] == "ほぼ同じ":
        return "→ 予想では: 気にしなくていい。そのぶん展示と水面を見よう"
    up = r["answer"] == "多い"
    if "1号艇が勝つ" in line:
        return "→ 予想では: 1号艇を信じる材料が1つ増える" if up else "→ 予想では: 1号艇以外から考える材料に"
    if "3着以内" in line:
        return "→ 予想では: この条件の選手は、3着までの相手に入れておく" if up else "→ 予想では: この条件の選手は、相手を考え直す材料に"
    return "→ 予想では: この条件を、見込みを上げる材料に" if up else "→ 予想では: この条件を、見込みを下げる材料に"


def neta_today(r: dict, hits: list[dict] | None, after: str = "15:30") -> str:
    """1枚1ネタ(15:30)の最後の1行: 「今日なら 住之江11R(締切16:42) 3号艇がこのタイプ」。締切がまだ先のレースだけ。"""
    if not hits:
        return ""
    def _hm(x):
        try:
            h, m = str(x).split(":"); return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return -1
    ok = sorted([h for h in hits if _hm(h.get("deadline")) > _hm(after)], key=lambda h: _hm(h.get("deadline")))
    if not ok:
        return ""
    h = ok[0]
    lanes = [x for x in (h.get("lanes") or []) if x]
    who = "・".join(f"{x}号艇" for x in lanes[:2]) if lanes and r.get("lab") in LANE_THEORIES else ""
    return f"今日なら {h['venue']}{h['rno']}R(締切{h['deadline']}){(' ' + who) if who else ''}がこのタイプ"


def neta_text(r: dict, from_poll: bool = False, hits: list[dict] | None = None) -> str:
    head = "昨日の投票の答え👇\n\n" if from_poll else ""
    v = {"多い": "ふだんより多い", "少ない": "ふだんより少ない", "ほぼ同じ": "ふだんとほぼ同じ"}[r["answer"]]
    tail = "\n(この差は、たまたまでも出るくらいの幅)" if r["answer"] == "ほぼ同じ" and r.get("a") is not None and abs(r["a"] - r["b"]) >= 0.5 else ""
    end = "あなたの予想は当たってた?" if from_poll else "あなたは、どっちだと思ってた?"
    use = neta_use(r)
    today = neta_today(r, hits)
    from kyotei.xtext import xlen as _xl
    for parts in ((tail, f"検証ラボ「{r['title']}」より📰 ", today), ("", f"検証ラボ「{r['title']}」より📰 ", today), ("", "", today),
                  (tail, f"検証ラボ「{r['title']}」より📰 ", ""), ("", f"検証ラボ「{r['title']}」より📰 ", ""), ("", "", "")):
        td = f"{parts[2]}\n" if parts[2] else ""
        body = f"{head}「{r['name']}」\n→ {v}\n\n{r['line']}{parts[0]}\n{use}\n{td}\n{parts[1]}{end}"
        if _xl(body) <= 256:   # 後ろにハッシュタグ2個(24字ぶん)を足せるように
            return body
    return body


def neta_poll(r: dict) -> dict:
    q = f"【明日答えます】{r['name']}。" + r["line"].split("のは")[0] + "のは、ふだんより?"
    return {"text": q, "options": ["多い", "少ない", "ほぼ同じ"]}


def practical_lines(t, con):
    """実用の説の、結論のあとの短い掛け合い(説 → ひと言の答え → どこで使う? → 使いどころ)。"""
    v = con[0].split("。")[0]
    if "ウソ" in v:
        g2 = "なにぃ……。じゃあ、予想のどこで気をつければいいんだ?"
    elif v.startswith(("本当", "信じていい", "番長は本物")):
        g2 = "だろ? で、予想のどこで使えばいいんだ?"
    else:
        g2 = "ふむ。で、予想のどこで使えばいいんだ?"
    u0 = t["use"][0] if t.get("use") else t["lead"]
    return [("g", t["belief"]), ("m", f"{count_words(t)}、数えてみたよ。ひと言でいうと『{v}』"), ("g", g2), ("m", u0)]


def count_words(t) -> str:
    """「17万レース」のような、数えた量のひと言。"""
    n = t.get("n_races")
    return f"{n / 10000:.0f}万レース" if n else "3年分のレース"


def page(t: dict, asof: str) -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    con = conclusion(t)
    hook = _hook(t)
    hook_html = ""
    if hook:
        rows = "".join(f'<div class="hk {w}">{gull_svg(44, bg="#ffffff", cls="hk-g", who="gen" if w == "g" else "mikata")}<p><small>{"ゲンさん" if w == "g" else "ミカタ"}</small>{e(x)}</p></div>'
                       for w, x in hook["lines"])
        hook_html = (f'<section class="hook"><span class="label">はじめに(正直に言うと)</span>'
                     f'<p class="who">ゲンさん=ゲンかつぎ歴40年の大先輩。ストップウォッチ片手に展示を見る目は確かで、ジンクスも信じる。ミカタ=データにくわしいカモメの記者</p><div class="hks">{rows}</div>'
                     f'<p class="ask">あなたは、どっちだと思う? <b>答えは、すぐ下。</b></p></section>')
    else:   # 実用の説: 結論のあとに、説と短い掛け合い(どこで使えるか)
        lines = practical_lines(t, con)
        rows = "".join(f'<div class="hk {w}">{gull_svg(44, bg="#ffffff", cls="hk-g", who="gen" if w == "g" else "mikata")}<p><small>{"ゲンさん" if w == "g" else "ミカタ"}</small>{e(x)}</p></div>'
                       for w, x in lines)
        hook_html = (f'<section class="hook pr"><span class="label">ゲンさんの説</span>'
                     f'<p class="who">ゲンさん=ゲンかつぎ歴40年の大先輩。ストップウォッチ片手に展示を見る目は確か</p><div class="hks">{rows}</div></section>')
    # オカルト枠は表紙で答えを言わない(問いだけ)。答えは掛け合いのすぐ下。実用の説は表紙で結論まで言う
    deck = (f"「{hook['x'][0]}」――関係ないのは分かってる。でも、ワンチャン大いなる力が働いてるかも? ギャンブラーの気持ちを、{count_words(t)}のデータで確かめた。" if hook
            else con[1])
    cv_con = "" if hook else f'<p class="cv-con"><span>結論</span>{e(con[0])}</p>'
    stamp = (f'<section class="stamp"><span class="label">ミカタの結論</span><div class="st-box"><b>{e(con[0])}</b>'
             f'<p class="kl">{e(key_line(t))}</p>' + (f'<p>{e(con[1])}</p>' if hook else "") + '</div></section>')
    gen_reply = f'<blockquote class="ft-quote gen">{gull_svg(64, bg="#ffffff", cls="q", who="gen")}<p><small>ゲンさんの返し</small>{e(t.get("gen", "ふーん。で、今日はどこが荒れるんだ?"))}</p></blockquote>'
    detail_html = (f'<section class="howto"><span class="label">くわしく</span><p>{e(t["lead"])}</p></section>' if hook
                   else f'<p class="more">ここから先は、くわしい数字。場ごと・年ごとの表も</p><section class="howto"><span class="label">くわしく</span><p>{e(t["lead"])}</p></section>')

    tables = "".join(table_html(*tb) for tb in t["tables"])
    _rate_mode = _is_rate(t.get("unit"), "回", t.get("per", 100))
    _nums = ("数字は「そのレース(走)で起きる確率」。66%なら3回に2回" if _rate_mode
             else f"数字はぜんぶ「{t.get('per', 100)}{t.get('unit') or ('走' if t.get('no_market') else 'レース')}あたり何回か」")
    howto_html = e(t["howto"]) if t.get("howto") else (f"""{_nums}。棒の上が<b>くらべる相手</b>、下が<b>この条件</b>。差がはっきりしていて、たまたまでは出ない差なら「<b>本物の差</b>」のしるしが付きます。{'' if t.get('no_market') else '人気にも同じ差が出ていれば「<b>人気どおり</b>」=配当はそのぶん安め。人気よりも多く来ていれば「<b>人気以上に来る</b>」。'}""")
    use_l = t["use"] if hook else t["use"][1:]
    use_html = (f'<section class="side"><h3>{"予想に使うなら" if hook else "ほかの使いどころ"}</h3><ul>' + "".join(f"<li>{e(x)}</li>" for x in use_l) + "</ul></section>") if use_l else ""
    todai = f'<section class="todai"><span class="label">今日のお題</span><div class="td-box">{gull_svg(48, bg="#fff", cls="td")}<p>{e(t.get("challenge", "次に行く場で、この説が本当か自分の目で確かめてみよう"))}</p></div></section>'
    rules = ('<section class="side"><h3>まず、ルールをざっくり</h3><ol>' + "".join(f"<li>{e(x)}</li>" for x in t["rules"]) + "</ol></section>") if t.get("rules") else ""
    faq = ('<section><span class="label">よくある疑問</span>' + "".join(f'<h4>Q. {e(q)}</h4><p class="faq">{e(a)}</p>' for q, a in t["faq"]) + "</section>") if t.get("faq") else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex"><title>ミカタ検証ラボ {e(t['title'])}</title>{mag.FONTS}<style>{mag.CSS}
.mag section{{min-width:0}} .tw{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.lab{{width:100%;margin:0;min-width:0}} .legend{{font-size:12.5px;color:var(--mute);line-height:1.6;margin:8px 0 0}} .lab td,.lab th{{text-align:left;white-space:normal}} .lab td b{{font:700 17px var(--num);color:var(--red)}} .lab small{{display:block;font-size:11px;color:var(--mute);white-space:normal}}
.lab.cells{{min-width:0}} .lab.cells td,.lab.cells th{{white-space:nowrap}}
.belief{{margin:0;font:700 clamp(16px,4.2vw,20px)/1.7 var(--serif);border-left:6px solid var(--yellow);padding:4px 0 4px 14px;background:rgba(255,225,0,.18);flex:1 1 auto}}
.gen-say{{display:flex;gap:12px;align-items:flex-start}} .gen-say svg{{flex:0 0 64px}} .who{{margin:8px 0 0;font-size:12.5px;color:var(--mute);line-height:1.6}}
.ft-quote.gen p{{border-color:#0b5fb4}} .ft-quote.gen small{{color:#0b5fb4}}
.rcs{{display:grid;gap:12px}} .rc{{background:var(--card);border:2px solid var(--rule);padding:12px 14px}}
.rc-h{{margin:0 0 8px;font:700 15.5px/1.5 var(--sans)}} .rc-h small{{margin-left:8px;font-weight:500;font-size:11.5px;color:var(--mute)}}
.rc-row{{display:grid;grid-template-columns:7.5em 1fr 4.2em;align-items:center;gap:8px;margin:4px 0;font-size:12.5px;color:var(--mute)}}
.rc-row .bar{{height:14px;background:rgba(0,0,0,.06);border-radius:3px;overflow:hidden}} .rc-row .bar i{{display:block;height:100%;background:#9aa3ab}}
.rc-row b{{font:700 17px var(--num);color:var(--ink);text-align:right}}
.rc-row.this span{{color:var(--ink);font-weight:700}} .rc-row.this.up .bar i{{background:var(--red)}} .rc-row.this.down .bar i{{background:#1f6fd1}} .rc-row.this.flat .bar i{{background:#6b7680}}
.rc-d{{margin:8px 0 4px;font-size:14px}} .rc-d b{{font:400 20px var(--head)}} .rc-d.up b{{color:var(--red)}} .rc-d.down b{{color:#1f6fd1}}
.rc-odds{{margin:2px 0 6px;font-size:12.5px;color:var(--mute)}} .rc-odds small{{display:block;font-size:11px}}
.rc-b{{display:flex;flex-wrap:wrap;gap:6px}} .bd{{font-size:11.5px;padding:3px 8px;border-radius:999px;border:1px solid var(--rule)}}
.bd.ok{{background:#e7f6ec;border-color:#2e8b57;color:#1e6b3f}} .bd.warn{{background:#fff4d6;border-color:#c98a00;color:#7a5200}} .bd.mute{{color:var(--mute)}} .bd.base{{background:#eee}}
.howto p{{margin:0;font-size:14px;line-height:1.8}}
.hks{{display:grid;gap:8px;background:#f1e9fb;border:2px solid #8a5cc8;padding:12px}} .hk{{display:flex;gap:10px;align-items:flex-start}} .hk svg{{flex:0 0 44px;width:44px;height:44px}}
.hk p{{margin:0;background:#fff;border-radius:10px;padding:8px 12px;font:700 14.5px/1.7 var(--serif);border:2px solid #c8141c}} .hk.g p{{border-color:#0b5fb4}}
.hk p small{{display:block;font:700 11px var(--sans);color:#c8141c}} .hk.g p small{{color:#0b5fb4}} .hk.m{{flex-direction:row-reverse}}
.gauge{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:8px}} .gauge div{{background:var(--card);border:2px solid var(--rule);padding:10px 12px}}
.gauge b{{display:block;font:400 15px var(--head);color:var(--red)}} .gauge span{{font-size:13px}}
.td-box{{display:flex;gap:12px;align-items:flex-start;background:var(--yellow);padding:14px 16px;border:3px solid var(--ink)}} .td-box p{{margin:0;font:700 15.5px/1.7 var(--serif)}} .td-box svg{{flex:0 0 48px;width:48px;height:48px}}
.st-box{{background:var(--red);color:#fff;padding:14px 16px}} .st-box b{{display:block;font:400 clamp(20px,5.5vw,28px)/1.3 var(--head)}} .st-box p{{margin:6px 0 0;font-size:14px;line-height:1.6}}
.ask{{margin:10px 0 0;font:700 15.5px/1.6 var(--serif);text-align:center}} .ask b{{color:#c8141c}} .hook.pr .hks{{background:#eef4fb;border-color:#0b5fb4}}
.st-box .kl{{margin:8px 0 0;font:700 15px/1.5 var(--sans);background:rgba(255,255,255,.16);padding:6px 10px}}
.cv-con{{margin:6px 0 0;font:400 clamp(20px,5.6vw,30px)/1.3 var(--head);color:#c8141c}} .cv-con span{{display:inline-block;font:700 12px var(--sans);background:#c8141c;color:#fff;padding:3px 8px;margin-right:8px;vertical-align:middle}}
.more{{margin:28px 0 0;padding:10px 0;border-top:3px double var(--ink);font:700 13px var(--sans);color:var(--mute);text-align:center}}
.mag h4{{margin:14px 0 6px;font:400 17px var(--head)}} .side ul,.side ol{{font-size:14.5px}} .faq{{margin:0 0 10px;font-size:14.5px;line-height:1.8}}
</style></head><body>
<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ検証ラボ<small>「◯◯理論」を同じ物差しで試す</small></div><div class="issue"><b>LAB</b><br>{e(today)}</div></div>
<p class="cv-kicker">{"オカルト枠" if hook else "検証する説"}</p><h1 class="cv-h">{e(t['title'])}</h1>{cv_con}
<p class="cv-deck">{e(deck)}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ(カモメの記者)/ 説の持ち込み ゲンさん(ゲンかつぎ歴40年の大先輩)<br>公式の成績データ 2023-10〜{e(asof)} を独自に集計</span></div></div></header>
<main class="mag">
{(hook_html + stamp + gen_reply) if hook else (stamp + rules + hook_html + use_html + todai)}
{detail_html}<section class="howto"><span class="label">数字の見方</span><p>{howto_html}</p></section>
{rules if hook else ''}<section><span class="label">結果</span>{measures_html(t['measures'], t.get('subject', '1号艇'), t.get('verb', '勝つ'), t.get('no_market', False), t.get('compare', '全体'), t.get('ref_label'), t.get('unit'), t.get('per', 100))}{tables}</section>{faq}
{(use_html + todai) if hook else ''}
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>{e(t['mikata'])}</p></blockquote>
{'' if hook else gen_reply}
<section class="method"><h3>データについて</h3><p>公式の成績データ(番組表・競走成績)と、締切時のオッズ(集めたレース分)を自分たちで集計。「人気から考えると◯%」は、締切時のオッズから逆算した見込み(払い戻しに回らない25%の分を除き、人気薄が買われすぎるいつもの傾向も差し引いた値)。
「ふだん並み」かどうかは、同じ数のレースを何度も引き直したときに出るブレの幅で判定(ブレの外なら「本物の差」)。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ検証ラボ ・ 毎週1本。競艇をいろんな角度から。予想が楽しくなる材料を。</span></footer></main></body></html>"""


def note_text(t: dict) -> str:
    con = conclusion(t)
    hk = _hook(t)
    who = lambda w: "ゲンさん" if w == "g" else "ミカタ"  # noqa: E731
    if hk:   # オカルト枠: 問いのタイトル → 掛け合い → あなたはどっち? → すぐ結論
        out = ["【タイトル案】", f"1. {t['title']} {count_words(t)}で数えてみた", f"2. 関係ないのは分かってる。{t['title']}", "",
               "■はじめに(正直に言うと)", "(ゲンさん=ゲンかつぎ歴40年の大先輩。ミカタ=データにくわしいカモメの記者)", *[f"{who(w)}「{x}」" for w, x in hk["lines"]], "", "あなたは、どっちだと思う? 答えは、すぐ下。", "",
               f"■ミカタの結論:{con[0]}", key_line(t), con[1], "", f"ゲンさんの返し:「{t.get('gen', '')}」", "", "■くわしく", t["lead"], ""]
    else:    # 実用の説: タイトルで結論 → 結論と数字 → 説と短い掛け合い → 使いどころ・お題 → (ここから有料にするなら)くわしく
        out = ["【タイトル案】", f"1. {t['title']}|{con[0]}", f"2. {t['title']}→{con[0].split('。')[0]}。{count_words(t)}で確かめた", "",
               f"■ミカタの結論:{con[0]}", key_line(t), con[1], ""]
        if t.get("rules"):
            out += ["■まず、ルールをざっくり"] + [f"{i + 1}. {x}" for i, x in enumerate(t["rules"])] + [""]
        out += ["■ゲンさんの説(ゲンかつぎ歴40年の大先輩)"] + [f"{who(w)}「{x}」" for w, x in practical_lines(t, con)] + [""]
        if t["use"][1:]:
            out += ["■ほかの使いどころ"] + [f"・{x}" for x in t["use"][1:]] + [""]
        out += ["■今日のお題", t.get("challenge", ""), "", "(有料にするなら、ここから先)", "■くわしく", t["lead"], ""]
    out += ["■結果"]
    for name, m, v in t["measures"]:
        unit = t.get("unit") or ("走" if t.get("no_market") else "レース")
        refl = m.get("ref_label") or t.get("ref_label") or ("ふだん" if t.get("no_market") else "全レース")
        per = t.get("per", 100)
        nn = (lambda v_: f"{v_ * per:.1f}") if _fine(m, per) else (lambda v_: _n100(v_, per))  # noqa: E731
        cu = m.get("cu", "回")
        if _is_rate(m.get("unit", unit), cu, per):
            line = f"・{name}: {measure_line(t, m, name)}"
        else:
            line = f"・{name}: {per}{unit}で{nn(m['in1'])}{cu}({refl}{'' if refl.endswith('なら') else 'は'}{nn(m['in1_ref'])}{cu})→ {_diff_words(m, m.get('verb', t.get('verb', '勝つ')), per).replace('回', cu)}"
        tags = [("本物の差" if v.get("real") else "差は小さい")] if not v.get("baseline") else ["基準"]
        if v.get("stable") and not v.get("baseline"):
            tags.append("前の2年も最近の1年も同じ向き" if v["stable"].startswith("前の2年") else "年によって変わる")
        r_ = m.get("market_ratio")
        if not t.get("no_market") and r_ and r_ == r_:
            exp_ = m["in1"] / r_ * (m.get("market_ref") or 1.0)
            tags.append(f"人気から考えると{_rate(exp_) if _is_rate(m.get('unit', unit), cu, per) else _n100(exp_, per) + cu}")
        out.append(line + "。" + "・".join(tags))
    if False:
      for name, m, v in t["measures"]:
        ex, kn, sb = mark(v)
        r = m.get("market_ratio")
        odds = (f"オッズの見立ては{per100(m['in1'] / r)}、実際は{per100(m['in1'])}({round((r - 1) * 100):+d}%)" if r and r == r else "オッズのデータは集計中")
        subj, verb = t.get("subject", "1号艇"), t.get("verb", "勝つ")
        out.append(f"・{name}({m['n']:,}走): 100走で{subj}が{verb}のは{per100(m['in1'])}({fun_rate(m['in1'])}。くらべる相手は{per100(m['in1_ref'])})→ {ex}。"
                   + ("" if t.get("no_market") else f"{odds} → {kn}。") + f"来年も同じか: {sb}")
    for h, rows, *_lbl in t["tables"]:
        if rows and isinstance(rows[0], (list, tuple)):
            out += ["", f"■{h}"] + ["・" + " / ".join(str(c) for c in x) for x in rows]
            continue
        out += ["", f"■{h}"] + [f"・{x['venue']}{x['rno']}{'R' if x['rno'] != '' else ''} {_rate(x['in1'])}({x['n']:,}レース)" for x in rows]
    if t.get("rules") and hk:
        out += ["", "■まず、ルールをざっくり"] + [f"{i + 1}. {x}" for i, x in enumerate(t["rules"])]
    if t.get("faq"):
        out += ["", "■よくある疑問"] + [f"Q. {q}\n{a}" for q, a in t["faq"]]
    if hk:
        out += ["", "■予想に使うなら"] + [f"・{x}" for x in t["use"]] + ["", "■今日のお題", t.get("challenge", "")]
    out += ["", f"ミカタのひと言:「{t['mikata']}」"] + ([] if hk else [f"ゲンさんの返し:「{t.get('gen', '')}」"]) + ["",
            "■データについて", "公式の成績データと締切時のオッズを自分たちで集計。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"]
    return "\n".join(out)


def x_first_line(t: dict) -> str:
    """X の1行目: 数字つきの言い切り(市場の投稿は1行目に数字が1〜2個)。記事に x1 があればそれ。
    例: 「1号艇がA1なら、勝つのは66%。全レースは47%。」"""
    if t.get("x1"):
        return t["x1"]
    name, m, _ = _main_measure(t)
    unit = m.get("unit") or t.get("unit") or ("走" if t.get("no_market") else "レース")
    per, cu = t.get("per", 100), m.get("cu", "回")
    if not _is_rate(unit, cu, per):
        return key_line(t)
    refl = m.get("ref_label") or t.get("ref_label") or ("ふだん" if t.get("no_market") else "全レース")
    subj = m.get("subject", t.get("subject", "1号艇"))
    sv = ("" if subj.startswith("その") or subj in name else f"{subj}が") + m.get("verb", t.get("verb", "勝つ"))
    fine = _fine(m, per)
    if len(name) > 26:   # 条件の名前が長い回は、見出し→数字の形に
        return f"{t['title']}→ {sv}のは{_rate(m['in1'], fine)}({refl}は{_rate(m['in1_ref'], fine)})"
    return f"{name}なら、{sv}のは{_rate(m['in1'], fine)}。{refl}は{_rate(m['in1_ref'], fine)}。"


def x_card(t: dict) -> str:
    """X に載せる画像(1080×1350 の専用カード。kyotei.xcard)。記事の紙面は撮らない(スマホで文字が読めないため。2026-10-07 ユーザー)。
    結論のハンコ → いちばん大事な物差しの2本の棒 → 人気とのくらべ → ゲンさんの返し。"""
    from kyotei.xcard import lab_card_html
    con = conclusion(t)
    name, m, v = _main_measure(t)
    unit = m.get("unit") or t.get("unit") or ("走" if t.get("no_market") else "レース")
    per, cu = t.get("per", 100), m.get("cu", "回")
    refl = m.get("ref_label") or t.get("ref_label") or ("ふだん" if t.get("no_market") else "全レース")
    subj = m.get("subject", t.get("subject", "1号艇"))
    sv = ("" if subj.startswith("その") or subj in name else f"{subj}が") + m.get("verb", t.get("verb", "勝つ"))
    real = not con[0].startswith("ふだんと同じ")
    market = ""
    if real and not t.get("no_market") and m.get("market_ratio") and m["market_ratio"] == m["market_ratio"]:
        market = odds_words(m)
    gen = (t.get("gen") or "").strip()
    if len(gen) > 75:   # 吹き出しは3行まで(36px で1行25字)。長いときは文の切れ目で、入るところまで
        out_ = ""
        for sen in [x + "。" for x in gen.split("。") if x]:
            if len(out_ + sen) > 75:
                break
            out_ += sen
        gen = out_ or gen[:74] + "…"
    rate = _is_rate(unit, cu, per) and m.get("in1") is not None and m.get("in1_ref") is not None
    return lab_card_html(t["title"], con[0], real, name, sv, m["in1"] if rate else None, m["in1_ref"] if rate else None, refl,
                         "" if rate else key_line(t), market, gen)


LANE_THEORIES = {"hot", "flying", "rest", "penalty", "tilt", "weight", "a1in", "slowdash", "formation", "lucky7", "name"}


def today_line(t: dict, hits: list[dict] | None) -> str:
    """「今日なら 住之江11R 1号艇がこのタイプだった」。hits: [{"venue","rno","lanes","deadline"}](その日の理論ぶつけで、この説が当てはまったレース)。
    20時の投稿なので今日のレースは終わっている → 答え合わせは読む人にまかせ、明日の出走表で探す行動につなげる。"""
    if not hits:
        return ""
    h = hits[0]
    lanes = [x for x in (h.get("lanes") or []) if x]
    who = ("・".join(f"{x}号艇" for x in lanes[:2]) if lanes and t["id"] in LANE_THEORIES else "")
    return f"今日なら {h['venue']}{h['rno']}R{(' ' + who) if who else ''}がこのタイプだった。明日の出走表でも探してみて"


def _use_short(t: dict, limit: int = 44) -> str:
    """使いどころの1文目(短いときだけ)。"""
    u = (t.get("use") or [""])[0].split("。")[0]
    return u if 0 < len(u) <= limit else ""


def x_text(t: dict, hits: list[dict] | None = None) -> str:
    """X の投稿案(2026-10-06 市場の作りに合わせる: 1行目は数字つきの言い切り、1行1情報、最後に今日の該当レース。
    ゲンさんのセリフは画像の中に出すので本文には入れない。オカルト枠だけ掛け合い2行から入る)。
    全角は2文字で数え、280(タグ2個ぶんを残して256)に収まるいちばん情報の多い形を選ぶ。リンクは本文に入れず返信に。"""
    con = conclusion(t)
    l1, l2, l3, l4 = x_first_line(t), f"→ {con[0]}", _use_short(t), today_line(t, hits)
    hk = _hook(t)
    if hk:   # オカルト枠: ゲンさんのゲンかつぎ → ミカタ → 数字 → 結論 → 読み手のゲンかつぎを聞く
        gx, mx = hk["x"]
        h2 = f"ゲンかつぎ歴40年のゲンさん「{gx}」\nミカタ「{mx}」\n\n"   # 「ゲンさんってだれ?」とならないよう紹介つき
        ask = "あなたのゲンかつぎも教えて。次に数えます"
        cands = [h2 + f"{l1}\n{l2}\n{l4}\n\n{ask}" if l4 else "", h2 + f"{l1}\n{l2}\n\n{ask}", h2 + f"{l1}\n{l2}", h2 + l2]
    else:    # 実用の説: 数字 → 結論 → 今日の該当レース → ミカタのひと言(ミカタが喋るのは最後だけ。1行目は情報のまま)
        mk = t.get("mikata", "")
        cands = [f"{l1}\n{l2}\n{l4}\n\n{mk}" if mk and l4 else "", f"{l1}\n{l2}\n{l4}\n\n{l3}" if l3 and l4 else "", f"{l1}\n{l2}\n\n{l4}" if l4 else "",
                 f"{l1}\n{l2}\n\n{mk}" if mk else "", f"{l1}\n{l2}\n{l3}" if l3 else "", f"{l1}\n{l2}\n\nみんなは信じてた?", f"{l1}\n{l2}"]
    cands = [c for c in cands if c]
    body = next((c for c in cands if xlen(c) <= 256), cands[-1])
    return (f"--- 投稿1({xlen(body)}/280) ---\n{body}\n\n画像: 結果のカード(ゲンさんの返しは画像の中に)\n"
            "出し方: 記事のリンクは本文に入れず、この投稿への自分の返信に付ける。タグは #競艇 #ボートレース(+場名)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theory", default=None)
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "out/lab"))
    a = ap.parse_args()
    if a.list:
        for k in BUILDERS:
            print(k, "済" if private_exists(REP / f"{k}.json") else "")
        return
    if a.theory == "all":
        tids = list(BUILDERS)
    elif a.theory:
        tids = a.theory.split(",")
    else:
        tids = [next((k for k in BUILDERS if not private_exists(REP / f"{k}.json")), None)] if a.next else []
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
    now = dt.datetime.now(JST).strftime("%Y-%m-%d")
    old = REP / f"{tid}.json"
    made0 = None
    if private_exists(old):   # 作り直しても『はじめて出した日』は変えない(記事の並び順に使う)。直した日は updated に
        try:
            made0 = (load_private(old) or {}).get("made")
        except Exception:  # noqa: BLE001
            made0 = None
    t["asof"], t["made"], t["updated"], t["n_races"] = asof, made0 or now, now, int(len(r))
    save_private(REP / f"{tid}.json", json.loads(json.dumps(t, ensure_ascii=False, default=float)))   # 本文は暗号化(公開リポジトリでパクられないように)
    print("wrote", out / f"lab_{tid}.html")
    print(t["lead"])


if __name__ == "__main__":
    main()
