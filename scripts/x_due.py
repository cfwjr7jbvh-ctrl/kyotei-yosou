"""X の投稿で「出す時間が来たのに、まだ出ていないもの」を見つける(直前予想のループが5分ごとに呼ぶ)。

GitHub の定期実行は遅れたり飛んだりする(30分おきに間引かれる・1時間半遅れる日もある)ので、
5分ごとに動いている直前予想のループ(scripts/live_loop.sh)から見回り、出すものがあれば x_post.yml を起動する。
x_post.yml は同じグループで1本ずつ動き、出したら reports/x_drafts/posted.json に記録するので、二重には出ない。

python scripts/x_due.py STATE_FILE   → 起動する what(theory / morning / neta / evening / poll / event)を1行ずつ出す

- 決まった時間の投稿: 予定の8分後を過ぎてもまだ出ていなければ起動。遅れすぎたら出さない(理論ぶつけは12時まで、など)
- ミカタ新聞: 出す時間 ≦ 今 < 締切の15分前 で、まだ出していないもの
- 同じ what は12分以内に2回起動しない(STATE_FILE に起動した時刻を残す)
- 変数 X_AUTOPOST が "1" のときだけ(直前予想のジョブには変数が無いので、x_post の最後の記録で判断)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
JST = dt.timezone(dt.timedelta(hours=9))
# 決まった時間の投稿と、これより遅れたら出さない時刻
LATE = {"theory": ("8:20", "12:00"), "morning": ("12:10", "14:30"), "neta": ("15:30", "19:00"), "hayami": ("18:00", "19:45"),
        "evening": ("20:00", "22:30"), "poll": ("21:30", "23:30")}
EVENT_CUTOFF_MIN = 15


def hm(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def main():
    ap = os.environ.get("X_AUTOPOST")
    if ap is None:   # 直前予想のジョブには変数が無いので、x_post の最後の記録(「自動投稿: ON」)で判断
        logs = [ROOT / "reports/x_drafts/last_run.txt", ROOT / "reports/x_drafts/last_event.txt"]
        ap = "1" if any(p_.exists() and "自動投稿: ON" in p_.read_text(encoding="utf-8") for p_ in logs) else "0"
    if ap != "1":
        return
    state_p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports/x_drafts/_due_state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    import x_post
    now = dt.datetime.now(JST)
    day = now.strftime("%Y-%m-%d")
    t = now.hour * 60 + now.minute
    posted = json.loads((ROOT / "reports/x_drafts/posted.json").read_text(encoding="utf-8")) \
        if (ROOT / "reports/x_drafts/posted.json").exists() else {}
    q = x_post.queue(day)
    due = []
    # ミカタ新聞
    for it in q:
        if not str(it.get("label", "")).startswith(("新聞:", "大会:")) or not it.get("deadline"):
            continue
        if posted.get(f"event:{it['label']}") == day:
            continue
        if hm(it["time"]) <= t < hm(it["deadline"]) - EVENT_CUTOFF_MIN:
            due.append("event")
            break
    # 決まった時間の投稿
    times = {it.get("time") for it in q}
    for what, (at, until) in LATE.items():
        if posted.get(what) == day:
            continue
        if what != "morning" and at not in times:   # 記事タブに今日のその時間の投稿が無い
            continue
        if hm(at) + 8 <= t <= hm(until):
            due.append(what)
    out = []
    for w in due:
        last = state.get(w)
        if last and (now - dt.datetime.fromisoformat(last)).total_seconds() < 12 * 60:
            continue
        state[w] = now.isoformat()
        out.append(w)
    state_p.write_text(json.dumps(state))
    print("\n".join(out))


if __name__ == "__main__":
    main()
