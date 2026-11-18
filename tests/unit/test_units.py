"""Task 4(U04) 단위: 평·㎡·ha, 금액 반올림 표, 금액 문구, 나이(age_basis)."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.units import HA_M2, PYEONG_M2, age_bounds, age_on, fmt_won, m2_to_ha, py_to_m2, round_won

AS_OF = date(2026, 11, 13)


# --- 계획서 Step 1(그대로) ---

def test_round_won_bands(): assert round_won(Decimal("1234567")) == 1230000 and round_won(Decimal("456789")) == 460000 and round_won(Decimal("45678")) == 46000


def test_fmt_won_range():
    # 계획서 문구는 "약 180만~260만 원"(1라운드 H안: 범위는 10만 원 단위)이었다.
    # test_round_won_bands(1,234,567 → 123만)와 골든 T1·T2("연 약 259만~323만 원", "260만~325만")는
    # 100만 원 이상도 만 원 단위라서 둘을 함께 만족하는 규칙이 없다. 골든·2라운드 A안을 따른다(보고서).
    assert fmt_won(1_790_000, 2_560_000) == "약 179만~256만 원"


# --- 반올림 표 경계 ---

@pytest.mark.parametrize("won, expected", [
    (0, 0), (499, 0), (500, 1_000),                    # 10만 미만: 천 원 단위, 반올림(.5 올림)
    (99_499, 99_000), (99_500, 100_000),
    (100_000, 100_000), (104_999, 100_000), (105_000, 110_000),   # 10만~100만: 만 원 단위
    (999_999, 1_000_000), (1_004_999, 1_000_000), (1_005_000, 1_010_000),  # 100만 이상: 만 원 단위
    (12_134_567, 12_130_000),
])
def test_round_won_band_edges(won, expected):
    assert round_won(Decimal(won)) == expected
    assert round_won(won) == expected  # int도 받는다


def test_round_won_rejects_negative_and_float():
    with pytest.raises(ValueError): round_won(Decimal("-1"))
    with pytest.raises(TypeError): round_won(1234.5)


# --- 금액 문구 ---

def test_fmt_won_plan_examples():
    assert fmt_won(None, 4_300_000) == "최대 약 430만 원"
    assert fmt_won(1_300_000, 1_300_000) == "130만 원"


@pytest.mark.parametrize("low, high, text", [
    (233_815, 556_150, "약 23만~56만 원"),          # 골든 P1 "약 23만~56만 원 더"
    (2_587_550, 3_232_155, "약 259만~323만 원"),     # 골든 T1 "연 약 259만~323만 원"
    (2_600_000, 3_250_000, "약 260만~325만 원"),     # 골든 T2 "연 약 260만~325만 원"
    (94_000, 150_000, "약 9만 4천~15만 원"),
    (12_130_000, 12_130_400, "약 1,213만 원"),       # 반올림 뒤 같아지면 한 값
])
def test_fmt_won_golden_ranges(low, high, text):
    assert fmt_won(low, high) == text


def test_fmt_won_fixed_is_exact_and_cap_never_rounds_up():
    # round2-A §4-0 "정액·상한은 숫자 그대로", round2-K: 상한을 올려 찍으면 실제 한도보다 커진다
    assert fmt_won(168_000, 168_000) == "16만 8천 원"
    assert fmt_won(106_650, 106_650) == "10만 6,650 원"
    assert fmt_won(None, 168_000) == "최대 약 16만 원"
    assert fmt_won(None, 106_650) == "최대 약 10만 원"
    assert fmt_won(None, 46_500) == "최대 약 4만 6천 원"


def test_fmt_won_lower_bound_only():
    assert fmt_won(1_234_567, None) == "약 123만 원 이상"


def test_fmt_won_lower_bound_rounds_down():   # "이상"이 실제 하한보다 크면 안 된다(상한의 내림과 같은 이유)
    assert fmt_won(1_235_000, None) == "약 123만 원 이상"
    assert fmt_won(46_500, None) == "약 4만 6천 원 이상"


def test_fmt_won_rejects_nothing_or_inverted():
    with pytest.raises(ValueError): fmt_won(None, None)   # 금액이 없으면 사유 문구는 부르는 쪽이 쓴다
    with pytest.raises(ValueError): fmt_won(300_000, 200_000)


# --- 면적 ---

@pytest.mark.parametrize("py, m2", [(1_500, 4_959), (3_000, 9_917), (1_800, 5_950), (900, 2_975),
                                    (3_600, 11_901), (2_100, 6_942), (0, 0), (1, 3)])
def test_py_to_m2_matches_persona_areas(py, m2):  # conftest 페르소나 area_m2와 같은 값
    assert py_to_m2(py) == m2


def test_py_to_m2_rejects_negative():
    with pytest.raises(ValueError): py_to_m2(-1)


def test_m2_to_ha_rejects_negative():
    with pytest.raises(ValueError): m2_to_ha(-1)


def test_m2_to_ha_is_exact_decimal():
    assert m2_to_ha(4_959) == Decimal("0.4959") and m2_to_ha(9_917) == Decimal("0.9917")
    assert m2_to_ha(10_000) == Decimal("1") and m2_to_ha(5_000) == Decimal("0.5")
    assert isinstance(m2_to_ha(4_959), Decimal)


def test_unit_constants_match_schema(tables_dir):
    rules = json.loads((tables_dir / "schema.json").read_text(encoding="utf-8"))["unit_rules"]
    assert PYEONG_M2 == Decimal(str(rules["pyeong_m2"])) and HA_M2 == rules["ha_m2"]


# --- 나이: 태어난 해만 받는다(round2-I §1-3). Y = as_of 연도 − birth_year ---

def test_age_on_by_basis():
    assert age_on(1961, "연말", AS_OF) == 65
    assert age_on(1961, "1월1일", AS_OF) == 65   # 상한(1월 1일생). 경계는 age_bounds로
    assert age_on(1961, "신청일", AS_OF) == 65   # 생일이 지났을 때 값(상한). 경계는 age_bounds로


def test_age_bounds_application_day_is_uncertain():
    assert age_bounds(1961, "신청일", AS_OF) == (64, 65)   # 은퇴직불 65세: 하나만 범위 안 → CHECK
    assert age_bounds(1941, "신청일", AS_OF) == (84, 85)   # 골든 B02: 84세 상한 → CHECK
    assert age_bounds(1961, "연말", AS_OF) == (65, 65)


def test_age_bounds_jan1_includes_jan1_birthdays():   # 1월 1일생은 그날 Y가 된다
    assert age_bounds(1961, "1월1일", AS_OF) == (64, 65)
    assert age_bounds(1961, "1월1일", date(2026, 1, 1)) == (64, 65)


def test_age_bounds_birth_year_edges():
    assert age_bounds(2026, "신청일", AS_OF) == (0, 0)     # 올해 태어남: 음수 나이 없음
    with pytest.raises(ValueError): age_bounds(2027, "연말", AS_OF)
    with pytest.raises(ValueError): age_on(2027, "신청일", AS_OF)


def test_age_on_rejects_unknown_basis():
    with pytest.raises(ValueError): age_on(1961, "apply", AS_OF)
