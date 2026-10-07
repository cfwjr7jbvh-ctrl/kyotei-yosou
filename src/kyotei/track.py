"""1マークの攻防を、水面の寸法と艇の速さから組み立てて描く(2026-10-07 ユーザー「実際の船の軌跡を忠実に再現していこう」)。

実際の航跡データ(GPS など)は公開されていないので、次の「物理の目安」から艇の動きを計算して描く:
- 長さはメートルで持つ。スタートライン(大時計の前)を x=0、1マークを x=MARK_X、y はスタンドから遠ざかる向き。
  1マークは直径約1m(公式の説明で幅約100cm)。1マークと2マークはおよそ300m(対角線上)。スタートから1マークまでの距離は場によって違うので目安。
- 艇は全長約3m。スタートの速さは約80km/h(22m/s)、ダッシュ勢(4〜6コース)は助走が長いぶん少し速い。
  STの差 0.1秒 = 約2.2m(艇の長さの3分の2ほど)。旋回中は速度が落ち、小回りほど落ちる。
- 回り方: 艇は1マークを左手に見ながら反時計回りに回る。小回りの艇はマークを1〜3mの間隔でかすめ、ふくらむ艇は大きな円を描く。
- ターンは1マークの手前から始め、ターンのいちばん外へ張り出すところ(頂点)でマークをかすめる(先マイ)。マークとの間隔(gap)が小さいほど小回り。
- まくった艇の後ろには引き波が立ち、被せられた内の艇は引き波に乗って失速する(旋回の速さを落として表す)。
各艇の「ST・旋回の半径・マークとの間隔・旋回の速さ」をシナリオごとに決め、同じ時計で動かす。
図には航跡と、同じ瞬間の6艇の位置を3つの時刻(スタート・マークの手前・ターンを終えるころ)で描く。
参考にした描き方: 公式・解説サイトの決まり手の図解(上から見た1マークと矢印)、展開予想ボード(スリットの隊形→1マークの位置取り)、
新聞のスリット隊形図(ST順の凹凸)。それらに「同じ瞬間の6艇」と「引き波」を足して、動きのつながりが見えるようにした。
"""
from __future__ import annotations

import html
import math

LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
LANE_FG = ["#111111", "#ffffff", "#ffffff", "#ffffff", "#111111", "#ffffff"]
MARK_X = 110.0          # スタートラインから1マークまで(m、目安。場によって違う)
LANE_Y = [-7.0, -13.0, -19.0, -25.0, -31.0, -37.0]   # スリットでの各コースの位置(m、マークの線からスタンド側へ)
V_SLOW, V_DASH = 22.0, 23.5   # m/s(スロー勢・ダッシュ勢のスタート後の速さ。約80km/h)
BOAT_L, BOAT_W = 3.0, 1.4


def B(st, r, gap, cy=0.0, lead=40.0, vt=None):
    """1艇の設定。st=ST(秒)、r=旋回半径(m)、gap=頂点でのマークとの間隔(m)、cy=旋回中心の上下のずれ、lead=マークの何m手前から内へ寄るか、vt=旋回の速さ(m/s)。"""
    return {"st": st, "r": r, "gap": gap, "cy": cy, "lead": lead, "vt": vt}


SCENES = {
    "nige": {"label": "1号艇が先にターンして、そのまま逃げる", "win": 1, "key": [1, 2],
             "boats": {1: B(0.11, 8, 1.5), 2: B(0.15, 11, 4.5, 1), 3: B(0.15, 14, 7.5, 2), 4: B(0.15, 17, 10, 3),
                       5: B(0.17, 20, 12.5, 4), 6: B(0.18, 23, 15, 5)}},
    "sashi": {"label": "1号艇がふくらんだ内側を、2号艇が差す", "win": 2, "key": [1, 2],
              "boats": {1: B(0.15, 12, 9, 3), 2: B(0.13, 7, 1.5, -2, 55), 3: B(0.15, 15, 12, 5), 4: B(0.16, 18, 14, 6),
                        5: B(0.17, 21, 16, 7), 6: B(0.18, 24, 18, 8)}},
    # まくり: 4号艇はスタートで前に出て全速のまま外を回る。被せられた1〜3号艇は引き波で失速
    "makuri": {"label": "4号艇がスタートで前に出て、内の3艇の上をまとめて回る", "win": 4, "key": [1, 4],
               "boats": {1: B(0.17, 8, 1.5, 0, 40, 10.0), 2: B(0.17, 10, 4.5, 1, 40, 10.5), 3: B(0.18, 12, 7, 2, 40, 11.0),
                         4: B(0.06, 15, 11, 0, 80, 22.0), 5: B(0.14, 19, 15, 2, 45, 18.0), 6: B(0.17, 23, 18, 4)}},
    # まくり差し: 2号艇がまくりに行って外へ流れる。3号艇は1号艇と2号艇の間を、速さを保ったまま抜ける
    "mz": {"label": "2号艇がまくりに行き、1号艇との間のすき間を3号艇が突く", "win": 3, "key": [1, 2, 3],
           "boats": {1: B(0.15, 8, 1.5, 0, 40, 11.0), 2: B(0.12, 15, 12, 2, 55, 14.0), 3: B(0.11, 10, 5, 0, 55, 19.0),
                     4: B(0.15, 18, 15, 3), 5: B(0.17, 21, 17, 4), 6: B(0.18, 24, 19, 5)}},
}


def _cubic(p0, p1, p2, p3, n=24):
    out = []
    for k in range(1, n + 1):
        u = k / n
        out.append(tuple((1 - u) ** 3 * a + 3 * (1 - u) ** 2 * u * b + 3 * (1 - u) * u ** 2 * c + u ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


def boat_path(lane: int, b: dict, x_start: float = -18.0, back: float = 80.0):
    """1艇の航跡: スリットの位置から直進 → 内へ寄せながら旋回の入口へ → 反時計回りに半周(頂点でマークをかすめる)→ 2マークの方へ直進。"""
    r = b["r"]
    cx, cy = MARK_X + b["gap"] - r, b["cy"]
    y0 = LANE_Y[lane - 1]
    xa = max(cx - b["lead"], 6.0)
    pts, turn = [(x_start, y0), (xa, y0)], [False, False]
    seg = _cubic((xa, y0), (xa + (cx - xa) * 0.45, y0), (cx - (cx - xa) * 0.45, cy - r), (cx, cy - r))
    pts += seg
    turn += [False] * len(seg)
    for k in range(1, 37):
        a = -math.pi / 2 + math.pi * k / 36
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        turn.append(True)
    xe = cx - back
    for k in range(1, 9):
        pts.append((cx + (xe - cx) * k / 8, cy + r))
        turn.append(False)
    return pts, turn


def timeline(pts, turn, st: float, v: float, r: float, v_turn: float | None = None):
    """各点の時刻(スタートの合図=0秒)。スタートラインを ST 秒で横切る。旋回中は小回りほど遅い(v_turn で上書き)。"""
    v_turn = v_turn or max(11.0, 9.0 + 0.55 * r)
    ts = [0.0]
    for (x0, y0), (x1, y1), tr in zip(pts, pts[1:], turn[1:]):
        ts.append(ts[-1] + math.hypot(x1 - x0, y1 - y0) / (v_turn if tr else v))
    t0 = next(t + (0 - x0) / max(x1 - x0, 1e-6) * (t1 - t) for (x0, _), (x1, _), t, t1 in zip(pts, pts[1:], ts, ts[1:]) if x0 <= 0 <= x1)
    return [t - t0 + st for t in ts]


def at_time(pts, ts, t):
    """時刻 t の位置と向き(ラジアン)。最初の点より前は、同じ速さでさかのぼる。"""
    if t <= ts[0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
        v = math.hypot(x1 - x0, y1 - y0) / max(ts[1] - ts[0], 1e-6)
        return (x0 - v * (ts[0] - t), y0), 0.0
    i = len(ts) - 2 if t >= ts[-1] else next(k for k in range(len(ts) - 1) if ts[k] <= t <= ts[k + 1])
    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    w = 0.0 if ts[i + 1] == ts[i] else min(max((t - ts[i]) / (ts[i + 1] - ts[i]), 0), 1)
    return (x0 + (x1 - x0) * w, y0 + (y1 - y0) * w), math.atan2(y1 - y0, x1 - x0)


def simulate(cat: str):
    sc = SCENES[cat]
    paths, clocks = {}, {}
    for lane, b in sc["boats"].items():
        pts, tr = boat_path(lane, b)
        paths[lane], clocks[lane] = pts, timeline(pts, tr, b["st"], V_DASH if lane >= 4 else V_SLOW, b["r"], b["vt"])
    win = sc["win"]
    wb = sc["boats"][win]
    wp, wt = paths[win], clocks[win]
    cxw = MARK_X + wb["gap"] - wb["r"]
    ta = next(t for (x, _), t in zip(wp, wt) if x >= MARK_X - 28)                       # マークの手前
    tb = next(t for (x, y), t in zip(wp, wt) if y > wb["cy"] and x < cxw - 14)        # ターンを終えて立ち上がるころ
    return paths, clocks, ta, tb


def scene(cat: str) -> str:
    sc = SCENES.get(cat)
    if not sc:
        return ""
    paths, clocks, ta, tb = simulate(cat)
    win = sc["win"]
    X0, X1, Y0, Y1 = -22.0, MARK_X + 30.0, -44.0, 34.0
    W = 300.0
    s = W / (X1 - X0)
    H = (Y1 - Y0) * s + 14
    px = lambda x: (x - X0) * s  # noqa: E731
    py = lambda y: (Y1 - y) * s  # noqa: E731
    out = [f'<rect x="0" y="0" width="{W:.0f}" height="{H:.1f}" fill="#d9e9f2"/>']
    # スタートラインと大時計、2マークの方角、縮尺
    out.append(f'<path d="M{px(0):.1f} {py(Y1) + 10:.1f}V{py(Y0) - 1:.1f}" stroke="#e60012" stroke-width="1.1" stroke-dasharray="3 3"/>')
    out.append(f'<circle cx="{px(0):.1f}" cy="{py(Y1) + 6:.1f}" r="4.2" fill="#fff" stroke="#111" stroke-width="1"/>'
               f'<path d="M{px(0):.1f} {py(Y1) + 6:.1f}V{py(Y1) + 2.8:.1f}" stroke="#e60012" stroke-width="1"/>'
               f'<text x="{px(0) + 6:.1f}" y="{py(Y1) + 8.6:.1f}" font-size="7.5" font-weight="700" fill="#e60012">大時計・スタートライン</text>')
    out.append(f'<text x="{px(X0) + 3:.1f}" y="{py(20):.1f}" font-size="7" fill="#46606e">← 2マークへ</text>')
    sb = px(X0) + 4
    out.append(f'<path d="M{sb:.1f} {py(Y0) - 4:.1f}h{10 * s:.1f}" stroke="#46606e" stroke-width="1.4"/>'
               f'<text x="{sb + 10 * s + 3:.1f}" y="{py(Y0) - 2:.1f}" font-size="6.5" fill="#46606e">10m</text>')
    order = [l for l in sorted(paths) if l != win] + [win]
    key = set(sc.get("key", [win]))
    for lane in order:
        d = "M" + " L".join(f"{px(x):.1f} {py(y):.1f}" for x, y in paths[lane])
        if lane == win:      # 主役: 太く
            out.append(f'<path d="{d}" fill="none" stroke="#111" stroke-width="6.4" stroke-linejoin="round" stroke-linecap="round"/>')
            out.append(f'<path d="{d}" fill="none" stroke="{LANE_BG[lane - 1]}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
        elif lane in key:    # 相手: ふつう
            out.append(f'<path d="{d}" fill="none" stroke="#111" stroke-opacity=".75" stroke-width="3.6" stroke-linejoin="round" stroke-linecap="round"/>')
            out.append(f'<path d="{d}" fill="none" stroke="{LANE_BG[lane - 1]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="5 3"/>')
        else:                # ほか: 細く薄く
            out.append(f'<path d="{d}" fill="none" stroke="{LANE_BG[lane - 1] if lane != 1 else "#888"}" stroke-opacity=".3" stroke-width="1.1" stroke-linejoin="round"/>')
    mx, my = px(MARK_X), py(0)
    out.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="3.4" fill="#ffe100" stroke="#111" stroke-width="1.5"/><path d="M{mx - 3:.1f} {my:.1f}h6" stroke="#e60012" stroke-width="1.5"/>')
    out.append(f'<text x="{mx - 6:.1f}" y="{my + 2.8:.1f}" font-size="7.5" font-weight="700" fill="#111" text-anchor="end" stroke="#d9e9f2" stroke-width="2.6" paint-order="stroke">1マーク</text>')

    def boat(lane, t, op=1.0, wake=False, num=True):
        (x, y), h = at_time(paths[lane], clocks[lane], t)
        cxp, cyp = px(x), py(y)
        L, Wd = BOAT_L * s * 2.3, BOAT_W * s * 2.6
        deg = -math.degrees(h)
        g = ""
        if wake:   # 引き波: 艇の後ろに開くV字
            for sgn in (1, -1):
                a = h + math.pi + sgn * 0.42
                ex, ey = x + 9 * math.cos(a), y + 9 * math.sin(a)
                g += f'<path d="M{cxp:.1f} {cyp:.1f}L{px(ex):.1f} {py(ey):.1f}" stroke="#ffffff" stroke-width="1.6" stroke-opacity=".85" stroke-linecap="round"/>'
        poly = f"{-L / 2:.1f},{-Wd / 2:.1f} {L / 4:.1f},{-Wd / 2:.1f} {L / 2:.1f},0 {L / 4:.1f},{Wd / 2:.1f} {-L / 2:.1f},{Wd / 2:.1f}"
        g += f'<g transform="translate({cxp:.1f} {cyp:.1f}) rotate({deg:.1f})" opacity="{op}"><polygon points="{poly}" fill="{LANE_BG[lane - 1]}" stroke="#111" stroke-width="1"/></g>'
        if num:
            g += f'<text x="{cxp:.1f}" y="{cyp + 2.7:.1f}" font-size="7.2" font-weight="700" fill="{LANE_FG[lane - 1]}" text-anchor="middle" opacity="{op}">{lane}</text>'
        return g
    for lane in order:      # スタートの瞬間(0秒): STの差がそのまま並びの凹凸になる
        out.append(boat(lane, 0.0, .45, num=False))
    for lane in order:      # ターンを終えるころ(主役には引き波)。主役と相手は濃く、ほかは少し薄く
        out.append(boat(lane, tb, 1.0 if lane in key or lane == win else .6, wake=(lane == win)))
    out.append(f'<rect x="0" y="{H - 12:.1f}" width="{W:.0f}" height="12" fill="#111"/>'
               f'<text x="{W / 2:.0f}" y="{H - 3.2:.1f}" font-size="8.5" font-weight="700" fill="#fff" text-anchor="middle">スタンド(観客席)</text>')
    label = sc["label"]
    sts = "・".join(f"{l}号艇 .{round(sc['boats'][l]['st'] * 100):02d}" for l in sorted(sc["boats"]))
    return (f'<figure class="dg"><svg viewBox="0 0 {W:.0f} {H:.1f}" role="img" aria-label="{html.escape(label)}">{"".join(out)}</svg>'
            f'<figcaption>{html.escape(label)}。<small>薄い艇=スタートの瞬間、濃い艇=ターンを終えるころ(白いV字は引き波)。'
            f'艇の速さ(約80km/h)とST({sts})から組み立てた再現図</small></figcaption></figure>')
