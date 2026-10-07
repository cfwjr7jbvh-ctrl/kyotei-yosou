"""出す前の事実の照合(2026-10-07 ユーザー「こういうミスは信頼を失墜するから絶対しないように」)。

あった事故: 選手の名前は「竜」なのに、ミカタ新聞とXに『龍』と出した(字の対応表で竜と龍を同じに扱い、決まった字を出していた)。
→ 読者に見せる文字を、元のデータ(その日の出走表)ともう一度突き合わせる。作った側のコードとは別の道で確かめる。
- clean_notes(rr): 理論の札のうち、出走表と合わないもの(名前に無い字など)を外す。外した数を返す
- text_problems(text, rr): 出す文字(カードの見える文字・X の本文)の中の、出走表と合わないところ
- card_problems(html, rr): カードの HTML から見える文字を取り出して text_problems
合わないものが1つでもあれば、その投稿は出さない(ura_auto が X の予定に入れない)。ログには種類と数だけ(名前は出さない)。
"""
from __future__ import annotations

import html as _html
import re

# 『X』の1字は、カードでは名前の字の話にしか使わない → 1字の『』は、このレースのだれかの名前に必ずある字
_ONE = re.compile(r"『(.)』")
_NAME_CLAIM = re.compile(r"([1-6])号艇[^。『』]{0,24}?名前に『(.+?)』")
_LANE = re.compile(r"(\d+)号艇")
_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


def _norm(s) -> str:
    return re.sub(r"[\s　]", "", str(s or ""))


def names(rr: dict) -> dict[int, str]:
    """艇番 → 名前(空白なし)。出走表(rr['boats'])から。"""
    out = {}
    for b in rr.get("boats") or []:
        try:
            out[int(b["lane"])] = _norm(b.get("name") or b.get("racer_name"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def text_problems(text: str, rr: dict) -> list[str]:
    """出す文字の中で、出走表と合わないところ(種類だけ。名前は入れない)。"""
    nm = names(rr)
    probs = []
    t = str(text or "")
    for m in _NAME_CLAIM.finditer(t):
        lane, ch = int(m.group(1)), m.group(2)
        if lane in nm and nm[lane] and ch not in nm[lane]:
            probs.append(f"名前の字: {lane}号艇の名前に無い字")
    all_names = "".join(nm.values())
    if all_names:
        for m in _ONE.finditer(t):
            if m.group(1) not in all_names:
                probs.append("名前の字: だれの名前にも無い1字を『』で出している")
    for m in _LANE.finditer(t):
        if not 1 <= int(m.group(1)) <= 6:
            probs.append(f"艇番: {m.group(1)}号艇")
    for m in _PCT.finditer(t):
        if float(m.group(1)) > 100:
            probs.append(f"確率: {m.group(1)}%")
    # 艇番と名前の組み合わせ(「2号艇 ◯◯」の◯◯が、別の艇の人になっていないか)
    for lane, n in nm.items():
        for lane2, n2 in nm.items():
            if lane2 != lane and n2 and len(n2) >= 2 and re.search(rf"{lane}号艇\s?{re.escape(n2)}", t):
                probs.append(f"艇番と名前: {lane}号艇に別の艇の名前")
    return sorted(set(probs))


def note_problems(n: dict, rr: dict) -> list[str]:
    """理論の札1つ(見出し・本文・ゲンさんのひと言)。名前の字の札は、その艇の名前にその字があること。"""
    nm = names(rr)
    probs = text_problems(" ".join(str(n.get(k) or "") for k in ("title", "text", "gen")), rr)
    if n.get("id") == "name":
        chars = [m.group(1) for m in _ONE.finditer(str(n.get("title") or "") + str(n.get("text") or ""))]
        for ln in n.get("lanes") or []:
            if not nm.get(int(ln)) or any(c not in nm[int(ln)] for c in chars):
                probs.append("名前の字: 札の艇の名前に無い字")
    if n.get("id") == "lucky7":   # モーター番号の末尾7(出走表にモーター番号があるときだけ確かめる)
        mot = {int(b["lane"]): b.get("motor_no") for b in rr.get("boats") or [] if b.get("motor_no") not in (None, "")}
        for ln in n.get("lanes") or []:
            if int(ln) in mot and int(float(mot[int(ln)])) % 10 != 7:
                probs.append("モーター: 末尾が7ではない")
    return sorted(set(probs))


def clean_notes(rr: dict) -> list[str]:
    """rr['theories'] から出走表と合わない札を外す(rr を書きかえる)。外した札の問題の一覧を返す。"""
    th = rr.get("theories")
    if not th:
        return []
    keep, probs = [], []
    for n in th:
        p = note_problems(n, rr)
        if p:
            probs += p
        else:
            keep.append(n)
    if probs:
        rr["theories"] = keep
        try:
            from . import theories
            rr["th_sum"] = theories.summarize(keep)
        except Exception:  # noqa: BLE001
            pass
    return probs


def visible_text(html: str) -> str:
    s = re.sub(r"<(style|script)[\s\S]*?</\1>", " ", str(html or ""), flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return _html.unescape(s)


def card_problems(html: str, rr: dict) -> list[str]:
    return text_problems(visible_text(html), rr)


# はみ出しの測り方(playwright の page.evaluate に渡す)。カード(.c、1080×1350)の中の文字が、
# 下の帯(.ft)にかかっていないか・右や左にはみ出していないか。{"v": 下にはみ出した px, "h": 横にはみ出した px}
OVERFLOW_JS = """() => {
  const c = document.querySelector('.c'); if (!c) return {v: 0, h: 0};
  const cr = c.getBoundingClientRect();
  const ft = c.querySelector('.ft');
  const lim = ft ? ft.getBoundingClientRect().top - 4 : cr.bottom;
  let v = -1e9, h = -1e9;
  const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode;
    if (!n.textContent.trim() || (ft && ft.contains(n))) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) {
      if (!b.width || !b.height) continue;
      v = Math.max(v, b.bottom - lim);
      h = Math.max(h, b.right - (cr.right - 8), (cr.left + 8) - b.left);
    }
  }
  return {v: Math.round(v), h: Math.round(h)};
}"""
