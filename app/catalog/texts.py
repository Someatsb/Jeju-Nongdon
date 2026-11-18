"""지원 안내 글: 신청 기간 한 줄, 금액 한 줄, '누가 받나요' 조건 줄. 모두 표의 칸 값에서만 만든다.

- 날짜·금액·숫자는 표에 있는 값 그대로다. 새로 세는 것은 '며칠 남음' 뿐이다(기준일에서 표의 날짜까지).
- 표에서 알 수 없는 것은 "창구에서 확인"이라고 쓴다. 지어내지 않는다.
- 영어·코드 낱말은 글에 나오지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from app.catalog.period import parse_period
from app.catalog.tags import age_text, area_text, crop_names, num
from app.core.calendar import apply_window
from app.core.models import Program
from app.core.when_text import ALWAYS, ASK_WHEN, month_when

ASK_OFFICE = "창구에 물어보세요"
ASK_AMOUNT = "금액은 창구에 물어보세요"
NO_TIMING = ASK_WHEN                      # '언제 받는지는 창구에 물어보세요'
PRIOR_NOTE = "지난 공고 기준이에요. 올해 공고가 나오면 달라질 수 있어요"
HOLD_NOTE = "아직 확인 중인 내용이에요. 창구에 꼭 다시 물어보세요"
ENDED_THIS_YEAR = "올해 신청은 끝났어요"
BEFORE_NOTICE = "올해 공고 전이에요"

# 순서(rank): 작을수록 먼저 보여 준다
RANK_OPEN, RANK_SOON, RANK_ALWAYS, RANK_LATER, RANK_UNKNOWN = 0, 1, 2, 3, 4
RANK_ENDED = 5            # 새 공고 중 신청이 끝난 것: 새 공고 맨 뒤


def md(d: date) -> str:
    return f"{d.month}월 {d.day}일"


@dataclass(frozen=True)
class Window:
    text: str
    rank: int
    days: int | None          # 마감(또는 시작)까지 남은 날. 모르면 None
    open_now: bool            # 확정된 행이고 지금 신청을 받는다(상시 포함)
    month: int | None = None  # 다음 신청 철의 달(올해·내년 말은 글에만 있다). 순서·정렬은 이 값으로 가른다(글을 되읽지 않는다)


_ALWAYS_TEXT = {"상시": ALWAYS, "자동": "따로 신청 기간이 없어요"}
_EVENT_TEXT = {"재해": "재해가 난 뒤에 신청해요", "사고": "사고가 난 뒤에 신청해요"}


def next_season(month: int, as_of: date, *, force_next_year: bool = False) -> str:
    """끝난 지원의 다음 철 글: '내년 3월쯤 다시 받아요'(올해 안이면 '올해 12월쯤 다시 받아요')."""
    when = f"내년 {month}월쯤" if force_next_year else month_when(month, as_of)
    return f"{when} 다시 받아요"


def window_of(p: Program, as_of: date) -> Window:
    """행 하나의 신청 기간 글. 기준일(as_of)은 부르는 쪽이 정한다."""
    if p.status == "hold":
        return Window(NO_TIMING, RANK_UNKNOWN, None, False)
    w = apply_window(p, as_of)
    if w.always_open:
        if p.apply_cycle == "사후신청":
            text = _EVENT_TEXT.get(p.event_type or "", "일이 생긴 뒤에 신청해요")
        elif p.apply_cycle == "자동" and p.applicant == "농협경유":
            text = "농협이 대신 신청해요"
        else:
            text = _ALWAYS_TEXT[p.apply_cycle]
        return Window(text, RANK_ALWAYS, None, p.status == "confirmed")
    if p.apply_cycle != "연1회" or p.apply_end is None:
        return Window(NO_TIMING, RANK_UNKNOWN, None, False)
    month = p.expected_notice_month or p.next_month or (w.first_date.month if w.first_date else None)
    if p.status == "prior_year_reference":
        if month is None:
            return Window(NO_TIMING, RANK_UNKNOWN, None, False)
        if month >= as_of.month:
            return Window(f"{BEFORE_NOTICE} · {month}월쯤 받아요", RANK_LATER, None, False, month)
        return Window(f"{ENDED_THIS_YEAR} · {next_season(month, as_of)}", RANK_LATER, None, False, month)
    end = w.next_end
    if end.year > p.apply_end.year:                      # 올해 창이 지나 다음 해로 옮겨 짐
        if month is None:
            return Window(ENDED_THIS_YEAR, RANK_LATER, None, False)
        return Window(f"{ENDED_THIS_YEAR} · {next_season(month, as_of, force_next_year=True)}", RANK_LATER, None, False, month)
    left = (end - as_of).days
    if w.open_now or w.next_start is None:
        tail = "오늘 마감" if left == 0 else f"{left}일 남음"
        return Window(f"{md(end)}까지 · {tail}", RANK_OPEN, left, w.open_now)
    until = (w.next_start - as_of).days
    return Window(f"{md(w.next_start)}부터 · {until}일 뒤 열려요", RANK_SOON, until, False)


def notice_window(period: str, read_date: date, as_of: date) -> tuple[Window, date | None, date | None]:
    """새 공고의 신청 기간 글(공고 원문 한 줄)을 표의 지원과 같은 말투로. (글, 시작일, 마감일).
    마감일을 읽지 못하면 지어내지 않는다: 원문 글이 있으면 앞머리 기호만 뗀 그대로, 없으면 '창구에서 확인'."""
    start, end = parse_period(period, read_date)
    if end is None:
        text = _PERIOD_LABEL.sub("", plain_line(period), count=1).strip()        # 칸 제목이 '언제'라 글 앞의 '신청기간:' 이름은 떼고 보인다(저장된 글은 그대로)
        return Window(text or NO_TIMING, RANK_UNKNOWN, None, False), start, None
    if end < as_of:
        return Window("신청이 끝났어요", RANK_ENDED, None, False), start, end
    if start is not None and start > as_of:
        until = (start - as_of).days
        return Window(f"{md(start)}부터 · {until}일 뒤 열려요", RANK_SOON, until, False), start, end
    left = (end - as_of).days
    tail = "오늘 마감" if left == 0 else f"{left}일 남음"
    return Window(f"{md(end)}까지 · {tail}", RANK_OPEN, left, True), start, end


# --- 공고 원문 줄 보여 주기 ------------------------------------------------------------------

_PERIOD_LABEL = re.compile(r"^(?:신청\s*기간|접수\s*기간|신청\s*시기)\s*[:：]\s*")
# 줄 앞머리의 번호·기호: '가. ' '3. ' '① ' '(1) ' '○ ' '- ' '※ ' '* ' ... 날짜로 시작하는 줄('11. 9. ~')은 건드리지 않는다.
_LEAD = re.compile(r"^\s*(?:\d{1,2}[.)]\s+(?=[^\d\s])|[가-힣][.)]\s+|[①-⑳]\s*|\(\d{1,2}\)\s*|\([가-힣]\)\s*|[○●◦▪■□◆◇▶▷※*＊•·\-–—]+\s*)")


def plain_line(text: str) -> str:
    """보여 줄 때만: 줄 앞머리 기호('가. ', '3. ', '○ ', '- ', '※ ', '* ' ...)를 뗀다. 저장된 글은 그대로 둔다."""
    s = (text or "").strip()
    while (m := _LEAD.match(s)) and m.end() > 0:
        s = s[m.end():]
    return s.strip()


def plain_lines(text: str) -> tuple[str, ...]:
    """여러 줄 글을 줄마다 앞머리 기호를 떼어 빈 줄 없이."""
    return tuple(x for x in (plain_line(ln) for ln in (text or "").splitlines()) if x)


# --- 금액 ------------------------------------------------------------------------------------

_PERIOD = {"연": "1년에", "월": "한 달에", "일": "하루에", "1회": "한 번에"}


def won(n: int) -> str:
    """원 단위 정수 → '130만 원', '7만 9,200원'. 반올림하지 않는다."""
    if n >= 10_000:
        man, rest = divmod(n, 10_000)
        return f"{man:,}만 원" if not rest else f"{man:,}만 {rest:,}원"
    return f"{n:,}원"


def amount_of(p: Program) -> str | None:
    """행의 금액 글. 표의 amount_note(사람이 쓴 한 줄)가 있으면 그대로, 없으면 amount_* 칸으로만 만든다. 없으면 None."""
    if p.amount_note:
        return p.amount_note
    if p.amount_value is not None:
        base = won(p.amount_value)
        if p.amount_type == "kg당":
            return f"kg당 {base}"
        if p.amount_type == "단위당":
            return f"{p.unit_name}당 {base}" if p.unit_name else f"단위당 {base}"
        if p.amount_type == "면적비례":
            return f"면적에 따라 {base}"
        return f"{_PERIOD.get(p.period or '', '')} {base}".strip()
    if p.amount_min is not None and p.amount_max is not None:
        return f"{won(p.amount_min)}~{won(p.amount_max)}"
    if p.amount_max is not None:
        return f"최대 {won(p.amount_max)}"
    if p.rate_pct_min is not None or p.rate_pct_max is not None:
        lo, hi = p.rate_pct_min, p.rate_pct_max
        rate = f"{num(lo)}~{num(hi)}%" if lo is not None and hi is not None and lo != hi else f"{num(hi if hi is not None else lo)}%"
        return f"{rate} 지원" + (f", 최대 {won(p.cap_won)}" if p.cap_won else "")
    return None


# --- 누가 받나요 -----------------------------------------------------------------------------

_BASIS = {"신청일": "신청하는 날의 나이", "연말": "그해 연말의 나이", "1월1일": "1월 1일의 나이"}
_AREA_BASIS = {"경작": "농사짓는 땅 전체", "해당작물": "그 작물을 심은 땅", "소유": "내 땅", "인증": "인증받은 땅"}
_ENROLL_NOTE = "미리 참여 신청을 해야 해요"


_EVENT_WHO = {"재해": "재해를 입은 분이 받아요", "사고": "사고를 당한 분이 받아요"}


def _eun(word: str) -> str:
    """'과수' → '과수는', '감귤' → '감귤은'."""
    last = word.rstrip()[-1:]
    return word + ("는" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 0 else "은")


def condition_lines(p: Program, labels: Mapping[str, str]) -> list[str]:
    """'누가 받나요' 줄. 표의 조건 칸을 '이름: 값' 꼴의 쉬운 말로 푼다."""
    out: list[str] = []
    if p.applicant == "농협경유":
        out.append("신청은 지역농협이 해요")
    if p.crop_in:
        out.append("작물: " + " · ".join(crop_names(p.crop_in, labels)))
    if p.crop_not_in:
        out.append(_eun(" · ".join(crop_names(p.crop_not_in, labels))) + " 안 돼요")
    if p.facility:
        out.append(f"재배 형태: {p.facility}")
    if p.sex:
        out.append("성별: 여성")
    if age := age_text(p):
        basis = _BASIS.get(p.age_basis or "")
        out.append(f"나이: {age}" + (f" ({basis})" if basis else ""))
    if p.region_in:
        out.append(f"{p.region_in}에 농지가 있어야 해요" if p.region_basis == "농지소재지"
                   else f"{p.region_in}에 살아야 해요" if p.region_basis == "주소지" else f"지역: {p.region_in}")
    if p.area_type_in:
        out.append("지역: " + ("읍·면에 살아야 해요" if p.area_type_in == "읍면" else "동에 살아야 해요"))
    if p.health_ins_in:
        out.append("건강보험: " + " · ".join({"지역": "지역가입자", "직장": "직장가입자", "피부양자": "피부양자"}[h] for h in p.health_ins_in))
    if p.needs_coop == "E" and p.needs_selfpay_fund == "E":
        out.append("농협 출하 또는 자조금 가입 중 하나는 해야 해요")
    else:
        if p.needs_coop:
            out.append("농협에 출하해야 해요" if p.needs_coop == "Y" else "농협 출하(또는 자조금 가입)")
        if p.needs_selfpay_fund:
            out.append("자조금에 가입해야 해요" if p.needs_selfpay_fund == "Y" else "자조금 가입(또는 농협 출하)")
    if p.needs_enrollment:
        out.append(_ENROLL_NOTE)
    if p.min_ha is not None or p.max_ha is not None:
        basis = _AREA_BASIS.get(p.area_basis or "")
        out.append("넓이: " + (f"{basis} " if basis else "") + area_text(p.min_ha, p.max_ha))
    if p.owns_land:
        out.append("땅: 내 땅이어야 해요" + (f" ({p.land_hold_years}년 이상 가지고 있어야 해요)" if p.land_hold_years else ""))
    if p.max_owned_ha is not None:
        out.append(f"가진 농지: {num(p.max_owned_ha)}ha 이하")
    if p.min_farming_years:
        out.append(f"농사 경력: {p.min_farming_years}년 이상")
    if p.min_residence_years:
        out.append(f"제주 거주: {p.min_residence_years}년 이상")
    if p.income_test == "상한":
        out.append(f"농사 말고 버는 소득이 {p.income_max_manwon:,}만 원 이하여야 해요" if p.income_max_manwon else "농사 말고 버는 소득에 상한이 있어요")
    elif p.income_test == "심사":
        out.append("소득을 심사해요")
    if p.needs_mgmt:
        out.append("농업경영체에 등록해야 해요" + (f" ({p.min_mgmt_years}년 이상)" if p.min_mgmt_years else ""))
    if p.event_type:
        out.append(_EVENT_WHO.get(p.event_type) or f"이런 일이 있어야 해요: {p.event_type}")
    return out


def check_items(p: Program) -> list[str]:
    """창구에서 확인하는 것: 표의 manual_check 를 ' / ' 로 나눈 그대로(표 글자)."""
    return [s for s in _split_top(p.manual_check or "") if s]


def _split_top(text: str) -> list[str]:
    """' / ' 로 나누되 괄호 안의 ' / '(예: '농지 종류(진흥지역 논·밭 / 밖 논 / 밖 밭)')는 자르지 않는다. 화면에 보이는 조각만 이렇게 나눈다(표 글자는 그대로)."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(text):
        c = text[i]
        depth += (c == "(") - (c == ")")
        if depth <= 0 and text.startswith(" / ", i):
            out.append(text[start:i].strip())
            start, i = i + 3, i + 3
            continue
        i += 1
    out.append(text[start:].strip())
    return out
