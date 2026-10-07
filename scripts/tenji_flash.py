"""展示速報: 展示が出たら、すぐ X に出す(2026-10-07 ユーザー「展示がでたあとに高速で記事を出すことできるかな?」「今日からやろう」)。

対象: その日の「今日のX投稿」に入っているミカタ新聞のレース + SG・G1 の準優・優勝戦。
動き: live.yml の中で直前予想のループと並べて動かす(--watch)。対象レースの締切25分前から1分ごとに公式の直前情報を見て、
      展示タイムが5艇以上そろったら、本文と画像(大きな文字のカード)を作って X に出す。締切3分前を過ぎたら出さない。
      出したレースは $TENJI_DIR/tenji_YYYYMMDD.txt に残し(live ブランチにも置かれる)、二重に出さない。
      直前予想のループと同じ作業フォルダの git には触らない(ぶつからないよう、データは GitHub の API で読む)。
中身: 展示タイムの順位(検証ラボで本物: 展示1位の3着以内は ふだん51%→63%)、展示の進入、展示を入れた見立て(出ていれば)。
      展示STは使わない(検証ラボ exst で「本番とほぼ関係ない」)。買い目・的中・回収率は出さない。

  python scripts/tenji_flash.py --watch                 # 本番(live.yml の中)
  python scripts/tenji_flash.py --demo                  # 手元で文面と画像を作って確かめる(投稿しない)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from kyotei.xtext import xlen  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
REPO = "cfwjr7jbvh-ctrl/kyotei-yosou"
STATE_DIR = pathlib.Path(os.environ.get("TENJI_DIR") or (pathlib.Path(tempfile.gettempdir()) / "tenji"))
WATCH_FROM, STOP_BEFORE = 25, 3   # 締切の何分前から見に行くか / 何分前を過ぎたら出さないか
WEEK = "月火水木金土日"


def now() -> dt.datetime:
    return dt.datetime.now(JST)


def log(*a):
    print(now().strftime("[tenji %H:%M:%S]"), *a, flush=True)


# ---------------------------------------------------------------- 読み込み(git に触らず、GitHub の API で)
def gh_raw(path: str, ref: str) -> str | None:
    try:
        r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/{path}?ref={ref}"],
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 and r.stdout.strip() else None
    except Exception:  # noqa: BLE001
        return None


def use_workspace_salt():
    """暗号のソルトは本体の作業フォルダ(GITHUB_WORKSPACE)のものを使う。見張りは写しのフォルダで動くので、
    そのままだと写しに無いソルトを新しく作ってしまい、鍵が合わない(InvalidTag)。2026-10-07 初日に起きた"""
    from kyotei import publish
    s_ = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or ROOT) / "docs/data/salt.txt"
    if s_.exists():
        publish.SALT_PATH = s_


def gh_json(path: str, ref: str):
    raw = gh_raw(path, ref)
    if not raw:
        return None
    use_workspace_salt()
    from kyotei.publish import read_json
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(raw)
    try:
        return read_json(pathlib.Path(f.name))
    except Exception as ex:  # noqa: BLE001
        log("読めませんでした:", path, type(ex).__name__)
        return None
    finally:
        os.unlink(f.name)


def today_races(day: dt.date) -> list[dict]:
    d = gh_json(f"days/{day.isoformat()}.json", "live") or gh_json(f"docs/data/days/{day.isoformat()}.json", "main")
    return (d or {}).get("races", [])


MIN_DEMAND = 1.0     # 3連単の売上の見込み(億円)。★★以上=見る人・買う人が多そうなレース
MAX_PER_DAY = 8      # 1日に出す上限(出しすぎない)


def targets(day: dt.date, races: list[dict]) -> list[dict]:
    """見る人が多そうなレース: ミカタ新聞のレース(今日のX投稿の「新聞:」)、SG・G1 の準優・優勝戦、売上の見込みが1億円以上のレース。
    このうち「狙い目かも?」が出たレースだけを出す(2026-10-07 ユーザー「狙い目が出たかつ、購読者が多そうなレースだけやろう」)。"""
    from kyotei import demand
    ws = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or ROOT) / "reports/demand_model.json"
    if ws.exists():
        demand.MODEL = ws
    q = gh_json(f"ura/xpost_{day:%Y%m%d}.json", "cards") or {}
    want = set()
    for it in q.get("queue") or []:
        m = re.match(r"新聞:\s*(\D+?)(\d+)R", str(it.get("label", "")))
        if m:
            want.add((m.group(1), int(m.group(2))))
    ser = {s_.get("jcd"): s_ for s_ in q.get("series_today") or []}
    big = {j for j, s_ in ser.items() if s_.get("grade") in ("SG", "G1")}
    a1s = {j: demand.day_a1(races, j) for j in {r.get("jcd") for r in races}}
    out = []
    for r in races:
        if not r.get("deadline"):
            continue
        rt = str(r.get("race_type") or "")
        sc = demand.score((ser.get(r.get("jcd")) or {}).get("grade"), rt, r.get("rno"), day, r["deadline"], r.get("jcd"), a1s.get(r.get("jcd")))
        if (r.get("venue"), r.get("rno")) in want or (r.get("jcd") in big and "優勝戦" in rt) or sc >= MIN_DEMAND:
            out.append({**r, "_demand": sc})
    return out


def lab_fact() -> tuple[str, str, str]:
    """検証ラボ「展示タイム番長は本物か」の数字(展示1位の艇が3着以内に入る ふだん → 展示1位)。読めなければ記事どおりの値。"""
    a, b = 0.507, 0.626
    try:
        from kyotei.publish import load_private
        use_workspace_salt()
        t = load_private(ROOT / "reports/lab/tenji.json") or {}
        m = next(m for n, m, _ in t.get("measures") or [] if n == "展示タイム1位")
        a, b = float(m["in1_ref"]), float(m["in1"])
    except Exception:  # noqa: BLE001
        pass
    return "展示1位の艇が3着以内に入る", f"{round(a * 100)}%", f"{round(b * 100)}%"


# ---------------------------------------------------------------- 中身
def course_line(info: dict) -> str:
    bx = info.get("boats") or {}
    cs = {int(l): int(b["ex_course"]) for l, b in bx.items() if b.get("ex_course") and b.get("ex_course") == b.get("ex_course")}
    if len(cs) < 6:
        return ""
    if all(c == l for l, c in cs.items()):
        return "進入は枠なり(展示)"
    order = "-".join(str(l) for l, _ in sorted(cs.items(), key=lambda x: x[1]))
    inward = [l for l, c in sorted(cs.items()) if c < l]
    return f"展示の進入は {order}" + (f"({'・'.join(f'{l}号艇' for l in inward[:2])}が内へ)" if inward else "")


def usual_exrank(day: dt.date) -> dict[int, tuple[float, int]]:
    """選手ごとの「ふだんの展示順位」(前の日までの180日、レース内の展示タイムの順位の平均, 回数)。10回以上の選手だけ。
    2026-10-07 ユーザー「展示が結果に響く選手かどうかも関係する?」→ 検証ラボ(tenji): 効くのは今日の順位が本人のふだんとどれだけ違うか。"""
    import glob
    import pandas as pd
    base = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or ROOT) / "data/history"
    since = day - dt.timedelta(days=180)
    months = {(since + dt.timedelta(days=30 * i)).strftime("%Y%m") for i in range(8)} | {day.strftime("%Y%m")}
    fs = [f for f in sorted(glob.glob(str(base / "entries_*.csv.gz"))) if f[-13:-7] in months]
    if not fs:
        return {}
    e = pd.concat([pd.read_csv(f, usecols=["race_id", "date", "racer_id", "exhibit_time"]) for f in fs])
    e["date"] = pd.to_datetime(e["date"]).dt.date
    e = e[(e["date"] >= since) & (e["date"] < day) & e["exhibit_time"].notna()]
    e["r"] = e.groupby("race_id")["exhibit_time"].rank(method="min")
    g = e.groupby("racer_id")["r"].agg(["mean", "size"])
    g = g[g["size"] >= 10]
    return {int(i): (float(m), int(n)) for i, (m, n) in g.iterrows()}


def racer_tags(rid: int) -> list[str]:
    """選手カードの型(よい面だけのタグ)。"""
    try:
        b = gh_json(f"cards/b{rid % 50:02d}.json", "cards") or {}
        return [t.get("t") for t in ((b.get("cards") or {}).get(str(rid)) or {}).get("tags", [])]
    except Exception:  # noqa: BLE001
        return []


def lab_dev() -> tuple[str, str, str]:
    """検証ラボ tenji: 展示の順位が本人のふだんより2つ以上上 / 下 の3着以内(ふだん, 上, 下)。"""
    a, up, dn = 0.512, 0.603, 0.399
    try:
        from kyotei.publish import load_private
        use_workspace_salt()
        t = load_private(ROOT / "reports/lab/tenji.json") or {}
        ms = {n: m for n, m, _ in t.get("measures") or []}
        up = float(ms["展示の順位が、本人のふだんより2つ以上上"]["in1"])
        dn = float(ms["本人のふだんより2つ以上下"]["in1"])
        a = float(ms["展示の順位が、本人のふだんより2つ以上上"]["in1_ref"])
    except Exception:  # noqa: BLE001
        pass
    return f"{round(a * 100)}%", f"{round(up * 100)}%", f"{round(dn * 100)}%"


def late_ready(race: dict | None) -> bool:
    """直前予想に展示が入ったか(展示タイムが5艇以上入った直前予想)。"""
    boats = (race or {}).get("boats") or []
    return bool(race) and race.get("stage") == "late" and sum(1 for b in boats if b.get("exhibit_time")) >= 5


def market_win(odds: dict[str, float]) -> dict[int, float]:
    """3連単のオッズ(締切前)から、人気から考えた各艇の1着の確率(払い戻しの割合は差し引いてならす)。"""
    import numpy as np
    from kyotei.betting import COMBOS, market_probs
    if len(odds) < 100:
        return {}
    o = np.array([odds.get(c, np.nan) for c in COMBOS], dtype=float)
    pk = market_probs(o)
    return {l: float(sum(p for c, p in zip(COMBOS, pk) if c[0] == str(l))) for l in range(1, 7)}


def _chg(a: float | None, b: float | None) -> str:
    """「52%→58%に上がる」。朝の見立てが無ければ「58%」。"""
    pc = lambda v: f"{round(v * 100)}%"  # noqa: E731
    if a is None:
        return pc(b)
    if round(a * 100) == round(b * 100):
        return f"{pc(b)}(朝とほぼ同じ)"
    return f"{pc(a)}→{pc(b)}に{'上がる' if b > a else '下がる'}"


def gen_line(nl: int, rank: dict, dev: dict, r1: int | None) -> str:
    """ゲンさん(ストップウォッチ片手に展示を見る大先輩)のひと言。画像の中だけ(X の決まり: ゲンさんのセリフは画像の中)。
    事実(展示順位・ふだんとの差)に合わせた定型で、約束や断定はしない。選手をけなさない。"""
    if dev.get(nl, 0) >= 2:
        return "ふだんより展示が来てる。こういう日があるんだよ"
    if rank.get(nl) == 1:
        return "展示1位だろ? ストップウォッチは正直なんだよ"
    if r1 and r1 >= 4 and nl != 1:
        return "1号艇の展示がもうひとつ。外の出番もあるかもな"
    return "展示で予想が変わる。それが競艇なんだよ"


def build(race: dict, info: dict, day: dt.date, late: dict | None = None, morning: dict | None = None,
          odds: dict[str, float] | None = None, usual: dict | None = None, tags: dict | None = None) -> dict | None:
    """展示速報の本文と画像。late=展示を入れた直前予想(無ければ展示の事実だけ)、morning=朝の予想、odds=締切前の3連単オッズ。"""
    from kyotei import seo
    from kyotei.xcard import tenji_card_html
    bx = info.get("boats") or {}
    ts = {int(l): float(b["exhibit_time"]) for l, b in bx.items() if b.get("exhibit_time") and b.get("exhibit_time") == b.get("exhibit_time")}
    if len(ts) < 5:
        return None
    rank = {l: 1 + sum(1 for x in ts.values() if x < t) for l, t in ts.items()}
    pw = {int(b["lane"]): float(b.get("p_win") or 0) for b in (late or {}).get("boats") or []} if late_ready(late) else {}
    p0 = {int(b["lane"]): float(b.get("p_win") or 0) for b in (morning or {}).get("boats") or []}
    mk = market_win(odds or {})
    fact = lab_fact()
    top = sorted([l for l in ts if rank[l] == 1])
    L = top[0]
    r1 = rank.get(1)
    # いちばん大きく見せる1行: 1号艇が展示で崩れた/1位なら逃げの見込み、ほかは展示1位の艇の見込み
    if pw:
        if r1 and (r1 == 1 or r1 >= 4):
            hook = f"1号艇は展示{r1}位。逃げの見込み {_chg(p0.get(1), pw[1])}"
        else:
            hook = f"展示1位は{L}号艇。1着の見込み {_chg(p0.get(L), pw[L])}"
    else:
        hook = f"展示1位は{'・'.join(f'{l}号艇' for l in top)}({ts[L]:.2f})" + (f"。1号艇は{r1}位" if r1 and L != 1 else "")
    # 狙い目かも?: 見立て(展示込み)が人気から考えた確率より大きい艇。見立て8%以上・1.3倍以上でいちばん差が大きい艇(買い目ではない)
    nl, nerai = None, ""
    if pw and mk:
        cands = [(pw[l] / mk[l], l) for l in pw if mk.get(l, 0) > 0.005 and pw[l] >= 0.08 and pw[l] / mk[l] >= 1.3]
        if cands:
            ratio, nl = max(cands)
            nerai = (f"展示で見方が変わった。狙い目かも? {nl}号艇の1着\n人気は{round(mk[nl] * 100)}%、ミカタの見立ては{round(pw[nl] * 100)}%"
                     f"(人気の{ratio:.1f}倍)→ 人気の割に来そう")
        else:
            nerai = "狙い目かも? 今回は見立てと人気がほぼ同じ(人気どおり)"
    # 今日の展示順位と、その選手のふだんの展示順位の差(+ はふだんより上)。2つ以上の差がある艇を1つ取り上げる
    rid = {int(b["lane"]): int(b["racer_id"]) for b in (late or morning or race).get("boats") or [] if b.get("racer_id")}
    dev = {l: (usual or {})[rid[l]][0] - rank[l] for l in ts if l in rid and rid[l] in (usual or {})}
    dv = lab_dev()
    dev_line = ""
    big = sorted([l for l in dev if abs(dev[l]) >= 2], key=lambda l: (-(dev[l] >= 2), l != 1, -abs(dev[l])))
    if big:
        l = big[0]
        u = (usual or {})[rid[l]][0]
        dev_line = (f"{l}号艇は展示{rank[l]}位(ふだん{u:.0f}位前後)。ふだんより2つ以上上の艇は3着以内{dv[0]}→{dv[1]}" if dev[l] > 0
                    else f"{l}号艇は展示{rank[l]}位(ふだん{u:.0f}位前後)。ふだんより2つ以上下だと3着以内{dv[0]}→{dv[2]}")
    # 型: 展示が悪くても本番で崩れにくいタイプ(選手カードの「展示は控えめ、本番で化ける」。時期を変えても少しは重なる程度の型)
    type_line = ""
    for l in sorted(ts, key=lambda x: -rank[x]):
        if rank[l] >= 4 and "展示は控えめ、本番で化ける" in ((tags or {}).get(l) or []):
            type_line = f"{l}号艇は展示{rank[l]}位。でも展示が悪くても本番で崩れにくいタイプ"
            break
    cl = course_line(info)
    rows = [{"lane": l, "time": ts[l], "rank": rank[l], "p": pw.get(l, p0.get(l)), "mkt": mk.get(l),
             "dev": (1 if dev.get(l, 0) >= 2 else -1 if dev.get(l, 0) <= -2 else 0),
             "course": (f"進入{int(bx[l]['ex_course'])}" if bx.get(l, {}).get("ex_course") and int(bx[l]["ex_course"]) != l else ""),
             "nerai": l == nl} for l in sorted(ts)]
    rt = str(race.get("race_type") or "")
    # 1行目は市場の型(場名+R+締切)に「展示速報」。2行目に、出した理由の「狙い目かも?」(2026-10-07 ユーザー「速報の時は何でタイトル?」)
    # 2026-10-07 ユーザー「ミカタ感がないからタイトル工夫」→ 名前の「ミカタ(見方)」に掛けて【ミカタ速報】+「展示で見方が変わった」。最後にミカタのひと言
    head = f"【ミカタ速報】{race['venue']}{race['rno']}R{(' ' + rt) if rt else ''} 締切{race['deadline']}"
    f_ = f"{'・'.join(f'{l}号艇' for l in top)}は展示1位。展示1位の艇の3着以内は{fact[1]}→{fact[2]}"
    tail = f"\n\nこういう見方もあるよ📰 あなたの予想は?\n{seo.x_tags(race['venue'])}"
    text = ""
    for parts in ([head, nerai, hook, dev_line], [head, nerai, hook, f_], [head, nerai, dev_line], [head, nerai, hook],
                  [head, nerai], [head, hook]):
        t = "\n".join(x for x in parts if x) + tail
        if xlen(t) <= 280:
            text = t
            break
    hook_card = re.sub(r"に(上がる|下がる)$", "", hook)   # 画像は矢印で向きが分かるので短く(2行に折れないように)
    dl_ = f"{day.month}/{day.day}({WEEK[day.weekday()]})"
    rc_ = f"{race['venue']}{race['rno']}R"
    # 2枚目: 6艇の展示順位・タイム・見立て・人気(いちばん大きい行は1号艇/展示1位の見込みの動き)
    table = tenji_card_html(dl_, rc_, race["deadline"], rt, hook_card, rows, "見立て(展示込み)" if pw else "見立て(朝)",
                            cl or "進入は展示の情報なし", fact, dev_line or type_line, "")
    cards = [table]
    if nl:   # 1枚目: 狙い目かも?(人気=みんなの予想と、ミカタの見立てを2本の棒で。なぜその艇か、を3つまで)
        from kyotei.xcard import myomi_card_html
        why = [f"展示タイム{rank[nl]}位" + (f"(ふだんは{(usual or {})[rid[nl]][0]:.0f}位前後)" if dev.get(nl, 0) >= 2 else "")]
        c_ = (bx.get(nl) or {}).get("ex_course")
        if c_ and int(c_) != nl:
            why.append(f"展示の進入は{int(c_)}コース")
        if p0.get(nl) is not None and round(p0[nl] * 100) != round(pw[nl] * 100):
            why.append(f"ミカタの見立ては朝{round(p0[nl] * 100)}%→展示込み{round(pw[nl] * 100)}%")
        good = [t for t in ((tags or {}).get(nl) or []) if t]
        if good:
            why.append(f"型: {'・'.join(good[:2])}")
        cards.insert(0, myomi_card_html(dl_, rc_, race["deadline"], rt, nl, pw[nl], mk[nl], why[:2], gen_line(nl, rank, dev, r1)))
    return {"text": text or (head + tail), "cards": cards, "card": cards[0], "late": bool(pw), "nerai": nl}


async def _render(html: str) -> bytes:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        await pg.set_content(html)
        await pg.evaluate("document.fonts.ready")
        await pg.wait_for_timeout(300)
        png = await pg.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        await b.close()
    return png


def render(html: str) -> bytes | None:
    try:
        return asyncio.run(_render(html))
    except Exception as ex:  # noqa: BLE001  画像が作れなくても文字だけで出す
        log("画像を作れませんでした:", ex)
        return None


def send(text: str, pngs: list[bytes] | bytes | None) -> str | None:
    import x_post
    if not x_post.creds() or os.environ.get("X_AUTOPOST") != "1":
        log("下書き(鍵か X_AUTOPOST が無い):\n" + text)
        return None
    if isinstance(pngs, (bytes, bytearray)):
        pngs = [pngs]
    s = x_post.session()
    mids = [m for m in (x_post.upload_media(s, b) for b in (pngs or [])[:4]) if m]
    return x_post.post(s, text, mids or None)


# ---------------------------------------------------------------- 見張り
def state_file(day: dt.date) -> pathlib.Path:
    return STATE_DIR / f"tenji_{day:%Y%m%d}.txt"


def load_state(day: dt.date) -> dict[str, str]:
    """出した(posted)・見送った(skip)レース。前のジョブの分も live ブランチから(ジョブは約6時間ごとに入れ替わる)。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = state_file(day)
    done: dict[str, str] = {}
    for raw in ((f.read_text() if f.exists() else ""), gh_raw(f"notify/tenji_{day:%Y%m%d}.txt", "live") or ""):
        for line in raw.splitlines():
            k, _, v = line.partition(" ")
            if k:
                done.setdefault(k, v or "posted")
    f.write_text("".join(f"{k} {v}\n" for k, v in sorted(done.items())))
    return done


def mark(day: dt.date, rid: str, done: dict, status: str = "posted"):
    done[rid] = status
    state_file(day).write_text("".join(f"{k} {v}\n" for k, v in sorted(done.items())))


def deadline_dt(day: dt.date, hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)


def live_sha() -> str:
    try:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/commits/live", "--jq", ".sha"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def wait_late(day: dt.date, race: dict, left_min: float, max_sec: int = 240) -> dict | None:
    """展示を入れた直前予想が live ブランチに出るのを待つ。直前予想のループを起こし(TENJI_DIR/kick)、
    最大4分(締切4分前まで)待つ。間に合わなければ None(展示の事実だけで出す)。"""
    (STATE_DIR / "kick").write_text(race["race_id"])
    end = time.time() + min(max_sec, max(0, (left_min - STOP_BEFORE - 1) * 60))
    sha = ""
    while True:
        s_ = live_sha()
        if s_ and s_ != sha:
            sha = s_
            r = next((x for x in today_races(day) if x.get("race_id") == race["race_id"]), None)
            if late_ready(r):
                return r
        if time.time() >= end:
            log("展示を入れた見立てが間に合わず(展示の事実だけで出す)", race["race_id"])
            return None
        time.sleep(20)


SELF_FILES = ("scripts/tenji_flash.py", "src/kyotei/xcard.py", "src/kyotei/scrape.py", "src/kyotei/seo.py")


def self_update(shas: dict) -> bool:
    """main で見張りのコードが直されたら、写しのフォルダに取り込んで自分を起動し直す(ジョブの入れ替わりを待たずに直しを入れる)。
    初回は今の sha を覚えるだけ。変わったら True(呼び出し側で execv)。"""
    changed = False
    for f in SELF_FILES:
        try:
            r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{f}?ref=main", "--jq", ".sha"], capture_output=True, text=True, timeout=30)
            sha = r.stdout.strip()
        except Exception:  # noqa: BLE001
            continue
        if not sha:
            continue
        if f in shas and shas[f] != sha:
            raw = gh_raw(f, "main")
            if raw:
                (ROOT / f).write_text(raw, encoding="utf-8")
                changed = True
                log("コードを取り込みました:", f)
        shas[f] = sha
    return changed


def watch(until: str = "23:30", every: int = 60):
    from kyotei.scrape import fetch, parse_beforeinfo, parse_odds3t
    day, done, tg, races, t_load, morning, usual = None, {}, [], [], 0.0, {}, {}
    shas: dict = {}
    t_upd = 0.0
    while now().strftime("%H:%M") < until:
        t0 = time.time()
        if time.time() - t_upd > 600:   # 10分ごとにコードの直しを確かめる
            t_upd = time.time()
            if self_update(shas) and shas:
                log("新しいコードで起動し直します")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        try:
            if day != now().date():
                day = now().date()
                done, t_load, usual = load_state(day), 0.0, {}
            if time.time() - t_load > 300:   # 対象と見立ては5分ごとに読み直す(朝の記事タブ・直前予想の更新を取り込む)
                races = today_races(day)
                tg = targets(day, races)
                if not usual:
                    try:
                        usual = usual_exrank(day)
                        log("ふだんの展示順位:", len(usual), "人")
                    except Exception as ex:  # noqa: BLE001
                        log("ふだんの展示順位を作れませんでした:", ex)
                mday = gh_json(f"docs/data/days/{day.isoformat()}.json", "main") or {}   # 朝の予想(「朝→展示込み」の変化用)
                morning = {x["race_id"]: x for x in mday.get("races", [])}
                t_load = time.time()
                log("対象:", [f"{r['venue']}{r['rno']}R {r['deadline']}" for r in tg],
                    "出した:", sum(1 for v in done.values() if v == "posted"), "見送り:", sum(1 for v in done.values() if v != "posted"))
            for r in tg:
                if r["race_id"] in done:
                    continue
                if sum(1 for v in done.values() if v == "posted") >= MAX_PER_DAY:
                    break
                left = (deadline_dt(day, r["deadline"]) - now()).total_seconds() / 60
                if not (STOP_BEFORE <= left <= WATCH_FROM):
                    continue
                hd = day.strftime("%Y%m%d")
                html = fetch("beforeinfo", r["jcd"], r["rno"], hd)
                info = parse_beforeinfo(html) if html else {}
                bx = info.get("boats") or {}
                if sum(1 for b in bx.values() if b.get("exhibit_time")) < 5:
                    continue
                late = wait_late(day, r, left)
                oh = fetch("odds3t", r["jcd"], r["rno"], hd)
                odds = parse_odds3t(oh) if oh else {}
                tags = {int(b["lane"]): racer_tags(int(b["racer_id"])) for b in r.get("boats") or [] if b.get("racer_id")}
                out = build(r, info, day, late=late, morning=morning.get(r["race_id"]), odds=odds, usual=usual, tags=tags)
                if not out:
                    continue
                if not out.get("nerai"):   # 狙い目かも?が出なかったレースは出さない(展示を入れた見立てが間に合わなかったときも)
                    log("見送り(狙い目かも?なし)", f"{r['venue']}{r['rno']}R", "見立て" + ("あり" if out.get("late") else "間に合わず"))
                    mark(day, r["race_id"], done, "skip")
                    continue
                pngs = [x for x in (render(h) for h in out["cards"]) if x]
                try:
                    tid = send(out["text"], pngs)
                    log("出しました" if tid else "下書きのみ", f"{r['venue']}{r['rno']}R 締切{r['deadline']} 残り{left:.0f}分", tid or "")
                except BaseException as ex:  # noqa: BLE001  1本の失敗で見張りを止めない(二重に出さないよう、出したことにする)
                    log("投稿に失敗:", ex)
                mark(day, r["race_id"], done)
        except Exception as ex:  # noqa: BLE001
            log("見張りでエラー(続けます):", ex)
        time.sleep(max(5, every - (time.time() - t0)))


def demo(out_dir: pathlib.Path):
    """手元の確認用: 架空の展示・見立て・オッズで本文と画像を作る(投稿しない)。"""
    import numpy as np
    from kyotei.betting import COMBOS
    race = {"race_id": "demo", "venue": "住之江", "rno": 12, "deadline": "20:45", "race_type": "準優勝戦"}
    pl, pm0 = (.50, .13, .12, .14, .06, .05), (.55, .14, .12, .09, .06, .04)
    late = {**race, "stage": "late", "boats": [{"lane": i, "racer_id": 1000 + i, "exhibit_time": 6.7, "p_win": p} for i, p in zip(range(1, 7), pl)]}
    morning = {**race, "boats": [{"lane": i, "p_win": p} for i, p in zip(range(1, 7), pm0)]}
    mw = np.array([.60, .13, .11, .08, .05, .03])
    def pl(c):   # 人気の3連単確率(1着→2着→3着の順に、残りの中で選ばれる)
        a_, b_, c_ = (int(x) - 1 for x in c.split("-"))
        return mw[a_] * mw[b_] / (1 - mw[a_]) * mw[c_] / (1 - mw[a_] - mw[b_])
    odds = {c: round(0.75 / pl(c), 1) for c in COMBOS}
    info = {"boats": {1: {"exhibit_time": 6.74, "ex_course": 1}, 2: {"exhibit_time": 6.71, "ex_course": 2}, 3: {"exhibit_time": 6.70, "ex_course": 3},
                      4: {"exhibit_time": 6.62, "ex_course": 4}, 5: {"exhibit_time": 6.77, "ex_course": 5}, 6: {"exhibit_time": 6.71, "ex_course": 6}}}
    usual = {1001: (2.1, 40), 1002: (3.5, 30), 1003: (3.2, 33), 1004: (4.3, 25), 1005: (3.8, 20), 1006: (4.0, 22)}
    tags = {5: ["展示は控えめ、本番で化ける"]}
    o = build(race, info, now().date(), late=late, morning=morning, odds=odds, usual=usual, tags=tags)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tenji_demo.txt").write_text(o["text"], encoding="utf-8")
    for i, h in enumerate(o["cards"], 1):
        png_ = render(h)
        if png_:
            (out_dir / f"tenji_demo{i}.png").write_bytes(png_)
    png = render(o["card"])
    if png:
        (out_dir / "tenji_demo.png").write_bytes(png)
    print(o["text"], f"\n({xlen(o['text'])}/280)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--until", default="23:30")
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--demo", default=None, help="確認用の出力先フォルダ")
    a = ap.parse_args()
    if a.demo:
        demo(pathlib.Path(a.demo))
    elif a.watch:
        watch(a.until, a.every)


if __name__ == "__main__":
    main()
