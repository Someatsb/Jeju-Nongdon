"""Task 20: LLM에 넘기는 숫자 없는 보기. 열두 골든 모두 JSON 어디에도 숫자가 없어야 한다.

열두 개 = P1~P5·T1·T2 일곱 개 + 같은 일곱 중 칸 몇 개만 바꾼 변종 다섯 개(B 경계 골든은 Task 34에서 맞춘다).
"""
import re
from functools import lru_cache

import pytest

from app.core.models import FarmProfile, NarrativeInput
from app.core.pipeline import build_fact_sheet, narrative_input
from app.core.sheet import EmptyFront, build_sheet
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, ROOT, T1_KWARGS, T2_KWARGS

GOLDEN12 = {
    "P1": P1_KWARGS, "P2": P2_KWARGS, "P3": P3_KWARGS, "P4": P4_KWARGS, "P5": P5_KWARGS, "T1": T1_KWARGS, "T2": T2_KWARGS,
    "P4_registered": {**P4_KWARGS, "mgmt_status": "over_2y", "mgmt_last_reg_year": 2024, "spouse": "registered"},
    "P2_disaster": {**P2_KWARGS, "flags": {"disaster_damage": True, "direct_payment_education": "N"}},
    "P3_unknowns": {**P3_KWARGS, "health_ins": "unknown", "owner_sex": None},
    "P1_nothing_yet": {**P1_KWARGS, "already_receiving": frozenset()},
    "P5_insured": {**P5_KWARGS, "ins_safety": frozenset({"owner", "spouse"})},
}
DIGIT = re.compile(r"[0-9０-９]")
PLACEHOLDER_ID = re.compile(r"[a-z][a-z0-9_]*")


@lru_cache(maxsize=None)
def tables():
    return load_tables(ROOT / "data" / "tables", AS_OF)


@lru_cache(maxsize=None)
def snap():
    return load_snapshot(ROOT / "data" / "snapshot", AS_OF, crops=tables().crops)


def fact_sheet(kwargs):
    return build_fact_sheet(FarmProfile(**kwargs), tables(), snap(), AS_OF, "v")


@pytest.mark.parametrize("name", list(GOLDEN12))
def test_narrative_input_numberless_all_golden(name):
    fs = fact_sheet(GOLDEN12[name])
    ni = narrative_input(fs)
    assert isinstance(ni, NarrativeInput) and not DIGIT.search(ni.model_dump_json())
    assert fs.profile.emd_code not in ni.model_dump_json()


@pytest.mark.parametrize("name", list(GOLDEN12))
def test_ids_are_placeholder_safe_and_aliases_map_back(name):
    fs = fact_sheet(GOLDEN12[name])
    ni = narrative_input(fs)
    for item in ni.items:
        assert PLACEHOLDER_ID.fullmatch(item.program_id), item
        assert item.official_name
    for alias, real in ni.aliases.items():
        assert PLACEHOLDER_ID.fullmatch(alias)
        assert real  # 되돌릴 실제 id(숫자 포함 가능)
    assert "aliases" not in ni.model_dump_json()
    assert len({i.fact_id for i in ni.items}) == len(ni.items)


@pytest.mark.parametrize("name", ["P1", "P2", "P3", "P4", "P5", "T1", "T2"])
def test_empty_sheet_flag_matches_printed_sheet(name):
    fs = fact_sheet(GOLDEN12[name])
    assert narrative_input(fs).empty_sheet == isinstance(build_sheet(fs, tables(), AS_OF).front, EmptyFront)


def test_p4_items_carry_status_missing_and_office():
    ni = narrative_input(fact_sheet(P4_KWARGS))
    mgmt = next(i for i in ni.items if i.section == "action" and "경영체" in i.official_name)
    assert mgmt.status == "PREREQ" and mgmt.office_id
    support = [i for i in ni.items if i.section == "support"]
    assert support and any(i.missing for i in support)
    assert any(i.section == "insurance" for i in ni.items)


def test_empty_sheet_items_use_empty_section():
    fs = fact_sheet(T2_KWARGS)
    fs = fs.model_copy(update={"matches": tuple(m.model_copy(update={"status": "ALREADY", "missing_prereqs": ()})
                                                for m in fs.matches), "actions": ()})
    ni = narrative_input(fs)
    assert ni.empty_sheet and ni.items and {i.section for i in ni.items} <= {"empty", "insurance"}
    assert any(i.section == "empty" and i.status == "ALREADY" for i in ni.items)


def test_digit_bearing_id_maps_back_through_aliases():
    fs = fact_sheet(P4_KWARGS)
    ni = narrative_input(fs)
    real = ni.aliases["jeju_pstab"]
    assert DIGIT.search(real) and real.startswith("JEJU-PSTAB@") and real in {m.program_id for m in fs.matches}
    assert not DIGIT.search("jeju_pstab")


def test_unknown_insurance_target_is_an_error():
    fs = fact_sheet(P4_KWARGS)
    bad = fs.insurance[0].model_copy(update={"product_id": "crop_disaster:없는작물", "status": "NEXT_WINDOW"})
    with pytest.raises(ValueError, match="없는작물"):
        narrative_input(fs.model_copy(update={"insurance": (bad,)}))


def test_same_group_actions_get_distinct_aliases():
    fs = fact_sheet(P4_KWARGS)
    keep = next(a for a in fs.actions if a.kind == "PREREQ").model_copy(update={"kind": "KEEP"})
    two = (keep.model_copy(update={"action_id": "KEEP:mgmt_renewal:2024"}),
           keep.model_copy(update={"action_id": "KEEP:mgmt_renewal:2027"}))
    ni = narrative_input(fs.model_copy(update={"actions": two}))
    acts = [i for i in ni.items if i.section == "action"]
    assert len(acts) == 2 and len({i.program_id for i in acts}) == 2 and len({i.fact_id for i in acts}) == 2
    assert {ni.aliases[i.program_id] for i in acts} == {"KEEP:mgmt_renewal:2024", "KEEP:mgmt_renewal:2027"}
    assert not DIGIT.search(ni.model_dump_json())
