"""市場の言葉を毎朝数える(X で読まれている言葉・検索されている言葉・ニュースの見出し)。

ユーザーの指示(2026-10-06): 「X の競艇関係の検索ワードで人気を把握して、読者が欲しがっている情報を出そう」「毎日分析!」
X は API で読めない(投稿専用)ので、X の投稿を検索できる Yahoo!リアルタイム検索と、note・公式ニュース・Google ニュースの RSS を読む。
GitHub Actions(market.yml、毎朝 6:05 JST)で動かす。作業環境からは外のサイトに出られない。

出すもの(公開リポジトリなので、投稿の本文はそのまま残さない。残すのは言葉の回数と、ニュースの見出し・URL だけ):
  reports/market/YYYY-MM-DD.json  … 言葉の上位(全体・場名・選手名・用語・ハッシュタグ)、前日との差、新顔、ニュースの見出し
  reports/market/latest.json      … 同じ中身(x_post.py / ura_auto.py が今日の言葉を読むため)
  reports/market/YYYY-MM-DD.md    … 人に読ませる1枚(人気の分析に貼る)

python scripts/market_words.py                 # 今日
python scripts/market_words.py --day 2026-10-06 --no-fetch   # 取りに行かず、保存してある生データ(あれば)から集計だけ
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.parse
from collections import Counter

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.theories import VENUES  # noqa: E402

OUT = ROOT / "reports/market"
JST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou market research; personal use)", "Accept-Language": "ja"}

# いつも見る言葉(X の投稿・見出しの中で数える)。予想屋の投稿でよく使われる言葉を中心に
TERMS = ["予想", "無料予想", "本命", "穴", "中穴", "大穴", "万舟", "的中", "回収率", "舟券", "3連単", "2連単", "ワイド", "展示", "展示タイム", "スタート",
         "ST", "フライング", "モーター", "進入", "前づけ", "前付け", "イン", "逃げ", "まくり", "差し", "まくり差し", "カド", "ダッシュ", "スロー",
         "節一", "伸び", "出足", "回り足", "足", "気配", "優勝戦", "準優", "ドリーム", "初日", "最終日", "SG", "G1", "G2", "G3", "一般戦", "ナイター",
         "ミッドナイト", "直前", "締切", "払戻", "結果", "荒れ", "堅い", "鉄板", "勝負", "勝負レース", "見解", "買い目", "オッズ", "人気", "級別", "A1",
         "B1", "新燃料", "E30", "返還", "欠場", "事故", "転覆", "周年", "地元", "引退", "デビュー", "初優勝", "女子", "レディース", "ヴィーナス"]
HASHTAG = re.compile(r"#([^\s#＃　]+)")
JP_WORD = re.compile(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{1,}")   # ひらがな(助詞)で切れるので、漢字・カタカナの連なりだけ
STOP = {"ボートレース", "競艇", "こと", "これ", "それ", "ため", "よう", "さん", "ので", "から", "まで", "です", "ます", "した", "して", "いる", "ある",
        "する", "なる", "本日", "今日", "明日", "昨日", "みなさん", "皆さん", "ください", "ありがとう", "ございます", "おはよう", "https", "http", "com", "jp"}
_last = [0.0]


def _get(url: str, timeout: int = 20) -> str | None:
    """1秒に1回以下で取りに行く。だめなら None(ほかの取り込みを止めない)。"""
    wait = 1.2 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.ok:
            return r.text
        print("取れませんでした:", r.status_code, url[:90])
    except requests.RequestException as ex:
        print("取れませんでした:", type(ex).__name__, url[:90])
    return None


def _strip(html: str) -> str:
    html = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html)
    txt = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", urllib.parse.unquote(txt))


# ---------------------------------------------------------------- 取り込み
def yahoo_realtime(q: str) -> list[str]:
    """Yahoo!リアルタイム検索(X の投稿の検索)。投稿の本文らしい文字列の一覧(数えるためだけに使い、保存しない)。"""
    html = _get(f"https://search.yahoo.co.jp/realtime/search?p={urllib.parse.quote(q)}&ei=UTF-8")
    if not html:
        return []
    posts: list[str] = []
    # 1) ページに埋め込まれた JSON(__NEXT_DATA__ など)から "text" を拾う
    for m in re.finditer(r'"(?:text|displayText|body)"\s*:\s*"((?:[^"\\]|\\.){10,600})"', html):
        try:
            posts.append(json.loads(f'"{m.group(1)}"'))
        except json.JSONDecodeError:
            pass
    # 2) だめなら本文のタグを外した文字列から、競艇の言葉を含む行だけ
    if len(posts) < 5:
        txt = _strip(html)
        posts += [s for s in re.split(r"[。\n]|(?<=\S) {2,}", txt) if ("競艇" in s or "ボート" in s) and 10 <= len(s) <= 300]
    seen, out = set(), []
    for p in posts:
        k = p[:40]
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def google_news(q: str) -> list[dict]:
    """Google ニュースの RSS(見出し・URL・時刻)。"""
    xml = _get(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=ja&gl=JP&ceid=JP:ja")
    if not xml:
        return []
    out = []
    for it in re.finditer(r"<item>([\s\S]*?)</item>", xml):
        b = it.group(1)
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", b)
        u = re.search(r"<link>(.*?)</link>", b)
        d = re.search(r"<pubDate>(.*?)</pubDate>", b)
        if t:
            out.append({"title": re.sub(r"\s+", " ", t.group(1)).strip(), "url": (u.group(1).strip() if u else ""), "at": (d.group(1) if d else "")})
    return out[:40]


def note_hashtag(tag: str) -> list[dict]:
    """note の #競艇 の新着(API)。見出しと URL、スキ数。"""
    txt = _get(f"https://note.com/api/v3/hashtags/{urllib.parse.quote(tag)}/notes?order=new&page=1")
    if not txt:
        return []
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        return []
    notes = (((d.get("data") or {}).get("notes")) or []) if isinstance(d, dict) else []
    out = []
    for n in notes[:40]:
        out.append({"title": n.get("name") or "", "url": f"https://note.com/{(n.get('user') or {}).get('urlname', '')}/n/{n.get('key', '')}",
                    "likes": n.get("likeCount") or n.get("like_count") or 0, "price": n.get("price") or 0})
    return out


def boatrace_news() -> list[dict]:
    """公式サイトのニュース一覧(見出し・URL)。"""
    html = _get("https://www.boatrace.jp/owpc/pc/site/news/")
    if not html:
        return []
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(/owpc/pc/site/news/\d{4}/\d{2}/\d+/?)"[^>]*>([\s\S]*?)</a>', html):
        t = re.sub(r"\s+", " ", _strip(m.group(2))).strip()
        if t and m.group(1) not in seen and len(t) >= 6:
            seen.add(m.group(1))
            out.append({"title": t[:80], "url": "https://www.boatrace.jp" + m.group(1)})
    return out[:30]


# ---------------------------------------------------------------- 数える
def racer_names() -> set[str]:
    """最近3か月に走った選手の名前(スペースなし)。X の投稿の中で数える。"""
    import gzip
    names: set[str] = set()
    files = sorted((ROOT / "data/history").glob("entries_*.csv.gz"))[-3:]
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                head = f.readline().rstrip("\n").split(",")
                if "racer_name" not in head:
                    continue
                i = head.index("racer_name")
                for line in f:
                    cols = line.rstrip("\n").split(",")
                    if len(cols) > i and cols[i]:
                        names.add(cols[i].replace("　", "").replace(" ", ""))
        except OSError:
            pass
    return names


def count_words(texts: list[str], names: set[str]) -> dict:
    """言葉の回数: 全体(2文字以上の語)・場名・選手名・用語・ハッシュタグ。"""
    allw: Counter = Counter()
    venues: Counter = Counter()
    racers: Counter = Counter()
    terms: Counter = Counter()
    tags: Counter = Counter()
    vn = sorted(VENUES.values(), key=len, reverse=True)
    names_l = [n for n in names if len(n) >= 3]   # 2文字の名前は一般の言葉とまぎれるので数えない
    for t in texts:
        t2 = t.replace("　", " ")
        for h in HASHTAG.findall(t2):
            tags[h[:30]] += 1
        for w in JP_WORD.findall(t2):
            if w in STOP or len(w) > 20:
                continue
            allw[w] += 1
        for v in vn:   # 場名・選手名・用語は、文の中にあれば数える(1投稿1回)
            if v in t2:
                venues[v] += 1
        for n in names_l:
            if n in t2:
                racers[n] += 1
        for k in TERMS:
            if k in t2:
                terms[k] += 1
    return {"all": allw.most_common(80), "venues": venues.most_common(24), "racers": racers.most_common(30), "terms": terms.most_common(60),
            "hashtags": tags.most_common(40)}


def diff_prev(day: dt.date, cur: dict) -> dict:
    """前の日との差(回数が増えた言葉・新顔)。"""
    prev_p = OUT / f"{(day - dt.timedelta(days=1)).isoformat()}.json"
    if not prev_p.exists():
        return {}
    try:
        prev = json.loads(prev_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    pa = dict(prev.get("words", {}).get("all", []))
    ca = dict(cur.get("all", []))
    up = sorted(((w, c - pa.get(w, 0)) for w, c in ca.items()), key=lambda x: -x[1])[:20]
    new = [w for w, c in cur.get("all", []) if w not in pa and c >= 3][:20]
    return {"up": up, "new": new}


# ---------------------------------------------------------------- 本体
def collect(day: dt.date, queries: list[str]) -> dict:
    texts: list[str] = []
    per_q: dict = {}
    for q in queries:
        ps = yahoo_realtime(q)
        per_q[q] = len(ps)
        texts += ps
    news = google_news("競艇 OR ボートレース")
    notes = note_hashtag("競艇")
    official = boatrace_news()
    return {"texts": texts, "per_query": per_q, "news": news, "notes": notes, "official": official}


def today_queries(day: dt.date) -> list[str]:
    """いつもの言葉+今日の開催場(その日の予想のファイルがあれば)。"""
    qs = ["競艇", "ボートレース", "競艇 予想", "万舟", "ボートレース 予想"]
    try:
        from kyotei.publish import read_json
        dp = ROOT / f"docs/data/days/{day.isoformat()}.json"
        if dp.exists():
            vs = sorted({r.get("venue") for r in read_json(dp).get("races", []) if r.get("venue")})
            qs += [f"{v} 競艇" for v in vs[:8]]
    except Exception as ex:  # noqa: BLE001
        print("今日の開催場は読めませんでした:", ex)
    return qs


def summarize_md(day: dt.date, rep: dict) -> str:
    w = rep["words"]
    def top(lst, n, fmt=lambda k, c: f"{k}({c})"):
        return "、".join(fmt(k, c) for k, c in lst[:n]) or "-"
    lines = [f"# 市場の言葉 {day.isoformat()}", "",
             f"- 読んだ X の投稿(Yahoo!リアルタイム検索): {rep['n_posts']}本 / 検索した言葉: {', '.join(f'{k}:{v}' for k, v in rep['per_query'].items())}",
             f"- よく出る言葉: {top(w['all'], 25)}",
             f"- 用語: {top(w['terms'], 20)}",
             f"- 場名: {top(w['venues'], 10)}",
             f"- 選手名: {top(w['racers'], 12)}",
             f"- ハッシュタグ: {top(w['hashtags'], 15, lambda k, c: f'#{k}({c})')}"]
    d = rep.get("diff") or {}
    if d:
        lines += [f"- 前日より増えた: {top(d.get('up', []), 12, lambda k, c: f'{k}(+{c})')}", f"- 新顔: {'、'.join(d.get('new', [])[:12]) or '-'}"]
    lines += ["", "## ニュースの見出し(Google ニュース)"] + [f"- {x['title']}" + (f" {x['url']}" if x.get("url") else "") for x in rep["news"][:15]]
    lines += ["", "## 公式のお知らせ"] + [f"- {x['title']} {x['url']}" for x in rep["official"][:10]]
    lines += ["", "## note の #競艇 新着(スキ数)"] + [f"- {x['title']}({x.get('likes', 0)}) {x['url']}" for x in rep["notes"][:12]]
    lines += ["", "## 今日の題材に(自動の下書き)",
              f"- 場: {top(w['venues'], 3, lambda k, c: k)} / 選手: {top(w['racers'], 3, lambda k, c: k)} / 言葉: {top(w['terms'], 5, lambda k, c: k)}",
              "- 投稿の1行目は、上の『用語』の上位の言葉を使う(例: 逃げ率・ST・展示)。注目の選手名があれば、その人の『◯コースの◯◯』を推し選手カードに"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--no-fetch", action="store_true", help="取りに行かない(保存した raw があれば集計だけ)")
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.day) if a.day else dt.datetime.now(JST).date()
    OUT.mkdir(parents=True, exist_ok=True)
    raw_p = OUT / f"_raw_{day.isoformat()}.json"   # 投稿の本文は公開リポジトリに残さない(.gitignore)。その日の作業用だけ
    if a.no_fetch and raw_p.exists():
        raw = json.loads(raw_p.read_text(encoding="utf-8"))
    else:
        raw = collect(day, today_queries(day))
        raw_p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    names = racer_names()
    texts = raw["texts"] + [x["title"] for x in raw["news"]] + [x["title"] for x in raw["notes"]] + [x["title"] for x in raw["official"]]
    words = count_words(texts, names)
    rep = {"day": day.isoformat(), "made": dt.datetime.now(JST).isoformat(timespec="minutes"), "n_posts": len(raw["texts"]), "per_query": raw["per_query"],
           "words": words, "news": raw["news"], "official": raw["official"], "notes": raw["notes"]}
    rep["diff"] = diff_prev(day, words)
    (OUT / f"{day.isoformat()}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{day.isoformat()}.md").write_text(summarize_md(day, rep), encoding="utf-8")
    print(f"X の投稿 {len(raw['texts'])}本 / ニュース {len(raw['news'])} / 公式 {len(raw['official'])} / note {len(raw['notes'])}")
    print("用語:", words["terms"][:12])
    print("場名:", words["venues"][:6], "選手:", words["racers"][:6])


if __name__ == "__main__":
    main()
