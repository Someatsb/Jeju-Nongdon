"""표 행에서 만든 태그(app/catalog/tags.py): 42행 전부 3~4개이고, 태그 글이 표 값과 어긋나지 않는다(설계서 B-2).

어긋남 검사(holds)는 태그 글에서 숫자를 다시 읽어 행의 칸 값과 견주는 별도 코드다(태그를 만드는 코드와 따로 쓴다).
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.catalog.tags import (
    KIND_TAG,
    LEVEL_TAG,
    MAX_TAGS,
    MIN_TAGS,
    area_text,
    crop_labels,
    crop_names,
    group_tags,
    pyeong,
    row_tags,
)
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = load_tables(ROOT / "data" / "tables", date(2026, 11, 14))
LABELS = crop_labels(BUNDLE.crops)
ROWS = {p.id: p for p in BUNDLE.programs}
GROUPS: dict[str, list] = {}
for _p in BUNDLE.programs:
    GROUPS.setdefault(_p.program_key.split("@")[0].split("#")[0], []).append(_p)
MODE = {"값이 내릴 때 지원": lambda p: p.trigger == "price_stab", "운송비 지원": lambda p: p.trigger == "logistics",
        "재해가 났을 때": lambda p: p.trigger == "disaster",
        "재해가 났을 때 신청": lambda p: p.trigger == "none" and p.apply_cycle == "사후신청" and p.event_type == "재해",
        "사고가 났을 때 신청": lambda p: p.trigger == "none" and p.apply_cycle == "사후신청" and p.event_type == "사고",
        "일이 생긴 뒤 신청": lambda p: p.trigger == "none" and p.apply_cycle == "사후신청" and p.event_type is None,
        "상시 신청": lambda p: p.trigger == "none" and p.apply_cycle == "상시",
        "해마다 한 번 신청": lambda p: p.trigger == "none" and p.apply_cycle == "연1회",
        "따로 신청하지 않아요": lambda p: p.trigger == "none" and p.apply_cycle == "자동"}


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def holds(text: str, p) -> bool:
    """태그 글이 그 행의 칸 값과 맞는가(글에서 숫자를 다시 읽어서 견준다)."""
    if text == "여성":
        return p.sex == "여"
    if m := re.fullmatch(r"(\d+)세 이상", text):
        return p.min_age == int(m[1]) and p.max_age is None
    if m := re.fullmatch(r"(\d+)세 이하", text):
        return p.max_age == int(m[1]) and p.min_age is None
    if m := re.fullmatch(r"(\d+)~(\d+)세", text):
        return (p.min_age, p.max_age) == (int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{4})~(\d{4})년생", text):
        return p.born_after == date(int(m[1]), 1, 1) and p.born_before == date(int(m[2]) + 1, 1, 1)
    if m := re.fullmatch(r"(\d{4})년 이후 출생", text):
        return p.born_after == date(int(m[1]), 1, 1) and p.born_before is None
    if m := re.fullmatch(r"(\d{4})년 이전 출생", text):
        return p.born_before == date(int(m[1]) + 1, 1, 1) and p.born_after is None
    if m := re.fullmatch(r"(제주시|서귀포시)( 농지| 주소지)?", text):
        basis = {None: None, " 농지": "농지소재지", " 주소지": "주소지"}[m[2]]
        return p.region_in == m[1] and p.region_basis == basis
    if text in ("읍·면 지역", "동 지역"):
        return p.area_type_in == ("읍면" if text.startswith("읍") else "동")
    if m := re.fullmatch(r"건강보험 (.+)", text):
        word = {"지역가입자": "지역", "직장가입자": "직장", "피부양자": "피부양자"}
        return tuple(word[w] for w in m[1].split("·")) == p.health_ins_in
    if text == "농협에 파는 농가":
        return p.needs_coop == "Y"
    if text == "자조금 가입":
        return p.needs_selfpay_fund == "Y"
    if text == "농협 출하나 자조금 가입":
        return p.needs_coop == "E" and p.needs_selfpay_fund == "E"
    if text == "미리 참여 신청":
        return p.needs_enrollment == "Y"
    if m := re.fullmatch(r"([\d.]+)ha 이상\(약 ([\d,]+)평\)", text):
        return p.min_ha == Decimal(m[1]) and p.max_ha is None and abs(_num(m[2]) - p.min_ha * 3025) <= 120
    if m := re.fullmatch(r"([\d.]+)ha 이하\(약 ([\d,]+)평\)", text):
        return p.max_ha == Decimal(m[1]) and p.min_ha is None and abs(_num(m[2]) - p.max_ha * 3025) <= 120
    if m := re.fullmatch(r"([\d.]+)~([\d.]+)ha", text):
        return (p.min_ha, p.max_ha) == (Decimal(m[1]), Decimal(m[2]))
    if m := re.fullmatch(r"농지 (\d+)년 이상 보유", text):
        return p.owns_land == "Y" and p.land_hold_years == int(m[1])
    if text == "농지 소유":
        return p.owns_land == "Y" and not p.land_hold_years
    if m := re.fullmatch(r"소유 농지 ([\d.]+)ha 이하", text):
        return p.max_owned_ha == Decimal(m[1])
    if m := re.fullmatch(r"농사 (\d+)년 이상", text):
        return p.min_farming_years == int(m[1])
    if m := re.fullmatch(r"제주 거주 (\d+)년 이상", text):
        return p.min_residence_years == int(m[1])
    if m := re.fullmatch(r"농외소득 ([\d,]+)만 원 이하", text):
        return p.income_test == "상한" and p.income_max_manwon == int(m[1].replace(",", ""))
    if text == "소득 심사":
        return p.income_test == "심사"
    if text == "농업경영체 등록":
        return p.needs_mgmt == "Y" and not p.min_mgmt_years
    if m := re.fullmatch(r"농업경영체 등록 (\d+)년 이상", text):
        return p.needs_mgmt == "Y" and p.min_mgmt_years == int(m[1])
    if m := re.fullmatch(r"(노지|시설) 재배", text):
        return p.facility == m[1]
    if m := re.fullmatch(r"(.+) 제외", text):
        return not p.crop_in and set(m[1].split("·")) <= {LABELS.get(c, c) for c in p.crop_not_in}
    if text in KIND_TAG.values():
        return KIND_TAG[p.kind] == text
    if text in LEVEL_TAG.values():
        return LEVEL_TAG[p.agency_level] == text
    if text in MODE:
        return MODE[text](p)
    raise AssertionError(f"검사 규칙이 없는 태그 글: {text}")


def crop_union(rows) -> list[str]:
    return crop_names([c for r in rows for c in r.crop_in], LABELS)


def is_crop_tag(text: str, rows) -> bool:
    union = crop_union(rows)
    return bool(union) and (text == "여러 작물" or text == "·".join(union))


def crop_ok(text: str, rows) -> bool:
    """작물 태그: 행들의 작물 이름 합집합과 같거나(3개까지), 그보다 많으면 '여러 작물'."""
    union = crop_union(rows)
    return (text == "여러 작물" and len(union) > 3) or (text == "·".join(union) and len(union) <= 3)


def tags_ok(rows, tags) -> None:
    assert MIN_TAGS <= len(tags) <= MAX_TAGS, tags
    assert len(set(tags)) == len(tags)
    assert all(0 < len(t) <= 20 for t in tags), tags
    for t in tags:
        if is_crop_tag(t, rows):
            assert crop_ok(t, rows)
        else:
            assert all(holds(t, r) for r in rows), (t, [r.id for r in rows])


@pytest.mark.parametrize("pid", sorted(ROWS))
def test_every_table_row_gets_three_or_four_tags_that_match_its_values(pid):
    tags_ok([ROWS[pid]], row_tags(ROWS[pid], LABELS))


@pytest.mark.parametrize("key", sorted(GROUPS))
def test_every_scheme_gets_three_or_four_tags_true_for_all_its_rows(key):
    tags_ok(GROUPS[key], group_tags(GROUPS[key], LABELS))


def test_forty_two_rows_in_twenty_eight_schemes():
    assert len(ROWS) == 42 and len(GROUPS) == 28


def test_area_tag_follows_the_spec_example():
    assert area_text(Decimal("0.5"), None) == "0.5ha 이상(약 1,500평)"
    assert area_text(None, Decimal("0.5")) == "0.5ha 이하(약 1,500평)"
    assert area_text(Decimal("0.033"), None) == "0.033ha 이상(약 100평)"
    assert area_text(Decimal("0.10"), Decimal("0.86")) == "0.1~0.86ha"
    assert pyeong(Decimal("0.5")) == 1500 and pyeong(Decimal("0.01")) == 100       # 최소 100평


def test_women_voucher_tags_use_birth_years_and_sex_first():
    assert row_tags(ROWS["JEJU-WOMEN-VOUCHER@2026"], LABELS)[:2] == ("여성", "1946~2005년생")


def test_tags_come_in_priority_order_crop_then_who_region_trade_area():
    assert row_tags(ROWS["JS-MANDARIN-BAG@2026"], LABELS) == ("만감류", "노지 재배", "제주시 농지", "0.033ha 이상(약 100평)")
    assert row_tags(ROWS["JEJU-PSTAB@2026-27#당근"], LABELS) == ("당근", "농협에 파는 농가", "자조금 가입", "미리 참여 신청")
    assert row_tags(ROWS["NAT-DIRECT-SMALL@2026"], LABELS)[0] == "0.1~0.86ha"


def test_scheme_with_no_condition_is_filled_with_kind_mode_and_level():
    assert row_tags(ROWS["NAT-DISASTER-RECOVERY@2026"], LABELS) == ("현금 지원", "재해가 났을 때", "나라 사업")
    assert row_tags(ROWS["KRC-FARMLAND-PENSION@2026"], LABELS) == ("60세 이상", "농지 2년 이상 보유", "농사 5년 이상")


def test_crops_merge_across_rows_and_citrus_collapses():
    assert crop_names(["감귤_노지", "감귤_만감", "당근"], LABELS) == ["감귤", "당근"]
    assert crop_names(["감귤_만감"], LABELS) == ["만감류"]
    assert group_tags(GROUPS["NAT-CROP-INS"], LABELS)[0] == "여러 작물"       # 감귤·당근·월동무·양배추·마늘·양파·브로콜리
    assert group_tags(GROUPS["JEJU-PSTAB"], LABELS)[0] == "당근·양배추·브로콜리"


def test_conditions_that_differ_between_rows_are_not_tags():
    taxi = group_tags(GROUPS["JEJU-HAPPY-TAXI"], LABELS)               # 읍면 65세 · 동 70세
    assert not any("65" in t or "70" in t or "읍" in t or "동 지역" in t for t in taxi)
    assert "자조금 가입" not in group_tags(GROUPS["NAT-INCOME-INS"], LABELS)      # 자조금은 일부 작물만
