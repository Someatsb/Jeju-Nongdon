"""단위(Task 4, U04): 평·㎡·ha, 금액 반올림 표, 금액 문구, 나이(age_basis).

금액 반올림은 이 파일의 `WON_ROUNDING` 표 한 곳에서만 바꾼다(round2-C-agent.md §1 "A안, 한 표에서만 변경").
"""
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

PYEONG_M2 = Decimal("3.3058")  # schema.json unit_rules.pyeong_m2
HA_M2 = 10_000                 # schema.json unit_rules.ha_m2

# (하한 원, 반올림 단위 원). 위에서부터 보고, 금액이 하한 이상인 첫 줄의 단위를 쓴다.
# 100만 원 이상도 만 원 단위다: round2-A-service.md §4-0("10만 원 이상 총액은 만 원 단위"), 골든 T1·T2
# ("연 약 259만~323만 원"), 계획서 test_round_won_bands(1,234,567 → 1,230,000). 계획서 Global Constraints
# 문구(1라운드 A: 100만 이상 10만 원 단위)와 다르다 — 바꾸려면 첫 줄 단위만 100_000으로.
WON_ROUNDING: tuple[tuple[int, int], ...] = (
    (1_000_000, 10_000),
    (100_000, 10_000),
    (0, 1_000),
)

AgeBasis = Literal["신청일", "연말", "1월1일"]  # schema.json supports.age_basis


# --- 면적 ---------------------------------------------------------------------------------

def py_to_m2(py: int) -> int:
    """평 → ㎡(1평 = 3.3058㎡, 반올림). 1,500평 → 4,959㎡."""
    if py < 0:
        raise ValueError("면적은 0 이상이어야 합니다.")
    return int((Decimal(py) * PYEONG_M2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def m2_to_ha(m2: int) -> Decimal:
    """㎡ → ha, 자르지 않은 Decimal. 4,959㎡ → 0.4959."""
    if m2 < 0:
        raise ValueError("면적은 0 이상이어야 합니다.")
    return Decimal(m2) / HA_M2


# --- 금액 ---------------------------------------------------------------------------------

def _to_decimal(won: Decimal | int) -> Decimal:
    if isinstance(won, bool) or not isinstance(won, (Decimal, int)):
        raise TypeError("금액은 Decimal 또는 int로 넘겨 주세요(float 금지).")
    value = Decimal(won)
    if value < 0:
        raise ValueError("금액은 0원 이상이어야 합니다.")
    return value


def _round_band(won: Decimal | int, rounding: str) -> int:
    value = _to_decimal(won)
    unit = next(u for floor, u in WON_ROUNDING if value >= floor)
    return int((value / unit).quantize(Decimal(1), rounding=rounding)) * unit


def round_won(won: Decimal | int) -> int:
    """금액 반올림(.5 올림): 10만 원 이상 만 원 단위, 그 아래 천 원 단위(표 `WON_ROUNDING`)."""
    return _round_band(won, ROUND_HALF_UP)


def _won_text(n: int) -> str:
    """원 단위 정수 → "1,213만", "16만 8천", "10만 6,650", "9천", "950"("원"은 붙이지 않는다)."""
    man, rest = divmod(n, 10_000)
    rest_text = f"{rest // 1_000}천" if rest and rest % 1_000 == 0 else f"{rest:,}"
    if not man:
        return rest_text
    return f"{man:,}만" + (f" {rest_text}" if rest else "")


def fmt_won(low: int | None, high: int | None) -> str:
    """금액 문구. 숫자는 `fact()` 매크로가 그리며, 이 함수는 그 안의 글자만 만든다.

    - 범위(low < high): "약 179만~256만 원" — 양끝 `round_won`. 반올림 뒤 같으면 "약 X 원".
    - 정액(low == high): "130만 원" — 반올림하지 않는다(round2-A §4-0 "정액·상한은 숫자 그대로").
      계산으로 나온 한 값은 부르는 쪽이 범위로 넘기거나 `round_won` 뒤에 넘긴다.
    - 상한만(low=None): "최대 약 430만 원" — 같은 단위로 내림. 실제 한도보다 크게 찍지 않는다(round2-K).
    - 하한만(high=None): "약 123만 원 이상" — 상한처럼 내림. "이상"이 실제 하한보다 크면 안 된다.
    - 둘 다 None: ValueError. 금액이 없으면 사유 문구("금액 공개 안 됨" 등)는 부르는 쪽이 쓴다.
    """
    if low is None and high is None:
        raise ValueError("금액이 없습니다. 사유 문구를 쓰세요.")
    if low is not None and high is not None and low > high:
        raise ValueError("금액 하한이 상한보다 큽니다.")
    if low is None:
        return f"최대 약 {_won_text(_round_band(high, ROUND_DOWN))} 원"
    if high is None:
        return f"약 {_won_text(_round_band(low, ROUND_DOWN))} 원 이상"
    if low == high:
        return f"{_won_text(int(_to_decimal(low)))} 원"
    lo, hi = round_won(low), round_won(high)
    if lo == hi:
        return f"약 {_won_text(lo)} 원"
    return f"약 {_won_text(lo)}~{_won_text(hi)} 원"


# --- 나이 ---------------------------------------------------------------------------------
# 태어난 해만 받는다(round2-I-quality.md §1-3). Y = as_of 연도 − birth_year. 지금 만 나이는 Y−1 또는 Y.

APPROX_BIRTH_YEARS = 2       # birth_year_approx("대략 몇 세"로 받음): 태어난 해를 ±2년으로 본다


def age_bounds(birth_year: int, basis: AgeBasis, as_of: date) -> tuple[int, int]:
    """기준일의 만 나이가 될 수 있는 (가장 적은, 가장 많은) 값.

    - 연말(농지연금): 그해 12월 31일엔 생일이 지났다 → (Y, Y).
    - 1월1일: 그해 1월 1일엔 거의 모두 생일 전(Y−1)이지만 1월 1일생은 그날 Y가 된다 → (Y−1, Y).
    - 신청일(은퇴직불·안전보험): as_of가 신청일이다. 생일을 모르니 (Y−1, Y).
      둘 다 범위 안이면 통과, 하나만 안이면 CHECK("생신 확인"), 둘 다 밖이면 해당 없음(Task 5).
    birth_year가 as_of 연도보다 뒤면 ValueError.
    """
    if birth_year > as_of.year:
        raise ValueError(f"태어난 해({birth_year})가 기준일 연도({as_of.year})보다 뒤입니다.")
    y = as_of.year - birth_year
    if basis == "연말":
        return (y, y)
    if basis in ("1월1일", "신청일"):
        return (max(y - 1, 0), y)
    raise ValueError(f"모르는 나이 기준입니다: {basis!r}")


def age_on(birth_year: int, basis: AgeBasis, as_of: date) -> int:
    """기준일의 만 나이 한 값 = `age_bounds`의 상한(생일이 지났다고 본 값). 경계 판정은 `age_bounds`로."""
    return age_bounds(birth_year, basis, as_of)[1]
