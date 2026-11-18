"""Task 14(U14) 금액 계산: amount_type 7종(round1-B-data.md §2-4), 가격안정관리제 두 줄, 가정 재대조 금액.

플랜의 자리표시자는 실제 값으로 바꿨다.
- JEJU-PSTAB@2025-26#cabbage → JEJU-PSTAB@2026-27#양배추(표에 있는 행. 2025-26 기준가 723·하한가 542를 넘겨 씀).
- P4 / M_P4(가격안정관리제 줄): P4 그대로는 계통출하·자조금이 없어 BLOCKED_PREREQ라 금액 줄이 없다(§12-A(2) 계통
  전환 줄에 금액 없음 — 아래 test_blocked_pstab_has_no_money_line). 그래서 P4가 농협 출하·자조금 가입을 했다고
  본 P4_COOP과 그 매칭으로 kg당 차액을 본다.
- P4_AFTER_MGMT: P4에서 경영체만 2년 이상으로 바꾼 농가(what_if와 같은 변화).
- T_MET_AT_FLOOR: 반월 평균이 하한가(542원)인 MET 판정 → kg당 (723 − 542) × 0.9 = 162.9원.
"""
from datetime import date
from decimal import Decimal
from functools import lru_cache

import pytest

from app.core.amounts import CHECK_NOTE, NEAR_NOTE, NOT_FORECAST, calc_amounts, small_area_rate, unlock_amounts
from app.core.match import match_supports
from app.core.match_rules import AREA_DIRECT_WON_PER_HA
from app.core.models import AmountLine, FarmProfile, MatchResult, Program, SourceRef, TriggerResult
from app.core.tables_models import TableBundle
from app.core.triggers import PRICE_BASIS
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P4_KWARGS, ROOT

PSTAB_CABBAGE = "JEJU-PSTAB@2026-27#양배추"
AREA_DIRECT = "NAT-DIRECT-AREA@2026"


@lru_cache(maxsize=None)
def bundle() -> TableBundle:
    return load_tables(ROOT / "data" / "tables", AS_OF)


def programs() -> tuple[Program, ...]:
    return bundle().programs


def matches(profile: FarmProfile) -> tuple[MatchResult, ...]:
    return match_supports(profile, programs(), AS_OF, crops=bundle().crops)


def line(program_id: str, lines: tuple[AmountLine, ...], kind: str | None = None) -> AmountLine:
    return next(a for a in lines if a.program_id == program_id and (kind is None or a.kind == kind))


def ids(lines: tuple[AmountLine, ...]) -> set[str]:
    return {a.program_id for a in lines}


def with_row(program_id: str, **changes) -> TableBundle:
    """표 한 행만 바꾼 묶음(합성 행 시험용)."""
    rows = tuple(Program.model_validate({**dict(p), **changes}) if p.id == program_id else p for p in programs())
    return TableBundle.model_validate({**dict(bundle()), "programs": rows})


def stab(status: str, observed: str | None) -> dict[str, tuple[TriggerResult, ...]]:
    """양배추 PRICE_STAB 판정 하나(합성). 금액 계산은 판정 결과만 믿으므로 기준일과 시즌 달은 맞추지 않았다."""
    price = SourceRef(source_id="hub1361:양배추", url=None, as_of=AS_OF)
    t = TriggerResult(rule_id="PRICE_STAB", status=status, provisional=False, metric=PRICE_BASIS,
                      observed=None if observed is None else Decimal(observed), threshold=Decimal(723),
                      window=(date(2026, 11, 1), date(2026, 11, 15)), n_days_with_data=9, data_as_of=AS_OF,
                      staleness_days=0, history_hits=None, sources=(price,))
    return {"양배추": (t,)}


def p4_coop_kwargs() -> dict:
    (plot,) = P4_KWARGS["crops"]
    return {**P4_KWARGS, "crops": ({**plot, "sales_channel": "coop", "selfpay_fund": "paid"},)}


P4 = FarmProfile(**P4_KWARGS)
P4_COOP = FarmProfile(**p4_coop_kwargs())
P4_AFTER_MGMT = FarmProfile(**{**P4_KWARGS, "mgmt_status": "over_2y"})
P1 = FarmProfile(**P1_KWARGS)
P2 = FarmProfile(**P2_KWARGS)
T_MET_AT_FLOOR = stab("MET", "542")


# --- 플랜 Step 1 테스트 4개 -------------------------------------------------------------------

def test_cabbage_stab_cap_163():
    a = line(PSTAB_CABBAGE, calc_amounts(P4_COOP, matches(P4_COOP), T_MET_AT_FLOOR, bundle(), AS_OF), "PER_KG_TRIGGER")
    assert a.terms_by("kg당 차액").value == Decimal("162.9")
    assert a.excluded == (NOT_FORECAST,) and a.low_won is None and a.high_won is None   # kg당 사실만, 총액 없음


def test_p4_unlock_mgmt_range():
    low, high = unlock_amounts(P4, programs(), AS_OF, {"mgmt_status": "over_2y"}, crops=bundle().crops)
    assert 1_790_000 <= low <= 1_900_000 and 2_500_000 <= high <= 2_600_000


def test_coop_switch_has_no_amount():
    assert unlock_amounts(P1, programs(), AS_OF, {"crops[0].sales_channel": "coop"}, crops=bundle().crops) == (None, None)


def test_check_status_still_prints_amount_with_note():
    a = line(AREA_DIRECT, calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, bundle(), AS_OF))
    assert a.low_won and a.check_note == CHECK_NOTE == "확인할 조건 있음"


# --- 면적비례: 면적직불 단가 ---------------------------------------------------------------------

def test_area_direct_small_farm_uses_outside_zone_rate_from_note():
    # 1.1901ha ≤ 2ha: 하한 = 진흥지역 밖 밭 150만/ha(행 amount_note), 상한 = amount_max 215만/ha. 만 원 단위 반올림.
    a = line(AREA_DIRECT, calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, bundle(), AS_OF))
    assert a.kind == "PER_AREA" and (a.low_won, a.high_won) == (1_790_000, 2_560_000)   # 1,785,150 · 2,558,715
    assert a.terms_by("ha당 하한").value == Decimal(1_500_000) and a.terms_by("ha당 상한").value == Decimal(2_150_000)
    assert a.terms_by("면적").value == Decimal("1.1901") and a.pay_timing == "11~12월 통장 지급"
    assert a.period == "연"


def test_area_direct_note_rate_pinned_to_table_and_match_rules():
    """면적직불 행 amount_note에서 읽은 2ha 이하 단가가 택1 비교 상수(Task 10)와 같은지. 표가 바뀌면 둘 다 본다."""
    area = next(p for p in programs() if p.id == AREA_DIRECT)
    assert small_area_rate(area) == (Decimal(2), AREA_DIRECT_WON_PER_HA)


def test_area_direct_over_2ha_falls_back_to_table_min_max():
    p = FarmProfile(**{**P4_KWARGS, "mgmt_status": "over_2y", "total_area_m2": 30_000,
                       "crops": ({**P4_KWARGS["crops"][0], "area_m2": 30_000},)})
    a = line(AREA_DIRECT, calc_amounts(p, matches(p), {}, bundle(), AS_OF))
    assert (a.low_won, a.high_won) == (4_080_000, 6_450_000)                              # 136만·215만 × 3ha


def test_area_unknown_keeps_rates_without_total():
    p = FarmProfile(**{**P4_KWARGS, "mgmt_status": "over_2y", "total_area_m2": None,
                       "crops": ({**P4_KWARGS["crops"][0], "area_m2": None},)})
    a = line(AREA_DIRECT, calc_amounts(p, matches(p), {}, bundle(), AS_OF))
    assert a.low_won is None and a.high_won is None and a.terms_by("ha당 상한").value == Decimal(2_150_000)


def test_crop_area_basis_resolves_crop_group():
    # 토양 휴경(crop_in=월동채소 그룹, 해당작물면적): 당근 0.9917ha × ha당 440만~460만.
    a = line("JEJU-SOIL-ECO@2026", calc_amounts(P2, matches(P2), {}, bundle(), AS_OF))
    assert a.kind == "PER_AREA" and (a.low_won, a.high_won) == (4_360_000, 4_560_000)    # 4,363,480 · 4,561,820
    assert a.check_note is None and a.period == "1회"                                    # LIKELY 줄은 꼬리표 없음


def test_owned_area_basis_for_retirement_payment():
    # 은퇴직불(소유면적, 월 ha당 40만~50만): P1은 자기 땅 4,959㎡ → 월 198,360~247,950원.
    a = line("NAT-RETIRE-DIRECT@2026", calc_amounts(P1, matches(P1), {}, bundle(), AS_OF))
    assert (a.low_won, a.high_won) == (200_000, 250_000) and a.check_note == CHECK_NOTE
    assert a.period == "월"                                                              # 월 20만~25만, 연 합계가 아니다


def test_cap_won_cuts_and_is_printed_as_is():
    capped = with_row(AREA_DIRECT, cap_won=2_000_000)
    a = line(AREA_DIRECT, calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, capped, AS_OF))
    assert (a.low_won, a.high_won) == (1_790_000, 2_000_000)                             # 상한은 표 숫자 그대로


# --- 정액·단위당·보조율·없음·kg당 ------------------------------------------------------------------

def test_fixed_amount_line():
    lines = calc_amounts(P1, matches(P1), {}, bundle(), AS_OF)
    a = line("JEJU-SMALLFARM@2026", lines)
    assert a.kind == "FIXED" and (a.low_won, a.high_won) == (150_000, 150_000) and a.check_note is None
    assert a.period == "연"
    small = line("NAT-DIRECT-SMALL@2026", lines)
    assert (small.low_won, small.high_won) == (1_300_000, 1_300_000) and small.check_note == CHECK_NOTE


def test_fixed_two_person_farm_uses_per_person_amount():
    p = FarmProfile(**{**P1_KWARGS, "spouse": "registered", "already_receiving": frozenset()})
    a = line("JEJU-FARMER-ALLOW@2026", calc_amounts(p, matches(p), {}, bundle(), AS_OF))
    assert (a.low_won, a.high_won) == (900_000, 900_000)                                 # 2인 경영체 1인당 45만 × 2
    assert a.terms_by("1인당").value == Decimal(450_000) and a.terms_by("인원").value == Decimal(2)


@pytest.mark.parametrize("area_m2", [9917, 9960])
def test_per_unit_amount_counts_whole_units(area_m2):
    # 칼슘유황비료: ha당 100포 × 0.9917ha(99.6포도) = 99포(낱포만, 내림) × 2,000원 = 198,000원 → 약 20만 원.
    p = FarmProfile(**{**P2_KWARGS, "total_area_m2": area_m2, "crops": ({**P2_KWARGS["crops"][0], "area_m2": area_m2},)})
    a = line("DO-CALCIUM-SULFUR@2026", calc_amounts(p, matches(p), {}, bundle(), AS_OF))
    assert a.kind == "PER_AREA" and (a.low_won, a.high_won) == (200_000, 200_000)
    assert a.terms_by("수량").value == Decimal(99) and a.terms_by("단가").value == Decimal(2_000)


def test_subsidy_rate_has_no_total_only_terms():
    a = line("DO-SMALL-MACHINE@2026", calc_amounts(P2, matches(P2), {}, bundle(), AS_OF))
    assert a.kind == "UNDISCLOSED" and a.low_won is None and a.high_won is None
    assert (a.terms_by("지원 비율 하한").value, a.terms_by("지원 비율 상한").value) == (Decimal(60), Decimal(70))
    assert a.terms_by("최대").value == Decimal(7_000_000) and a.check_note == CHECK_NOTE


def test_none_type_is_undisclosed_with_cap_term():
    a = line("KRC-FARMLAND-PENSION@2026", calc_amounts(P1, matches(P1), {}, bundle(), AS_OF))
    assert a.kind == "UNDISCLOSED" and a.low_won is None and a.terms_by("최대").value == Decimal(3_000_000)


def test_per_kg_without_shipment_input_prints_rate_only():
    per_kg = with_row(AREA_DIRECT, amount_type="kg당", amount_value=16, amount_min=None, amount_max=None)
    a = line(AREA_DIRECT, calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, per_kg, AS_OF))
    assert a.kind == "UNDISCLOSED" and a.low_won is None and a.terms_by("kg당").value == Decimal(16)


# --- 상태별: 금액 줄이 없는 묶음 -------------------------------------------------------------------

def test_no_line_for_blocked_not_eligible_exclusive_but_already_is_flagged():
    p4 = calc_amounts(P4, matches(P4), T_MET_AT_FLOOR, bundle(), AS_OF)
    assert AREA_DIRECT not in ids(p4) and "JEJU-FARMER-ALLOW@2026" not in ids(p4)        # BLOCKED_PREREQ
    assert "NAT-FARM-HELPER@2026" not in ids(p4)                                         # NOT_ELIGIBLE
    p1 = calc_amounts(P1, matches(P1), {}, bundle(), AS_OF)
    assert AREA_DIRECT not in ids(p1)                                                    # EXCLUSIVE_OTHER
    keep = line("JEJU-FARMER-ALLOW@2026", p1)                                            # ALREADY: 지키실 돈
    assert keep.already is True and (keep.low_won, keep.high_won) == (500_000, 500_000)
    assert not any(a.already for a in p1 if a.program_id != "JEJU-FARMER-ALLOW@2026"
                   and next(m for m in matches(P1) if m.program_id == a.program_id).status != "ALREADY")


def test_candidate_lines_are_not_flagged_already():
    lines = calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, bundle(), AS_OF)
    assert not line(AREA_DIRECT, lines).already


def test_p2_already_rows_keep_amounts_and_last_season_line():
    """골든 P2: 이미 받는 가격안정관리제 → 지난 시즌 실적 줄(71원 × 9.917 × 3,279kg = 2,308,800원 → 만 원 단위 약 231만 원). 발동 판정 없이도 나온다."""
    lines = calc_amounts(P2, matches(P2), {}, bundle(), AS_OF)
    ref = line("JEJU-PSTAB@2026-27#당근", lines)
    assert ref.kind == "REFERENCE_LAST_SEASON" and ref.already is True
    assert (ref.low_won, ref.high_won) == (2_310_000, 2_310_000) and ref.excluded == (NOT_FORECAST,)
    assert [a.kind for a in lines if a.program_id == ref.program_id] == ["REFERENCE_LAST_SEASON"]   # kg당 차액 줄은 없다
    area = line(AREA_DIRECT, lines)
    assert area.already is True and area.low_won is not None
    assert line("JEJU-FARMER-ALLOW@2026", lines).already is True


def test_blocked_pstab_has_no_money_line():
    """§12-A(2): 계통 전환 줄에는 금액을 적지 않는다. P4(상인 계약)는 발동이 돼도 금액 줄이 없다."""
    lines = calc_amounts(P4, matches(P4), T_MET_AT_FLOOR, bundle(), AS_OF)
    mine = [a for a in lines if a.program_id == PSTAB_CABBAGE]
    assert all(a.low_won is None and a.high_won is None for a in mine)     # 금액(총액)은 없다


def test_blocked_pstab_keeps_last_season_kg_fact_only():
    """사실 한 줄("작년 kg당 153원")은 허용(§12-A(2)): 계통 전환으로 막힌 행도 총액 없는 사실 항을 가진다."""
    (a,) = [a for a in calc_amounts(P4, matches(P4), T_MET_AT_FLOOR, bundle(), AS_OF) if a.program_id == PSTAB_CABBAGE]
    assert a.kind == "REFERENCE_LAST_SEASON" and a.excluded == (NOT_FORECAST,)
    assert [(t.label, t.value) for t in a.terms] == [("작년 kg당 평균", Decimal(153))]


# --- 가격안정관리제 두 줄 -----------------------------------------------------------------------

def test_cabbage_last_season_reference():
    # 작년 kg당 평균 153원 × 예상 물량(11.901 × 10a × 4,711kg = 56,066kg) = 8,578,098원 → 약 858만 원.
    a = line(PSTAB_CABBAGE, calc_amounts(P4_COOP, matches(P4_COOP), T_MET_AT_FLOOR, bundle(), AS_OF),
             "REFERENCE_LAST_SEASON")
    assert (a.low_won, a.high_won) == (8_580_000, 8_580_000) and a.excluded == (NOT_FORECAST,)
    assert a.terms_by("작년 kg당 평균").value == Decimal(153) and a.terms_by("10a당 수확량").value == Decimal(4711)
    assert a.terms_by("예상 물량").value == Decimal(56_066)
    assert a.conditional_on == ("계통출하 물량에 한함",) and a.check_note == CHECK_NOTE   # 참여 신청은 입력에 없음


def test_pstab_kg_terms_and_sources():
    a = line(PSTAB_CABBAGE, calc_amounts(P4_COOP, matches(P4_COOP), T_MET_AT_FLOOR, bundle(), AS_OF), "PER_KG_TRIGGER")
    assert (a.terms_by("기준가").value, a.terms_by("하한가").value) == (Decimal(723), Decimal(542))
    assert a.terms_by("kg당 최대").value == Decimal("162.9") and a.terms_by("지급 비율").value == Decimal("0.9")
    assert a.terms_by("기준가").source.source_id == "params:2025-26:양배추:stab_base"
    assert a.terms_by("반월 평균").source.source_id == "hub1361:양배추"
    assert a.pay_timing == "시즌 끝난 뒤 7월 정산(2026년 사례)"


def test_pstab_below_floor_is_capped_at_floor():
    a = line(PSTAB_CABBAGE, calc_amounts(P4_COOP, matches(P4_COOP), stab("MET", "402"), bundle(), AS_OF),
             "PER_KG_TRIGGER")
    assert a.terms_by("kg당 차액").value == Decimal("162.9")       # B §4-1: 4월 평균 402원 → 289원이 아니라 163원


@pytest.mark.parametrize("status", ["NOT_MET", "OUT_OF_SEASON", "NO_DATA", "STALE", "NOT_APPLICABLE"])
def test_pstab_lines_only_when_met_or_near(status):
    lines = calc_amounts(P4_COOP, matches(P4_COOP), stab(status, None), bundle(), AS_OF)
    assert PSTAB_CABBAGE not in ids(lines)
    assert PSTAB_CABBAGE not in ids(calc_amounts(P4_COOP, matches(P4_COOP), {}, bundle(), AS_OF))  # 판정 없음


def test_pstab_near_note_and_no_negative_difference():
    lines = calc_amounts(P4_COOP, matches(P4_COOP), stab("NEAR", "750.0"), bundle(), AS_OF)   # 기준가 위, 경계 안
    kg = line(PSTAB_CABBAGE, lines, "PER_KG_TRIGGER")
    assert kg.terms_by("kg당 차액").value == Decimal(0) and kg.check_note == f"{CHECK_NOTE} · {NEAR_NOTE}"
    assert NEAR_NOTE == "근처 — 농협 확인"
    assert line(PSTAB_CABBAGE, lines, "REFERENCE_LAST_SEASON").check_note == f"{CHECK_NOTE} · {NEAR_NOTE}"


# --- 가정 재대조 금액 ---------------------------------------------------------------------------

def test_unlock_counts_only_newly_opened_money_not_waiting_years():
    # 경영체 등록으로 새로 열리는 돈 = 면적직불 줄(보험·농기계는 보조율이라 총액 없음). 농민수당은 등록 뒤 2년을
    # 기다려야 열려(min_mgmt_years) 금액에 넣지 않는다(골든 P4 "농민수당 50만 원은 2029년~").
    after = line(AREA_DIRECT, calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, bundle(), AS_OF))
    got = unlock_amounts(P4, programs(), AS_OF, {"mgmt_status": "over_2y"}, crops=bundle().crops)
    assert got == (after.low_won, after.high_won) == (1_790_000, 2_560_000)


def test_unlock_nothing_new_is_none():
    assert unlock_amounts(P4, programs(), AS_OF, {"mgmt_status": "none"}, crops=bundle().crops) == (None, None)


def test_coop_switch_with_fund_still_has_no_amount():
    change = {"crops[0].sales_channel": "coop", "crops[0].selfpay_fund": "paid"}
    assert unlock_amounts(P4, programs(), AS_OF, change, crops=bundle().crops) == (None, None)


def test_unlock_uses_changed_profile_for_amounts():
    # 바뀐 농가로 금액을 센다: 경작 면적 3ha로 바꾸면 면적직불도 3ha 기준(136만·215만 × 3ha).
    change = {"mgmt_status": "over_2y", "total_area_m2": 30_000}
    assert unlock_amounts(P4, programs(), AS_OF, change, crops=bundle().crops) == (4_080_000, 6_450_000)


def test_fund_only_change_is_not_a_coop_switch():
    # 자조금 가입만(계통 전환 아님) → 토양 휴경(E짝: 계통출하 또는 자조금)이 새로 열려 금액이 있다.
    p = FarmProfile(**{**P2_KWARGS, "crops": ({**P2_KWARGS["crops"][0], "sales_channel": "direct",
                                                "selfpay_fund": "not_paid"},)})
    low, high = unlock_amounts(p, programs(), AS_OF, {"crops[0].selfpay_fund": "paid"}, crops=bundle().crops)
    assert (low, high) == (4_360_000, 4_560_000)


# --- 가장자리 ---------------------------------------------------------------------------------

def test_two_target_plots_get_a_line_each():
    # crop_in을 양배추·당근으로 넓힌 합성 행 + 두 작물 밭 → 작물마다 줄(기준가 출처에 작물이 드러난다).
    crop_in = with_row(PSTAB_CABBAGE, crop_in=("양배추", "당근"))
    cab = P4_COOP.crops[0]
    carrot = P2.crops[0]
    p = FarmProfile(**{**p4_coop_kwargs(), "crops": (cab.model_dump(), carrot.model_dump())})
    triggers = {**stab("MET", "542"), "당근": stab("MET", "816")["양배추"]}
    ms = match_supports(p, crop_in.programs, AS_OF, crops=crop_in.crops)
    lines = [a for a in calc_amounts(p, ms, triggers, crop_in, AS_OF)
             if a.program_id == PSTAB_CABBAGE and a.kind == "REFERENCE_LAST_SEASON"]
    assert {a.terms_by("작년 kg당 평균").source.source_id for a in lines} == {
        "params:2025-26:양배추:stab_paid_avg", "params:2025-26:당근:stab_paid_avg"}
    assert 2_310_000 in {a.low_won for a in lines}                                       # 당근 밭 0.9917ha


def _with_area(profile: FarmProfile, area_m2: int | None) -> FarmProfile:
    """입력 모델은 0 면적을 막는다. 그 방어를 시험하려고 검증을 건너뛰어 만든다."""
    (plot,) = profile.crops
    return profile.model_copy(update={"total_area_m2": area_m2, "crops": (plot.model_copy(update={"area_m2": area_m2}),)})


def test_zero_area_gives_no_line_not_a_zero_won_line():
    p = _with_area(P4_AFTER_MGMT, 0)
    assert AREA_DIRECT not in ids(calc_amounts(p, matches(p), {}, bundle(), AS_OF))
    q = _with_area(P4_COOP, 0)
    lines = calc_amounts(q, matches(q), T_MET_AT_FLOOR, bundle(), AS_OF)
    assert not any(a.kind == "REFERENCE_LAST_SEASON" for a in lines if a.program_id == PSTAB_CABBAGE)
    assert not any(a.low_won == 0 for a in lines)


def test_missing_yield_keeps_last_season_average_term_only(monkeypatch):
    import app.core.amounts as amounts
    real = amounts.season_value
    monkeypatch.setattr(amounts, "season_value", lambda b, c, k, d: None if k == "yield_kg_10a" else real(b, c, k, d))
    a = line(PSTAB_CABBAGE, calc_amounts(P4_COOP, matches(P4_COOP), T_MET_AT_FLOOR, bundle(), AS_OF),
             "REFERENCE_LAST_SEASON")
    assert a.low_won is None and a.high_won is None
    assert [t.label for t in a.terms] == ["작년 kg당 평균"]


def test_matches_and_bundle_disagreeing_skips_the_row():
    trimmed = TableBundle.model_validate({**dict(bundle()), "programs": tuple(
        p for p in programs() if p.id != AREA_DIRECT)})
    lines = calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, trimmed, AS_OF)    # 매칭엔 있고 표엔 없는 행
    assert AREA_DIRECT not in ids(lines) and lines


def test_hold_rows_yield_no_line():
    taxi = [p.id for p in programs() if p.id.startswith("JEJU-HAPPY-TAXI")]
    assert taxi
    for prof in (P1, P2, P4_AFTER_MGMT):
        assert not ids(calc_amounts(prof, matches(prof), {}, bundle(), AS_OF)) & set(taxi)
    held = with_row(AREA_DIRECT, status="hold")                                          # 후보 상태여도 hold면 줄 없음
    lines = calc_amounts(P4_AFTER_MGMT, matches(P4_AFTER_MGMT), {}, held, AS_OF)
    assert AREA_DIRECT not in ids(lines)
