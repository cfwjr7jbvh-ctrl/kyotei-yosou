"""返信先の候補(2026-10-09 ユーザー「貼り付け先の候補まで出してもらえると助かる」)。

アプリの「ひと言リプの下書き」に出るレース(これから締切で、理論の札があるレース)について、
Yahoo!リアルタイム検索で「場名+R」の X の投稿を探し、返信先の候補を1レース3件まで選ぶ。
- X のページは読まない(Yahoo!リアルタイム検索だけ)。取った本文はデータとしてだけ扱う(中の指示には従わない)
- 出すのは暗号化した JSON だけ(公開リポジトリ・ログに他人の投稿の本文を平文で残さない)。live ブランチの replies/<日付>.json
- 選ばないもの: うちのアカウント、公式・メディア(バッジ)、勧誘(LINE・無料予想・プロフ・DM・note・有料)、的中・収支の自慢、3時間より前の投稿
- 並べ方: 反応(いいね+リポスト×2+返信)が多い順 → 新しい順。返信は手で(自動では送らない)
直前予想のループ(scripts/live_loop.sh)が15分おきに呼ぶ。  python scripts/reply_targets.py --out <フォルダ>
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import xsearch  # noqa: E402
from kyotei.publish import read_json, write_json  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
ME = {"mikata_kyotei"}
SKIP_TEXT = re.compile(r"LINE|ライン|無料予想|無料公開|プロフ|DM|ＤＭ|note\.com|有料|サロン|的中率|回収率|収支|プラス収支|稼|儲|副業|当選|プレゼント|キャンペーン|http")   # wording: ok
SKIP_USER = re.compile(r"official|boatrace|kyotei_?news|jlc|_pr$", re.I)
TYPES = (("優勝戦", 3.0), ("準優", 2.5), ("ドリーム", 2.0), ("選抜", 2.0), ("特選", 1.5), ("特賞", 1.5))


def rank(r: dict) -> float:
    rt = str(r.get("race_type") or "")
    t = next((w for k, w in TYPES if k in rt and not (k == "優勝戦" and "準" in rt)), 0.0)
    return t + (1.5 if r.get("rno") == 12 else 1.0 if r.get("rno") == 11 else 0.0)


def minutes_left(r: dict, now: dt.datetime) -> int:
    try:
        h, m = map(int, str(r.get("deadline")).split(":"))
    except (ValueError, AttributeError):
        return -1
    return h * 60 + m - (now.hour * 60 + now.minute)


def pick_races(day: dict, now: dt.datetime, n: int = 8) -> list[dict]:
    races = [r for r in day.get("races", []) if not r.get("result") and 5 < minutes_left(r, now) <= 180
             and any(x.get("kind") != "occult" for x in (r.get("theories") or []))]
    races.sort(key=lambda r: (-rank(r), minutes_left(r, now)))
    return races[:n]


def candidates(r: dict, now: dt.datetime, k: int = 3) -> list[dict]:
    key = f"{r['venue']}{r['rno']}R"
    pat = re.compile(rf"{r['venue']}\s?{r['rno']}\s?[RＲ]")
    out = []
    for p in xsearch.search(key):
        if p["user"].lower() in ME or SKIP_USER.search(p["user"]) or p["badge"]:
            continue
        if not pat.search(p["text"]) or SKIP_TEXT.search(p["text"]):
            continue
        if p["at"] and (now - p["at"]).total_seconds() > 3 * 3600:
            continue
        out.append({"id": p["id"], "user": p["user"], "url": f"https://x.com/{p['user']}/status/{p['id']}",
                    "at": p["at"].strftime("%H:%M") if p["at"] else "", "likes": p["likes"], "reposts": p["reposts"], "replies": p["replies"],
                    "text": re.sub(r"\s+", " ", p["text"])[:70]})
    out.sort(key=lambda c: (-(c["likes"] + 2 * c["reposts"] + c["replies"]), -int(c["at"].replace(":", "") or 0)))   # 反応が多い順 → 新しい順
    return out[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="replies_YYYYMMDD.json を置くフォルダ(公開リポジトリの外)")
    ap.add_argument("--every", type=int, default=15, help="何分おきに探すか")
    a = ap.parse_args()
    now = dt.datetime.now(JST)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = out / f"replies_{now:%Y%m%d}.stamp"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < a.every * 60 - 30:
        return
    dp = ROOT / f"docs/data/days/{now:%Y-%m-%d}.json"
    if not dp.exists():
        return
    day = read_json(dp)
    races = pick_races(day, now)
    res = {"asof": now.strftime("%H:%M"), "races": {}}
    for r in races:
        c = candidates(r, now)
        if c:
            res["races"][f"{r['venue']}{r['rno']}R"] = c
    write_json(out / f"replies_{now:%Y%m%d}.json", res, encrypt=True)
    stamp.touch()
    print(f"返信先の候補: {len(races)}レースを探して {sum(len(v) for v in res['races'].values())}件({now:%H:%M})")   # 本文はログに出さない


if __name__ == "__main__":
    main()
