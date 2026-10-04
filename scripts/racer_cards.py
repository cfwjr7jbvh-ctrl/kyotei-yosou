"""選手カードを作る(src/kyotei/racer_card.py)。

python scripts/racer_cards.py build --out DIR  # 全選手 → DIR/cards/bNN.json(登番を50で割った余りごと)と DIR/cards/meta.json(どちらも暗号化)
                                               # と reports/racer_cards_meta.json(基準とタグの数だけ、平文)
python scripts/racer_cards.py show 峰竜太 4238  # 指定した選手のカードを表示(登番か名前)

カードは公式の成績データを自分たちで集計した数字だけでできている。売り物にもなる集計なので暗号化し、
履歴を積み上げないよう cards ブランチに1コミットだけで置く(scripts/push_cards.sh、毎朝の予想のあと)。
アプリは /api/data/cards/bNN.json を、選手名をタップしたときに読む。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei import racer_card as rc  # noqa: E402

META = ROOT / "reports/racer_cards_meta.json"
BUCKETS = 50


def compact(c: dict) -> dict:
    """アプリ用に小さくする(基準の文はメタにまとめ、タグにはタグ名と根拠だけ)。"""
    x = {k: v for k, v in c.items() if k not in ("tags",)}
    x["tags"] = [{"t": t["t"], "why": t["why"], "cat": t["cat"]} for t in c["tags"]]
    return x


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "build"
    d = rc.load_table()
    cards, meta = rc.build(d)
    if what == "show":
        for k in sys.argv[2:]:
            c = rc.find(cards, k)
            print(json.dumps(c, ensure_ascii=False, indent=1) if c else f"見つかりません: {k}")
        return
    from kyotei.publish import write_json
    out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "out"
    (out / "cards").mkdir(parents=True, exist_ok=True)
    asof = meta["asof"]
    recent = str(int(asof[:4]) - 1) + asof[4:]  # 直近1年に走った選手だけ
    active = {k: compact(v) for k, v in cards.items() if v["period"][1] >= recent}
    buckets: dict[int, dict] = {}
    for k, v in active.items():
        buckets.setdefault(k % BUCKETS, {})[str(k)] = v
    for b in range(BUCKETS):
        write_json(out / f"cards/b{b:02d}.json", {"asof": asof, "cards": buckets.get(b, {})})
    write_json(out / "cards/meta.json", {"asof": asof, "period": meta["period"], "buckets": BUCKETS, "radar": rc.RADAR,
                                         "rules": {r["tag"]: r["rule"] for r in meta["rules"]},
                                         "groups": rc.GROUP_NAME, "pop_by_group": meta["pop_by_group"]})
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(p.stat().st_size for p in (out / "cards").glob("*.json"))
    print(f"cards: {len(active)} 人 / asof {asof} / {size / 1e6:.1f}MB → {out / 'cards'}")


if __name__ == "__main__":
    main()
