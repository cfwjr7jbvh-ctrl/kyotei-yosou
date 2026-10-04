"""公式の出走表に無い「足の評価」を集める: 記者の直前気配・選手コメント・オリジナル展示・前検タイム。

集める先(2026-10-04 の調査、data/probe/*_summary.json):
  nikkan   日刊スポーツの直前予想(nikkansports.raceyosou.jp)。レースごとに、記者の直前気配(行き足・回り足・ピット離れ・
           モーター評価の記号)、コンピ指数、オリジナル展示(展示・一周・回り足・直線のタイム)、選手コメント(前日など)。
           過去の日も約3か月分さかのぼって見られる(徳山は 2026-07 から)。いまは徳山・びわこがこの形
  comment  場の公式サイトの全選手コメント: 唐津・芦屋(同じ作り、モーター評価の記号つき)、大村(モーターの点数つき)。今節の分だけ
  zenken   場の公式サイトのモーター抽選・前検タイムランキング(同じ作りの14場)。今節の分だけ

方針:
- 文章や記者の評価は著作物なので、公開リポジトリには SITE_PASSWORD で暗号化して置く(data/extra/*.csv.gz.enc)。
  サイトに文章は出さず、学習では点数にしてから使う(著作権法30条の4の情報解析の範囲で使う)
- SITE_PASSWORD を変えるときは、古いパスワードで復号して新しいパスワードで暗号化し直す(scripts/fetch_extra.py rekey)
- アクセスは1つの場につき1秒に1回以下、1回の実行は --time-limit 分まで。取れた件数(文章なし)は data/extra/status.json

python scripts/fetch_extra.py all [--time-limit 40] [--backfill-days 95]
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DIR = ROOT / "data/extra"
STATUS = DIR / "status.json"
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou personal research)"}
JST = dt.timezone(dt.timedelta(hours=9))
NIKKAN = "https://nikkansports.raceyosou.jp/boatrace/"
NIKKAN_SLUGS = {"toda": 2, "hamanako": 6, "tokoname": 8, "tsu": 9, "biwako": 11, "suminoe": 12, "amagasaki": 13, "kojima": 16,
                "tokuyama": 18, "shimonoseki": 19, "wakamatsu": 20, "ashiya": 21, "fukuoka": 22, "karatsu": 23, "omura": 24}
CMS = {1: "https://www.kiryu-kyotei.com", 5: "https://www.boatrace-tamagawa.com", 6: "https://www.boatrace-hamanako.jp",
       8: "https://www.boatrace-tokoname.jp", 9: "https://www.boatrace-tsu.com", 10: "https://www.boatrace-mikuni.jp",
       11: "https://www.boatrace-biwako.jp", 13: "https://www.boatrace-amagasaki.jp", 14: "https://www.n14.jp",
       18: "https://www.boatrace-tokuyama.jp", 19: "https://www.boatrace-shimonoseki.jp", 20: "https://www.wmb.jp",
       21: "https://www.boatrace-ashiya.com", 23: "https://www.boatrace-karatsu.jp"}
COMMENT_CMS = {21: "https://www.boatrace-ashiya.com", 23: "https://www.boatrace-karatsu.jp"}
OMURA = "https://omurakyotei.jp/yosou/comment.php"
_last: dict[str, float] = {}
DEADLINE = [float("inf")]


def now() -> dt.datetime:
    return dt.datetime.now(JST)


def get(url: str) -> str | None:
    host = urllib.parse.urlsplit(url).netloc
    wait = 1.0 - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    for k in range(2):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding
            return r.text
        except Exception:  # noqa: BLE001
            time.sleep(3 + 3 * k)
    return None


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or "").replace(",", ""))
    return float(m.group()) if m else None


def norm_name(s: str) -> str:
    return re.sub(r"[\s　]", "", s or "")


# ---------- 保存(暗号化した月ごとの gzip CSV) ----------
def _key():
    from kyotei.publish import _key as k
    pw = os.environ.get("SITE_PASSWORD", "")
    if not pw:
        raise SystemExit("SITE_PASSWORD が未設定のため保存しません")
    return k(pw)


def load(src: str, ym: str) -> pd.DataFrame | None:
    p = DIR / f"{src}_{ym}.csv.gz.enc"
    if not p.exists():
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    b = p.read_bytes()
    raw = AESGCM(_key()).decrypt(b[:12], b[12:], None)
    return pd.read_csv(io.BytesIO(gzip.decompress(raw)), dtype={"race_id": str})


def save(src: str, rows: list[dict], keys: list[str]) -> int:
    """月ごとに既存分と合わせ、keys が同じ行は新しい方を残す。増えた行数を返す。"""
    if not rows:
        return 0
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    df = pd.DataFrame(rows)
    added = 0
    for ym, g in df.groupby(df["date"].str.replace("-", "").str.slice(0, 6)):
        old = load(src, ym)
        n0 = 0 if old is None else len(old)
        m = g if old is None else pd.concat([old, g], ignore_index=True)
        m = m.drop_duplicates(keys, keep="last")
        added += len(m) - n0
        buf = gzip.compress(m.to_csv(index=False).encode())
        iv = os.urandom(12)
        DIR.mkdir(parents=True, exist_ok=True)
        (DIR / f"{src}_{ym}.csv.gz.enc").write_bytes(iv + AESGCM(_key()).encrypt(iv, buf, None))
    return added


# ---------- 日刊スポーツ(レースごと) ----------
def parse_nikkan(html: str) -> list[dict] | None:
    soup = BeautifulSoup(html, "html.parser")
    head = soup.select_one("table.sign_head")
    st = soup.select_one("table.start_table")
    if head is None:
        return None
    boats = {}
    for tr in head.select("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None or not th.get_text(strip=True).isdigit():
            continue
        m = re.match(r"\s*(\d{4})\s*/\s*([AB][12])\s*(.*)", td.get_text(" ", strip=True))
        if m:
            boats[int(th.get_text(strip=True))] = {"racer_id": int(m.group(1)), "class": m.group(2), "name": norm_name(m.group(3))}
    by_id = {b["racer_id"]: lane for lane, b in boats.items()}
    for tr in soup.select("table.sign_table tr"):
        tds = tr.find_all("td")
        if len(tds) < 7 or "thumb" not in (tds[0].get("class") or []):
            continue
        img = tds[0].find("img")
        m = re.search(r"(\d{4})\.(?:jpg|png)", img.get("src", "") if img else "")
        lane = by_id.get(int(m.group(1))) if m else None
        if lane is None:
            continue
        icons = []
        for td in tds[2:6]:
            el = td.find(class_=re.compile(r"^icon_"))
            icons.append(next((c for c in (el.get("class") or []) if c.startswith("icon_")), None) if el is not None else None)
        boats[lane].update({"k_iki": icons[0], "k_mawari": icons[1], "k_pit": icons[2], "k_motor": icons[3], "compi": num(tds[6].get_text())})
    if st is not None:
        trs = st.select("tr")
        cols = [re.sub(r"\s+", "", th.get_text()) for th in trs[0].find_all("th")] if trs else []
        for course, tr in enumerate(trs[1:7], start=1):
            tds = tr.find_all("td")
            img = tr.find("img")
            m = re.search(r"img_boat(\d)", img.get("src", "") if img else "")
            if not m or int(m.group(1)) not in boats:
                continue
            vals = dict(zip(cols, [td.get_text(strip=True) for td in tds]))
            boats[int(m.group(1))].update({
                "course": course, "sd": vals.get("コース"), "ex_st_raw": vals.get("ST"),
                "o_ex": num(vals.get("展示タイム")), "o_lap": num(vals.get("一周タイム")),
                "o_mawari": num(vals.get("回り足タイム")), "o_straight": num(vals.get("直線タイム"))})
    names = {b["name"]: lane for lane, b in boats.items()}
    for tr in soup.select("table.comment_table tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None:
            continue
        lane = names.get(norm_name(th.get_text()))
        if lane is None:
            continue
        txt = re.sub(r"\s+", " ", td.get_text(" ", strip=True))
        parts = re.split(r"【\s*([^】]{1,8}?)\s*】", txt)
        segs = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
        boats[lane]["c_prev"] = segs.pop("前日", None)
        boats[lane]["c_other"] = " / ".join(f"{k}:{v}" for k, v in segs.items()) or (txt if len(parts) == 1 else None)
    return [{"lane": lane, **b} for lane, b in sorted(boats.items())]


def race_days() -> pd.DataFrame:
    files = sorted((ROOT / "data/history").glob("races_*.csv.gz"))[-5:]
    r = pd.concat([pd.read_csv(p, usecols=["race_id", "date", "jcd", "rno"], dtype={"race_id": str}) for p in files])
    return r.drop_duplicates("race_id")


def nikkan(backfill_days: int, st: dict) -> list[dict]:
    """まだ取っていない (場, 日) を新しい日から。対象の作りでない場は記録して以後飛ばす。"""
    done_p = DIR / "nikkan_done.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    skip_p = DIR / "nikkan_layout.json"  # 場ごとの「この作りのページがあるか」(最後に確かめた日)
    layout = json.loads(skip_p.read_text()) if skip_p.exists() else {}
    rd = race_days()
    today = now().date()
    since = (today - dt.timedelta(days=backfill_days)).isoformat()
    rows = []
    todo = []
    for slug, jcd in NIKKAN_SLUGS.items():
        lay = layout.get(slug)
        if lay and not lay["ok"] and lay["checked"] >= (today - dt.timedelta(days=14)).isoformat():
            continue  # 2週間以内に「この作りではない」と確かめた場
        days = sorted(rd[(rd["jcd"] == jcd) & (rd["date"] >= since) & (rd["date"] < today.isoformat())]["date"].unique(), reverse=True)
        todo += [(d, slug, jcd) for d in days if f"{slug}/{d}" not in done]
    todo.sort(reverse=True)
    st["nikkan_todo"] = len(todo)
    n_pages = 0
    for d, slug, jcd in todo:
        if time.time() > DEADLINE[0]:
            break
        rnos = sorted(rd[(rd["jcd"] == jcd) & (rd["date"] == d)]["rno"].astype(int).unique())
        got = 0
        for rno in rnos:
            html = get(f"{NIKKAN}{slug}/{d.replace('-', '')}/{rno}")
            n_pages += 1
            boats = parse_nikkan(html) if html else None
            if not boats:
                if rno == rnos[0]:
                    break  # 1Rから無い日は、この場はこの作りではない(または過去分が消えている)
                continue
            got += 1
            rid = f"{d.replace('-', '')}{jcd:02d}{rno:02d}"
            rows += [{"race_id": rid, "date": d, "jcd": jcd, "rno": rno, "src": "nikkan", **b} for b in boats]
        if got == 0:
            layout.setdefault(slug, {})
            # 一度も取れたことのない場だけ「作りが違う」とする(過去分が消えた日は単に取れない)
            if not layout[slug].get("ever"):
                layout[slug].update({"ok": False, "checked": today.isoformat()})
        else:
            layout[slug] = {"ok": True, "ever": True, "checked": today.isoformat()}
        done.add(f"{slug}/{d}")
    DIR.mkdir(parents=True, exist_ok=True)
    done_p.write_text("\n".join(sorted(done)) + "\n")
    skip_p.write_text(json.dumps(layout, ensure_ascii=False, indent=1))
    st["nikkan_pages"] = n_pages
    st["nikkan_rows"] = len(rows)
    st["nikkan_fields"] = {k: sum(1 for r in rows if r.get(k) not in (None, "")) for k in
                           ("k_iki", "k_mawari", "k_pit", "k_motor", "compi", "o_ex", "o_lap", "o_mawari", "o_straight", "c_prev", "c_other")}
    st["nikkan_icons"] = sorted({r.get(k) for r in rows for k in ("k_iki", "k_mawari", "k_pit", "k_motor") if r.get(k)})
    return rows


# ---------- 場の公式サイトの全選手コメント ----------
def parse_cms_comment(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one("div.racers_comment table")
    out = []
    if t is None:
        return out
    for tr in t.find_all("tr", recursive=False) or t.select("tr"):
        c1, c2, c3 = tr.select_one("td.col1"), tr.select_one("td.col2"), tr.select_one("td.col3")
        if c1 is None or c3 is None:
            continue
        m = re.match(r"\s*(\d{4})\s*/\s*([AB][12])", c1.get_text(" ", strip=True))
        if not m:
            continue
        marks = [re.search(r"ico-mark-(\d+)", i.get("src", "")) for i in (c2.select("img") if c2 else [])]
        marks = [int(x.group(1)) for x in marks if x]
        sj = re.search(r"素性\s*[:：]\s*(\S)", c2.get_text(" ", strip=True)) if c2 else None
        out.append({"racer_id": int(m.group(1)), "class": m.group(2), "m_deashi": marks[0] if len(marks) > 0 else None,
                    "m_nobi": marks[1] if len(marks) > 1 else None, "sujo": sj.group(1) if sj else None,
                    "text": re.sub(r"\s+", " ", c3.get_text(" ", strip=True))})
    return out


def parse_omura(html: str) -> tuple[str | None, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    out, day = [], None
    for tr in soup.select("table#tblcomment tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        a = tds[3].find("a", href=True)
        m = re.search(r"day=(\d{8}).*?num=(\d{4})", a["href"]) if a else None
        if not m:
            continue
        day = m.group(1)
        mp = re.search(r"(\d+)\s*点\s*(\d+)\s*号機", tds[2].get_text(" ", strip=True))
        out.append({"racer_id": int(m.group(2)), "motor_point": int(mp.group(1)) if mp else None,
                    "motor_no": int(mp.group(2)) if mp else None, "text": re.sub(r"\s+", " ", tds[1].get_text(" ", strip=True))})
    return day, out


def comments(st: dict) -> list[dict]:
    t = now()
    date = t.date().isoformat()
    phase = "am" if t.hour < 15 else "pm"  # 朝 = 前日までのコメント、夜 = その日のレース後のコメント
    rows = []
    for jcd, site in COMMENT_CMS.items():
        html = get(f"{site}/modules/raceinfo/?page=index_racers_comment")
        got = parse_cms_comment(html) if html else []
        seen = set()  # 履歴のポップアップの中の表を拾っても、選手ごとに最初の1行だけ
        got = [x for x in got if not (x["racer_id"] in seen or seen.add(x["racer_id"]))]
        rows += [{"date": date, "phase": phase, "jcd": jcd, "src": "cms", **x} for x in got]
        st[f"comment_{jcd}"] = len(got)
    html = get(OMURA)
    day, got = parse_omura(html) if html else (None, [])
    if day:
        d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        rows += [{"date": d, "phase": phase, "jcd": 24, "src": "omura", **x} for x in got]
    st["comment_24"] = len(got)
    return rows


# ---------- 前検タイム ----------
def parse_timerank(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one("div.tableBlock table")
    out = []
    if t is None:
        return out
    for tr in t.select("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 10 or not re.fullmatch(r"\d{4}", tds[1]):
            continue
        out.append({"racer_id": int(tds[1]), "class": tds[3], "motor_no": num(tds[4]), "motor_2rate": num(tds[5]),
                    "sujo": tds[6] or None, "boat_no": num(tds[7]), "boat_2rate": num(tds[8]), "zenken": num(tds[9]),
                    "zenken_rank": num(tds[0])})
    return out


def zenken(st: dict, jcds: list[int]) -> list[dict]:
    date = now().date().isoformat()
    rows = []
    for jcd in jcds:
        if jcd not in CMS:
            continue
        html = get(f"{CMS[jcd]}/modules/raceinfo/?page=index_timerank")
        got = parse_timerank(html) if html else []
        rows += [{"date": date, "jcd": jcd, **x} for x in got]
        st[f"zenken_{jcd}"] = len(got)
    return rows


def today_jcds() -> list[int]:
    p = ROOT / f"docs/data/days/{now().date().isoformat()}.json"
    try:
        from kyotei.publish import read_json
        return sorted({int(r["jcd"]) for r in read_json(p)["races"]})
    except Exception:  # noqa: BLE001
        return sorted(CMS)


def rekey():
    """SITE_PASSWORD を変えたとき: OLD_SITE_PASSWORD で復号し、SITE_PASSWORD で暗号化し直す。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from kyotei.publish import _key as k
    old, new = k(os.environ["OLD_SITE_PASSWORD"]), k(os.environ["SITE_PASSWORD"])
    for p in sorted(DIR.glob("*.enc")):
        b = p.read_bytes()
        raw = AESGCM(old).decrypt(b[:12], b[12:], None)
        iv = os.urandom(12)
        p.write_bytes(iv + AESGCM(new).encrypt(iv, raw, None))
        print("rekeyed", p.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["all", "nikkan", "comment", "zenken", "rekey"])
    ap.add_argument("--time-limit", type=float, default=40, help="分")
    ap.add_argument("--backfill-days", type=int, default=95)
    a = ap.parse_args()
    if a.what == "rekey":
        return rekey()
    _key()  # パスワードが無ければここで止める
    DEADLINE[0] = time.time() + a.time_limit * 60
    st = {"at": now().isoformat(timespec="minutes")}
    if a.what in ("all", "comment"):
        st["comment_added"] = save("comment", comments(st), ["date", "jcd", "racer_id", "text"])
    if a.what in ("all", "zenken"):
        st["zenken_added"] = save("zenken", zenken(st, today_jcds()), ["date", "jcd", "racer_id"])
    if a.what in ("all", "nikkan"):
        st["nikkan_added"] = save("nikkan", nikkan(a.backfill_days, st), ["race_id", "lane"])
    hist = json.loads(STATUS.read_text()) if STATUS.exists() else []
    hist = (hist + [st])[-60:]
    STATUS.write_text(json.dumps(hist, ensure_ascii=False, indent=1))
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
