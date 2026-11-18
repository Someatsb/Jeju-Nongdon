"""다음 행동(Task 15): 종류 우선순위, 묶음, 계통 전환에는 금액 없음."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.actions import KIND_RANK, next_actions
from app.core.models import Action, ApplyWindow
from app.data_layer.tables import load_tables
from conftest import AS_OF, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS
from factsheet_fixtures import amount, make_fs


@pytest.fixture(scope="module")
def bundle():
    return load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)


def full_actions(kwargs, bundle, amounts=()):
    """limit에 안 걸린 전체 행동."""
    fs = make_fs(kwargs, bundle, AS_OF)
    return next_actions(fs.profile, bundle, fs.matches, fs.insurance, amounts, (), AS_OF, limit=50)


def test_kind_rank_follows_brief_order():
    order = ["URGENT", "DISASTER_REPORT", "PREREQ", "KEEP", "APPLY_NOW", "ASK_COOP", "COOP_SWITCH", "APPLY_NEXT", "REVISIT"]
    assert sorted(KIND_RANK, key=KIND_RANK.get) == order


def test_p3_garlic_insurance_open_now_is_first_urgent(bundle):
    acts = make_fs(P3_KWARGS, bundle, AS_OF).actions
    assert acts[0].kind == "URGENT" and acts[0].due == date(2026, 11, 13)
    assert acts[0].sort_key[0] == KIND_RANK["URGENT"]


def test_p4_mgmt_prereq_bundles_blocked_rows_and_copies_amounts(bundle):
    amounts = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),
               amount("JEJU-FARMER-ALLOW@2026", 500_000, 500_000))
    acts = full_actions(P4_KWARGS, bundle, amounts)
    mgmt = next(a for a in acts if a.action_id == "PREREQ:mgmt_registration")
    assert mgmt.kind == "PREREQ" and "NAT-DIRECT-AREA@2026" in mgmt.unlocks
    assert (mgmt.unlock_low_won, mgmt.unlock_high_won) == (2_300_000, 3_080_000)
    assert acts.index(mgmt) < min(i for i, a in enumerate(acts) if a.kind in ("APPLY_NOW", "APPLY_NEXT", "COOP_SWITCH"))


def test_p4_coop_switch_has_no_amount_even_if_amounts_passed(bundle):
    amounts = (amount("JEJU-PSTAB@2026-27#양배추", 100_000, 200_000), amount("JEJU-LOGI@2026-27", 50_000, 60_000))
    switch = [a for a in full_actions(P4_KWARGS, bundle, amounts) if a.kind == "COOP_SWITCH"]
    assert switch and all(a.unlock_low_won is None and a.unlock_high_won is None for a in switch)
    assert any("JEJU-PSTAB@2026-27#양배추" in a.unlocks for a in switch)


def test_disaster_report_uses_table_row_and_ranks_after_urgent(bundle):
    kwargs = {**P2_KWARGS, "flags": {"disaster_damage": True, "direct_payment_education": "Y"}}
    acts = full_actions(kwargs, bundle)
    row = next(p for p in bundle.programs if p.event_type == "재해")
    d = next(a for a in acts if a.kind == "DISASTER_REPORT")
    assert d.action_id == f"DISASTER_REPORT:{row.id}"
    assert all(a.kind != "DISASTER_REPORT" for a in full_actions(P2_KWARGS, bundle))
    kinds = [a.kind for a in acts]
    assert kinds.index("DISASTER_REPORT") < min(kinds.index(k) for k in kinds if k not in ("URGENT", "DISASTER_REPORT"))


def test_keep_mgmt_renewal_year_and_direct_pay_education(bundle):
    ids = {a.action_id for a in full_actions(T1_KWARGS, bundle) if a.kind == "KEEP"}
    assert ids == {"KEEP:mgmt_renewal:2027", "KEEP:direct_pay_education"}   # 2024 + 3 = 2027 <= 2026 + 1
    later = {**T1_KWARGS, "mgmt_last_reg_year": 2025, "flags": {"disaster_damage": False, "direct_payment_education": "Y"}}
    assert not [a for a in full_actions(later, bundle) if a.kind == "KEEP"]   # 2028 > 2027, 교육 완료


def test_already_and_exclusive_rows_never_make_actions(bundle):
    fs = make_fs(T1_KWARGS, bundle, AS_OF)
    skip = {m.program_id for m in fs.matches if m.status in ("ALREADY", "EXCLUSIVE_OTHER")}
    assert skip
    for a in full_actions(T1_KWARGS, bundle):
        assert not skip & set(a.unlocks)


def test_sort_key_is_kind_due_unlock_then_id(bundle):
    acts = full_actions(P3_KWARGS, bundle)
    keys = [a.sort_key for a in acts]
    assert keys == sorted(keys)
    assert all(isinstance(a, Action) and a.sort_key[3] == a.action_id for a in acts)


def test_limit_caps_the_list(bundle):
    fs = make_fs(P3_KWARGS, bundle, AS_OF)
    assert len(next_actions(fs.profile, bundle, fs.matches, fs.insurance, (), (), AS_OF, limit=2)) == 2


# --- 종류별 행동과 30일 경계 ---------------------------------------------------------------------

def _ids(kwargs, bundle):
    return {a.action_id for a in full_actions(kwargs, bundle)}


def test_apply_now_for_open_direct_program(bundle):
    assert "APPLY_NOW:NHIS-FARMER-SUPPORT" in _ids(P3_KWARGS, bundle)


def test_apply_next_for_prior_year_window_not_open_yet(bundle):
    acts = {a.action_id: a for a in full_actions(P2_KWARGS, bundle)}
    nxt = acts["APPLY_NEXT:DO-CALCIUM-SULFUR"]
    assert nxt.kind == "APPLY_NEXT" and nxt.due == date(2027, 1, 2)


def test_revisit_for_insurance_next_window(bundle):
    acts = {a.action_id: a for a in full_actions(P2_KWARGS, bundle)}
    assert acts["REVISIT:ins:당근"].kind == "REVISIT" and acts["REVISIT:ins:당근"].due == date(2027, 7, 1)


def test_ask_coop_when_coop_route_row_does_not_know_coop_shipping(bundle):
    fs = make_fs(P5_KWARGS, bundle, AS_OF)
    matches = tuple(m.model_copy(update={"unknown_fields": ("needs_coop",)}) if m.program_key == "JEJU-PSTAB" else m
                    for m in fs.matches)
    acts = next_actions(fs.profile, bundle, matches, fs.insurance, (), (), AS_OF, limit=50)
    ask = next(a for a in acts if a.kind == "ASK_COOP")
    assert ask.action_id == "ASK_COOP:coop" and any(u.startswith("JEJU-PSTAB@") for u in ask.unlocks)


def _with_window(bundle, days_left):
    """P3의 열려 있는 확정 행(농어업인 건보료 지원)의 창을 '오늘부터 days_left일 뒤 마감'으로 바꾼 행동."""
    fs = make_fs(P3_KWARGS, bundle, AS_OF)
    window = ApplyWindow(always_open=False, open_now=True, next_start=None, next_end=AS_OF + timedelta(days=days_left))
    matches = tuple(m.model_copy(update={"window": window}) if m.program_key == "NHIS-FARMER-SUPPORT" else m
                    for m in fs.matches)
    return {a.action_id: a for a in next_actions(fs.profile, bundle, matches, fs.insurance, (), (), AS_OF, limit=50)}


def test_window_closing_in_30_days_is_urgent(bundle):
    acts = _with_window(bundle, 30)
    assert acts["URGENT:NHIS-FARMER-SUPPORT@2026#읍면"].due == AS_OF + timedelta(days=30)
    assert "APPLY_NOW:NHIS-FARMER-SUPPORT" not in acts


def test_window_closing_in_31_days_is_not_urgent(bundle):
    acts = _with_window(bundle, 31)
    assert "URGENT:NHIS-FARMER-SUPPORT@2026#읍면" not in acts
    assert acts["APPLY_NOW:NHIS-FARMER-SUPPORT"].due == AS_OF + timedelta(days=31)
