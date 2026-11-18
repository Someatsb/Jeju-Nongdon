"""Task 5(U05) 매칭 1: 조건 컬럼마다 PASS/FAIL/UNKNOWN, 네 묶음, hold 제외, 나이 경계.
Task 10(U10) 매칭 2: 이미 받음(ALREADY), 택1(EXCLUSIVE_OTHER), what_if."""
from datetime import date
from decimal import Decimal
from typing import NamedTuple

import pytest
from pydantic import ValidationError

from app.core.match import apply_changes, match_supports, what_if
from app.core.match_rules import AREA_DIRECT_WON_PER_HA
from app.core.models import FarmProfile, MatchResult, Program
from app.core.units import py_to_m2
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS


@pytest.fixture
def bundle(tables_dir):
    return load_tables(tables_dir, AS_OF)


def run(profile: FarmProfile, bundle, as_of: date = AS_OF, extra: tuple[Program, ...] = ()) -> tuple[MatchResult, ...]:
    return match_supports(profile, bundle.programs + extra, as_of, crops=bundle.crops)


def status_of(program_id: str, results: tuple[MatchResult, ...]) -> str | None:
    return next((m.status for m in results if m.program_id == program_id), None)


def find(program_id: str, results: tuple[MatchResult, ...]) -> MatchResult:
    return next(m for m in results if m.program_id == program_id)


def cond(m: MatchResult, field: str) -> str:
    return next(c.result for c in m.conds if c.field == field)


def profile(base: dict, **changes) -> FarmProfile:
    return FarmProfile(**{**base, **changes})


def plot(crop: str, py: int, sales: str = "coop", fund: str = "paid") -> dict:
    return {"crop_code": crop, "area_m2": py_to_m2(py), "sales_channel": sales, "selfpay_fund": fund}


def profile_born(year: int) -> FarmProfile:
    """P1(노지감귤 1,500평 자가 2년+, 영농 45년)에서 태어난 해만 바꾼다."""
    return profile(P1_KWARGS, birth_year=year)


# --- round1-B-data.md §2-5 변환 예시 13건 ---------------------------------------------------
# 예시 행마다 농가 하나를 골라 B §2-3 묶음 규칙(맞음/안 맞음/모름)으로 기대 상태를 손으로 정했다.
# 표 행은 지금 supports.csv 값으로 판정한다(예: 소농직불 max_ha는 B 초안 0.5가 아니라 표의 0.86).
# manual_check(직원 확인 항목)는 묶음에 넣지 않고 결과에 실어 뒷면에 찍는다(fix 1 레저 결정): 모두 맞으면 LIKELY.

# 2,000평(0.66ha) 당근 농가, 계통·자조금, 경영체 2년+ — B §2-5 "계산 예"의 농가. 받고 있는 제도 없음.
CARROT_2000PY = {**P2_KWARGS, "crops": (plot("당근", 2000),), "total_area_m2": py_to_m2(2000),
                 "already_receiving": frozenset()}
# 골든 B02: 양배추 1,500평 자가, 1941년생.
B02_1941 = {**P1_KWARGS, "birth_year": 1941, "crops": (plot("양배추", 1500),)}
# 골든 B06: 월동무 302평(998㎡) — 0.1ha(1,000㎡) 바로 아래.
B06_302PY = {**P1_KWARGS, "crops": (plot("월동무", 302, fund="unknown"),), "total_area_m2": py_to_m2(302)}

# B §2-5 #13: 출처(source_url)가 없어 status=hold로 둔 재해복구비 초안 행. 지금 표의 NAT-DISASTER-RECOVERY@2026은
# 근거를 찾아 confirmed가 됐으므로, B가 적은 초안 행을 그대로 만들어 넣고 결과에서 빠지는지 본다.
B13_DRAFT_HOLD = Program(id="DISASTER-RECOVERY@2026", program_key="DISASTER-RECOVERY", edition="2026", status="hold",
                         applicant="개인", trigger="disaster", apply_cycle="사후신청", apply_within_days=10,
                         amount_type="없음", amount_note="현장조사 후 결정",
                         manual_check="피해 사진 지참 / 피해율 기준(실험판엔 20%·70%로 적혀 있음)")


class BCase(NamedTuple):
    no: int
    program_id: str
    profile: dict
    expected: str | None   # None = 결과에서 빠짐(hold)
    why: str


B_CASES = [
    BCase(1, "JEJU-FARMER-ALLOW@2026", P4_KWARGS, "BLOCKED_PREREQ",
          "경영체 미등록 → needs_mgmt·min_mgmt_years만 FAIL(고칠 수 있음), 거주 3년 PASS, 건보·소득 모름"),
    BCase(2, "NAT-DIRECT-SMALL@2026", {**P1_KWARGS, "mgmt_status": "none"}, "BLOCKED_PREREQ",
          "B 본문 예: 소농 0.5ha 농가가 경영체 미등록이면 '먼저 할 일 — 경영체 등록'"),
    BCase(3, "NAT-DIRECT-AREA@2026", CARROT_2000PY, "EXCLUSIVE_OTHER",
          "0.66ha 경작·경영체 PASS, 소득 상한 모름 → 확인 후보지만(B 계산 예 약 90만~142만 원), "
          "Task 10 택1: 0.66ha × 150만 = 99만 < 소농 130만 → 소농직불을 남김"),
    BCase(4, "KRC-FARMLAND-PENSION@2026", P1_KWARGS, "LIKELY",
          "연말 기준 74세·영농 45년·자가·2년 보유 모두 PASS(지목·거리·채권은 manual_check 꼬리표)"),
    BCase(5, "NAT-RETIRE-DIRECT@2026", B02_1941, "CHECK",
          "신청일 기준 84~85세 → max_age 84 모름(생신 확인), 보유 3년은 '2년 넘음'만 알아 모름"),
    BCase(6, "JEJU-PSTAB@2026-27#당근", {**CARROT_2000PY, "crops": (plot("당근", 2000, fund="not_paid"),)},
          "BLOCKED_PREREQ", "골든 B12: 계통 Y·자조금 N → 자조금 FAIL, 참여 신청 모름 → 먼저 할 일"),
    BCase(7, "JEJU-LOGI@2026-27", P3_KWARGS, "BLOCKED_PREREQ",
          "물류비 작물은 월동무만(마늘 제외): 상인 밭떼기 → 계통 FAIL, 자조금 모름"),
    BCase(8, "JEJU-SOIL-ECO@2026", P5_KWARGS, "LIKELY",
          "브로콜리 ∈ 월동채소 그룹, 계통 또는 자조금(E) 중 계통 PASS"),
    BCase(9, "NAT-INCOME-INS@2026#월동무", B06_302PY, "NOT_ELIGIBLE",
          "골든 B06: 해당작물 998㎡ < 0.1ha → min_ha FAIL(고칠 수 없음)"),
    BCase(10, "NAT-CROP-INS@2026#당근", P2_KWARGS, "LIKELY",
          "당근 9,917㎡ ≥ 0.03ha·경영체 PASS(출현율 80%는 manual_check 꼬리표)"),
    BCase(11, "DO-SMALL-MACHINE@2026", P1_KWARGS, "NOT_ELIGIBLE",
          "노지감귤은 밭작물이 아니고 과수(제외 작물) → crop_in·crop_not_in FAIL"),
    BCase(12, "DO-CALCIUM-SULFUR@2026", CARROT_2000PY, "LIKELY",
          "당근 0.66ha(0.1~5ha)·경영체 PASS(B 계산 예 66포 × 2,000원)"),
    BCase(13, "DISASTER-RECOVERY@2026", P1_KWARGS, None,
          "출처 없는 초안 행 = hold → 결과에서 빠짐(인쇄 안 됨)"),
]


@pytest.mark.parametrize("case", B_CASES, ids=[f"B{c.no}" for c in B_CASES])
def test_b_conversion_examples_match(bundle, case):
    results = run(FarmProfile(**case.profile), bundle, extra=(B13_DRAFT_HOLD,))
    assert status_of(case.program_id, results) == case.expected, case.why


# --- 계획서 테스트 ------------------------------------------------------------------------------

P4_UNKNOWN_FUND = {**P4_KWARGS, "mgmt_status": "unknown",
                   "crops": ({"crop_code": "양배추", "area_m2": 11901, "sales_channel": "unknown", "selfpay_fund": "unknown"},)}


def test_unknown_prereq_becomes_check_not_hidden(bundle):
    m = find("JEJU-PSTAB@2026-27#양배추", run(FarmProfile(**P4_UNKNOWN_FUND), bundle))
    assert m.status == "CHECK"
    assert {"needs_coop", "needs_selfpay_fund", "needs_enrollment"} <= set(m.unknown_fields)
    assert m.missing_prereqs == ()


def test_p4_cabbage_price_stab_blocked_prereq(bundle):  # 골든 P4: 계통·자조금·참여 신청 농가만
    m = find("JEJU-PSTAB@2026-27#양배추", run(FarmProfile(**P4_KWARGS), bundle))
    assert m.status == "BLOCKED_PREREQ"
    assert set(m.missing_prereqs) == {"needs_coop", "needs_selfpay_fund"}


def test_hold_rows_excluded(bundle):
    hold_ids = {p.id for p in bundle.programs if p.status == "hold"}
    assert hold_ids  # 표에 hold 행이 있어야 이 테스트가 뜻이 있다
    results = run(FarmProfile(**P1_KWARGS), bundle)
    assert all(m.row_status != "hold" for m in results)
    assert not hold_ids & {m.program_id for m in results}
    assert len(results) == len(bundle.programs) - len(hold_ids)


def test_age_boundary_65(bundle):
    m = find("NAT-RETIRE-DIRECT@2026", run(profile_born(1961), bundle, date(2026, 11, 13)))
    assert m.status != "NOT_ELIGIBLE"
    assert cond(m, "min_age") == "UNKNOWN"  # 신청일 기준 64~65세: 생신 확인


@pytest.mark.parametrize("year, min_age, status", [
    (1962, "FAIL", "NOT_ELIGIBLE"),   # 63~64세
    (1961, "UNKNOWN", "CHECK"),       # 64~65세
    (1960, "PASS", "CHECK"),          # 65~66세(보유 3년은 모름)
])
def test_retire_direct_age_on_application_date(bundle, year, min_age, status):
    m = find("NAT-RETIRE-DIRECT@2026", run(profile_born(year), bundle))
    assert (cond(m, "min_age"), m.status) == (min_age, status)


# --- 묶음 규칙 ----------------------------------------------------------------------------------

def row(pid: str = "TEST-ROW@2026", **cells) -> Program:
    key, edition = pid.split("@")[0], pid.split("@")[1]
    base = dict(id=pid, program_key=key, edition=edition, status="confirmed", valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31), apply_cycle="상시", renew_type="상시")
    return Program(**{**base, **cells})


def match_one(program: Program, base: dict = P1_KWARGS, as_of: date = AS_OF, **changes) -> MatchResult:
    (m,) = match_supports(profile(base, **changes), (program,), as_of)
    return m


def test_all_pass_is_likely():
    assert match_one(row(needs_mgmt="Y")).status == "LIKELY"


def test_manual_check_is_a_print_tag_not_a_bundle_input():  # fix 1: 42행 모두 manual_check가 있어 LIKELY가 막혔다
    m = match_one(row(needs_mgmt="Y", manual_check="지방세 체납 없음"))
    assert (m.status, m.manual_check) == ("LIKELY", "지방세 체납 없음")


def test_income_review_makes_check():
    assert match_one(row(needs_mgmt="Y", income_test="심사")).status == "CHECK"


def test_corporate_applicant_rows_excluded():  # fix 1: 법인·단체 사업은 hold와 같이 뺀다
    rows = (row("CORP@2026", applicant="법인·단체"), row("VIA-COOP@2026", applicant="농협경유"), row("SELF@2026"))
    assert [m.program_id for m in match_supports(FarmProfile(**P1_KWARGS), rows, AS_OF)] == ["VIA-COOP@2026", "SELF@2026"]


def test_disaster_event_row_only_with_recent_damage(bundle):  # event_type=재해
    rec = "NAT-DISASTER-RECOVERY@2026"
    m = find(rec, run(FarmProfile(**P1_KWARGS), bundle))
    assert (m.status, cond(m, "event_type")) == ("NOT_ELIGIBLE", "FAIL")
    damaged = profile(P1_KWARGS, flags={**P1_KWARGS["flags"], "disaster_damage": True})
    assert status_of(rec, run(damaged, bundle)) != "NOT_ELIGIBLE"


@pytest.mark.parametrize("kwargs", [P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS,
                                    {**P1_KWARGS, "flags": {"disaster_damage": True}}])
def test_farm_helper_accident_row_never_matches(bundle, kwargs):  # event_type=사고: 모든 종이에 고정 줄로
    assert status_of("NAT-FARM-HELPER@2026", run(FarmProfile(**kwargs), bundle)) == "NOT_ELIGIBLE"


@pytest.mark.parametrize("crop, facility, expected", [
    ("감귤_노지", "노지", "PASS"), ("감귤_노지", "시설", "FAIL"), ("시설과채", "시설", "PASS"),
    ("시설과채", "노지", "FAIL"), ("감귤_만감", "노지", "UNKNOWN"),
])
def test_facility_from_crop_code(crop, facility, expected):
    m = match_one(row(facility=facility), crops=(plot(crop, 1500),))
    assert cond(m, "facility") == expected


def test_source_keeps_missing_verified_date_as_none():  # 확인일을 지어내지 않는다
    assert match_one(row()).source.as_of is None
    assert match_one(row(verified_date=date(2026, 11, 2))).source.as_of == date(2026, 11, 2)


@pytest.mark.parametrize("year, approx, basis, expected", [
    (1961, True, "신청일", "UNKNOWN"),   # 대략 1961 → 1959~1963년생 → 62~67세: FAIL 아님
    (1962, False, "연말", "FAIL"),       # 연말 기준 64세 확정
    (1962, True, "연말", "UNKNOWN"),     # 대략이면 1960~1964년생 → 62~66세
    (1990, True, "신청일", "FAIL"),      # 경계에서 멀면 대략이라도 FAIL
])
def test_approx_birth_year_widens_age(year, approx, basis, expected):
    m = match_one(row(min_age=65, age_basis=basis), birth_year=year, birth_year_approx=approx)
    assert cond(m, "min_age") == expected
    assert (m.status == "NOT_ELIGIBLE") == (expected == "FAIL")


def test_approx_birth_year_on_retire_direct(bundle):
    near = find("NAT-RETIRE-DIRECT@2026", run(profile(P1_KWARGS, birth_year=1961, birth_year_approx=True), bundle))
    assert cond(near, "min_age") == "UNKNOWN" and near.status != "NOT_ELIGIBLE"
    far = profile(P1_KWARGS, birth_year=1990, birth_year_approx=True)
    assert status_of("NAT-RETIRE-DIRECT@2026", run(far, bundle)) == "NOT_ELIGIBLE"


@pytest.mark.parametrize("m2, min_ha, max_ha", [(1000, "0.1", "0.86"), (8600, "0.1", "0.86")])
def test_area_exactly_at_threshold_passes(m2, min_ha, max_ha):  # 이상·이하(경계 포함)
    m = match_one(row(min_ha=Decimal(min_ha), max_ha=Decimal(max_ha), area_basis="경작"), total_area_m2=m2)
    assert (cond(m, "min_ha"), cond(m, "max_ha")) == ("PASS", "PASS")
    assert cond(match_one(row(min_ha=Decimal(min_ha), area_basis="경작"), total_area_m2=999), "min_ha") == "FAIL"


def test_prereq_and_hard_fail_is_not_eligible():
    r = row(needs_mgmt="Y", min_residence_years=3)
    assert match_one(r, mgmt_status="none").status == "BLOCKED_PREREQ"
    assert match_one(r, mgmt_status="none", residence_3y=False).status == "NOT_ELIGIBLE"


def test_out_of_validity_except_prior_year_reference():
    past = dict(needs_mgmt="Y", valid_to=date(2026, 10, 31))
    assert match_one(row(**past)).status == "OUT_OF_VALIDITY"
    m = match_one(row(**past, status="prior_year_reference", expected_notice_month=3))
    assert (m.status, m.row_status) == ("LIKELY", "prior_year_reference")


def test_validity_last_day_and_open_end_are_not_expired():
    assert match_one(row(needs_mgmt="Y", valid_to=AS_OF)).status == "LIKELY"   # as_of == valid_to: 마지막 날
    assert match_one(row(needs_mgmt="Y", valid_to=None)).status == "LIKELY"    # 끝나는 날 없음


def test_renew_annual_flag(bundle):  # Task 10: ALREADY이면서 매년신청인 행만(E' "작년처럼 다시 신청" 줄)
    p4 = run(FarmProfile(**P4_KWARGS), bundle)  # 받는 것 없음
    assert find("JEJU-FARMER-ALLOW@2026", p4).status == "BLOCKED_PREREQ"
    assert not find("JEJU-FARMER-ALLOW@2026", p4).renew_annual           # 매년신청이지만 안 받음
    assert not find("KRC-FARMLAND-PENSION@2026", p4).renew_annual        # 상시
    nhis = find("NHIS-FARMER-SUPPORT@2026#읍면", run(FarmProfile(**P2_KWARGS), bundle))
    assert nhis.status == "ALREADY" and not nhis.renew_annual             # 받지만 상시


def test_coop_or_selfpay_fund_either_one(bundle):  # needs_coop=E·needs_selfpay_fund=E
    soil = "JEJU-SOIL-ECO@2026"
    assert status_of(soil, run(FarmProfile(**P4_KWARGS), bundle)) == "BLOCKED_PREREQ"  # 상인·자조금 안 냄
    fund_only = {**P4_KWARGS, "crops": ({**P4_KWARGS["crops"][0], "selfpay_fund": "paid"},)}
    assert cond(find(soil, run(FarmProfile(**fund_only), bundle)), "needs_coop") == "PASS"


def test_crop_group_without_crop_table_is_unknown_not_fail(bundle):
    carrot = FarmProfile(**CARROT_2000PY)
    (m,) = match_supports(carrot, tuple(p for p in bundle.programs if p.id == "DO-SMALL-MACHINE@2026"), AS_OF)
    assert cond(m, "crop_in") == "UNKNOWN"  # '밭작물'이 그룹인지 모르면 숨기지 않는다
    assert cond(find("DO-SMALL-MACHINE@2026", run(carrot, bundle)), "crop_in") == "PASS"


def test_target_crop_area_is_zero_when_no_crop_fits(bundle):  # 감귤 면적을 밭작물 면적으로 세지 않는다
    m = find("DO-SMALL-MACHINE@2026", run(FarmProfile(**P1_KWARGS), bundle))
    assert (cond(m, "min_ha"), next(c.actual for c in m.conds if c.field == "min_ha")) == ("FAIL", "0㎡")


def test_region_from_eupmyeon(bundle):  # P1 남원읍 = 서귀포시
    results = run(FarmProfile(**P1_KWARGS), bundle)
    assert status_of("JS-WINDBREAK@2026", results) == "NOT_ELIGIBLE"
    assert status_of("SGP-WINDBREAK@2026", results) == "LIKELY"  # 경영체·감귤·서귀포시 PASS(fix 1 전엔 manual_check로 CHECK)


def test_results_follow_table_order(bundle):
    results = run(FarmProfile(**P2_KWARGS), bundle)
    assert [m.program_id for m in results] == [p.id for p in bundle.programs if p.status != "hold"]


# --- Task 10(U10) 매칭 2: 이미 받음·택1·what_if ----------------------------------------------------

SMALL, AREA = "NAT-DIRECT-SMALL@2026", "NAT-DIRECT-AREA@2026"
CANDIDATE = {"LIKELY", "CHECK"}

P2_RECEIVING_ALLOW = FarmProfile(**{**P2_KWARGS, "already_receiving": frozenset({"JEJU-FARMER-ALLOW"})})


def count(results: tuple[MatchResult, ...], statuses: set[str]) -> int:
    return sum(m.status in statuses for m in results)


def profile_total_ha(ha: float, base: dict = P1_KWARGS, **changes) -> FarmProfile:
    """P1(노지감귤 자가, 영농 45년, 경영체 2년+, 직불은 안 받음)에서 면적만 바꾼다."""
    m2 = round(ha * 10_000)
    return profile(base, crops=({**base["crops"][0], "area_m2": m2},), total_area_m2=m2, **changes)


def test_already_receiving_annual_flag(bundle):
    r = run(P2_RECEIVING_ALLOW, bundle)
    m = find("JEJU-FARMER-ALLOW@2026", r)
    assert m.status == "ALREADY" and m.renew_annual
    area = find(AREA, r)  # 같은 농가의 매년신청 행이지만 안 받음 → 표시 없음
    assert area.status != "ALREADY" and not area.renew_annual


def test_small_vs_area_direct_picks_small_under_130(bundle):
    r = run(profile_total_ha(0.7), bundle)
    assert status_of(SMALL, r) in CANDIDATE and status_of(AREA, r) == "EXCLUSIVE_OTHER"


def test_what_if_mgmt_unlocks(bundle):
    p4 = FarmProfile(**P4_KWARGS)
    before = run(p4, bundle)
    after = what_if(p4, bundle.programs, AS_OF, {"mgmt_status": "over_2y"}, crops=bundle.crops)
    assert count(after, CANDIDATE) > count(before, CANDIDATE)


def with_small(bundle, **cells) -> tuple[Program, ...]:
    """소농직불 행의 칸만 바꾼 표."""
    return tuple(Program.model_validate({**dict(p), **cells}) if p.id == SMALL else p for p in bundle.programs)


@pytest.mark.parametrize("ha, kept, dropped", [
    (0.8666, SMALL, AREA),   # 8,666㎡ × 150만 원/ha = 129.99만 < 130만 → 소농
    (0.8667, AREA, SMALL),   # 130.005만 ≥ 130만 → 면적직불
])
def test_small_vs_area_keeps_larger_amount(bundle, ha, kept, dropped):
    # 면적 상한(0.86ha)을 2ha로 푼다. 표 그대로면 소농이 후보일 때 늘 소농이 커서 반대쪽을 못 본다.
    r = match_supports(profile_total_ha(ha), with_small(bundle, max_ha=Decimal("2")), AS_OF, crops=bundle.crops)
    assert status_of(kept, r) in CANDIDATE and status_of(dropped, r) == "EXCLUSIVE_OTHER"


def test_direct_comparison_uses_small_row_area_basis(bundle):
    """비교 면적은 소농 행 area_basis로 본다. '인증' 면적은 입력에 없으니 경작 0.7ha를 알아도 비교 보류."""
    r = match_supports(profile_total_ha(0.7), with_small(bundle, area_basis="인증"), AS_OF, crops=bundle.crops)
    for pid in (SMALL, AREA):
        assert find(pid, r).status == "CHECK" and "excludes" in find(pid, r).unknown_fields


def test_rival_not_candidate_keeps_row(bundle):
    r = run(profile_total_ha(0.7, farming_years=2), bundle)  # 소농은 영농 3년 미만 → NOT_ELIGIBLE
    assert (status_of(SMALL, r), status_of(AREA, r)) == ("NOT_ELIGIBLE", "CHECK")


def test_both_sides_already_stay_already(bundle):
    r = run(profile_total_ha(0.7, already_receiving=frozenset({"NAT-DIRECT-SMALL", "NAT-DIRECT-AREA"})), bundle)
    assert (status_of(SMALL, r), status_of(AREA, r)) == ("ALREADY", "ALREADY")


def test_small_vs_area_undecided_without_area(bundle):
    no_area = profile(P1_KWARGS, crops=({**P1_KWARGS["crops"][0], "area_m2": None},), total_area_m2=None)
    r = run(no_area, bundle)
    for pid in (SMALL, AREA):
        m = find(pid, r)
        assert m.status == "CHECK" and "excludes" in m.unknown_fields
        assert next(c.actual for c in m.conds if c.field == "excludes") == "택1 비교 보류"


def test_direct_pair_rate_matches_table(bundle):
    """택1 비교 단가 상수가 면적직불 행 amount_note와 같은지. 표가 바뀌면 match_rules 상수를 다시 본다."""
    area = next(p for p in bundle.programs if p.id == AREA)
    assert f"ha당 {AREA_DIRECT_WON_PER_HA // 10_000}만 원" in (area.amount_note or "")


@pytest.mark.parametrize("kwargs, received, other", [
    (P5_KWARGS, AREA, SMALL),  # 골든 P5: 0.69ha라 소농이 더 커도 받는 쪽을 남김(차액은 종이 문구로)
    (T1_KWARGS, SMALL, AREA),  # 빈 종이 T1: 소농을 받으니 면적직불을 빠뜨린 돈으로 찍지 않음
])
def test_received_side_of_exclusive_pair_is_kept(bundle, kwargs, received, other):
    r = run(FarmProfile(**kwargs), bundle)
    assert (status_of(received, r), status_of(other, r)) == ("ALREADY", "EXCLUSIVE_OTHER")


def test_already_only_on_rows_for_own_crop_and_area(bundle):
    r = run(FarmProfile(**P2_KWARGS), bundle)  # 구좌읍 당근, JEJU-PSTAB·NHIS-FARMER-SUPPORT를 받음
    assert status_of("JEJU-PSTAB@2026-27#당근", r) == "ALREADY"
    assert status_of("JEJU-PSTAB@2026-27#양배추", r) == "NOT_ELIGIBLE"
    assert status_of("NHIS-FARMER-SUPPORT@2026#읍면", r) == "ALREADY"
    assert status_of("NHIS-FARMER-SUPPORT@2026#동", r) == "NOT_ELIGIBLE"


def test_already_overrides_eligibility_but_not_expired_row():
    receiving = frozenset({"TEST-ROW"})
    assert match_one(row(needs_mgmt="Y"), mgmt_status="none", already_receiving=receiving).status == "ALREADY"
    expired = row(needs_mgmt="Y", valid_to=date(2026, 10, 31))
    assert match_one(expired, already_receiving=receiving).status == "OUT_OF_VALIDITY"


def test_other_exclusive_pairs_left_to_farmer_unless_received():
    def ins(pid: str, crop: str, excludes: str) -> Program:
        return row(pid, needs_mgmt="Y", crop_in=(crop,), excludes=(excludes,))

    rows = (ins("INS-A@2026#마늘", "마늘", "INS-B"), ins("INS-B@2026#마늘", "마늘", "INS-A"),
            ins("INS-B@2026#양파", "양파", "INS-A"))
    garlic_onion = {**P3_KWARGS, "crops": (plot("마늘", 1800), plot("양파", 900)), "already_receiving": frozenset()}
    r = match_supports(FarmProfile(**garlic_onion), rows, AS_OF)
    assert [m.status for m in r] == ["LIKELY"] * 3  # 둘 다 후보면 어르신이 고른다
    r = match_supports(profile(garlic_onion, already_receiving=frozenset({"INS-A"})), rows, AS_OF)
    assert [m.status for m in r] == ["ALREADY", "EXCLUSIVE_OTHER", "LIKELY"]  # 같은 작물끼리만 짝


def test_what_if_crop_plot_change_clears_prereqs(bundle):
    p4 = FarmProfile(**P4_KWARGS)
    before = find("JEJU-PSTAB@2026-27#양배추", run(p4, bundle))
    assert set(before.missing_prereqs) == {"needs_coop", "needs_selfpay_fund"}
    after = what_if(p4, bundle.programs, AS_OF, {"crops[0].selfpay_fund": "paid", "crops[0].sales_channel": "coop"},
                    crops=bundle.crops)
    assert find("JEJU-PSTAB@2026-27#양배추", after).missing_prereqs == ()
    assert p4.crops[0].selfpay_fund == "not_paid"  # 원래 농가는 그대로


def test_what_if_without_changes_equals_match(bundle):
    p2 = FarmProfile(**P2_KWARGS)
    assert what_if(p2, bundle.programs, AS_OF, {}, crops=bundle.crops) == run(p2, bundle)


@pytest.mark.parametrize("key", ["mgmt", "crops[1].selfpay_fund", "crops[0].area_py"])
def test_what_if_rejects_unknown_keys(bundle, key):
    with pytest.raises(KeyError):
        what_if(FarmProfile(**P4_KWARGS), bundle.programs, AS_OF, {key: "x"})


@pytest.mark.parametrize("change", [{"mgmt_status": "yes"}, {"crops[0].selfpay_fund": "maybe"}])
def test_what_if_rejects_invalid_values(bundle, change):
    with pytest.raises(ValidationError):
        what_if(FarmProfile(**P4_KWARGS), bundle.programs, AS_OF, change)


def test_needs_enrollment_reads_enrollment_requested(bundle):
    key = "JEJU-PSTAB@2026-27#양배추"
    base = {**P2_KWARGS, "crops": ({"crop_code": "양배추", "area_m2": 9917, "sales_channel": "coop", "selfpay_fund": "paid"},)}
    got = {}
    for answer in ("예", "아니오", "모름"):
        m = find(key, run(FarmProfile(**base, enrollment_requested=answer), bundle))
        got[answer] = next(c.result for c in m.conds if c.field == "needs_enrollment")
    assert got == {"예": "PASS", "아니오": "FAIL", "모름": "UNKNOWN"}


def test_apply_changes_returns_new_profile_and_keeps_original():
    p4 = FarmProfile(**P4_KWARGS)
    changed = apply_changes(p4, {"mgmt_status": "over_2y", "crops[0].selfpay_fund": "paid"})
    assert changed.mgmt_status == "over_2y" and changed.crops[0].selfpay_fund == "paid"
    assert p4.mgmt_status == "none" and p4.crops[0].selfpay_fund == "not_paid"
    with pytest.raises(KeyError):
        apply_changes(p4, {"mgmt": "x"})
