"""종이 배치 모델과 조립(Task 15, U15): FactSheet → 앞면 A~G / 빈 종이 / 뒷면. 템플릿(Task 17)은 이 모델만 그린다.

앞면 섹션(§7-2): A 급한 것 · B 먼저 하실 일 · C 농협 창구에서 신청하는 돈 · D 직접 신청하셔야 받는 돈 · E 보험 — 가입 시기 안내 ·
E2(=E′) 작년처럼 다시 신청 · F 가실 곳 · G 책임 표기. 합계는 없다(빈 종이의 '지키실 돈'만 예외, §12-A(2)).
- 줄: program_key당 하나(변종은 합침). 항목(A~E2) 7개 상한, A는 2개 상한. 넘친 줄은 Sheet.overflow와 뒷면으로.
- 줄 글자 수: sheet_rules.LIMIT. Line 모델이 어기면 만들어지지 않는다.
- 영농도우미·재해 미신고 안내는 항목 수에 안 들어가는 고정 줄(Front.fixed).
- A·B·C·D가 모두 비면(B의 KEEP 줄은 안 셈) EmptyFront.
"""
import re
from collections.abc import Iterator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import model_validator

from app.core.actions import (FIXED_AMOUNT_KINDS, MGMT_RENEW_YEARS, candidates, crop_of, disaster_row, is_coop_route,
                              is_open_crop_insurance, is_printable_support)
from app.core.amounts import target_crops
from app.core.calendar import days_until, revisit_calendar
from app.core.insurance import SOURCE_HOLD
from app.core.models import (Action, CalendarSlot, CoreModel, FactSheet, InsuranceResult, MatchResult, Program,
                             TriggerResult)
from app.core.sheet_back import (FINGERPRINT_SLOT, Excluded, LineConds, checks, excluded, hold_note, input_summary,
                                 line_conds, price_basis)
from app.core.sheet_rules import (BRING_TEXT, CHECK_TAG, DISASTER_ASK_TEXT, DISCLAIMER, EMPTY_TITLE, FARM_HELPER_TEXT, LIMIT,
                                  MGMT_PHONE, PREREQ_MONEY, TRIGGER_WORD, Pt, amount_text, first_segment, fit, join, md,
                                  notice_badge, program_label, window_text)
from app.core.tables_models import TableBundle
from app.core.units import fmt_won
from app.core.when_text import day_when, month_when, month_when_of, year_word_of

_OPENNESS = {s: i for i, s in enumerate(("MET", "MET_ESTIMATED", "NEAR", "NOT_MET", "STALE", "NO_DATA", "OUT_OF_SEASON"))}
MAX_ITEMS = 7
MAX_A = 2
SECTIONS = ("A", "B", "C", "D", "E", "E2", "F", "G")
ITEM_SECTIONS = ("A", "B", "C", "D", "E", "E2")
__all__ = ["LIMIT", "Sheet", "Front", "EmptyFront", "Back", "Line", "LineConds", "Excluded", "build_sheet", "flatten"]


class Line(CoreModel):
    section: str
    kind: str                       # URGENT / DISASTER_REPORT / PREREQ / KEEP / COOP_SWITCH / ASK_COOP / SUPPORT / INSURANCE / RENEW / OFFICE / FIXED / NOTICE
    title: str                      # 무엇(14pt)
    text: str                       # 핵심 한 줄(금액·마감). pt 크기의 글자 수 상한을 넘으면 만들어지지 않는다
    pt: Pt
    sub: str | None = None          # 작은 글씨 한 줄(14pt 상한). '확인할 조건 있음' 등
    detail: str | None = None       # 줄 수 제한 없는 원문(재해 신고 안내 전체 등). 템플릿이 작게 찍는다
    badge: str | None = None        # 작년 공고 기준 배지. 글(text)에 섞지 않는다
    program_key: str | None = None
    program_id: str | None = None   # 줄이 나온 표 행 id(같은 program_key가 작물별로 여럿이라 출처 표시는 이 id로 찾는다)
    due: date | None = None
    office: str | None = None       # F 칸 '가실 곳' 모으기용
    trigger_id: str | None = None   # 줄의 상태 글자가 "잠정(거래 n일)" 판정에서 왔으면 그 규칙 id(FactSheet.triggers의 rule_id)
    no_numbers: bool = False        # 출처가 보류(source_hold)인 보험 줄: 숫자 없이 찍는다
    print_tag: Literal["LIKELY", "CHECK"] | None = None   # manual_check 있는 지원금 줄의 인쇄 꼬리표

    @model_validator(mode="after")
    def _lengths(self) -> "Line":
        if len(self.text) > LIMIT[self.pt]:
            raise ValueError(f"{self.pt}pt는 {LIMIT[self.pt]}자까지: {self.text!r}")
        if (self.sub and len(self.sub) > LIMIT[14]) or len(self.title) > LIMIT[14]:
            raise ValueError(f"작은 글씨는 {LIMIT[14]}자까지: {self.title!r} {self.sub!r}")
        return self


class Front(CoreModel):
    sections: dict[str, tuple[Line, ...]]       # SECTIONS 키 모두
    fixed: tuple[Line, ...]                     # 영농도우미(항상)·재해 미신고 안내
    calendar3: tuple[CalendarSlot, CalendarSlot, CalendarSlot]

    @property
    def item_count(self) -> int:
        return sum(len(self.sections[s]) for s in ITEM_SECTIONS)


class EmptyFront(CoreModel):
    title: str
    money_text: str | None                      # "지키실 돈 연 약 ○만 원" (이 종이에서만 합계 허용)
    badge: str | None
    keep_low_won: int | None
    keep_high_won: int | None
    keep_actions: tuple[Line, ...]
    insurance_next: tuple[Line, ...]
    calendar3: tuple[CalendarSlot, CalendarSlot, CalendarSlot]
    fixed: tuple[Line, ...]
    footer: tuple[Line, ...]                    # G 책임 표기


class Back(CoreModel):
    input_summary: tuple[str, ...]
    line_conds: tuple[LineConds, ...]
    price_basis: tuple[str, ...]
    overflow: tuple[Line, ...]
    excluded: tuple[Excluded, ...]              # 뺀 것 상위 3
    checks: tuple[str, ...]                     # 창구 확인란 "□ …"
    fingerprint_slot: str
    office_names: dict[str, str] = {}           # 접수처 id → 표(offices.csv)의 한글 이름(뒷면 숫자 근거 표)
    office_phones: dict[str, str] = {}          # 접수처 id → 표의 전화(전화가 있는 접수처만). 가실 곳 카드의 전화
    hold_note: str | None = None                # "준비 중 n건": 원문 대조가 끝나지 않아 종이에 넣지 않은 제도 수(설계 §7-2)


class Sheet(CoreModel):
    front: Front | EmptyFront
    back: Back
    overflow: tuple[Line, ...]


def flatten(front: Front | EmptyFront) -> Iterator[Line]:
    """앞면의 모든 줄(고정 줄 포함)."""
    if isinstance(front, EmptyFront):
        yield from (*front.keep_actions, *front.insurance_next, *front.fixed, *front.footer)
        return
    for s in SECTIONS:
        yield from front.sections[s]
    yield from front.fixed


# --- 조립 --------------------------------------------------------------------------------------

class _Ctx:
    def __init__(self, fs: FactSheet, bundle: TableBundle, as_of: date) -> None:
        self.fs, self.bundle, self.as_of = fs, bundle, as_of
        self.by_id = {p.id: p for p in bundle.programs}
        self.amount_of = {a.program_id: a for a in fs.amounts if a.kind != "DIFF_IF_SWITCH"}      # 줄 금액(전환 차액은 따로)
        self.diff_of = {a.program_id: a for a in fs.amounts if a.kind == "DIFF_IF_SWITCH"}
        self.shown: dict[str, MatchResult] = {}     # 줄로 나간 program_key → 판정(뒷면 조건표)

    def program(self, m: MatchResult) -> Program:
        return self.by_id[m.program_id]

    def office_name(self, office_id: str) -> str | None:
        o = self.bundle.offices.get(office_id)
        return o.name if o else None

    def trigger(self, program: Program) -> TriggerResult | None:
        """줄을 움직이는 판정(driving trigger). 이 제도가 겨냥하는 작물의 판정만 보고, 작물이 둘이면 더 '열린' 쪽
        (MET > 추정 > 근처 > 아직 > 자료 문제 > 시즌 전, 같으면 먼저 입력한 작물)이다. 한 작물만 겨냥하면 그 작물의 판정이다."""
        rule = {"price_stab": "PRICE_STAB", "logistics": "LOGISTICS"}.get(program.trigger or "none")
        if rule is None:
            return None
        crops = target_crops(program, self.fs.profile, self.bundle.crops)
        mine = [t for t in self.fs.triggers if t.rule_id == rule and (t.crop_code is None or not crops or t.crop_code in crops)]
        applicable = [t for t in mine if t.status != "NOT_APPLICABLE"]
        return min(applicable, key=lambda t: _OPENNESS.get(t.status, 9)) if applicable else (mine[0] if mine else None)


def build_sheet(fs: FactSheet, bundle: TableBundle, as_of: date) -> Sheet:
    ctx = _Ctx(fs, bundle, as_of)
    lines = {"A": _section_a(ctx), "B": _section_b(ctx), "C": [], "D": [], "E": _section_e(ctx, ()), "E2": []}
    used = {l.program_key for l in lines["A"] if l.program_key}     # 줄은 program_key당 하나: A에 나온 제도는 C·D에서 뺀다
    lines["C"] = _coop_switch_lines(ctx, used)
    for m in candidates(fs.matches, ctx.by_id):
        if m.program_key in used:
            continue
        line = _support_line(ctx, m)
        if line is not None:
            used.add(m.program_key)
            lines["C" if is_coop_route(ctx.program(m)) else "D"].append(line)
    lines["D"] += _switch_only_lines(ctx, used)
    lines["E2"] = _section_e2(ctx, used)
    fixed, footer = _fixed(ctx), tuple(_footer())
    calendar3 = revisit_calendar(bundle.programs, fs.insurance, as_of)

    core = [l for s in ("A", "B", "C", "D") for l in lines[s] if l.kind != "KEEP"]
    if not core:
        front: Front | EmptyFront = _empty(ctx, lines["B"], fixed, footer, calendar3)
        return Sheet(front=front, back=_back(ctx, ()), overflow=())

    kept, overflow = _cap(lines)
    kept["F"] = _section_f(ctx, kept)
    kept["G"] = list(footer)
    front = Front(sections={s: tuple(kept[s]) for s in SECTIONS}, fixed=fixed, calendar3=calendar3)
    return Sheet(front=front, back=_back(ctx, tuple(overflow)), overflow=tuple(overflow))


def _cap(lines: dict[str, list[Line]]) -> tuple[dict[str, list[Line]], list[Line]]:
    """A는 2개, 전체 7개까지 앞에서부터 채우고 나머지는 넘침으로."""
    kept: dict[str, list[Line]] = {s: [] for s in SECTIONS}
    overflow: list[Line] = []
    total = 0
    for s in ITEM_SECTIONS:
        for line in lines[s]:
            if total < MAX_ITEMS and not (s == "A" and len(kept["A"]) >= MAX_A):
                kept[s].append(line)
                total += 1
            else:
                overflow.append(line)
    return kept, overflow


# --- A 급한 것 ---------------------------------------------------------------------------------

def _section_a(ctx: _Ctx) -> list[Line]:
    out: list[Line] = []
    for a in ctx.fs.actions:
        ref = a.action_id.split(":", 1)[1]
        if a.kind == "URGENT" and ref.startswith("ins:"):
            out.append(_urgent_insurance(ctx, ref[4:], a))
        elif a.kind == "URGENT":
            m = next(x for x in ctx.fs.matches if x.program_id == ref)
            p = ctx.program(m)
            out.append(_a_line("URGENT", program_label(p), _days_text(a.due, ctx.as_of), p.program_key, a.due,
                               office=p.office))
            ctx.shown[p.program_key] = m
        elif a.kind == "DISASTER_REPORT":
            out.append(_disaster_line(ctx, ref))
            out.extend(_claim_lines(ctx))
    return out


def _a_line(kind: str, title: str, text: str, key: str | None, due: date | None, *, sub: str | None = None,
            detail: str | None = None, office: str | None = None) -> Line:
    text, pt = fit(text, 22)
    return Line(section="A", kind=kind, title=title, text=text, pt=pt, sub=sub, detail=detail, program_key=key,
                due=due, office=office)


def _days_text(due: date | None, as_of: date) -> str:
    if due is None:
        return "곧 마감"
    n = days_until(due, as_of)
    return f"오늘 {md(due)}까지" if n == 0 else f"{md(due)}까지 · {n}일 남음"


def _urgent_insurance(ctx: _Ctx, crop: str, a: Action) -> Line:
    both = sum(1 for r in ctx.fs.insurance if is_open_crop_insurance(r) and crop_of(r.product_id) == crop) > 1
    sub = "재해보험과 수입안정보험 중 하나만 들 수 있어요" if both else None
    return _a_line("URGENT", f"{crop} 농작물보험", _days_text(a.due, ctx.as_of), None, a.due, sub=sub,
                   office=ctx.office_name(a.office_id))


def _claim_lines(ctx: _Ctx) -> list[Line]:
    """재해 피해가 있고 재해보험에 이미 들어 있으면: 신고와 따로 보험사고를 농협에 알린다(골든 B05-K2)."""
    crops = [crop_of(r.product_id) for r in ctx.fs.insurance if r.product_id.startswith("crop_disaster") and r.status == "ENROLLED"]
    if not crops:
        return []
    names = " · ".join(dict.fromkeys(_crop_label(ctx, c) for c in crops))
    return [_a_line("INSURANCE_CLAIM", "재해보험 사고 접수", "가입하신 농협에 사고를 알려 주세요", None, None, sub=names,
                    office=ctx.office_name("coop"))]


def _disaster_line(ctx: _Ctx, program_id: str) -> Line:
    row = ctx.by_id[program_id]
    first = first_segment(row.manual_check) or f"{program_label(row)}는 읍·면·동에 물어보세요"
    return _a_line("DISASTER_REPORT", "재해 피해 신고", first, row.program_key, None, detail=row.manual_check,
                   office=row.office)


# --- B 먼저 하실 일 ----------------------------------------------------------------------------

_PREREQ_TITLE = {"mgmt_registration": "농업경영체 등록 (농관원)", "enrollment": "참여 신청", "fund": "자조금 가입",
                 "spouse_registration": "배우자 경영체 등록 (농관원)"}


def _section_b(ctx: _Ctx) -> list[Line]:
    out: list[Line] = []
    for a in ctx.fs.actions:
        group = a.action_id.split(":", 1)[1]
        if a.kind == "PREREQ":
            out.append(_prereq_line(ctx, a, group))
        elif a.kind == "ASK_COOP":
            title, said = (("자조금 가입 확인", "가입했는지 농협에 물어보세요") if group == "fund"
                           else ("농협에 물어볼 것", "올해 농협으로 내시는지 알려 주세요"))
            text, pt = fit(said, 16)
            out.append(Line(section="B", kind="ASK_COOP", title=title, text=text, pt=pt,
                            sub=f"이것을 하시면 알아볼 수 있는 지원 {len(a.unlocks)}가지"))
        elif a.kind == "KEEP":
            out.append(_keep_line(group))
    return out


def _prereq_line(ctx: _Ctx, a: Action, group: str) -> Line:
    if group == "spouse_registration" and not a.unlocks:       # 배우자 성별을 모름: 제도 이름·금액 없이 확인만
        return Line(section="B", kind="PREREQ", title="배우자가 경영체에 등록했는지 확인", text="농산물품질관리원에 물어보세요", pt=16,
                    sub=join(MGMT_PHONE, CHECK_TAG), office=ctx.office_name(a.office_id) or "국립농산물품질관리원 제주지원(농관원)", print_tag="CHECK")
    if a.unlock_high_won is not None:
        text = f"{PREREQ_MONEY} 연 {fmt_won(a.unlock_low_won, a.unlock_high_won)}"
    else:
        text = f"{PREREQ_MONEY} 알아볼 수 있는 지원 {len(a.unlocks)}가지"
    text, pt = fit(text, 18)
    rows = [m for m in ctx.fs.matches if m.program_id in a.unlocks]
    check = any((x := ctx.amount_of.get(m.program_id)) and x.check_note for m in rows)
    paid = [m for m in rows if (x := ctx.amount_of.get(m.program_id)) and x.kind in FIXED_AMOUNT_KINDS] or rows
    months = [ctx.program(m).expected_notice_month for m in paid if m.row_status == "prior_year_reference"]
    prior = any(m.row_status == "prior_year_reference" for m in paid)   # 금액을 낸 제도들의 배지
    badge = notice_badge("prior_year_reference" if prior else None, min((x for x in months if x), default=None), ctx.as_of)
    for m in rows:
        ctx.shown.setdefault(m.program_key, m)
    sub = _fit_sub(MGMT_PHONE if group in ("mgmt_registration", "spouse_registration") else None, _enroll_note(ctx, rows, group),
                   CHECK_TAG if check else None)
    return Line(section="B", kind="PREREQ", title=_PREREQ_TITLE[group], text=text, pt=pt, sub=sub, badge=badge,
                detail=_spouse_detail(ctx, a) if group == "spouse_registration" else _mgmt_detail(ctx, rows) if group == "mgmt_registration" else None,
                due=a.due, office=ctx.office_name(a.office_id) or ("국립농산물품질관리원 제주지원(농관원)" if group == "mgmt_registration" else None))


def _mgmt_detail(ctx: _Ctx, rows: list[MatchResult]) -> str | None:
    """경영체 등록 줄 아래 한 줄: 등록하고 받을 직불의 신청 시기(표의 apply_start~apply_end 달)와 임차 땅의 증빙 준비."""
    wins = [m.window for m in rows if ctx.program(m).program_key.startswith("NAT-DIRECT") and m.window.next_start and m.window.next_end]
    if not wins:
        return None
    first, last = min(w.next_start for w in wins), max(w.next_end for w in wins)
    when = "내년" if first.year > ctx.as_of.year else "올해"
    months = f"{first.month}월" if first.month == last.month else f"{first.month}~{last.month}월"
    head = f"직불은 {when} {months}쯤 신청해요"
    if ctx.fs.profile.land_tenure != "rent_all":
        return head
    # 한 줄(13pt 40자)에 안 들어가면 줄여서: 임차 땅은 증빙 서류를 물어보세요
    return next(t for t in (f"{head} · 임차 땅은 증빙 서류를 물어보세요", f"{head} · 임차 땅은 서류를 물어보세요") if len(t) <= 40)


def _spouse_detail(ctx: _Ctx, a: Action) -> str | None:
    """배우자 등록으로 생기는 돈의 내역: 행복이용권 정액, 2인 경영체 농민수당 1인당 금액(표의 숫자 그대로)."""
    parts = []
    for pid in a.unlocks:
        p = ctx.by_id[pid]
        if p.program_key == "JEJU-WOMEN-VOUCHER" and p.amount_value:
            parts.append(f"{program_label(p)} {fmt_won(p.amount_value, p.amount_value).removeprefix('약 ')}")
        elif p.amount_2plus_each:
            parts.append(f"{program_label(p)} 1인당 {fmt_won(p.amount_2plus_each, p.amount_2plus_each).removeprefix('약 ')}(2인)")
    return " · ".join(parts) or None


def _enroll_note(ctx: _Ctx, rows: list[MatchResult], group: str) -> str | None:
    """이 먼저 할 일 말고도 '참여 신청'이 필요한 제도(가격안정관리제)가 묶여 있으면 그 사실과 신청 철('내년 9월쯤')."""
    row = next((m for m in rows if group != "enrollment" and "needs_enrollment" in (*m.missing_prereqs, *m.unknown_fields)), None)
    if row is None:
        return None
    first = row.window.first_date
    return f"{month_when_of(first, ctx.as_of)} 참여 신청도 해야 해요" if first else "참여 신청도 해야 해요"


def _fit_sub(*parts: str | None) -> str | None:
    """작은 글씨 한 줄(14pt 상한)에 들어가도록 뒤에서부터 덜 중요한 조각을 버린다."""
    kept = [p for p in parts if p]
    while kept and len(" · ".join(kept)) > LIMIT[14]:
        kept.pop()
    return " · ".join(kept) or None


_SWITCH_STEPS = (("needs_selfpay_fund", "자조금"), ("needs_coop", "농협 출하"), ("needs_enrollment", "참여 신청"))   # 짧게: 이름 + 조건이 한 줄에 들어가야 한다


def _last_season_fact(ctx: _Ctx, program_id: str) -> str | None:
    """'작년 kg당 153원': 지난 시즌 평균 지급액 항(AmountLine의 REFERENCE_LAST_SEASON)을 그대로. 총액은 쓰지 않는다."""
    for a in ctx.fs.amounts:
        if a.program_id == program_id and a.kind == "REFERENCE_LAST_SEASON":
            for t in a.terms:
                if t.label == "작년 kg당 평균":
                    return f"지난 시즌 kg당 {t.value:,.0f}원"
    return None


COOP_FILES_TEXT = "농협이 대신 신청해요 · 농협 출하 농가만"
COOP_FILES_SHORT = "농협이 대신 신청해요"           # 지난 시즌 사실과 한 줄(36자)에 안 들면 이쪽


def _when(ctx: _Ctx, p: Program, m: MatchResult) -> str:
    """신청 시기 글자. 농협이 신청 주체(applicant=농협경유)이거나 자동(apply_cycle=자동)이면 농가가 '상시 신청'할 수 없다."""
    if p.applicant == "농협경유" or p.apply_cycle == "자동":
        return COOP_FILES_TEXT
    return window_text(m.window, m.row_status, ctx.as_of)


_ONE_ROW_MM = 77.0     # 14pt 작은 글씨가 배지(약 86mm)와 한 줄에 나란히 앉는 폭(ui.render.r2_rows와 같은 어림)


def _mm14(text: str) -> float:
    """14pt 글자 폭 어림(mm): 한글 0.92em, 그 밖 0.5em, 1pt = 0.353mm(ui.render.text_mm과 같은 식)."""
    ko = sum("가" <= c <= "힣" for c in text)
    return 14 * 0.353 * (0.92 * ko + 0.5 * (len(text) - ko))


def _season_over(ctx: _Ctx, p: Program, fact: str | None) -> str | None:
    """올해 모집이 이미 끝난 연1회 제도(표의 apply_end가 기준일보다 앞): '올해 모집 끝(10월) · 다음 9월쯤 문의'.
    달은 표의 apply_end·next_month. 지난 시즌 사실(fact)이 있으면 한 줄(36자)에 들면 함께 적고, 없으면 배지와 한 줄에
    앉도록 짧은 쪽을 고른다. 아니면 None."""
    if p.apply_cycle != "연1회" or p.apply_end is None or p.apply_end >= ctx.as_of:
        return None
    end, nxt = f"올해 모집은 끝났어요({p.apply_end.month}월)", p.next_month
    if not nxt:
        return join(fact, end)
    ask = f"{month_when(nxt, ctx.as_of)} 물어보세요"
    opts = [join(fact, ask)] if fact else [join(end, ask), join("올해 모집은 끝났어요", ask), ask]
    return next((o for o in opts if len(o) <= LIMIT[14] and (fact or _mm14(o) <= _ONE_ROW_MM)), ask)


def _fit_when(fact: str | None, when: str) -> str | None:
    """지난 시즌 사실과 신청 시기 글을 한 줄(36자)에. 넘치면 농협 대신 신청 글은 짧은 쪽으로."""
    text = join(fact, when)
    if text and len(text) > LIMIT[14] and when == COOP_FILES_TEXT:
        text = join(fact, COOP_FILES_SHORT)
    return text


def _coop_switch_lines(ctx: _Ctx, used: set[str]) -> list[Line]:
    """C: 농협 출하·자조금이 막은 제도. 조건(missing_prereqs)과 작년 사실 한 줄만, 금액은 없다(§12-A(2))."""
    out: list[Line] = []
    for a in ctx.fs.actions:
        if a.kind != "COOP_SWITCH":
            continue
        for m in (x for pid in a.unlocks for x in ctx.fs.matches if x.program_id == pid):
            if m.program_key in used:
                continue
            p = ctx.program(m)
            todo = [(field, word) for field, word in _SWITCH_STEPS
                    if field in m.missing_prereqs or (field == "needs_enrollment" and field in m.unknown_fields)]
            # 표의 칸값이 E인 조건끼리는 '둘 중 하나'라 '또는', Y인 것은 모두 해야 해서 '+'
            either = [w for f, w in todo if getattr(p, f, None) == "E"]
            steps = [w for f, w in todo if getattr(p, f, None) != "E"] + ([" 또는 ".join(either)] if either else [])
            text, pt = fit(f"먼저: {' + '.join(steps)}" if steps else "농협 출하 조건을 확인하세요", 16)
            fact = _last_season_fact(ctx, m.program_id)
            when = _season_over(ctx, p, fact) or _fit_when(fact, _when(ctx, p, m))
            used.add(m.program_key)
            ctx.shown[m.program_key] = m
            out.append(Line(section="C", kind="COOP_SWITCH", title=program_label(p), text=text, pt=pt,
                            sub=when, program_id=m.program_id,
                            badge=notice_badge(m.row_status, p.expected_notice_month, ctx.as_of),
                            program_key=m.program_key, due=m.window.next_end, office=p.office))
    return out


def _keep_line(ref: str, *, yearly: bool = False) -> Line:
    if ref.startswith("mgmt_renewal:"):
        return Line(section="B", kind="KEEP", title="끊기지 않게 · 경영체 갱신", text=f"경영체 {ref.split(':')[1]}년 갱신", pt=16,
                    sub=MGMT_PHONE)
    text = "직불 교육은 해마다 들어 주세요" if yearly else "올해 직불 교육을 들어 주세요"
    return Line(section="B", kind="KEEP", title="끊기지 않게 · 직불 교육", text=text, pt=16)


# --- C·D 지원금 줄 -----------------------------------------------------------------------------

def _kg_facts(ctx: _Ctx, program_id: str, crop: str | None) -> dict[str, Decimal]:
    """가격안정관리제 줄의 kg당 사실 항: 'kg당 최대'·'하한가'(PER_KG_TRIGGER), '작년 kg당 평균'(REFERENCE_LAST_SEASON).
    crop은 줄을 움직이는 판정의 작물(TriggerResult.crop_code): 작물이 둘이어도 상태 글자와 같은 작물의 숫자를 쓴다."""
    out: dict[str, Decimal] = {}
    for a in ctx.fs.amounts:
        if a.program_id == program_id and a.kind in ("PER_KG_TRIGGER", "REFERENCE_LAST_SEASON") and (crop is None or a.crop_code in (None, crop)):
            for t in a.terms:
                if t.label in ("kg당 최대", "하한가", "작년 kg당 평균"):
                    out.setdefault(t.label, t.value)
    return out


def _won_text(v: Decimal) -> str:
    return f"{v.quantize(Decimal(1), rounding=ROUND_HALF_UP):,}원"


def _support_line(ctx: _Ctx, m: MatchResult) -> Line | None:
    p = ctx.program(m)
    a = ctx.amount_of.get(m.program_id)
    amt = amount_text(a)
    tag = CHECK_TAG if (m.status == "CHECK" or (a and a.check_note)) else None
    when = _when(ctx, p, m)
    state = None
    detail = None
    trig = ctx.trigger(p) if is_coop_route(p) else None
    if is_coop_route(p) and trig is not None:
        if trig.status == "NOT_APPLICABLE":
            return None
        state = TRIGGER_WORD.get(trig.status, "확인") + ("(잠정)" if trig.provisional else "")
        if trig.status == "NO_DATA" and trig.note:          # 자료가 오래된 게 아니라 기준가가 없다(브로콜리): 농협 확인으로
            state = f"{trig.note} · 농협에 물어보세요"
        if trig.status == "OUT_OF_SEASON" and trig.window:
            state += f" · {trig.window[0].month}월부터"      # 언제부터 판정하는지(시즌 시작 달)
        when = None
        kg = _kg_facts(ctx, m.program_id, trig.crop_code) if trig.status in ("MET", "NEAR") else {}
        if "kg당 최대" in kg:                                # 열림·근처: 오늘 kg당 최대와 하한가, 작년 사실 한 줄(총액 아님)
            amt = f"kg당 최대 {_won_text(kg['kg당 최대'])}"
            detail = join(f"작년 kg당 {_won_text(kg['작년 kg당 평균'])}" if "작년 kg당 평균" in kg else None, "예측 아님")
    text = join(state, amt) if amt else join(state, when)
    text, pt = fit(text or when, 18 if amt else 16)
    floor = _kg_facts(ctx, m.program_id, trig.crop_code if trig else None).get("하한가") if detail else None
    sub = join(when if amt and detail is None else None, f"하한가 {_won_text(floor)}" if floor else None, tag)
    ctx.shown[m.program_key] = m
    line_tag = _print_tag(p, m)
    note = _direct_pay_note(ctx, p)
    price_detail = detail is not None
    switch = _switch_text(ctx, m.program_id)
    if switch and detail is None:
        detail, line_tag = switch, "CHECK"
    return Line(section="C" if is_coop_route(p) else "D", kind="SUPPORT", title=program_label(p), text=text, pt=pt,
                sub=_fit_sub(sub, note) if note and not price_detail else sub, detail=detail,
                badge=notice_badge(m.row_status, p.expected_notice_month, ctx.as_of), program_key=m.program_key,
                program_id=m.program_id, due=m.window.next_end, office=p.office, print_tag=line_tag,
                trigger_id=trig.rule_id if trig is not None and trig.provisional else None)


DIRECT_PAY_KEYS = frozenset({"NAT-DIRECT-SMALL", "NAT-DIRECT-AREA"})
DIRECT_PAY_UNKNOWN = "NAT-DIRECT-ANY"        # R1 [받고 있음] "직불은 받는데 어떤 직불인지 모름"


def _direct_pay_note(ctx: _Ctx, p: Program) -> str | None:
    """직불 종류를 모르는 채 받고 계신 분: 소농·면적직불 줄에 작년 통지서로 종류를 확인하게 한다(받고 있는 것과 겹쳐 세지 않도록)."""
    if p.program_key in DIRECT_PAY_KEYS and DIRECT_PAY_UNKNOWN in ctx.fs.profile.already_receiving:
        return "직불 종류는 통지서에 있어요"
    return None


def _switch_text(ctx: _Ctx, program_id: str) -> str | None:
    """'전환하면 약 N만~M만 원 더(확인)'. 하한이 0이면 '최대 약 N만 원'. 면적직불에서 소농직불로 바꿀 때의 차액(DIFF_IF_SWITCH)."""
    d = ctx.diff_of.get(program_id)
    if d is None or d.high_won is None:
        return None
    return f"전환하면 {fmt_won(d.low_won or None, d.high_won)} 더(확인)"


def _switch_only_lines(ctx: _Ctx, used: set[str]) -> list[Line]:
    """면적직불을 이미 받아 택1에서 밀린 소농직불 행(EXCLUSIVE_OTHER): 전환 차액이 있을 때만 줄로 안내한다."""
    out: list[Line] = []
    for m in ctx.fs.matches:
        p = ctx.program(m)
        text = _switch_text(ctx, m.program_id) if m.status == "EXCLUSIVE_OTHER" and m.program_key not in used else None
        if text is None:
            continue
        amt = fmt_won(p.amount_value, p.amount_value) if p.amount_value else None
        ctx.shown[m.program_key] = m
        used.add(m.program_key)
        out.append(Line(section="D", kind="SUPPORT", title=program_label(p), text=amt or "금액은 창구에서 확인", pt=18,
                        sub=join(window_text(m.window, m.row_status, ctx.as_of), CHECK_TAG), detail=text,
                        badge=notice_badge(m.row_status, p.expected_notice_month, ctx.as_of), program_key=m.program_key,
                        program_id=m.program_id, due=m.window.next_end, office=p.office, print_tag="CHECK"))
    return out


def _print_tag(p: Program, m: MatchResult) -> Literal["LIKELY", "CHECK"] | None:
    """manual_check가 있는 줄의 꼬리표: FAIL 0·UNKNOWN 0이면 LIKELY, UNKNOWN ≥ 1이거나 소득 심사면 CHECK."""
    if not p.manual_check or any(c.result == "FAIL" for c in m.conds):
        return None
    unknown = any(c.result == "UNKNOWN" for c in m.conds) or p.income_test == "심사"
    return "CHECK" if unknown else "LIKELY"


# --- E 보험, E2 다시 신청 ----------------------------------------------------------------------

def _section_e(ctx: _Ctx, also: tuple[str, ...]) -> list[Line]:
    """보험 — 가입 시기 안내. also에 든 상태(예: ENROLLED)도 낸다. OPEN_NOW 작물 보험은 A가 맡는다."""
    skip = {"NOT_COVERED", "NOT_ELIGIBLE"} | ({"ENROLLED"} - set(also))
    crops: dict[str, list[InsuranceResult]] = {}
    safety: list[InsuranceResult] = []
    in_a = {crop_of(r.product_id) for r in ctx.fs.insurance if is_open_crop_insurance(r)}   # A에 나온 작물은 E에서 뺀다
    for r in ctx.fs.insurance:
        if r.status in skip:
            continue
        if r.product_id.startswith("nh_safety"):
            if SOURCE_HOLD not in r.reasons:      # 원문 대조가 안 끝난(hold) 보험은 앞면에 안 낸다. 뒷면 '준비 중' 수에만 센다
                safety.append(r)
        elif not is_open_crop_insurance(r) and crop_of(r.product_id) not in in_a:
            crops.setdefault(crop_of(r.product_id), []).append(r)
    out = [_crop_insurance_line(ctx, crop, rs) for crop, rs in crops.items()]
    if safety:
        out.append(_safety_line(ctx, safety))
    return out


def _crop_insurance_line(ctx: _Ctx, crop: str, rs: list[InsuranceResult]) -> Line:
    r = min(rs, key=lambda x: x.next_window[0] if x.next_window else date.max)
    start = r.next_window[0] if r.next_window else None
    if r.status == "ENROLLED":
        text = f"가입 중이에요 · {day_when(start, ctx.as_of)}부터 다시 가입해요" if start else "가입 중이에요"
    elif r.status == "NEXT_WINDOW" and start and len({x.product_id.split(":")[0] for x in rs if x.next_window}) > 1:
        # 재해보험·수입안정보험의 시작일이 달라 한 날짜로 단정하지 않는다: 두 창의 합집합 달 범위
        wins = [x.next_window for x in rs if x.next_window]
        first, last = min(w[0] for w in wins).month, max(w[1] for w in wins).month
        when = year_word_of(min(w[0] for w in wins), ctx.as_of)
        text = f"{when} {first}~{last}월에 가입해요 · 날짜는 농협에 물어보세요" if first != last else f"{when} {first}월에 가입해요 · 날짜는 농협에 물어보세요"
    elif r.status == "NEXT_WINDOW" and start:
        text = f"{day_when(start, ctx.as_of)}부터 가입할 수 있어요"
    elif r.status == "CHECK" and r.next_window:
        text = f"{md(r.next_window[1])}까지 가입할 수 있어요 · 농협에 물어보세요"
    else:
        text = "가입 시기는 농협에 물어보세요"
    text, pt = fit(text, 16)
    ids = insurance_program_ids(rs)
    rows = [x for x in ctx.fs.matches if x.program_id in ids]
    month = next((ctx.program(x).expected_notice_month for x in rows if x.row_status == "prior_year_reference"), None)
    prior = "prior_year_reference" if any(x.row_status == "prior_year_reference" for x in rows) else None
    sub = "재해보험과 수입안정보험 중 하나만 들 수 있어요" if len({x.product_id.split(":")[0] for x in rs}) > 1 else None
    if sub is None and any(x.product_id == f"income_stab:{crop}" and x.status == "NOT_COVERED" for x in ctx.fs.insurance):
        sub = "재해보험만 들 수 있어요 · 수입안정보험은 대상이 아니에요"          # 온주 등: 수입안정보험 대상 품목이 아님을 알려 잘못된 기대를 막는다. 배지와 한 줄에 들어가게 짧게
    return Line(section="E", kind="INSURANCE", title=f"{_crop_label(ctx, crop)} 농작물보험", text=text, pt=pt, sub=sub,
                detail=_extra_requirement(ctx, r), badge=notice_badge(prior, month, ctx.as_of), due=start,
                office=ctx.office_name("coop"))


def _extra_requirement(ctx: _Ctx, r: InsuranceResult) -> str | None:
    """보험 상품 행의 가입 요건 글(당근 재해보험 '싹이 밭의 80% 이상 나와야 가입'). 표 글자 그대로."""
    kind, crop = r.product_id.split(":", 1)[0], crop_of(r.product_id)
    row = next((p for p in ctx.bundle.insurance if p.product_id == kind and p.crop_keys and crop in p.crop_keys), None)
    return row.extra_requirement if row else None


def _crop_label(ctx: _Ctx, crop: str) -> str:
    """보험 줄 제목의 작물 이름: 표(crops.csv)의 label. 감귤은 노지온주·만감류가 달라 코드 앞토막 '감귤'만으로는 가려지지 않는다."""
    return next((c.label for c in ctx.bundle.crops if c.crop_code == crop), crop)


def insurance_program_ids(rs: list[InsuranceResult]) -> set[str]:
    """보험 결과 → 근거 제도 행 id. 결과의 출처 id가 'supports:<program_id>'라 이름이 아니라 id로 잇는다."""
    return {r.source.source_id.removeprefix("supports:") for r in rs}


def _safety_line(ctx: _Ctx, rs: list[InsuranceResult]) -> Line:
    who = "·".join("본인" if r.product_id.endswith("owner") else "배우자" for r in rs)
    text = "지금 가입 가능" if any(r.status == "OPEN_NOW" for r in rs) else "가입 여부 확인"
    return Line(section="E", kind="INSURANCE", title="NH안전보험", text=text, pt=16, sub=f"가입 대상: {who}", office=ctx.office_name("coop"),
                no_numbers=any(SOURCE_HOLD in r.reasons for r in rs))


def _section_e2(ctx: _Ctx, used: set[str]) -> list[Line]:
    out: dict[str, Line] = {}
    for m in ctx.fs.matches:
        p = ctx.program(m)
        if m.status == "ALREADY" and m.renew_annual and is_printable_support(p) and m.program_key not in out and m.program_key not in used:
            first = m.window.first_date
            sub, detail, trig = month_when_of(first, ctx.as_of) if first else None, None, None
            if p.trigger == "price_stab":       # 가격안정관리제: 이번 반월 판정과 기준가·작년 사실을 함께(가격 자체는 인쇄하지 않는다)
                trig = ctx.trigger(p)
                if trig is not None and trig.status in TRIGGER_WORD and trig.status != "OUT_OF_SEASON":
                    sub = join(sub, f"이번 반월 {TRIGGER_WORD[trig.status]}" + ("(잠정)" if trig.provisional else ""))
                    paid = _kg_facts(ctx, m.program_id, trig.crop_code).get("작년 kg당 평균")
                    detail = join(f"기준가 {_won_text(trig.threshold)}" if trig.threshold else None,
                                  f"작년 kg당 {_won_text(paid)}" if paid else None)
            out[m.program_key] = Line(
                section="E2", kind="RENEW", title=program_label(p), text="작년처럼 다시 신청하세요", pt=16,
                sub=sub, detail=detail, program_key=m.program_key, program_id=m.program_id, office=p.office,
                badge=notice_badge(m.row_status, p.expected_notice_month, ctx.as_of),
                trigger_id=trig.rule_id if trig is not None and trig.provisional and detail else None)
            ctx.shown.setdefault(m.program_key, m)
    return list(out.values())


# --- F 가실 곳, 고정 줄, G ----------------------------------------------------------------------

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"          # 앞면 항목 번호(ui.render와 같은 순서·같은 글자)
MAX_OFFICES = 3
_OFFICE_ORDER = ("A", "B", "D", "E", "E2", "C")   # 직접 신청·먼저 할 일의 창구를 앞에, 먼저 할 일이 남은 농협 줄의 창구는 뒤에


def _own_emd_office(office: str, emd: str) -> tuple[str, str | None]:
    """접수처가 'A·B·C농협, 수급관리센터'처럼 여러 곳이고 입력 읍면과 같은 이름이 있으면 그 농협만(표 글자 그대로의 토막).
    이름이 안 맞으면 원문 그대로. 반환: (상자에 적을 이름, 나머지를 담은 원문 또는 None)."""
    stem = emd.rstrip("읍면동")
    tokens = [t.strip() for t in office.replace(",", "·").split("·")]
    if len(tokens) < 3 or not stem:
        return office, None
    hit = next((t for t in tokens if t.removesuffix("농협") == stem), None)
    if hit is None:
        return office, None
    return (hit if hit.endswith("농협") else hit + "농협"), office


def _short_office(name: str) -> str:
    """'국립농산물품질관리원 제주지원(농관원)' → '농관원 제주지원'(괄호 안 줄임말 + 앞 이름의 마지막 낱말). 형식이 다르면 원문."""
    m = re.fullmatch(r"(.+\s)(\S+)\((\S+)\)", name)
    return f"{m[3]} {m[2]}" if m else name


def _section_f(ctx: _Ctx, kept: dict[str, list[Line]]) -> list[Line]:
    shown = [l for s in ITEM_SECTIONS for l in kept[s]]
    number = {id(l): CIRCLED[i] if i < len(CIRCLED) else str(i + 1) for i, l in enumerate(shown)}
    # 같은 창구가 "지역농협"·"지역농협(신청 주체)"처럼 꼬리만 다르게 두 번 오면 한 칸만 둔다(괄호 앞 이름이 같으면 같은 곳).
    boxes: dict[str, tuple[str, list[str]]] = {}
    for sec in _OFFICE_ORDER:
        for l in kept[sec]:
            if l.office:
                key = l.office.split("(")[0].strip()
                boxes.setdefault(key, (l.office, []))[1].append(number[id(l)])
    for key, (name, nums) in boxes.items():       # 번호는 앞면 순서로
        nums.sort(key=CIRCLED.find)
    out = []
    for office, nums in list(boxes.values())[:MAX_OFFICES]:
        name, full = _own_emd_office(office, ctx.fs.profile.emd_code)
        o = ctx.bundle.office_named(office)
        text, pt = fit(join(_short_office(name), o.phone if o else None) or name, 14)
        out.append(Line(section="F", kind="OFFICE", title="가실 곳 " + "".join(nums), text=text, pt=pt,
                        detail=f"전체: {full}" if full else None))
    docs = list(dict.fromkeys(d for l in shown if l.program_key
                              if (d := next((p.documents for p in ctx.bundle.programs
                                             if p.program_key == l.program_key and p.documents), None))))
    if docs:
        full = "; ".join(docs)
        text, pt = fit("서류: " + docs[0], 14)
        out.append(Line(section="F", kind="OFFICE", title="가져오실 서류", text=text, pt=pt,
                        detail=full if len(docs) > 1 else None))   # 서류가 하나면 본문과 같아 다시 적지 않는다
    return out


def _fixed(ctx: _Ctx) -> tuple[Line, ...]:
    # 준비물 줄(3차 평가단 지적): 창구에 들고 갈 것. 제도별 서류는 표 documents 칸이 찬 행에서만 F '가져오실 서류'로 찍힌다.
    text, pt = fit(BRING_TEXT, 14)
    out = [Line(section="F", kind="FIXED", title="가실 때", text=text, pt=pt)]
    text, pt = fit(FARM_HELPER_TEXT, 14)
    out.append(Line(section="F", kind="FIXED", title="영농도우미", text=text, pt=pt))
    if not ctx.fs.profile.flags.disaster_damage:
        row = disaster_row(ctx.bundle)
        # 한 줄로 쓴다(두 줄이면 앞면 바닥글을 밀어낸다). 기한은 표의 apply_within_days, 없으면 manual_check 첫 토막.
        days = row.apply_within_days if row else None
        deadline = f"재난 뒤 {days}일 안에 읍·면·동에 신고해요" if days else (first_segment(row.manual_check) if row else None)
        both = join(DISASTER_ASK_TEXT, deadline)
        if both and len(both) > LIMIT[13]:            # 한 줄(13pt 40자)에 안 들면 앞 문장을 줄인다(뜻은 같다)
            both = join(DISASTER_ASK_TEXT.replace("꼭 ", ""), deadline)
        text, pt = fit(both or DISASTER_ASK_TEXT, 14)
        out.append(Line(section="F", kind="FIXED", title="재해 피해", text=text, pt=pt))
    return tuple(out)


def _footer() -> Iterator[Line]:
    for t in DISCLAIMER:
        yield Line(section="G", kind="NOTICE", title="안내", text=t, pt=13)


# --- 빈 종이 ----------------------------------------------------------------------------------

def _empty(ctx: _Ctx, b_lines: list[Line], fixed: tuple[Line, ...], footer: tuple[Line, ...], calendar3) -> EmptyFront:
    already = {m.program_key: m for m in ctx.fs.matches if m.status == "ALREADY" and is_printable_support(ctx.program(m))}
    low = high = 0
    counted = False
    for m in already.values():
        a = ctx.amount_of.get(m.program_id)
        if a and a.kind in FIXED_AMOUNT_KINDS and a.low_won is not None and a.high_won is not None:
            low, high, counted = low + a.low_won, high + a.high_won, True
    months = [ctx.program(m).expected_notice_month for m in already.values() if m.row_status == "prior_year_reference"]
    prior = any(m.row_status == "prior_year_reference" for m in already.values())
    insurance = _section_e(ctx, ("ENROLLED",))
    return EmptyFront(
        title=EMPTY_TITLE, money_text=f"지키실 돈 연 {fmt_won(low, high)}" if counted else None,
        badge=notice_badge("prior_year_reference" if prior else None, min((x for x in months if x), default=None), ctx.as_of),
        keep_low_won=low if counted else None, keep_high_won=high if counted else None,
        keep_actions=_keep_all(ctx, [l for l in b_lines if l.kind == "KEEP"]), insurance_next=tuple(insurance),
        calendar3=calendar3, fixed=fixed, footer=footer)


def _keep_all(ctx: _Ctx, due_soon: list[Line]) -> tuple[Line, ...]:
    """빈 종이의 '끊기지 않게': 경영체 갱신 연도는 몇 년 뒤여도, 직불 교육은 받으시는 분이면 해마다 보인다(설계 §12-A(2)).
    앞면 B칸의 KEEP(갱신이 내년까지, 올해 교육 아직)은 그대로 쓰고 없는 것만 채운다."""
    p = ctx.fs.profile
    have = {a.action_id.split(":")[1] for a in ctx.fs.actions if a.kind == "KEEP"}     # 이미 B칸 KEEP 행동이 있는 것(mgmt_renewal, direct_pay_education)
    out = list(due_soon)
    if p.mgmt_last_reg_year is not None and "mgmt_renewal" not in have:
        out.append(_keep_line(f"mgmt_renewal:{p.mgmt_last_reg_year + MGMT_RENEW_YEARS}"))
    if p.flags.direct_payment_education in ("Y", "N") and "direct_pay_education" not in have:
        out.append(_keep_line("direct_pay_education", yearly=True))
    return tuple(out)


def _back(ctx: _Ctx, overflow: tuple[Line, ...]) -> Back:
    return Back(input_summary=input_summary(ctx), line_conds=line_conds(ctx), price_basis=price_basis(ctx),
                overflow=overflow, excluded=excluded(ctx), checks=checks(ctx), fingerprint_slot=FINGERPRINT_SLOT,
                office_names={o.office_id: o.name for o in ctx.bundle.offices.values()},
                office_phones={o.office_id: o.phone for o in ctx.bundle.offices.values() if o.phone}, hold_note=hold_note(ctx))
