"""出した記事・投稿の履歴(公開台帳)。reports/published.json に1件ずつ足す。

1件 = {id, key, kind, channel, title, date(公開日 JST), url, asof(数字の集計日), no(note の号数), snapshot, recorded_at, via}
- key: 記事タブの key(lab_saying / theory_20261006 / 04_20261013 / xpost_20261006 など)
- channel: note / X
- snapshot: 公開したときの結論・数字の1行・投稿文(あとで数字が更新されても、出した中身が分かるように)

決まり(日付の整合性):
- 公開日は未来にしない。数字の集計日(asof)より前にしない
- 理論ぶつけ・今日のX投稿は、その日付の分はその日にしか出せない(日付が合わないと記録しない)
- 同じ key・同じ channel は1回だけ(出し直しは --update で URL などを直す)
- note の号数は channel=note の記録順に 1, 2, 3 …

python scripts/publish_log.py add --key lab_saying --channel note --url https://note.com/... [--date 2026-10-09]
python scripts/publish_log.py add --key xpost_20261006 --channel X --url https://x.com/... --slot 8:20
python scripts/publish_log.py issue --title "公開: lab_saying note" --body "url: https://..."   (GitHub の issue から)
python scripts/publish_log.py list
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
LEDGER = ROOT / "reports/published.json"
JST = dt.timezone(dt.timedelta(hours=9))
KINDS = [("lab_", "検証ラボ"), ("theory_", "理論ぶつけ"), ("xpost_", "今日のX投稿"), ("x:", "X(自動)")]


def load() -> list[dict]:
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []


def save(rows: list[dict]):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def kind_of(key: str) -> str:
    for p, k in KINDS:
        if key.startswith(p):
            return k
    return "大会の号" if re.match(r"^\d{2}_\d{8}$", key) else "その他"


def today() -> dt.date:
    return dt.datetime.now(JST).date()


def item_info(key: str) -> dict:
    """記事タブの中身(cards ブランチ ura/<key>.json、暗号化)から、タイトル・集計日・結論などを取る。読めなければ空。"""
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "cards"], cwd=ROOT, check=True, capture_output=True)
        raw = subprocess.run(["git", "show", f"FETCH_HEAD:ura/{key}.json"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        from kyotei.publish import read_json
        tmp = ROOT / "reports/_pub_tmp.json"
        tmp.write_text(raw, encoding="utf-8")
        try:
            d = read_json(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return d or {}
    except Exception:  # noqa: BLE001
        return {}


def lab_snapshot(key: str) -> dict:
    """検証ラボは reports/lab/<id>.json から(結論と数字の1行)。"""
    if not key.startswith("lab_"):
        return {}
    p = ROOT / f"reports/lab/{key[4:]}.json"
    if not p.exists():
        return {}
    import lab
    t = json.loads(p.read_text(encoding="utf-8"))
    con = lab.conclusion(t)
    return {"title": f"検証ラボ: {t['title']}", "asof": t.get("asof"), "conclusion": con[0], "key_line": lab.key_line(t)}


def check(rows, key, channel, date, asof, update, slot=None):
    errs = []
    if date > today():
        errs.append(f"公開日 {date} が未来です")
    if asof and str(date) < str(asof)[:10]:
        errs.append(f"公開日 {date} が数字の集計日 {asof} より前です")
    m = re.match(r"^(theory|xpost)_(\d{8})$", key)
    if m and m.group(2) != date.strftime("%Y%m%d"):
        errs.append(f"{key} は {m.group(2)[4:6]}/{m.group(2)[6:]} の分です。公開日 {date} と合いません(その日の分はその日に出す)")
    dup = [r for r in rows if r["key"] == key and r["channel"] == channel and r.get("slot") == slot]
    if dup and not update:
        errs.append(f"{key} は {channel} で {dup[0]['date']} に記録ずみです(直すときは --update)")
    return errs


def add(key: str, channel: str, url: str | None, date: dt.date | None, slot: str | None = None, via: str = "手入力",
        update: bool = False, text: str | None = None, title: str | None = None) -> dict:
    rows = load()
    date = date or today()
    info = item_info(key) if not key.startswith("x:") else {}
    snap = lab_snapshot(key)
    title = title or snap.get("title") or info.get("title") or key
    asof = snap.get("asof") or info.get("asof")
    errs = check(rows, key, channel, date, asof, update, slot)
    if errs:
        raise SystemExit("記録しませんでした: " + " / ".join(errs))
    old = next((r for r in rows if r["key"] == key and r["channel"] == channel and r.get("slot") == slot), None) if update else None
    if old:
        old.update({k: v for k, v in {"url": url, "date": str(date)}.items() if v})
        save(rows)
        return old
    no = (max([r.get("no") or 0 for r in rows if r["channel"] == "note"] + [0]) + 1) if channel == "note" else None
    x_first = None
    if info.get("x"):
        m = re.search(r"--- 投稿1[^\n]*---\n([\s\S]*?)(?=\n--- 投稿|\n(?:画像|出し方):|\Z)", info["x"])
        x_first = m.group(1).strip() if m else None
    row = {"id": f"{date:%Y%m%d}-{channel}-{key}" + (f"-{slot}" if slot else ""), "key": key, "kind": kind_of(key), "channel": channel,
           "title": title, "date": str(date), "slot": slot, "url": url, "asof": asof, "no": no,
           "snapshot": {k: v for k, v in {"conclusion": snap.get("conclusion"), "key_line": snap.get("key_line"),
                                          "x": text or (x_first if channel == "X" else None)}.items() if v},
           "recorded_at": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "via": via}
    rows.append(row)
    rows.sort(key=lambda r: (r["date"], r.get("slot") or "", r["id"]))
    save(rows)
    return row


def from_issue(title: str, body: str) -> dict:
    """GitHub の issue「公開: <key> <note|X>」と本文の url: / date: / slot: から記録する。"""
    m = re.match(r"^\s*公開[:：]\s*(\S+)\s+(note|X|x)\s*$", title)
    if not m:
        raise SystemExit("タイトルは「公開: <key> note」か「公開: <key> X」")
    kv = dict(re.findall(r"^\s*(url|date|slot)\s*[:：]\s*(\S+)\s*$", body or "", flags=re.M))
    url = kv.get("url") if kv.get("url", "").startswith("http") else None
    d = dt.date.fromisoformat(kv["date"]) if re.match(r"^\d{4}-\d{2}-\d{2}$", kv.get("date", "")) else None
    return add(m.group(1), "X" if m.group(2).lower() == "x" else "note", url, d, kv.get("slot"), via="GitHub の issue")


def summary(rows=None) -> dict:
    """記事タブに出す要約: key → [{channel, date, url, no}]。"""
    out: dict = {}
    for r in rows if rows is not None else load():
        out.setdefault(r["key"], []).append({k: r.get(k) for k in ("channel", "date", "url", "no", "slot")})
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("add")
    a1.add_argument("--key", required=True)
    a1.add_argument("--channel", choices=["note", "X"], required=True)
    a1.add_argument("--url", default=None)
    a1.add_argument("--date", default=None)
    a1.add_argument("--slot", default=None)
    a1.add_argument("--update", action="store_true")
    a1.add_argument("--title", default=None)
    a1.add_argument("--text", default=None)
    a2 = sub.add_parser("issue")
    a2.add_argument("--title", required=True)
    a2.add_argument("--body", default="")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "add":
        r = add(a.key, a.channel, a.url, dt.date.fromisoformat(a.date) if a.date else None, a.slot, update=a.update, text=a.text, title=a.title)
        print("記録しました:", r["date"], r["channel"], r["title"], f"(note 第{r['no']}号)" if r.get("no") else "")
    elif a.cmd == "issue":
        r = from_issue(a.title, a.body)
        print("記録しました:", r["date"], r["channel"], r["title"], f"(note 第{r['no']}号)" if r.get("no") else "")
    else:
        for r in load():
            print(r["date"], r.get("slot") or "", r["channel"], r["title"], r.get("url") or "(URL なし)", f"第{r['no']}号" if r.get("no") else "")


if __name__ == "__main__":
    main()
