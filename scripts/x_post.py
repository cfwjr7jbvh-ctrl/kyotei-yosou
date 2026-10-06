"""X(旧Twitter)への投稿: 毎日の下書きを作り、鍵があれば投稿する。鍵が無いあいだは下書きだけ(reports/x_drafts/ に残す)。

python scripts/x_post.py theory    # 8:20 今日の理論ぶつけ(画像つき。記事タブの「今日のX投稿」から)
python scripts/x_post.py morning   # 12:10 今日の荒れそうなレース(文字だけ)
python scripts/x_post.py evening   # 20:00 火・金は検証ラボ、ほかの日は次のグレードレースの注目選手(画像つき)
python scripts/x_post.py neta      # 15:30 1枚1ネタ(前の日の投票の答え。画像つき)
python scripts/x_post.py poll      # 21:30 投票(次の日の1枚1ネタを先に問題に。24時間)
python scripts/x_post.py event     # 大会の準優・優勝戦: 締切70分前の投稿のうち、時間が来ていてまだ出していないもの(15分ごとに見る)
  ※ theory / morning / evening は、記事タブの「今日のX投稿」(cards ブランチ ura/xpost_YYYYMMDD.json)と同じ文章・画像を出す。
    そこに無いときだけ、従来どおりここで作る
python scripts/x_post.py thread --key 04_20261013   # 大会前の3投稿のスレッド(最後だけ note のリンク。NOTE_URL を渡す)
python scripts/x_post.py test      # 鍵の確認だけ(投稿しない)

投稿する条件: GitHub の Secrets に X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET があり、
リポジトリの変数 X_AUTOPOST が "1"。どちらかが無ければ下書きを書いて終わる(--dry でも同じ)。
料金(2026年、使った分だけ): 文字だけ $0.015/本、リンク入り $0.20/本、画像はほぼ無料。読み取りは使わない。
同じ日に同じ種類を2回は投稿しない(reports/x_drafts/posted.json に記録)。
決まりごと(発信方針): 的中・回収率・儲けの話をしない、問いかけで終える、リンクは最後の投稿だけ、舟券は20歳から。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.xtext import xlen  # noqa: E402
from kyotei.publish import read_json  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
DRAFTS = ROOT / "reports/x_drafts"
POSTED = DRAFTS / "posted.json"
API = "https://api.x.com/2"
ARASHI_WORD = {5: "大荒れ注意", 4: "荒れ気味"}


# ---------------------------------------------------------------- データ
def git_show(ref: str, path: str) -> str | None:
    try:
        subprocess.run(["git", "fetch", "-q", "origin", ref], cwd=ROOT, check=True, capture_output=True)
        return subprocess.run(["git", "show", f"FETCH_HEAD:{path}"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return None


def load_enc(ref: str, path: str):
    raw = git_show(ref, path)
    if raw is None:
        return None
    tmp = DRAFTS / "_tmp.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(raw, encoding="utf-8")
    try:
        return read_json(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def today_races() -> list[dict]:
    day = dt.datetime.now(JST).strftime("%Y-%m-%d")
    d = load_enc("live", f"days/{day}.json") or load_enc("main", f"docs/data/days/{day}.json")
    return (d or {}).get("races", [])


def ura_index() -> dict:
    return load_enc("cards", "ura/index.json") or {"items": []}


# ---------------------------------------------------------------- 文章(アプリの表示と同じ考え方。理由は本物と確かめた型だけ)
def st_fmt(v: float) -> str:
    return ("F" if v < 0 else "") + f"{abs(v):.2f}"[1:]


def reasons(r: dict) -> list[str]:
    out = []
    boats = r.get("boats", [])
    course = lambda b: b.get("course") if r.get("stage") == "late" and b.get("course") else b["lane"]  # noqa: E731
    inb = next((b for b in boats if course(b) == 1), boats[0] if boats else None)
    if not inb:
        return out
    t = inb.get("traits") or {}
    st = t.get("st_pred") if r.get("stage") == "late" and t.get("st_pred") is not None else t.get("st")
    bad = []
    if t.get("nige") is not None and t["nige"] < 0.39:
        bad.append(f"逃げ率{round(t['nige'] * 100)}%")
    if st is not None and st >= 0.18:
        bad.append(f"ST {st_fmt(st)}")
    if t.get("series") is not None and t["series"] <= -0.27:
        bad.append("今節の足△")
    elif t.get("motor") is not None and t["motor"] <= -0.15:
        bad.append("モーター△")
    if (t.get("f") or 0) >= 1:
        bad.append("F持ち")
    if bad:
        out.append(f"{inb['lane']}号艇に不安材料({'・'.join(bad[:2])})")
    for b in boats:
        c = course(b)
        if c is None or c < 2 or c > 5:
            continue
        u = b.get("traits") or {}
        types = [("まくり", u.get("makuri"), 0.048), ("差し", u.get("sashi"), 0.042), ("まくり差し", u.get("mz"), 0.040)]
        types = sorted([x for x in types if x[1] is not None and x[1] >= x[2]], key=lambda x: -x[1] / x[2])
        bst = u.get("st_pred") if r.get("stage") == "late" and u.get("st_pred") is not None else u.get("st")
        if types:
            out.append(f"{b['lane']}号艇は{types[0][0]}型" + (f"でST速い({st_fmt(bst)})" if bst is not None and bst <= 0.144 else ""))
        elif bst is not None and bst <= 0.135:
            out.append(f"{b['lane']}号艇のST速い({st_fmt(bst)})")
    return out[:3]


def morning_text(races: list[dict], now: dt.datetime) -> str | None:
    def mins_left(r):
        try:
            hh, mm = map(int, r["deadline"].split(":"))
        except (KeyError, ValueError, AttributeError):
            return None
        return (now.replace(hour=hh, minute=mm, second=0) - now).total_seconds() / 60
    up = [r for r in races if not r.get("result") and (r.get("arashi") or {}).get("in_lose") is not None
          and (mins_left(r) is None or mins_left(r) > 0)]
    up.sort(key=lambda r: -r["arashi"]["in_lose"])
    top = up[:3]
    if not top:
        return None
    lines = [f"{'①②③'[i]} {r['venue']}{r['rno']}R({r['deadline']}) 1号艇以外が勝つ見込み{round(r['arashi']['in_lose'] * 100)}%" for i, r in enumerate(top)]
    why = [w for w in reasons(top[0]) if "不安材料" not in w]   # 不利な面を強調しない(発信方針)。挑む側の強みだけ
    head = f"今日の荒れそうなレース🌊 {now:%-m/%-d}\n\n" + "\n".join(lines)
    for k in (3, 2, 1, 0):
        w = f"\n\n{top[0]['venue']}{top[0]['rno']}R:{'、'.join(why[:k])}" if why[:k] else ""
        body = head + w + "\n\n荒れそう=当てやすい、ではないです。どのレースが荒れると思う?"
        if xlen(body) <= 280:
            return body
    return head + "\n\nどのレースが荒れると思う?"


def evening_pick(idx: dict, posted: dict) -> tuple[dict, dict, dict] | None:
    """次に近いグレードレースの注目選手から、まだ出していない人を順に。(節, 下書き, 画像)"""
    items = sorted(idx.get("items", []), key=lambda x: x["hd"])
    for it in items:
        d = load_enc("cards", f"ura/{it['key']}.json")
        if not d:
            continue
        done = set(posted.get("evening_racers", []))
        for p, im in zip(d.get("picks", []), [x for x in d.get("images", []) if not x["name"].startswith("早見表")]):
            if f"{it['key']}:{p['id']}" in done:
                continue
            img = load_enc("cards", f"ura/{im['file']}")
            if img:
                return it, {**p, "key": it["key"], "title": d["title"], "venue": d["venue"], "hd": it["hd"]}, img
    return None


def evening_text(p: dict, card: dict | None) -> str:
    hd = f"{int(p['hd'][4:6])}/{int(p['hd'][6:])}"
    tag = p.get("tag", "")
    why = ""
    if card:
        t = next((x for x in card.get("tags", []) if x["t"] == tag), None)
        why = t["why"] if t else ""
    q = {"スタート職人": "スリットで前に出たら、どう組み立てる?", "イン逃げ番長": "1号艇のとき、信じる派? 崩す派?",
         "まくり屋": "外に入ったときの一撃、狙う?", "差し職人": "2コースに入ったら差しの筋、考える?",
         "まくり差しの職人": "3コースより外のとき、すき間を突く筋、見る?"}.get(tag, "あなたはこの選手、どう見る?")
    body = f"{p['title']}({p['venue']}、{hd}〜)の注目選手📰\n\n{p['name']}「{tag}」\n{why}\n\n{q}"
    if xlen(body) > 280:
        body = f"{p['title']}({hd}〜)の注目選手📰\n\n{p['name']}「{tag}」\n{why}\n\n{q}"
    if xlen(body) > 280:
        body = f"{p['name']}「{tag}」\n{why}\n\n{q}\n#{p['venue']} #競艇"
    return body


def thread_texts(key: str, note_url: str | None) -> list[str]:
    d = load_enc("cards", f"ura/{key}.json")
    if not d:
        raise SystemExit(f"下書きがありません: {key}")
    posts = []
    import re
    for m in re.finditer(r"--- 投稿(\d+)\((\d+)字\)(.*?) ---\n([\s\S]*?)(?=\n--- 投稿|\n画像:|\Z)", d["x"]):
        n, body = int(m.group(1)), m.group(4).strip()
        if n > 3:
            break
        if n == 3 and note_url:
            body = body.replace("(noteのURL)", note_url)
        posts.append(body)
    return posts


# ---------------------------------------------------------------- X API
SLOTS = {"theory": "8:20", "morning": "12:10", "neta": "15:30", "evening": "20:00", "poll": "21:30"}


def queue(day: str) -> list[dict]:
    q = load_enc("cards", f"ura/xpost_{day.replace('-', '')}.json")
    return (q or {}).get("queue", [])


def queue_item(day: str, slot: str) -> tuple[str, bytes | None, dict | None] | None:
    """記事タブの「今日のX投稿」から、その時間帯の投稿(本文, 画像, 投票)を取る。"""
    want = SLOTS[slot]
    for it in queue(day):
        if it.get("time") == want and not str(it.get("label", "")).startswith("大会:"):
            img = load_enc("cards", f"ura/{it['image']}") if it.get("image") else None
            return it["text"], (base64.b64decode(img["png"]) if img else None), it.get("poll")
    return None


def hm(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def event_due(day: str, now: dt.datetime, posted: dict) -> list[dict]:
    """大会の投稿で、出す時間を過ぎていて、締切の10分前より前で、まだ出していないもの。"""
    t = now.hour * 60 + now.minute
    out = []
    for it in queue(day):
        if not str(it.get("label", "")).startswith("大会:") or not it.get("deadline"):
            continue
        tag = f"event:{it['label']}"
        if posted.get(tag) == day:
            continue
        if hm(it["time"]) <= t < hm(it["deadline"]) - 10:
            out.append({**it, "tag": tag})
    return out


def creds() -> dict | None:
    k = {n: os.environ.get(n, "") for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    return k if all(k.values()) else None


def session():
    from requests_oauthlib import OAuth1Session
    c = creds()
    return OAuth1Session(c["X_API_KEY"], client_secret=c["X_API_SECRET"], resource_owner_key=c["X_ACCESS_TOKEN"],
                         resource_owner_secret=c["X_ACCESS_SECRET"])


def upload_media(s, png: bytes) -> str:
    """v2 の media upload(INIT → APPEND → FINALIZE)。"""
    r = s.post(f"{API}/media/upload", data={"command": "INIT", "total_bytes": len(png), "media_type": "image/png", "media_category": "tweet_image"})
    r.raise_for_status()
    mid = r.json()["data"]["id"]
    for i in range(0, len(png), 4_000_000):
        r = s.post(f"{API}/media/upload", data={"command": "APPEND", "media_id": mid, "segment_index": i // 4_000_000},
                   files={"media": png[i:i + 4_000_000]})
        r.raise_for_status()
    r = s.post(f"{API}/media/upload", data={"command": "FINALIZE", "media_id": mid})
    r.raise_for_status()
    return mid


def post(s, text: str, media_id: str | None = None, reply_to: str | None = None, poll: dict | None = None) -> str:
    body: dict = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    elif poll:   # 投票と画像は一緒にできない
        body["poll"] = {"options": poll["options"][:4], "duration_minutes": int(poll.get("minutes", 1440))}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    r = s.post(f"{API}/tweets", json=body)
    if r.status_code >= 300:
        raise SystemExit(f"投稿に失敗: {r.status_code} {r.text[:300]}")
    return r.json()["data"]["id"]


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["theory", "morning", "neta", "evening", "poll", "event", "thread", "test"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--note-url", default=os.environ.get("NOTE_URL") or None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.now(JST)
    DRAFTS.mkdir(parents=True, exist_ok=True)
    posted = json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else {}
    live = bool(creds()) and os.environ.get("X_AUTOPOST") == "1" and not a.dry
    print("鍵:", "あり" if creds() else "なし", "/ 自動投稿:", "ON" if live else "OFF(下書きだけ)")
    if a.what == "test":   # 鍵が通るか(自分のアカウント名を1回だけ読む。投稿はしない)
        if creds():
            r = session().get(f"{API}/users/me")
            print("鍵の確認:", r.status_code, (r.json().get("data") or {}).get("username") if r.ok else r.text[:300])
        return
    day = now.strftime("%Y-%m-%d")
    texts, media, poll = [], None, None
    tag = a.what
    if a.what == "event":
        due = event_due(day, now, posted)
        if not due:
            print("いま出す大会の投稿はありません"); return
        it = due[0]   # 1回に1本(同じ時間に重なったら次の15分で)
        texts, tag = [it["text"]], it["tag"]
    qi = queue_item(day, a.what) if a.what in SLOTS else None
    if qi:
        texts, media, poll = [qi[0]], qi[1], qi[2]
    elif a.what in ("neta", "poll"):
        print("今日のこの時間の投稿がありません(記事タブの更新待ち)"); return
    elif a.what == "event":
        pass
    elif a.what == "theory":
        print("今日の理論ぶつけの投稿がまだありません(記事タブの更新待ち)"); return
    elif a.what == "morning":
        t = morning_text(today_races(), now)
        if not t:
            print("今日の予想がまだ無いか、締切前のレースがありません"); return
        texts = [t]
    elif a.what == "evening":
        pk = evening_pick(ura_index(), posted)
        if not pk:
            print("出せるカードがありません(グレードレースの下書きが無い、または全員出した)"); return
        it, p, img = pk
        card = None
        try:
            b = p["id"] % 50
            bucket = load_enc("cards", f"cards/b{b:02d}.json")
            card = (bucket or {}).get("cards", {}).get(str(p["id"]))
        except Exception:
            card = None
        texts = [evening_text(p, card)]
        media = base64.b64decode(img["png"])
        tag = f"evening:{p['key']}:{p['id']}"
    elif a.what == "thread":
        if not a.key:
            raise SystemExit("--key 場コード_初日 を指定")
        texts = thread_texts(a.key, a.note_url)
        tag = f"thread:{a.key}"
    if posted.get(tag) == day or (a.what == "thread" and tag in posted):
        print("今日はもう出しています:", tag); return
    # 下書きを残す
    draft = DRAFTS / f"{day}_{a.what}.txt"
    draft.write_text("\n\n---\n\n".join(texts) + ("\n\n(画像つき)" if media else "")
                     + (f"\n\n(投票: {' / '.join(poll['options'])})" if poll and not media else ""), encoding="utf-8")
    for i, t in enumerate(texts, 1):
        print(f"--- {i} ({xlen(t)}/280) ---\n{t}\n")
    if not live:
        print("下書き:", draft); return
    s = session()
    mid = upload_media(s, media) if media else None
    last = None
    ids = []
    for t in texts:
        last = post(s, t, mid if not ids else None, last, poll if not ids else None)
        ids.append(last)
    posted[tag] = day if a.what != "thread" else {"day": day, "ids": ids}
    if a.what == "evening" and ":" in tag:
        posted.setdefault("evening_racers", []).append(tag.split(":", 1)[1])
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=1), encoding="utf-8")
    print("投稿しました:", ids)
    try:   # 出した記事の履歴(reports/published.json)にも残す
        import publish_log
        slot = SLOTS.get(a.what) or (texts and a.what == "event" and tag.split(":", 1)[1]) or None
        key = f"xpost_{day.replace('-', '')}" if (qi or a.what == "event") else f"x:{tag}"
        publish_log.add(key, "X", f"https://x.com/i/web/status/{ids[0]}", now.date(), slot, via="自動投稿", text=texts[0])
    except SystemExit as ex:
        print(ex)
    except Exception as ex:  # noqa: BLE001
        print("履歴に残せませんでした:", ex)


if __name__ == "__main__":
    main()
