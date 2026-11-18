"""매칭 1(Task 5, U05): 표 행마다 조건 칸을 맞음·안 맞음·모름(PASS/FAIL/UNKNOWN)으로 보고 네 묶음으로 나눈다.

round1-B-data.md §2-3 판정 방식 그대로(eval 없이 고정 칸만):
- 조건 칸마다 CondCheck 하나. 입력이 없거나 "모름"이면 UNKNOWN(숨기지 않고 "확인").
- FAIL 0·UNKNOWN 0 → LIKELY / FAIL 0이고 UNKNOWN ≥ 1 또는 income_test=심사 → CHECK /
  FAIL이 전부 고칠 수 있는 칸(PREREQ_FIELDS) → BLOCKED_PREREQ / 그 밖의 FAIL이 하나라도 → NOT_ELIGIBLE.
  manual_check(직원 확인 항목)는 묶음에 넣지 않고 결과에 실어 뒷면 "□ 확인할 것"으로 찍는다(42행 모두 있음).
- valid_to < as_of이고 prior_year_reference가 아니면 OUT_OF_VALIDITY. prior 행은 상태를 그대로 두고
  row_status로 배지를 넘긴다. hold 행과 applicant=법인·단체 행은 결과에서 뺀다.
- event_type(그 일이 있을 때만): 재해 → 최근 60일 재해 피해가 있어야 PASS, 사고(영농도우미) → 늘 FAIL
  (종이는 모든 농가에 같은 고정 줄로 안내한다).
- 나이는 age_bounds(태어난 해만 알아 신청일 기준은 Y−1~Y), born_before(미만)·born_after(이상)는 태어난 해로.
- 작물 그룹(밭작물·월동채소·과수·감귤)은 crops.csv(`crops`)로 푼다. 표를 안 넘기면 그룹 칸은 UNKNOWN.
- 작물별 칸(계통출하·자조금)은 대상 작물 중 가장 잘 맞는 한 작물로, 해당작물 면적은 대상 작물 면적의 합으로 본다.
- 이미 받음(ALREADY)·택1(excludes → EXCLUSIVE_OTHER)은 match_rules.py(Task 10)가 행 판정 뒤에 건다.
- what_if(Task 10): 농가 칸 몇 개를 바꿔 다시 맞춘다(먼저 할 일이 무엇을 풀어 주는지 세는 데 쓴다).
"""
import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from app.core.calendar import apply_window
from app.core.match_rules import apply_already, apply_excludes
from app.core.models import CondCheck, CropPlot, FarmProfile, MatchResult, MatchStatus, Program, SourceRef
from app.core.tables_models import Crop
from app.core.units import APPROX_BIRTH_YEARS, HA_M2, AgeBasis, age_bounds  # noqa: F401  (APPROX_BIRTH_YEARS: 옛 import 경로 유지)

Result = Literal["PASS", "FAIL", "UNKNOWN"]

# 고칠 수 있는 조건(경영체 등록·계통출하·자조금·참여 신청·경영체 유지 연수): 이것만 FAIL이면 "먼저 할 일".
PREREQ_FIELDS = frozenset({"needs_mgmt", "needs_coop", "needs_selfpay_fund", "needs_enrollment", "min_mgmt_years"})

OWNED_QUESTION_M2 = 15_500   # 5a "소유 4,700평 초과" 질문 = 소농직불 소유 1.55ha 상한(round2-I §1-3)
_MANY = 10**9                # 범위의 위쪽을 모를 때

# 읍면 → 행정시. 동은 표가 없어 모름. emd_code(입력 1번 한 칸)를 주소지이자 농지 소재지로 본다.
_CITY_OF_EUPMYEON: Mapping[str, str] = {
    **dict.fromkeys(("한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "추자면", "우도면"), "제주시"),
    **dict.fromkeys(("대정읍", "남원읍", "성산읍", "안덕면", "표선면"), "서귀포시"),
}
_HEALTH_INS = {"regional": "지역", "employee": "직장", "dependent": "피부양자"}  # unknown → 모름
_MGMT = {"over_2y": "PASS", "under_2y": "PASS", "none": "FAIL"}                   # unknown → 모름
_MGMT_YEARS = {"over_2y": (2, _MANY), "under_2y": (0, 1), "none": (0, 0), "unknown": (0, _MANY)}
_LAND = {"own_all": "PASS", "own_part": "PASS", "rent_all": "FAIL"}               # unknown → 모름
_COOP = {"coop": "PASS", "unknown": "UNKNOWN"}                                    # 상인·직접 판매 → FAIL
_FUND = {"paid": "PASS", "not_paid": "FAIL"}                                      # unknown·na → 모름
_ENROLLMENT: Mapping[str, Result] = {"예": "PASS", "아니오": "FAIL", "모름": "UNKNOWN"}
_NOT: Mapping[Result, Result] = {"PASS": "FAIL", "FAIL": "PASS", "UNKNOWN": "UNKNOWN"}
_FACILITY_OF_CROP = {"감귤_노지": "노지", "시설과채": "시설"}                       # 그 밖의 작물은 모름
EXCLUDED_APPLICANTS = frozenset({"법인·단체"})                                    # 개인 농가 종이에 안 나감


def match_supports(profile: FarmProfile, programs: tuple[Program, ...], as_of: date, *,
                   crops: Iterable[Crop] = ()) -> tuple[MatchResult, ...]:
    """표 순서대로 hold·법인·단체가 아닌 행마다 MatchResult 하나. crops는 TableBundle.crops(작물 그룹 풀이용).
    행마다 판정한 뒤 행끼리 규칙(이미 받음 → 택1, match_rules.py)을 건다."""
    groups = {c.crop_code: frozenset(c.groups) for c in crops}
    results = tuple(_match(program, profile, as_of, groups) for program in programs
                    if program.status != "hold" and program.applicant not in EXCLUDED_APPLICANTS)
    results = apply_already(results, programs, profile.already_receiving)

    def area_of(program: Program) -> tuple[int, int]:  # 택1 비교 면적: 그 행의 area_basis로(조건 칸과 같은 방식)
        return _area_m2(program.area_basis or "경작", profile, _target_plots(program, profile.crops, groups))

    return apply_excludes(results, programs, area_of)


def what_if(profile: FarmProfile, programs: tuple[Program, ...], as_of: date, changes: Mapping[str, object], *,
            crops: Iterable[Crop] = ()) -> tuple[MatchResult, ...]:
    """가정 재매칭: changes만 바꾼 농가로 match_supports를 다시 돌린다(같은 crops로).

    키는 FarmProfile 필드명(`mgmt_status`, `spouse` ...), 작물 칸은 `crops[0].selfpay_fund`처럼 쓴다.
    모르는 키·없는 작물 번호는 KeyError, 허용 안 된 값은 pydantic ValidationError. profile은 그대로 둔다.
    """
    return match_supports(apply_changes(profile, changes), programs, as_of, crops=crops)


_CROP_KEY = re.compile(r"crops\[(\d+)\]\.(\w+)")


def apply_changes(profile: FarmProfile, changes: Mapping[str, object]) -> FarmProfile:
    """농가 칸 몇 개를 바꾼 새 FarmProfile(what_if와 같은 키 규칙·오류). 원래 농가는 그대로."""
    data = profile.model_dump()
    for key, value in changes.items():
        hit = _CROP_KEY.fullmatch(key)
        i, name = (int(hit[1]), hit[2]) if hit else (-1, "")
        if 0 <= i < len(data["crops"]) and name in CropPlot.model_fields:
            plots = list(data["crops"])
            plots[i] = {**dict(plots[i]), name: value}
            data["crops"] = plots
        elif key in FarmProfile.model_fields:
            data[key] = value
        else:
            raise KeyError(key)
    return FarmProfile.model_validate(data)


_changed = apply_changes  # 옛 이름(비공개) 별칭


def _match(program: Program, profile: FarmProfile, as_of: date, groups: Mapping[str, frozenset[str]]) -> MatchResult:
    conds = _conditions(program, profile, as_of, groups)
    return MatchResult(
        program_id=program.id,
        program_key=program.program_key,
        status=_status(program, conds, as_of),
        row_status=program.status,
        conds=conds,
        missing_prereqs=tuple(c.field for c in conds if c.prereq and c.result == "FAIL"),
        unknown_fields=tuple(c.field for c in conds if c.result == "UNKNOWN"),
        manual_check=program.manual_check,     # 묶음과 무관한 인쇄용 꼬리표
        window=apply_window(program, as_of),
        # hold 아닌 표 행은 verified_date가 필수(R19). 비어 있으면 None 그대로(확인일을 지어내지 않음).
        source=SourceRef(source_id=f"supports:{program.id}", url=program.source_url, as_of=program.verified_date),
        # renew_annual은 기본 False. ALREADY가 된 매년신청 행에만 match_rules.apply_already가 단다.
    )


def _status(program: Program, conds: tuple[CondCheck, ...], as_of: date) -> MatchStatus:
    if program.valid_to is not None and program.valid_to < as_of and program.status != "prior_year_reference":
        return "OUT_OF_VALIDITY"
    fails = [c for c in conds if c.result == "FAIL"]
    if fails:
        return "BLOCKED_PREREQ" if all(c.prereq for c in fails) else "NOT_ELIGIBLE"
    if program.income_test == "심사" or any(c.result == "UNKNOWN" for c in conds):
        return "CHECK"
    return "LIKELY"


# --- 조건 칸 ----------------------------------------------------------------------------------
# schema.json 컬럼 순서(C 조건 → G·H 추가)로 낸다. required는 표 칸 값, actual은 농가 입력(또는 그 범위).

def _conditions(program: Program, profile: FarmProfile, as_of: date,
                groups: Mapping[str, frozenset[str]]) -> tuple[CondCheck, ...]:
    pr, p = program, profile
    out: list[CondCheck] = []

    def add(field: str, required: object, actual: str, result: Result) -> None:
        out.append(CondCheck(field=field, required=str(required), actual=actual, result=result,
                             prereq=field in PREREQ_FIELDS))

    if pr.min_age is not None or pr.max_age is not None:
        basis: AgeBasis = pr.age_basis or "신청일"   # R04: 나이 칸이 있으면 기준 필수. 없으면 가장 넓게
        lo, hi = _age_range(p, basis, as_of)
        if pr.min_age is not None:
            add("min_age", pr.min_age, _span(lo, hi, "세"), _at_least(lo, hi, pr.min_age))
        if pr.max_age is not None:
            add("max_age", pr.max_age, _span(lo, hi, "세"), _at_most(lo, hi, pr.max_age))
    if pr.sex:
        add("sex", pr.sex, p.owner_sex or "모름",
            "UNKNOWN" if p.owner_sex is None else "PASS" if p.owner_sex == "F" else "FAIL")
    if pr.min_residence_years is not None:
        lo, hi = (3, _MANY) if p.residence_3y else (0, 2)
        add("min_residence_years", pr.min_residence_years, _span(lo, hi, "년"),
            _at_least(lo, hi, pr.min_residence_years))
    if pr.min_farming_years is not None:
        lo, hi = _farming_years(p)
        add("min_farming_years", pr.min_farming_years, _span(lo, hi, "년"), _at_least(lo, hi, pr.min_farming_years))
    if pr.needs_mgmt:
        add("needs_mgmt", pr.needs_mgmt, p.mgmt_status, _MGMT.get(p.mgmt_status, "UNKNOWN"))
    if pr.min_mgmt_years is not None:
        lo, hi = _MGMT_YEARS[p.mgmt_status]
        add("min_mgmt_years", pr.min_mgmt_years, p.mgmt_status, _at_least(lo, hi, pr.min_mgmt_years))

    plots = _target_plots(pr, p.crops, groups)   # 대상 작물이 없으면 () → 해당작물 면적 0㎡
    if pr.min_ha is not None or pr.max_ha is not None:
        lo, hi = _area_m2(pr.area_basis or "경작", p, plots)
        if pr.min_ha is not None:
            add("min_ha", pr.min_ha, _span(lo, hi, "㎡"), _at_least(lo, hi, pr.min_ha * HA_M2))
        if pr.max_ha is not None:
            add("max_ha", pr.max_ha, _span(lo, hi, "㎡"), _at_most(lo, hi, pr.max_ha * HA_M2))
    if pr.max_owned_ha is not None:
        lo, hi = _owned_m2(p)
        add("max_owned_ha", pr.max_owned_ha, _span(lo, hi, "㎡"), _at_most(lo, hi, pr.max_owned_ha * HA_M2))
    if pr.owns_land:
        add("owns_land", pr.owns_land, p.land_tenure, _LAND.get(p.land_tenure, "UNKNOWN"))
    if pr.land_hold_years is not None:
        lo, hi = _land_hold_years(p)
        add("land_hold_years", pr.land_hold_years, _span(lo, hi, "년"), _at_least(lo, hi, pr.land_hold_years))
    out.extend(_sales_checks(pr, plots or p.crops))  # 대상 작물이 없으면(crop_in FAIL) 칸 기록용으로 전부
    if pr.needs_enrollment:
        add("needs_enrollment", pr.needs_enrollment, p.enrollment_requested, _ENROLLMENT[p.enrollment_requested])
    if pr.needs_cert:
        add("needs_cert", pr.needs_cert, "입력 없음", "UNKNOWN")
    if pr.income_test in ("상한", "심사"):
        add("income_test", pr.income_max_manwon or pr.income_test, "입력 없음", "UNKNOWN")

    crop_codes = ";".join(pl.crop_code for pl in p.crops)
    in_list = [_member(pl.crop_code, pr.crop_in, groups) for pl in p.crops] if pr.crop_in else []
    if pr.crop_in:
        add("crop_in", ";".join(pr.crop_in), crop_codes, _any(in_list))
    if pr.crop_not_in:
        pool = [pl for pl, r in zip(p.crops, in_list) if r != "FAIL"] or list(p.crops)  # 대상 작물 중 제외 아닌 것
        add("crop_not_in", ";".join(pr.crop_not_in), crop_codes,
            _any(_NOT[_member(pl.crop_code, pr.crop_not_in, groups)] for pl in pool))
    if pr.facility:
        target = plots or p.crops
        add("facility", pr.facility, ";".join(_FACILITY_OF_CROP.get(pl.crop_code, "모름") for pl in target),
            _any(_facility(pl.crop_code, pr.facility) for pl in target))
    if pr.region_in:
        city = _CITY_OF_EUPMYEON.get(p.emd_code)
        add("region_in", pr.region_in, city or "모름", "UNKNOWN" if city is None else _is(city == pr.region_in))

    if pr.born_before:
        add("born_before", pr.born_before.isoformat(), _birth_text(p), _born_before(p, pr.born_before))
    if pr.event_type:
        if pr.event_type == "재해":
            add("event_type", pr.event_type, "재해 피해 있음" if p.flags.disaster_damage else "재해 피해 없음",
                _is(p.flags.disaster_damage))
        elif pr.event_type == "사고":
            add("event_type", pr.event_type, "묻지 않음(고정 줄로 안내)", "FAIL")
        else:
            add("event_type", pr.event_type, "입력 없음", "UNKNOWN")
    if pr.born_after:
        add("born_after", pr.born_after.isoformat(), _birth_text(p), _born_on_or_after(p, pr.born_after))
    if pr.area_type_in:
        kind = "읍면" if p.emd_code.endswith(("읍", "면")) else "동" if p.emd_code.endswith("동") else None
        add("area_type_in", pr.area_type_in, kind or "모름", "UNKNOWN" if kind is None else _is(kind == pr.area_type_in))
    if pr.health_ins_in:
        ins = _HEALTH_INS.get(p.health_ins)
        add("health_ins_in", ";".join(pr.health_ins_in), ins or "모름",
            "UNKNOWN" if ins is None else _is(ins in pr.health_ins_in))
    return tuple(out)


def _sales_checks(program: Program, plots: tuple[CropPlot, ...]) -> list[CondCheck]:
    """계통출하·자조금 칸. 대상 작물마다 보고 가장 잘 맞는 작물 하나를 낸다. E 짝은 둘 중 하나면 둘 다 PASS."""
    fields = [f for f in ("needs_coop", "needs_selfpay_fund") if getattr(program, f)]
    if not fields:
        return []
    either = program.needs_coop == "E" and program.needs_selfpay_fund == "E"

    def per_plot(pl: CropPlot) -> list[CondCheck]:
        own: dict[str, Result] = {"needs_coop": _COOP.get(pl.sales_channel, "FAIL"),
                                  "needs_selfpay_fund": _FUND.get(pl.selfpay_fund, "UNKNOWN")}
        actual = {"needs_coop": pl.sales_channel, "needs_selfpay_fund": pl.selfpay_fund}
        if either:
            own = dict.fromkeys(own, _any(own.values()))
        return [CondCheck(field=f, required=str(getattr(program, f)), actual=f"{pl.crop_code}:{actual[f]}",
                          result=own[f], prereq=f in PREREQ_FIELDS) for f in fields]

    return min((per_plot(pl) for pl in plots),
               key=lambda cs: (sum(c.result == "FAIL" for c in cs), sum(c.result == "UNKNOWN" for c in cs)))


# --- 작물 -------------------------------------------------------------------------------------

def _member(code: str, tokens: tuple[str, ...], groups: Mapping[str, frozenset[str]]) -> Result:
    """작물 코드가 목록(코드 또는 그룹)에 드는지. 표에 없는 작물이면 그룹을 풀 수 없어 모름."""
    if code in tokens:
        return "PASS"
    if code in groups:
        return _is(bool(groups[code] & set(tokens)))
    return "UNKNOWN"


def _facility(code: str, facility: str) -> Result:
    """재배 형태를 작물 코드에서 알 수 있으면(노지감귤 → 노지, 시설과채 → 시설) 비교, 아니면 모름."""
    known = _FACILITY_OF_CROP.get(code)
    return "UNKNOWN" if known is None else _is(known == facility)


def _target_plots(program: Program, crops: tuple[CropPlot, ...],
                  groups: Mapping[str, frozenset[str]]) -> tuple[CropPlot, ...]:
    """이 행의 대상 작물(crop_in에 들고 crop_not_in에 안 드는 것). 확실한 것, 없으면 모르는 것, 없으면 ()."""
    def fit(pl: CropPlot) -> Result:
        rs: list[Result] = []
        if program.crop_in:
            rs.append(_member(pl.crop_code, program.crop_in, groups))
        if program.crop_not_in:
            rs.append(_NOT[_member(pl.crop_code, program.crop_not_in, groups)])
        return _all(rs)

    fits = [(pl, fit(pl)) for pl in crops]
    return (tuple(pl for pl, r in fits if r == "PASS")
            or tuple(pl for pl, r in fits if r == "UNKNOWN"))


# --- 농가 입력 → 범위(가장 적은 값, 가장 많은 값) ------------------------------------------------

def _birth_years(p: FarmProfile) -> tuple[int, int] | None:
    if p.birth_year is None:
        return None
    k = APPROX_BIRTH_YEARS if p.birth_year_approx else 0
    return p.birth_year - k, p.birth_year + k


def _age_range(p: FarmProfile, basis: AgeBasis, as_of: date) -> tuple[int, int]:
    years = _birth_years(p)
    if years is None:
        return 0, _MANY
    return age_bounds(years[1], basis, as_of)[0], age_bounds(years[0], basis, as_of)[1]


def _birth_dates(p: FarmProfile) -> tuple[date, date] | None:
    """태어난 해만 아니까 생일은 그해 1월 1일~12월 31일 중 언제든."""
    years = _birth_years(p)
    return None if years is None else (date(years[0], 1, 1), date(years[1], 12, 31))


def _born_before(p: FarmProfile, d: date) -> Result:       # schema: 미만(그날 포함 안 함)
    span = _birth_dates(p)
    if span is None:
        return "UNKNOWN"
    return "PASS" if span[1] < d else "FAIL" if span[0] >= d else "UNKNOWN"


def _born_on_or_after(p: FarmProfile, d: date) -> Result:  # schema: 이상(그날 포함)
    span = _birth_dates(p)
    if span is None:
        return "UNKNOWN"
    return "PASS" if span[0] >= d else "FAIL" if span[1] < d else "UNKNOWN"


def _birth_text(p: FarmProfile) -> str:
    years = _birth_years(p)
    return "모름" if years is None else _span(years[0], years[1], "년생")


def _farming_years(p: FarmProfile) -> tuple[int, int]:
    if p.farming_years is not None:
        return p.farming_years, p.farming_years
    return (10, _MANY) if p.farming_10y_plus else (0, _MANY)


def _area_m2(basis: str, p: FarmProfile, plots: tuple[CropPlot, ...]) -> tuple[int, int]:
    if basis == "해당작물":
        known = [pl.area_m2 for pl in plots if pl.area_m2 is not None]
        return sum(known), (sum(known) if len(known) == len(plots) else _MANY)
    if basis == "소유":
        return _owned_m2(p)
    if basis == "인증":
        return 0, _MANY                          # 인증 면적은 입력에 없다
    if p.total_area_m2 is not None:              # 경작
        return p.total_area_m2, p.total_area_m2
    return sum(pl.area_m2 or 0 for pl in p.crops), _MANY


def _owned_m2(p: FarmProfile) -> tuple[int, int]:
    if p.land_tenure == "rent_all":
        return 0, 0
    if p.owned_over_4700py is not None:
        return (OWNED_QUESTION_M2 + 1, _MANY) if p.owned_over_4700py else (0, OWNED_QUESTION_M2)
    return 0, _MANY


def _land_hold_years(p: FarmProfile) -> tuple[int, int]:
    if p.land_tenure == "rent_all":
        return 0, 0
    if p.land_held_2y is not None:
        return (2, _MANY) if p.land_held_2y else (0, 1)
    return 0, _MANY


# --- 3값 계산 ---------------------------------------------------------------------------------

def _is(ok: bool) -> Result:
    return "PASS" if ok else "FAIL"


def _at_least(lo: int, hi: int, minimum: int | Decimal) -> Result:
    return "PASS" if lo >= minimum else "FAIL" if hi < minimum else "UNKNOWN"


def _at_most(lo: int, hi: int, maximum: int | Decimal) -> Result:
    return "PASS" if hi <= maximum else "FAIL" if lo > maximum else "UNKNOWN"


def _any(results: Iterable[Result]) -> Result:
    rs = list(results)
    return "PASS" if "PASS" in rs else "UNKNOWN" if "UNKNOWN" in rs else "FAIL"


def _all(results: Iterable[Result]) -> Result:
    rs = list(results)
    return "FAIL" if "FAIL" in rs else "UNKNOWN" if "UNKNOWN" in rs else "PASS"


def _span(lo: int, hi: int, unit: str) -> str:
    if lo == hi:
        return f"{lo}{unit}"
    if hi >= _MANY:
        return f"{lo}{unit} 이상" if lo else "모름"
    return f"{lo}~{hi}{unit}"
