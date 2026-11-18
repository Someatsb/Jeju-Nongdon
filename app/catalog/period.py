"""새 공고의 신청 기간 글("가. 신청기간: 2026. 11. 9.(월) ~ 11. 23.(월) (15일간)")에서 시작일·마감일을 읽는다.

- 확실히 읽히는 꼴만 읽는다. 날짜가 달력에 없거나, 날짜가 둘보다 많거나, 앞뒤 관계를 알 수 없으면 지어내지 않고 None 이다.
- 연도가 없으면 읽은 날(read_date)의 해로 본다. 마감이 시작보다 앞서면 마감은 다음 해다.
- 시계를 읽지 않는다. 순수 함수다.
"""
from __future__ import annotations

import re
from datetime import date

# 연도(선택) + 월 + 일. '2026. 11. 9.', '11. 23', '11월 9일', '2026년 12월 20일' 모두 읽는다. 앞뒤가 숫자이면 날짜가 아니다.
MAX_AHEAD_DAYS = 183
_DATE = re.compile(r"(?<!\d)(?:(\d{4})\s*[.년]\s*)?(\d{1,2})\s*[.월]\s*(\d{1,2})(?!\d)\s*일?")
# 날짜 뒤에 바로 단위·낱말이 붙으면('1.5억', '3.5톤', '2.5ha') 날짜가 아니라 소수다. 까지·부터·일은 날짜의 일부다.
_NOT_DATE_AFTER = re.compile(r"\s*[억만천]|(?![까부일])[가-힣%a-zA-Z㎡]")
_RANGE_SIGN = re.compile(r"[~∼〜–-]|부터")
_UNTIL_AFTER = re.compile(r"^\s*\.?\s*(?:\([^)]*\))?\s*까지")
_FROM_AFTER = re.compile(r"^\s*\.?\s*(?:\([^)]*\))?\s*부터")


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_period(text: str, read_date: date) -> tuple[date | None, date | None]:
    """(시작, 마감). 읽지 못하는 쪽은 None. 끝만 적힌 글('~ 12. 31.까지')은 (None, 마감)."""
    if not text:
        return None, None
    found = [m for m in _DATE.finditer(text) if not _NOT_DATE_AFTER.match(text, m.end())]
    if not found or len(found) > 2:
        return None, None
    year0 = read_date.year
    if len(found) == 1:
        m = found[0]
        d = _make(int(m.group(1) or year0), int(m.group(2)), int(m.group(3)))
        if d is None:
            return None, None
        before, after = text[:m.start()].rstrip(), text[m.end():]
        if before.endswith(("~", "∼", "〜", "–")) or _UNTIL_AFTER.match(after):
            if m.group(1) is None and d < read_date:       # 연도 없는 끝 날짜가 읽은 날보다 앞서면 해를 알 수 없다
                return None, None
            return None, d
        if _FROM_AFTER.match(after):
            return d, None
        return None, None
    a, b = found
    if not _RANGE_SIGN.search(text[a.end():b.start()]):
        return None, None
    start = _make(int(a.group(1) or year0), int(a.group(2)), int(a.group(3)))
    if start is None:
        return None, None
    if b.group(1) is not None:
        end = _make(int(b.group(1)), int(b.group(2)), int(b.group(3)))
    else:
        end = _make(start.year, int(b.group(2)), int(b.group(3)))
        if end is not None and end < start:       # 끝이 앞서면 다음 해. 같은 달이면 오타일 수 있어 읽지 않는다
            end = _make(start.year + 1, int(b.group(2)), int(b.group(3))) if int(b.group(2)) < start.month else None
    if end is None or end < start:
        return None, None
    if (start - read_date).days > MAX_AHEAD_DAYS:          # 시작이 반년 넘게 앞선 미래면 해 오타일 수 있어 읽지 않는다
        return None, None
    return start, end
