"""유형별 종이(Task 22): 작물 x 면적 구간 x 연령대 -> 사람 정보 없는 한 장."""
from functools import lru_cache

import pytest

from app.core.models import FarmProfile, TypeQuery
from app.core.pipeline import build_fact_sheet
from app.core.typesheet import (MAX_OPEN_MONEY, MEMO_CHECKS, CheckItem, TypeSheet, build_typesheet, representative_profile,
                               tier_of)
from app.core.units import py_to_m2
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from conftest import AS_OF, ROOT

Q = TypeQuery(crop_code="양배추", area_band="0_5_to_1ha", age_band="65_74")


@lru_cache(maxsize=None)
def B():
    return load_tables(ROOT / "data" / "tables", AS_OF)


@lru_cache(maxsize=None)
def S():
    return load_snapshot(ROOT / "data" / "snapshot", AS_OF, crops=B().crops)


@lru_cache(maxsize=None)
def T() -> TypeSheet:
    return build_typesheet(Q, B(), S(), AS_OF)


def test_typesheet_has_five_checks():
    assert len(T().self_check5) == 5
    assert all(isinstance(c, CheckItem) and c.question and c.if_no for c in T().self_check5)


def test_typesheet_no_personal_fields():
    js = T().model_dump_json()
    for key in ("emd_code", "birth_year", "phone", "010-"):
        assert key not in js
    assert "name" not in TypeSheet.model_fields and "phone" not in TypeSheet.model_fields


def test_example_is_1000py():
    assert T().example_1000py
    assert all("1,000평" in l.label for l in T().example_1000py)


def test_representative_profile_lower_bound_and_unknowns():
    p = representative_profile(Q, AS_OF)
    assert p.birth_year == AS_OF.year - 65
    assert p.crops[0].area_m2 == 5001 and p.total_area_m2 == 5001 and p.total_area_is_crop_sum
    assert p.mgmt_status == "unknown" and p.crops[0].selfpay_fund == "unknown"
    assert p.crops[0].sales_channel == "unknown" and p.flags.direct_payment_education == "NA"
    assert p.health_ins == "unknown" and not p.already_receiving


@pytest.mark.parametrize("area", ["le_0_5ha", "0_5_to_1ha", "gt_1ha"])
@pytest.mark.parametrize("age", ["lt60", "60_64", "65_74", "75_84", "ge85"])
def test_every_band_builds_valid_profile(area, age):
    assert isinstance(representative_profile(TypeQuery(crop_code="양배추", area_band=area, age_band=age), AS_OF), FarmProfile)


def test_open_money_and_actions():
    t = T()
    assert t.open_money and all(l.section in ("C", "D") and l.kind == "SUPPORT" for l in t.open_money)
    assert 1 <= len(t.first_three) <= 3


def test_example_area_is_1000py():
    assert py_to_m2(1000) == 3306
    assert T().example_1000py[0].amount.low_won is not None


def test_self_check_is_memo_subset_with_memo_wording():
    memo = {c.question: c.if_no for c in MEMO_CHECKS}
    assert len(MEMO_CHECKS) == 7
    assert all(memo.get(c.question) == c.if_no for c in T().self_check5)
    assert len({c.question for c in T().self_check5}) == 5
    assert any("→" in c.if_no for c in T().self_check5)
    assert all("->" not in c.if_no and "지역농협" not in c.if_no for c in MEMO_CHECKS)
    assert any("농협" in c.if_no for c in MEMO_CHECKS)
    assert {"건강보험료", "4,700평"} <= {w for c in MEMO_CHECKS for w in ("건강보험료", "4,700평") if w in c.question}


def test_mgmt_question_first_and_mgmt_move_among_first_three():
    assert "경영체" in T().self_check5[0].question
    assert any(a.action_id == "PREREQ:mgmt_registration" for a in T().first_three)
    assert len(T().first_three) == 3


def test_open_money_cap_more_and_no_fail_rows():
    t = T()
    fs = build_fact_sheet(representative_profile(Q, AS_OF), B(), S(), AS_OF, "x")
    live = {m.program_key for m in fs.matches if m.status in ("LIKELY", "CHECK")}
    assert len(t.open_money) <= MAX_OPEN_MONEY == 4
    assert t.open_money_more >= 1
    assert all(l.program_key in live for l in t.open_money)


def test_open_money_order_by_tier():
    t = T()
    fs = build_fact_sheet(representative_profile(Q, AS_OF), B(), S(), AS_OF, "x")
    by_id = {p.id: p for p in B().programs}
    tier = {m.program_key: tier_of(m, by_id[m.program_id]) for m in fs.matches}
    tiers = [tier[l.program_key] for l in t.open_money]
    assert tiers == sorted(tiers)


def test_tier_of_deadline_first():
    fs = build_fact_sheet(representative_profile(Q, AS_OF), B(), S(), AS_OF, "x")
    by_id = {p.id: p for p in B().programs}
    m = next(m for m in fs.matches if m.status in ("LIKELY", "CHECK"))
    soon = m.model_copy(update={"window": m.window.model_copy(update={"open_now": True, "next_end": AS_OF})})
    assert tier_of(soon, by_id[m.program_id]) == 0


def test_basis_note_states_both_bases():
    n = T().basis_note
    assert "1,000평" in n and "평" in n and "65" in n


def test_second_crop_band_pair_builds():
    q = TypeQuery(crop_code="감귤_노지", area_band="le_0_5ha", age_band="75_84")
    t = build_typesheet(q, B(), S(), AS_OF)
    assert len(t.self_check5) == 5 and len(t.first_three) == 3
    assert len(t.open_money) <= 4 and all("1,000평" in l.label for l in t.example_1000py)
    assert "emd_code" not in t.model_dump_json()


def test_price_stab_fact_line_for_cabbage():
    facts = [e.label for e in T().example_1000py if "kg당 평균" in e.label]
    assert len(facts) == 1 and "153원" in facts[0] and "1,000평" in facts[0] and "작년 계통출하" in facts[0]
