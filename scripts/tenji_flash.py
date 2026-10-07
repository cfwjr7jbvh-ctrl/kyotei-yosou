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


def gh_json(path: str, ref: str):
    raw = gh_raw(path, ref)
    if not raw:
        return None
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


def targets(day: dt.date, races: list[dict]) -> list[dict]:
    """ミカタ新聞のレース(今日のX投稿の「新聞:」)と、SG・G1 の準優・優勝戦。"""
    q = gh_json(f"ura/xpost_{day:%Y%m%d}.json", "cards") or {}
    want = set()
    for it in q.get("queue") or []:
        m = re.match(r"新聞:\s*(\D+?)(\d+)R", str(it.get("label", "")))
        if m:
            want.add((m.group(1), int(m.group(2))))
    big = {s.get("jcd") for s in q.get("series_today") or [] if s.get("grade") in ("SG", "G1")}
    return [r for r in races if r.get("deadline") and ((r.get("venue"), r.get("rno")) in want
                                                       or (r.get("jcd") in big and "優勝戦" in str(r.get("race_type") or "")))]


def lab_fact() -> tuple[str, str, str]:
    """検証ラボ「展示タイム番長は本物か」の数字(展示1位の艇が3着以内に入る ふだん → 展示1位)。読めなければ記事どおりの値。"""
    a, b = 0.507, 0.626
    try:
        from kyotei.publish import load_private
        t = load_private(ROOT / "reports/lab/tenji.json") or {}
        m = next(m for n, m, _ in t.get("measures") or [] if n == "展示タイム1位")
        a, b = float(m["in1_ref"]), float(m["in1"])
    except Exception:  # noqa: BLE001
        pass
    return "展示1位の艇が3着以内に入る", f"{round(a * 100)}%", f"{round(b * 100)}%"


# ---------------------------------------------------------------- 中身
def tenji_rows(info: dict) -> list[dict]:
    bx = info.get("boats") or {}
    ts = {int(l): float(b["exhibit_time"]) for l, b in bx.items() if b.get("exhibit_time") == b.get("exhibit_time") and b.get("exhibit_time")}
    order = sorted(ts, key=lambda l: (ts[l], l))
    rows = []
    for l in order:
        rank = 1 + sum(1 for x in ts.values() if x < ts[l])
        c = (bx.get(l) or {}).get("ex_course")
        rows.append({"rank": rank, "lane": l, "time": ts[l],
                     "course": (f"進入{int(c)}コース" if c and int(c) != l else "") if c == c and c else ""})
    return rows


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


def view_line(race: dict) -> str:
    """展示を入れた直前予想が出ていれば、1着の見込みの上位2艇。まだ展示が入っていなければ空。"""
    boats = race.get("boats") or []
    if race.get("stage") != "late" or sum(1 for b in boats if b.get("exhibit_time")) < 5:
        return ""
    top = sorted(boats, key=lambda b: -(b.get("p_win") or 0))[:2]
    return "展示を入れた見立て: 1着は " + "・".join(f"{b['lane']}号艇{round((b.get('p_win') or 0) * 100)}%" for b in top)


def build(race: dict, info: dict, day: dt.date) -> dict | None:
    rows = tenji_rows(info)
    if len(rows) < 5:
        return None
    from kyotei import seo
    from kyotei.xcard import tenji_card_html
    fact = lab_fact()
    top = [r for r in rows if r["rank"] == 1]
    cl, vw = course_line(info), view_line(race)
    rt = str(race.get("race_type") or "")
    head = f"【展示】{race['venue']}{race['rno']}R{(' ' + rt) if rt else ''}(締切{race['deadline']})"
    t1 = "・".join(f"{r['lane']}号艇" for r in top) + f" {top[0]['time']:.2f}"
    lines = [head, f"展示タイム1位は{t1}", f"→ {fact[0]}のは{fact[2]}(ふだんは{fact[1]})"]
    if cl:
        lines.append(cl)
    tail = f"\n\n展示を見て、あなたの予想は変わった?\n{seo.x_tags(race['venue'])}"
    text = "\n".join(lines + ([vw] if vw else [])) + tail
    if xlen(text) > 280:
        text = "\n".join(lines) + tail
    card = tenji_card_html(f"{day.month}/{day.day}({WEEK[day.weekday()]})", f"{race['venue']}{race['rno']}R", race["deadline"], rt,
                           rows, fact, cl or "進入は展示の情報なし", vw)
    return {"text": text, "card": card}


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


def send(text: str, png: bytes | None) -> str | None:
    import x_post
    if not x_post.creds() or os.environ.get("X_AUTOPOST") != "1":
        log("下書き(鍵か X_AUTOPOST が無い):\n" + text)
        return None
    s = x_post.session()
    mid = x_post.upload_media(s, png) if png else None
    return x_post.post(s, text, mid)


# ---------------------------------------------------------------- 見張り
def state_file(day: dt.date) -> pathlib.Path:
    return STATE_DIR / f"tenji_{day:%Y%m%d}.txt"


def load_state(day: dt.date) -> set[str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = state_file(day)
    done = set(f.read_text().split()) if f.exists() else set()
    prev = gh_raw(f"notify/tenji_{day:%Y%m%d}.txt", "live")   # 前のジョブが出した分(ジョブは約6時間ごとに入れ替わる)
    if prev:
        done |= set(prev.split())
        f.write_text("\n".join(sorted(done)) + "\n")
    return done


def mark(day: dt.date, rid: str, done: set[str]):
    done.add(rid)
    state_file(day).write_text("\n".join(sorted(done)) + "\n")


def deadline_dt(day: dt.date, hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)


def watch(until: str = "23:30", every: int = 60):
    from kyotei.scrape import fetch, parse_beforeinfo
    day, done, tg, races, t_load = None, set(), [], [], 0.0
    while now().strftime("%H:%M") < until:
        t0 = time.time()
        try:
            if day != now().date():
                day = now().date()
                done, t_load = load_state(day), 0.0
            if time.time() - t_load > 300:   # 対象と見立ては5分ごとに読み直す(朝の記事タブ・直前予想の更新を取り込む)
                races = today_races(day)
                tg = targets(day, races)
                t_load = time.time()
                log("対象:", [f"{r['venue']}{r['rno']}R {r['deadline']}" for r in tg], "出した:", len(done))
            for r in tg:
                if r["race_id"] in done:
                    continue
                left = (deadline_dt(day, r["deadline"]) - now()).total_seconds() / 60
                if not (STOP_BEFORE <= left <= WATCH_FROM):
                    continue
                html = fetch("beforeinfo", r["jcd"], r["rno"], day.strftime("%Y%m%d"))
                info = parse_beforeinfo(html) if html else {}
                out = build(r, info, day)
                if not out:
                    continue
                png = render(out["card"])
                try:
                    tid = send(out["text"], png)
                    log("出しました" if tid else "下書きのみ", f"{r['venue']}{r['rno']}R 締切{r['deadline']} 残り{left:.0f}分", tid or "")
                except BaseException as ex:  # noqa: BLE001  1本の失敗で見張りを止めない(二重に出さないよう、出したことにする)
                    log("投稿に失敗:", ex)
                mark(day, r["race_id"], done)
        except Exception as ex:  # noqa: BLE001
            log("見張りでエラー(続けます):", ex)
        time.sleep(max(5, every - (time.time() - t0)))


def demo(out_dir: pathlib.Path):
    """手元の確認用: 架空の展示で本文と画像を作る(投稿しない)。"""
    race = {"race_id": "demo", "venue": "住之江", "rno": 12, "deadline": "20:45", "race_type": "準優勝戦", "stage": "late",
            "boats": [{"lane": i, "exhibit_time": 6.7, "p_win": p} for i, p in zip(range(1, 7), (.58, .12, .1, .11, .05, .04))]}
    info = {"boats": {1: {"exhibit_time": 6.68, "ex_course": 1}, 2: {"exhibit_time": 6.71, "ex_course": 3}, 3: {"exhibit_time": 6.74, "ex_course": 2},
                      4: {"exhibit_time": 6.62, "ex_course": 4}, 5: {"exhibit_time": 6.77, "ex_course": 5}, 6: {"exhibit_time": 6.71, "ex_course": 6}}}
    o = build(race, info, now().date())
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tenji_demo.txt").write_text(o["text"], encoding="utf-8")
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
