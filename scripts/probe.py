"""公式データの取得可否と形式を調べる調査スクリプト(GitHub Actionsで実行)。

結果は data/probe/ に保存してコミットされる。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import time

import requests

OUT = pathlib.Path("data/probe")
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (kyotei-yosou research; low-frequency)"}
log: list[dict] = []


def get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=30)
        log.append({"url": url, "status": r.status_code, "bytes": len(r.content),
                    "ctype": r.headers.get("content-type")})
        return r
    except Exception as e:  # noqa: BLE001
        log.append({"url": url, "error": repr(e)})
        return None
    finally:
        time.sleep(1.5)


def extract(lzh: pathlib.Path, dest: pathlib.Path) -> list[pathlib.Path]:
    dest.mkdir(parents=True, exist_ok=True)
    for cmd in (["7z", "x", "-y", f"-o{dest}", str(lzh)], ["lha", "xqw=" + str(dest), str(lzh)]):
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            break
        except Exception as e:  # noqa: BLE001
            log.append({"extract_fail": cmd[0], "err": repr(e)})
    return [p for p in dest.iterdir() if p.is_file()]


def main() -> None:
    today = dt.date.today()
    days = [today - dt.timedelta(days=k) for k in (3, 4)]
    for d in days:
        for kind in ("B", "K"):
            name = f"{kind.lower()}{d:%y%m%d}.lzh"
            for scheme in ("http", "https"):
                url = f"{scheme}://www1.mbrace.or.jp/od2/{kind}/{d:%Y%m}/{name}"
                r = get(url)
                if r is not None and r.status_code == 200 and len(r.content) > 500:
                    p = OUT / name
                    p.write_bytes(r.content)
                    for f in extract(p, OUT / f"x_{kind}_{d:%y%m%d}"):
                        txt = f.read_bytes().decode("cp932", errors="replace")
                        (OUT / f"{f.stem}_utf8.txt").write_text(txt, encoding="utf-8")
                        f.unlink()
                    p.unlink()
                    break

    # 公式サイトのレースページ(直前情報・オッズ・結果)
    d = days[0]
    hd = d.strftime("%Y%m%d")
    r = get(f"https://www.boatrace.jp/owpc/pc/race/index?hd={hd}")
    jcds = []
    if r is not None and r.ok:
        (OUT / "index.html").write_text(r.text, encoding="utf-8")
        import re
        jcds = sorted(set(re.findall(r"jcd=(\d\d)", r.text)))[:2]
    for jcd in jcds or ["01"]:
        for page in ("racelist", "beforeinfo", "odds3t", "oddstf", "raceresult"):
            r = get(f"https://www.boatrace.jp/owpc/pc/race/{page}?rno=12&jcd={jcd}&hd={hd}")
            if r is not None and r.ok:
                (OUT / f"{page}_{jcd}.html").write_text(r.text, encoding="utf-8")
        break
    (OUT / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
