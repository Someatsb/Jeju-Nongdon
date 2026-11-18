"""달력(Task 4, U04): 반월 구간, 신청 창·다음 회차, D-day, '다음에 오실 때' 달력 3칸.

as_of는 늘 인자로 받는다. 표의 날짜는 작년(2026) 공고 값이라, 지난 창은 해를 옮겨 다음 회차로 본다.
"""
from collections.abc import Iterable
from datetime import date, timedelta

from app.core.models import ApplyWindow, CalendarSlot, InsuranceResult, Program, RowStatus

ALWAYS_OPEN_CYCLES = frozenset({"상시", "사후신청", "자동"})  # 정해진 창이 없다(사후신청은 사건 뒤 n일)
INSURANCE_KEY_PREFIXES = ("NAT-CROP-INS", "NAT-INCOME-INS")  # 달력 셋째 칸(작물 보험 달)
INTEGRATED_MONTH = 1   # 첫째 칸: 1월 농업보조사업 통합신청(통합공고)
ALLOWANCE_MONTH = 3    # 둘째 칸: 3월 농민수당·직불
_NO_INSURANCE_MONTH = frozenset({"NOT_COVERED", "NOT_ELIGIBLE"})


# --- 반월 ---------------------------------------------------------------------------------

def _month_end(d: date) -> date:
    first_of_next = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return first_of_next - timedelta(days=1)


def half_month(d: date) -> tuple[date, date]:
    """d가 든 반월(1~15일, 16일~말일)의 첫날과 끝날."""
    if d.day <= 15:
        return d.replace(day=1), d.replace(day=15)
    return d.replace(day=16), _month_end(d)


def half_months_between(start: date, end: date) -> list[tuple[date, date]]:
    """start~end(양끝 포함)에 걸치는 반월을 앞에서부터. 반월은 자르지 않은 온전한 구간이다."""
    if start > end:
        return []
    out: list[tuple[date, date]] = []
    h = half_month(start)
    while h[0] <= end:
        out.append(h)
        h = half_month(h[1] + timedelta(days=1))
    return out


# --- 신청 창 ------------------------------------------------------------------------------

def _add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 2월 29일 → 평년에는 2월 28일
        return d.replace(year=d.year + n, day=28)


def _years_to_reach(d: date, as_of: date, *, after: bool) -> int:
    """d를 몇 해 뒤로 옮겨야 as_of 이후가 되는지(after=False면 같은 날 포함). 앞당기지는 않는다."""
    k = max(0, as_of.year - d.year - 1)
    while (_add_years(d, k) <= as_of) if after else (_add_years(d, k) < as_of):
        k += 1
    return k


def _shifted(program: Program, k: int) -> tuple[date | None, date]:
    start = _add_years(program.apply_start, k) if program.apply_start else None
    return start, _add_years(program.apply_end, k)


def apply_window(program: Program, as_of: date) -> ApplyWindow:
    """신청 창. 열려 있으면 next_*는 지금 창, 아니면 다음 창이다.

    - 상시·사후신청·자동: always_open, open_now, 날짜 없음.
    - 연1회: 마감이 as_of 이후(당일 포함)가 될 때까지 작년 창을 1년씩 옮긴다(2026-03-09~31, 11-13 기준
      → 2027-03-09~31). 옮긴 창이든 아니든 as_of가 창 안(양끝 포함)이면 open_now. 옮긴 창은 작년 날짜라
      배지는 행 상태가 맡는다. 시작일이 빈 행은 마감만 옮기고, 열렸는지 모르므로 open_now=False
      (마감은 next_end로 남는다).
    - apply_cycle·apply_end가 없으면 모름: 모두 False·None.
    """
    if program.apply_cycle in ALWAYS_OPEN_CYCLES:
        return ApplyWindow(always_open=True, open_now=True, next_start=None, next_end=None)
    if program.apply_cycle != "연1회" or program.apply_end is None:
        return ApplyWindow(always_open=False, open_now=False, next_start=None, next_end=None)
    k = _years_to_reach(program.apply_end, as_of, after=False)
    start, end = _shifted(program, k)
    open_now = start is not None and start <= as_of  # end ≥ as_of는 k를 고를 때 이미 맞췄다
    return ApplyWindow(always_open=False, open_now=open_now, next_start=start, next_end=end)


def days_until(d: date, as_of: date) -> int:
    """as_of에서 d까지 날 수(당일 0, 지났으면 음수)."""
    return (d - as_of).days


# --- 다음에 오실 때: 달력 3칸 ----------------------------------------------------------------

_Upcoming = tuple[Program, int, date | None, date, bool]  # (행, 달, 시작, 마감, 작년 창을 옮김)


def _upcoming(program: Program, as_of: date) -> _Upcoming | None:
    """as_of 뒤에 시작하는 첫 연1회 창. 지금 열린 창은 '급한 것'이 다루므로 다음 회차로 넘긴다."""
    if program.status == "hold" or program.apply_cycle != "연1회" or program.apply_end is None:
        return None
    k = _years_to_reach(program.apply_start or program.apply_end, as_of, after=True)
    start, end = _shifted(program, k)
    month = program.next_month or (start or end).month
    return program, month, start, end, k > 0


_DIRECT_PREFIX = "NAT-DIRECT"    # 직불 행(달력 둘째 칸의 나머지는 수당 쪽)
_INCOME_PREFIX = "NAT-INCOME-INS"


def _months(members: list[_Upcoming]) -> str:
    """제도 묶음의 신청 달 범위('3월', '3~5월'). 표의 시작·마감 날짜에서만 만든다(시작일이 없으면 마감 달)."""
    first = min((s or e).month for _, _, s, e, _ in members)
    last = max(e.month for _, _, _, e, _ in members)
    return f"{first}월" if first == last else f"{first}~{last}월"


def _label(kind: str, members: list[_Upcoming]) -> str | None:
    """한 칸에 제도가 여럿일 때의 설명(없으면 None: 템플릿이 칸 이름을 쓴다)."""
    if kind == "allowance_direct":
        direct = [u for u in members if u[0].program_key.startswith(_DIRECT_PREFIX)]
        other = [u for u in members if not u[0].program_key.startswith(_DIRECT_PREFIX)]
        if direct and other:
            return f"직불 {_months(direct)} · 수당 {_months(other)}"
    elif kind == "insurance":
        if {u[0].program_key.startswith(_INCOME_PREFIX) for u in members} == {True, False}:
            return "작물 보험(둘 중 하나)"
    return None


def _slot(kind: str, month: int | None, members: list[_Upcoming]) -> CalendarSlot:
    if not members:
        return CalendarSlot(kind=kind, month=month, start=None, end=None, programs=(), row_status=None)
    windows = tuple(sorted((p.id, s, e) for p, _, s, e, _ in members))
    # 칸의 창은 제도들의 합집합이다(가장 이른 시작 ~ 가장 늦은 마감). 일부만 열린 날도 포함되므로 칸의 label이
    # 제도별 달을 함께 적는다(수당 3월·직불 3~5월을 한 날짜로 오해하지 않게). 시작일을 모르는 제도가 있으면 날짜는 비운다.
    start = end = None
    if all(s is not None for _, s, _ in windows):
        start, end = min(s for _, s, _ in windows), max(e for _, _, e in windows)
    prior = any(p.status == "prior_year_reference" or moved for p, _, _, _, moved in members)
    status: RowStatus = "prior_year_reference" if prior else "confirmed"
    return CalendarSlot(kind=kind, month=month, start=start, end=end, programs=windows, row_status=status,
                        label=_label(kind, members))


def revisit_calendar(programs: Iterable[Program], insurance: tuple[InsuranceResult, ...],
                     as_of: date) -> tuple[CalendarSlot, CalendarSlot, CalendarSlot]:
    """'다음에 오실 때' 달력 3칸: 1월 통합공고 / 3월 수당·직불 / 작물 보험 달.

    programs는 이 농가에 해당하는 행만 넘긴다(매칭이 거른 것, 이미 받는 것 포함). hold 행은 뺀다.
    첫째·둘째 칸은 달이 고정이고, 그 달(next_month, 없으면 시작 달)에 다음 창이 시작하는 행을 모은다.
    셋째 칸의 달은 insurance(Task 11 보험 판정)가 있으면 그 판정만 따른다: 대상 아님·보장 안 됨을 뺀
    결과의 revisit_month 중 가장 먼저 오는 달, 없으면 None(표 행으로 되살리지 않는다).
    insurance가 비었을 때만 program_key가 NAT-CROP-INS·NAT-INCOME-INS인 행 중 다음 창이 가장 먼저
    시작하는 달을 쓴다. 칸의 날짜·제도는 그 달의 보험 행에서 온다.
    """
    upcoming = [u for p in programs if (u := _upcoming(p, as_of)) is not None]
    is_ins = [u for u in upcoming if u[0].program_key.startswith(INSURANCE_KEY_PREFIXES)]
    others = [u for u in upcoming if not u[0].program_key.startswith(INSURANCE_KEY_PREFIXES)]

    ins_month: int | None = None
    ins_members = is_ins
    if insurance:
        live = [r for r in insurance if r.revisit_month and r.status not in _NO_INSURANCE_MONTH]
        if live:
            ins_month = min((r.revisit_month for r in live), key=lambda m: (m - as_of.month) % 12)
            # 같은 작물의 보험 상품(재해보험·수입안정보험)은 시작일이 달라도 한 칸: 합집합으로 찍는다
            crops = {r.product_id.split(":", 1)[-1].split("#", 1)[0] for r in live if r.revisit_month == ins_month}
            ids = {r.source.source_id.removeprefix("supports:") for r in insurance
                   if r.status not in _NO_INSURANCE_MONTH and r.product_id.split(":", 1)[-1].split("#", 1)[0] in crops}
            ins_members = [u for u in is_ins if u[0].id in ids] or [u for u in is_ins if u[1] == ins_month]
    elif is_ins:
        ins_month = min(is_ins, key=lambda u: u[2] or u[3])[1]
        ins_members = [u for u in is_ins if u[1] == ins_month]

    return (
        _slot("integrated", INTEGRATED_MONTH, [u for u in others if u[1] == INTEGRATED_MONTH]),
        _slot("allowance_direct", ALLOWANCE_MONTH, [u for u in others if u[1] == ALLOWANCE_MONTH]),
        _slot("insurance", ins_month, ins_members if ins_month else []),
    )
