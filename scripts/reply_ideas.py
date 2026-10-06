"""今日の返信ネタ(2026-10-07 ユーザー「返信案は毎朝頂戴」)。

新しいアカウントはフォロワーがいないので、投稿より「返信」が読まれる(相手のフォロワーに表示される)。
毎朝、今日の開催場ごとに「相手の話に乗れる数字」を3つまでと、そのまま貼れる返信の文(ミカタの口調、100字前後)を作り、
記事タブ「今日の返信ネタ M/D」に並べる(ura_auto.py から呼ぶ)。数字は検証ラボの JSON と成績データから。買い目・的中・回収率は書かない。

python scripts/reply_ideas.py --day 2026-10-07   (確認用。本番は ura_auto.py)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.theories import VENUES  # noqa: E402
from kyotei.xtext import xlen  # noqa: E402

e = html.escape
LAB = ROOT / "reports/lab"
# 海水・汽水・淡水(潮の話に乗れる場)
SEA = {"江戸川", "平和島", "浜名湖", "常滑", "津", "鳴門", "丸亀", "児島", "宮島", "徳山", "下関", "若松", "芦屋", "福岡", "唐津", "大村"}


def _lab(tid: str) -> dict:
    p = LAB / f"{tid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _pct(v) -> str:
    return "-" if v is None or v != v else f"{round(float(v) * 100)}%"


def venue_numbers(d: pd.DataFrame | None, venue: str, jcd: int, today: dt.date | None = None) -> dict:
    """その場の、相手の話に乗れる数字(逃げ率・万舟はこの1年)。"""
    out: dict = {"venue": venue}
    if d is not None and len(d) and today is not None and "date" in d.columns:
        d = d[pd.to_datetime(d["date"]).dt.date >= today - dt.timedelta(days=365)]
    if d is not None and len(d):
        v1 = d[(d["jcd"] == jcd) & (d["lane"] == 1) & d["finish"].notna()]
        a1 = d[(d["lane"] == 1) & d["finish"].notna()]
        if len(v1) >= 300:
            out["in1"] = float((v1["finish"] == 1).mean())
            out["in1_all"] = float((a1["finish"] == 1).mean())
            byv = d[(d["lane"] == 1) & d["finish"].notna()].groupby("jcd").apply(lambda g: (g["finish"] == 1).mean())
            out["in1_rank"] = int((byv > out["in1"]).sum() + 1)
            out["n_venues"] = int(len(byv))
            if "tri_pop" in d.columns:
                rr = d[(d["jcd"] == jcd) & (d["lane"] == 1)].drop_duplicates("race_id")
                out["upset"] = float((pd.to_numeric(rr["tri_pop"], errors="coerce") >= 30).mean())
                ra = d[d["lane"] == 1].drop_duplicates("race_id")
                out["upset_all"] = float((pd.to_numeric(ra["tri_pop"], errors="coerce") >= 30).mean())
    bg = _lab("bangumi")
    for ti, kind in ((0, "堅い"), (1, "荒れる")):
        tbl = (bg.get("tables") or [[None, []], [None, []]])[ti][1]
        hit = [x for x in tbl if x.get("venue") == venue]
        if hit:
            out[f"bangumi_{kind}"] = [(int(x["rno"]), float(x["in1"])) for x in hit]
    for x in _lab("deme").get("numbers", {}).get("venues", []):
        if x.get("venue") == venue and (x.get("lift_l") or 0) >= 1.2:
            out["deme"] = (x["sig"], float(x["lift_e"]))
    w = _lab("wind")
    for row in (w.get("tables") or [[None, []], [None, []]])[1][1] if len(w.get("tables") or []) > 1 else []:
        if row and row[0] == venue:
            out["wind"] = (row[1], row[2])   # 風2m以下 / 5m以上 の1号艇
    return out


def drafts_for_venue(nums: dict, races: list[dict]) -> list[dict]:
    """返信の文案(100字前後、ミカタの口調)。相手の投稿の種類も添える。"""
    v = nums["venue"]
    out = []
    if "in1" in nums:
        cmp_ = "全国より高め" if nums["in1"] > nums["in1_all"] + 0.02 else ("全国より低め" if nums["in1"] < nums["in1_all"] - 0.02 else "全国と同じくらい")
        out.append({"to": f"公式や予想アカウントの「今日の{v}」の投稿、「{v}行く」の投稿",
                    "text": f"{v}の1号艇の逃げ率はこの1年で{_pct(nums['in1'])}、24場中{nums['in1_rank']}位({cmp_})。"
                            + (f"万舟は{_pct(nums['upset'])}のレースで出てる(全国{_pct(nums['upset_all'])})。" if "upset" in nums else "")
                            + "こういう見方もあるよ📰"})
    if "bangumi_堅い" in nums or "bangumi_荒れる" in nums:
        parts = []
        if "bangumi_堅い" in nums:
            parts.append("・".join(f"{r}R({_pct(p)})" for r, p in nums["bangumi_堅い"][:2]) + "はインが堅い枠")
        if "bangumi_荒れる" in nums:
            parts.append("・".join(f"{r}R({_pct(p)})" for r, p in nums["bangumi_荒れる"][:2]) + "は荒れる枠")
        out.append({"to": f"{v}の特定のレース(番号)の予想の投稿",
                    "text": f"{v}は番組の癖がはっきりしてて、" + "、".join(parts) + "。毎年ほぼ同じ顔ぶれ。番組屋さんの気持ちで読むと面白いよ"})
    if "deme" in nums:
        sig, lift = nums["deme"]
        out.append({"to": f"「{v}の出目」「{v}は荒れる」系の投稿",
                    "text": f"{v}の『らしい出目』は{sig}。全国の{lift:.1f}倍出てて、最近の1年も多いまま。場の顔ってあるんだね"})
    if "wind" in nums:
        try:
            drop = int(nums["wind"][0].rstrip("%")) - int(nums["wind"][1].rstrip("%"))
        except ValueError:
            drop = 0
        if drop >= 6:
            out.append({"to": f"「{v}、今日は風が強い」の投稿(直前情報の風5m以上の日)",
                        "text": f"{v}は風に弱いインの場。1号艇の逃げは風2m以下で{nums['wind'][0]}、5m以上だと{nums['wind'][1]}。風の日は展示から目が離せないね"})
        elif drop <= 2:
            out.append({"to": f"「{v}、今日は風が強い」の投稿(直前情報の風5m以上の日)",
                        "text": f"{v}は風が吹いてもインが崩れにくい場。1号艇の逃げは風2m以下で{nums['wind'][0]}、5m以上でも{nums['wind'][1]}。風より進入と展示を見たいね"})
    # 今日の悩ましいレース(理論ぶつけ)
    conf = [r for r in races if r.get("venue") == v and (r.get("th_sum") or {}).get("conflict")]
    if conf:
        r = conf[0]; sm = r["th_sum"]
        out.append({"to": f"{v}{r['rno']}R(締切{r.get('deadline', '-')})の予想の投稿",
                    "text": f"{v}{r['rno']}Rは理論がぶつかるレース。インに有利: {'・'.join(sm['plus'][:2])}/不利: {'・'.join(sm['minus'][:2])}。どっちに乗る?"})
    if v in SEA:
        out.append({"to": "「満潮だからイン」「干潮だから外」の投稿", "text": f"{v}は海水の場だから潮の話が出るよね。潮でインがどれだけ変わるかは、いま数えてる(近いうちに検証ラボで)。結果が出たら教えに来るね"})
    for x in out:
        if xlen(x["text"]) > 280:
            x["text"] = x["text"][:135] + "…"
    return out[:4]


def build(today: dt.date, races: list[dict], d: pd.DataFrame | None) -> dict | None:
    venues = sorted({(r.get("venue"), r.get("jcd")) for r in races if r.get("venue")}, key=lambda x: x[1] or 0)
    if not venues:
        return None
    blocks = []
    for v, jcd in venues:
        jcd = int(jcd) if jcd is not None else next((k for k, nm in VENUES.items() if nm == v), 0)
        nums = venue_numbers(d, v, jcd, today)
        ds = drafts_for_venue(nums, races)
        if ds:
            blocks.append({"venue": v, "drafts": ds})
    if not blocks:
        return None
    wk = "月火水木金土日"[today.weekday()]
    title = f"今日の返信ネタ {today.month}/{today.day}({wk})"
    lines = [f"【{title}】", "使い方: 公式・予想アカウント・ファンの投稿に、数字をひとつ添えて返信する(1日5〜10件)。文はそのまま貼ってよいし、相手の話に合わせて削ってよい。",
             "返信につける画像は、記事タブの「1枚1ネタ」か、その場の注目選手カード。記事のリンクは本文に入れず、自分の返信にぶら下げる。", ""]
    rows = ""
    for b in blocks:
        lines.append(f"■{b['venue']}")
        rows += f"<section><h3>{e(b['venue'])}</h3>"
        for x in b["drafts"]:
            lines += [f"・返信先: {x['to']}", f"  {x['text']}", ""]
            rows += f"<p class='to'>返信先: {e(x['to'])}</p><pre>{e(x['text'])}</pre>"
        rows += "</section>"
    html_ = (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<style>body{{font-family:sans-serif;margin:16px;line-height:1.7}} pre{{white-space:pre-wrap;background:#f4efdf;padding:12px;font:inherit}} .to{{margin:14px 0 4px;font-size:13px;color:#666}} h3{{margin:20px 0 0;border-left:6px solid #c8141c;padding-left:10px}}</style>"
             f"</head><body><h2>{e(title)}</h2><p>{e(lines[1])}<br>{e(lines[2])}</p>{rows}</body></html>")
    return {"title": title, "html": html_, "note": "\n".join(lines), "x": "\n".join(lines), "n": sum(len(b["drafts"]) for b in blocks)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default=str(ROOT / "out/reply"))
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.day) if a.day else dt.date.today()
    from kyotei.publish import read_json
    dp = ROOT / f"docs/data/days/{day.isoformat()}.json"
    races = read_json(dp).get("races", []) if dp.exists() else []
    from kyotei import racer_card as rc
    d = rc.load_table(since=(day - dt.timedelta(days=400)).strftime("%Y%m"))
    t = build(day, races, d)
    if not t:
        print("今日の開催がありません"); return
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / f"reply_{day:%Y%m%d}.txt").write_text(t["note"], encoding="utf-8")
    (out / f"reply_{day:%Y%m%d}.html").write_text(t["html"], encoding="utf-8")
    print(t["note"])


if __name__ == "__main__":
    main()
