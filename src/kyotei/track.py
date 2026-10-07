"""1マークの攻防を、水面の寸法と艇の速さから組み立てて描く(2026-10-07 ユーザー「実際の船の軌跡を忠実に再現していこう」)。

実際の航跡データ(GPS など)は公開されていないので、次の「物理の目安」から艇の動きを計算して描く:
- 長さはメートルで持つ。スタートライン(大時計の前)を x=0、1マークを x=MARK_X、y はスタンドから遠ざかる向き。
  1マークは直径約1m(公式の説明で幅約100cm)。1マークと2マークはおよそ300m(対角線上)。スタートから1マークまでの距離は場によって違うので目安。
- 艇は全長約3m。スタートの速さは約80km/h(22m/s)、ダッシュ勢(4〜6コース)は助走が長いぶん少し速い。
  STの差 0.1秒 = 約2.2m(艇の長さの3分の2ほど)。旋回中は速度が落ち、小回りほど落ちる。
- 回り方: 艇は1マークを左手に見ながら反時計回りに回る。小回りの艇はマークを1〜3mの間隔でかすめ、ふくらむ艇は大きな円を描く。
各艇の「スタートの速さ(ST)・旋回の中心と半径」をシナリオごとに決め、同じ時計で動かす。図には航跡と、同じ瞬間の6艇の位置(2つの時刻)を描く。
"""
from __future__ import annotations

import html
import math

LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"]
LANE_FG = ["#111111", "#ffffff", "#ffffff", "#ffffff", "#111111", "#ffffff"]
MARK_X = 110.0          # スタートラインから1マークまで(m、目安)
LANE_Y = [-5.0, -11.0, -17.0, -23.0, -29.0, -35.0]   # スリットでの各コースの位置(m、マークの線からスタンド側へ)
V_SLOW, V_DASH = 22.0, 23.5   # m/s(スロー勢・ダッシュ勢のスタート後の速さ)
BOAT_L, BOAT_W = 3.0, 1.4

# シナリオ: 各艇 (コース番号: ST, 旋回中心のx(マークからの差), 中心のy, 半径, 寄せ始め(マークの何m手前から内へ寄るか))
SCENES = {
    "nige": {"label": "1号艇が先にターンして、そのまま逃げる", "win": 1,
             "boats": {1: (0.11, 1.0, 5.0, 8.0, 40), 2: (0.15, -2.0, 7.5, 12.0, 40), 3: (0.15, -3.0, 10.0, 16.0, 40),
                       4: (0.15, -4.0, 12.0, 19.0, 40), 5: (0.17, -5.0, 14.0, 22.0, 40), 6: (0.18, -6.0, 16.0, 25.0, 40)}},
    "sashi": {"label": "1号艇がふくらんだ内側を、2号艇が差す", "win": 2,
              "boats": {1: (0.15, 4.0, 9.0, 13.0, 40), 2: (0.13, -3.0, 4.5, 7.0, 55), 3: (0.15, 1.0, 13.0, 17.0, 40),
                        4: (0.16, 0.0, 14.0, 20.0, 40), 5: (0.17, -2.0, 16.0, 23.0, 40), 6: (0.18, -4.0, 18.0, 26.0, 40)}},
    # まくり: 4号艇は全速のまま回り(6つ目の値=旋回の速さ m/s)、上から被せられた1〜3号艇は引き波で速度が落ちる
    "makuri": {"label": "4号艇がスタートで前に出て、内の3艇の上をまとめて回る", "win": 4,
               "boats": {1: (0.17, 1.0, 5.0, 8.0, 40, 10.5), 2: (0.17, -1.0, 7.5, 11.0, 40, 11.0), 3: (0.18, -1.0, 10.5, 14.0, 40, 12.0),
                         4: (0.06, 4.0, 10.0, 16.0, 75, 22.0), 5: (0.14, 0.0, 15.0, 22.0, 45, 18.0), 6: (0.17, -3.0, 18.0, 26.0, 40)}},
    # まくり差し: 2号艇は外へ大きく回って失速、3号艇は1号艇と2号艇の間を速さを保ったまま抜ける
    "mz": {"label": "2号艇がまくりに行き、1号艇との間のすき間を3号艇が突く", "win": 3,
           "boats": {1: (0.15, 1.0, 5.0, 8.0, 40, 11.0), 2: (0.12, 5.0, 11.0, 17.0, 55, 14.0), 3: (0.11, -0.5, 6.5, 11.0, 50, 19.0),
                     4: (0.15, 2.0, 15.0, 21.0, 40), 5: (0.17, 0.0, 17.0, 24.0, 40), 6: (0.18, -3.0, 19.0, 27.0, 40)}},
}


def _cubic(p0, p1, p2, p3, n=24):
    out = []
    for k in range(1, n + 1):
        s = k / n
        out.append(tuple((1 - s) ** 3 * a + 3 * (1 - s) ** 2 * s * b + 3 * (1 - s) * s ** 2 * c + s ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


def boat_path(lane: int, dx: float, cy: float, r: float, lead: float, x_start: float = -18.0, back: float = 75.0):
    """1艇の航跡: スリットの位置から直進 → 内へ寄せながらマークへ → 中心(cx,cy)・半径rで反時計回りに半周 → 2マークの方へ直進。
    点の並びと、各点が「旋回中か」を返す。"""
    cx = MARK_X + dx
    y0 = LANE_Y[lane - 1]
    xa = max(cx - lead, 6.0)   # 寄せ始め(スタートラインより後ろ)
    pts = [(x_start, y0), (xa, y0)]
    turn = [False, False]
    seg = _cubic((xa, y0), (xa + (cx - xa) * 0.45, y0), (cx - (cx - xa) * 0.45, cy - r), (cx, cy - r))
    pts += seg
    turn += [False] * len(seg)
    for k in range(1, 37):   # 半周(-90°→+90°)
        a = -math.pi / 2 + math.pi * k / 36
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        turn.append(True)
    xe = cx - back
    for k in range(1, 9):
        pts.append((cx + (xe - cx) * k / 8, cy + r))
        turn.append(False)
    return pts, turn


def timeline(pts, turn, st: float, v: float, r: float, v_turn: float | None = None):
    """各点の時刻(スタートの合図=0)。スタートラインを ST 秒で横切る。旋回中は小回りほど遅い(v_turn で上書きできる)。"""
    v_turn = v_turn or max(11.0, 9.0 + 0.55 * r)
    ts = [0.0]
    for (x0, y0), (x1, y1), tr in zip(pts, pts[1:], turn[1:]):
        ts.append(ts[-1] + math.hypot(x1 - x0, y1 - y0) / (v_turn if tr else v))
    # スタートライン(x=0)を通る時刻を st にそろえる
    t0 = next(t + (0 - x0) / max(x1 - x0, 1e-6) * (t1 - t) for (x0, _), (x1, _), t, t1 in zip(pts, pts[1:], ts, ts[1:]) if x0 <= 0 <= x1)
    return [t - t0 + st for t in ts]


def at_time(pts, ts, t):
    """時刻 t の位置と向き(ラジアン)。"""
    if t <= ts[0]:
        i = 0
    elif t >= ts[-1]:
        i = len(ts) - 2
    else:
        i = next(k for k in range(len(ts) - 1) if ts[k] <= t <= ts[k + 1])
    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    w = 0.0 if ts[i + 1] == ts[i] else min(max((t - ts[i]) / (ts[i + 1] - ts[i]), 0), 1)
    return (x0 + (x1 - x0) * w, y0 + (y1 - y0) * w), math.atan2(y1 - y0, x1 - x0)


def scene(cat: str) -> str:
    sc = SCENES.get(cat)
    if not sc:
        return ""
    # 画面: x は -22〜MARK_X+34 m、y は -42〜+50 m(上がスタンドの反対側)
    X0, X1, Y0, Y1 = -22.0, MARK_X + 34.0, -42.0, 50.0
    W = 300.0
    s = W / (X1 - X0)
    H = (Y1 - Y0) * s + 14
    px = lambda x: (x - X0) * s  # noqa: E731
    py = lambda y: (Y1 - y) * s  # noqa: E731
    paths, clocks = {}, {}
    for lane, spec in sc["boats"].items():
        st, dx, cy, r, lead = spec[:5]
        pts, tr = boat_path(lane, dx, cy, r, lead)
        ts = timeline(pts, tr, st, V_DASH if lane >= 4 else V_SLOW, r, spec[5] if len(spec) > 5 else None)
        paths[lane], clocks[lane] = pts, ts
    win = sc["win"]
    # 時刻: (a) 勝つ艇がマークの25m手前、(b) 勝つ艇が半周を終えるころ
    wp, wt = paths[win], clocks[win]
    ta = next(t for (x, _), t in zip(wp, wt) if x >= MARK_X - 25)
    tb = next(t for (x, y), t in zip(wp, wt) if y > SCENES[cat]["boats"][win][2] and x < MARK_X + SCENES[cat]["boats"][win][1] - 12)

    out = [f'<rect x="0" y="0" width="{W:.0f}" height="{H:.1f}" fill="#d9e9f2"/>']
    # 2マークの方角とスタートライン(大時計)
    out.append(f'<path d="M{px(0):.1f} {py(Y1) + 4:.1f}V{py(Y0) - 2:.1f}" stroke="#e60012" stroke-width="1.2" stroke-dasharray="3 3"/>')
    out.append(f'<text x="{px(0) + 3:.1f}" y="{py(Y1) + 11:.1f}" font-size="8" font-weight="700" fill="#e60012">スタートライン</text>')
    out.append(f'<text x="{px(X0) + 3:.1f}" y="{py(26):.1f}" font-size="7.5" fill="#46606e">← 2マークへ</text>')
    # 航跡(負けた艇は細く、勝った艇は太く)
    order = [l for l in sorted(paths) if l != win] + [win]
    for lane in order:
        d = "M" + " L".join(f"{px(x):.1f} {py(y):.1f}" for x, y in paths[lane])
        bold = lane == win
        op = "1" if bold else ".55"
        out.append(f'<path d="{d}" fill="none" stroke="#111" stroke-opacity="{op}" stroke-width="{6.5 if bold else 3.4}" stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="{LANE_BG[lane - 1]}" stroke-opacity="{op}" stroke-width="{4 if bold else 1.8}" stroke-linejoin="round" stroke-linecap="round"/>')
    # 1マーク(直径約1mだが、見えるように少し大きく)
    mx, my = px(MARK_X), py(0)
    out.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="3.6" fill="#ffe100" stroke="#111" stroke-width="1.6"/><path d="M{mx - 3.2:.1f} {my:.1f}h6.4" stroke="#e60012" stroke-width="1.6"/>')
    out.append(f'<text x="{mx - 7:.1f}" y="{my + 3:.1f}" font-size="8" font-weight="700" fill="#111" text-anchor="end" stroke="#d9e9f2" stroke-width="2.6" paint-order="stroke">1マーク</text>')

    def boat(lane, t, ghost=False):
        (x, y), h = at_time(paths[lane], clocks[lane], t)
        cxp, cyp = px(x), py(y)
        L, Wd = BOAT_L * s * 1.9, BOAT_W * s * 2.2   # 見えるように少し大きく
        deg = -math.degrees(h)
        op = ".35" if ghost else "1"
        poly = f"{-L / 2:.1f},{-Wd / 2:.1f} {L / 4:.1f},{-Wd / 2:.1f} {L / 2:.1f},0 {L / 4:.1f},{Wd / 2:.1f} {-L / 2:.1f},{Wd / 2:.1f}"
        g = (f'<g transform="translate({cxp:.1f} {cyp:.1f}) rotate({deg:.1f})" opacity="{op}"><polygon points="{poly}" fill="{LANE_BG[lane - 1]}" stroke="#111" stroke-width="1"/></g>')
        if not ghost:
            g += f'<text x="{cxp:.1f}" y="{cyp + 2.6:.1f}" font-size="6.5" font-weight="700" fill="{LANE_FG[lane - 1]}" text-anchor="middle">{lane}</text>'
        return g
    for lane in order:
        out.append(boat(lane, ta, ghost=True))
    for lane in order:
        out.append(boat(lane, tb))
    # スタンド
    out.append(f'<rect x="0" y="{H - 12:.1f}" width="{W:.0f}" height="12" fill="#111"/>'
               f'<text x="{W / 2:.0f}" y="{H - 3.2:.1f}" font-size="8.5" font-weight="700" fill="#fff" text-anchor="middle">スタンド(観客席)</text>')
    label = sc["label"]
    sts = "・".join(f"{l}号艇 .{round(sc['boats'][l][0] * 100):02d}" for l in sorted(sc["boats"]))
    return (f'<figure class="dg"><svg viewBox="0 0 {W:.0f} {H:.1f}" role="img" aria-label="{html.escape(label)}">{"".join(out)}</svg>'
            f'<figcaption>{html.escape(label)}。薄い艇はマークの手前、濃い艇はターンを終えるころの、同じ瞬間の6艇。'
            f'<small>艇の速さ(約80km/h)とスタートの差(この図のST: {sts})から組み立てた再現図</small></figcaption></figure>')
