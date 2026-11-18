"""유형별 종이(Task 22, U22): 작물 x 면적 구간 x 연령대 -> 사람 정보 없는 A4 한 장(이장·작목반장이 센터에서 고른다).

순수 함수다: 시계·파일을 읽지 않는다. 표 묶음·스냅샷·기준일은 인자로 받는다.
- 이름·번호·읍면동·태어난 해는 어디에도 없다(TypeQuery에도 없고 TypeSheet에도 없다).
- 대표 농가(representative_profile): 구간의 하한. 나이는 구간의 가장 적은 나이(lt60은 50세로 둔다 - 하한이 없는 구간이라
  농사짓는 대표 나이), 면적은 구간 바로 위쪽 경계(le_0_5ha는 0.1ha=경영체 하한 1,000㎡, 0_5_to_1ha는 5,001㎡,
  gt_1ha는 10,001㎡). 경영체·자조금·계통 출하·건강보험은 "모름", 직불 교육은 NA, 배우자는 등록 칸에 '모름'이 없어
  "none"(배우자 농사 없음)으로 둔다. 총면적은 작물 면적과 같다고 보고 total_area_is_crop_sum=True.
- open_money: 종이에 찍을 수 있는 지원금 줄 가운데 LIKELY·CHECK(꼬리표 print_tag 유지), 최대 MAX_OPEN_MONEY줄.
  순서: 마감이 열린 것(마감 가까운 순) -> 농협 경유 -> 직접 신청·정액 -> 보험. 못 실은 줄 수는 open_money_more.
- 모름 칸 7개(MOVES, 보고서 2-5의 순서)마다 what_if로 "예"일 때 새로 열리거나 LIKELY로 굳는 제도 수와 금액 하한 합을
  구해 (제도 수, 금액) 큰 순으로 정렬한다(같으면 MOVES 순서). 제도 수를 먼저 보는 까닭: 대표 농가는 대부분 CHECK라
  "새로 열리는" 금액 줄이 거의 없고, 경영체 등록은 보험 두 줄을 LIKELY로 굳히지만 금액 줄은 없다.
  self_check5는 그 앞 5개 문항, first_three는 "먼저 하실 일"이 되는 5가지(경영체·자조금·농협 출하·배우자·직불 교육)
  가운데 앞 3개(모자라면 next_actions로 채운다).
- example_1000py: 1,000평 밭으로 다시 계산한 정액·면적비례 금액과, 작년 계통출하 kg당 평균 사실 한 줄.
- basis_note: open_money(구간 하한 면적)와 example_1000py(1,000평)의 기준이 다름을 적는 글(템플릿이 찍는다).
"""
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.core.actions import CANDIDATE, INSURANCE_KEYS, MGMT_OFFICE_ID, _action, candidates, is_coop_route
from app.core.match import apply_changes, match_supports
from app.core.models import (Action, AmountLine, CoreModel, CropPlot, FarmProfile, Flags, MatchResult, Program,
                             TypeQuery)
from app.core.params_view import season_params
from app.core.pipeline import build_fact_sheet
from app.core.sheet import Line, _Ctx, _support_line
from app.core.sheet_rules import MGMT_PHONE, program_label
from app.core.snapshot_models import Snapshot
from app.core.tables_models import TableBundle
from app.core.units import fmt_won, py_to_m2

EXAMPLE_PY = 1000
MAX_OPEN_MONEY = 4
DATA_VERSION = "typesheet"
AREA_M2 = {"le_0_5ha": 1_000, "0_5_to_1ha": 5_001, "gt_1ha": 10_001}
AREA_TEXT = {"le_0_5ha": "0.5ha 이하", "0_5_to_1ha": "0.5~1ha", "gt_1ha": "1ha 넘는"}
AGE = {"lt60": 50, "60_64": 60, "65_74": 65, "75_84": 75, "ge85": 85}
EXAMPLE_KINDS = ("FIXED", "PER_AREA", "REFERENCE_LAST_SEASON")
PYEONG_M2 = Decimal("3.3058")


class CheckItem(CoreModel):
    question: str
    if_no: str          # 창구로 가실 답과 갈 곳(보고서 2-5의 "창구로 가실 답" 칸 그대로. 문항에 따라 "아니다" 또는 "그렇다")


class ExampleLine(CoreModel):
    label: str          # "<제도> - 1,000평이면 ○만 원" 또는 규칙형 사실 한 줄
    amount: AmountLine | None         # 규칙형 사실 한 줄은 금액 줄이 없다


class TypeSheet(CoreModel):
    query: TypeQuery
    as_of: date
    open_money: tuple[Line, ...]
    open_money_more: int              # 못 실은 줄 수
    first_three: tuple[Action, ...]
    example_1000py: tuple[ExampleLine, ...]
    self_check5: tuple[CheckItem, ...]
    basis_note: str


# 보고서 2-5의 7문항(순서 = 동점일 때 우선순위). 건보료 문항은 사장이 범위에 두기로 했다.
MEMO_CHECKS = (
    CheckItem(question="농업경영체 등록 확인서를 3년 안에 받았다", if_no=f"아니다·모른다 → {MGMT_PHONE}"),
    CheckItem(question="작목반 회비(자조금)를 낸다", if_no="아니다·모른다 → 농협"),
    CheckItem(question="올해 물량을 농협에 낸다(밭떼기 계약 안 함)", if_no="아니다 → 다음 시즌 조건 확인(농협)"),
    CheckItem(question="함께 농사짓는 배우자도 경영체에 올라 있다", if_no=f"아니다 → {MGMT_PHONE}"),
    CheckItem(question="건강보험료 고지서가 집으로 온다", if_no="그렇다 → 건보료 지원 확인(공단)"),
    CheckItem(question="올해 직불 교육을 들었다", if_no="아니다·모른다 → 읍면"),
    CheckItem(question="가진 땅을 다 합치면 4,700평 넘는다", if_no="그렇다 → 소농직불 확인"),
)
YEAR = "<as_of 연도>"
# MEMO_CHECKS와 같은 순서: 문항에 "예"(건보료·4,700평은 "그렇다")라고 가정할 때 바뀌는 칸.
MOVES: tuple[Mapping[str, object], ...] = (
    {"mgmt_status": "over_2y", "mgmt_last_reg_year": YEAR},
    {"crops[0].selfpay_fund": "paid"},
    {"crops[0].sales_channel": "coop"},
    {"spouse": "registered"},
    {"health_ins": "regional"},
    {"flags": {"disaster_damage": False, "direct_payment_education": "Y"}},
    {"owned_over_4700py": True},
)
# 먼저 하실 일 후보: MEMO_CHECKS 번호 -> (행동 종류, 행동 ref, 접수처)
PREREQ_MOVES: dict[int, tuple[str, str, str]] = {
    0: ("PREREQ", "mgmt_registration", MGMT_OFFICE_ID), 1: ("PREREQ", "fund", "coop"),
    2: ("COOP_SWITCH", "coop_fund", "coop"), 3: ("PREREQ", "spouse_registration", MGMT_OFFICE_ID),
    5: ("KEEP", "direct_pay_education", "emd_farmland_online"),
}


def representative_profile(q: TypeQuery, as_of: date, *, area_m2: int | None = None) -> FarmProfile:
    """구간 하한 농가. area_m2를 주면 면적만 그 값(1,000평 예시용)."""
    area = AREA_M2[q.area_band] if area_m2 is None else area_m2
    return FarmProfile(
        visitor="village_head_proxy", owner_sex=None, emd_code="", birth_year=as_of.year - AGE[q.age_band],
        crops=(CropPlot(crop_code=q.crop_code, area_m2=area, sales_channel="unknown", selfpay_fund="unknown"),),
        total_area_m2=area, total_area_is_crop_sum=True, land_tenure="unknown", land_held_2y=None, owned_over_4700py=None,
        mgmt_status="unknown", mgmt_last_reg_year=None, spouse="none", farming_years=None, health_ins="unknown",
        flags=Flags(direct_payment_education="NA"))


def tier_of(m: MatchResult, p: Program) -> int:
    """open_money 순서 칸: 0 마감이 열린 것 / 1 농협 경유 / 2 직접 신청·정액 / 3 보험."""
    if m.window.open_now and m.window.next_end is not None:
        return 0
    if p.program_key in INSURANCE_KEYS:
        return 3
    return 1 if is_coop_route(p) else 2


def build_typesheet(q: TypeQuery, bundle: TableBundle, snap: Snapshot, as_of: date) -> TypeSheet:
    profile = representative_profile(q, as_of)
    fs = build_fact_sheet(profile, bundle, snap, as_of, DATA_VERSION)
    by_id = {p.id: p for p in bundle.programs}
    cands = sorted(candidates(fs.matches, by_id), key=lambda m: (tier_of(m, by_id[m.program_id]),
                                                                  m.window.next_end or date.max, m.program_key))
    ctx = _Ctx(fs, bundle, as_of)
    lines = [l for m in cands if (l := _support_line(ctx, m)) is not None]
    scored = _score_moves(profile, fs.matches, bundle, snap, as_of)
    order = sorted(range(len(MOVES)), key=lambda i: (-scored[i][0], -scored[i][1], i))
    moves = [_move_action(i, scored[i]) for i in order if i in PREREQ_MOVES]
    first = (moves + [a for a in fs.actions if a.action_id not in {m.action_id for m in moves}])[:3]
    return TypeSheet(query=q, as_of=as_of, open_money=tuple(lines[:MAX_OPEN_MONEY]),
                     open_money_more=max(len(lines) - MAX_OPEN_MONEY, 0), first_three=tuple(first),
                     example_1000py=_example(q, bundle, snap, as_of, {m.program_id for m in cands}, by_id),
                     self_check5=tuple(MEMO_CHECKS[i] for i in order[:5]), basis_note=_basis_note(q))


def _score_moves(profile: FarmProfile, before: tuple[MatchResult, ...], bundle: TableBundle, snap: Snapshot, as_of: date,
                 ) -> list[tuple[int, int, tuple[str, ...]]]:
    """MOVES마다 (새로 열리거나 LIKELY로 굳는 제도 수, 그 제도의 금액 하한 합, 그 program_id들)."""
    old = {m.program_id: m.status for m in before}
    out = []
    for raw in MOVES:
        change = {k: (as_of.year if v == YEAR else v) for k, v in raw.items()}
        changed = apply_changes(profile, change)
        after = match_supports(changed, bundle.programs, as_of, crops=bundle.crops)
        gained = tuple(m.program_id for m in after if m.status in CANDIDATE and old[m.program_id] != m.status
                       and (old[m.program_id] not in CANDIDATE or m.status == "LIKELY"))
        keys = {m.program_id: m.program_key for m in after}
        money = 0
        if gained:
            fs = build_fact_sheet(changed, bundle, snap, as_of, DATA_VERSION)
            money = sum(a.low_won for a in fs.amounts if a.program_id in gained and a.kind in ("FIXED", "PER_AREA")
                        and a.low_won is not None and not a.already)
        out.append((len({keys[i] for i in gained}), money, gained))
    return out


def _move_action(i: int, score: tuple[int, int, tuple[str, ...]]) -> Action:
    kind, ref, office = PREREQ_MOVES[i]
    _, money, ids = score
    amount = money if money and kind == "PREREQ" else None     # 계통 전환 줄에는 금액을 적지 않는다
    return _action(kind, ref, office, unlocks=ids, low=amount, high=amount)  # type: ignore[arg-type]


def _basis_note(q: TypeQuery) -> str:
    py = int((Decimal(AREA_M2[q.area_band]) / PYEONG_M2).to_integral_value())
    return (f"지금 열린 돈의 금액은 {AREA_TEXT[q.area_band]} 구간의 가장 작은 밭(약 {py:,}평)·만 {AGE[q.age_band]}세 기준이고, "
            f"예시는 {EXAMPLE_PY:,}평 기준이에요. 실제 금액은 센터·농협 창구에서 어르신 조건으로 다시 계산해요.")


def _example(q: TypeQuery, bundle: TableBundle, snap: Snapshot, as_of: date, ids: set[str],
             by_id: Mapping[str, Program]) -> tuple[ExampleLine, ...]:
    profile = representative_profile(q, as_of, area_m2=py_to_m2(EXAMPLE_PY))
    fs = build_fact_sheet(profile, bundle, snap, as_of, DATA_VERSION)
    out = []
    for a in fs.amounts:
        if a.program_id not in ids or a.already or a.kind not in EXAMPLE_KINDS:
            continue
        name = program_label(by_id[a.program_id])
        if a.kind == "REFERENCE_LAST_SEASON":
            avg = next((t.value for t in a.terms if t.label == "작년 kg당 평균"), None)
            if avg is not None:
                out.append(ExampleLine(label=f"{name} - {EXAMPLE_PY:,}평 금액 대신: 작년 계통출하 농가 kg당 평균 {int(avg):,}원",
                                       amount=a))
        elif a.low_won is not None:
            out.append(ExampleLine(label=f"{name} - {EXAMPLE_PY:,}평이면 {fmt_won(a.low_won, a.high_won)}", amount=a))
    if not any(e.amount is not None and e.amount.kind == "REFERENCE_LAST_SEASON" for e in out):
        out.extend(_stab_facts(q, bundle, as_of, ids, by_id))
    return tuple(out)


def _stab_facts(q: TypeQuery, bundle: TableBundle, as_of: date, ids: set[str], by_id: Mapping[str, Program]) -> list[ExampleLine]:
    """규칙형(가격안정관리제)은 금액 대신 사실 한 줄: 작년 계통출하 농가 kg당 평균. 시세 조건과 무관하게 싣는다."""
    params = season_params(bundle, q.crop_code, as_of)
    if params is None or params.stab_paid_avg is None:
        return []
    return [ExampleLine(label=f"{program_label(by_id[i])} - {EXAMPLE_PY:,}평 금액 대신: 작년 계통출하 농가 kg당 평균 "
                              f"{int(params.stab_paid_avg):,}원", amount=None)
            for i in sorted(ids) if by_id[i].rule_ref == "price_stab" and q.crop_code in i]
