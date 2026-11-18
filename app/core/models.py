"""코어 모델(Task 2, U02). 모두 pydantic v2, frozen=True, extra="forbid".

- 입력: CropPlot·Flags·FarmProfile·TypeQuery — research/dept/round2-C-agent.md §5-1 그대로.
  입원·질병 값은 어디에도 없다(사원 F).
- 표: Program — data/tables/schema.json의 supports 79컬럼(expected_notice_month 포함) + hold_reason.
  CSV 해석은 하지 않는다(Task 3 로더). 빈칸은 None, 목록 칸은 tuple로 받는다.
- 결과: SourceRef ~ FactSheet, Header, NarrativeInput(LLM에 넘기는 숫자 없는 보기).
"""
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class CoreModel(BaseModel):
    """코어 모델 공통 설정: 바꿀 수 없고, 모르는 키는 거부한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")


RowStatus = Literal["confirmed", "prior_year_reference", "hold"]

MAX_AREA_M2 = 300_000  # 30ha(=90,750평). 넘으면 평 칸에 ㎡·ha를 넣은 것으로 본다.


def _check_area(v: int) -> int:
    if v <= 0:
        raise ValueError("면적은 0보다 커야 합니다. 모르시면 비워 두세요.")
    if v > MAX_AREA_M2:
        raise ValueError("면적이 30ha(90,750평)를 넘습니다. 평으로 넣으셨나요?")
    return v


AreaM2 = Annotated[int, AfterValidator(_check_area)]  # ㎡, 1 ~ 300,000


# --- 입력 -----------------------------------------------------------------------------------

class CropPlot(CoreModel):
    crop_code: str = Field(min_length=1)       # crops.csv 코드. 감귤은 노지온주 / 만감류를 나눔
    area_m2: AreaM2 | None                     # 3. None=모름 → "면적 알려 주시면 계산"
    sales_channel: Literal["coop", "field_contract_done", "merchant_planned", "direct", "unknown"]  # 10(작물별)
    selfpay_fund: Literal["paid", "not_paid", "unknown", "na"]  # 11(na=자조금 품목 아님)
    ins_disaster: bool | None = None           # R2
    ins_income: bool | None = None             # R2


class Flags(CoreModel):
    disaster_damage: bool = False              # 12 최근 60일 재해 피해(입원·질병 값 없음)
    direct_payment_education: Literal["Y", "N", "NA"] = "NA"  # 14 올해 직불 교육(NA=직불 안 받음·해당없음)


class FarmProfile(CoreModel):
    visitor: Literal["self", "family_proxy", "village_head_proxy"]  # (0)
    owner_sex: Literal["F", "M"] | None        # (0)
    emd_code: str                              # 1. 종이 창구명에만. LLM·로그 금지(로그는 행정시)
    birth_year: int | None                     # 2
    birth_year_approx: bool = False
    crops: tuple[CropPlot, ...]                # 3·10·11·R2 (1~2개)
    total_area_m2: AreaM2 | None               # 4
    total_area_is_crop_sum: bool = False
    land_tenure: Literal["own_all", "own_part", "rent_all", "unknown"]  # 5
    land_held_2y: bool | None
    owned_over_4700py: bool | None             # 5a(조건부)
    mgmt_status: Literal["over_2y", "under_2y", "none", "unknown"]  # 6
    mgmt_last_reg_year: int | None             # 13(화면에서는 6번 바로 아래)
    spouse: Literal["registered", "cofarming_unregistered", "none"]  # 7
    farming_years: int | None = Field(ge=0, le=100)  # 8
    farming_10y_plus: bool = False
    residence_3y: bool = True
    health_ins: Literal["regional", "dependent", "employee", "unknown"]  # 9(납부 방식. 건강 상태 아님)
    flags: Flags                               # 12·14
    already_receiving: frozenset[str] = frozenset()  # R1 [받고 있음] program_key
    first_heard: frozenset[str] = frozenset()        # R1 [처음 들음](로그에는 개수만)
    ins_safety: frozenset[Literal["owner", "spouse"]] = frozenset()  # R2(사람별)
    spouse_birth_year: int | None = None             # 선택. 배우자 보험나이용(없으면 모름)
    spouse_sex: Literal["남", "여"] | None = None     # 선택
    enrollment_requested: Literal["예", "아니오", "모름"] = "모름"  # "참여 신청" 했는지(needs_enrollment 조건)

    @field_validator("birth_year", "spouse_birth_year")
    @classmethod
    def _birth_year(cls, v: int | None) -> int | None:
        if v is not None and not 1900 <= v <= 2010:
            raise ValueError("태어난 해는 1900~2010 사이 네 자리로 넣어 주세요.")
        return v

    @field_validator("crops")
    @classmethod
    def _crops(cls, v: tuple[CropPlot, ...]) -> tuple[CropPlot, ...]:
        if not 1 <= len(v) <= 2:
            raise ValueError("작물은 1~2개를 넣어 주세요.")
        return v

    @field_serializer("already_receiving", "first_heard", "ins_safety", when_used="json")
    def _sorted(self, v: frozenset[str]) -> list[str]:
        return sorted(v)  # 집합 순서가 실행마다 달라도 JSON(계산 지문)은 같게


class TypeQuery(CoreModel):                    # 유형별 종이
    crop_code: str
    area_band: Literal["le_0_5ha", "0_5_to_1ha", "gt_1ha"]
    age_band: Literal["lt60", "60_64", "65_74", "75_84", "ge85"]


# --- 표: supports.csv 한 행 ------------------------------------------------------------------

class Program(CoreModel):
    """supports.csv 한 행. 컬럼 이름·허용값·범위는 schema.json 그대로.

    식별 칸(id·program_key·edition·status)만 필수다. 나머지는 hold 행이 비워 둘 수 있어
    선택(None)으로 두고, 필수 여부는 표 검증기(Task 3)가 행 상태에 따라 따진다.
    정수 칸은 int, 소수 칸은 Decimal, 날짜 칸은 date, ';' 목록 칸은 tuple[str, ...].
    """

    # A 식별
    id: str
    program_key: str
    edition: str
    status: RowStatus
    applicant: Literal["개인", "농협경유", "법인·단체"] | None = None
    name: str | None = Field(default=None, max_length=30)
    agency: str | None = None
    agency_level: Literal["국가", "도", "제주시", "서귀포시", "농협", "공사", "공단"] | None = None
    kind: Literal["현금", "현물·자재", "사업비보조", "보험료지원", "연금", "서비스", "감면"] | None = None
    trigger: Literal["none", "price_stab", "logistics", "buyout", "disaster"] | None = None
    # B 기간
    valid_from: date | None = None
    valid_to: date | None = None
    apply_start: date | None = None
    apply_end: date | None = None
    apply_cycle: Literal["연1회", "상시", "사후신청", "자동"] | None = None
    apply_within_days: int | None = Field(default=None, ge=1, le=365)
    next_month: int | None = Field(default=None, ge=1, le=12)
    payout_timing: str | None = None
    # C 조건
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_age: int | None = Field(default=None, ge=0, le=120)
    age_basis: Literal["신청일", "연말", "1월1일"] | None = None
    sex: Literal["여"] | None = None
    min_residence_years: int | None = Field(default=None, ge=0, le=100)
    min_farming_years: int | None = Field(default=None, ge=0, le=100)
    needs_mgmt: Literal["Y"] | None = None
    min_mgmt_years: int | None = Field(default=None, ge=0, le=50)
    min_ha: Decimal | None = Field(default=None, ge=0, le=100)
    max_ha: Decimal | None = Field(default=None, ge=0, le=100)
    area_basis: Literal["경작", "해당작물", "소유", "인증"] | None = None
    max_owned_ha: Decimal | None = Field(default=None, ge=0, le=100)
    owns_land: Literal["Y"] | None = None
    land_hold_years: int | None = Field(default=None, ge=0, le=50)
    needs_coop: Literal["Y", "E"] | None = None
    needs_selfpay_fund: Literal["Y", "E"] | None = None
    needs_enrollment: Literal["Y"] | None = None
    needs_cert: Literal["친환경", "GAP", "친환경또는GAP"] | None = None
    income_test: Literal["없음", "상한", "심사"] | None = None
    income_max_manwon: int | None = Field(default=None, ge=0, le=100_000)
    crop_in: tuple[str, ...] = ()
    crop_not_in: tuple[str, ...] = ()
    facility: Literal["노지", "시설"] | None = None
    region_in: Literal["제주시", "서귀포시"] | None = None
    region_basis: Literal["주소지", "농지소재지"] | None = None
    excludes: tuple[str, ...] = ()
    manual_check: str | None = None
    # D 금액
    amount_type: Literal["정액", "면적비례", "kg당", "단위당", "보조율", "규칙", "없음"] | None = None
    amount_value: int | None = Field(default=None, ge=0, le=1_000_000_000)
    amount_min: int | None = Field(default=None, ge=0, le=1_000_000_000)
    amount_max: int | None = Field(default=None, ge=0, le=1_000_000_000)
    period: Literal["1회", "연", "월", "일"] | None = None
    calc_basis: Literal["경작면적", "해당작물면적", "소유면적", "출하량"] | None = None
    units_per_ha: Decimal | None = Field(default=None, ge=0, le=100_000)
    unit_name: str | None = Field(default=None, max_length=12)
    cap_units: int | None = Field(default=None, ge=0, le=1_000_000)
    rate_pct_min: Decimal | None = Field(default=None, ge=0, le=100)
    rate_pct_max: Decimal | None = Field(default=None, ge=0, le=100)
    cap_won: int | None = Field(default=None, ge=0, le=10_000_000_000)
    rule_ref: Literal["price_stab", "logistics"] | None = None
    amount_note: str | None = Field(default=None, max_length=60)
    # E 창구
    office: str | None = None
    phone: str | None = None
    documents: str | None = None
    # F 근거
    source_title: str | None = None
    source_url: str | None = None
    source_page: str | None = None
    source_grade: Literal["원문", "보도자료", "언론"] | None = None
    evidence: str | None = None
    verified_date: date | None = None
    verified_by: str | None = Field(default=None, max_length=20)
    notes: str | None = None
    # G 서비스
    renew_type: Literal["매년신청", "자동갱신", "상시", "사건별"] | None = None
    recognition_cue: str | None = Field(default=None, max_length=60)
    born_before: date | None = None
    event_type: Literal["재해", "사고"] | None = None
    # H 추가
    born_after: date | None = None
    area_type_in: Literal["읍면", "동"] | None = None
    health_ins_in: tuple[Literal["지역", "직장", "피부양자"], ...] = ()
    amount_2plus_each: int | None = Field(default=None, ge=0, le=100_000_000)
    # B 기간 칸(표에 있음, 레인 P가 추가) · 표 밖 칸(로더가 채움)
    expected_notice_month: int | None = Field(default=None, ge=1, le=12)  # 표에 있음. prior 배지 "○월 확인"
    hold_reason: str | None = None                                        # 로더가 채움. 예: "superseded"


# --- 결과 -----------------------------------------------------------------------------------

class SourceRef(CoreModel):
    source_id: str                             # "hub1361" / "notice:제주특별자치도 공고 제2026-2547호" ...
    url: str | None
    as_of: date | None                         # 데이터 기준일 또는 공고 확인일. 모르면 None(날짜를 지어내지 않음)


class CondCheck(CoreModel):
    field: str
    required: str
    actual: str
    result: Literal["PASS", "FAIL", "UNKNOWN"]
    prereq: bool                               # 경영체·계통출하·자조금·참여 신청처럼 "하면 풀리는" 조건


class ApplyWindow(CoreModel):
    always_open: bool
    open_now: bool
    next_start: date | None
    next_end: date | None

    @property
    def first_date(self) -> date | None:
        """창의 첫 날짜: 시작일, 없으면 마감일."""
        return self.next_start or self.next_end


class CalendarSlot(CoreModel):
    """'다음에 오실 때' 달력 한 칸(Task 4 `revisit_calendar`). 글자는 템플릿이 쓴다."""

    kind: Literal["integrated", "allowance_direct", "insurance"]  # 1월 통합공고 / 3월 수당·직불 / 작물 보험 달
    month: int | None = Field(ge=1, le=12)     # insurance 칸은 해당 보험이 없으면 None
    # 칸의 창 = 제도들의 합집합(가장 이른 시작 ~ 가장 늦은 마감). 시작일을
    # 모르는 제도가 있으면 둘 다 None → 템플릿은 programs의 제도별 날짜를 찍는다.
    start: date | None
    end: date | None
    programs: tuple[tuple[str, date | None, date], ...]  # (program_id, 다음 시작, 다음 마감), id 순
    row_status: RowStatus | None               # 작년 창을 옮긴 날짜가 하나라도 있으면 prior_year_reference(배지)
    label: str | None = None                   # 칸에 제도가 여럿일 때 제도별 달 설명("직불(3~5월) · 수당(3월)"). 없으면 칸 이름

    @property
    def program_ids(self) -> tuple[str, ...]:
        return tuple(pid for pid, _, _ in self.programs)


MatchStatus = Literal["LIKELY", "CHECK", "BLOCKED_PREREQ", "NOT_ELIGIBLE", "ALREADY", "EXCLUSIVE_OTHER", "OUT_OF_VALIDITY"]


class MatchResult(CoreModel):
    program_id: str
    program_key: str
    status: MatchStatus
    row_status: RowStatus
    conds: tuple[CondCheck, ...]
    missing_prereqs: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    manual_check: str | None                   # 직원 확인 항목(뒷면 "□ 확인할 것"). 묶음 판정에는 쓰지 않는다
    window: ApplyWindow
    source: SourceRef
    renew_annual: bool = False                 # ALREADY + 매년신청 → "작년처럼 다시 신청" 줄(Task 10)


class TriggerResult(CoreModel):
    rule_id: Literal["PRICE_STAB", "LOGISTICS", "ISOLATION_HISTORY"]
    status: Literal["MET", "NEAR", "MET_ESTIMATED", "NOT_MET", "NOT_APPLICABLE", "OUT_OF_SEASON", "NO_DATA", "STALE"]
    provisional: bool                          # 진행 중 반월, 거래일 3~4일 → "잠정(거래 n일)"
    metric: str
    observed: Decimal | None
    threshold: Decimal | None
    window: tuple[date, date] | None
    n_days_with_data: int = Field(ge=0)
    data_as_of: date | None
    staleness_days: int | None
    history_hits: tuple[int, int] | None       # ISOLATION_HISTORY: (7, 7) → "과거 7번 중 7번"
    sources: tuple[SourceRef, ...]
    note: str | None = None                    # 상태의 이유 한 마디: 기준가 값은 있으나 등급 미확인 → "기준가 미확인"
    crop_code: str | None = None               # 어느 작물의 판정인지(check_triggers가 채운다). 작물 둘인 농가의 줄이 제 작물 것을 고르는 데 쓴다


def _check_won_range(low: int | None, high: int | None) -> None:
    if (low is not None and low < 0) or (high is not None and high < 0):
        raise ValueError("금액은 0원 이상이어야 합니다.")
    if low is not None and high is not None and low > high:
        raise ValueError("금액 하한이 상한보다 큽니다.")


class Term(CoreModel):
    label: str
    value: Decimal
    unit: str
    source: SourceRef


class AmountLine(CoreModel):
    program_id: str
    kind: Literal["FIXED", "PER_AREA", "PER_KG_TRIGGER", "REFERENCE_LAST_SEASON", "DIFF_IF_SWITCH", "UNDISCLOSED"]
    low_won: int | None
    high_won: int | None
    terms: tuple[Term, ...]                    # 계산식 각 항(뒷면에 그대로)
    excluded: tuple[str, ...]                  # 포함 안 된 것 꼬리표("예측 아님" 등)
    conditional_on: tuple[str, ...]            # "계통출하 물량에 한함"
    pay_timing: str | None
    check_note: str | None                     # CHECK 줄: "확인할 조건 있음"
    period: Literal["월", "연", "1회", "일"] | None = None   # 표의 period: 월 20만 원과 연 20만 원을 구별한다
    already: bool = False                      # ALREADY 행(지키실 돈) 줄. 앞면 "받을 돈"은 건너뛴다
    crop_code: str | None = None               # 가격안정관리제 줄이 어느 작물의 것인지(작물별 줄). 그 밖의 줄은 None

    @model_validator(mode="after")
    def _won(self) -> "AmountLine":
        _check_won_range(self.low_won, self.high_won)
        return self

    def terms_by(self, label: str) -> Term:
        for t in self.terms:
            if t.label == label:
                return t
        raise KeyError(label)


class InsuranceResult(CoreModel):
    product_id: str
    status: Literal["ENROLLED", "OPEN_NOW", "NEXT_WINDOW", "NOT_COVERED", "NOT_ELIGIBLE", "CHECK"]
    next_window: tuple[date, date] | None
    revisit_month: int | None = Field(ge=1, le=12)  # 상담 시기와 가입 시기가 어긋날 때 재방문 달
    reasons: tuple[str, ...]
    source: SourceRef


ActionKind = Literal["URGENT", "DISASTER_REPORT", "PREREQ", "KEEP", "APPLY_NOW", "ASK_COOP",
                     "COOP_SWITCH", "APPLY_NEXT", "REVISIT"]


class Action(CoreModel):
    action_id: str
    kind: ActionKind
    office_id: str
    unlocks: tuple[str, ...]                   # PREREQ: what_if로 새로 LIKELY/CHECK가 되는 program_id
    unlock_low_won: int | None
    unlock_high_won: int | None
    due: date | None
    documents: tuple[str, ...]
    sort_key: tuple[Any, ...]                  # (kind 순위, due, -unlock 상한, action_id) — 결정적 정렬

    @model_validator(mode="after")
    def _amounts(self) -> "Action":
        if self.kind == "COOP_SWITCH" and (self.unlock_low_won is not None or self.unlock_high_won is not None):
            raise ValueError("계통 전환 행동(COOP_SWITCH)에는 금액을 붙이지 않습니다.")
        _check_won_range(self.unlock_low_won, self.unlock_high_won)
        return self


class Fact(CoreModel):
    fact_id: str
    label: str
    value: int | Decimal | date | str
    unit: str | None
    source: SourceRef
    as_of: date
    row_status: RowStatus | None               # 표 행에서 온 숫자면 그 행 상태(prior면 배지), 가격 등은 None
    expected_notice_month: int | None = Field(default=None, ge=1, le=12)  # prior 행의 supports 표 칸. 배지 "○월 확인"


class ReminderRequest(BaseModel):
    """문자 안내 요청. FarmProfile 밖에 둔다(저장·암호화는 Task 39)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phone: str = Field(pattern=r"^010-[0-9]{4}-[0-9]{4}$")
    consent: bool


class Header(CoreModel):
    price_as_of: date | None
    citrus_as_of: date | None
    tables_verified: date
    snapshot_built: date
    refresh_ok: bool | None
    demo_asof: bool                            # --asof 시연 기준일이면 "기준일 2026-11-13(시연)"


class FactSheet(CoreModel):
    profile: FarmProfile
    matches: tuple[MatchResult, ...]
    triggers: tuple[TriggerResult, ...]
    amounts: tuple[AmountLine, ...]
    insurance: tuple[InsuranceResult, ...]
    actions: tuple[Action, ...]
    facts: tuple[Fact, ...]
    header: Header
    as_of: date
    data_version: str
    fingerprint: str | None = None             # 계산 지문(pipeline.fingerprint). 지문 자신은 지문에 들어가지 않는다


# --- LLM에 넘기는 숫자 없는 보기(round2-C-agent.md §6-3) ----------------------------------------
# 제도 ID·정식 이름·상태·누락 조건·창 상태·창구 ID만. 숫자·나이·면적·읍면동 키는 없다.

_DIGIT = re.compile(r"[\d①-⑳]")  # \d는 전각 숫자 등 유니코드 숫자도 잡는다


class NarrativeItem(CoreModel):
    section: Literal["support", "insurance", "action", "empty"]
    fact_id: str                               # 인용 키, 예: "M:jeju_farmer_allowance"
    program_id: str                            # {P:id} 자리표시자 id(숫자 없는 별칭)
    official_name: str
    status: str                                # MatchResult.status / InsuranceResult.status / Action.kind 코드
    row_status: RowStatus | None
    missing: tuple[str, ...] = ()              # 누락 조건(조건 컬럼 이름)
    window: Literal["always_open", "open_now", "upcoming", "closed", "unknown"]
    office_id: str | None

    @field_validator("fact_id", "program_id", "official_name", "status", "missing", "office_id")
    @classmethod
    def _numberless(cls, v: str | tuple[str, ...] | None) -> str | tuple[str, ...] | None:
        for s in (v if isinstance(v, tuple) else (v,)):
            if s is not None and _DIGIT.search(s):
                raise ValueError("숫자 없는 보기에 숫자가 들어갔습니다.")
        return v


class NarrativeInput(CoreModel):
    empty_sheet: bool                          # 빈 종이(T1·T2)면 True
    items: tuple[NarrativeItem, ...]
    # 숫자 없는 별칭 → 실제 id(숫자가 들어 있을 수 있다: "JEJU-PSTAB@2025-26"). 에이전트 층이 자리표시자를 되돌릴 때만 쓰고,
    # LLM에 가는 JSON에는 싣지 않는다(exclude).
    aliases: dict[str, str] = Field(default_factory=dict, exclude=True)
