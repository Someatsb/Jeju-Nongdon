"""Task 20 앞뒤 면 보강: 줄 꼬리표(print_tag·trigger_id·no_numbers), 작년 공고 달, 뒷면 한글 라벨."""
import re

import pytest

from app.core.insurance import check_insurance
from app.core.sheet import Line, build_sheet, flatten
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P4_KWARGS, ROOT
from factsheet_fixtures import amount, make_fs, trigger

RAW_CODE = re.compile(r"[a-z]+_[a-z0-9_]+|\b(?:over|under)_\d")


@pytest.fixture(scope="module")
def bundle():
    return load_tables(ROOT / "data" / "tables", AS_OF)


def test_line_defaults():
    line = Line(section="D", kind="SUPPORT", title="t", text="x", pt=16)
    assert line.trigger_id is None and line.no_numbers is False and line.print_tag is None


def test_back_input_summary_has_no_raw_codes_p4(bundle):
    fs = make_fs(P4_KWARGS, bundle, AS_OF, amounts=(amount("NAT-DIRECT-AREA@2026", 1, 2),))
    back = build_sheet(fs, bundle, AS_OF).back
    assert not [s for s in back.input_summary if RAW_CODE.search(s)], back.input_summary
    assert any("임차" in s for s in back.input_summary) and any("등록 안 함" in s or "미등록" in s for s in back.input_summary)


def test_back_conds_are_korean_p4(bundle):
    fs = make_fs(P4_KWARGS, bundle, AS_OF)
    back = build_sheet(fs, bundle, AS_OF).back
    conds = [c for lc in back.line_conds for c in lc.conds]
    assert conds
    for c in conds:
        assert not RAW_CODE.search(c.field), c
        assert not RAW_CODE.search(c.actual.split(":")[-1]), c
        assert c.required not in ("Y", "N", "E") and c.actual not in ("Y", "N")
    assert any(c.field == "경영체 등록" for c in conds)


def test_excluded_reason_has_no_raw_code(bundle):
    back = build_sheet(make_fs(P1_KWARGS, bundle, AS_OF), bundle, AS_OF).back
    assert not [e for e in back.excluded if RAW_CODE.search(e.reason)]


def test_print_tag_follows_match_counts(bundle):
    fs = make_fs(P4_KWARGS, bundle, AS_OF)
    by_id = {p.id: p for p in bundle.programs}
    lines = [l for l in flatten(build_sheet(fs, bundle, AS_OF).front) if l.kind == "SUPPORT"]
    shown = {m.program_key: m for m in fs.matches}
    for l in lines:
        m, p = shown[l.program_key], by_id[shown[l.program_key].program_id]
        if not p.manual_check:
            assert l.print_tag is None
            continue
        unknown = any(c.result == "UNKNOWN" for c in m.conds) or p.income_test == "심사"
        assert l.print_tag == ("CHECK" if unknown else "LIKELY")


def _c_line(fs, bundle):
    return [l for l in flatten(build_sheet(fs, bundle, AS_OF).front) if l.section == "C" and l.kind == "SUPPORT"]


def test_trigger_id_only_when_provisional(bundle):
    from conftest import P2_KWARGS
    prov = trigger("PRICE_STAB", "MET").model_copy(update={"provisional": True})
    p2 = {**P2_KWARGS, "already_receiving": frozenset()}
    fs = make_fs(p2, bundle, AS_OF, triggers=(prov, trigger("LOGISTICS", "NOT_APPLICABLE")))
    lines = [l for l in _c_line(fs, bundle) if "가격안정" in l.title]
    assert lines and all(l.trigger_id == "PRICE_STAB" and "(잠정)" in l.text for l in lines)
    fs2 = make_fs(p2, bundle, AS_OF, triggers=(trigger("PRICE_STAB", "MET"), trigger("LOGISTICS", "NOT_APPLICABLE")))
    assert all(l.trigger_id is None for l in flatten(build_sheet(fs2, bundle, AS_OF).front))


def test_source_hold_insurance_line_has_no_numbers(bundle):
    fs = make_fs(P4_KWARGS, bundle, AS_OF)
    hold = frozenset(f"supports:{p.id}" for p in bundle.programs if p.status == "hold")
    fs = fs.model_copy(update={"insurance": check_insurance(fs.profile, bundle.insurance, AS_OF, hold)})
    assert any("source_hold" in r.reasons for r in fs.insurance if r.product_id.startswith("nh_safety"))
    sheet = build_sheet(fs, bundle, AS_OF)
    # 출처가 보류(hold)인 보험은 앞면 줄로 나오지 않고, 뒷면 '준비 중' 수에만 센다
    assert not [l for l in flatten(sheet.front) if l.title == "NH안전보험"]
    assert sheet.back.hold_note and "준비 중" in sheet.back.hold_note
    plain = make_fs(P4_KWARGS, bundle, AS_OF)
    assert not any(l.no_numbers for l in flatten(build_sheet(plain, bundle, AS_OF).front))


def _literal(model, field: str) -> set[str]:
    """pydantic 모델 칸의 Literal 허용값(타입에서 바로 읽는다 — 값을 시험 안에 다시 적지 않는다)."""
    from typing import get_args
    return set(get_args(model.model_fields[field].annotation))


def test_back_page_never_prints_raw_codes(bundle):
    """뒷면이 보여 줄 수 있는 코드값·칸 이름은 모두 한글 표에 있다(허용값은 모델의 Literal에서 읽는다)."""
    from app.core.match import match_supports
    from app.core.models import CropPlot, FarmProfile
    from app.core.sheet_rules import FIELD_LABEL, VALUE_LABEL, YN_LABEL
    for table, model, field in (("mgmt_status", FarmProfile, "mgmt_status"), ("land_tenure", FarmProfile, "land_tenure"),
                                ("spouse", FarmProfile, "spouse"), ("health_ins", FarmProfile, "health_ins"),
                                ("sales_channel", CropPlot, "sales_channel"), ("selfpay_fund", CropPlot, "selfpay_fund")):
        assert set(VALUE_LABEL[table]) == _literal(model, field), table
    assert set(YN_LABEL) == {"Y", "N", "NA", "E"}
    # 조건표 칸 이름: 판정기가 실제로 낸 모든 field(여러 농가 × 표 전체 행). 소스 글자를 뒤지지 않는다.
    from conftest import P2_KWARGS, P3_KWARGS, P5_KWARGS, T1_KWARGS
    seen = {c.field for kw in (P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS)
            for m in match_supports(FarmProfile(**kw), bundle.programs, AS_OF, crops=bundle.crops) for c in m.conds}
    assert {"health_ins_in", "min_age", "needs_coop"} <= seen          # 건강보험 칸도 이 농가들에서 실제로 나온다
    assert seen <= set(FIELD_LABEL), seen - set(FIELD_LABEL)


def test_back_input_summary_shows_health_insurance_in_korean(bundle):
    fs = make_fs(P1_KWARGS, bundle, AS_OF)
    line = next(s for s in build_sheet(fs, bundle, AS_OF).back.input_summary if s.startswith("건강보험"))
    assert line == "건강보험 지역가입자"
