"""データ台帳: 何のデータを、いつからいつまで持っているか。集める仕組みと、さかのぼれるか。待っているアイデアは何がそろえば検証できるか。

2026-10-07 ユーザー「新たなモデルのアイディアを探し、検証に追加のデータが必要なら収集をはじめ、過去に遡及して集められるなら集めるサイクルは?」
→ アイデアとデータをつなぐ表。毎週(data_catalog.yml)と、毎朝の改善サイクルが読む。

  python scripts/data_catalog.py      → reports/data_catalog.md と reports/data_catalog.json
新しいデータを集め始めたら DATASETS に、データ待ちのアイデアは WAITING に1行足す。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 名前, ファイル(glob), 集める仕組み(ワークフロー), さかのぼれるか, 中身, 出どころ・決まり
DATASETS = [
    ("成績・出走表", "data/history/entries_*.csv.gz", "daily.yml / history.yml", "○ 公式は2002年〜(いまは2023-10〜)", "全レースの出走表と着順・ST・展示タイム", "公式(BOAT RACE)"),
    ("払戻・レース結果", "data/history/races_*.csv.gz", "daily.yml / history.yml", "○", "3連単などの払戻・人気・決まり手", "公式"),
    ("決まり手", "data/kimarite/kimarite_*.csv.gz", "kimarite.yml", "○", "", "公式"),
    ("直前情報(展示・チルト・体重)", "data/previews/previews_*.csv.gz", "previews.yml / live.yml", "○ 公式の直前情報ページは過去日も残る", "展示タイム・展示の進入とST・チルト・当日体重・気象", "公式"),
    ("3連単の確定オッズ", "data/odds/odds3t_*.csv.gz", "odds.yml(毎晩少しずつさかのぼる)", "○ 公式のオッズページは過去日も残る", "120通りの確定オッズ", "公式"),
    ("締切前オッズ", "data/odds_live/live_*.csv.gz", "live.yml(直前予想のループ)", "× その場でしか取れない(10/4〜)", "締切に近い取得と早い取得", "公式"),
    ("公式コンピュータ予想", "data/pcexpect/pcx_*.csv.gz", "pcexpect.yml(さかのぼり中)", "○", "印・自信度・フォーカス", "公式"),
    ("天気(過去)", "data/weather/archive.csv.gz", "weather_hist.yml", "○ Open-Meteo の過去分", "1時間ごとの気圧・湿度・気温・風・雨", "Open-Meteo(CC BY 4.0)"),
    ("天気予報", "data/weather/forecast_*.csv.gz", "weather.yml", "× その日の予報はその日だけ", "レース時刻の予報", "Open-Meteo"),
    ("潮位", "data/tide/tide_*.csv.gz", "tide.yml(月1)", "○ 天文潮の推算なので何年でも", "毎時の潮位・満潮干潮の時刻と高さ", "気象庁 潮位表"),
    ("記者の評価・コメント・前検", "data/extra/*.enc", "extra.yml(毎日2回)", "△ 日刊の直前予想は約3か月前まで", "行き足などの記号・コメント・前検タイム(暗号化)", "日刊スポーツ・各場(読むだけの決まりを守る)"),
    ("あっせん(出場予定)", "data/assen/assen_*.json", "assen.yml", "×", "これからの出場予定", "公式"),
    ("選手の期別成績", "data/racers/*", "racers.yml(5月・11月)", "○ 公式は2002年〜", "期ごとの勝率・コース別など", "公式(ファン手帳)"),
]

# データを待っているアイデア: id, 中身, 必要なデータ(DATASETS の名前), そろう条件(人が読む), 判定(データの量から自動)
WAITING = [
    ("tide", "検証ラボ: 満潮はイン、干潮は外", "潮位", "2023年〜の潮位がそろう", lambda c: "2023" <= (c.get("潮位", {}).get("first") or "9") <= "2023-12"),
    ("E10", "締切前に売れた組はよく来るか(オッズの動き)", "締切前オッズ", "数百日ぶん(目安 2026-12〜)", lambda c: c.get("締切前オッズ", {}).get("n_files", 0) >= 60),
    ("E13", "期待値150%以上の買い目を締切前オッズで確かめる", "締切前オッズ", "300点(目安: 数か月)", lambda c: False),
    ("A13", "記者の評価・コメントを点数に(市場に上乗せがあるか)", "記者の評価・コメント・前検", "オッズのあるレース数千", lambda c: c.get("記者の評価・コメント・前検", {}).get("n_files", 0) >= 30),
    ("E11", "公式コンピュータ予想の組は買われすぎか", "公式コンピュータ予想", "2倍のレース数(さかのぼり中)", lambda c: c.get("公式コンピュータ予想", {}).get("first", "9") <= "2025-06"),
    ("A10", "2023年より前の成績で、珍しい条件の例を増やす", "成績・出走表", "2021年〜までさかのぼる(未着手)", lambda c: c.get("成績・出走表", {}).get("first", "9") <= "2021-01"),
    ("A1", "期別成績(長期の実力)を事前の手がかりに", "選手の期別成績", "2002年〜の期別成績", lambda c: c.get("選手の期別成績", {}).get("n_files", 0) >= 20),
]


def _period(name: str) -> str | None:
    f = re.match(r"fan(\d{2})(\d{2})", name)   # 期別成績(ファン手帳)は fanYYMM
    if f:
        return f"20{f.group(1)}-{f.group(2)}"
    m = re.search(r"(20\d{2})(\d{2})(\d{2})?", name)
    if not m:
        y = re.search(r"_(20\d{2})\.", name)   # 年ごとのファイル(tide_2023.csv.gz)
        return y.group(1) if y else None
    return f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")


def build() -> dict:
    cat = {}
    for name, pat, wf, back, what, src in DATASETS:
        fs = sorted(ROOT.glob(pat))
        ps = sorted(p for p in (_period(f.name) for f in fs) if p)
        size = sum(f.stat().st_size for f in fs)
        cat[name] = {"files": pat, "n_files": len(fs), "first": ps[0] if ps else ("あり" if fs else ""), "last": ps[-1] if ps else "",
                     "mb": round(size / 1e6, 1), "workflow": wf, "backfill": back, "what": what, "source": src}
    waits = []
    for i, what, need, cond, ok in WAITING:
        try:
            ready = bool(ok(cat))
        except Exception:  # noqa: BLE001
            ready = False
        waits.append({"id": i, "what": what, "data": need, "need": cond, "ready": ready})
    return {"asof": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"), "datasets": cat, "waiting": waits}


def to_md(c: dict) -> str:
    out = [f"# データ台帳({c['asof']} 時点)", "", "scripts/data_catalog.py が毎週作り直す。新しいデータは DATASETS、データ待ちのアイデアは WAITING に足す。", "",
           "## 持っているデータ", "", "| データ | 期間 | ファイル | MB | 集める仕組み | さかのぼれるか | 出どころ |", "|---|---|---|---|---|---|---|"]
    for k, v in c["datasets"].items():
        per = f"{v['first']}〜{v['last']}" if v["last"] else (v["first"] or "まだ無い")
        out.append(f"| {k} | {per} | {v['n_files']} | {v['mb']} | {v['workflow']} | {v['backfill']} | {v['source']} |")
    out += ["", "## データを待っているアイデア", "", "| id | アイデア | 必要なデータ | そろう条件 | いま |", "|---|---|---|---|---|"]
    for w in c["waiting"]:
        out.append(f"| {w['id']} | {w['what']} | {w['data']} | {w['need']} | {'検証できる' if w['ready'] else '待ち'} |")
    return "\n".join(out) + "\n"


def main():
    c = build()
    (ROOT / "reports/data_catalog.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "reports/data_catalog.md").write_text(to_md(c), encoding="utf-8")
    print(to_md(c))


if __name__ == "__main__":
    main()
