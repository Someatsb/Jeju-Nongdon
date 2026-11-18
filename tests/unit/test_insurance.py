"""Task 11(U11) 보험 판정: 재해·수입안정 택1(작물별), 작물별 가입 창, 안전보험 사람별 15~87세, 다시 오실 달.

결과 id = "<insurance.csv product_id>:<crop_code | owner | spouse>" (예: "crop_disaster:마늘", "nh_safety:owner").
"""
from datetime import date

import pytest

from app.core.calendar import revisit_calendar
from app.core.insurance import ONE_OF_CHECK, check_insurance
from app.core.models import FarmProfile, InsuranceResult, SourceRef
from app.core.tables_models import InsuranceProduct
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P3_KWARGS, P4_KWARGS, ROOT, T1_KWARGS, T2_KWARGS

BUNDLE = load_tables(ROOT / "data" / "tables", AS_OF)
PRODUCTS = BUNDLE.insurance
P1, P3, P4 = FarmProfile(**P1_KWARGS), FarmProfile(**P3_KWARGS), FarmProfile(**P4_KWARGS)
NO_MONTH = {"NOT_COVERED", "NOT_ELIGIBLE"}


def find(result_id: str, results: tuple[InsuranceResult, ...]) -> InsuranceResult:
    return next(r for r in results if r.product_id == result_id)


def status(result_id: str, results: tuple[InsuranceResult, ...]) -> str | None:
    return next((r.status for r in results if r.product_id == result_id), None)


def profile(base: dict = P1_KWARGS, **changes) -> FarmProfile:
    return FarmProfile(**{**base, **changes})


def profile_born(year: int | None, **changes) -> FarmProfile:
    return profile(birth_year=year, **changes)


def plot(crop_code: str, **flags) -> dict:
    return {"crop_code": crop_code, "area_m2": 3000, "sales_channel": "coop", "selfpay_fund": "paid", **flags}


def crops(*plots: dict, **changes) -> FarmProfile:
    return profile(crops=plots, total_area_m2=None, **changes)


# --- 브리프 네 줄 --------------------------------------------------------------------------

def test_open_citrus_income_not_covered():
    assert status("income_stab:감귤_노지", check_insurance(P1, PRODUCTS, AS_OF)) == "NOT_COVERED"


def test_garlic_disaster_open_now_on_1113():
    assert status("crop_disaster:마늘", check_insurance(P3, PRODUCTS, date(2026, 11, 13))) == "OPEN_NOW"


def test_cabbage_next_window_august():
    r = find("income_stab:양배추", check_insurance(P4, PRODUCTS, AS_OF))
    assert r.status == "NEXT_WINDOW" and r.next_window[0].month == 8


def test_safety_age_88_not_eligible():
    assert status("nh_safety:owner", check_insurance(profile_born(1937), PRODUCTS, AS_OF)) == "NOT_ELIGIBLE"  # 88~89


# --- 가입 창(실제 표) ------------------------------------------------------------------------

def test_open_window_is_the_current_one_and_revisit_is_this_month():
    r = find("crop_disaster:마늘", check_insurance(P3, PRODUCTS, AS_OF))
    assert r.next_window == (date(2026, 10, 12), date(2026, 11, 13)) and r.revisit_month == 11


def test_window_closed_yesterday_moves_to_next_year():
    r = find("crop_disaster:마늘", check_insurance(P3, PRODUCTS, date(2026, 11, 14)))
    assert (r.status, r.next_window, r.revisit_month) == (
        "NEXT_WINDOW", (date(2027, 10, 12), date(2027, 11, 13)), 10)


def test_next_windows_by_crop_on_the_shipped_table():
    p4 = check_insurance(P4, PRODUCTS, AS_OF)
    assert find("income_stab:양배추", p4).next_window == (date(2027, 8, 1), date(2027, 9, 30))
    assert find("crop_disaster:양배추", p4).next_window == (date(2027, 9, 2), date(2027, 10, 30))
    assert find("crop_disaster:양배추", p4).revisit_month == 9
    citrus = find("crop_disaster:감귤_노지", check_insurance(P1, PRODUCTS, AS_OF))
    assert (citrus.status, citrus.next_window, citrus.revisit_month) == (
        "NEXT_WINDOW", (date(2027, 4, 27), date(2027, 5, 29)), 4)


def test_mandarin_hybrid_is_covered_by_income_insurance():
    res = check_insurance(crops(plot("감귤_만감")), PRODUCTS, AS_OF)
    income, disaster = find("income_stab:감귤_만감", res), find("crop_disaster:감귤_만감", res)
    assert (income.status, income.next_window) == ("NEXT_WINDOW", (date(2027, 4, 27), date(2027, 5, 29)))
    assert disaster.status == "NEXT_WINDOW"
    assert "exclusive_with:crop_disaster" in income.reasons and "exclusive_with:income_stab" in disaster.reasons


def test_crop_without_any_row_is_not_covered_by_either_product():
    res = check_insurance(crops(plot("감자")), PRODUCTS, AS_OF)
    assert status("crop_disaster:감자", res) == status("income_stab:감자", res) == "NOT_COVERED"


# --- 택1(같은 작물·같은 밭) -----------------------------------------------------------------

def test_both_enrolled_on_one_crop_is_check_on_both():
    res = check_insurance(crops(plot("월동무", ins_disaster=True, ins_income=True)), PRODUCTS, AS_OF)
    for rid in ("crop_disaster:월동무", "income_stab:월동무"):
        r = find(rid, res)
        assert r.status == "CHECK" and ONE_OF_CHECK in r.reasons and r.revisit_month == 8
    assert ONE_OF_CHECK == "둘 중 하나만 가능, 농협 확인"


@pytest.mark.parametrize("flags, enrolled, other", [
    ({"ins_disaster": True}, "crop_disaster", "income_stab"),
    ({"ins_income": True, "ins_disaster": False}, "income_stab", "crop_disaster"),
])
def test_one_enrolled_makes_the_other_one_of_two(flags, enrolled, other):
    res = check_insurance(crops(plot("월동무", **flags)), PRODUCTS, AS_OF)
    mine, theirs = find(f"{enrolled}:월동무", res), find(f"{other}:월동무", res)
    assert (mine.status, mine.next_window, mine.revisit_month) == (
        "ENROLLED", (date(2027, 8, 1), date(2027, 10, 31)), 8)
    assert (theirs.status, theirs.reasons, theirs.next_window, theirs.revisit_month) == (
        "NOT_ELIGIBLE", (f"exclusive_with:{enrolled}",), None, None)


def test_one_of_is_per_plot_not_across_citrus_rows():
    # 노지 밭 재해보험 가입이 만감 밭 수입안정보험을 막지 않는다(같은 밭일 때만 택1)
    res = check_insurance(crops(plot("감귤_노지", ins_disaster=True), plot("감귤_만감")), PRODUCTS, AS_OF)
    assert status("crop_disaster:감귤_노지", res) == "ENROLLED"
    assert status("income_stab:감귤_노지", res) == "NOT_COVERED"
    assert status("income_stab:감귤_만감", res) == "NEXT_WINDOW"
    assert status("crop_disaster:감귤_만감", res) == "NEXT_WINDOW"


def test_not_yet_enrolled_pair_both_open_and_say_one_of_two():
    res = check_insurance(P3, PRODUCTS, AS_OF)
    disaster, income = find("crop_disaster:마늘", res), find("income_stab:마늘", res)
    assert (disaster.status, income.status) == ("OPEN_NOW", "OPEN_NOW")
    assert income.next_window == (date(2026, 10, 1), date(2026, 11, 30))
    assert "exclusive_with:income_stab" in disaster.reasons and "exclusive_with:crop_disaster" in income.reasons


def test_enrolled_flag_on_a_product_that_does_not_cover_the_crop_stays_not_covered():
    res = check_insurance(crops(plot("감귤_노지", ins_disaster=True, ins_income=True)), PRODUCTS, AS_OF)
    assert status("crop_disaster:감귤_노지", res) == "ENROLLED"
    assert status("income_stab:감귤_노지", res) == "NOT_COVERED"


# --- 다음에 오실 때(달력 셋째 칸) -------------------------------------------------------------

@pytest.mark.parametrize("kwargs, crop, months", [
    (T1_KWARGS, "감귤_노지", (4, 5)),
    (T2_KWARGS, "당근", (7, 9)),
])
def test_enrolled_renewal_month_feeds_the_calendar(kwargs, crop, months):
    res = check_insurance(FarmProfile(**kwargs), PRODUCTS, AS_OF)
    r = find(f"crop_disaster:{crop}", res)
    assert r.status == "ENROLLED" and (r.next_window[0].month, r.next_window[1].month) == months
    assert r.revisit_month == months[0]
    assert status(f"income_stab:{crop}", res) == "NOT_COVERED"
    assert status("nh_safety:owner", res) == status("nh_safety:spouse", res) == "ENROLLED"
    assert revisit_calendar((), res, AS_OF)[2].month == months[0]   # 골든 T1·T2 calendar_3


@pytest.mark.parametrize("prof", [P1, P3, P4, FarmProfile(**T1_KWARGS), profile_born(1938),
                                  crops(plot("월동무", ins_disaster=True))])
def test_revisit_month_only_where_the_calendar_should_show_it(prof):
    res = check_insurance(prof, PRODUCTS, AS_OF)
    assert res
    for r in res:
        if r.status in NO_MONTH or r.product_id.startswith("nh_safety:"):
            assert r.revisit_month is None, r      # 셋째 칸은 작물 보험 달. 안전보험·대상 아님은 안 올림
        else:
            assert r.revisit_month is not None, r


# --- 안전보험(사람별) ------------------------------------------------------------------------

def test_safety_is_per_person_owner_and_spouse_if_any():
    p3 = check_insurance(P3, PRODUCTS, AS_OF)   # 1955년생, 부인 함께 농사(미등록)
    owner, spouse = find("nh_safety:owner", p3), find("nh_safety:spouse", p3)
    assert (owner.status, owner.next_window, owner.revisit_month) == ("OPEN_NOW", None, None)
    assert spouse.status == "CHECK" and "age_unknown:15~87" in spouse.reasons  # 배우자 태어난 해는 안 받는다
    assert status("nh_safety:spouse", check_insurance(P1, PRODUCTS, AS_OF)) is None  # 배우자 없음


def test_safety_enrollment_is_per_person():
    res = check_insurance(profile(P3_KWARGS, ins_safety=frozenset({"spouse"})), PRODUCTS, AS_OF)
    assert (status("nh_safety:owner", res), status("nh_safety:spouse", res)) == ("OPEN_NOW", "ENROLLED")


@pytest.mark.parametrize("year, as_of, expected", [
    (1940, AS_OF, "OPEN_NOW"),                # 85~86
    (1939, AS_OF, "OPEN_NOW"),                # 86~87: 둘 다 안
    (1938, AS_OF, "CHECK"),                   # 87~88: 생신 확인
    (1937, AS_OF, "NOT_ELIGIBLE"),            # 88~89
    (1938, date(2026, 12, 31), "CHECK"),      # 해가 바뀌면 한 살씩: 2026 → 87~88, 2027 → 88~89
    (1938, date(2027, 1, 1), "NOT_ELIGIBLE"),
    (2010, AS_OF, "OPEN_NOW"),                # 15~16세
    (2010, date(2025, 11, 13), "CHECK"),      # 14~15세 (FarmProfile은 2010년생까지라 날짜를 당긴다)
    (2010, date(2024, 11, 13), "NOT_ELIGIBLE"),   # 13~14세
])
def test_safety_age_uses_application_date_bounds(year, as_of, expected):
    r = find("nh_safety:owner", check_insurance(profile_born(year), PRODUCTS, as_of))
    assert r.status == expected
    if expected != "OPEN_NOW":
        assert "age:15~87" in r.reasons


def test_safety_age_unknown_or_approximate_is_check():
    unknown = find("nh_safety:owner", check_insurance(profile_born(None), PRODUCTS, AS_OF))
    assert unknown.status == "CHECK" and unknown.reasons == ("age_unknown:15~87",)
    approx = find("nh_safety:owner", check_insurance(profile_born(1940, birth_year_approx=True), PRODUCTS, AS_OF))
    assert approx.status == "CHECK"         # 1938~1942년생으로 본다: 최대 88세


def test_safety_hold_source_is_tagged_and_only_then():
    hold = frozenset(f"supports:{p.id}" for p in BUNDLE.programs if p.status == "hold")
    assert "supports:NAT-SAFETY-INS@2026" in hold
    for prof in (P1, P3, profile(P3_KWARGS, ins_safety=frozenset({"owner"})), profile_born(1937)):
        res = check_insurance(prof, PRODUCTS, AS_OF, hold_source_ids=hold)
        safety = [r for r in res if r.product_id.startswith("nh_safety:")]
        assert safety and all("source_hold" in r.reasons for r in safety)
        assert not any("source_hold" in r.reasons for r in res if not r.product_id.startswith("nh_safety:"))
        assert not any("source_hold" in r.reasons for r in check_insurance(prof, PRODUCTS, AS_OF))


def test_window_start_day_is_open_now():
    prods = (product("income_stab", ("감자",), (("11-13", "12-31"),)),)
    r = only(prods, AS_OF)
    assert (r.status, r.next_window) == ("OPEN_NOW", (date(2026, 11, 13), date(2026, 12, 31)))


def test_two_plots_with_the_same_crop_get_distinct_ids():
    res = check_insurance(crops(plot("당근"), plot("당근", ins_disaster=True)), PRODUCTS, AS_OF)
    ids = [r.product_id for r in res]
    assert len(ids) == len(set(ids))
    assert {"crop_disaster:당근", "income_stab:당근", "crop_disaster:당근#2", "income_stab:당근#2"} <= set(ids)
    assert status("crop_disaster:당근#2", res) == "ENROLLED"


# --- 경영체(먼저 할 일) ------------------------------------------------------------------------

def test_missing_mgmt_before_the_window_is_next_window_with_prereq():
    r = find("income_stab:양배추", check_insurance(P4, PRODUCTS, AS_OF))   # 경영체 미등록
    assert r.reasons == ("exclusive_with:crop_disaster", "needs_mgmt") and r.revisit_month == 8


@pytest.mark.parametrize("mgmt", ["none", "unknown"])
def test_missing_mgmt_while_open_is_check(mgmt):
    res = check_insurance(profile(P3_KWARGS, mgmt_status=mgmt), PRODUCTS, AS_OF)
    garlic, owner = find("crop_disaster:마늘", res), find("nh_safety:owner", res)
    assert garlic.status == "CHECK" and "needs_mgmt" in garlic.reasons and garlic.revisit_month == 11
    assert owner.status == "CHECK" and owner.reasons == ("needs_mgmt",)


def test_enrolled_wins_over_missing_mgmt():
    res = check_insurance(profile(P4_KWARGS, ins_safety=frozenset({"owner"})), PRODUCTS, AS_OF)
    assert status("nh_safety:owner", res) == "ENROLLED"


# --- 합성 상품(창 계산) ------------------------------------------------------------------------

SRC = SourceRef(source_id="test", url=None, as_of=date(2026, 11, 7))


def product(kind: str, crop_keys: tuple[str, ...] | None, windows: tuple[tuple[str, str], ...], **kw) -> InsuranceProduct:
    return InsuranceProduct(product_id=kind, crop_keys=crop_keys, windows=windows, needs_mgmt=False,
                            office_id="coop", subsidy_text="", source=SRC, **kw)


def only(prods: tuple[InsuranceProduct, ...], as_of: date, crop: str = "감자") -> InsuranceResult:
    (r,) = [r for r in check_insurance(crops(plot(crop)), prods, as_of) if r.product_id == f"income_stab:{crop}"]
    return r


def test_window_across_new_year():
    prods = (product("income_stab", ("감자",), (("11-15", "02-15"),)),)
    r = only(prods, date(2027, 1, 10))
    assert (r.status, r.next_window, r.revisit_month) == ("OPEN_NOW", (date(2026, 11, 15), date(2027, 2, 15)), 1)
    r = only(prods, date(2027, 3, 1))
    assert (r.status, r.next_window, r.revisit_month) == ("NEXT_WINDOW", (date(2027, 11, 15), date(2028, 2, 15)), 11)


def test_two_windows_pick_the_soonest():
    prods = (product("income_stab", ("감자",), (("09-01", "09-30"), ("03-01", "03-31"))),)
    assert only(prods, date(2026, 5, 1)).next_window == (date(2026, 9, 1), date(2026, 9, 30))
    assert only(prods, date(2026, 10, 1)).next_window == (date(2027, 3, 1), date(2027, 3, 31))


def test_leap_day_end_in_a_common_year():
    prods = (product("income_stab", ("감자",), (("02-01", "02-29"),)),)
    assert only(prods, date(2027, 1, 5)).next_window == (date(2027, 2, 1), date(2027, 2, 28))


def test_no_windows_means_always_open():
    r = only((product("income_stab", ("감자",), ()),), AS_OF)
    assert (r.status, r.next_window, r.revisit_month) == ("OPEN_NOW", None, 11)


def test_only_kinds_present_in_the_table_are_judged():
    prods = (product("income_stab", ("양파",), (("10-01", "11-30"),)),)
    res = check_insurance(crops(plot("감자")), prods, AS_OF)
    assert [(r.product_id, r.status) for r in res] == [("income_stab:감자", "NOT_COVERED")]
    assert res[0].source == SRC                      # 대상 작물 목록이 있는 그 상품 행이 근거
    assert check_insurance(P1, (), AS_OF) == ()


def test_results_are_ordered_and_ids_unique():
    res = check_insurance(P3, PRODUCTS, AS_OF)
    assert [r.product_id for r in res] == [
        "crop_disaster:마늘", "income_stab:마늘", "crop_disaster:월동무", "income_stab:월동무",
        "nh_safety:owner", "nh_safety:spouse"]
    assert check_insurance(P3, PRODUCTS, AS_OF) == res


# --- insurance.csv 정합(supports.csv 보험 행과 같은 창·작물) --------------------------------------

def test_shipped_insurance_table_matches_supports_rows():
    by_id = {p.id: p for p in BUNDLE.programs}
    crop_codes = {c.crop_code for c in BUNDLE.crops}
    assert len(PRODUCTS) == 13
    for ins in PRODUCTS:
        assert ins.office_id in BUNDLE.offices
        assert set(ins.crop_keys or ()) <= crop_codes
        row = by_id[ins.source.source_id.removeprefix("supports:")]
        assert ins.source.url == row.source_url.split(" ; ")[0] and ins.source.as_of == row.verified_date
        if ins.product_id == "nh_safety":
            assert (ins.windows, ins.min_age, ins.max_age, ins.crop_keys) == ((), row.min_age, row.max_age, None)
        else:
            assert ins.crop_keys == row.crop_in
            assert ins.windows == ((row.apply_start.strftime("%m-%d"), row.apply_end.strftime("%m-%d")),)
        assert ins.needs_mgmt == (row.needs_mgmt == "Y")
