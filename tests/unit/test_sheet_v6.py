"""4차 심사 보완(v6): 앞면 문구가 지원제도 표(supports.csv)·접수처 표(offices.csv)와 어긋나지 않는다."""
from pathlib import Path

import pytest

from app.core.sheet import build_sheet, flatten
from app.core.sheet_rules import DISCLAIMER
from app.data_layer.tables import load_tables
from conftest import AS_OF, P4_KWARGS
from factsheet_fixtures import amount, make_fs

P4_AMOUNTS = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)


@pytest.fixture(scope="module")
def bundle():
    return load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)


@pytest.fixture(scope="module")
def sheet(bundle):
    return build_sheet(make_fs(P4_KWARGS, bundle, AS_OF, amounts=P4_AMOUNTS), bundle, AS_OF)


def _line(sheet, key):
    return next(l for l in flatten(sheet.front) if l.program_key == key)


def test_logistics_line_says_coop_files_not_always_open(sheet, bundle):
    row = next(p for p in bundle.programs if p.program_key == "JEJU-LOGI")
    assert row.applicant == "농협경유" and row.apply_cycle == "자동"       # 표의 값이 근거
    line = _line(sheet, "JEJU-LOGI")
    assert "농협이 대신 신청" in line.sub and "언제든 신청할 수 있어요" not in line.sub
    nhis = _line(sheet, "NHIS-FARMER-SUPPORT")                              # 개인·상시인 줄은 그대로
    assert "언제든 신청할 수 있어요" in nhis.text + (nhis.sub or "")


def test_either_conditions_join_with_or_and_all_have_first_prefix(sheet, bundle):
    soil = next(p for p in bundle.programs if p.program_key == "JEJU-SOIL-ECO")
    assert soil.needs_coop == "E" and soil.needs_selfpay_fund == "E"
    assert _line(sheet, "JEJU-SOIL-ECO").text == "먼저: 자조금 또는 농협 출하"
    assert _line(sheet, "JEJU-LOGI").text == "먼저: 자조금 + 농협 출하"
    assert _line(sheet, "JEJU-PSTAB").text.startswith("먼저: ")


def test_price_stab_line_says_season_over_and_next_month_from_table(sheet, bundle):
    row = next(p for p in bundle.programs if p.program_key == "JEJU-PSTAB")
    assert row.apply_end < AS_OF and row.next_month == 9
    sub = _line(sheet, "JEJU-PSTAB").sub
    assert "내년 9월쯤 물어보세요" in sub and "예년" not in sub and "다음 9월쯤" not in sub


def test_price_stab_source_is_the_crop_row_not_broccoli(sheet):
    assert _line(sheet, "JEJU-PSTAB").program_id == "JEJU-PSTAB@2026-27#양배추"


def test_insurance_next_window_is_union_months_not_one_date(sheet):
    ins = next(l for l in flatten(sheet.front) if l.kind == "INSURANCE")
    assert ins.text == "내년 8~10월에 가입해요 · 날짜는 농협에 물어보세요"


def test_calendar_cells_use_union_windows(sheet):
    _, allowance, insurance = sheet.front.calendar3
    assert (allowance.start.month, allowance.start.day, allowance.end.month, allowance.end.day) == (3, 1, 5, 31)
    assert allowance.label == "직불 3~5월 · 수당 3월"
    assert (insurance.start.month, insurance.end.month, insurance.end.day) == (8, 10, 30)


def test_office_boxes_carry_line_numbers_and_priority(sheet):
    boxes = sheet.front.sections["F"]
    offices = [l for l in boxes if l.title.startswith("가실 곳")]
    assert [l.title for l in offices][:2] == ["가실 곳 ①", "가실 곳 ⑤"]           # B·D 줄의 창구가 앞
    assert "1577-1000" in offices[1].text                                       # 건보공단 지사가 잘리지 않는다
    assert len(offices) <= 3


def test_soil_eco_office_narrowed_to_own_emd(bundle):
    from app.core.sheet import _own_emd_office
    row = next(p for p in bundle.programs if p.program_key == "JEJU-SOIL-ECO")
    assert _own_emd_office(row.office, "애월읍") == ("애월농협", row.office)
    assert _own_emd_office(row.office, "추자면") == (row.office, None)       # 이름이 안 맞으면 원문 그대로


def test_mgmt_line_has_when_and_rent_prep_detail(sheet):
    a = next(l for l in sheet.front.sections["B"] if l.title.startswith("농업경영체 등록"))
    assert a.detail == "직불은 내년 3~5월쯤 신청해요 · 임차 땅은 증빙 서류를 물어보세요"


def test_back_side_uses_ha_korean_names_and_season_words(sheet):
    area = next(lc for lc in sheet.back.line_conds if lc.program_key == "NAT-DIRECT-AREA")
    text = " ".join(f"{c.required} {c.actual}" for c in area.conds)
    assert "기준 0.1ha 이상" in text and "입력 1.19ha" in text and "㎡" not in text
    assert not any(l.startswith(("PRICE_STAB", "LOGISTICS", "ISOLATION_HISTORY")) for l in sheet.back.price_basis)
    assert sheet.back.office_names["emd_home"] == "주소지 읍·면사무소, 동 주민센터"


def test_footer_first_line_names_the_issuer():
    assert DISCLAIMER[0] == "이 종이를 뽑아 준 곳: 제주빅데이터센터 창구 · 궁금한 점도 그곳에"
    assert len(DISCLAIMER[0]) <= 40
