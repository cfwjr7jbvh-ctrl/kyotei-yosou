"""「勝てる根拠」が出たかを学習のたびに判定し、変わったら LINE で知らせる。

リポジトリは「勝てる根拠が出るまで公開」と決めている(2026-10-04)。根拠が出たら非公開に切り替えるか決める。

勝てる根拠(どちらか。どちらもテスト期間の、学習に使っていないレースで):
  A. 本番の買い方(合成確率+買う判断、期待値100%以上)の回収率の90%区間の下限が100%を超えた(300点以上)
  B. 荒れ狙いの追試に合格し、条件に合うレースの回収率の90%区間(日ごとに引き直し)の下限が100%を超えた
荒れ狙いの追試に合格しただけ(全レースより良いが、100%超えは確かでない)のときも、本番の買い目が切り替わるので知らせる。

状態は reports/edge_status.json に保存し、前回から変わったときだけ送る(LINE の Secrets が無ければ表示だけ)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyotei.notify import SITE_URL, push  # noqa: E402

REPORT = ROOT / "reports/model_report.json"
STATUS = ROOT / "reports/edge_status.json"
UPSET = ROOT / "reports/upset_eval.json"
MIN_BETS = 300


def judge(rep: dict) -> dict:
    out = {"edge": False, "reasons": [], "arashi_passed": False}
    for row in (rep.get("ev") or {}).get("ev_filtered") or []:
        if row.get("ev_min") == 1.0 and row.get("bets", 0) >= MIN_BETS and (row.get("roi_lo90") or 0) > 1.0:
            out["edge"] = True
            out["reasons"].append(f"本番の買い方: 回収率 {row['roi']:.0%}(90%区間の下限 {row['roi_lo90']:.0%})・{row['bets']}点")
    ac = rep.get("arashi_confirm") or {}
    if ac.get("passed"):
        out["arashi_passed"] = True
        lo = (ac.get("roi_hi_ci90") or [0, 0])[0]
        if lo > 1.0:
            out["edge"] = True
            out["reasons"].append(f"荒れ狙い: 回収率 {ac['roi_hi']:.0%}(90%区間の下限 {lo:.0%})・{ac['hi_races']}レース")
    return out


def main():
    if not REPORT.exists():
        print("レポートがありません")
        return
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    # 荒れ狙いの追試は全期間の検証(upset_eval.py --walk-forward)の結果を正とする
    if UPSET.exists():
        up = json.loads(UPSET.read_text(encoding="utf-8"))
        if up.get("mode") == "walk_forward" and up.get("confirm"):
            rep["arashi_confirm"] = up["confirm"]
    now = judge(rep)
    before = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"edge": False, "arashi_passed": False}
    msgs = []
    if now["arashi_passed"] and not before.get("arashi_passed"):
        ac = rep["arashi_confirm"]
        msgs.append("【荒れ狙いの追試に合格】\n"
                    f"1号艇が負けそうなレースだけ期待値で買う方法が、全レースより良いと確かめられました"
                    f"(回収率 {ac['roi_hi']:.0%} 対 {ac['roi_all']:.0%}、{ac['period'][0]}〜{ac['period'][1]}・{ac['hi_races']}レース)。\n"
                    "サイトの買い目はこの条件に自動で切り替わります。")
    if now["edge"] and not before.get("edge"):
        msgs.append("【勝てる根拠が出ました】\n" + "\n".join(now["reasons"]) +
                    "\nリポジトリを非公開に切り替えるか決めましょう(作業用の会話で相談)。")
    if not now["edge"] and before.get("edge"):
        msgs.append("【お知らせ】新しいデータでは、回収率100%超えの根拠が消えました。")
    now["checked_at"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes")
    STATUS.write_text(json.dumps(now, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(now, ensure_ascii=False))
    token, to = os.environ.get("LINE_CHANNEL_TOKEN", ""), os.environ.get("LINE_USER_ID", "")
    for m in msgs:
        print(m)
        if token and to:
            ok, info = push(m + "\n" + SITE_URL, token, to)
            print("LINE:", "送信" if ok else "失敗", info)


if __name__ == "__main__":
    main()
