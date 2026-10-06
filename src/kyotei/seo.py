"""検索で見つけてもらうための言葉(X・note・Google)。

予想する人が検索するのは「場名+R(住之江12R)」「大会名」「選手名」「競艇/ボートレース」。だから:
- X: 1行目に場名・R・レースの種類・大会名。本文に選手名(フルネーム)。ハッシュタグは2個(多いとスパム扱いされやすい。2〜3個が目安)。
  #の後ろに空白や記号を入れない(そこで切れる)。大会の日は「#大会名」、ふだんは「#ボートレース場名」。もう1個は「#競艇」か「#ボートレース」
- note: タイトルの前の方に場名・大会名・「競艇」。ハッシュタグは10個まで(競艇・ボートレース・場・大会・選手名)。
「的中」「必勝」「儲かる」「予想屋」のような言葉は使わない(発信方針)。
"""
from __future__ import annotations

import re
import unicodedata

from .xtext import xlen


def clean_tag(s: str) -> str:
    """ハッシュタグに使える形(空白・記号を抜く)。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[\s・･!！?？\-ー―‐()（）「」『』【】.,、。:：/／&＆#＃'’\"“”]", "", s)


def x_tags(venue: str | None = None, series: str | None = None, general: str = "競艇") -> str:
    """X のハッシュタグ2個。大会の日は「#大会名 #ボートレース場名」、ふだんは「#ボートレース場名 #競艇」。場が無ければ「#競艇 #ボートレース」。"""
    v = f"#ボートレース{clean_tag(venue)}" if venue else None
    if series:
        return f"#{clean_tag(series)} " + (v or "#ボートレース")
    if v:
        return f"{v} #{general}"
    return "#競艇 #ボートレース"


def with_tags(body: str, tags: str, limit: int = 280) -> str:
    """本文の最後にハッシュタグの行を足す(280字を超えるなら1個に減らす、それでも超えるなら足さない)。"""
    for t in (tags, tags.split(" ")[0]):
        b = f"{body}\n{t}"
        if xlen(b) <= limit:
            return b
    return body


def note_tags(venue: str | None = None, series: str | None = None, racers: list[str] | None = None, extra: list[str] | None = None) -> str:
    """note に設定するハッシュタグ(10個まで)。"""
    tags = ["競艇", "ボートレース"]
    if venue:
        tags.append(f"ボートレース{clean_tag(venue)}")
    if series:
        tags.append(clean_tag(series))
    tags += [clean_tag(x) for x in (extra or [])]
    tags += [clean_tag(x) for x in (racers or [])]
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append("#" + t)
    return "【ハッシュタグ(note に設定)】" + " ".join(out[:10])
