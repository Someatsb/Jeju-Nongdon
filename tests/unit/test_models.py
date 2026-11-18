"""Task 2(U02) 코어 모델: 입력 경계, 금액 없는 계통 전환, 숫자 없는 보기, supports.csv 78컬럼."""
import json
import typing

import pytest
from pydantic import ValidationError

from app.core.models import Action, CropPlot, FarmProfile, NarrativeInput, NarrativeItem, Program
from conftest import P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, ROOT, T1_KWARGS, T2_KWARGS

PERSONAS = {"P1": P1_KWARGS, "P2": P2_KWARGS, "P3": P3_KWARGS, "P4": P4_KWARGS,
            "P5": P5_KWARGS, "T1": T1_KWARGS, "T2": T2_KWARGS}


# --- 계획서 Step 1의 4건(그대로) ---

def test_farmprofile_rejects_unknown_field():
    with pytest.raises(ValidationError): FarmProfile(**P4_KWARGS, hospitalized=True)


def test_area_over_30ha_rejected():
    with pytest.raises(ValidationError): CropPlot(crop_code="cabbage", area_m2=300_001, sales_channel="coop", selfpay_fund="unknown")


def test_coop_switch_action_cannot_carry_amount():
    with pytest.raises(ValidationError): Action(action_id="a", kind="COOP_SWITCH", office_id="coop", unlocks=(), unlock_low_won=10000, unlock_high_won=None, due=None, documents=(), sort_key=(5,))


def test_narrative_input_has_no_number_keys():
    assert not {"birth_year","area_m2","total_area_m2","emd_code"} & set(NarrativeInput.model_fields)


# --- 덧붙인 것: 페르소나 픽스처, 경계의 반대편, 표 스키마 동기 ---

@pytest.mark.parametrize("name", sorted(PERSONAS))
def test_persona_kwargs_build_profile_and_roundtrip(name):
    p = FarmProfile(**PERSONAS[name])
    assert FarmProfile.model_validate_json(p.model_dump_json()) == p


def test_valid_edges_accepted():
    assert CropPlot(crop_code="cabbage", area_m2=300_000, sales_channel="coop", selfpay_fund="unknown").area_m2 == 300_000
    a = Action(action_id="a", kind="COOP_SWITCH", office_id="coop", unlocks=(), unlock_low_won=None, unlock_high_won=None, due=None, documents=(), sort_key=(5,))
    assert a.unlock_low_won is None and a.unlock_high_won is None


def test_area_error_message_is_korean():
    with pytest.raises(ValidationError) as e:
        CropPlot(crop_code="cabbage", area_m2=300_001, sales_channel="coop", selfpay_fund="unknown")
    assert "평으로" in str(e.value)


def test_narrative_input_rejects_digits():
    item = dict(section="support", fact_id="M:jeju_farmer_allowance", program_id="jeju_farmer_allowance",
                official_name="제주 농민수당", status="BLOCKED_PREREQ", row_status="prior_year_reference",
                missing=("needs_mgmt",), window="upcoming", office_id="emd_office")
    assert NarrativeInput(empty_sheet=False, items=(NarrativeItem(**item),)).items[0].program_id == "jeju_farmer_allowance"
    for key, bad in (("official_name", "2026 제주 농민수당"), ("missing", ("min_mgmt_years>=2",)), ("office_id", "농관원 ２지원")):
        with pytest.raises(ValidationError): NarrativeItem(**{**item, key: bad})


def _literal_values(annotation):
    """Program 필드 타입에서 Literal 값만 모은다(None·tuple 껍질 제거)."""
    out = set()
    stack = [annotation]
    while stack:
        t = stack.pop()
        if typing.get_origin(t) is typing.Literal:
            out |= set(typing.get_args(t))
        else:
            stack.extend(a for a in typing.get_args(t) if a is not Ellipsis)
    return out


def _bounds(field):
    out = {}
    for m in field.metadata:
        for attr, key in (("ge", "min"), ("le", "max"), ("max_length", "max")):
            if getattr(m, attr, None) is not None:
                out[key] = getattr(m, attr)
    return out


def test_program_matches_supports_schema():
    cols = json.loads((ROOT / "data" / "tables" / "schema.json").read_text(encoding="utf-8"))["tables"]["supports"]["columns"]
    fields = Program.model_fields
    assert [c["key"] for c in cols if c["key"] not in fields] == []
    for c in cols:
        f = fields[c["key"]]
        if "enum" in c:
            assert _literal_values(f.annotation) == set(c["enum"]), c["key"]
        want = {k: c[k] for k in ("min", "max") if k in c}
        assert _bounds(f) == want, c["key"]
    assert typing.get_args(fields["status"].annotation) == ("confirmed", "prior_year_reference", "hold")


def test_spouse_birth_year_range_matches_birth_year():
    for bad in (1899, 2011, 85):
        with pytest.raises(ValidationError): FarmProfile(**{**P4_KWARGS, "spouse_birth_year": bad})
    assert FarmProfile(**{**P4_KWARGS, "spouse_birth_year": 1900}).spouse_birth_year == 1900
    assert FarmProfile(**{**P4_KWARGS, "spouse_birth_year": 2010}).spouse_birth_year == 2010
    assert FarmProfile(**P4_KWARGS).spouse_birth_year is None
