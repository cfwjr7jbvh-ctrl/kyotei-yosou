"""平文で残っている記事の本文(reports/lab/*.json)を暗号化する(2026-10-07 パクられ対策。一度きり+保険)。
鍵(SITE_PASSWORD)のある GitHub Actions(encrypt_reports.yml / lab.yml)で動かす。"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.publish import write_json  # noqa: E402

n = 0
for p in sorted((ROOT / "reports/lab").glob("*.json")):
    obj = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(obj, dict) and obj.get("enc") == 1:
        continue
    write_json(p, obj, encrypt=True)
    n += 1
print("暗号化:", n, "本")
