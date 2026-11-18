"""다음 행동(Task 15, U15): 판정 결과를 '먼저 하실 일' 순서의 Action 목록으로 만든다. 순수 함수(as_of는 인자).

종류 우선순위(KIND_RANK): URGENT > DISASTER_REPORT > PREREQ > KEEP > APPLY_NOW > ASK_COOP > COOP_SWITCH >
APPLY_NEXT > REVISIT. sort_key = (종류 순위, 마감·시작 날짜 또는 date.max, -(풀리는 금액 상한), action_id).

action_id = "<종류>:<대상>[:<값>]" — 종이 배치(sheet.py)가 이 id로 줄 글자를 고른다.
- URGENT:ins:<작물>        OPEN_NOW 작물 보험(재해·수입안정은 작물당 하나로 묶음)
- URGENT:<program_id>      30일 안에 마감하는 열린 창(올해 공고 확정 행만. 작년 날짜를 옮긴 창은 급하다고 하지 않음)
- DISASTER_REPORT:<id>     재해 피해 신고(글자는 재해복구비 행의 manual_check 그대로)
- PREREQ:mgmt_registration | PREREQ:enrollment | PREREQ:fund   BLOCKED_PREREQ 행을 먼저 할 일별로 묶음
- PREREQ:spouse_registration   함께 짓지만 미등록인 배우자를 경영체에 올리면 생기는 돈(행복이용권·2인 농민수당 차액)
- COOP_SWITCH:coop_fund    계통 출하·자조금이 막은 행(금액을 붙이지 않는다 — 설계 §12-A(2))
- KEEP:mgmt_renewal:<연도> | KEEP:direct_pay_education   끊기지 않게 할 일
- ASK_COOP:coop            계통 출하 여부를 몰라 CHECK가 된 농협 경유 제도
- ASK_COOP:fund            자조금 가입 여부를 몰라 CHECK가 된 제도
- APPLY_NOW:<key> | APPLY_NEXT:<key>   직접 신청(열림 / 다음 창), REVISIT:ins:<작물>   보험 다음 창

ALREADY·EXCLUSIVE_OTHER 행은 missing_prereqs가 낡았을 수 있어 상태로 먼저 거른다. 금액은 넘겨받은 AmountLine을
옮겨 더할 뿐 새로 계산하지 않는다(풀리는 금액 = 같은 program_key 하나당 한 줄, FIXED·PER_AREA만).
"""
from collections.abc import Iterable
from datetime import date

from app.core.amounts import calc_amounts, unlock_amounts
from app.core.calendar import days_until
from app.core.match import match_supports
from app.core.models import Action, ActionKind, AmountLine, FarmProfile, InsuranceResult, MatchResult, Program, TriggerResult
from app.core.tables_models import TableBundle

KIND_RANK: dict[str, int] = {k: i for i, k in enumerate(
    ("URGENT", "DISASTER_REPORT", "PREREQ", "KEEP", "APPLY_NOW", "ASK_COOP", "COOP_SWITCH", "APPLY_NEXT", "REVISIT"))}

URGENT_DAYS = 30
MGMT_RENEW_YEARS = 3                 # 경영체 정보는 3년마다 갱신
MGMT_OFFICE_ID = "naqs"              # 농관원(경영체 등록 창구). offices.csv에 없어 코드 상수로 둔다
INSURANCE_KEYS = frozenset({"NAT-CROP-INS", "NAT-INCOME-INS"})   # 보험은 InsuranceResult가 맡는다
# 땅을 내놓거나 담보로 잡는 제도: '놓친 돈 챙기기' 종이에 올리지 않는다(골든 P4 must_not_print).
UNPRINTED_KEYS = frozenset({"KRC-FARMLAND-PENSION", "NAT-RETIRE-DIRECT"})
MONEY_KINDS = frozenset({"현금", "현물·자재", "사업비보조", "보험료지원", "감면"})   # 연금·서비스는 줄로 안 낸다
CANDIDATE = frozenset({"LIKELY", "CHECK"})
FIXED_AMOUNT_KINDS = frozenset({"FIXED", "PER_AREA"})

_MGMT_FIELDS = frozenset({"needs_mgmt", "min_mgmt_years"})
_COOP_FIELDS = frozenset({"needs_coop", "needs_selfpay_fund"})
_FUND_FIELDS = frozenset({"needs_selfpay_fund"})
_ENROLL_FIELDS = frozenset({"needs_enrollment"})


def is_printable_support(program: Program) -> bool:
    """지원금 줄(C·D)로 낼 수 있는 행: 보험·땅을 내놓는 제도·연금·서비스는 제외."""
    return (program.program_key not in INSURANCE_KEYS and program.program_key not in UNPRINTED_KEYS
            and program.kind in MONEY_KINDS)


def is_coop_route(program: Program) -> bool:
    """농협 창구에서 신청하는 돈(종이 C): 농협경유 또는 가격안정·물류비 같은 트리거 제도."""
    return program.applicant == "농협경유" or (program.trigger or "none") != "none"


def candidates(matches: Iterable[MatchResult], by_id: dict[str, Program]) -> list[MatchResult]:
    """LIKELY·CHECK이고 줄로 낼 수 있는 행을 program_key당 하나(LIKELY 먼저, 표 순서)로."""
    best: dict[str, MatchResult] = {}
    for m in matches:
        if m.status in CANDIDATE and is_printable_support(by_id[m.program_id]):
            old = best.get(m.program_key)
            if old is None or (old.status == "CHECK" and m.status == "LIKELY"):
                best[m.program_key] = m
    return list(best.values())


def next_actions(profile: FarmProfile, bundle: TableBundle, matches: tuple[MatchResult, ...],
                 insurance: tuple[InsuranceResult, ...], amounts: tuple[AmountLine, ...],
                 triggers: tuple[TriggerResult, ...], as_of: date, limit: int = 5) -> tuple[Action, ...]:
    by_id = {p.id: p for p in bundle.programs}
    live = tuple(m for m in matches if m.status not in ("ALREADY", "EXCLUSIVE_OTHER"))
    out = [*_urgent(live, insurance, bundle, by_id, as_of), *_disaster(profile, bundle),
           *_prereq(profile, live, by_id, amounts, bundle, as_of), *_spouse(profile, matches, bundle, as_of),
           *_keep(profile, as_of),
           *_apply(live, by_id, bundle, as_of), *_revisit(insurance, bundle)]
    out.sort(key=lambda a: a.sort_key)
    return tuple(out[:limit])


# --- 만들기 ------------------------------------------------------------------------------------

def _action(kind: ActionKind, ref: str, office_id: str, *, unlocks: tuple[str, ...] = (), due: date | None = None,
            low: int | None = None, high: int | None = None, documents: tuple[str, ...] = ()) -> Action:
    action_id = f"{kind}:{ref}"
    return Action(action_id=action_id, kind=kind, office_id=office_id, unlocks=unlocks, unlock_low_won=low,
                  unlock_high_won=high, due=due, documents=documents,
                  sort_key=(KIND_RANK[kind], due or date.max, -(high or 0), action_id))


def _office_id(bundle: TableBundle, program: Program | None) -> str:
    office = bundle.office_named(program.office) if program else None
    return office.office_id if office else "emd_home"


def crop_of(product_id: str) -> str:
    """'crop_disaster:마늘' → '마늘'. 같은 작물 둘째 밭의 '#2' 꼬리는 뗀다(작물당 한 줄)."""
    return product_id.split(":", 1)[1].split("#", 1)[0]


def is_open_crop_insurance(r: InsuranceResult) -> bool:
    """지금 열린 창이 있는 작물 보험(재해·수입안정). 안전보험은 아니다. A(급한 것)가 맡는다."""
    return r.status == "OPEN_NOW" and r.next_window is not None and not r.product_id.startswith("nh_safety")


def _insurance_office(bundle: TableBundle, product_id: str) -> str:
    kind = product_id.split(":", 1)[0]
    return next((p.office_id for p in bundle.insurance if p.product_id == kind), "coop")


def _urgent(live: tuple[MatchResult, ...], insurance: tuple[InsuranceResult, ...], bundle: TableBundle,
            by_id: dict[str, Program], as_of: date) -> list[Action]:
    out: list[Action] = []
    open_now: dict[str, list[InsuranceResult]] = {}
    for r in insurance:
        if is_open_crop_insurance(r):
            open_now.setdefault(crop_of(r.product_id), []).append(r)
    for crop, results in open_now.items():
        due = min(r.next_window[1] for r in results if r.next_window)
        out.append(_action("URGENT", f"ins:{crop}", _insurance_office(bundle, results[0].product_id), due=due))
    for m in live:
        program = by_id[m.program_id]
        w = m.window
        if (m.status in CANDIDATE and m.row_status == "confirmed" and is_printable_support(program)
                and w.open_now and not w.always_open and w.next_end is not None
                and 0 <= days_until(w.next_end, as_of) <= URGENT_DAYS):
            out.append(_action("URGENT", m.program_id, _office_id(bundle, program), due=w.next_end))
    return out


def _disaster(profile: FarmProfile, bundle: TableBundle) -> list[Action]:
    if not profile.flags.disaster_damage:
        return []
    row = disaster_row(bundle)
    if row is None:
        return []
    return [_action("DISASTER_REPORT", row.id, _office_id(bundle, row),
                    documents=(row.documents,) if row.documents else ())]


def disaster_row(bundle: TableBundle) -> Program | None:
    """재해복구비 행: event_type=재해인 확정 행(글자는 이 행의 manual_check)."""
    return next((p for p in bundle.programs if p.event_type == "재해" and p.status != "hold"), None)


def _prereq_group(missing: tuple[str, ...]) -> str | None:
    fields = frozenset(missing)
    if not fields:
        return None
    if fields <= _MGMT_FIELDS:
        return "mgmt_registration"
    if fields <= _ENROLL_FIELDS:
        return "enrollment"
    if fields <= _FUND_FIELDS:
        return "fund"
    if fields <= _COOP_FIELDS:
        return "coop_fund"
    return None   # 여러 가지가 겹치면 하나만 해결해서는 안 풀린다


def _sum_amounts(unlock_ids: Iterable[str], by_id: dict[str, Program], amounts: tuple[AmountLine, ...]) -> tuple[int | None, int | None]:
    """program_key당 한 줄(변종은 첫 줄)의 FIXED·PER_AREA 금액을 옮겨 더한다. 없으면 (None, None)."""
    line_of = {a.program_id: a for a in amounts if a.kind in FIXED_AMOUNT_KINDS and a.low_won is not None and a.high_won is not None}
    seen: set[str] = set()
    low = high = 0
    for pid in unlock_ids:
        key = by_id[pid].program_key
        if pid in line_of and key not in seen:
            seen.add(key)
            low += line_of[pid].low_won or 0
            high += line_of[pid].high_won or 0
    return (low, high) if seen else (None, None)


def _group_change(profile: FarmProfile, group: str) -> dict[str, object]:
    """먼저 할 일 묶음을 마친 농가: unlock_amounts에 넘기는 바뀜."""
    if group == "mgmt_registration":
        return {"mgmt_status": "over_2y"}
    if group == "enrollment":
        return {"enrollment_requested": "예"}
    return {f"crops[{i}].selfpay_fund": "paid" for i in range(len(profile.crops))}      # fund


def _prereq(profile: FarmProfile, live: tuple[MatchResult, ...], by_id: dict[str, Program],
            amounts: tuple[AmountLine, ...], bundle: TableBundle, as_of: date) -> list[Action]:
    groups: dict[str, list[MatchResult]] = {}
    for m in live:
        if m.status == "BLOCKED_PREREQ" and is_printable_support(by_id[m.program_id]) and (g := _prereq_group(m.missing_prereqs)):
            groups.setdefault(g, []).append(m)
    out: list[Action] = []
    for group, rows in groups.items():
        ids = tuple(m.program_id for m in rows)
        dates = [d for m in rows if (d := m.window.first_date)]
        due = min(dates) if dates else None
        docs = tuple(dict.fromkeys(d for m in rows if (d := by_id[m.program_id].documents)))
        if group == "coop_fund":      # 금액을 붙이지 않는다(설계 §12-A(2)): 조건과 날짜만
            out.append(_action("COOP_SWITCH", "coop_fund", _office_id(bundle, by_id[ids[0]]), unlocks=ids, due=due))
            continue
        low, high = _sum_amounts(ids, by_id, amounts)
        if low is None:     # 막힌 행의 금액 줄은 없다(앞면 '받을 돈'에 안 나간다) → 먼저 할 일을 한 농가로 다시 맞춰 본다(Task 14 unlock_amounts)
            low, high = unlock_amounts(profile, bundle.programs, as_of, _group_change(profile, group), crops=bundle.crops)
        office = MGMT_OFFICE_ID if group == "mgmt_registration" else _office_id(bundle, by_id[ids[0]])
        out.append(_action("PREREQ", group, office, unlocks=ids, due=due, low=low, high=high, documents=docs))
    return out


SPOUSE_VOUCHER_KEY = "JEJU-WOMEN-VOUCHER"     # 배우자(여성) 본인 몫으로 새로 생기는 돈
SPOUSE_ALLOWANCE_KEY = "JEJU-FARMER-ALLOW"    # 2인 경영체는 1인당 금액(amount_2plus_each)


def _spouse(profile: FarmProfile, matches: tuple[MatchResult, ...], bundle: TableBundle, as_of: date) -> list[Action]:
    """배우자 경영체 등록: 배우자 본인 몫(행복이용권)과 2인 경영체가 되면 달라지는 농민수당 차액을 더한 먼저 할 일.
    배우자 성별(spouse_sex)을 입력받지 않았으면 추측하지 않는다: 제도 이름·금액이 없는 '확인' 행동(unlocks 빔)만 낸다.
    경영주 본인이 미등록이면 경영체 등록이 먼저라 이 행동은 내지 않는다."""
    if profile.spouse != "cofarming_unregistered" or profile.mgmt_status == "none":
        return []
    if profile.spouse_sex is None:
        return [_action("PREREQ", "spouse_registration", MGMT_OFFICE_ID)]
    by_key = {p.program_key: p for p in bundle.programs if p.status != "hold"}
    ids: list[str] = []
    low = 0
    voucher, allowance = by_key.get(SPOUSE_VOUCHER_KEY), by_key.get(SPOUSE_ALLOWANCE_KEY)
    if voucher is not None and profile.spouse_sex == "여":
        after = profile.model_copy(update={"owner_sex": "F", "birth_year": profile.spouse_birth_year,
                                           "birth_year_approx": False, "mgmt_status": "over_2y", "spouse": "none",
                                           "already_receiving": frozenset(), "ins_safety": frozenset()})
        for m in match_supports(after, (voucher,), as_of, crops=bundle.crops):
            if m.status in CANDIDATE:
                got = [a for a in calc_amounts(after, (m,), {}, bundle, as_of) if a.kind in FIXED_AMOUNT_KINDS and a.low_won]
                if got:
                    ids.append(voucher.id)
                    low += got[0].low_won
    own = next((m for m in matches if allowance is not None and m.program_id == allowance.id), None)
    if (allowance is not None and allowance.amount_2plus_each and allowance.amount_value and own is not None
            and own.status in CANDIDATE | {"ALREADY"}):
        gain = 2 * allowance.amount_2plus_each - allowance.amount_value
        if gain > 0:
            ids.append(allowance.id)
            low += gain
    if not ids:
        return []
    dates = [d for m in matches if m.program_id in ids and (d := m.window.first_date)]
    return [_action("PREREQ", "spouse_registration", MGMT_OFFICE_ID, unlocks=tuple(ids), due=min(dates) if dates else None,
                    low=low, high=low)]


def _keep(profile: FarmProfile, as_of: date) -> list[Action]:
    out: list[Action] = []
    if profile.mgmt_last_reg_year is not None:
        renew = profile.mgmt_last_reg_year + MGMT_RENEW_YEARS
        if renew <= as_of.year + 1:
            out.append(_action("KEEP", f"mgmt_renewal:{renew}", MGMT_OFFICE_ID))
    if profile.flags.direct_payment_education == "N":
        out.append(_action("KEEP", "direct_pay_education", "emd_farmland_online"))
    return out


def _apply(live: tuple[MatchResult, ...], by_id: dict[str, Program], bundle: TableBundle, as_of: date) -> list[Action]:
    cands = candidates(live, by_id)
    urgent_ids = {a.action_id.split(":", 1)[1] for a in _urgent(live, (), bundle, by_id, as_of)}
    out: list[Action] = []
    ask = tuple(m.program_id for m in cands if is_coop_route(by_id[m.program_id]) and "needs_coop" in m.unknown_fields)
    if ask:
        out.append(_action("ASK_COOP", "coop", "coop", unlocks=ask))
    ask_fund = tuple(m.program_id for m in cands if "needs_selfpay_fund" in m.unknown_fields)   # 자조금 가입 여부를 몰라 CHECK
    if ask_fund:
        out.append(_action("ASK_COOP", "fund", "coop", unlocks=ask_fund))
    for m in cands:
        if m.program_id in urgent_ids:
            continue
        program = by_id[m.program_id]
        office = _office_id(bundle, program)
        w = m.window
        if w.open_now:
            out.append(_action("APPLY_NOW", m.program_key, office, unlocks=(m.program_id,), due=w.next_end))
        else:
            out.append(_action("APPLY_NEXT", m.program_key, office, unlocks=(m.program_id,), due=m.window.first_date))
    return out


def _revisit(insurance: tuple[InsuranceResult, ...], bundle: TableBundle) -> list[Action]:
    by_crop: dict[str, date] = {}
    for r in insurance:
        if r.status in ("NEXT_WINDOW", "CHECK") and r.next_window and not r.product_id.startswith("nh_safety"):
            crop = crop_of(r.product_id)
            by_crop[crop] = min(r.next_window[0], by_crop.get(crop, date.max))
    return [_action("REVISIT", f"ins:{crop}", "coop", due=due) for crop, due in by_crop.items()]
