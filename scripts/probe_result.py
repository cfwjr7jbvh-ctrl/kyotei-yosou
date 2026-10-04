"""公式サイトのページのサンプルを保存する(解析を作るための調査、GitHub Actionsで実行)。
- raceresult: レース結果(終わったレース・まだのレース)
- pcexpect: 公式のコンピュータ予想(今日と、過去の日も見られるか)
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyotei.scrape import fetch, race_days  # noqa: E402

OUT = pathlib.Path("data/probe")
OUT.mkdir(parents=True, exist_ok=True)
hd = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")
for jcd in race_days(hd)[:1]:
    for rno in (1, 12):
        html = fetch("pcexpect", jcd, rno, hd, wait=1.5)
        if html:
            (OUT / f"pcexpect_{jcd:02d}_{rno:02d}.html").write_text(html, encoding="utf-8")
            print("saved pcexpect", jcd, rno, len(html))
# 過去の日(2024-06-01)のコンピュータ予想と直前情報が残っているか
old = "20240601"
for jcd in race_days(old)[:1]:
    for page in ("pcexpect", "beforeinfo"):
        html = fetch(page, jcd, 1, old, wait=1.5)
        if html:
            (OUT / f"{page}_old_{jcd:02d}.html").write_text(html, encoding="utf-8")
            print("saved", page, old, jcd, len(html))
