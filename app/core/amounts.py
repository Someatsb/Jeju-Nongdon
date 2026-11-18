"""금액 계산(Task 14, U14). 금액은 코드만 계산해 "약·범위·최대·작년"으로 내보낸다. 전망은 하지 않는다.

amount_type 7종(research/dept/round1-B-data.md §2-4):
- 정액 → FIXED: amount_value. 배우자가 경영체에 등록돼(2인 경영체) amount_2plus_each가 있으면 1인당 × 2.
- 면적비례 → PER_AREA: ha당 [amount_min, amount_max](없는 쪽은 amount_value) × 면적, cap_won으로 자른다.
  면적은 calc_basis(경작면적·해당작물면적·소유면적), 비면 area_basis로 고른다. amount_note의 "○ha 이하 ha당 ○만 원"
  (면적직불: 진흥지역 밖 밭 — 제주 밭 대부분, 스펙 §12-A(7))은 면적이 그 이하일 때 하한 단가가 된다.
- kg당 → UNDISCLOSED: 출하량은 입력에 없어 kg당 단가 항만.
- 단위당 → PER_AREA: min(units_per_ha × 면적(낱개로 내림), cap_units) × amount_value, cap_won으로 자른다.
- 보조율 → UNDISCLOSED: 사업비를 모르므로 총액을 내지 않는다. 비율·최대 항만.
- 규칙 → §4 규칙이 줄을 만든다. 금액 줄은 price_stab만(물류비 §4-2는 과거 사실 문장뿐이라 줄 없음).
  그 작물의 PRICE_STAB 판정이 MET·NEAR일 때만 두 줄, 둘 다 excluded=("예측 아님",):
    PER_KG_TRIGGER: kg당 차액 (기준가 − max(반월 평균, 하한가)) × 지급 비율(0 아래로 안 감)을 사실로. 총액 없음.
    REFERENCE_LAST_SEASON: 지난 시즌 kg당 평균 지급액 × 예상 물량(면적 × 10a당 수확량) "작년 실적 참고".
- 없음 → UNDISCLOSED: 총액 없음(사유는 amount_note를 템플릿이 찍는다). cap_won이 있으면 최대 항.

줄은 LIKELY(꼬리표 없음)·CHECK(check_note "확인할 조건 있음", 스펙 §12-A(7)) 행과, 이미 받는 ALREADY 행(already=True:
"지키실 돈"·작년 실적 줄용, 앞면 "받을 돈"은 건너뛴다)에. ALREADY의 가격안정관리제는 발동 판정과 무관하게 지난 시즌
실적 줄만 낸다. BLOCKED_PREREQ의 돈은 먼저 할 일의 가정 금액(unlock_amounts)으로만 나가고 계통 전환에는 금액이 없다
(§12-A(2)). NOT_ELIGIBLE·EXCLUSIVE_OTHER·OUT_OF_VALIDITY·hold는 줄 없음. 면적이 0이면 0원 줄 대신 줄이 없다. 반올림: 계산한 금액은 round_won, 정액과 cap_won에 걸린 값은 표 숫자 그대로.
"""
import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.core.match import _changed, match_supports, what_if  # _changed: what_if와 같은 규칙으로 바꾼 농가
from app.core.models import AmountLine, CropPlot, FarmProfile, MatchResult, Program, SourceRef, Term, TriggerResult
from app.core.params_view import SeasonParams, season_params, season_value
from app.core.tables_models import Crop, TableBundle
from app.core.units import m2_to_ha, round_won

CHECK_NOTE = "확인할 조건 있음"
NEAR_NOTE = "근처 — 농협 확인"
NOT_FORECAST = "예측 아님"
COOP_ONLY = "계통출하 물량에 한함"
DIRECT_PAY_UNKNOWN = "NAT-DIRECT-ANY"        # R1 [받고 있음] "직불은 받는데 어떤 직불인지 모름"
SMALL_DIRECT, AREA_DIRECT = "NAT-DIRECT-SMALL", "NAT-DIRECT-AREA"
CANDIDATE = frozenset({"LIKELY", "CHECK"})
SHOWN_STAB = frozenset({"MET", "NEAR"})
# 채워도 몇 해를 기다려야 열리는 칸. 지금 하는 일로 생기는 돈이 아니라 가정 금액에 넣지 않는다
# (골든 P4: 경영체 등록 → 면적직불만, "농민수당 50만 원은 2029년~").
WAIT_FIELDS = frozenset({"min_mgmt_years"})
M2_PER_10A = 1_000
TENTH = Decimal("0.1")

_BASIS = {"경작면적": "경작", "해당작물면적": "해당작물", "소유면적": "소유"}
_SMALL_AREA = re.compile(r"(\d+(?:\.\d+)?)ha 이하 ha당 ([\d,]+)만 원")
_COOP_SWITCH = re.compile(r"crops\[\d+\]\.sales_channel")
_CALC = SourceRef(source_id="calc:amounts", url=None, as_of=None)   # 다른 항으로 계산한 값


class _Market(NamedTuple):
    """규칙(price_stab) 줄에 필요한 것. 가정 재대조(unlock_amounts)에는 없다."""

    triggers: Mapping[str, Iterable[TriggerResult]]
    bundle: TableBundle
    as_of: date


def calc_amounts(profile: FarmProfile, matches: Iterable[MatchResult], triggers: Mapping[str, Iterable[TriggerResult]],
                 bundle: TableBundle, as_of: date) -> tuple[AmountLine, ...]:
    """매칭 순서대로 금액 줄. triggers는 작물 코드 → check_triggers 결과(그 작물의 PRICE_STAB을 찾는다).
    가격안정관리제 행은 줄이 둘(PER_KG_TRIGGER, REFERENCE_LAST_SEASON)일 수 있다."""
    by_id = {p.id: p for p in bundle.programs}
    groups = _groups(bundle.crops)
    market = _Market(triggers, bundle, as_of)
    out: list[AmountLine] = []
    matches = tuple(matches)
    for m in matches:
        pr = by_id.get(m.program_id)
        if pr is None or pr.status == "hold":
            continue   # pr가 None: 매칭과 표 묶음이 어긋난 행 — 죽지 않고 줄 없이 넘긴다
        out.extend(_switch_lines(pr, m, matches, by_id, profile, groups))
        if m.status not in CANDIDATE | {"ALREADY"} and not (m.status == "BLOCKED_PREREQ" and pr.rule_ref == "price_stab"):
            continue
        lines = _lines(pr, m, profile, groups, market)
        out.extend(a.model_copy(update={"already": True}) for a in lines) if m.status == "ALREADY" else out.extend(lines)
    return tuple(out)


def _switch_lines(pr: Program, m: MatchResult, matches: tuple[MatchResult, ...], by_id: Mapping[str, Program],
                  profile: FarmProfile, groups: Mapping[str, frozenset[str]]) -> tuple[AmountLine, ...]:
    """DIFF_IF_SWITCH(Task 10 Ruling): 소농직불 고정액 − 면적직불 범위 = 면적직불에서 소농으로 '전환하면' 더 받는 돈.
    면적직불을 이미 받으면(소농 행은 EXCLUSIVE_OTHER) 또는 받는 직불 종류를 모르면(NAT-DIRECT-ANY, 소농 행이 후보) 낸다.
    범위는 [max(0, 소농 − 면적직불 상한), 소농 − 면적직불 하한]이고 상한이 0 이하면 줄이 없다(전환해도 손해)."""
    if pr.program_key != SMALL_DIRECT or pr.amount_value is None:
        return ()
    receiving_area = m.status == "EXCLUSIVE_OTHER" and any(
        o.program_key == AREA_DIRECT and o.status == "ALREADY" for o in matches)
    unknown_kind = m.status in CANDIDATE and DIRECT_PAY_UNKNOWN in profile.already_receiving
    if not (receiving_area or unknown_kind):
        return ()
    area_row = next((by_id[o.program_id] for o in matches if o.program_key == AREA_DIRECT and by_id[o.program_id].status != "hold"), None)
    area = None if area_row is None else _per_area(area_row, m.source, profile, groups, None)
    if area is None or area.low_won is None or area.high_won is None:
        return ()
    high = pr.amount_value - area.low_won
    if high <= 0:
        return ()
    low = max(0, pr.amount_value - area.high_won)
    terms = (_term("소농직불", pr.amount_value, "원", m.source), _term("면적직불 하한", area.low_won, "원", _CALC),
             _term("면적직불 상한", area.high_won, "원", _CALC))
    return (_line(pr, "DIFF_IF_SWITCH", low, high, terms, CHECK_NOTE),)


def unlock_amounts(profile: FarmProfile, programs: tuple[Program, ...], as_of: date, change: Mapping[str, object], *,
                   crops: Iterable[Crop] = ()) -> tuple[int | None, int | None]:
    """먼저 할 일(change)을 하면 새로 열리는 돈의 (하한 합, 상한 합). crops는 TableBundle.crops.

    what_if 결과 중 LIKELY·CHECK이고 바꾸기 전엔 아니던 행의 금액 줄을 더한다(바꾼 농가로 계산). 바꾸기 전에
    기다려야 하는 칸(WAIT_FIELDS)이 막고 있던 행은 뺀다. 계통 전환(sales_channel → coop)이 들어 있으면 금액을 만들지
    않는다(§12-A(2)). 총액이 있는 줄이 없으면 (None, None).
    """
    if any(_COOP_SWITCH.fullmatch(k) and v == "coop" for k, v in change.items()):
        return None, None
    crops = tuple(crops)
    before = {m.program_id: m for m in match_supports(profile, programs, as_of, crops=crops)}
    changed = _changed(profile, change)
    by_id = {p.id: p for p in programs}
    groups = _groups(crops)
    priced = [a for m in what_if(profile, programs, as_of, change, crops=crops) if _opened(m, before.get(m.program_id))
              for a in _lines(by_id[m.program_id], m, changed, groups, None)
              if a.low_won is not None and a.high_won is not None]
    if not priced:
        return None, None
    return sum(a.low_won for a in priced), sum(a.high_won for a in priced)


def target_crops(program: Program, profile: FarmProfile, crops: Iterable[Crop]) -> tuple[str, ...]:
    """이 제도가 겨냥하는 농가 작물 코드(crop_in·crop_not_in을 걸러 낸 것, 순서 유지). 줄이 제 작물의 판정을 고르는 데 쓴다."""
    return tuple(dict.fromkeys(pl.crop_code for pl in _target_plots(program, profile.crops, _groups(crops))))


def small_area_rate(program: Program) -> tuple[Decimal, int] | None:
    """amount_note의 "○ha 이하 ha당 ○만 원" → (ha, 원/ha). 면적직불: (2, 1,500,000). 없으면 None."""
    hit = _SMALL_AREA.search(program.amount_note or "")
    return None if hit is None else (Decimal(hit[1]), int(hit[2].replace(",", "")) * 10_000)


def _opened(m: MatchResult, before: MatchResult | None) -> bool:
    if m.status not in CANDIDATE:
        return False
    if before is None:
        return True
    return before.status not in CANDIDATE and not any(c.field in WAIT_FIELDS and c.result == "FAIL"
                                                      for c in before.conds)


def _lines(program: Program, m: MatchResult, profile: FarmProfile, groups: Mapping[str, frozenset[str]],
           market: _Market | None) -> tuple[AmountLine, ...]:
    note = CHECK_NOTE if m.status == "CHECK" else None
    kind = program.amount_type
    if kind == "정액":
        return (_fixed(program, m.source, profile, note),)
    if kind == "면적비례":
        one = _per_area(program, m.source, profile, groups, note)
        return () if one is None else (one,)
    if kind == "단위당":
        one = _per_unit(program, m.source, profile, groups, note)
        return () if one is None else (one,)
    if kind == "규칙":
        if program.rule_ref != "price_stab":
            return ()
        return _price_stab(program, profile, groups, market, note, already=m.status == "ALREADY",
                           fact_only=m.status == "BLOCKED_PREREQ")
    return (_undisclosed(program, m.source, note),)  # 보조율·kg당·없음


# --- 종류별 줄 --------------------------------------------------------------------------------

def _fixed(pr: Program, src: SourceRef, profile: FarmProfile, note: str | None) -> AmountLine:
    if profile.spouse == "registered" and pr.amount_2plus_each is not None:   # "2인 이상 경영체는 1인당 ○원"
        won: int | None = pr.amount_2plus_each * 2
        terms = (_term("1인당", pr.amount_2plus_each, "원", src), _term("인원", 2, "명", _input("spouse")))
    else:
        won = pr.amount_value
        terms = _terms(("금액", won, "원", src))
    return _line(pr, "FIXED", won, won, terms + _cap(pr, src), note)


def _per_area(pr: Program, src: SourceRef, profile: FarmProfile, groups: Mapping[str, frozenset[str]],
              note: str | None) -> AmountLine | None:
    lo_rate = pr.amount_min if pr.amount_min is not None else pr.amount_value
    hi_rate = pr.amount_max if pr.amount_max is not None else pr.amount_value
    basis, area = _area_m2(pr, profile, groups)
    small = small_area_rate(pr)
    if small is not None and area is not None and m2_to_ha(area) <= small[0]:
        lo_rate = small[1]
    terms = _terms(("ha당 하한", lo_rate, "원/ha", src), ("ha당 상한", hi_rate, "원/ha", src))
    if area is None or lo_rate is None or hi_rate is None:
        return _line(pr, "PER_AREA", None, None, terms + _cap(pr, src), note)
    if area == 0:
        return None                                  # 면적 0은 0원 줄이 아니라 줄 없음
    ha = m2_to_ha(area)
    return _line(pr, "PER_AREA", _won(lo_rate * ha, pr.cap_won), _won(hi_rate * ha, pr.cap_won),
                 terms + (_term("면적", ha, "ha", _input(basis)),) + _cap(pr, src), note)


def _per_unit(pr: Program, src: SourceRef, profile: FarmProfile, groups: Mapping[str, frozenset[str]],
              note: str | None) -> AmountLine | None:
    unit = pr.unit_name or "개"
    terms = _terms(("단가", pr.amount_value, f"원/{unit}", src), ("ha당 수량", pr.units_per_ha, unit, src),
                   ("수량 상한", pr.cap_units, unit, src))
    basis, area = _area_m2(pr, profile, groups)
    if area is None or pr.amount_value is None or pr.units_per_ha is None:
        return _line(pr, "PER_AREA", None, None, terms + _cap(pr, src), note)
    if area == 0:
        return None
    ha = m2_to_ha(area)
    units = (pr.units_per_ha * ha).quantize(Decimal(1), rounding=ROUND_DOWN)   # 비료 포대·상자는 낱개로
    if pr.cap_units is not None:
        units = min(units, Decimal(pr.cap_units))
    won = _won(units * pr.amount_value, pr.cap_won)
    terms += (_term("면적", ha, "ha", _input(basis)), _term("수량", units, unit, _CALC))
    return _line(pr, "PER_AREA", won, won, terms + _cap(pr, src), note)


def _undisclosed(pr: Program, src: SourceRef, note: str | None) -> AmountLine:
    terms = _terms(("kg당", pr.amount_value if pr.amount_type == "kg당" else None, "원/kg", src),
                   ("지원 비율 하한", pr.rate_pct_min, "%", src), ("지원 비율 상한", pr.rate_pct_max, "%", src))
    return _line(pr, "UNDISCLOSED", None, None, terms + _cap(pr, src), note)


# --- 가격안정관리제(§4-1) ---------------------------------------------------------------------

def _price_stab(pr: Program, profile: FarmProfile, groups: Mapping[str, frozenset[str]], market: _Market | None,
                note: str | None, *, already: bool = False, fact_only: bool = False) -> tuple[AmountLine, ...]:
    """대상 작물마다 줄. 신청 전(LIKELY·CHECK)은 그 작물의 MET·NEAR일 때만 두 줄, 이미 받는 행(already)은 판정과
    무관하게 지난 시즌 실적 줄 하나(앞면 지키실 돈). 계통 전환으로 막힌 행(fact_only)은 "작년 kg당 ○원" 사실 항만 가진
    총액 없는 줄 하나(금액은 붙이지 않는다 — 설계 §12-A(2): 사실 한 줄은 허용)."""
    plots = _target_plots(pr, profile.crops, groups)
    if market is None or not plots:
        return ()
    out: list[AmountLine] = []
    for crop in dict.fromkeys(pl.crop_code for pl in plots):     # 작물 코드 순서대로 한 번씩
        out.extend(_price_stab_crop(pr, crop, tuple(pl for pl in plots if pl.crop_code == crop), market, note, already,
                                    fact_only))
    return tuple(out)


def _price_stab_crop(pr: Program, crop: str, plots: tuple[CropPlot, ...], market: _Market, note: str | None,
                     already: bool, fact_only: bool = False) -> tuple[AmountLine, ...]:
    t = next((r for r in market.triggers.get(crop, ()) if r.rule_id == "PRICE_STAB"), None)
    params = season_params(market.bundle, crop, market.as_of)
    if fact_only:
        if params is None or params.stab_paid_avg is None:
            return ()
        paid = (_term("작년 kg당 평균", params.stab_paid_avg, "원/kg", params.sources["stab_paid_avg"]),)
        return (_line(pr, "REFERENCE_LAST_SEASON", None, None, paid, note, excluded=(NOT_FORECAST,),
                      conditional_on=(COOP_ONLY,) if pr.needs_coop == "Y" else (), crop_code=crop),)
    if params is None or (not already and (t is None or t.status not in SHOWN_STAB)):
        return ()
    near = t is not None and t.status == "NEAR" and not already
    note = " · ".join(n for n in (note, NEAR_NOTE if near else None) if n) or None
    tags = dict(excluded=(NOT_FORECAST,), conditional_on=(COOP_ONLY,) if pr.needs_coop == "Y" else (), crop_code=crop)
    lines: list[AmountLine] = []
    if not already and t is not None:
        kg = _kg_terms(t, params, season_value(market.bundle, crop, "stab_share", market.as_of))
        if kg:
            lines.append(_line(pr, "PER_KG_TRIGGER", None, None, kg, note, **tags))
    won, ref = _reference(plots, params, season_value(market.bundle, crop, "yield_kg_10a", market.as_of))
    if ref:
        lines.append(_line(pr, "REFERENCE_LAST_SEASON", won, won, ref, note, **tags))
    return tuple(lines)


def _kg_terms(t: TriggerResult, params: SeasonParams, share: tuple[str, SourceRef] | None) -> tuple[Term, ...]:
    """kg당 차액 = (기준가 − max(반월 평균, 하한가)) × 지급 비율, 0 아래로 안 감. 값이 하나라도 없으면 ()."""
    base, floor = params.stab_base, params.stab_floor
    if base is None or floor is None or share is None or t.observed is None:
        return ()
    rate = Decimal(share[0])
    diff = (max(base - max(t.observed, floor), Decimal(0)) * rate).quantize(TENTH, rounding=ROUND_HALF_UP)
    top = (max(base - floor, Decimal(0)) * rate).quantize(TENTH, rounding=ROUND_HALF_UP)
    return (_term("기준가", base, "원/kg", params.sources["stab_base"]),
            _term("하한가", floor, "원/kg", params.sources["stab_floor"]),
            _term("반월 평균", t.observed, "원/kg", t.sources[0] if t.sources else _CALC),
            _term("지급 비율", rate, "비율", share[1]),
            _term("kg당 차액", diff, "원/kg", _CALC),
            _term("kg당 최대", top, "원/kg", _CALC))


def _reference(plots: tuple[CropPlot, ...], params: SeasonParams,
               yld: tuple[str, SourceRef] | None) -> tuple[int | None, tuple[Term, ...]]:
    """(금액, 항): 지난 시즌 kg당 평균 × 예상 물량(면적 ÷ 10a × 10a당 수확량). 면적·수확량을 모르면 금액 None."""
    if params.stab_paid_avg is None:
        return None, ()
    paid = params.stab_paid_avg
    terms = (_term("작년 kg당 평균", paid, "원/kg", params.sources["stab_paid_avg"]),)
    areas = [pl.area_m2 for pl in plots]
    if yld is None or None in areas:
        return None, terms
    area = sum(a for a in areas if a is not None)
    if area == 0:
        return None, ()                              # 면적 0이면 줄 없음
    kg = (Decimal(area) / M2_PER_10A * Decimal(yld[0])).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return round_won(paid * kg), terms + (_term("면적", m2_to_ha(area), "ha", _input("crops.area_m2")),
                                          _term("10a당 수확량", Decimal(yld[0]), "kg/10a", yld[1]),
                                          _term("예상 물량", kg, "kg", _CALC))


# --- 면적 -------------------------------------------------------------------------------------

def _groups(crops: Iterable[Crop]) -> dict[str, frozenset[str]]:
    return {c.crop_code: frozenset(c.groups) for c in crops}


def _target_plots(pr: Program, plots: tuple[CropPlot, ...],
                  groups: Mapping[str, frozenset[str]]) -> tuple[CropPlot, ...]:
    """crop_in(코드 또는 그룹)에 들고 crop_not_in에 안 드는 작물. 표에 없는 작물은 그룹을 풀 수 없어 뺀다."""
    def member(code: str, tokens: tuple[str, ...]) -> bool:
        return code in tokens or bool(groups.get(code, frozenset()) & set(tokens))

    return tuple(pl for pl in plots if (not pr.crop_in or member(pl.crop_code, pr.crop_in))
                 and not (pr.crop_not_in and member(pl.crop_code, pr.crop_not_in)))


def _area_m2(pr: Program, profile: FarmProfile, groups: Mapping[str, frozenset[str]]) -> tuple[str, int | None]:
    """(면적 기준, ㎡). 모르면 ㎡ 자리가 None → 줄은 단가만 싣는다("면적 알려 주시면 계산")."""
    basis = _BASIS.get(pr.calc_basis or "", pr.area_basis or "경작")
    if basis == "해당작물":
        areas = [pl.area_m2 for pl in _target_plots(pr, profile.crops, groups)]
        return basis, (sum(a for a in areas if a is not None) if areas and None not in areas else None)
    if basis == "소유":                             # 소유 면적은 "전부 내 땅"일 때만 안다
        return basis, _cultivated(profile) if profile.land_tenure == "own_all" else None
    if basis == "경작":
        return basis, _cultivated(profile)
    return basis, None                               # 인증 면적은 입력에 없다


def _cultivated(profile: FarmProfile) -> int | None:
    if profile.total_area_m2 is not None:
        return profile.total_area_m2
    areas = [pl.area_m2 for pl in profile.crops]
    return None if None in areas else sum(a for a in areas if a is not None)


# --- 공통 -------------------------------------------------------------------------------------

def _won(raw: Decimal, cap: int | None) -> int:
    """계산 금액 → round_won. cap_won이 있으면 넘지 않게(걸리면 표 숫자 그대로)."""
    won = round_won(raw)
    return won if cap is None else min(won, cap)


def _term(label: str, value: Decimal | int, unit: str, source: SourceRef) -> Term:
    return Term(label=label, value=Decimal(value), unit=unit, source=source)


def _terms(*items: tuple[str, Decimal | int | None, str, SourceRef]) -> tuple[Term, ...]:
    """표 칸이 빈 항은 뺀다(0으로 찍지 않는다)."""
    return tuple(_term(label, value, unit, source) for label, value, unit, source in items if value is not None)


def _cap(pr: Program, src: SourceRef) -> tuple[Term, ...]:
    return _terms(("최대", pr.cap_won, "원", src))


def _input(field: str) -> SourceRef:
    return SourceRef(source_id=f"input:{field}", url=None, as_of=None)


def _line(pr: Program, kind: str, low: int | None, high: int | None, terms: tuple[Term, ...], note: str | None, *,
          excluded: tuple[str, ...] = (), conditional_on: tuple[str, ...] = (), crop_code: str | None = None) -> AmountLine:
    return AmountLine(program_id=pr.id, kind=kind, low_won=low, high_won=high, terms=terms, excluded=excluded,
                      conditional_on=conditional_on, pay_timing=pr.payout_timing, check_note=note, period=pr.period,
                      crop_code=crop_code)
