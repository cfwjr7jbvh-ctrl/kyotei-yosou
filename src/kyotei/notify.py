"""期待値100%以上の買い目(本番と、荒れ狙い・検証中)を LINE に送る(LINE Messaging API のプッシュメッセージ)。

- 環境変数 LINE_CHANNEL_TOKEN(チャネルアクセストークン)と LINE_USER_ID(送り先のユーザーID)が無ければ何もしない
- 無料のコミュニケーションプランは月200通まで(超えると送られずエラーになるだけで、料金はかからない)。
  1回の更新で新しく出た買い目は1通にまとめ、1日 LINE_DAILY_MAX 通(既定6)までにする
- 同じ買い目は1回だけ送る。送った記録は data/notify/sent_YYYYMMDD.txt(直前予想ループが live ブランチに一緒に置く)。
  公開リポジトリに買い目が平文で残らないよう、レース番号と組はパスワード付きでハッシュにして書く
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SENT = ROOT / "data/notify"
SITE_URL = os.environ.get("SITE_URL", "https://kyotei-yosou.pages.dev")
API = "https://api.line.me/v2/bot/message/push"


def _key(race_id: str, combo: str) -> str:
    salt = os.environ.get("SITE_PASSWORD", "")
    return hashlib.sha256(f"{salt}|{race_id}|{combo}".encode()).hexdigest()[:16]


def message(races: list[dict], updated_at: str, last: bool = False) -> str:
    lines = [f"【期待値100%超え】{updated_at} 更新"]
    for r in races:
        lines.append("")
        tag = "(荒れ狙い・検証中)" if r.get("kind") == "nerai" else ""
        lines.append(f"{r['venue']} {r['rno']}R(締切 {r.get('deadline') or '?'}){tag}")
        for b in r["bets"]:
            lines.append(f"{b['combo']}  期待値{round(b['ev'] * 100)}%(確率{b['prob'] * 100:.1f}%×{b['odds']:.1f}倍)")
    if any(r.get("kind") == "nerai" for r in races):
        lines += ["", "荒れ狙い = 1号艇が負けそうなレースで、モデルの確率×オッズが100%以上の組。過去12日の検証で回収率125%(偶然の可能性あり、追試中)"]
    lines += ["", SITE_URL]
    if last:
        lines.append("(今日の通知はこれで最後です)")
    return "\n".join(lines)


def push(text: str, token: str, to: str, timeout: float = 15.0) -> tuple[bool, str]:
    body = json.dumps({"to": to, "messages": [{"type": "text", "text": text[:4900]}]}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return True, str(res.status)
    except urllib.error.HTTPError as e:  # 429 = 月の上限、401 = トークン違い
        return False, f"{e.code} {e.read()[:200]!r}"
    except Exception as e:  # noqa: BLE001  通知の失敗で予想の更新を止めない
        return False, repr(e)


def notify_bets(day: dt.date, races: list[dict], now: dt.datetime, ev_min: float = 1.0) -> int:
    """races: 今回更新したレース(アプリと同じ形)。新しく出た買い目があれば1通送る。送った通数を返す。"""
    token, to = os.environ.get("LINE_CHANNEL_TOKEN", ""), os.environ.get("LINE_USER_ID", "")
    if not token or not to:
        return 0
    daily_max = int(os.environ.get("LINE_DAILY_MAX", "6"))
    SENT.mkdir(parents=True, exist_ok=True)
    path = SENT / f"sent_{day.strftime('%Y%m%d')}.txt"
    lines = path.read_text().split() if path.exists() else []
    sent_keys = {x[2:] for x in lines if x.startswith("b:")}
    n_msgs = sum(1 for x in lines if x.startswith("m:"))
    if n_msgs >= daily_max:
        return 0
    picks, keys = [], []
    for r in races:
        if r.get("result") or not r.get("deadline"):
            continue
        hh, mm = map(int, r["deadline"].split(":"))
        if now.replace(hour=hh, minute=mm, second=0, microsecond=0) < now:
            continue  # 締切を過ぎたレースは送らない
        for kind in ("bets", "nerai"):  # 本番の買い目と、荒れ狙い(検証中)
            new = [b for b in r.get(kind) or [] if b.get("ev", 0) >= ev_min
                   and _key(r["race_id"], b["combo"]) not in sent_keys]
            if new:
                picks.append({**r, "bets": new, "kind": kind})
                keys += [_key(r["race_id"], b["combo"]) for b in new]
    if not picks:
        return 0
    picks.sort(key=lambda r: r.get("deadline") or "")
    ok, info = push(message(picks, now.strftime("%H:%M"), last=n_msgs + 1 >= daily_max), token, to)
    print("LINE:", "送信" if ok else "失敗", info, f"{sum(len(r['bets']) for r in picks)}点")
    if not ok:
        return 0
    with path.open("a") as f:
        f.write("".join(f"b:{k}\n" for k in keys) + f"m:{now.strftime('%H%M%S')}\n")
    return 1
