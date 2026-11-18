"""공고 에이전트가 읽어 목록에 올린 새 공고(data/catalog/notices/<이름>.json) 읽기(설계서 B-1, B-3).

새 공고는 지원 표(supports.csv)에 넣지 않는다. 금액·자격은 따지지 않고, 공고에 적힌 글을 원문 그대로 보여 주는 '안내만' 카드다.
파일 한 개가 사업 하나다. 깨진 파일은 건너뛰고(다른 공고는 계속 보인다) 경고만 남긴다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from app.catalog.links import is_official_url

_log = logging.getLogger(__name__)

NOTICE_VERSION = 1
KEY_PREFIX = "new-"
MIN_TAGS = 2          # 근거 대조를 통과한 이름표가 이만큼이면 그것만으로 목록에 오른다
MIN_TAGS_WITH_WHEN = 1  # 이름표가 이만큼뿐이면 원문과 맞는 신청 기간 또는 접수처가 있어야 오른다(공고 읽기 v4는 이름표를 받을 조건만으로 낸다)


def enough_tags(n_tags: int, has_period_or_where: bool) -> bool:
    """올리는 규칙과 저장된 파일을 읽는 규칙이 같도록 한 곳에 둔다."""
    return n_tags >= MIN_TAGS or (n_tags >= MIN_TAGS_WITH_WHEN and has_period_or_where)


_YEAR = re.compile(r"[0-9]{4}\s*년도?")
_PAREN = re.compile(r"[(（\[]([^()（）\[\]]*)[)）\]]")
_FILLER = re.compile("추가|신청|접수|알림|계획|안내")
_SYMBOLS = re.compile(r"[\s·ㆍ∙•･,.\-_/~()（）\[\]{}<>「」『』〈〉\"'`]+")


def business_key(name: str) -> str | None:
    """사업 이름을 같은 사업끼리 같은 글이 되게 줄인다(같은 사업의 다른 글이 목록에 겹치지 않게 견주는 데 쓴다).
    뗀다: 연도("2027년"·"2027년도"), 띄어쓰기·가운뎃점·괄호 기호, 괄호 속이 "추가·신청·접수·알림·계획·안내" 낱말뿐인 덧말, 끝의 "지원사업"·"사업".
    괄호 속이 그 밖의 글("(감귤)"·"(융자)")이면 사업 구분일 수 있으니 글자는 남긴다. 뗀 뒤 글이 완전히 같아야 같은 사업이다
    (한쪽이 다른 쪽을 품는 것만으로는 같지 않다). 뗀 뒤 비면 None."""
    s = _YEAR.sub("", name or "")
    s = _PAREN.sub(lambda m: "" if not _FILLER.sub("", _SYMBOLS.sub("", m.group(1))) else m.group(0), s)
    s = _SYMBOLS.sub("", s)
    for tail in ("지원사업", "사업"):
        if s.endswith(tail):
            s = s[: -len(tail)]
            break
    return s or None


@dataclass(frozen=True)
class NoticeTag:
    label: str
    quote: str
    anchor: str | None = None


@dataclass(frozen=True)
class NoticeRecord:
    key: str                     # 'new-' + 파일 이름(확장자 뺀 것)
    name: str
    agency: str
    apply_period: str            # 공고 원문 그대로(근거 문장). 없으면 빈 글
    target: str                  # 공고 원문 그대로(줄바꿈으로 이은 근거 문장들)
    content: str                 # 공고 원문 그대로
    tags: tuple[NoticeTag, ...]
    url: str | None              # 공고를 받아 온 공식 주소. 없으면 None
    read_date: date
    decision: str
    table_key: str | None        # 표의 같은 제도 열쇠(에이전트가 기존 행과 같다고 본 것). 없으면 None
    apply_where: str = ""        # 어디서·어떻게 신청하는지 공고 원문 그대로(공고 읽기 v4부터). v3 파일이나 공고에 없으면 빈 글


def _record(path: Path) -> NoticeRecord:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != NOTICE_VERSION:
        raise ValueError("version")
    tags = tuple(NoticeTag(str(t["label"]).strip(), str(t["quote"]).strip(), t.get("anchor")) for t in raw["tags"])
    has_when = bool(str(raw.get("apply_period") or "").strip() or str(raw.get("apply_where") or "").strip())
    if not enough_tags(len(tags), has_when) or any(not t.label or not t.quote for t in tags):
        raise ValueError("tags")
    name = str(raw["name"]).strip()
    if not name:
        raise ValueError("name")
    url = raw.get("url")
    return NoticeRecord(
        key=KEY_PREFIX + path.stem, name=name, agency=str(raw.get("agency") or "").strip(),
        apply_period=str(raw.get("apply_period") or "").strip(), target=str(raw.get("target") or "").strip(),
        content=str(raw.get("content") or "").strip(), tags=tags,
        url=url if isinstance(url, str) and is_official_url(url) else None,
        read_date=date.fromisoformat(raw["read_date"]), decision=str(raw.get("decision") or ""),
        table_key=raw.get("table_key") or None, apply_where=str(raw.get("apply_where") or "").strip())


def load_notices(directory: Path) -> list[NoticeRecord]:
    """폴더의 새 공고들. 읽은 날이 늦은 것이 먼저, 같으면 이름순. 폴더가 없으면 빈 목록."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[NoticeRecord] = []
    for path in sorted(directory.glob("*.json")):
        try:
            out.append(_record(path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            _log.warning("새 공고 파일을 읽지 못해 건너뜁니다: %s (%s)", path.name, type(e).__name__)
    return sorted(dedupe_same_business(out), key=lambda n: (-n.read_date.toordinal(), n.name))


def dedupe_same_business(notices: Sequence[NoticeRecord]) -> list[NoticeRecord]:
    """이름이 같은 사업(business_key)이 둘 이상이면 하나만 남긴다: 접수처가 있는 쪽, 같으면 나중에 읽은 쪽, 그래도 같으면 파일 이름이 뒤인 쪽.
    손으로 폴더에 넣은 경우를 위한 안전 장치다. 순서는 들어온 대로 둔다."""
    best: dict[str, NoticeRecord] = {}
    for n in notices:
        k = business_key(n.name)
        if k is not None:
            cur = best.get(k)
            if cur is None or _rank(n) > _rank(cur):
                best[k] = n
    return [n for n in notices if (k := business_key(n.name)) is None or best[k] is n]


def _rank(n: NoticeRecord) -> tuple[bool, int, str]:
    return bool(n.apply_where), n.read_date.toordinal(), n.key
