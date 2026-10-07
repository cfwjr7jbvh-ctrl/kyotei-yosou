"""早見表のカード(X 用 1080×1350)。数字は scripts/hayami.py の hayami.json から。

2026-10-07 ユーザー「みんなが欲しがる情報まとめシート」「出目確率表」「各場の特徴まとめ、比較版や特化版」「めちゃくちゃいいの作り込んで」。
保存してもらう(ブックマーク)ための表。xcard.py と同じ決まり(いちばん小さい文字34px、主役の数字64px以上、スマホの幅で読める)。
色: インに有利=緑、不利=赤、全国の線=灰の点線。数字は「%」、差は「47%→66%」。買い目・回収率・配当の額は出さない。
"""
from __future__ import annotations

import html

from kyotei.card_render import LANE_BG, LANE_FG
from kyotei.xcard import BASE_CSS, F, INK, MINUS, MUTE, PLUS, _foot, _lanes_bar, lane_box

e = html.escape
NAVY = "#17345a"
SRC = "公式の成績 2023/10〜2026/9 約15万レースを集計"


def pct(x, d=0) -> str:
    return "-" if x is None else f"{x * 100:.{d}f}%"


def every(x) -> str:
    """出目の割合を「◯レースに1回」に。"""
    return "-" if not x else f"{round(1 / x):,}レースに1回"


CSS = BASE_CSS + f"""
.top h1{{font:900 76px/1.12 {F};margin:8px 0 0}} .top .sub{{font:700 34px/1.35 {F};color:#d9dde0;margin-top:12px}}
.body{{padding:44px 60px 0}}
.q{{position:absolute;left:60px;right:60px;bottom:150px;font:900 40px/1.35 {F};color:{INK}}}
.note{{font:700 34px/1.4 {F};color:{MUTE}}}
.tag{{display:inline-block;font:900 26px {F};padding:2px 8px;border-radius:6px;vertical-align:4px;background:#2b2f36;color:#fff}}
.tag.n{{background:#3b2a6b}} .tag.k{{background:#6b5b2a}}
.cols{{display:flex;gap:40px}} .col{{flex:1;min-width:0}}
.row{{display:flex;align-items:center;height:66px;border-bottom:2px solid #e2dccb}}
.row .rk{{width:50px;font:900 34px {F};color:{MUTE}}} .row .nm{{width:126px;font:900 40px {F};white-space:nowrap}} .row .tg{{width:56px}}
.row .br{{flex:1;height:26px;background:#e6e0cf;position:relative;margin:0 12px 0 4px}} .row .br i{{position:absolute;left:0;top:0;bottom:0}}
.row .br u{{position:absolute;top:-8px;bottom:-8px;border-left:3px dashed #8a8f96}}
.row .v{{width:96px;text-align:right;font:900 42px {F}}}
.pan{{background:#fffdf6;border-top:12px solid;padding:16px 24px 10px;margin-bottom:22px}} .pan h2{{font:900 42px {F};margin:0 0 4px}}
.pan .nat{{font:700 34px {F};color:{MUTE};margin-bottom:6px}}
.big{{font:900 150px/1 {F};letter-spacing:-.02em}} .big small{{font:900 60px {F}}}
.dm{{display:flex;align-items:center;height:64px;border-bottom:2px solid #e2dccb}} .dm .rk{{width:52px;font:900 34px {F};color:{MUTE}}}
.dm .cb{{display:flex;gap:4px;width:200px}} .dm .cb span{{width:56px;height:52px;display:inline-flex;align-items:center;justify-content:center;font:900 36px {F};border:3px solid #111}}
.dm .sh{{width:140px;text-align:right;font:900 44px {F}}} .dm .ev{{flex:1;padding-left:22px;font:700 34px {F};color:{MUTE}}}
.dm .pp{{font:900 30px {F};padding:4px 12px;border-radius:8px;color:#fff}}
"""


def _page(kicker: str, title: str, sub: str, body: str, q: str = "", foot: str | None = None) -> str:
    foot = foot or SRC
    return (f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="c">'
            f'<div class="top"><small>{e(kicker)}</small><h1>{title}</h1>{f"<div class=sub>{e(sub)}</div>" if sub else ""}{_lanes_bar()}</div>'
            f'<div class="body">{body}</div>{f"<div class=q>{q}</div>" if q else ""}{_foot(foot)}</div></body></html>')


def _bar_row(rank, name, val, nat, vmax, tags=None, col=None):
    col = col or (PLUS if val >= nat + 0.005 else MINUS if val <= nat - 0.005 else "#7d858d")
    w = max(0.0, min(1.0, val / vmax)) * 100
    u = max(0.0, min(1.0, nat / vmax)) * 100
    rk = f'<span class="rk">{rank}</span>' if rank else ""
    tg = f'<span class="tg">{tags}</span>' if tags is not None else ""
    return (f'<div class="row">{rk}<span class="nm">{e(name)}</span>{tg}<span class="br"><i style="width:{w:.1f}%;background:{col}"></i>'
            f'<u style="left:{u:.1f}%"></u></span><span class="v" style="color:{col}">{pct(val)}</span></div>')


def _venues(d):
    return {int(k): v for k, v in d["venues"].items() if k != "0"}


# ---------------------------------------------------------------- 24場の比較
def cmp_in1(d: dict) -> str:
    vs = sorted(_venues(d).items(), key=lambda kv: -kv[1]["in1"])
    nat = d["venues"]["0"]["in1"]

    def tags(v, j):
        t = ""
        if (v.get("night_share") or 0) > 0.4:
            t += '<span class="tag n">夜</span>'
        if (v.get("moved") or 1) < 0.02:
            t += '<span class="tag k">固</span>'
        return t
    rows = [_bar_row(i + 1, v["name"], v["in1"], nat, 0.7, tags(v, j)) for i, (j, v) in enumerate(vs)]
    body = (f'<div class="cols"><div class="col">{"".join(rows[:12])}</div><div class="col">{"".join(rows[12:])}</div></div>'
            f'<p class="note" style="margin-top:14px"><span class="tag n">夜</span> ナイター ・ <span class="tag k">固</span> 進入固定 ・ 緑=全国より上・赤=下</p>')
    return _page("24場 早見表 ① インの強さ", "インが強い場・弱い場", f"1コースの1着率(点線=全国 {pct(nat)})", body, "")


def _rank_panel(title, items, nat, col, key_name, vmax):
    rows = "".join(_bar_row(i + 1, v["name"], x, nat, vmax, col=col) for i, (v, x) in enumerate(items))
    return f'<div class="col pan" style="border-color:{col}"><h2>{e(title)}</h2><div class="nat">全国は{pct(nat)}</div>{rows}</div>'


def _two(a_html, b_html, note=""):
    return f'<div class="cols" style="gap:24px">{a_html}{b_html}</div>' + (f'<p class="note" style="margin-top:6px">{e(note)}</p>' if note else "")


def cmp_kimarite(d: dict) -> str:
    vs = list(_venues(d).values())
    nk = d["venues"]["0"]["kimarite"]
    mk = sorted(((v, v["kimarite"]["まくり"]) for v in vs), key=lambda t: -t[1])[:9]
    sk = sorted(((v, v["kimarite"]["差し"]) for v in vs), key=lambda t: -t[1])[:9]
    body = _two(_rank_panel("まくり", mk, nk["まくり"], "#c8141c", "", 0.3), _rank_panel("差し", sk, nk["差し"], NAVY, "", 0.3),
                "1着の決まり手のうちの割合。点線=全国")
    return _page("24場 早見表 ② 決まり手", "まくりの場、差しの場", "決まり手が多い場 ベスト9", body, "")


def cmp_are(d: dict) -> str:
    vs = list(_venues(d).values())
    nat = d["venues"]["0"]["are"]
    hi = sorted(((v, v["are"]) for v in vs), key=lambda t: -t[1])[:9]
    lo = sorted(((v, v["are"]) for v in vs), key=lambda t: t[1])[:9]
    body = _two(_rank_panel("荒れる", hi, nat, "#c8141c", "", 0.3), _rank_panel("堅い", lo, nat, PLUS, "", 0.3),
                "3連単が31番人気より下で決まった割合。点線=全国")
    return _page("24場 早見表 ③ 荒れやすさ", "荒れる場、堅い場", "人気薄で決まりやすい場・決まりにくい場 ベスト9", body, "")


def cmp_wind(d: dict) -> str:
    vs = list(_venues(d).values())
    n = d["venues"]["0"]["wind"]
    drop = [v for v in vs if v["wind"]["ci"] and v["wind"]["ci"][1] < 0 and v["wind"]["n_strong"] >= 300]
    drop = sorted(drop, key=lambda v: v["wind"]["in1_strong"] - v["wind"]["in1_calm"])[:7]
    keep = [v for v in vs if v["wind"]["ci"] and v["wind"]["ci"][0] <= 0 <= v["wind"]["ci"][1] and v["wind"]["n_strong"] >= 300]
    rows = "".join(
        f'<div class="row"><span class="nm" style="width:170px">{e(v["name"])}</span><span class="note" style="flex:1">ふだん {pct(v["wind"]["in1_calm"])}</span>'
        f'<span class="v" style="width:300px;color:{MINUS}">→ {pct(v["wind"]["in1_strong"])}</span></div>' for v in drop)
    keep_s = "・".join(v["name"] for v in sorted(keep, key=lambda v: -v["in1"]))
    body = (f'<div class="pan" style="border-color:{MINUS}"><h2>風5m以上で、インが弱くなる場</h2>'
            f'<div class="nat">全国は {pct(n["in1_calm"])} → {pct(n["in1_strong"])}(1コースの1着率)</div>{rows}</div>'
            f'<div class="pan" style="border-color:#8a8f96"><h2>風が強くても、ほぼ変わらない場</h2><div style="font:900 44px/1.4 {F}">{e(keep_s)}</div></div>')
    return _page("24場 早見表 ④ 風", "風の日のイン", "レース時の風速5m以上と、5m未満の比較", body, "")


# ---------------------------------------------------------------- 場の特化版
def venue_profile(d: dict, j: int, event: str = "") -> str:
    v = d["venues"][str(j)]
    n = d["venues"]["0"]
    rank = 1 + sum(1 for x in _venues(d).values() if x["in1"] > v["in1"])
    col = PLUS if v["in1"] >= n["in1"] else MINUS
    cw = "".join(
        f'<div class="row" style="height:54px"><span class="nm" style="width:180px">{c}コース</span><span class="br"><i style="width:{min(1, v["course_win"][str(c)] / 0.7) * 100:.1f}%;background:{NAVY}"></i>'
        f'<u style="left:{min(1, n["course_win"][str(c)] / 0.7) * 100:.1f}%"></u></span><span class="v">{pct(v["course_win"][str(c)])}</span></div>' for c in range(1, 7))
    k, nk = v["kimarite"], n["kimarite"]
    kim = "".join(
        f'<div class="row" style="height:56px"><span class="nm" style="width:220px">{name}</span><span class="note" style="flex:1">全国 {pct(nk[name])}</span>'
        f'<span class="v" style="width:120px;color:{"#c8141c" if k[name] > nk[name] + 0.01 else INK}">{pct(k[name])}</span></div>' for name in ("逃げ", "まくり", "差し", "まくり差し"))
    body = (f'<div style="display:flex;align-items:flex-end;gap:30px"><div class="big" style="color:{col}">{pct(v["in1"])[:-1]}<small>%</small></div>'
            f'<div style="font:900 40px/1.4 {F};padding-bottom:14px">1コースの1着率<br><span style="color:{MUTE};font-size:36px">全国{pct(n["in1"])} ・ 24場中{rank}位</span></div></div>'
            f'<div class="note" style="margin:22px 0 4px">コースごとの1着率(点線は全国)</div>{cw}'
            f'<div class="note" style="margin:22px 0 4px">1着の決まり手(赤=全国より多い)</div>{kim}'
            f'<div class="note" style="margin-top:8px">水面: {e(v["water"])} ・ 人気薄で決まる割合 {pct(v["are"])}(全国{pct(n["are"])})</div>')
    return _page(f"{v['name']}の早見表 ①" + (f" ・ {event}" if event else ""), f"{e(v['name'])}は、こんな場", "", body, "", )


def venue_change(d: dict, j: int, event: str = "") -> str:
    """その場で、インの1着率が条件で変わること(本当のものだけ大きく)。"""
    v = d["venues"][str(j)]
    n = d["venues"]["0"]
    td = d.get("tide", {}).get(str(j))
    items = []
    if td and td.get("real"):
        items.append(("潮", f"干潮のころ {pct(td['in1_low'])}", f"満潮のころ {pct(td['in1_high'])}",
                      f"満潮・干潮の前後1時間。レース番号をそろえても{round(abs(td['diff']) * 100)}ポイント差、前の2年も最近の1年も同じ向き(気象庁の潮位表)",
                      PLUS if td["diff"] > 0 else MINUS))
    elif td and abs(td.get("diff_raw") or 0) >= 0.04:
        items.append(("潮(見かけの差に注意)", f"干潮のころ {pct(td['in1_low'])}", f"満潮のころ {pct(td['in1_high'])}",
                      f"差があるように見えるが、{'満潮' if td['diff_raw'] > 0 else '干潮'}は後半のレースに重なりがち。レース番号をそろえるとほぼ同じ",
                      "#8a8f96"))
    w = v["wind"]
    if w["ci"]:
        same = w["ci"][0] <= 0 <= w["ci"][1]
        items.append(("風5m以上", f"ふだん {pct(w['in1_calm'])}", f"風の日 {pct(w['in1_strong'])}",
                      ("風が強くても、ほぼ変わらない(全国は" if same else "全国も下がる(") + f"{pct(n['wind']['in1_calm'])}→{pct(n['wind']['in1_strong'])})",
                      "#8a8f96" if same else MINUS))
    if v.get("a1_in1"):
        b1 = v.get("b1_in1")
        items.append(("1号艇の級別(予選・一般戦)", f"B1 {pct(b1)}" if b1 else "", f"A1 {pct(v['a1_in1'])}",
                      f"全国は B1 {pct(n.get('b1_in1'))} → A1 {pct(n.get('a1_in1'))}", PLUS if v["a1_in1"] >= (n.get("a1_in1") or 0) else MINUS))
    ss, sw = v["season"]["summer"], v["season"]["winter"]
    if ss and sw and abs(ss - sw) >= 0.03 and len(items) < 4:
        items.append(("夏(7〜9月)と冬(12〜2月)", f"夏 {pct(ss)}", f"冬 {pct(sw)}", "季節の差" + ("は小さい" if abs(ss - sw) < 0.03 else "あり"),
                      "#8a8f96" if abs(ss - sw) < 0.03 else (PLUS if sw > ss else MINUS)))
    rows = ""
    for title, a, b, note, col in items:
        nums = f'<span style="color:{MUTE}">{e(a)}</span> → <b style="color:{col}">{e(b)}</b>' if a else f'<b style="color:{col}">{e(b)}</b>'
        rows += (f'<div class="pan" style="border-color:{col}"><h2>{e(title)}</h2><div style="font:900 52px/1.25 {F}">{nums}</div>'
                 f'<div class="note" style="margin-top:6px">{e(note)}</div></div>')
    q = f"{e(event)}は、潮の時間もチェック。" if td and td.get("real") and event else ""
    return _page(f"{v['name']}の早見表 ②" + (f" ・ {event}" if event else ""), "インは、何で変わる?", f"{v['name']}の1コースの1着率", rows, "")


def venue_deme(d: dict, j: int, event: str = "") -> str:
    v = d["venues"][str(j)]
    dm = d["deme"]["venue"][str(j)]
    rows = ""
    for i, r in enumerate(dm["top"][:10]):
        c = [int(x) for x in r["combo"].split("-")]
        boxes = "".join(f'<span style="background:{LANE_BG[x - 1]};color:{LANE_FG[x - 1]}">{x}</span>' for x in c)
        diff = r["share"] - (r["national"] or 0)
        cmpw = "全国より多い" if diff > 0.003 else ("全国より少ない" if diff < -0.003 else "全国並み")
        rows += (f'<div class="dm"><span class="rk">{i + 1}</span><span class="cb">{boxes}</span><span class="sh">{pct(r["share"], 1)}</span>'
                 f'<span class="ev">{every(r["share"])} ・ {cmpw}</span></div>')
    stars = dm.get("stars") or []
    tail = (f"2着・3着の並びのクセで、最近の1年も続いたのは {'・'.join(s['combo'] for s in stars)}。" if stars
            else "インの強さを差し引くと、2着・3着の並びのクセは最近の1年で続いていなかった。")
    body = (f'<div class="note" style="margin-bottom:8px">3連単の結果の割合(買い目ではありません)</div>{rows}'
            f'<div style="font:900 36px/1.45 {F};margin-top:24px">{e(tail)}</div>')
    return _page(f"{v['name']}の早見表 ③" + (f" ・ {event}" if event else ""), f"{e(v['name'])}の出目", f"{v['races']:,}レース", body, "")


# ---------------------------------------------------------------- 級別×コース
def class_course(d: dict, key: str = "win") -> str:
    cc = d["class_course"]
    lab = "1着率" if key == "win" else "3着以内率"
    vmax = 0.75 if key == "win" else 0.95
    head = "".join(f'<th>{lane_box(c)}</th>' for c in range(1, 7))
    rows = ""
    for k in ("A1", "A2", "B1", "B2"):
        cells = ""
        for c in range(1, 7):
            x = cc[k][str(c)][key]
            a = min(1.0, x / vmax)
            bg = f"rgba(23,52,90,{0.08 + 0.85 * a:.2f})"
            fg = "#fff" if a > 0.45 else INK
            num = f"{x * 100:.1f}" if x < 0.01 else f"{round(x * 100)}"
            cells += f'<td style="background:{bg};color:{fg}">{num}<small>%</small></td>'
        rows += f'<tr><th class="k">{k}</th>{cells}</tr>'
    tbl = (f'<style>.cc{{border-collapse:separate;border-spacing:6px;width:100%;margin-top:6px}} .cc th{{font:900 36px {F};padding:6px 0}}'
           f'.cc th.k{{font:900 44px {F};width:100px}} .cc td{{text-align:center;font:900 52px {F};height:150px;border-radius:10px}} .cc td small{{font-size:30px}}'
           f'.cc .ln{{margin-left:0}}</style><table class="cc"><tr><th></th>{head}</tr>{rows}</table>')
    if key == "win":
        a1c3, b1c1 = cc["A1"]["3"]["win"], cc["B1"]["1"]["win"]
        note = f"A1の1コースは{pct(cc['A1']['1']['win'])}、B1の1コースは{pct(b1c1)}。同じインでも級別で{round((cc['A1']['1']['win'] - b1c1) * 100)}ポイント違う"
    else:
        note = f"A1なら6コースでも{pct(cc['A1']['6']['top3'])}が3着以内。B1の6コースは{pct(cc['B1']['6']['top3'])}"
    body = tbl + f'<div style="font:900 38px/1.45 {F};margin-top:22px">{e(note)}</div>'
    return _page(f"早見表 級別×コース", f"級別×コースの{lab}", "進入したコースごと(選手の級別はそのレースの時点)", body, "")


# ---------------------------------------------------------------- 出目
def deme_top(d: dict) -> str:
    dm = d["deme"]
    pr = (dm.get("popular_ratio") or {}).get("by_combo", {})
    rows = ""
    for i, r in enumerate(dm["top"][:11]):
        c = [int(x) for x in r["combo"].split("-")]
        boxes = "".join(f'<span style="background:{LANE_BG[x - 1]};color:{LANE_FG[x - 1]}">{x}</span>' for x in c)
        p = pr.get(r["combo"])
        tag = ""
        if p and p["ci"][0] > 1.0:
            tag = f'<span class="pp" style="background:{PLUS}">人気以上</span>'
        elif p and p["ci"][1] < 1.0:
            tag = f'<span class="pp" style="background:#8a8f96">ひかえめ</span>'
        rows += (f'<div class="dm" style="height:62px"><span class="rk">{i + 1}</span><span class="cb">{boxes}</span><span class="sh">{pct(r["share"], 1)}</span>'
                 f'<span class="ev">{every(r["share"])} {tag}</span></div>')
    nr = (dm.get("popular_ratio") or {}).get("races", 0)
    body = (f'<div class="note" style="margin-bottom:6px">3連単の結果の割合(買い目ではありません)</div>{rows}'
            f'<div class="note" style="margin-top:14px">人気以上=人気(オッズ)から考えるより多く来た出目({nr:,}レース)</div>')
    return _page("早見表 出目", "3連単の出目ランキング", f"全国 {dm['races']:,}レース", body, "")


def deme_cond(d: dict) -> str:
    dm = d["deme"]
    cond = dm["conditions"]
    rows = ""
    for k in ("1号艇A1", "1号艇A2", "1号艇B1", "1号艇B2", "風5m以上"):
        x = next((t for t in cond[k]["top"] if t["combo"] == "1-2-3"), None)
        if not x:
            continue
        w = min(1.0, x["share"] / 0.11) * 100
        rows += (f'<div class="row" style="height:80px"><span class="nm" style="width:240px">{e(k)}</span><span class="br"><i style="width:{w:.1f}%;background:{NAVY}"></i></span>'
                 f'<span class="v" style="width:150px">{pct(x["share"], 1)}</span></div>')
    stars = [(d["venues"][j]["name"], s["combo"]) for j, v in dm["venue"].items() for s in v.get("stars", [])]
    st = "・".join(f"{n}の{c}" for n, c in stars) or "なし"
    body = (f'<div class="pan" style="border-color:{NAVY}"><h2>1-2-3 が出る割合</h2><div class="nat">全国は{pct(dm["top"][0]["share"], 1)}</div>{rows}</div>'
            f'<div class="pan" style="border-color:#8a8f96"><h2>場ごとの「らしい出目」は?</h2>'
            f'<div style="font:700 36px/1.5 {F}">インの強さを差し引いて、前の2年で見つけたクセが最近の1年も続いたのは <b>{e(st)}</b> だけ。多くはインの強さで説明できる</div></div>')
    return _page("早見表 出目 ②", "出目は、条件で変わる", "", body, "")


def all_cards(d: dict, venue: int | None = None, event: str = "") -> dict[str, str]:
    """名前 → HTML。venue を渡すとその場の特化版も。"""
    global SRC
    p0, p1 = d["period"]
    SRC = f"公式の成績 {p0[:4]}/{int(p0[5:7])}〜{p1[:4]}/{int(p1[5:7])} 約{d['races'] / 10000:.1f}万レースを集計"
    out = {"cmp1_in": cmp_in1(d), "cmp2_kimarite": cmp_kimarite(d), "cmp3_are": cmp_are(d), "cmp4_wind": cmp_wind(d),
           "class_win": class_course(d, "win"), "class_top3": class_course(d, "top3"), "deme1_top": deme_top(d), "deme2_cond": deme_cond(d)}
    if venue:
        out.update({f"v{venue:02d}_1": venue_profile(d, venue, event), f"v{venue:02d}_2": venue_change(d, venue, event),
                    f"v{venue:02d}_3": venue_deme(d, venue, event)})
    return out


def render_all(cards: dict[str, str], outdir) -> list:
    """playwright で PNG に。スマホの実寸(幅375)の縮小版も *_phone.png に。"""
    import pathlib
    from playwright.sync_api import sync_playwright
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for name, h in cards.items():
            pg.set_content(h)
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(200)
            over = pg.evaluate("(() => { const c = document.querySelector('.c'); const q = document.querySelector('.q'); const ft = document.querySelector('.ft');"
                               " const bd = document.querySelector('.body'); const last = bd ? bd.getBoundingClientRect().bottom : 0;"
                               " const lim = (q ? q.getBoundingClientRect().top : ft.getBoundingClientRect().top) - 10; return Math.round(last - lim); })()")
            f = outdir / f"{name}.png"
            pg.screenshot(path=str(f), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
            paths.append((f, over))
        b.close()
    return paths
