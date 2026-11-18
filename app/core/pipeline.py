"""파이프라인(Task 20, U20): 농가 + 표 + 스냅샷 + 기준일 → FactSheet, 계산 지문, LLM에 넘기는 숫자 없는 보기.

순서: match → triggers(작물마다) → amounts → insurance → actions. 순수 함수다: 시계·파일을 읽지 않고, 표 묶음과
스냅샷은 인자로 받는다(읽는 일은 data_layer가 한다).

- hold 행의 출처(`supports:<행 id>`)를 보험 판정에 넘겨, 출처가 보류된 상품에 "source_hold" 꼬리표가 붙는다.
- 행동은 8개까지 둔다(계통 전환 줄이 잘리지 않게).
- FactSheet.facts: 종이에 나갈 수 있는 제도마다 정식 이름(`name:<제도 id>`)·접수처 id(`office:<제도 id>`), 보험 상품마다
  접수처 id(`office:<상품 id>`). narrative_input이 FactSheet 하나만으로 이름·창구를 알 수 있게 하는 자리다. 작년 공고 기준 행의
  사실에는 expected_notice_month를 싣는다.
- 계산 지문 = FactSheet(지문 칸 제외, as_of·data_version 포함)를 키 정렬 JSON으로 만든 sha256의 앞 8자.
- narrative_input 별칭 규칙: 제도는 program_key를 소문자·밑줄로(`NAT-DIRECT-AREA` → `nat_direct_area`), 보험은
  `<상품>_<작물 순번 a·b>` / `nh_safety_owner`, 행동은 `a_<묶음>`. 표 규칙상 program_key에 숫자가 없고, 혹시 있으면 숫자를
  `a~j`로 바꾼다. 별칭 → 실제 id 표는 NarrativeInput.aliases(JSON에는 안 나감).
"""
import hashlib
import json
from collections.abc import Mapping
from datetime import date

from app.core.actions import is_printable_support, next_actions
from app.core.amounts import calc_amounts
from app.core.insurance import check_insurance
from app.core.match import match_supports
from app.core.models import (Fact, FactSheet, FarmProfile, Header, InsuranceResult, MatchResult, NarrativeInput,
                             NarrativeItem, TriggerResult)
from app.core.params_view import season_params
from app.core.snapshot_models import Snapshot
from app.core.tables_models import TableBundle
from app.core.triggers import check_triggers

MAX_ACTIONS = 8
FINGERPRINT_LEN = 8
_NAME, _OFFICE = "name:", "office:"
META_FACT_PREFIXES = (_NAME, _OFFICE)   # 이름·접수처 id를 나르는 자리 사실(숫자 사실이 아님). 화면·골든 비교는 걸러 쓴다


def is_meta_fact(fact: Fact) -> bool:
    return fact.fact_id.startswith(META_FACT_PREFIXES)


def build_fact_sheet(profile: FarmProfile, bundle: TableBundle, snap: Snapshot, as_of: date, data_version: str, *,
                     demo_asof: bool = False) -> FactSheet:
    matches = match_supports(profile, bundle.programs, as_of, crops=bundle.crops)
    by_crop: dict[str, tuple[TriggerResult, ...]] = {}
    for plot in profile.crops:
        if plot.crop_code not in by_crop:
            by_crop[plot.crop_code] = check_triggers(plot.crop_code, snap, season_params(bundle, plot.crop_code, as_of),
                                                     bundle.interventions, as_of)
    triggers = tuple(t for rs in by_crop.values() for t in rs)
    amounts = calc_amounts(profile, matches, by_crop, bundle, as_of)
    hold = frozenset(f"supports:{p.id}" for p in bundle.programs if p.status == "hold")
    insurance = check_insurance(profile, bundle.insurance, as_of, hold)
    actions = next_actions(profile, bundle, matches, insurance, amounts, triggers, as_of, limit=MAX_ACTIONS)
    header = Header(price_as_of=snap.price_as_of, citrus_as_of=snap.citrus_as_of, tables_verified=bundle.verified_date,
                    snapshot_built=snap.built_at, refresh_ok=None, demo_asof=demo_asof)
    fs = FactSheet(profile=profile, matches=matches, triggers=triggers, amounts=amounts, insurance=insurance,
                   actions=actions, facts=_facts(matches, insurance, bundle, as_of), header=header, as_of=as_of,
                   data_version=data_version)
    return fs.model_copy(update={"fingerprint": fingerprint(fs)})


def _facts(matches: tuple[MatchResult, ...], insurance: tuple[InsuranceResult, ...], bundle: TableBundle,
           as_of: date) -> tuple[Fact, ...]:
    by_id = {p.id: p for p in bundle.programs}
    out: list[Fact] = []
    for m in matches:
        p = by_id.get(m.program_id)
        if p is None or not is_printable_support(p):
            continue
        prior = m.row_status == "prior_year_reference"
        out.append(Fact(fact_id=_NAME + p.id, label="정식 이름", value=p.name or p.program_key, unit=None, source=m.source,
                        as_of=as_of, row_status=m.row_status,
                        expected_notice_month=p.expected_notice_month if prior else None))
        office = bundle.office_named(p.office)
        if office is not None:
            out.append(Fact(fact_id=_OFFICE + p.id, label="접수처 id", value=office.office_id, unit=None,
                            source=m.source, as_of=as_of, row_status=None))
    for r in insurance:
        kind, _, target = r.product_id.partition(":")
        crop = target.split("#")[0]
        row = next((pr for pr in bundle.insurance if pr.product_id == kind and (pr.crop_keys is None or crop in pr.crop_keys)),
                   None)
        if row is not None:
            out.append(Fact(fact_id=_OFFICE + r.product_id, label="접수처 id", value=row.office_id, unit=None,
                            source=r.source, as_of=as_of, row_status=None))
    return tuple(out)


def fingerprint(fs: FactSheet) -> str:
    """계산 지문: FactSheet(지문 칸 제외)의 키 정렬 JSON sha256 앞 8자. as_of·data_version이 들어 있어 날짜가 바뀌면 달라진다."""
    body = fs.model_dump(mode="json", exclude={"fingerprint"})
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


# --- 숫자 없는 보기 ----------------------------------------------------------------------------------

_DIGIT_TO_LETTER = str.maketrans("0123456789", "abcdefghij")
_INS_NAME = {"crop_disaster": "농작물재해보험", "income_stab": "농업수입안정보험", "nh_safety": "NH안전보험"}
_ACTION_NAME = {"mgmt_registration": "농업경영체 등록", "enrollment": "참여 신청", "fund": "자조금 가입",
                "coop_fund": "농협 출하 전환", "coop": "농협 출하 확인", "direct_pay_education": "직불 교육",
                "mgmt_renewal": "경영체 갱신", "spouse_registration": "배우자 경영체 등록"}
_CORE_ACTIONS = frozenset({"URGENT", "DISASTER_REPORT", "PREREQ", "COOP_SWITCH", "APPLY_NOW", "APPLY_NEXT", "ASK_COOP"})
_SUPPORT_STATUS = ("LIKELY", "CHECK", "BLOCKED_PREREQ")
_RANK = {s: i for i, s in enumerate(_SUPPORT_STATUS)}


def _slug(text: str) -> str:
    return text.lower().replace("-", "_").replace(":", "_").replace("@", "_").translate(_DIGIT_TO_LETTER)


def _window(m: MatchResult) -> str:
    w = m.window
    if m.status == "OUT_OF_VALIDITY":
        return "closed"
    if w.always_open:
        return "always_open"
    if w.open_now:
        return "open_now"
    return "upcoming" if w.first_date is not None else "unknown"


def narrative_input(fs: FactSheet) -> NarrativeInput:
    """제도 id·정식 이름·상태·누락 조건·창 상태·창구 id만. 금액·날짜·나이·면적·읍면동은 넣지 않는다."""
    names = {f.fact_id.removeprefix(_NAME): str(f.value) for f in fs.facts if is_meta_fact(f) and f.fact_id.startswith(_NAME)}
    offices = {f.fact_id.removeprefix(_OFFICE): str(f.value) for f in fs.facts if is_meta_fact(f) and f.fact_id.startswith(_OFFICE)}
    aliases: dict[str, str] = {}
    has_support = any(m.program_id in names and m.status in _SUPPORT_STATUS for m in fs.matches)
    empty = not has_support and not any(a.kind in _CORE_ACTIONS for a in fs.actions)
    items: list[NarrativeItem] = []

    best: dict[str, MatchResult] = {}
    for m in fs.matches:
        if m.program_id not in names:
            continue
        ok = m.status == "ALREADY" if empty else m.status in _SUPPORT_STATUS
        if ok and (m.program_key not in best or _RANK.get(m.status, 9) < _RANK.get(best[m.program_key].status, 9)):
            best[m.program_key] = m
    for key, m in best.items():
        alias = _slug(key)
        aliases[alias] = m.program_id
        items.append(NarrativeItem(
            section="empty" if empty else "support", fact_id="M:" + alias, program_id=alias,
            official_name=names[m.program_id], status=m.status, row_status=m.row_status,
            missing=tuple(dict.fromkeys((*m.missing_prereqs, *m.unknown_fields))), window=_window(m),
            office_id=offices.get(m.program_id)))
    items += _insurance_items(fs, offices, aliases)
    items += _action_items(fs, names, {m.program_key: names[m.program_id] for m in fs.matches if m.program_id in names}, aliases)
    return NarrativeInput(empty_sheet=empty, items=tuple(items), aliases=aliases)


def _letter(letters: Mapping[str, str], target: str) -> str:
    if target not in letters:
        raise ValueError(f"농가 작물에 없는 보험 대상입니다: {target!r}")
    return letters[target]


def _crop_letters(profile: FarmProfile) -> dict[str, str]:
    """보험 결과의 대상(`당근`, 같은 작물이 또 있으면 `당근#2`) → 농가 작물 순번 글자(a, b)."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for i, plot in enumerate(profile.crops):
        seen[plot.crop_code] = n = seen.get(plot.crop_code, 0) + 1
        out[plot.crop_code if n == 1 else f"{plot.crop_code}#{n}"] = chr(ord("a") + i)
    return out


def _insurance_items(fs: FactSheet, offices: Mapping[str, str], aliases: dict[str, str]) -> list[NarrativeItem]:
    letters = _crop_letters(fs.profile)
    out = []
    for r in fs.insurance:
        if r.status in ("NOT_COVERED", "NOT_ELIGIBLE"):
            continue
        kind, _, target = r.product_id.partition(":")
        if kind == "nh_safety":
            alias, name = f"nh_safety_{target}", f"{_INS_NAME[kind]}({'본인' if target == 'owner' else '배우자'})"
        else:
            alias, name = f"{kind}_{_letter(letters, target)}", f"{_INS_NAME[kind]}({target.split('#')[0].split('_')[0]})"
        aliases[alias] = r.product_id
        out.append(NarrativeItem(
            section="insurance", fact_id="I:" + alias, program_id=alias, official_name=name, status=r.status,
            row_status=None, missing=(), window=_ins_window(r), office_id=offices.get(r.product_id)))
    return out


def _ins_window(r: InsuranceResult) -> str:
    if r.status == "OPEN_NOW":
        return "open_now"
    return "upcoming" if r.next_window else "unknown"


def _action_items(fs: FactSheet, names: Mapping[str, str], key_names: Mapping[str, str],
                  aliases: dict[str, str]) -> list[NarrativeItem]:
    out = []
    letters = _crop_letters(fs.profile)
    for a in fs.actions:
        ref = a.action_id.split(":", 1)[1]
        group = ref.split(":")[0]
        if ref in names:                                 # URGENT / DISASTER_REPORT:<제도 id>
            name, tail = names[ref], _slug(ref)
        elif ref in key_names:                           # APPLY_NOW / APPLY_NEXT:<program_key>
            name, tail = key_names[ref], _slug(ref)
        elif group == "ins":                             # ins:<작물> → 작물 순번 글자
            name, tail = "농작물보험", "ins_" + _letter(letters, ref.split(":", 1)[1])
        else:
            name, tail = _ACTION_NAME.get(group, "다음에 하실 일"), _slug(group)
        alias = base = "a_" + tail
        n = 0
        while alias in aliases and aliases[alias] != a.action_id:   # 같은 별칭이 다른 행동이면 글자를 붙인다
            alias, n = f"{base}_{chr(ord('a') + n)}", n + 1
        aliases[alias] = a.action_id
        out.append(NarrativeItem(
            section="action", fact_id="A:" + alias, program_id=alias, official_name=name, status=a.kind, row_status=None,
            missing=(), window="always_open" if a.due is None else "upcoming", office_id=a.office_id))
    return out
