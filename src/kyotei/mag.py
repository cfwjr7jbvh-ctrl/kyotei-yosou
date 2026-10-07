"""ミカタ新聞(大会の特集号)を雑誌の記事の水準で組む: 文章(巻頭リード・選手ごとの記事)と紙面(HTML)。

文章の決まりごと(発信方針):
- 数字はすべてカード(racer_card)と集計(nerai・occult_check)のもの。新しい数字を作らない
- 使う「型」は、時期を変えても同じ選手に出ると確かめたものだけ(trait_reliability.py)
- 選手をけなさない。断定しない(予想は読者のもの)。的中・儲けの話はしない
- ミカタ(カモメの記者)のひと言は、親しみやすい話し言葉で、押しつけない
紙面: 題字と表紙 → 巻頭リード → 目次 → 選手の特集(見出し・リード・本文・数字の図・ミカタのひと言)→ 早見表 → 囲み → データについて
"""
from __future__ import annotations

import datetime as dt
import html
import math

from . import nerai
from . import racer_card as rc
from .emblem import emblem_svg  # noqa: E402
from .card_render import gull_svg, radar_svg
from .xtext import xlen  # noqa: F401

e = html.escape
LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
LANE_FG = ["#111111", "#ffffff", "#ffffff", "#ffffff", "#111111", "#ffffff"]
PREF = {1: "群馬", 2: "埼玉", 3: "東京", 4: "東京", 5: "東京", 6: "静岡", 7: "愛知", 8: "愛知", 9: "三重", 10: "福井", 11: "滋賀",
        12: "大阪", 13: "兵庫", 14: "徳島", 15: "香川", 16: "岡山", 17: "広島", 18: "山口", 19: "山口", 20: "福岡", 21: "福岡",
        22: "福岡", 23: "佐賀", 24: "長崎"}


def pct(v) -> str:
    return "-" if v is None else f"{v:.0%}"


def topp(p) -> str:
    return f"上位{max(1, round(100 - p))}%" if p is not None else ""


# ---------------------------------------------------------------- ミカタのひと言
MIKATA = {
    "start": "スタート勝負になりそうな並びなら、この人が主役かも。展示のSTもあわせて見てみよう",
    "ex": "展示のSTがそのまま本番に出やすいタイプ。展示で速かったら、信じてみるのもアリだよ",
    "ex2": "展示のSTが遅く見えても、慌てなくていいよ。本番でちゃんと合わせてくるから",
    "nige": "1号艇に入ったら、素直に信じるか、あえて崩れる筋を探すか。こういう見方もあるよ",
    "sashi": "2コースに入ったら差しの筋。1号艇がちょっと流れる展開を想像してみて",
    "makuri": "3・4コースに入ったら一撃に注意。内の艇のスタートとセットで見るのがコツ",
    "mz": "3コースより外なら、まくり差しの筋。1マークで内の艇の間が空くかがカギだね",
    "out": "外枠でも3着には残してくる。ヒモに入れるかどうか、悩みどころだね",
    "front": "進入が動きやすい人。展示の進入を見てから組み立てると楽しいよ",
    "exlate": "展示タイムが平凡でも、評価を下げすぎないのが吉かも",
    "growth": "いま勢いがある。この伸び、4割くらいは次の3か月も続くってデータもあるよ",
    "stable": "とにかく舟券に絡む。3着までに入れるか迷ったら、思い出してみて",
}


def mikata(t: dict) -> str:
    return MIKATA.get(t["cat"], "数字を知っていると、レースの見え方が少し変わるよ")


# ---------------------------------------------------------------- 文章
def _pick(variants: list[str], key: int) -> str:
    return variants[key % len(variants)]


def deck(c: dict, t: dict) -> str:
    """見出しの下のリード。見出しの数字はくり返さず、どんな選手かを言葉で伝える(数字の中身は本文)。"""
    k, g, cat, rid = c["kim"], rc.GROUP_NAME.get(c["grp"], ""), t["cat"], c["id"]
    if cat == "start":
        return _pick([f"スリットで先手を取れる人。{g}で{topp(c['st']['grp'])}に入るスタートが、いちばんの武器だ。",
                      f"どの並びでも、まずスタートで主導権を握りにいく。{g}の{topp(c['st']['grp'])}という数字がそれを物語る。"], rid)
    if cat == "ex":
        return "展示を見れば、本番が読める。見る側にとって、いちばんありがたいタイプだ。"
    if cat == "ex2":
        return "展示では見せず、本番で踏み込んでくる。展示のSTだけで評価を下げるのは早い。"
    if cat == "nige":
        return _pick([f"1号艇に入ったときの信頼度は、{g}の中でも指折り。ターンの出口で後続を離していく。",
                      f"インに入れば、まず崩れない。{g}の{topp(k['nige']['grp'])}という逃げの数字がその証拠だ。"], rid)
    if cat == "sashi":
        return f"内の艇が流れた一瞬を逃さない。差しを「武器」と呼べる数少ない一人で、{g}の{topp(k['sashi']['grp'])}だ。"
    if cat == "makuri":
        return f"外から一撃で流れを変える。まくりで勝った数は{g}の{topp(k['makuri']['grp'])}に入る。"
    if cat == "mz":
        return f"いちばん難しい決まり手を、得意と言える。まくり差しの数字は{g}の{topp(k['mz']['grp'])}だ。"
    if cat == "out":
        return "外枠でも消えない。不利なコースから、3着までに残してくる力がある。"
    if cat == "front":
        return "枠なりでは終わらない。スタート展示の進入から、目が離せない一人だ。"
    if cat == "exlate":
        return "展示タイムで判断するのは早い。本番の着順は、展示の数字ほど落ちない。"
    if cat == "growth":
        return "いま、いちばん伸びている一人。勢いは、はっきり数字に出ている。"
    if cat == "stable":
        return f"どのコースからでも、3着までに顔を出す。コースの有利不利を差し引いても、{g}の{topp(c['p']['res3']['grp'])}だ。"
    return t["why"] + "。"


def body(c: dict, t: dict, bc: dict | None) -> list[str]:
    """本文(2〜4段落)。主役の型の詳しい数字 → 2つ目の型 → コース → 最近の調子。"""
    k, g, cat = c["kim"], rc.GROUP_NAME.get(c["grp"], ""), t["cat"]
    paras = []
    # 1) 主役の型の中身
    if cat == "start":
        paras.append(f"集計した{c['st']['n']}走の平均STは{rc.st_fmt(c['st']['avg'])}。フライングは期間中{c['st']['f']}回。"
                     "スタートで先手を取れるということは、1マークの主導権を握れるということでもある。内にいれば押し切り、外にいれば攻めの起点になる。")
    elif cat == "ex":
        paras.append(f"展示航走のSTと本番のSTのずれを{c['ex']['n']}走で平均すると{c['ex']['mae']:.3f}秒。"
                     "展示で速ければ本番も速く、展示で遅ければ本番も遅い。見る側にとって、これほど読みやすい選手はいない。")
    elif cat == "ex2":
        paras.append("展示のSTは、本番より遅めに出る選手が多い(全選手の中央値で約0.05秒)。"
                     f"その中でこの選手は、本番のSTが展示から平均{c['ex']['delta']:+.2f}秒。展示で見せないぶん、本番で踏み込んでくる。")
    elif cat == "nige":
        x = k["nige"]
        paras.append(f"1コースからの{x['n']}走で、逃げ切りは{x['w']}回(逃げ率{x['w'] / x['n']:.0%})。"
                     f"{g}の1コースの1着率は平均でも7割前後あるが、その中でも{topp(x['grp'])}に入る。ターンの出口で後続を離す形が、数字にそのまま表れている。")
    elif cat in ("sashi", "makuri", "mz"):
        x = k[cat]
        name = {"sashi": "差し", "makuri": "まくり", "mz": "まくり差し"}[cat]
        how = {"sashi": "内の艇がターンで膨らんだ瞬間に、その内側へ舳先をねじ込む。",
               "makuri": "スタートで内の艇をのぞき、1マークの手前で外から一気に絞り込む。",
               "mz": "内の艇がまくりに出た外側と、1号艇の間。空いた一瞬のすき間を突く、いちばん難しい決まり手だ。"}[cat]
        paras.append(f"{x['n']}走のうち{name}での1着が{x['w']}回。{how}"
                     f"この決まり手での勝ち数は、{g}の中で{topp(x['grp'])}に入る。")
    elif cat == "out":
        paras.append(f"4〜6コースからの{c['out']['n']}走で、3着内率はコースごとの平均を{c['out']['res'] * 100:+.0f}ポイント上回る。"
                     "外枠は不利が大きいぶん、そこで踏ん張れる選手は貴重だ。")
    elif cat == "front":
        paras.append(f"2枠より外に入った{c['front']['n']}走のうち、{c['front']['rate']:.0%}で枠より内のコースを取っている。"
                     "スタート展示の進入から、レースはもう始まっている。")
    elif cat == "exlate":
        ex = c["exlate"]
        paras.append(f"展示タイムがレース内で4位以下だった{ex['n']}走でも、3着内率は普段から{ex['res'] * 100:+.0f}ポイント。"
                     f"全選手の平均({(ex['pop'] or 0) * 100:+.0f}ポイント)より落ち込みが小さい。展示の数字に一喜一憂しないほうがいい選手だ。")
    elif cat == "growth":
        gr = c["growth"]
        paras.append(f"直近90日の{gr['n90']}走で勝率{gr['pts90']:.2f}。前の1年は{gr['prev']:.2f}だった。"
                     f"成長指数(伸び×0.41)は{gr['index']:+.2f}。過去3年の傾向では、直近の伸びの4割ほどが次の3か月も残っている。")
    elif cat == "stable":
        paras.append(f"集計した{c['n']}走の3着内率は{c['top3']:.0%}。1号艇が多い選手ほど数字は良く見えるので、コースごとの平均を差し引いて比べても、"
                     f"なお{c['res3'] * 100:+.0f}ポイント上回る。外を回されても、内を突いても、最後は3着までに入ってくる。")
    # 2) もうひとつの顔
    rest = [x for x in c["tags"] if x["t"] != t["t"]]
    if rest:
        r0 = rest[0]
        more = f"「{rest[1]['t']}」のタグも付いている。" if len(rest) > 1 else ""
        paras.append(f"もうひとつの顔は「{r0['t']}」。{r0['why']}。{more}")
    # 3) コース
    if bc:
        paras.append(f"コース別に見ると、光るのは{bc['c']}コースだ。{bc['n']}走で1着率{bc['win']:.0%}、3着内率{bc['top3']:.0%}。"
                     f"{g}の{bc['c']}コース平均(1着率{bc['avg_win']:.0%}・3着内率{bc['avg_top3']:.0%})を上回り、本人のほかのコースと比べても高い。")
    else:
        c1 = c["courses"][0]
        if c1["n"]:
            paras.append(f"1コースでは{c1['n']}走で1着率{pct(c1['win'])}、3着内率{pct(c1['top3'])}。")
    # 4) 最近
    sr = c.get("series")
    gr = c["growth"]
    tail = []
    if cat != "growth" and gr.get("index") is not None and gr["index"] >= 0.2:
        tail.append(f"直近90日の勝率は{gr['pts90']:.2f}(前の1年は{gr['prev']:.2f})と上向きだ")
    if sr and sr.get("finishes"):
        tail.append(f"直近の節({sr['venue']}、{sr['from'][5:].replace('-', '/')}〜{sr['to'][5:].replace('-', '/')})の着順は{' '.join(sr['finishes'])}")
    if tail:
        paras.append("。".join(tail) + "。")
    return paras


def issue_lead(sel: list[dict], picks, trend: dict | None, venue: str | None, name: str) -> list[str]:
    """巻頭リード: 出場選手の顔ぶれと場の傾向から、この大会の見どころを。"""
    n = len(sel)
    cls = {}
    for c in sel:
        cls[c["class"]] = cls.get(c["class"], 0) + 1
    tagc = {}
    for c in sel:
        for t in c["tags"]:
            nm = "上り調子" if t["t"] == "急成長中" else t["t"]
            tagc[nm] = tagc.get(nm, 0) + 1
    local = sum(1 for c in sel if venue and c.get("branch") == PREF.get(next((j for j, v in rc.VENUES.items() if v == venue), 0)))
    paras = []
    a1 = cls.get("A1", 0)
    paras.append(f"{venue + 'で開かれる' if venue else ''}{name}に、{n}人が集まる。{'全員がA1級' if a1 == n else f'A1は{a1}人'}"
                 + (f"、地元{PREF.get(next((j for j, v in rc.VENUES.items() if v == venue), 0), '')}支部からは{local}人" if venue and local else "")
                 + "。過去3年・約17万レースの成績から、ひとりひとりの“型”を読んだ。")
    if trend and venue:
        tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
        nt = trend["nat_top"] if tp is trend["top"] else trend["nat_all"]
        lbl = "トップ級のレースでも" if tp is trend["top"] else ""
        d = tp["c1"] - nt["c1"]
        kmax = max(trend["kim_non1"].items(), key=lambda x: x[1])
        if d <= -0.04:
            paras.append(f"まず水面。{venue}は{lbl}1号艇の1着率が{tp['c1']:.0%}と、全国({nt['c1']:.0%})より低い。インが絶対ではない水面で、"
                         f"1号艇以外が勝つときは{kmax[0]}がいちばん多い({kmax[1]:.0%})。")
        elif d >= 0.04:
            paras.append(f"まず水面。{venue}は{lbl}1号艇の1着率が{tp['c1']:.0%}と、全国({nt['c1']:.0%})より高い。インが強い水面で、"
                         f"それを崩すとすれば{kmax[0]}({kmax[1]:.0%})だ。")
        else:
            paras.append(f"まず水面。{venue}の1号艇の1着率は{lbl}{tp['c1']:.0%}で、全国({nt['c1']:.0%})とほぼ同じ。")
    attack = [(k, tagc.get(k, 0)) for k in ("まくり屋", "まくり差しの職人", "差し職人", "スタート職人", "イン逃げ番長")]
    attack = [x for x in attack if x[1]]
    if attack:
        paras.append("顔ぶれを型で数えると、" + "、".join(f"{k}{v}人" for k, v in attack) + "。"
                     "出走表が出たら、どの型の選手がどのコースに入ったかを見てほしい。それだけで、1マークの絵が少し見えてくる。")
    paras.append("ここに載せるのは、時期を変えても同じ選手に出ると確かめた「本物の型」だけだ。"
                 "「勝負駆けに強い」「○○巧者」のような、よく聞くけれど時期で入れ替わりやすい話は、後半のジンクス検証にまとめた。")
    return paras


USE_STEPS = ["① 出走表が出たら → 「狙い目の早見表」で、得意なコースに入った選手を探す",
             "② 展示を見たら → 「展示STを信じていい選手」かどうかをチェック",
             "③ 迷ったら → 注目選手の「ミカタのひと言」を読み返す"]


# ---------------------------------------------------------------- 図
def lane_tile(i: int, cls: str = "lt") -> str:
    return f'<span class="{cls}" style="background:{LANE_BG[i]};color:{LANE_FG[i]}">{i + 1}</span>'


def course_bars(c: dict) -> str:
    """コース別の1着率(濃い)と3着内率(薄い)の横棒。"""
    rows = []
    for x in c["courses"]:
        w, t3 = (x["win"] or 0), (x["top3"] or 0)
        rows.append(f'<div class="cb">{lane_tile(x["c"] - 1)}<div class="cb-tr"><i class="t3" style="width:{t3 * 100:.0f}%"></i>'
                    f'<i class="w" style="width:{w * 100:.0f}%"></i></div><span class="cb-n"><b>{pct(x["win"])}</b>/{pct(x["top3"])}'
                    f'<small>{x["n"]}走</small></span></div>')
    return '<div class="cbars"><div class="cb-h"><span>コース</span><span>1着/3着内</span></div>' + "".join(rows) + "</div>"


def diagram(cat: str) -> str:
    """決まり手の型の図(上から見た1マーク)。どの選手にも共通の模式図で、実際の航跡ではない。"""
    if cat not in ("start", "nige", "sashi", "makuri", "mz"):
        return ""
    W, H = 300, 170
    # 1マーク(70,40)。艇の線はマークから半径17以上はなして回る(2026-10-07 ユーザー「ターンマークに近くない?」)
    mark = '<circle cx="70" cy="40" r="7" fill="#ffe100" stroke="#111" stroke-width="2.5"/><path d="M63 40h14" stroke="#e60012" stroke-width="3"/>'
    lanes = "".join(f'<path d="M300 {58 + 18 * i}H120" stroke="#111" stroke-opacity=".12" stroke-width="1" stroke-dasharray="4 4"/>' for i in range(6))
    wide1 = "M290 58 C200 58 120 60 80 66 C44 72 30 52 34 36 C38 14 70 8 120 8 C180 8 230 10 260 12"     # 1号艇がふくらむ
    tight1 = "M290 58 C200 58 110 58 70 58 A18 18 0 0 1 70 22 C120 22 160 24 200 26"                    # 1号艇が小回り
    arrow = lambda d, col, w=5, dash="": (f'<path d="{d}" fill="none" stroke="#111" stroke-width="{w + 3}" stroke-linecap="round" {dash}/>'  # noqa: E731
                                         f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" {dash} marker-end="url(#ah)"/>')
    defs = '<defs><marker id="ah" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#111"/></marker></defs>'
    paths = ""
    label = ""
    if cat == "nige":
        paths = arrow("M290 58 C200 58 110 58 70 58 A18 18 0 0 1 70 22 C120 22 170 22 210 24", "#ffffff")
        label = "1号艇が先にターンして、そのまま逃げる"
    elif cat == "sashi":
        paths = arrow(wide1, "#bdbdbd", 4, 'stroke-dasharray="6 5"') + \
            arrow("M290 76 C210 76 140 70 100 62 C80 58 58 60 53 46 C49 34 58 23 72 22 C120 20 190 24 250 28", "#17191c")
        label = "1号艇がふくらんだ内側を、2号艇が差す"
    elif cat == "makuri":
        paths = arrow(tight1, "#bdbdbd", 4, 'stroke-dasharray="6 5"') + \
            arrow("M290 112 C230 110 170 94 120 72 C80 58 36 54 36 30 C36 6 100 4 160 4 C200 4 240 6 260 6", "#0b5fb4")
        label = "外の艇が、1マークの手前で内をまとめて絞る"
    elif cat == "mz":
        paths = arrow(wide1, "#bdbdbd", 4, 'stroke-dasharray="6 5"') + \
            arrow("M290 94 C230 92 170 80 124 68 C96 61 64 64 55 50 C48 38 54 26 68 22 C110 14 180 18 250 22", "#e3141b")
        label = "1号艇と外の艇の間の、すき間を突く"
    elif cat == "start":
        slit = '<path d="M150 44V160" stroke="#e60012" stroke-width="2.5" stroke-dasharray="5 4"/>'
        boats = "".join(f'<rect x="{124 if i == 2 else 100}" y="{54 + 18 * i}" width="28" height="12" rx="6" fill="{LANE_BG[i]}" stroke="#111" stroke-width="2"/>'
                        for i in range(6))
        stand = '<rect x="0" y="158" width="300" height="12" fill="#111"/><text x="150" y="167.5" font-size="9" font-weight="700" fill="#fff" text-anchor="middle">スタンド(観客席)</text>'
        return (f'<figure class="dg"><svg viewBox="0 0 {W} {H}" role="img" aria-label="スタートで一艇だけ前に出る図"><g transform="translate({W} 0) scale(-1 1)">{lanes}{slit}{boats}</g>'
                f'<text x="{W - 158}" y="40" font-size="12" font-weight="700" fill="#e60012" text-anchor="end">スリット</text>{stand}</svg>'
                f'<figcaption>スリットで一艇だけ前に出る。ここから主導権が生まれる(模式図)</figcaption></figure>')
    stand = '<rect x="0" y="158" width="300" height="12" fill="#111"/><text x="150" y="167.5" font-size="9" font-weight="700" fill="#fff" text-anchor="middle">スタンド(観客席)</text>'
    return (f'<figure class="dg"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{e(label)}">{defs}<g transform="translate({W} 0) scale(-1 1)">{lanes}{mark}{paths}</g>'
            f'<text x="{W - 70}" y="44" font-size="10" font-weight="700" fill="#111" text-anchor="end" dx="-14">1マーク</text>{stand}</svg>'
            f'<figcaption>{e(label)}(スタンドから見た模式図。艇は左から右へ走り、1マークを左に回る)</figcaption></figure>')


# ---------------------------------------------------------------- 紙面
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Shippori+Mincho:wght@500;700;800'
         '&family=Zen+Kaku+Gothic+New:wght@500;700;900&family=Oswald:wght@500;600;700&family=Zen+Maru+Gothic:wght@700&display=swap">')

CSS = """
:root{
  --paper:#f4efdf; --paper2:#e9e1c8; --card:#fffcf2; --ink:#111; --mute:#5e5848; --red:#e60012; --yellow:#ffe100; --rule:#111;
  --head:"Dela Gothic One","Zen Kaku Gothic New",system-ui,sans-serif; --sans:"Zen Kaku Gothic New","BIZ UDPGothic",system-ui,sans-serif;
  --serif:"Shippori Mincho","Zen Old Mincho","Hiragino Mincho ProN",serif; --num:"Oswald","Zen Kaku Gothic New",sans-serif;
  --maru:"Zen Maru Gothic","Zen Kaku Gothic New",sans-serif; --dots:rgba(17,17,17,.09);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#15130e;--paper2:#221e15;--card:#1c1912;--ink:#f3eedf;--mute:#b6ae98;--rule:#f3eedf;--dots:rgba(243,238,223,.07);color-scheme:dark}}
:root[data-theme="dark"]{--paper:#15130e;--paper2:#221e15;--card:#1c1912;--ink:#f3eedf;--mute:#b6ae98;--rule:#f3eedf;--dots:rgba(243,238,223,.07);color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.8 var(--sans);font-feature-settings:"palt"}
.mk{background:linear-gradient(transparent 60%,var(--yellow) 60%);box-decoration-break:clone;-webkit-box-decoration-break:clone;color:#111}
.lanebar{display:grid;grid-template-columns:repeat(6,1fr);height:8px}
.lanebar i:nth-child(1){background:#fff}.lanebar i:nth-child(2){background:#17191c}.lanebar i:nth-child(3){background:#e3141b}
.lanebar i:nth-child(4){background:#0b5fb4}.lanebar i:nth-child(5){background:#f5d00a}.lanebar i:nth-child(6){background:#12904a}
/* 表紙 */
.cover{background:#111;color:#fff;position:relative;overflow:hidden}
.cv-in{max-width:960px;margin:0 auto;padding:18px 16px 22px;display:grid;gap:14px}
.cv-top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;border-bottom:2px solid #fff;padding-bottom:8px;flex-wrap:wrap}
.brand{font:400 clamp(30px,8.5vw,56px)/1 var(--head);color:var(--yellow);letter-spacing:.04em}
.brand small{display:block;font:700 11px/1.4 var(--sans);color:#fff;letter-spacing:.2em;margin-top:4px}
.issue{font:700 12px/1.5 var(--sans);text-align:right;color:#ddd}
.issue b{display:inline-block;background:var(--red);color:#fff;font:400 15px/1 var(--head);padding:5px 8px;margin-bottom:4px}
.cv-kicker{margin:6px 0 0;font:700 12px var(--sans);letter-spacing:.3em;color:var(--yellow)}
.cv-h{margin:0;font:400 clamp(36px,10.5vw,76px)/1.08 var(--head);letter-spacing:.01em;text-wrap:balance}
.cv-h em{font-style:normal;color:var(--yellow)}
.cv-deck{margin:0;font:700 clamp(15px,4vw,18px)/1.75 var(--serif);color:#eee;max-width:36em}
.cv-row{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:16px;align-items:end}
@media (max-width:640px){.cv-row{grid-template-columns:1fr}}
.cv-graph{background:#fff;color:#111;padding:12px 14px;border-top:6px solid var(--red)}
.cv-graph .gl{font:700 12px var(--sans);color:#5e5848}
.cv-graph .gn{display:flex;align-items:baseline;gap:10px}
.cv-graph .gn b{font:700 clamp(64px,17vw,104px)/.95 var(--num);color:var(--red)}
.cv-graph .gn span{font:600 22px var(--num);color:#5e5848}
.dist{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;align-items:end;height:96px;margin-top:6px}
.dist div{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:3px;height:100%}
.dist i{display:block;width:72%;background:#111}
.dist div:first-child i{background:var(--red)}
.dist b{font:600 14px var(--num)}
.cv-lines{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.cv-lines li{border-left:6px solid var(--red);padding:2px 0 2px 10px;font:700 14px/1.4 var(--sans);color:#ddd}
.cv-lines li b{display:block;font:400 clamp(18px,4.8vw,24px)/1.25 var(--head);color:#fff}
.cv-by{display:flex;align-items:center;gap:10px;font:700 12px var(--sans);color:#ccc}
.cv-by svg{width:52px;height:52px;flex:none}
/* 本文の器 */
.mag{max-width:960px;margin:0 auto;padding:0 16px 56px;display:grid;gap:28px}
.opener{padding-top:22px;display:grid;gap:12px}
.label{display:inline-flex;align-items:center;gap:8px;font:700 12px var(--sans);letter-spacing:.25em;color:var(--red)}
.label::before{content:"";width:22px;height:3px;background:var(--red)}
.opener h2{margin:0;font:400 clamp(26px,7vw,40px)/1.2 var(--head);text-wrap:balance}
.prose{font:500 16.5px/2 var(--serif);max-width:38em}
.prose p{margin:0 0 1em}
.prose p.dc::first-letter{float:left;font:400 3.4em/1 var(--head);color:var(--red);margin:.08em .12em 0 0}
.howto{background:#111;color:#fff;padding:12px 14px 14px;border-left:10px solid var(--red)}
.howto h3{margin:0 0 6px;font:400 18px var(--head);color:var(--yellow)}
.howto ol{margin:0;padding-left:1.4em;display:grid;gap:4px;font:700 14.5px/1.6 var(--sans)}
.howto li::marker{color:var(--yellow);font-family:var(--num)}
.toc{border-top:4px solid var(--rule);border-bottom:1px solid var(--rule);padding:10px 0}
.toc h3{margin:0 0 6px;font:400 18px var(--head)}
.toc ol{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:2px 18px}
.toc li a{display:grid;grid-template-columns:2.2em minmax(0,1fr);gap:6px;align-items:baseline;padding:5px 0;border-bottom:1px dotted var(--mute);color:inherit;text-decoration:none}
.toc .n{font:600 18px var(--num);color:var(--red)}
.toc .nm{font:700 15px var(--sans)}
.toc .tg{display:block;font-size:12px;color:var(--mute)}
.sect{display:flex;align-items:baseline;gap:12px;border-bottom:4px solid var(--rule);padding-bottom:6px;margin-top:8px}
.sect b{font:400 clamp(24px,6.4vw,34px)/1.1 var(--head)}
.sect span{font:700 12px var(--sans);letter-spacing:.2em;color:var(--red)}
/* 特集(選手) */
.feat{background:var(--card);border-top:8px solid var(--rule);padding:16px 16px 18px;display:grid;gap:12px;box-shadow:0 1px 0 var(--rule)}
.ft-head{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;align-items:end}
.ft-no{font:700 clamp(56px,15vw,88px)/.8 var(--num);color:transparent;-webkit-text-stroke:2px var(--red)}
.ft-meta{display:block;font:700 12px var(--sans);color:var(--mute);letter-spacing:.08em}
.ft-head h2{margin:0;font:400 clamp(32px,9vw,52px)/1.05 var(--head);letter-spacing:.02em}
.ft-tag{justify-self:start;display:inline-flex;align-items:center;gap:10px;background:var(--red);color:#fff;padding:6px 12px 7px;transform:skewX(-10deg);box-shadow:4px 4px 0 #111}
.ft-tag > *{transform:skewX(10deg)}
.ft-tag b{font:400 clamp(18px,4.8vw,24px)/1.1 var(--head)}
.ft-tag i{font-style:normal;color:var(--yellow);font-size:16px;letter-spacing:1px}
.ft-catch{margin:4px 0 0;font:400 clamp(24px,6.4vw,36px)/1.32 var(--head);text-wrap:balance}
.ft-deck{margin:0;font:700 clamp(15.5px,4vw,18px)/1.8 var(--serif);border-left:4px solid var(--red);padding-left:12px}
.ft-grid{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:720px){.ft-grid{grid-template-columns:1fr}}
.ft-info{display:grid;gap:12px;background:var(--paper);padding:12px;border:2px solid var(--rule)}
.ft-big{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;border-bottom:2px solid var(--rule);padding-bottom:6px}
.ft-big b{font:700 clamp(54px,14vw,76px)/.9 var(--num);color:var(--red)}
.ft-big small{font:700 12.5px/1.4 var(--sans);color:var(--mute)}
.dg{margin:0;display:grid;gap:2px}
.dg svg{width:100%;height:auto;background:#d9ecf2;border:1.5px solid #111}
.dg figcaption,.ft-info figcaption{font-size:11.5px;color:var(--mute);line-height:1.5}
.radar{width:100%;max-width:320px;height:auto;justify-self:center}
.radar .rg{fill:none;stroke:var(--mute);stroke-opacity:.35;stroke-width:1}
.radar .rd{fill:var(--red);fill-opacity:.22;stroke:var(--red);stroke-width:2.2;stroke-linejoin:round}
.radar text{font-size:11px;fill:var(--mute);font-weight:700}
.radar .rv{font-family:var(--num);font-weight:600;fill:var(--ink);font-size:13px}
.cbars{display:grid;gap:5px}
.cb-h{display:flex;justify-content:space-between;font:700 11px var(--sans);color:var(--mute)}
.cb{display:grid;grid-template-columns:24px minmax(0,1fr) 88px;gap:8px;align-items:center}
.cb-tr{position:relative;height:14px;background:rgba(127,127,127,.15)}
.cb-tr i{position:absolute;left:0;top:0;bottom:0}
.cb-tr .t3{background:var(--red);opacity:.35}
.cb-tr .w{background:var(--red)}
.cb-n{font:500 13px var(--num);text-align:right;white-space:nowrap}
.cb-n b{font-weight:700;font-size:15px}
.cb-n small{font:500 10.5px var(--sans);color:var(--mute);margin-left:4px}
.lt{display:inline-grid;place-items:center;width:24px;height:24px;font:700 15px var(--num);box-shadow:inset 0 0 0 1.5px rgba(0,0,0,.5)}
.ft-quote{margin:0;display:grid;grid-template-columns:64px minmax(0,1fr);gap:12px;align-items:center}
.ft-quote svg{width:64px;height:64px}
.ft-quote p{margin:0;position:relative;background:#fff;color:#111;border:2.5px solid #111;border-radius:16px;padding:10px 14px;font:700 15.5px/1.7 var(--maru)}
.ft-quote p::before{content:"";position:absolute;left:-11px;top:50%;margin-top:-9px;border:9px solid transparent;border-right-color:#111;border-left:0}
.ft-quote p small{display:block;font:700 11px var(--sans);color:var(--red);letter-spacing:.1em}
.ft-side{background:#111;color:#fff;padding:10px 14px;font:700 14px/1.7 var(--sans)}
.ft-side b{display:block;color:var(--yellow);font:400 15px var(--head)}
.emb{vertical-align:middle;margin-right:6px;flex:0 0 auto}
.ft-tags{list-style:none;margin:0;padding:8px 0 0;border-top:1px dashed var(--mute);display:grid;gap:4px}
.ft-tags li{font-size:12.5px;color:var(--mute)}
.ft-tags li b{color:var(--ink);font-size:13.5px;margin-right:6px}
.ft-tags li i{font-style:normal;color:var(--red)}
.alt{font-size:12px;color:var(--mute)}
.alt ul{margin:4px 0 0;padding-left:1.2em}
/* 早見表 */
.chart{background:var(--card);border:3px solid var(--rule)}
.chart h3{margin:0;background:#111;color:var(--yellow);font:400 clamp(19px,5vw,24px)/1.3 var(--head);padding:10px 14px}
.chart > p{margin:10px 14px 4px;font-size:12.5px;color:var(--mute)}
.wk{display:grid}
.wk-row{display:grid;grid-template-columns:64px minmax(0,1fr);border-top:2px solid var(--rule)}
.wk-l{display:grid;place-items:center;align-content:center;gap:2px;font:700 10.5px/1.2 var(--sans);text-align:center;padding:6px 2px}
.wk-l .lt{width:40px;height:44px;font-size:28px}
.wk-r{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-left:2px solid var(--rule)}
.wk-r div{padding:7px 8px;border-left:1px dotted var(--mute);display:grid;gap:0}
.wk-r div:first-child{border-left:0;background:rgba(255,225,0,.25)}
.wk-r b{font:700 14.5px/1.3 var(--sans)}
.wk-r em{font-style:normal;font:700 22px/1.1 var(--num);color:var(--red)}
.wk-r div:not(:first-child) em{color:var(--ink);font-size:19px}
.wk-r small{font-size:10.5px;color:var(--mute)}
@media (max-width:480px){.wk-r b{font-size:13px}.wk-r em{font-size:19px}}
/* 囲み */
.sides{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px}
.side{background:var(--card);border:3px solid var(--rule);padding:0 0 12px}
.side h3{margin:0 0 8px;background:var(--red);color:#fff;font:400 18px/1.35 var(--head);padding:8px 12px}
.side ul{margin:0 12px;padding-left:1.1em;display:grid;gap:5px;font-size:14px}
.side p{margin:6px 12px 0;color:var(--mute);font-size:12.5px}
.side p:has(+ ul),.side p:has(+ table){color:var(--ink);font-weight:700;font-size:13.5px}
.scn{border-collapse:collapse;width:calc(100% - 24px);margin:0 12px;font-size:13px}
.scn th,.scn td{padding:5px 4px;border-bottom:1px solid var(--mute);text-align:right;white-space:nowrap}
.scn tr:first-child th{background:#111;color:#fff;font-size:11.5px;text-align:center}
.scn th:first-child{text-align:left}
.scn td{font:600 16px var(--num)}
.scn tr.hi td{color:var(--red)}
.method{border-top:4px double var(--rule);padding-top:12px;font-size:12.5px;color:var(--mute);display:grid;gap:8px}
.method h3{margin:0;font:400 18px var(--head);color:var(--ink)}
.method dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;margin:0}
.method dt{font-weight:700;color:var(--ink)}
.method dd{margin:0}
.colophon{display:flex;align-items:center;gap:12px;border-top:2px solid var(--rule);padding-top:12px;font-size:12px;color:var(--mute)}
.colophon svg{width:44px;height:44px;flex:none}
.note-top{background:var(--yellow);color:#111;font:700 13px var(--sans);padding:8px 12px}
"""


def cover_hook(trend: dict | None, venue: str | None) -> str | None:
    """表紙の大見出し(HTML)。場の傾向に全国との差があるときだけ数字で言い切る。"""
    if not trend or not venue:
        return None
    tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
    nt = trend["nat_top"] if tp is trend["top"] else trend["nat_all"]
    d = tp["c1"] - nt["c1"]
    if d <= -0.04:
        return f"{e(venue)}の1号艇は<br><em>{tp['c1']:.0%}</em>しか勝てない"
    if d >= 0.04:
        return f"{e(venue)}のインは<br><em>{tp['c1']:.0%}</em>で逃げる"
    k = max(trend["kim_non1"].items(), key=lambda x: x[1])
    return f"{e(venue)}でインが負けるとき<br><em>{e(k[0])}</em>が{k[1]:.0%}"


def stars(t: dict) -> str:
    sc = t.get("score")
    if t.get("cat") in ("front", "growth", "exlate", "ex2") or sc is None:
        return ""
    return "★★★" if sc >= 99 else "★★" if sc >= 95 else "★" if sc >= 90 else ""


def big_stat(c: dict, t: dict) -> tuple[str, str]:
    k, cat = c["kim"], t["cat"]
    if cat == "start":
        return rc.st_fmt(c["st"]["avg"]), "平均ST"
    if cat == "ex":
        return f"{c['ex']['mae']:.3f}", "展示と本番のSTのずれ(秒)"
    if cat == "ex2":
        return f"{c['ex']['delta']:+.2f}", "展示→本番のST(秒)"
    if cat == "nige":
        return f"{k['nige']['w'] / max(1, k['nige']['n']):.0%}", f"逃げ率(1コース{k['nige']['n']}走)"
    if cat in ("sashi", "makuri", "mz"):
        name = {"sashi": "差し", "makuri": "まくり", "mz": "まくり差し"}[cat]
        return f"{k[cat]['w']}", f"{name}で勝った回数"
    if cat == "out":
        return f"{c['out']['res'] * 100:+.0f}", "4〜6コースの3着内率(コース平均との差、ポイント)"
    if cat == "front":
        return f"{c['front']['rate']:.0%}", "枠より内のコースに入った割合"
    if cat == "growth":
        return f"{c['growth']['pts90']:.2f}", f"直近90日の勝率(前の1年 {c['growth']['prev']:.2f})"
    if cat == "exlate":
        return f"{c['exlate']['res'] * 100:+.0f}", "展示タイム4位以下のときの3着内率(普段との差)"
    return f"{c['top3']:.0%}", "3着内率"


def feature(i: int, c: dict, t: dict, heads: list[str], bc: dict | None) -> str:
    g = rc.GROUP_NAME.get(c["grp"], "")
    num, lbl = big_stat(c, t)
    paras = body(c, t, bc)
    prose = "".join(f'<p{" class=dc" if j == 0 and not p[:1].isdigit() else ""}>{e(p)}</p>' for j, p in enumerate(paras))
    tags = "".join(f"<li>{emblem_svg(x['t'], 20)}<b>{e(x['t'])}<i>{stars(x)}</i></b>{e(x['why'])}</li>" for x in c["tags"][:5])
    alt = "".join(f"<li>{e(h)}</li>" for h in heads[1:])
    side = (f'<div class="ft-side"><b>狙い目のコース</b>{bc["c"]}コースに入ったら注目。{bc["n"]}走で1着率{bc["win"]:.0%}・3着内率{bc["top3"]:.0%}'
            f'({g}の{bc["c"]}コース平均は{bc["avg_top3"]:.0%})</div>') if bc else ""
    return f"""<article class="feat" id="r{c['id']}">
<div class="ft-head"><span class="ft-no">{i:02d}</span><div><span class="ft-meta">{e(c['class'] or '')} ・ {e(c['branch'] or '')}支部 ・ {int(c['age'] or 0)}歳</span><h2>{e(c['name'])}</h2></div></div>
<div class="ft-tag">{emblem_svg(t['t'], 44)}<b>{e(t['t'])}</b><i>{stars(t)}</i></div>
<h3 class="ft-catch"><span class="mk">{e(heads[0])}</span></h3>
<p class="ft-deck">{e(deck(c, t))}</p>
<div class="ft-grid"><div class="prose">{prose}</div>
<aside class="ft-info"><div class="ft-big"><b>{e(num)}</b><small>{e(lbl)}</small></div>{diagram(t['cat'])}
{radar_svg(c['radar'])}<figcaption>レーダーは{e(g)}の中での位置(100がトップ)</figcaption>{course_bars(c)}</aside></div>
<blockquote class="ft-quote">{gull_svg(64, bg="#ffffff", cls="q")}<p><small>ミカタのひと言</small>{e(mikata(t))}</p></blockquote>
{side}
<ul class="ft-tags">{tags}</ul>
{f'<details class="alt"><summary>見出しの別案(編集用)</summary><ul>{alt}</ul></details>' if alt else ''}
</article>"""


def chart(wt: dict) -> str:
    rows = []
    for crs in range(1, 7):
        m = nerai.METRIC[crs]
        lab = "逃げ切り" if crs == 1 else ("1着率" if m == "win" else "3着内率")
        cells = "".join(f"<div><b>{e(r['name'])}</b><em>{r['rate']:.0%}</em><small>{r['k']}/{r['n']}走</small></div>" for r in wt.get(crs, []))
        cells += "<div></div>" * (3 - len(wt.get(crs, [])))
        rows.append(f'<div class="wk-row"><div class="wk-l">{lane_tile(crs - 1)}<span>{lab}</span></div><div class="wk-r">{cells}</div></div>')
    return ('<section class="chart" id="chart"><h3>狙い目の早見表 コースが決まったらチェック</h3>'
            '<p>出走表と展示の進入が出たら、そのコースに入った選手がこの表にいるかを見てほしい。進入したコースごとの成績(過去3年)で、その大会の出場選手の上位3人。'
            '順位は、レース数の少なさを差し引いた見込みで付けている(数字は実際の成績)。</p>'
            f'<div class="wk">{"".join(rows)}</div></section>')


def cover(title: str, grade: str, name: str, venue: str | None, n: int, n_pick: int, trend: dict | None, hook: str | None,
          period: tuple[str, str], today: str) -> str:
    graph = ""
    if trend and venue:
        tp = trend["top"] if trend["top"].get("n", 0) >= 100 else trend["all"]
        nt = trend["nat_top"] if tp is trend["top"] else trend["nat_all"]
        lbl = "トップ級のレース" if tp is trend["top"] else "全レース"
        bars = "".join(f'<div><b>{tp["dist"][k]:.0%}</b><i style="height:{round(tp["dist"][k] * 100)}px"></i>{lane_tile(k - 1)}</div>' for k in range(1, 7))
        graph = (f'<div class="cv-graph"><div class="gl">{e(venue)}・{e(lbl)}の1号艇の1着率({tp["n"]}レース)</div>'
                 f'<div class="gn"><b>{tp["c1"]:.0%}</b><span>全国 {nt["c1"]:.0%}</span></div>'
                 f'<div class="gl">1着になったコースの割合</div><div class="dist">{bars}</div></div>')
    head = hook or f"{name}の{n}人を、データで読む"
    return f"""<header class="cover"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="cv-in">
<div class="cv-top"><div class="brand">ミカタ新聞<small>競艇をいろんな角度から</small></div>
<div class="issue">{f'<b>{e(grade)}</b><br>' if grade else ''}{e(name)} 特集号<br>{e(venue or '')} ・ {e(today)}</div></div>
<p class="cv-kicker">巻頭特集</p>
<h1 class="cv-h">{head}</h1>
<p class="cv-deck">出場{n}人を、過去3年・約17万レースの成績で読む。買い目ではなく、あなたが自分で予想するための“材料”を集めた。</p>
<div class="cv-row">{graph}<ul class="cv-lines"><li><b>注目{n_pick}人の“型”</b>まくり屋、スタート職人、イン逃げ番長…</li>
<li><b>狙い目の早見表</b>コースが決まったら、ここを見る</li><li><b>ジンクス検証</b>「勝負駆けに強い」は本物か</li></ul></div>
<div class="cv-by">{gull_svg(52, bg="#f4efdf", cls="cv")}<span>文・データ ミカタ(カモメの記者)<br>公式の成績データ {e(period[0])}〜{e(period[1])} を独自に集計</span></div>
</div></header>"""


def page(title: str, venue: str | None, picks, sel: list[dict], wt: dict, trend: dict | None, sides: list[tuple[str, str]],
         rules: dict, note: str, hook: str | None, period: tuple[str, str]) -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    parts = title.split(" ")
    grade = parts[0] if parts[0] in ("SG", "PG1", "G1", "G2", "G3") else ""
    name = title[len(grade):].strip() if grade else title
    lead = issue_lead(sel, picks, trend, venue, name)
    toc = "".join(f'<li><a href="#r{c["id"]}"><span class="n">{i:02d}</span><span><span class="nm">{e(c["name"])}</span>'
                  f'<span class="tg">{emblem_svg(t["t"], 18)}{e(t["t"])} {stars(t)}</span></span></a></li>' for i, (c, t, *_x) in enumerate(picks, 1))
    feats = "\n".join(feature(i, c, t, heads, bc) for i, (c, t, heads, com, bc) in enumerate(picks, 1))
    sides_html = "".join(f'<section class="side"><h3>{e(h)}</h3>{b}</section>' for h, b in sides)
    shown = list(dict.fromkeys(("上り調子" if x["t"] == "急成長中" else x["t"]) for c, *_x in picks for x in c["tags"][:5]))
    basis = "".join(f"<dt>{emblem_svg(k, 22)}{e(k)}</dt><dd>{e(rules[k])}</dd>" for k in shown if k in rules)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex"><title>ミカタ新聞 {e(title)}</title>
{FONTS}<style>{CSS}</style></head><body>
{f'<div class="note-top">{e(note)}</div>' if note else ''}
{cover(title, grade, name, venue, len(sel), len(picks), trend, hook, period, today)}
<main class="mag">
<section class="opener"><span class="label">巻頭 ・ {e(name)}</span><h2>この大会は、ここを見る</h2>
<div class="prose">{''.join(f'<p{" class=dc" if j == 0 else ""}>{e(p)}</p>' for j, p in enumerate(lead))}</div></section>
<section class="howto"><h3>現地での使い方</h3><ol>{''.join(f"<li>{e(x[2:])}</li>" for x in USE_STEPS)}</ol></section>
<nav class="toc"><h3>この号の注目選手</h3><ol>{toc}</ol></nav>
<div class="sect"><b>注目選手の“型”</b><span>FEATURE</span></div>
{feats}
<div class="sect"><b>狙い目の早見表</b><span>CHART</span></div>
{chart(wt)}
<div class="sect"><b>データの囲み</b><span>COLUMN</span></div>
<div class="sides">{sides_html}</div>
<section class="method"><h3>この号のデータについて</h3>
<p>数字はすべて、公式の成績データ(番組表・競走成績)を自分たちで集計したもの。出走表・オッズの表・写真は使っていない。
「上位◯%」は同じ級別(A1・A2・B級)の中での位置で、★★★は上位1%、★★は上位5%、★は上位10%。
3着内率は、コースの有利不利を差し引いた「上積み」で比べている。決まり手の図は型を説明する模式図で、実際の航跡ではない。</p>
<dl>{basis}</dl>
<p>この新聞は予想を楽しむための読み物で、舟券の的中や利益を約束するものではありません。舟券の購入は20歳になってから。</p></section>
<footer class="colophon">{gull_svg(44, bg="#f4efdf", cls="co")}<span>ミカタ新聞 ・ 文・データ ミカタ(カモメの記者)・ {e(today)}<br>競艇をいろんな角度から。予想が楽しくなる材料を。</span></footer>
</main></body></html>"""


WALL_CSS = """
*{box-sizing:border-box}
body{margin:0;width:1080px;height:1920px;background:#f4efdf;color:#111;font-family:"Zen Kaku Gothic New","Noto Sans CJK JP",sans-serif;font-feature-settings:"palt"}
.w{width:1080px;height:1920px;display:grid;grid-template-rows:16px auto 1fr auto}
.lanebar{display:grid;grid-template-columns:repeat(6,1fr)}
.lanebar i:nth-child(1){background:#fff}.lanebar i:nth-child(2){background:#17191c}.lanebar i:nth-child(3){background:#e3141b}
.lanebar i:nth-child(4){background:#0b5fb4}.lanebar i:nth-child(5){background:#f5d00a}.lanebar i:nth-child(6){background:#12904a}
.hd{background:#111;color:#fff;padding:34px 50px 30px;border-bottom:10px solid #e60012;display:grid;gap:8px}
.hd .b{font:400 40px/1 "Dela Gothic One",sans-serif;color:#ffe100;letter-spacing:.04em}
.hd h1{margin:0;font:400 84px/1.05 "Dela Gothic One",sans-serif}
.hd p{margin:0;font:700 30px/1.4 "Zen Kaku Gothic New",sans-serif;color:#ddd}
.hd p b{background:#e60012;color:#fff;font:400 30px/1 "Dela Gothic One",sans-serif;padding:4px 10px;margin-right:12px}
.rows{display:grid;grid-template-rows:repeat(6,1fr)}
.row{display:grid;grid-template-columns:170px minmax(0,1fr);border-bottom:4px solid #111}
.lab{display:grid;place-items:center;align-content:center;gap:8px;border-right:4px solid #111;padding:8px}
.lt{display:grid;place-items:center;width:112px;height:120px;font:700 92px/1 "Oswald",sans-serif;box-shadow:inset 0 0 0 5px rgba(0,0,0,.55)}
.lab .lb{font:900 24px/1.2 "Zen Kaku Gothic New",sans-serif;text-align:center}
.ps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}
.p{display:grid;align-content:center;gap:4px;padding:10px 18px;border-left:2px dotted #5e5848}
.p:first-child{border-left:0;background:rgba(255,225,0,.35)}
.p b{font:900 38px/1.2 "Zen Kaku Gothic New",sans-serif}
.p em{font-style:normal;font:700 74px/1 "Oswald",sans-serif;color:#111}
.p:first-child em{color:#e60012;font-size:88px}
.p small{font:700 22px "Zen Kaku Gothic New",sans-serif;color:#5e5848}
.ft{background:#111;color:#ddd;padding:26px 50px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:24px;align-items:center;font:700 25px/1.5 "Zen Kaku Gothic New",sans-serif}
.ft svg{width:110px;height:110px}
.ft b{color:#ffe100;font:400 30px "Dela Gothic One",sans-serif}
"""


def chart_image_html(title: str, venue: str | None, wt: dict) -> str:
    """狙い目の早見表の画像(1080×1920、スマホの待ち受けサイズ)。保存して現地で見る用。"""
    import re as _re
    m = _re.match(r"(SG|PG1|G1|G2|G3)\s*(.*)", title)
    grade, name = (m.group(1), m.group(2)) if m else ("", title)
    rows = []
    for crs in range(1, 7):
        mt = nerai.METRIC[crs]
        lab = "逃げ切り" if crs == 1 else ("1着率" if mt == "win" else "3着以内")
        ps = "".join(f'<div class="p"><b>{e(r["name"])}</b><em>{r["rate"]:.0%}</em><small>{r["k"]}/{r["n"]}走</small></div>' for r in wt.get(crs, []))
        ps += '<div class="p"></div>' * (3 - len(wt.get(crs, [])))
        rows.append(f'<div class="row"><div class="lab"><span class="lt" style="background:{LANE_BG[crs - 1]};color:{LANE_FG[crs - 1]}">{crs}</span>'
                    f'<span class="lb">{lab}</span></div><div class="ps">{ps}</div></div>')
    return f"""<!doctype html><meta charset="utf-8">{FONTS}<style>{WALL_CSS}</style>
<div class="w"><div class="lanebar"><i></i><i></i><i></i><i></i><i></i><i></i></div>
<div class="hd"><div class="b">ミカタ新聞 ・ 保存版</div><h1>狙い目の早見表</h1>
<p>{f'<b>{e(grade)}</b>' if grade else ''}{e(venue or '')} {e(name)}</p><p>コースが決まったら、ここを見る</p></div>
<div class="rows">{''.join(rows)}</div>
<div class="ft">{gull_svg(110, bg="#f4efdf", cls="wl")}<div><b>出場選手の、そのコースでの成績の上位3人</b><br>
1〜4コースは1着率、5・6コースは3着以内の率(過去3年、進入したコースで集計。走数が少ない選手は補正して選出)。舟券は20歳になってから</div></div></div>"""
