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
from kyotei.xtext import xlen  # noqa: E402

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
    a, b = x[~x["late"]], x[x["late"]]
    ya, yb = y[~y["late"]], y[y["late"]]
    if len(a) >= 50 and len(b) >= 50:
        m["half"] = [float(a["c1"].mean() - ya["c1"].mean()), float(b["c1"].mean() - yb["c1"].mean())]
    return m


def verdicts(m: dict) -> dict:
    d = m["in1"] - m["in1_ref"]
    out = {"exists": "ある" if abs(d) >= 0.03 and not (m["in1_ci"][0] <= m["in1_ref"] <= m["in1_ci"][1]) else "ほぼ差なし"}
    if "market_ratio" in m:
        lo, hi = m["market_ci"]
        out["known"] = "人気どおり(織り込み済み)" if lo <= 1 <= hi else ("人気のわりに来る(ただし控除があるので、得になる水準=1.3以上ではない)" if lo > 1 < 1.3 else
                                                              ("人気のわりに来る" if lo > 1 else "人気のわりに来ない"))
    else:
        out["known"] = "オッズのデータが足りない"
    if "half" in m:
        a, b = m["half"]
        out["stable"] = "前半・後半とも同じ向き" if a * b > 0 and abs(a) >= 0.015 and abs(b) >= 0.015 else "時期で変わる(偶然の幅)"
    return out


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
        "lead": f"場×レース番号ごとの1号艇の1着率は、いちばん堅い枠で{g['in1'].max():.0%}、いちばん荒れる枠で{g['in1'].min():.0%}。"
                f"前半2年と後半1年で同じ枠が堅いか(相関)は{corr:.2f}。番組の癖はたしかにあり、年をまたいでも続いている。",
        "tables": [("1号艇が堅い枠(上位8)", rows), ("1号艇が荒れる枠(下位8)", rows2)],
        "measures": [("前半2年で堅かった枠8つ→後半1年", mh, verdicts(mh)), ("前半2年で荒れた枠8つ→後半1年", ms, verdicts(ms))],
        "use": ["出走表を見る前に、その場のその番号の「ふだんの堅さ」を頭に入れる。堅い枠で1号艇が弱そうなら、それ自体がニュース",
                "ただし堅い枠はオッズも堅い。人気どおりなら、1号艇を軸にするかどうかは配当との相談(ここは読者の判断)",
                "荒れる枠は、2〜4号艇にまくり型・差し型の選手が入っているかを先に見る"],
        "mikata": "番組屋さんの気持ちになって出走表を読むと、レースがもう一段おもしろくなるよ。『この枠に、なぜこの人を置いた?』って",
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
        "lead": f"レース名ごとの1号艇の1着率は、特別選抜戦{dict((x[0], x[1]['in1']) for x in measures).get('特別選抜戦', 0):.0%}、"
                f"ドリーム戦{dict((x[0], x[1]['in1']) for x in measures).get('ドリーム戦', 0):.0%}、一般戦{dict((x[0], x[1]['in1']) for x in measures).get('一般戦', 0):.0%}。"
                f"堅いのは本当。ただしオッズが見込んだ率との比はほとんどが1.0前後で、みんな知っている。"
                f"目立ったのは{best[0]}の{best[1]['market_ratio']:.2f}({best[1]['n_odds']}レース)だが、まだ偶然の幅に収まる。",
        "tables": [("レース名ごとの1号艇", rows)],
        "measures": measures,
        "use": ["企画レースは「インが堅い」より「堅いことが知られている」レース。1号艇を買うなら配当は安い、を前提に考える",
                "堅いレースこそ、2着・3着の並びで差がつく。差し型・まくり差し型の選手が2〜3号艇にいるかを見る",
                "1.0を大きく超える企画レースが見つかったら追試する(ミカタは毎週ここを更新する)"],
        "mikata": "『堅い』と『おいしい』は別もの。堅いレースは、2着3着で遊ぶのがコツかも",
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
                f"差は本物。ただしオッズが見込んだ率との比は{a.get('market_ratio', float('nan')):.2f}(A1)と{b.get('market_ratio', float('nan')):.2f}(B1)で、"
                "級別はみんな見ている。",
        "tables": [],
        "measures": [("1号艇がA1", a, verdicts(a)), ("1号艇がB1", b, verdicts(b))],
        "use": ["級別は出走表でいちばん目立つ情報なので、オッズにいちばん早く織り込まれる。級別『以外』の材料(ST・決まり手の型・今節の足)で差をつける",
                "B1の1号艇でも、平均STが速くて逃げ率が高い選手ならA1なみ。ミカタ新聞のカードはそこを見る"],
        "mikata": "A1かどうかは、みんな見てる。見てないところを見るのが、いろんな角度ってやつ",
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


def measures_html(ms):
    rows = ""
    for name, m, v in ms:
        rows += (f"<tr><th>{e(name)}</th><td>{m['n']:,}</td><td><b>{pc(m['in1'])}</b><small>(全体{pc(m['in1_ref'])})</small></td>"
                 f"<td>{m.get('market_ratio', float('nan')):.2f}<small>{e(v['known'])}</small></td><td>{e(v.get('stable', '-'))}</td></tr>")
    return ('<div class="tw"><table class="scn lab"><tr><th>条件</th><th>レース数</th><th>①1号艇の1着率</th><th>②オッズとの比</th><th>③時期を変えても</th></tr>'
            + rows + "</table></div>")


def page(t: dict, asof: str) -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    tables = "".join(table_html(h, rows) for h, rows in t["tables"])
    use = "".join(f"<li>{e(x)}</li>" for x in t["use"])
    return f"""<title>ミカタ検証ラボ {e(t['title'])}</title>{mag.FONTS}<style>{mag.CSS}
.mag section{{min-width:0}} .tw{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.lab{{width:100%;margin:0;min-width:520px}} .lab td,.lab th{{text-align:left;white-space:normal}} .lab td b{{font:700 17px var(--num);color:var(--red)}} .lab small{{display:block;font-size:11px;color:var(--mute);white-space:normal}}
.lab.cells{{min-width:0}} .lab.cells td,.lab.cells th{{white-space:nowrap}}
.belief{{margin:0;font:700 clamp(16px,4.2vw,20px)/1.7 var(--serif);border-left:6px solid var(--yellow);padding:4px 0 4px 14px;background:rgba(255,225,0,.18)}}
.gauge{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:8px}} .gauge div{{background:var(--card);border:2px solid var(--rule);padding:10px 12px}}
.gauge b{{display:block;font:400 15px var(--head);color:var(--red)}} .gauge span{{font-size:13px}}
.mag h4{{margin:14px 0 6px;font:400 17px var(--head)}} .side ul{{font-size:14.5px}}
</style>
<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ検証ラボ<small>「◯◯理論」を同じ物差しで試す</small></div><div class="issue"><b>LAB</b><br>{e(today)}</div></div>
<p class="cv-kicker">今週の理論</p><h1 class="cv-h">{e(t['title'])}</h1>
<p class="cv-deck">{e(t['lead'])}</p>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ(カモメの記者)<br>公式の成績データ 2023-10〜{e(asof)} を独自に集計</span></div></div></header>
<main class="mag">
<section class="opener"><span class="label">検証する説</span><p class="belief">{e(t['belief'])}</p></section>
<section><span class="label">3つの物差し</span><div class="gauge"><div><b>① あるか</b><span>その現象が本当に起きているか(率と、偶然の幅)</span></div>
<div><b>② 知られているか</b><span>オッズが見込んだ率との比。1.0なら人気どおり=みんな知っている</span></div>
<div><b>③ 続くか</b><span>前半2年と後半1年で同じ向きに出るか</span></div></div></section>
<section><span class="label">結果</span>{measures_html(t['measures'])}{tables}</section>
<section class="side"><h3>予想への活かし方</h3><ul>{use}</ul></section>
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>{e(t['mikata'])}</p></blockquote>
<section class="method"><h3>データについて</h3><p>公式の成績データ(番組表・競走成績)と、締切時のオッズ(集めたレース分)を自分たちで集計。「オッズとの比」は、実際に1号艇が勝った割合を、オッズから見込まれる割合(控除を除いた市場の見立て)で割ったもの。
偶然の幅は、日ごとにまとめて引き直した90%区間。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ検証ラボ ・ 毎週1本。競艇をいろんな角度から。買い目は売りません。</span></footer></main>"""


def note_text(t: dict) -> str:
    out = [f"【タイトル案】", f"1. {t['title']}|{t['belief'][:24]}…をデータで検証", f"2. 検証ラボ:{t['title']} 3つの物差しで確かめた", "",
           "■検証する説", t["belief"], "", "■結論", t["lead"], "", "■3つの物差し",
           "①その現象は本当にあるか ②みんな知っているか(オッズが見込んだ率との比、1.0=人気どおり) ③時期を変えても出るか", ""]
    for name, m, v in t["measures"]:
        out.append(f"・{name}:{m['n']:,}レース、1号艇の1着率{pc(m['in1'])}(全体{pc(m['in1_ref'])})→ {v['exists']}。"
                   f"オッズとの比{m.get('market_ratio', float('nan')):.2f} → {v['known']}。{v.get('stable', '')}")
    for h, rows in t["tables"]:
        out += ["", f"■{h}"] + [f"・{x['venue']}{x['rno']}{'R' if x['rno'] != '' else ''} {pc(x['in1'])}({x['n']:,}レース)" for x in rows]
    out += ["", "■予想への活かし方"] + [f"・{x}" for x in t["use"]] + ["", f"ミカタのひと言:「{t['mikata']}」", "",
            "■データについて", "公式の成績データと締切時のオッズを自分たちで集計。この記事は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。"]
    return "\n".join(out)


def x_text(t: dict) -> str:
    m = t["measures"][0][1]
    body = (f"【検証ラボ】{t['title']}\n\n説:{t['belief']}\n\n調べたら:{t['lead'].split('。')[0]}。\n\n"
            f"オッズとの比は{m.get('market_ratio', float('nan')):.2f}(1.0=人気どおり)。\n\nみんなはこの説、信じてた?")
    if xlen(body) > 280:
        body = f"【検証ラボ】{t['title']}\n\n{t['lead'].split('。')[0]}。\n\nオッズとの比{m.get('market_ratio', float('nan')):.2f}(1.0=人気どおり)。\n\nみんなはこの説、信じてた?"
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
