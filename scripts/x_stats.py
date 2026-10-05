"""X の反応を自動で取る(自分の投稿の表示回数・いいね・返信・ブックマーク・プロフィールのクリック と、自分への返信)。

python scripts/x_stats.py            # 鍵があれば取る。無ければ何もしない
→ reports/x_stats.json(平文。投稿の種類ごとの平均と、投稿ごとの数字。文章は先頭だけ)
→ docs/data/x_replies.json(暗号化。自分への返信の一覧。アプリの「記事」タブに「返信待ち」として出す)

料金(2026年、従量課金): 自分のデータの読み取り $0.001/件、他人の投稿(返信)の読み取り $0.005/件。
週2回・直近50投稿+返信50件で月 $0.5 ほど。
投稿の種類は文章の先頭で判定: 朝=荒れそうなレース、夜=注目選手、小ネタ=ジンクス、大会前=スレッド。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.publish import write_json  # noqa: E402

API = "https://api.x.com/2"
STATS = ROOT / "reports/x_stats.json"
REPLIES = ROOT / "docs/data/x_replies.json"
JST = dt.timezone(dt.timedelta(hours=9))
KIND = [("今日の荒れそうなレース", "朝:荒れそうなレース"), ("の注目選手", "夜:注目選手カード"), ("って本当?", "小ネタ:ジンクス"),
        ("は本当でした", "小ネタ:ジンクス"), ("熱いのか", "小ネタ:ジンクス"), ("出場予定", "大会前:スレッド1"),
        ("どこまで信じる?", "大会前:スレッド2"), ("noteにまとめました", "大会前:スレッド3(リンク)")]


def kind_of(text: str) -> str:
    return next((k for key, k in KIND if key in text), "その他")


def main():
    keys = {n: os.environ.get(n, "") for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    if not all(keys.values()):
        print("鍵が無いので何もしません"); return
    from requests_oauthlib import OAuth1Session
    s = OAuth1Session(keys["X_API_KEY"], client_secret=keys["X_API_SECRET"], resource_owner_key=keys["X_ACCESS_TOKEN"],
                      resource_owner_secret=keys["X_ACCESS_SECRET"])
    me = s.get(f"{API}/users/me", params={"user.fields": "public_metrics,username"}).json()["data"]
    uid, handle = me["id"], me["username"]
    r = s.get(f"{API}/users/{uid}/tweets", params={"max_results": 50, "exclude": "retweets,replies",
                                                   "tweet.fields": "created_at,public_metrics,non_public_metrics"})
    r.raise_for_status()
    posts = r.json().get("data", [])
    old = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {"posts": {}}
    for p in posts:
        pm, npm = p.get("public_metrics", {}), p.get("non_public_metrics", {})
        old["posts"][p["id"]] = {"at": p["created_at"], "kind": kind_of(p["text"]), "head": p["text"][:40],
                                 "impressions": pm.get("impression_count"), "likes": pm.get("like_count"), "replies": pm.get("reply_count"),
                                 "reposts": pm.get("retweet_count"), "bookmarks": pm.get("bookmark_count"),
                                 "profile_clicks": npm.get("user_profile_clicks"), "link_clicks": npm.get("url_link_clicks")}
    by = {}
    for v in old["posts"].values():
        b = by.setdefault(v["kind"], {"n": 0, "impressions": 0, "likes": 0, "replies": 0, "bookmarks": 0, "profile_clicks": 0})
        b["n"] += 1
        for k in ("impressions", "likes", "replies", "bookmarks", "profile_clicks"):
            b[k] += v.get(k) or 0
    old["by_kind"] = {k: {"n": b["n"], **{m: round(b[m] / b["n"], 1) for m in ("impressions", "likes", "replies", "bookmarks", "profile_clicks")}}
                      for k, b in by.items()}
    old["followers"] = me.get("public_metrics", {}).get("followers_count")
    old["asof"] = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    STATS.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    # 自分への返信(直近7日)
    r = s.get(f"{API}/tweets/search/recent", params={"query": f"to:{handle} -from:{handle}", "max_results": 50,
                                                     "tweet.fields": "created_at,conversation_id,author_id", "expansions": "author_id",
                                                     "user.fields": "username"})
    reps = []
    if r.ok:
        names = {u["id"]: u["username"] for u in r.json().get("includes", {}).get("users", [])}
        for t in r.json().get("data", []):
            reps.append({"id": t["id"], "at": t["created_at"], "from": names.get(t["author_id"], ""), "text": t["text"],
                         "to": t.get("conversation_id"), "url": f"https://x.com/{names.get(t['author_id'], 'i')}/status/{t['id']}"})
    write_json(REPLIES, {"asof": old["asof"], "handle": handle, "replies": reps})
    print(f"投稿 {len(posts)}件、返信 {len(reps)}件、フォロワー {old['followers']}")
    for k, b in old["by_kind"].items():
        print(k, b)


if __name__ == "__main__":
    main()
