"""Task 4(U04) 달력: 반월 구간, 신청 창·다음 회차, D-day, "다음에 오실 때" 달력 3칸."""
from datetime import date

import pytest

from app.core.calendar import apply_window, days_until, half_month, half_months_between, revisit_calendar
from app.core.models import ApplyWindow, CalendarSlot, InsuranceResult, Program, SourceRef

AS_OF = date(2026, 11, 13)


def prog(pid: str, cycle: str | None = "연1회", start: date | None = None, end: date | None = None,
         next_month: int | None = None, status: str = "prior_year_reference") -> Program:
    """supports.csv 한 행 중 달력에 쓰는 칸만 채운 Program. pid는 표의 id(예: "NAT-CROP-INS@2026#감귤")."""
    key, edition = pid.split("@")[0], pid.split("@")[1].split("#")[0]
    return Program(id=pid, program_key=key, edition=edition, status=status, apply_cycle=cycle,
                   apply_start=start, apply_end=end, next_month=next_month)


# supports.csv 값 그대로(2026년 기준 행)
FARMER_ALLOW_2026 = prog("JEJU-FARMER-ALLOW@2026", start=date(2026, 3, 9), end=date(2026, 3, 31), next_month=3)
DIRECT_AREA_2026 = prog("NAT-DIRECT-AREA@2026", start=date(2026, 3, 1), end=date(2026, 5, 31), next_month=3)
SMALLFARM_2026 = prog("JEJU-SMALLFARM@2026", start=date(2026, 2, 3), end=date(2026, 2, 23), next_month=2)
WINDBREAK_2026 = prog("JS-WINDBREAK@2026", start=date(2026, 1, 2), end=date(2026, 1, 16), next_month=1)
CALCIUM_2026 = prog("DO-CALCIUM-SULFUR@2026", start=date(2026, 1, 2), end=date(2026, 1, 16), next_month=1)
CROP_INS_CITRUS = prog("NAT-CROP-INS@2026#감귤", start=date(2026, 4, 27), end=date(2026, 5, 29), next_month=4)
CROP_INS_CARROT = prog("NAT-CROP-INS@2026#당근", start=date(2026, 7, 1), end=date(2026, 9, 30), next_month=7)
CROP_INS_GARLIC = prog("NAT-CROP-INS@2026#마늘", start=date(2026, 10, 12), end=date(2026, 11, 13), next_month=10,
                       status="confirmed")
INCOME_INS_GARLIC = prog("NAT-INCOME-INS@2026#마늘", start=date(2026, 10, 1), end=date(2026, 11, 30), next_month=10,
                         status="confirmed")
CROP_INS_RADISH = prog("NAT-CROP-INS@2026#월동무", start=date(2026, 8, 1), end=date(2026, 10, 31), next_month=8)
INCOME_INS_RADISH = prog("NAT-INCOME-INS@2026#월동무", start=date(2026, 8, 1), end=date(2026, 10, 31), next_month=8)
PSTAB_CARROT = prog("JEJU-PSTAB@2026-27#당근", start=None, end=date(2025, 10, 31), next_month=9)
FARMLAND_PENSION = prog("KRC-FARMLAND-PENSION@2026", cycle="상시", status="confirmed")


# --- 계획서 Step 1(그대로) ---

def test_half_month_feb(): assert half_month(date(2026, 2, 20)) == (date(2026, 2, 16), date(2026, 2, 28))


def test_apply_window_next_year_when_closed(): w = apply_window(FARMER_ALLOW_2026, date(2026, 11, 13)); assert not w.open_now and w.next_start == date(2027, 3, 9)


# --- 반월 ---

@pytest.mark.parametrize("d, expected", [
    (date(2026, 11, 1), (date(2026, 11, 1), date(2026, 11, 15))),
    (date(2026, 11, 15), (date(2026, 11, 1), date(2026, 11, 15))),
    (date(2026, 11, 16), (date(2026, 11, 16), date(2026, 11, 30))),
    (date(2026, 12, 31), (date(2026, 12, 16), date(2026, 12, 31))),
    (date(2028, 2, 20), (date(2028, 2, 16), date(2028, 2, 29))),   # 윤년
])
def test_half_month_bounds(d, expected):
    assert half_month(d) == expected


def test_half_months_between_covers_both_ends_in_order():
    assert half_months_between(date(2026, 11, 10), date(2026, 12, 20)) == [
        (date(2026, 11, 1), date(2026, 11, 15)), (date(2026, 11, 16), date(2026, 11, 30)),
        (date(2026, 12, 1), date(2026, 12, 15)), (date(2026, 12, 16), date(2026, 12, 31)),
    ]
    assert half_months_between(date(2026, 12, 16), date(2027, 1, 1)) == [
        (date(2026, 12, 16), date(2026, 12, 31)), (date(2027, 1, 1), date(2027, 1, 15)),
    ]
    assert half_months_between(date(2026, 11, 13), date(2026, 11, 13)) == [(date(2026, 11, 1), date(2026, 11, 15))]
    assert half_months_between(date(2026, 12, 1), date(2026, 11, 30)) == []


def test_half_months_between_inverted_inside_one_half_month_is_empty():
    assert half_months_between(date(2026, 12, 10), date(2026, 12, 5)) == []


# --- 신청 창 ---

def test_apply_window_open_through_last_day():
    w = apply_window(CROP_INS_GARLIC, AS_OF)   # 마늘 재해보험 10.12~11.13, 기준일이 마감일
    assert w == ApplyWindow(always_open=False, open_now=True, next_start=date(2026, 10, 12), next_end=date(2026, 11, 13))
    assert not apply_window(CROP_INS_GARLIC, date(2026, 11, 14)).open_now
    assert apply_window(CROP_INS_GARLIC, date(2026, 11, 14)).next_start == date(2027, 10, 12)


def test_apply_window_upcoming_this_year():
    w = apply_window(FARMER_ALLOW_2026, date(2026, 2, 1))
    assert w == ApplyWindow(always_open=False, open_now=False, next_start=date(2026, 3, 9), next_end=date(2026, 3, 31))


def test_apply_window_closed_window_next_end_moves_too():
    w = apply_window(FARMER_ALLOW_2026, AS_OF)
    assert w == ApplyWindow(always_open=False, open_now=False, next_start=date(2027, 3, 9), next_end=date(2027, 3, 31))


def test_apply_window_shifted_window_containing_as_of_is_open():
    # 작년(2026) 창을 옮긴 2027-03-09~31 안의 날이면 열린 것이다(지난 next_start를 '다음'으로 내주지 않는다)
    w = apply_window(FARMER_ALLOW_2026, date(2027, 3, 15))
    assert w == ApplyWindow(always_open=False, open_now=True, next_start=date(2027, 3, 9), next_end=date(2027, 3, 31))
    w = apply_window(FARMER_ALLOW_2026, date(2027, 3, 31))   # 옮긴 창의 마감일
    assert w.open_now and w.next_end == date(2027, 3, 31)
    assert not apply_window(FARMER_ALLOW_2026, date(2027, 4, 1)).open_now


def test_start_day_boundary():
    # as_of == apply_start: 그날부터 열린다(행의 창이든 옮긴 창이든)
    assert apply_window(FARMER_ALLOW_2026, date(2026, 3, 9)) == ApplyWindow(
        always_open=False, open_now=True, next_start=date(2026, 3, 9), next_end=date(2026, 3, 31))
    assert apply_window(FARMER_ALLOW_2026, date(2027, 3, 9)).open_now
    assert not apply_window(FARMER_ALLOW_2026, date(2026, 3, 8)).open_now
    # 달력은 '다음에 시작하는' 창: 시작 당일이면 이미 열렸으니 다음 회차, 전날이면 이번 회차
    on_start = revisit_calendar((FARMER_ALLOW_2026,), (), date(2026, 3, 9))[1]
    assert (on_start.start, on_start.end) == (date(2027, 3, 9), date(2027, 3, 31))
    day_before = revisit_calendar((FARMER_ALLOW_2026,), (), date(2026, 3, 8))[1]
    assert (day_before.start, day_before.end) == (date(2026, 3, 9), date(2026, 3, 31))


def test_apply_window_always_open_kinds():
    for cycle in ("상시", "사후신청", "자동"):
        w = apply_window(prog("X@2026", cycle=cycle, status="confirmed"), AS_OF)
        assert w == ApplyWindow(always_open=True, open_now=True, next_start=None, next_end=None), cycle


def test_apply_window_deadline_only_row_skips_stale_years():
    # 가격안정관리제 당근: 시작일 없이 "2025-10-31까지"만 있는 행 → 2026-10-31도 지났으니 2027-10-31
    w = apply_window(PSTAB_CARROT, AS_OF)
    assert w == ApplyWindow(always_open=False, open_now=False, next_start=None, next_end=date(2027, 10, 31))
    # 시작일을 모르면 열렸는지 모른다 → open_now=False, 마감은 next_end로 남긴다
    assert apply_window(PSTAB_CARROT, date(2025, 10, 1)) == ApplyWindow(
        always_open=False, open_now=False, next_start=None, next_end=date(2025, 10, 31))


def test_apply_window_unknown_without_cycle_or_deadline():
    blank = ApplyWindow(always_open=False, open_now=False, next_start=None, next_end=None)
    assert apply_window(prog("X@2026", cycle=None), AS_OF) == blank
    assert apply_window(prog("X@2026", start=date(2026, 3, 1), end=None), AS_OF) == blank


def test_apply_window_leap_day_start_moves_to_feb_28():
    p = prog("X@2024", start=date(2024, 2, 29), end=date(2024, 3, 10))
    w = apply_window(p, date(2025, 6, 1))
    assert (w.next_start, w.next_end) == (date(2026, 2, 28), date(2026, 3, 10))
    w = apply_window(p, date(2027, 6, 1))   # 2028은 윤년: 다시 29일
    assert (w.next_start, w.next_end) == (date(2028, 2, 29), date(2028, 3, 10))


def test_days_until():
    assert days_until(date(2026, 11, 13), AS_OF) == 0
    assert days_until(date(2026, 11, 30), AS_OF) == 17
    assert days_until(date(2026, 11, 12), AS_OF) == -1
    assert days_until(date(2027, 3, 9), AS_OF) == 116


# --- 다음에 오실 때: 달력 3칸(1월 통합공고 / 3월 수당·직불 / 작물 보험 달) ---

def test_revisit_calendar_t1_citrus_months():   # 골든 T1 calendar_3 = 1월·3월·4월
    s1, s2, s3 = revisit_calendar((FARMER_ALLOW_2026, DIRECT_AREA_2026, WINDBREAK_2026, CROP_INS_CITRUS,
                                   SMALLFARM_2026, FARMLAND_PENSION), (), AS_OF)
    assert [s.kind for s in (s1, s2, s3)] == ["integrated", "allowance_direct", "insurance"]
    assert [s.month for s in (s1, s2, s3)] == [1, 3, 4]
    assert s1 == CalendarSlot(kind="integrated", month=1, start=date(2027, 1, 2), end=date(2027, 1, 16),
                              programs=(("JS-WINDBREAK@2026", date(2027, 1, 2), date(2027, 1, 16)),),
                              row_status="prior_year_reference")
    assert s2.program_ids == ("JEJU-FARMER-ALLOW@2026", "NAT-DIRECT-AREA@2026")   # 2월 소규모는 칸 밖
    # 칸의 창 = 합집합: 가장 이른 시작(직불 3/1) ~ 가장 늦은 마감(직불 5/31). 라벨이 제도별 달을 적는다(수당 3월만 3/31까지)
    assert (s2.start, s2.end) == (date(2027, 3, 1), date(2027, 5, 31))
    assert s2.label == "직불 3~5월 · 수당 3월"
    assert s2.programs == (("JEJU-FARMER-ALLOW@2026", date(2027, 3, 9), date(2027, 3, 31)),
                           ("NAT-DIRECT-AREA@2026", date(2027, 3, 1), date(2027, 5, 31)))
    assert s3.program_ids == ("NAT-CROP-INS@2026#감귤",) and s3.start == date(2027, 4, 27)


def test_revisit_calendar_no_overlap_takes_union_window():
    early = prog("NAT-DIRECT-SMALL@2026", start=date(2026, 3, 1), end=date(2026, 3, 5), next_month=3)
    s2 = revisit_calendar((FARMER_ALLOW_2026, early), (), AS_OF)[1]
    assert (s2.start, s2.end) == (date(2027, 3, 1), date(2027, 3, 31))   # 3/1~3/5와 3/9~3/31: 합집합(가장 이른 시작~가장 늦은 마감)
    assert s2.programs == (("JEJU-FARMER-ALLOW@2026", date(2027, 3, 9), date(2027, 3, 31)),
                           ("NAT-DIRECT-SMALL@2026", date(2027, 3, 1), date(2027, 3, 5)))
    assert s2.row_status == "prior_year_reference"


def test_revisit_calendar_unknown_start_leaves_slot_dates_empty():
    no_start = prog("JEJU-X@2026", start=None, end=date(2026, 3, 20), next_month=3)
    s2 = revisit_calendar((FARMER_ALLOW_2026, no_start), (), AS_OF)[1]
    assert (s2.start, s2.end) == (None, None)
    assert ("JEJU-X@2026", None, date(2027, 3, 20)) in s2.programs


def test_revisit_calendar_t2_carrot_insurance_month():   # 골든 T2 calendar_3 = 1월·3월·7월
    slots = revisit_calendar((CALCIUM_2026, FARMER_ALLOW_2026, CROP_INS_CARROT, PSTAB_CARROT), (), AS_OF)
    assert [s.month for s in slots] == [1, 3, 7]


def test_revisit_calendar_open_window_goes_to_next_cycle():
    # P3: 마늘 보험은 오늘 마감(급한 것 묶음) → 달력은 다음에 시작하는 월동무 8월
    s3 = revisit_calendar((CROP_INS_GARLIC, INCOME_INS_GARLIC, CROP_INS_RADISH, INCOME_INS_RADISH), (), AS_OF)[2]
    assert s3.month == 8 and s3.start == date(2027, 8, 1)
    assert s3.program_ids == ("NAT-CROP-INS@2026#월동무", "NAT-INCOME-INS@2026#월동무")


def test_revisit_calendar_projected_confirmed_row_carries_prior_badge():
    # 올해 확정 행이라도 내년 창은 작년 날짜를 옮긴 값 → 배지 대상
    s3 = revisit_calendar((CROP_INS_GARLIC,), (), AS_OF)[2]
    assert s3.start == date(2027, 10, 12) and s3.row_status == "prior_year_reference"


def test_revisit_calendar_this_years_upcoming_confirmed_row_stays_confirmed():
    p = prog("NAT-CROP-INS@2026#감귤", start=date(2026, 4, 27), end=date(2026, 5, 29), next_month=4, status="confirmed")
    s3 = revisit_calendar((p,), (), date(2026, 2, 1))[2]
    assert s3.start == date(2026, 4, 27) and s3.row_status == "confirmed"


def test_revisit_calendar_skips_hold_rows_and_keeps_empty_slots():
    held = prog("JS-WINDBREAK@2026", start=date(2026, 1, 2), end=date(2026, 1, 16), next_month=1, status="hold")
    s1, s2, s3 = revisit_calendar((held,), (), AS_OF)
    assert s1 == CalendarSlot(kind="integrated", month=1, start=None, end=None, programs=(), row_status=None)
    assert s2.month == 3 and s2.program_ids == ()
    assert s3 == CalendarSlot(kind="insurance", month=None, start=None, end=None, programs=(), row_status=None)


def test_revisit_calendar_insurance_revisit_month_wins():
    src = SourceRef(source_id="notice:test", url=None, as_of=AS_OF)
    ins = (InsuranceResult(product_id="NAT-CROP-INS#월동무", status="NEXT_WINDOW", next_window=None, revisit_month=8,
                           reasons=(), source=src),
           InsuranceResult(product_id="NAT-CROP-INS#당근", status="NOT_ELIGIBLE", next_window=None, revisit_month=2,
                           reasons=(), source=src))
    # 표만 보면 감귤 4월이 먼저지만, 보험 판정이 정한 재방문 달(8월)을 따른다. 대상 아님(2월)은 무시
    s3 = revisit_calendar((CROP_INS_CITRUS, CROP_INS_RADISH), ins, AS_OF)[2]
    assert s3.month == 8 and s3.program_ids == ("NAT-CROP-INS@2026#월동무",) and s3.start == date(2027, 8, 1)


def test_revisit_calendar_same_crop_insurance_products_take_union_window():
    # P4 양배추: 재해보험 9/2~10/30과 수입안정보험 8/1~9/30은 한 칸 — 8/1~10/30, 라벨은 시작일을 농협에 확인하라고 적는다
    crop = prog("NAT-CROP-INS@2026#양배추", start=date(2026, 9, 2), end=date(2026, 10, 30), next_month=9)
    income = prog("NAT-INCOME-INS@2026#양배추", start=date(2026, 8, 1), end=date(2026, 9, 30), next_month=8)
    other = prog("NAT-CROP-INS@2026#월동무", start=date(2026, 8, 1), end=date(2026, 10, 31), next_month=8)   # 다른 작물은 안 섞는다
    ins = tuple(InsuranceResult(product_id=pid, status="NEXT_WINDOW", next_window=None, revisit_month=m, reasons=(),
                                source=SourceRef(source_id=f"supports:{row.id}", url=None, as_of=AS_OF))
                for pid, m, row in (("crop_disaster:양배추", 9, crop), ("income_stab:양배추", 8, income)))
    s3 = revisit_calendar((crop, income, other), ins, AS_OF)[2]
    assert s3.month == 8 and (s3.start, s3.end) == (date(2027, 8, 1), date(2027, 10, 30))
    assert s3.program_ids == ("NAT-CROP-INS@2026#양배추", "NAT-INCOME-INS@2026#양배추")
    assert s3.label == "작물 보험(둘 중 하나)"


def test_revisit_calendar_ineligible_insurance_does_not_fall_back_to_table():
    # 보험 판정이 있으면 그것만 따른다: 전부 대상 아님·보장 안 됨이면 표 행으로 보험 달을 되살리지 않는다
    src = SourceRef(source_id="notice:test", url=None, as_of=AS_OF)
    ins = (InsuranceResult(product_id="NAT-CROP-INS#감귤", status="NOT_ELIGIBLE", next_window=None, revisit_month=4,
                           reasons=(), source=src),
           InsuranceResult(product_id="NAT-INCOME-INS#만감류", status="NOT_COVERED", next_window=None,
                           revisit_month=None, reasons=(), source=src))
    s3 = revisit_calendar((CROP_INS_CITRUS,), ins, AS_OF)[2]
    assert s3 == CalendarSlot(kind="insurance", month=None, start=None, end=None, programs=(), row_status=None)
