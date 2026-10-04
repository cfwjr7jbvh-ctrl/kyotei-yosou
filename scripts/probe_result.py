"""公式サイトのレース結果ページ(raceresult)のサンプルを保存する(解析を作るための調査、GitHub Actionsで実行)。"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyotei.scrape import fetch, race_days  # noqa: E402

OUT = pathlib.Path("data/probe")
OUT.mkdir(parents=True, exist_ok=True)
hd = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")
for jcd in race_days(hd)[:2]:
    for rno in (1, 12):  # 1R は終わっている、12R はまだ(終わる前のページの形も見る)
        html = fetch("raceresult", jcd, rno, hd, wait=1.5)
        if html:
            (OUT / f"raceresult_{jcd:02d}_{rno:02d}.html").write_text(html, encoding="utf-8")
            print("saved", jcd, rno, len(html))
