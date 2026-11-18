"""때를 말하는 글을 기준일에서 본 말로 만드는 한 곳(2026-11-15 표현 정리).

표에는 '3월'처럼 달만 있다. 어르신이 읽는 화면·종이에는 기준일(as_of)에서 본 '올해 12월쯤'·'내년 3월쯤'으로 보인다.
화면에 보일 때만 바꾼다: 표의 값과 AI 입력(FactSheet·NarrativeInput)에는 쓰지 않는다. 숫자(달·날짜)는 그대로이고 앞말만 붙는다.
규칙: 날짜가 있으면 그 날짜의 해로 가른다(year_word_of). 달만 있으면 그 달이 기준일의 달보다 뒤일 때만 올해, 같거나 앞서면 내년이다
(달만 아는 철은 같은 달이면 이미 지난 철이라 다음 해로 넘어간 것이다)
"""
from __future__ import annotations

from datetime import date

ALWAYS = "언제든 신청할 수 있어요"
ASK_WHEN = "언제 받는지는 창구에 물어보세요"


def year_word(month: int, as_of: date) -> str:
    """'올해' | '내년': month(1~12)가 기준일의 달보다 뒤면 올해, 같거나 앞서면 내년."""
    return "올해" if month > as_of.month else "내년"


def year_word_of(d: date, as_of: date) -> str:
    """날짜가 있을 때는 그 해로 가른다: 기준일의 해보다 뒤면 내년, 같으면 올해."""
    return "내년" if d.year > as_of.year else "올해"


def month_when(month: int, as_of: date) -> str:
    """'내년 3월쯤' · '올해 12월쯤'."""
    return f"{year_word(month, as_of)} {month}월쯤"


def month_when_of(d: date, as_of: date) -> str:
    """날짜가 있는 철의 '올해 12월쯤' · '내년 1월쯤': 올해·내년은 그 날짜의 해로 정한다(같은 달이어도 이미 지나 다음 해로 넘어간 철은 내년)."""
    return f"{year_word_of(d, as_of)} {d.month}월쯤"


def months_when(first: int, last: int, as_of: date) -> str:
    """'내년 3~5월쯤'. 달이 하나면 month_when 과 같다. 앞 달로 올해·내년을 가른다."""
    if first == last:
        return month_when(first, as_of)
    return f"{year_word(first, as_of)} {first}~{last}월쯤"


def date_when(d: date) -> str:
    """'4월 27일' (앞말 없이). 해는 year_word_of 로 따로 붙인다."""
    return f"{d.month}월 {d.day}일"


def day_when(d: date, as_of: date) -> str:
    """'내년 4월 27일' · '올해 12월 3일'."""
    return f"{year_word_of(d, as_of)} {date_when(d)}"
