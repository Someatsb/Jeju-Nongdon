"""Task 34 골든 검토에서 나온 코어 보강: 작물별 판정 고르기, 시즌 전 시작 달, 가격안정 kg당 사실, 먼저 할 일 금액,
배우자 등록, 빈 종이 끊기지 않게, 뒷면(준비 중·뺀 이유·받고 계신 것), 보험 줄(요건·수입안정 안내), '현재 값 아님' 띠."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.models import FarmProfile
from app.core.pipeline import build_fact_sheet
from app.core.sheet import build_sheet, flatten
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from app.ui.render import STALE_DAYS, _stale_notes
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P4_KWARGS, ROOT

COOP = {"sales_channel": "coop", "selfpay_fund": "paid"}


@pytest.fixture(scope="module")
def bundle():
    return load_tables(ROOT / "data" / "tables", AS_OF)


def paper(kwargs: dict, as_of: date = AS_OF, **over):
    b = load_tables(ROOT / "data" / "tables", as_of)
    snap = load_snapshot(ROOT / "data" / "snapshot", as_of, crops=b.crops)
    fs = build_fact_sheet(FarmProfile(**{**kwargs, **over}), b, snap, as_of, "test", demo_asof=True)
    return fs, build_sheet(fs, b, as_of)


def line_of(sheet, title_part: str):
    return next(l for l in (*flatten(sheet.front), *sheet.overflow) if title_part in l.title)    # 앞면 7개 상한을 넘은 줄은 넘침에 있다


def crops(*pairs):
    return tuple({"crop_code": code, "area_m2": area, **COOP} for code, area in pairs)


@pytest.mark.parametrize("order", [("월동무", "양배추"), ("양배추", "월동무")])
def test_two_crop_line_follows_the_most_open_target_crop_trigger_whatever_the_input_order(order):
    """물류비는 양배추·월동무 둘 다 겨냥한다. 2026-03-15: 월동무 '아직'(NOT_MET), 양배추 '근처'(NEAR) →
    줄은 입력 순서와 상관없이 더 열린 양배추 판정을 따른다(예전엔 먼저 입력한 작물 것을 그대로 썼다)."""
    fs, sheet = paper(P2_KWARGS, date(2026, 3, 15), crops=crops((order[0], 5000), (order[1], 5000)), total_area_m2=10000,
                      already_receiving=frozenset())
    states = {t.crop_code: t.status for t in fs.triggers if t.rule_id == "LOGISTICS"}
    assert states == {"월동무": "NOT_MET", "양배추": "NEAR"}
    assert all(t.crop_code for t in fs.triggers)
    assert "곧 열릴 수 있음" in line_of(sheet, "물류비").text


def test_trigger_id_names_the_driving_crop_trigger_only_when_provisional():
    fs, sheet = paper(P2_KWARGS, AS_OF, already_receiving=frozenset())     # 11-13 당근: 거래 3일 잠정 NOT_MET
    line = line_of(sheet, "가격안정관리제(당근)")
    assert "(잠정)" in line.text and line.trigger_id == "PRICE_STAB"


def test_out_of_season_line_says_when_the_season_starts():
    fs, sheet = paper(P4_KWARGS, AS_OF, crops=crops(("양배추", 4000)), mgmt_status="over_2y", mgmt_last_reg_year=2025,
                      land_tenure="own_all", land_held_2y=True)
    assert "시즌 전 · 12월부터" in line_of(sheet, "가격안정관리제(양배추)").text


def test_open_price_line_prints_kg_facts_not_a_farm_total():
    """가격 근처/열림 줄: 오늘 kg당 최대·하한가·작년 kg당 사실과 '예측 아님'. 농가 총액은 앞면 줄에 쓰지 않는다."""
    fs, sheet = paper(P2_KWARGS, date(2026, 1, 15), already_receiving=frozenset())
    line = line_of(sheet, "가격안정관리제(당근)")
    assert line.text == "곧 열릴 수 있음 · kg당 최대 245원"
    assert "하한가 816원" in line.sub and line.detail == "작년 kg당 71원 · 예측 아님"
    assert "만 원" not in f"{line.text}{line.sub}{line.detail}"


def test_blocked_prereq_line_unlock_money_comes_from_unlock_amounts():
    """막힌 행의 금액 줄은 없어도 먼저 할 일은 '하시면 연 ○만 원'을 가진다(pipeline이 unlock_amounts를 부른다)."""
    fs, sheet = paper(P4_KWARGS)
    mgmt = next(a for a in fs.actions if a.action_id == "PREREQ:mgmt_registration")
    assert mgmt.unlock_low_won and mgmt.unlock_high_won > mgmt.unlock_low_won
    assert line_of(sheet, "농업경영체 등록").text.startswith("조건이 맞으면 연 약 1")


def test_fund_prereq_names_the_enrollment_it_does_not_cover():
    fs, sheet = paper(P2_KWARGS, AS_OF, crops=({**COOP, "crop_code": "당근", "area_m2": 6612, "selfpay_fund": "not_paid"},),
                      already_receiving=frozenset())
    line = line_of(sheet, "자조금 가입")
    assert "내년 10월쯤 참여 신청도 해야 해요" in line.sub


def test_spouse_registration_prereq_counts_voucher_and_two_person_allowance():
    fs, sheet = paper({**P2_KWARGS, "spouse_birth_year": 1960, "spouse_sex": "여"})
    act = next(a for a in fs.actions if a.action_id == "PREREQ:spouse_registration")
    assert (act.unlock_low_won, act.unlock_high_won) == (600_000, 600_000)       # 행복이용권 20만 + 농민수당 2×45만 − 50만
    line = line_of(sheet, "배우자 경영체 등록")
    assert line.text == "조건이 맞으면 연 60만 원" and "20만" in line.detail and "45만" in line.detail


def test_unknown_spouse_sex_gives_check_only_line_without_program_or_amount():
    """배우자 성별을 입력받지 않았으면 추측하지 않는다: 이름·금액 없는 '확인' 줄."""
    fs, sheet = paper({**P2_KWARGS, "spouse_birth_year": 1960})                 # spouse_sex 없음
    act = next(a for a in fs.actions if a.action_id == "PREREQ:spouse_registration")
    assert act.unlocks == () and act.unlock_low_won is None and act.unlock_high_won is None
    line = line_of(sheet, "배우자가 경영체에 등록했는지 확인")
    assert line.print_tag == "CHECK" and "확인할 조건 있음" in line.sub
    assert not any(w in f"{line.text}{line.sub}{line.detail or ''}" for w in ("행복이용권", "만 원", "20만", "45만"))


@pytest.mark.parametrize("over", [{"spouse": "none"}, {"spouse": "registered"}, {"mgmt_status": "none", "mgmt_last_reg_year": None}])
def test_no_spouse_prereq_without_an_unregistered_spouse_or_with_unregistered_owner(over):
    fs, _ = paper(P2_KWARGS, **over)
    assert not [a for a in fs.actions if a.action_id.endswith("spouse_registration")]


def test_pension_style_programs_never_make_a_spouse_voucher_for_a_man():
    fs, _ = paper(P2_KWARGS, spouse_birth_year=1960, spouse_sex="남")
    act = next(a for a in fs.actions if a.action_id == "PREREQ:spouse_registration")
    assert all("VOUCHER" not in u for u in act.unlocks)                          # 남성 배우자: 2인 농민수당 차액만


def test_back_page_hold_note_receiving_names_and_failure_basis(bundle):
    fs, sheet = paper({**P1_KWARGS, "crops": ({"crop_code": "감귤_노지", "area_m2": 5002, "sales_channel": "coop",
                                                "selfpay_fund": "na"},), "total_area_m2": 5002,
                       "already_receiving": frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-ANY"})})
    back = sheet.back
    assert back.hold_note and back.hold_note.startswith("준비 중 ") and "건" in back.hold_note
    summary = " / ".join(back.input_summary)
    assert "이미 받고 계신 것 제주 농민수당 · 직불금(어떤 직불인지 모름)" in summary
    assert any("기준" in x.reason and "입력" in x.reason for x in back.excluded)   # 안 맞는 조건의 기준·입력을 함께


def test_direct_pay_line_asks_for_last_years_notice_when_the_kind_is_unknown():
    fs, sheet = paper({**P1_KWARGS, "already_receiving": frozenset({"NAT-DIRECT-ANY"})})
    assert "통지서" in line_of(sheet, "소농직불금").sub


def test_insurance_line_shows_crop_label_requirement_and_income_stab_note():
    fs, sheet = paper(P2_KWARGS)
    carrot = line_of(sheet, "당근 농작물보험")
    assert carrot.detail and "80%" in carrot.detail and "수입안정보험은 대상이 아니에요" in carrot.sub
    fs1, sheet1 = paper(P1_KWARGS)
    assert line_of(sheet1, "노지감귤(온주) 농작물보험")        # 감귤 앞토막이 아니라 표의 이름


def test_disaster_with_enrolled_insurance_adds_a_claim_line():
    fs, sheet = paper({**P2_KWARGS, "flags": {"disaster_damage": True, "direct_payment_education": "Y"},
                       "crops": ({**COOP, "crop_code": "당근", "area_m2": 6612, "ins_disaster": True},)})
    a = [l for l in sheet.front.sections["A"]]
    assert [l.kind for l in a] == ["DISASTER_REPORT", "INSURANCE_CLAIM"] and "농협" in a[1].text


def test_stale_note_only_for_citrus_growers_and_only_from_15_days():
    fs, _ = paper(P1_KWARGS)
    old = fs.header.model_copy(update={"citrus_as_of": date(2026, 4, 6)})
    assert _stale_notes(fs.model_copy(update={"header": old}), {}) == ("감귤 가격은 2026년 4월 6일 값이에요 · 현재 값 아님",)
    recent = fs.header.model_copy(update={"citrus_as_of": date.fromordinal(AS_OF.toordinal() - STALE_DAYS + 1)})
    assert _stale_notes(fs.model_copy(update={"header": recent}), {}) == ()
    fs2, _ = paper(P2_KWARGS)
    assert _stale_notes(fs2.model_copy(update={"header": old}), {}) == ()       # 당근 농가에게 감귤 띠는 없다


def test_threshold_numbers_are_decimal_quantized_to_won():
    from app.core.sheet import _won_text
    assert _won_text(Decimal("244.8")) == "245원" and _won_text(Decimal("1088")) == "1,088원"


def test_switch_money_line_when_direct_pay_kind_is_unknown():
    """받는 직불 종류를 모르면(NAT-DIRECT-ANY) 소농직불 줄에 '전환하면 약 N만~M만 원 더(확인)': 130만 − 0.4959ha × (150만~215만)."""
    fs, sheet = paper({**P1_KWARGS, "already_receiving": frozenset({"NAT-DIRECT-ANY"})})
    (diff,) = [a for a in fs.amounts if a.kind == "DIFF_IF_SWITCH"]
    assert (diff.low_won, diff.high_won) == (230_000, 560_000)      # 면적직불 74만~107만(만 원 단위 반올림)을 뺀다
    line = line_of(sheet, "소농직불금")
    assert line.text == "130만 원" and line.detail == "전환하면 약 23만~56만 원 더(확인)" and line.print_tag == "CHECK"


def test_switch_money_line_for_the_rival_the_farm_already_receives():
    """면적직불을 이미 받는 농가: 소농직불은 택1로 밀리지만(EXCLUSIVE_OTHER) 더 받을 수 있는 만큼을 줄로 안내한다."""
    from conftest import P5_KWARGS
    fs, sheet = paper({**P5_KWARGS, "crops": ({**P5_KWARGS["crops"][0], "area_m2": 7000},), "total_area_m2": 7000})
    small = next(m for m in fs.matches if m.program_id == "NAT-DIRECT-SMALL@2026")
    assert small.status == "EXCLUSIVE_OTHER"
    line = line_of(sheet, "소농직불금")
    assert line.detail == "전환하면 최대 약 25만 원 더(확인)" and line.print_tag == "CHECK"


def test_no_switch_line_when_switching_loses_money():
    from conftest import P5_KWARGS
    fs, sheet = paper({**P5_KWARGS, "crops": ({**P5_KWARGS["crops"][0], "area_m2": 9000},), "total_area_m2": 9000})
    assert not [a for a in fs.amounts if a.kind == "DIFF_IF_SWITCH"]            # 0.9ha × 150만 = 135만 > 130만


def test_unknown_fund_membership_asks_the_coop_and_missing_base_price_says_coop_check():
    from conftest import P5_KWARGS
    fs, sheet = paper(P5_KWARGS)
    assert any(a.action_id == "ASK_COOP:fund" for a in fs.actions)
    assert line_of(sheet, "자조금 가입 확인").kind == "ASK_COOP"
    assert "기준가 미확인 · 농협에 물어보세요" in line_of(sheet, "가격안정관리제(브로콜리)").text      # 자료가 오래된 게 아니다


@pytest.mark.parametrize("born,status", [(1957, "OPEN_NOW"), (1930, "NOT_ELIGIBLE"), (None, "CHECK")])
def test_spouse_safety_insurance_uses_spouse_birth_year(born, status):
    """배우자 안전보험 나이는 spouse_birth_year로 판정한다(없으면 모름 → CHECK, 나이 범위 15~87)."""
    fs, _ = paper({**P2_KWARGS, "spouse_birth_year": born})
    assert next(r for r in fs.insurance if r.product_id == "nh_safety:spouse").status == status


def test_price_amount_lines_carry_their_crop_and_kg_facts_follow_the_trigger_crop():
    fs, sheet = paper(P2_KWARGS, date(2026, 1, 15), already_receiving=frozenset())
    assert {a.crop_code for a in fs.amounts if a.kind in ("PER_KG_TRIGGER", "REFERENCE_LAST_SEASON")} == {"당근"}
    from app.core.sheet import _Ctx, _kg_facts
    ctx = _Ctx(fs, load_tables(ROOT / "data" / "tables", date(2026, 1, 15)), date(2026, 1, 15))
    pid = next(a.program_id for a in fs.amounts if a.kind == "PER_KG_TRIGGER")
    assert _kg_facts(ctx, pid, "당근")["kg당 최대"] == Decimal("244.8") and _kg_facts(ctx, pid, "양배추") == {}


@pytest.mark.parametrize("as_of,month,text", [
    (date(2026, 11, 13), 3, "2026년 기준 · 2027년 공고 전 · 3월 확인"),      # 올해 3월 공고는 이미 났다 → 다음은 내년
    (date(2026, 1, 15), 3, "2025년 기준 · 2026년 공고 전 · 3월 확인"),      # 올해 3월 공고가 아직 앞 → 올해 공고 전
    (date(2026, 3, 15), 3, "2025년 기준 · 2026년 공고 전 · 3월 확인"),      # 공고 달 안: 아직 안 났다고 본다
    (date(2026, 11, 13), None, "2026년 기준 · 2027년 공고 전 · 공고 시기 확인")])
def test_prior_year_badge_year_follows_the_notice_month(as_of, month, text):
    from app.core.sheet_rules import notice_badge
    assert notice_badge("prior_year_reference", month, as_of) == text
