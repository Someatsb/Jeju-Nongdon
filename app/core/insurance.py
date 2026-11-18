"""보험 판정(Task 11, U11): 종이 E칸 "보험 — 가입 시기 안내". 권유가 아니라 안내이고, 다음 가입 창을 알려 드린다.

결과 id(InsuranceResult.product_id) = "<insurance.csv product_id>:<대상>"
  대상 = 작물 보험(crop_disaster·income_stab)은 밭의 crop_code(같은 작물 밭이 둘이면 두 번째부터 "#<밭 번호>"를 붙인다.
  예: "crop_disaster:당근", "crop_disaster:당근#2"), 안전보험(nh_safety)은 owner·spouse.
  예: "crop_disaster:마늘", "income_stab:감귤_만감", "nh_safety:spouse". 순서는 밭 순서대로 재해→수입안정,
  그다음 안전보험 owner→spouse. 표에 그 종류 행이 하나도 없으면 그 종류 결과는 내지 않는다.

작물 보험(밭마다, 재해보험·수입안정보험 둘 중 하나만 — 택1은 같은 밭 안에서만 본다):
- 그 작물을 담은 행이 없으면 NOT_COVERED(노지감귤 수입안정보험 등). 같은 작물이 두 행에 있으면 표 순서 첫 행.
- 둘 다 그 작물을 담고 둘 다 가입(ins_disaster·ins_income True)이면 둘 다 CHECK(ONE_OF_CHECK).
- 하나만 가입이면 그쪽 ENROLLED, 다른 쪽 NOT_ELIGIBLE("exclusive_with:<가입한 쪽>"). 대상 아님과 같이
  달력·할 일에 안 올라가고, 이유 코드로 "택1, 이미 다른 보험 가입"을 알린다(골든 B07).
- 둘 다 가입 전이면 각자 창으로 판정하고, 짝이 있으면 "exclusive_with:<짝>"를 붙인다.
안전보험(사람별): owner, 배우자가 있으면(spouse ≠ none) spouse. ins_safety에 있으면 ENROLLED.

가입 전 판정(_offer): 나이가 확실히 밖이면 NOT_ELIGIBLE. 경영체(needs_mgmt)를 못 채웠거나 모르거나 나이를
확인해야 하면 이유를 붙이고, 창이 아직 안 열렸으면 NEXT_WINDOW(그 전에 하시면 된다), 지금 열렸거나 상시면 CHECK.
다 맞으면 열린 창 안이면 OPEN_NOW, 아니면 NEXT_WINDOW.

나이는 supports 행(NAT-SAFETY-INS@2026: 15,87,신청일)대로 신청일 기준 만 나이다. 태어난 해만 받으므로
age_bounds(birth_year, "신청일", as_of)의 (Y−1, Y)를 쓴다(보험나이 같은 별도 규칙 없음). 대략 몇 세면 태어난 해
범위(±APPROX_BIRTH_YEARS) 양 끝을 합친다. 둘 다 15~87 안이면 가입 가능, 둘 다 밖이면 NOT_ELIGIBLE, 걸치면
CHECK(이유 "age:15~87", 생신 확인). 2026-11-13에 1939년생은 86~87세(OPEN_NOW), 1938년생은 87~88세(CHECK),
1937년생은 88~89세(NOT_ELIGIBLE). FarmProfile에 배우자 태어난 해는 없어서 배우자 나이는 늘 모름
(가입 전이면 CHECK "age_unknown").

출처 행이 hold(언론 근거만, 원문 대조 전)인 상품이면 안전보험 결과마다 이유 "source_hold"를 붙인다 —
check_insurance의 hold_source_ids(hold 행의 source_id 집합)로 받는다. 시트는 이 줄을 숫자 없이 찍는다.

창(windows, "MM-DD")은 해마다 같은 날로 보고 as_of 앞뒤 해로 옮긴다. 끝이 시작보다 앞이면 해를 넘는 창.
창이 비면 상시. next_window = 지금 열린 창(OPEN_NOW·가입 전 CHECK) 또는 as_of 뒤에 시작하는 첫 창
(NEXT_WINDOW, 가입한 상품의 갱신 창). NOT_COVERED·NOT_ELIGIBLE은 None.
revisit_month('다음에 오실 때' 달력 셋째 칸 = 작물 보험 달): 작물 보험 중 NOT_COVERED·NOT_ELIGIBLE이 아닌
결과에 그 next_window의 첫 달, 지금 열린 창은 이번 달. 안전보험은 그 칸에 안 올리므로 늘 None.
"""
from datetime import date
from typing import Literal

from app.core.models import CropPlot, FarmProfile, InsuranceResult
from app.core.tables_models import InsuranceProduct
from app.core.units import APPROX_BIRTH_YEARS, age_bounds

Kind = Literal["crop_disaster", "income_stab", "nh_safety"]
Result = Literal["PASS", "FAIL", "UNKNOWN"]
Window = tuple[date, date]

CROP_KINDS: tuple[Kind, Kind] = ("crop_disaster", "income_stab")   # 같은 밭에 둘 중 하나만
SAFETY: Kind = "nh_safety"
SOURCE_HOLD = "source_hold"
ONE_OF_CHECK = "둘 중 하나만 가능, 농협 확인"
NEEDS_MGMT = "needs_mgmt"
_MGMT: dict[str, Result] = {"over_2y": "PASS", "under_2y": "PASS", "none": "FAIL"}   # unknown → 모름


def check_insurance(profile: FarmProfile, products: tuple[InsuranceProduct, ...], as_of: date,
                    hold_source_ids: frozenset[str] = frozenset()) -> tuple[InsuranceResult, ...]:
    """농가의 보험 판정. 순수 함수(as_of는 인자). hold_source_ids = hold 행의 source_id(예: "supports:NAT-SAFETY-INS@2026")."""
    seen: dict[str, int] = {}
    out = []
    for plot in profile.crops:
        seen[plot.crop_code] = n = seen.get(plot.crop_code, 0) + 1
        target = plot.crop_code if n == 1 else f"{plot.crop_code}#{n}"
        out += [r for kind in CROP_KINDS
                if (r := _crop_result(profile, plot, kind, products, as_of, target)) is not None]
    safety = next((p for p in products if p.product_id == SAFETY), None)
    if safety is not None:
        people = ("owner",) if profile.spouse == "none" else ("owner", "spouse")
        hold = safety.source.source_id in hold_source_ids
        out += [_safety_result(profile, who, safety, as_of, hold) for who in people]
    return tuple(out)


# --- 작물 보험 ---------------------------------------------------------------------------------

def _covering(products: tuple[InsuranceProduct, ...], kind: Kind, crop: str) -> InsuranceProduct | None:
    return next((p for p in products if p.product_id == kind and (p.crop_keys is None or crop in p.crop_keys)), None)


def _crop_result(profile: FarmProfile, plot: CropPlot, kind: Kind, products: tuple[InsuranceProduct, ...],
                 as_of: date, target: str) -> InsuranceResult | None:
    rid = f"{kind}:{target}"
    row = _covering(products, kind, plot.crop_code)
    if row is None:
        first = next((p for p in products if p.product_id == kind), None)   # 대상 작물 목록이 있는 행이 근거
        return None if first is None else InsuranceResult(
            product_id=rid, status="NOT_COVERED", next_window=None, revisit_month=None, reasons=(),
            source=first.source)
    other: Kind = CROP_KINDS[1 - CROP_KINDS.index(kind)]
    paired = _covering(products, other, plot.crop_code) is not None
    mine = _enrolled_flag(plot, kind)
    theirs = paired and _enrolled_flag(plot, other)
    if mine and theirs:
        return _renewal(rid, row, as_of, "CHECK", (ONE_OF_CHECK,), on_calendar=True)
    if mine:
        return _renewal(rid, row, as_of, "ENROLLED", (), on_calendar=True)
    if theirs:
        return InsuranceResult(product_id=rid, status="NOT_ELIGIBLE", next_window=None, revisit_month=None,
                               reasons=(f"exclusive_with:{other}",), source=row.source)
    return _offer(rid, row, profile, _owner_birth_years(profile), as_of, on_calendar=True,
                  reasons=(f"exclusive_with:{other}",) if paired else ())


def _enrolled_flag(plot: CropPlot, kind: Kind) -> bool:
    return (plot.ins_disaster if kind == "crop_disaster" else plot.ins_income) is True


# --- 안전보험 ----------------------------------------------------------------------------------

def _safety_result(profile: FarmProfile, who: Literal["owner", "spouse"], row: InsuranceProduct,
                   as_of: date, hold: bool) -> InsuranceResult:
    rid = f"{SAFETY}:{who}"
    if who in profile.ins_safety:
        r = _renewal(rid, row, as_of, "ENROLLED", (), on_calendar=False)
    else:
        years = _owner_birth_years(profile) if who == "owner" else _spouse_birth_years(profile)
        r = _offer(rid, row, profile, years, as_of, on_calendar=False)
    return r.model_copy(update={"reasons": r.reasons + (SOURCE_HOLD,)}) if hold else r


# --- 판정 공통 ---------------------------------------------------------------------------------

def _renewal(rid: str, row: InsuranceProduct, as_of: date, status: Literal["ENROLLED", "CHECK"],
             reasons: tuple[str, ...], *, on_calendar: bool) -> InsuranceResult:
    """가입한 상품: 다음 창(갱신)을 알린다."""
    _, upcoming = _windows(row, as_of)
    month = upcoming[0].month if upcoming and on_calendar else None
    return InsuranceResult(product_id=rid, status=status, next_window=upcoming, revisit_month=month,
                           reasons=reasons, source=row.source)


def _offer(rid: str, row: InsuranceProduct, profile: FarmProfile, birth_years: tuple[int, int] | None,
           as_of: date, *, on_calendar: bool, reasons: tuple[str, ...] = ()) -> InsuranceResult:
    """가입 전 상품: 나이·경영체·창으로 OPEN_NOW / NEXT_WINDOW / CHECK / NOT_ELIGIBLE."""
    age = _age(birth_years, row, as_of)
    if age == "FAIL":
        return InsuranceResult(product_id=rid, status="NOT_ELIGIBLE", next_window=None, revisit_month=None,
                               reasons=reasons + (_age_reason(row, birth_years),), source=row.source)
    todo = [_age_reason(row, birth_years)] if age == "UNKNOWN" else []
    if row.needs_mgmt and _MGMT.get(profile.mgmt_status, "UNKNOWN") != "PASS":
        todo.append(NEEDS_MGMT)
    current, upcoming = _windows(row, as_of)
    if current is not None or upcoming is None:          # 지금 열림 또는 상시(창 없음)
        status, window, month = ("CHECK" if todo else "OPEN_NOW"), current, as_of.month
    else:                                                # 먼저 할 일이 있어도 창이 열리기 전에 하면 된다
        status, window, month = "NEXT_WINDOW", upcoming, upcoming[0].month
    return InsuranceResult(product_id=rid, status=status, next_window=window,
                           revisit_month=month if on_calendar else None, reasons=reasons + tuple(todo),
                           source=row.source)


# --- 나이(신청일 기준 만 나이) ----------------------------------------------------------------------------

def _owner_birth_years(profile: FarmProfile) -> tuple[int, int] | None:
    """경영주가 태어났을 수 있는 해(가장 이른, 가장 늦은). '대략 몇 세'면 ±APPROX_BIRTH_YEARS(매칭과 같게)."""
    if profile.birth_year is None:
        return None
    k = APPROX_BIRTH_YEARS if profile.birth_year_approx else 0
    return profile.birth_year - k, profile.birth_year + k


def _spouse_birth_years(profile: FarmProfile) -> tuple[int, int] | None:
    """배우자 태어난 해(선택 입력 spouse_birth_year). 없으면 모름."""
    y = profile.spouse_birth_year
    return None if y is None else (y, y)


def _age(birth_years: tuple[int, int] | None, row: InsuranceProduct, as_of: date) -> Result:
    if row.min_age is None and row.max_age is None:
        return "PASS"
    if birth_years is None:
        return "UNKNOWN"
    lo, hi = age_bounds(birth_years[1], "신청일", as_of)[0], age_bounds(birth_years[0], "신청일", as_of)[1]
    low, high = row.min_age if row.min_age is not None else 0, row.max_age if row.max_age is not None else hi
    if hi < low or lo > high:
        return "FAIL"
    return "PASS" if low <= lo and hi <= high else "UNKNOWN"


def _age_reason(row: InsuranceProduct, birth_years: tuple[int, int] | None) -> str:
    span = f"{'' if row.min_age is None else row.min_age}~{'' if row.max_age is None else row.max_age}"
    return f"age_unknown:{span}" if birth_years is None else f"age:{span}"


# --- 가입 창 -----------------------------------------------------------------------------------

def _on(year: int, month_day: str) -> date:
    m, d = int(month_day[:2]), int(month_day[3:])
    if (m, d) == (2, 29) and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        d = 28                                           # 평년에는 2월 28일
    return date(year, m, d)


def _windows(row: InsuranceProduct, as_of: date) -> tuple[Window | None, Window | None]:
    """(as_of가 든 창, as_of 뒤에 시작하는 첫 창). 창이 없으면(상시) (None, None)."""
    spans = sorted((_on(y, s), _on(y + (e < s), e))      # "MM-DD" 글자 비교: 끝이 앞이면 해를 넘는 창
                   for s, e in row.windows for y in (as_of.year - 1, as_of.year, as_of.year + 1))
    current = next((w for w in spans if w[0] <= as_of <= w[1]), None)
    upcoming = next((w for w in spans if w[0] > as_of), None)
    return current, upcoming
