"""X の反応を自動で取る(自分の投稿の表示回数・いいね・返信・ブックマーク・プロフィールのクリック と、自分への返信)。

python scripts/x_stats.py            # 鍵があれば取る。無ければ何もしない
→ reports/x_stats.json(平文。投稿の種類ごとの平均と、投稿ごとの数字。文章は先頭だけ)
→ docs/data/x_replies.json(暗号化。自分への返信の一覧。アプリの「記事」タブに「返信待ち」として出す)

料金(2026年、従量課金): 自分のデータの読み取り $0.001/件、他人の投稿(返信)の読み取り $0.005/件。
毎日23:50に直近50投稿(月 $1.5 ほど)+月・木だけ返信50件(月 $2 ほど)。
投稿の種類は、出した記録(reports/published.json の時間帯)から。記録が無い投稿だけ文章の先頭で判定。
種類ごとに: 表示回数(インプレッション)・反応(いいね+返信+リポスト+ブックマーク)÷表示・1000表示あたりのプロフィールのクリック。
フォロワー数は取るたびに履歴に残す(フォローが増えた投稿は API では分からないので、期間の増え方と見比べる)。投票は票数も。
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


SLOT_KIND = {"8:20": "8:20 理論ぶつけ", "12:10": "12:10 荒れそうなレース", "15:30": "15:30 1枚1ネタ", "18:00": "18:00 早見表", "13:00": "13:00 注目選手(昼)", "21:30": "21:30 投票"}
KIND = [("【ミカタ速報】", "ミカタ速報"), ("【ミカタ新聞】", "ミカタ新聞"), ("今日の悩ましいレース", "8:20 理論ぶつけ"), ("【今日の理論ぶつけ】", "8:20 理論ぶつけ"), ("今日の荒れそうなレース", "12:10 荒れそうなレース"),
        ("昨日の投票の答え", "15:30 1枚1ネタ"), ("【明日答えます】", "21:30 投票"), ("#今日の理論ぶつけ", "大会の締切前"),
        ("検証ラボ", "20:00 検証ラボ"), ("の注目選手", "20:00 注目選手カード")] + KIND


def published_kinds() -> dict:
    """出した記録から、投稿の id → 種類。"""
    p = ROOT / "reports/published.json"
    out = {}
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    for r in rows:
        if r.get("channel") != "X" or not r.get("url") or "/status/" not in r["url"]:
            continue
        tid = r["url"].rstrip("/").split("/status/")[-1].split("?")[0]
        sl = r.get("slot") or ""
        if r["key"].startswith("x:pinned"):
            k = "固定ポスト"
        elif sl in SLOT_KIND:
            k = SLOT_KIND[sl]
        elif sl == "20:00":
            k = "20:00 検証ラボ" if "検証ラボ" in ((r.get("snapshot") or {}).get("x") or "") or r["key"].startswith("lab_") else "20:00 注目選手カード"
        elif sl.startswith("大会"):
            k = "大会の締切前"
        elif sl.startswith("新聞"):
            k = "ミカタ新聞"
        elif r["key"].startswith("lab_"):
            k = "検証ラボ(手で)"
        else:
            k = None
        if k:
            out[tid] = k
    return out


def kind_of(text: str, tid: str | None = None, pk: dict | None = None) -> str:
    if pk and tid in pk:
        return pk[tid]
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
                                                   "tweet.fields": "created_at,public_metrics,non_public_metrics,attachments",
                                                   "expansions": "attachments.poll_ids,attachments.media_keys", "poll.fields": "options,voting_status",
                                                   "media.fields": "type"})
    r.raise_for_status()
    posts = r.json().get("data", [])
    polls = {p["id"]: p for p in r.json().get("includes", {}).get("polls", [])}
    mtype = {m["media_key"]: m.get("type") for m in r.json().get("includes", {}).get("media", [])}   # 動画か画像か(費用対効果の比べ用)
    pk = published_kinds()
    old = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {"posts": {}}
    for p in posts:
        pm, npm = p.get("public_metrics", {}), p.get("non_public_metrics", {})
        pid = ((p.get("attachments") or {}).get("poll_ids") or [None])[0]
        at_jst = dt.datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")).astimezone(JST)
        ts = {mtype.get(k) for k in (p.get("attachments") or {}).get("media_keys") or []}
        media = "video" if ts & {"video", "animated_gif"} else "image" if "photo" in ts else "text"
        old["posts"][p["id"]] = {"at": p["created_at"], "jst": at_jst.strftime("%m/%d %H:%M"), "kind": kind_of(p["text"], p["id"], pk), "head": p["text"][:40],
                                 "media": media,
                                 **({"poll": {o["label"]: o["votes"] for o in polls[pid]["options"]}} if pid in polls else {}),
                                 "impressions": pm.get("impression_count"), "likes": pm.get("like_count"), "replies": pm.get("reply_count"),
                                 "reposts": pm.get("retweet_count"), "bookmarks": pm.get("bookmark_count"),
                                 "profile_clicks": npm.get("user_profile_clicks"), "link_clicks": npm.get("url_link_clicks")}
    by = {}
    M = ("impressions", "likes", "replies", "reposts", "bookmarks", "profile_clicks", "votes")
    for v in old["posts"].values():
        v["votes"] = sum((v.get("poll") or {}).values()) if v.get("poll") else 0
        b = by.setdefault(v["kind"], {"n": 0, **{m: 0 for m in M}})
        b["n"] += 1
        for k in M:
            b[k] += v.get(k) or 0
    old["by_kind"] = {}
    for k, b in sorted(by.items(), key=lambda kv: -kv[1]["impressions"] / max(kv[1]["n"], 1)):
        imp = max(b["impressions"], 1)
        old["by_kind"][k] = {"n": b["n"], **{m: round(b[m] / b["n"], 1) for m in M},
                             "react_pct": round((b["likes"] + b["replies"] + b["reposts"] + b["bookmarks"] + b["votes"]) / imp * 100, 2),
                             "profile_per_1000": round(b["profile_clicks"] / imp * 1000, 1)}
    # 同じ種類の中で、動画・画像・文字だけをくらべる(2026-10-08 ユーザー「アニメーションの方が伸びるならそっちで、費用対効果考えてな」)
    bm: dict = {}
    for v in old["posts"].values():
        if not v.get("media"):
            continue
        b = bm.setdefault(v["kind"], {}).setdefault(v["media"], {"n": 0, "impressions": 0, "react": 0, "profile_clicks": 0, "imps": []})
        b["n"] += 1
        b["impressions"] += v.get("impressions") or 0
        b["imps"].append(v.get("impressions") or 0)
        b["react"] += sum(v.get(k) or 0 for k in ("likes", "replies", "reposts", "bookmarks", "votes"))
        b["profile_clicks"] += v.get("profile_clicks") or 0
    old["by_kind_media"] = {k: {m: {"n": b["n"], "impressions_median": sorted(b["imps"])[len(b["imps"]) // 2],
                                    "react_pct": round(b["react"] / max(b["impressions"], 1) * 100, 2),
                                    "profile_per_1000": round(b["profile_clicks"] / max(b["impressions"], 1) * 1000, 1)} for m, b in ms.items()}
                            for k, ms in bm.items() if len(ms) > 1}
    # 出した時間帯ごと(何時に出すと見られるか。ミカタ新聞の時間を決める材料)
    bh: dict = {}
    for v in old["posts"].values():
        h = (v.get("jst") or " 00:00").split(" ")[-1][:2]
        b = bh.setdefault(h, {"n": 0, "impressions": 0, "profile_clicks": 0})
        b["n"] += 1
        b["impressions"] += v.get("impressions") or 0
        b["profile_clicks"] += v.get("profile_clicks") or 0
    old["by_hour"] = {h: {"n": b["n"], "impressions": round(b["impressions"] / b["n"], 1),
                          "profile_per_1000": round(b["profile_clicks"] / max(b["impressions"], 1) * 1000, 1)} for h, b in sorted(bh.items())}
    old["followers"] = me.get("public_metrics", {}).get("followers_count")
    old["asof"] = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    hist = old.setdefault("followers_hist", [])
    if not hist or hist[-1]["at"] != old["asof"]:
        hist.append({"at": old["asof"], "followers": old["followers"], "posts": me.get("public_metrics", {}).get("tweet_count")})
    # 自分への返信(直近7日)。他人の投稿の読み取りは高いので月・木だけ(返信そのものは X の通知で見られる)
    reps = None
    if dt.datetime.now(JST).weekday() in (0, 3) or "--replies" in sys.argv:
        reps = replies(s, handle, old["asof"])
    prev = old["followers_hist"][-2] if len(old["followers_hist"]) >= 2 else None
    STATS.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"フォロワー {old['followers']}" + (f"({prev['at']} から {old['followers'] - (prev['followers'] or 0):+d})" if prev else "") +
          f" / 投稿 {len(posts)}件" + (f" / 自分への返信 {len(reps)}件" if reps is not None else ""))
    print("種類 | 本数 | 平均の表示 | 反応率 | 1000表示あたりプロフィールへ | 平均の返信 | 平均の票")
    for k, b in old["by_kind"].items():
        print(f"{k} | {b['n']} | {b['impressions']} | {b['react_pct']}% | {b['profile_per_1000']} | {b['replies']} | {b['votes']}")
    for k, ms in old["by_kind_media"].items():
        print(f"{k}: " + " / ".join(f"{m} {b['n']}本 表示の中央値{b['impressions_median']} 反応率{b['react_pct']}% プロフィールへ{b['profile_per_1000']}" for m, b in ms.items()))
    print("出した時 | 本数 | 平均の表示 | 1000表示あたりプロフィールへ")
    for h, b in old["by_hour"].items():
        print(f"{h}時 | {b['n']} | {b['impressions']} | {b['profile_per_1000']}")


def replies(s, handle, asof):
    r = s.get(f"{API}/tweets/search/recent", params={"query": f"to:{handle} -from:{handle}", "max_results": 50,
                                                     "tweet.fields": "created_at,conversation_id,author_id", "expansions": "author_id",
                                                     "user.fields": "username"})
    reps = []
    if r.ok:
        names = {u["id"]: u["username"] for u in r.json().get("includes", {}).get("users", [])}
        for t in r.json().get("data", []):
            reps.append({"id": t["id"], "at": t["created_at"], "from": names.get(t["author_id"], ""), "text": t["text"],
                         "to": t.get("conversation_id"), "url": f"https://x.com/{names.get(t['author_id'], 'i')}/status/{t['id']}"})
    write_json(REPLIES, {"asof": asof, "handle": handle, "replies": reps})
    return reps


if __name__ == "__main__":
    main()
