"""Yahoo!リアルタイム検索のページから X の投稿(id・アカウント・時刻・反応の数・本文)を取り出す。
X のページそのものは読まない(決まり)。取り出した本文はデータとしてだけ扱い、公開リポジトリには平文で置かない。
mikata-lab の scripts/popular_posts.py の parse と同じ考え方。"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse

JST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (personal research; mikata)", "Accept-Language": "ja"}
_TEXT_KEYS = ("displayText", "text", "body", "fullText")
_ID_KEYS = ("id", "tweetId", "postId", "statusId")
_last = [0.0]


def get(url: str, gap: float = 1.5) -> str | None:
    import requests
    wait = gap - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=20)
        return r.text if r.ok else None
    except Exception:  # noqa: BLE001
        return None


def _walk(o, out: list):
    if isinstance(o, dict):
        if any(isinstance(o.get(k), str) and len(o.get(k)) >= 8 for k in _TEXT_KEYS) and any(k in o for k in _ID_KEYS):
            out.append(o)
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"[\d,]+", v.strip()):
        return int(v.replace(",", ""))
    return None


def _count(d: dict, pats: tuple[str, ...]) -> int:
    for k, v in d.items():
        if any(p in k.lower() for p in pats) and _num(v) is not None:
            return _num(v)
    return 0


def _time(d: dict) -> dt.datetime | None:
    for k in ("createdAt", "created_at", "time", "postedAt", "date"):
        v = d.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                x = float(v)
                return dt.datetime.fromtimestamp(x / 1000 if x > 1e11 else x, JST)
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(JST)
        except (ValueError, OSError):
            continue
    return None


def parse(html: str) -> list[dict]:
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html or "")
    ents: list = []
    if m:
        try:
            _walk(json.loads(m.group(1)), ents)
        except json.JSONDecodeError:
            pass
    out, seen = [], set()
    for e in ents:
        text = next((e[k] for k in _TEXT_KEYS if isinstance(e.get(k), str)), "")
        text = re.sub(r"\t?(START|END)\t?", "", text)
        pid = str(next((e[k] for k in _ID_KEYS if e.get(k) not in (None, "")), ""))
        user = next((str(e[k]) for k in ("screenName", "screen_name", "userScreenName", "username") if e.get(k)), "")
        if not user and isinstance(e.get("user"), dict):
            user = str(e["user"].get("screenName") or e["user"].get("screen_name") or "")
        if not (pid and user and text) or pid in seen:
            continue
        seen.add(pid)
        t = _time(e)
        out.append({"id": pid, "user": user, "text": text, "at": t, "likes": _count(e, ("like", "fav")),
                    "reposts": _count(e, ("rtcount", "retweet", "repost", "rt_count")), "replies": _count(e, ("reply",)),
                    "badge": bool(e.get("badge"))})
    return out


def search(q: str) -> list[dict]:
    """新しい順(リアルタイム)の検索結果。"""
    return parse(get(f"https://search.yahoo.co.jp/realtime/search?p={urllib.parse.quote(q)}&ei=UTF-8"))
