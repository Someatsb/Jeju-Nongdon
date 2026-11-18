"""종이 배치(Task 15): 앞면 A~G, 항목 7개 상한, 줄 길이, 넘침, 배지, 고정 줄."""
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.models import ApplyWindow, InsuranceResult, SourceRef, Term
from app.core.sheet import LIMIT, build_sheet, flatten
from app.data_layer.tables import load_tables
from conftest import AS_OF, P2_KWARGS, P3_KWARGS, P4_KWARGS, T2_KWARGS
from factsheet_fixtures import SRC, amount, make_fs, trigger


@pytest.fixture(scope="module")
def bundle():
    return load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)


P4_AMOUNTS = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)
P2_AMOUNTS = (amount("KRC-FARMLAND-PENSION@2026", 100_000, 100_000), amount("DO-CALCIUM-SULFUR@2026", 130_000, 130_000),
              amount("NHIS-FARMER-SUPPORT@2026#읍면", None, None, kind="UNDISCLOSED"))


@pytest.fixture(scope="module")
def fs_p4(bundle):
    return make_fs(P4_KWARGS, bundle, AS_OF, amounts=P4_AMOUNTS)


@pytest.fixture(scope="module")
def fs_p2(bundle):
    return make_fs(P2_KWARGS, bundle, AS_OF, amounts=P2_AMOUNTS,
                   triggers=(trigger("PRICE_STAB", "NOT_MET"), trigger("LOGISTICS", "NOT_APPLICABLE")))


@pytest.fixture(scope="module")
def fs_p3(bundle):
    return make_fs(P3_KWARGS, bundle, date(2026, 11, 13))


@pytest.fixture(scope="module")
def fs_many(bundle):
    """모든 판정을 LIKELY로 바꿔 항목이 7개를 넘게 만든 합성 FactSheet."""
    fs = make_fs(P3_KWARGS, bundle, AS_OF)
    matches = tuple(m.model_copy(update={"status": "LIKELY", "missing_prereqs": ()}) for m in fs.matches)
    return make_fs(P3_KWARGS, bundle, AS_OF, matches=matches)


def test_p4_front_first_item_is_prereq_mgmt(fs_p4, bundle):
    s = build_sheet(fs_p4, bundle, AS_OF)
    first = s.front.sections["B"][0]
    assert first.kind == "PREREQ" and "경영체" in first.title
    assert "180만" in first.text and "확인할 조건 있음" in (first.sub or "")
    assert first.badge and "공고 전" in first.badge


def test_front_item_cap_7_and_overflow_to_back(fs_many, bundle):
    s = build_sheet(fs_many, bundle, AS_OF)
    assert s.front.item_count <= 7 and len(s.overflow) >= 1
    assert s.back.overflow == s.overflow
    assert len(s.front.sections["A"]) <= 2


def test_line_length_limits(fs_p4, fs_p2, fs_p3, fs_many, bundle):
    for fs in (fs_p4, fs_p2, fs_p3, fs_many):
        lines = list(flatten(build_sheet(fs, bundle, fs.as_of).front))
        assert lines and all(len(l.text) <= LIMIT[l.pt] for l in lines)
        assert all(len(l.sub) <= LIMIT[14] for l in lines if l.sub)


def test_fixed_lines_always_present(fs_p2, bundle):
    texts = [l.text for l in flatten(build_sheet(fs_p2, bundle, AS_OF).front)]
    assert any("영농도우미" in t and "60일 안에 농협" in t for t in texts)


def test_disaster_unreported_line_only_when_no_damage(fs_p2, bundle):
    fixed = build_sheet(fs_p2, bundle, AS_OF).front.fixed
    assert any("재해 피해는" in l.text and "말씀해 주세요" in l.text and "10일 안" in l.text for l in fixed)   # 한 줄: 안내 + 신고 기한
    hit = make_fs({**P2_KWARGS, "flags": {"disaster_damage": True, "direct_payment_education": "Y"}}, bundle, AS_OF)
    s = build_sheet(hit, bundle, AS_OF)
    assert not any("재해 피해는" in l.text and "말씀해 주세요" in l.text for l in s.front.fixed)
    first = s.front.sections["A"][0]
    assert first.kind == "DISASTER_REPORT" and "10일 안에" in first.text + (first.detail or "")


def test_p3_urgent_garlic_insurance_on_1113(fs_p3, bundle):
    s = build_sheet(fs_p3, bundle, date(2026, 11, 13))
    assert s.front.sections["A"] and "11월 13일" in s.front.sections["A"][0].text
    assert "마늘" in s.front.sections["A"][0].title


def test_prior_year_rows_carry_badge_with_notice_month(fs_p2, bundle):
    s = build_sheet(fs_p2, bundle, AS_OF)
    lines = [l for l in flatten(s.front) if l.program_key == "DO-CALCIUM-SULFUR"]
    assert len(lines) == 1
    assert lines[0].badge == "2026년 기준 · 2027년 공고 전 · 1월 확인"
    assert "공고 전" not in lines[0].text and "13만 원" in lines[0].text


def test_one_line_per_program_key_and_no_sum(fs_p2, bundle):
    s = build_sheet(fs_p2, bundle, AS_OF)
    keys = [l.program_key for l in flatten(s.front) if l.program_key]
    assert len(keys) == len(set(keys))
    assert not any("합계" in l.text for l in flatten(s.front))


def test_already_renewing_rows_become_e_prime_line_once(bundle):
    lines = build_sheet(make_fs(T2_KWARGS, bundle, AS_OF), bundle, AS_OF).front.sections["E2"]
    assert {l.program_key for l in lines} >= {"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA"}
    assert all("작년처럼 다시 신청" in l.text for l in lines)
    assert len({l.program_key for l in lines}) == len(lines)


def test_pension_and_retire_rows_are_not_printed(fs_p2, bundle):
    keys = {l.program_key for l in flatten(build_sheet(fs_p2, bundle, AS_OF).front)}
    assert not keys & {"KRC-FARMLAND-PENSION", "NAT-RETIRE-DIRECT"}


def test_back_page_excluded_top3_conds_and_unknown_source_date(bundle):
    base = make_fs(P4_KWARGS, bundle, AS_OF, amounts=P4_AMOUNTS)
    matches = tuple(m.model_copy(update={"source": m.source.model_copy(update={"as_of": None})}) for m in base.matches)
    fs = make_fs(P4_KWARGS, bundle, AS_OF, amounts=P4_AMOUNTS, matches=matches)
    back = build_sheet(fs, bundle, AS_OF).back
    assert len(back.excluded) <= 3
    assert back.line_conds and any("확인일 미상" in lc.source for lc in back.line_conds)
    assert back.input_summary and back.fingerprint_slot


def test_trigger_note_is_read_when_present(fs_p2, bundle):
    noted = tuple(t.model_copy(update={"note": "시험 메모"}) for t in fs_p2.triggers)
    fs = fs_p2.model_copy(update={"triggers": noted})
    assert any("시험 메모" in t for t in build_sheet(fs, bundle, AS_OF).back.price_basis)
    assert build_sheet(fs_p2, bundle, AS_OF).back.price_basis


def _urgent_window_fs(bundle):
    """P3의 열린 건보료 지원 행을 10일 뒤 마감으로 바꿔 A(급한 것)와 D(직접 신청)에 모두 오를 수 있게 한다."""
    base = make_fs(P3_KWARGS, bundle, AS_OF)
    window = ApplyWindow(always_open=False, open_now=True, next_start=None, next_end=AS_OF + timedelta(days=10))
    matches = tuple(m.model_copy(update={"window": window}) if m.program_key == "NHIS-FARMER-SUPPORT" else m
                    for m in base.matches)
    return make_fs(P3_KWARGS, bundle, AS_OF, matches=matches)


def test_urgent_program_is_printed_once_not_again_in_c_d(bundle):
    s = build_sheet(_urgent_window_fs(bundle), bundle, AS_OF)
    in_a = [l for l in s.front.sections["A"] if l.program_key == "NHIS-FARMER-SUPPORT"]
    assert len(in_a) == 1
    assert not [l for sec in ("C", "D") for l in s.front.sections[sec] if l.program_key == "NHIS-FARMER-SUPPORT"]
    assert not [l for l in s.overflow if l.program_key == "NHIS-FARMER-SUPPORT"]      # 넘침(뒷면)에도 다시 안 나온다


@pytest.mark.parametrize("name", ["fs_p2", "fs_p3", "fs_p4", "fs_many", "urgent"])
def test_no_program_key_appears_in_two_sections(name, request, bundle):
    fs = _urgent_window_fs(bundle) if name == "urgent" else request.getfixturevalue(name)
    s = build_sheet(fs, bundle, fs.as_of)
    where: dict[str, set[str]] = {}
    for sec, lines in s.front.sections.items():
        for l in lines:
            if l.program_key:
                where.setdefault(l.program_key, set()).add(sec)
    for l in s.overflow:
        if l.program_key:
            where.setdefault(l.program_key, set()).add(l.section)
    keys = [l.program_key for sec in s.front.sections.values() for l in sec if l.program_key]
    keys += [l.program_key for l in s.overflow if l.program_key]
    assert all(len(secs) == 1 for secs in where.values()), where
    assert len(keys) == len(set(keys))


def _p4_with_last_season(bundle, per_kg=153):
    pid = "JEJU-PSTAB@2026-27#양배추"
    ref = amount(pid, 8_578_098, 8_578_098, kind="REFERENCE_LAST_SEASON")
    term = Term(label="작년 kg당 평균", value=Decimal(per_kg), unit="원/kg", source=SRC)
    return make_fs(P4_KWARGS, bundle, AS_OF, amounts=(*P4_AMOUNTS, ref.model_copy(update={"terms": (term,)})))


def test_p4_coop_switch_line_in_section_c_per_golden_k2(bundle):
    s = build_sheet(_p4_with_last_season(bundle), bundle, AS_OF)
    assert not [l for l in s.front.sections["B"] if l.kind == "COOP_SWITCH"]
    line = next(l for l in s.front.sections["C"] if l.kind == "COOP_SWITCH" and l.program_key == "JEJU-PSTAB")
    whole = " ".join(filter(None, (line.title, line.text, line.sub)))
    for need in ("양배추", "자조금", "참여 신청", "153원"):
        assert need in whole
    assert "만 원" not in whole and "원" not in line.text          # 금액 없음(§12-A(2)): 사실 한 줄은 sub
    assert "지난 시즌 kg당 153원" in (line.sub or "")
    assert line.badge and "공고 전" in line.badge


def test_coop_switch_fact_comes_from_data_not_literal(bundle):
    s = build_sheet(_p4_with_last_season(bundle, per_kg=171), bundle, AS_OF)
    line = next(l for l in s.front.sections["C"] if l.kind == "COOP_SWITCH" and l.program_key == "JEJU-PSTAB")
    assert "지난 시즌 kg당 171원" in line.sub and "153" not in line.sub


def test_coop_switch_steps_follow_missing_prereqs(bundle):
    fs = _p4_with_last_season(bundle)
    matches = tuple(m.model_copy(update={"missing_prereqs": ("needs_coop",), "unknown_fields": ()})
                    if m.program_key == "JEJU-PSTAB" else m for m in fs.matches)
    fs2 = make_fs(P4_KWARGS, bundle, AS_OF, amounts=fs.amounts, matches=matches)
    line = next(l for l in build_sheet(fs2, bundle, AS_OF).front.sections["C"]
                if l.kind == "COOP_SWITCH" and l.program_key == "JEJU-PSTAB")
    assert "농협" in line.text and "자조금" not in line.text and "참여 신청" not in line.text


def _prior_badge_for_crop(bundle, link_confirmed):
    base = make_fs(P2_KWARGS, bundle, AS_OF)
    matches = tuple(m.model_copy(update={"row_status": "confirmed"}) if link_confirmed and m.program_id == "NAT-CROP-INS@2026#당근" else m
                    for m in base.matches)
    s = build_sheet(make_fs(P2_KWARGS, bundle, AS_OF, matches=matches), bundle, AS_OF)
    return next(l for l in s.front.sections["E"] if "당근" in l.title).badge


def test_insurance_badge_follows_the_linked_program_row(bundle):
    assert _prior_badge_for_crop(bundle, False) == "2026년 기준 · 2027년 공고 전 · 7월 확인"
    assert _prior_badge_for_crop(bundle, True) is None


def test_insurance_link_is_by_source_id_not_by_name():
    from app.core.sheet import insurance_program_ids
    r = InsuranceResult(product_id="crop_disaster:당근#2", status="NEXT_WINDOW", next_window=None, revisit_month=None,
                        reasons=(), source=SourceRef(source_id="supports:NAT-CROP-INS@2026#당근", url=None, as_of=None))
    assert insurance_program_ids([r]) == {"NAT-CROP-INS@2026#당근"}
