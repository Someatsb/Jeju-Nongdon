"""뒷면 조립 도우미(Task 15): 입력 요약, 줄별 조건표, 가격 근거, 뺀 것, 확인란. sheet.py가 Back으로 묶는다.

창구 담당자용(10pt)이라 줄 글자 수 상한이 없다. SourceRef.as_of가 None이면 '확인일 미상'을 찍는다(날짜를 지어내지 않음).
"""
import re
from datetime import date
from typing import Protocol

from app.core.actions import is_printable_support
from app.core.models import CondCheck, CoreModel, FactSheet, MatchResult, Program
from app.core.tables_models import TableBundle
from app.core.units import HA_M2
from app.core.sheet_rules import (FIELD_LABEL, KEY_NOTE, RULE_LABEL, TRIGGER_WORD, UNIT_OF, VALUE_LABEL, YN_LABEL, join,
                                  program_label)


_M2 = re.compile(r"(\d+)㎡")


class BackCtx(Protocol):
    fs: FactSheet
    as_of: date
    shown: dict[str, MatchResult]

    bundle: TableBundle

    def program(self, m: MatchResult) -> Program: ...


class LineConds(CoreModel):
    program_key: str
    name: str
    conds: tuple[CondCheck, ...]
    source: str                                 # "<출처 id> · 확인일 2026-11-07" 또는 "… · 확인일 미상"


class Excluded(CoreModel):
    name: str
    reason: str


_SEX = {"M": "남", "F": "여"}
BACK_STATUS = {"NOT_APPLICABLE": "해당 없음"}                    # 앞면 줄에는 안 나오는 판정 상태의 쉬운 이름(영어 코드를 뒷면에 찍지 않는다)
FINGERPRINT_SLOT = "계산 지문 · 표 확인일 · 시세 기준일 · 보험 기준일 (인쇄할 때 채움)"
_COND_VALUES = {"needs_mgmt": "mgmt_status", "min_mgmt_years": "mgmt_status", "owns_land": "land_tenure"}
_SALES_VALUES = {"needs_coop": "sales_channel", "needs_selfpay_fund": "selfpay_fund"}


def _label(kind: str, code: str) -> str:
    return VALUE_LABEL[kind].get(code, code)


def input_summary(ctx: BackCtx) -> tuple[str, ...]:
    p = ctx.fs.profile
    out = [f"기준일 {ctx.as_of.isoformat()}", f"읍면동 {p.emd_code}",
           f"태어난 해 {p.birth_year or '모름'}" + (" (대략)" if p.birth_year_approx else ""),
           f"경영체 {_label('mgmt_status', p.mgmt_status)} · 마지막 등록 {p.mgmt_last_reg_year or '모름'}",
           f"땅 {_label('land_tenure', p.land_tenure)}", f"배우자 {_label('spouse', p.spouse)}",
           f"건강보험 {_label('health_ins', p.health_ins)}", f"이미 받고 계신 것 {_receiving_names(ctx)}",
           f"재해 피해 {'있음' if p.flags.disaster_damage else '없음'}",
           f"직불 교육 {YN_LABEL.get(p.flags.direct_payment_education, p.flags.direct_payment_education)}"]
    out += [f"작물 {c.crop_code} {c.area_m2 or '면적 모름'}㎡ · {_label('sales_channel', c.sales_channel)} · "
            f"자조금 {_label('selfpay_fund', c.selfpay_fund)}" for c in p.crops]
    return tuple(out)


def _receiving_names(ctx: BackCtx) -> str:
    """입력의 [받고 있음] program_key → 제도 이름(표에 있는 이름). 표에 없는 칸(직불 종류 모름)은 풀어 쓴다. 없으면 '없음'."""
    names = {p.program_key: p.name for p in ctx.bundle.programs if p.name}
    got = [KEY_NOTE.get(k) or names.get(k) or k for k in sorted(ctx.fs.profile.already_receiving)]
    return " · ".join(got) if got else "없음"


def _source_text(m: MatchResult) -> str:
    return f"{m.source.source_id} · " + (f"확인일 {m.source.as_of.isoformat()}" if m.source.as_of else "확인일 미상")


def _ha(m2: str) -> str:
    """'12000㎡' → '1.2ha'(소수 둘째 자리까지, 끝의 0은 뗀다)."""
    return _M2.sub(lambda m: f"{(int(m[1]) / HA_M2):.2f}".rstrip("0").rstrip(".") + "ha", m2)


_HA_DIRECTION = {"min_ha": "이상", "max_ha": "이하", "max_owned_ha": "이하"}


def _korean(c: CondCheck, units: bool = False) -> CondCheck:
    """뒷면용 조건 한 칸: 칸 이름·코드값을 한글로(판정 결과는 그대로). units면 면적 칸은 단위를 ha로 맞춘다."""
    if units and c.field in _HA_DIRECTION and c.required:
        return c.model_copy(update={"field": FIELD_LABEL.get(c.field, c.field),
                                    "required": f"기준 {c.required}ha {_HA_DIRECTION[c.field]}", "actual": f"입력 {_ha(c.actual)}"})
    required = YN_LABEL.get(c.required, c.required)
    actual = c.actual
    if c.field == "sex":                                    # 성별 코드(M·F)는 남·여로
        required, actual = _SEX.get(required, required), _SEX.get(actual, actual)
    if c.field in _COND_VALUES:
        actual = _label(_COND_VALUES[c.field], actual)
    elif c.field in _SALES_VALUES and ":" in actual:
        crop, code = actual.split(":", 1)
        actual = f"{crop}: {_label(_SALES_VALUES[c.field], code)}"
    return c.model_copy(update={"field": FIELD_LABEL.get(c.field, c.field), "required": required, "actual": actual})


def line_conds(ctx: BackCtx) -> tuple[LineConds, ...]:
    return tuple(LineConds(program_key=k, name=program_label(ctx.program(m)), conds=tuple(_korean(c, units=True) for c in m.conds),
                           source=_source_text(m)) for k, m in ctx.shown.items())


def price_basis(ctx: BackCtx) -> tuple[str, ...]:
    """가격 판정 근거 한 줄씩. 영문 코드 대신 한글로(규칙 이름·상태·시즌 전이면 다음 판정 달과 자료 마지막 날)."""
    out = []
    for t in ctx.fs.triggers:
        status = TRIGGER_WORD.get(t.status) or BACK_STATUS.get(t.status, t.status)
        if t.status == "MET" and t.rule_id == "ISOLATION_HISTORY":
            status = "과거에 있었음"
        status += "(잠정)" if t.provisional else ""
        if t.status == "OUT_OF_SEASON" and t.window:
            status = f"시즌 전({t.window[0].month}월부터 판정)"
        last = ctx.fs.header.price_as_of
        if t.data_as_of:
            asof = f"기준일 {t.data_as_of.isoformat()}"
        elif t.status == "OUT_OF_SEASON" and last:
            asof = f"자료 마지막 날 {last.strftime('%m-%d')}"
        else:
            asof = "기준일 미상"
        metric = ("과거 {1}번 중 {0}번".format(*t.history_hits) if t.history_hits else
                  "반월 가중 평균가" if "반월가중" in t.metric else "월 가중 평균가" if "월가중" in t.metric else
                  "수매·격리가 있었던 시즌 수" if "seasons_with_intervention" in t.metric else t.metric)
        out.append(join(RULE_LABEL.get(t.rule_id, t.rule_id), status, metric, asof, t.note) or t.rule_id)
    return tuple(out)


def excluded(ctx: BackCtx) -> tuple[Excluded, ...]:
    best: dict[str, MatchResult] = {}
    live = {m.program_key for m in ctx.fs.matches if m.status not in ("NOT_ELIGIBLE", "OUT_OF_VALIDITY")}
    for m in ctx.fs.matches:
        if m.status in ("NOT_ELIGIBLE", "OUT_OF_VALIDITY") and m.program_key not in live and is_printable_support(ctx.program(m)):
            best.setdefault(m.program_key, m)
    out = []
    for m in list(best.values())[:3]:
        fail = next((c for c in m.conds if c.result == "FAIL"), None)
        reason = "기간이 끝남" if m.status == "OUT_OF_VALIDITY" else _fail_reason(fail)
        out.append(Excluded(name=program_label(ctx.program(m)), reason=reason))
    return tuple(out)


def hold_note(ctx: BackCtx) -> str | None:
    """원문 대조가 끝나지 않아(hold) 종이에 넣지 않은 지원금 제도 수. 제도 이름이나 금액은 싣지 않는다."""
    n = len({p.program_key for p in ctx.bundle.programs if p.status == "hold" and is_printable_support(p)})
    return f"준비 중 {n}건 (원문 확인이 끝나지 않아 이 종이에는 넣지 않았어요)" if n else None


def _fail_reason(c: CondCheck | None) -> str:
    """'소유 면적 조건에 안 맞음 (기준 1.55ha · 입력 15501㎡ 이상)': 기준과 입력을 함께 보여 창구가 바로 대조한다."""
    if c is None:
        return "조건에 안 맞음"
    k = _korean(c)                                  # 코드값은 한글로(뒷면은 코드를 찍지 않는다)
    unit = UNIT_OF.get(c.field, "")
    actual = _ha(k.actual) if unit == "ha" else k.actual    # 면적 조건은 ha 하나로
    detail = f" (기준 {k.required}{unit} · 입력 {actual})" if k.required else ""
    return f"{k.field} 조건에 안 맞음{detail}"


def checks(ctx: BackCtx) -> tuple[str, ...]:
    return tuple(f"□ {program_label(ctx.program(m))}: {m.manual_check}" for m in ctx.shown.values() if m.manual_check)
