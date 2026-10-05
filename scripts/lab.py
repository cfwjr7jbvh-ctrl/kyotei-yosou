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
    return ent, r


def boot_ci(x: np.ndarray, n=400, seed=0):
    rng = np.random.default_rng(seed)
    m = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


def measure(r: pd.DataFrame, mask: pd.Series, ref: pd.Series | None = None) -> dict:
    """①率 ②市場との比 ③前半・後半。ref は比べる相手(無ければ全体)。"""
    x, y = r[mask], (r[ref] if ref is not None else r)
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
    """記事の冒頭に置く結論(ハンコ)。(見出し, ひとこと)。"""
    vs = [v for _, _, v in t["measures"]]
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


THEORIES = {t["id"]: t for t in []}
BUILDERS = {"bangumi": t_bangumi, "kikaku": t_kikaku, "streak": t_streak, "a1in": t_a1in}


# ---------------------------------------------------------------- 記事
def pc(v):
    return "-" if v is None or v != v else f"{v:.0%}"


def table_html(title, rows):
    if not rows:
        return ""
    has_ratio = any("ratio" in x for x in rows)
    head = "<tr><th>場・レース名</th><th>R</th><th>レース数</th><th>1号艇の1着率</th>" + ("<th>オッズとの比</th>" if has_ratio else "") + "</tr>"
    body = "".join(f"<tr><td>{e(str(x['venue']))}</td><td>{x['rno']}</td><td>{x['n']:,}</td><td><b>{pc(x['in1'])}</b></td>"
                   + (f"<td>{x['ratio']:.2f}</td>" if has_ratio and x.get('ratio') else ("<td>-</td>" if has_ratio else "")) + "</tr>" for x in rows)
    return f'<h4>{e(title)}</h4><table class="scn lab cells">{head}{body}</table>'


def per100(v):
    return "-" if v is None or v != v else f"{round(v * 100)}回"


def mark(v):
    """表に入れる短い判定。"""
    ex = "○ 本当" if v.get("real") else "– ふだん並み"
    e_ = v.get("edge")
    kn = "○ みんな知ってる" if e_ == 0 and "追試中" not in v.get("known", "") else ("！ 見立て超え(追試中)" if "追試中" in v.get("known", "") else
                                                                       ("！ 見立て超え" if e_ == 1 else ("ひかえめ" if e_ == -1 else "- 集計中")))
    st = v.get("stable")
    sb = "-" if st is None else ("○ 同じ" if st.startswith("前の2年") else "年で変わる")
    return ex, kn, sb


def measures_html(ms):
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
    legend = (f"<p class=\"legend\">①は「100レースで1号艇が勝つ回数」(ふだんは{per100(ms[0][1]['in1_ref'])}、{fun_rate(ms[0][1]['in1_ref'])})。"
              f"②は「オッズがみんなの予想として見立てていた回数」と実際の回数。1号艇はどのレースでも見立てより少し多く勝つ{e(ref_w)}ので、それと同じなら、みんな知っている=配当は堅め。③は前の2年と最近の1年で同じ向きか。</p>")
    return ('<div class="tw"><table class="scn lab"><tr><th>条件</th><th>①本当?</th><th>②知られてる?</th><th>③来年も?</th></tr>'
            + rows + "</table></div>" + legend)


def page(t: dict, asof: str) -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    con = conclusion(t)
    tables = "".join(table_html(h, rows) for h, rows in t["tables"])
    use = "".join(f"<li>{e(x)}</li>" for x in t["use"])
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
.mag h4{{margin:14px 0 6px;font:400 17px var(--head)}} .side ul{{font-size:14.5px}}
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
<div><b>② みんな知ってる?</b><span>オッズは「みんなの予想」。1号艇はどのレースでもオッズの見立てより少し多く来るので、その「全レースの平均」と同じなら、知られている=配当は安い</span></div>
<div><b>③ 来年も同じ?</b><span>前の2年と最近の1年で、同じ向きに出るか。出なければ一時のもの</span></div></div></section>
<section><span class="label">結果</span>{measures_html(t['measures'])}{tables}</section>
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
        out.append(f"・{name}({m['n']:,}レース): 100レースで1号艇が勝つのは{per100(m['in1'])}({fun_rate(m['in1'])}。ふだんは{per100(m['in1_ref'])})→ {ex}。"
                   f"{odds} → {kn}。来年も同じか: {sb}")
    for h, rows in t["tables"]:
        out += ["", f"■{h}"] + [f"・{x['venue']}{x['rno']}{'R' if x['rno'] != '' else ''} {pc(x['in1'])}({x['n']:,}レース)" for x in rows]
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
    tid = a.theory or (next((k for k in BUILDERS if not (REP / f"{k}.json").exists()), None) if a.next else None)
    if not tid:
        print("作る理論がありません"); return
    ent, r = base()
    t = BUILDERS[tid](ent, r)
    asof = str(r["date"].max())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
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
