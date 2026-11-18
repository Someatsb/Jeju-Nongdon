"""매칭 2(Task 10, U10): 표 행끼리 보는 규칙. match_supports가 행마다 판정한 뒤에 이 순서로 건다.

1. 이미 받음: program_key ∈ already_receiving → ALREADY. 같은 program_key가 작물·지역별 여러 행이면
   농가의 작물·지역에 맞는 행에만 붙인다(crop_in·crop_not_in·area_type_in·region_in 칸이 FAIL이면 그대로).
   기간이 끝난 행(OUT_OF_VALIDITY)도 그대로 둔다. renew_annual은 ALREADY가 된 매년신청 행에만 단다(E' 줄).
2. 택1(excludes): 후보(LIKELY·CHECK)인 행만 바뀐다. 짝이 되는 행을
   - 이미 받고 있으면 → EXCLUSIVE_OTHER(받는 쪽을 남김. round2-M 골든 P5, 차액은 종이 문구가 적는다)
   - 소농 vs 면적직불이 둘 다 후보면 → 금액이 큰 쪽을 남기고 작은 쪽이 EXCLUSIVE_OTHER.
     면적을 몰라 못 가르면 둘 다 CHECK로 두고 "택1 비교 보류" 칸을 단다.
   - 그 밖의 쌍(재해보험 vs 수입안정보험)이 둘 다 후보면 → 둘 다 둔다(어르신이 고름, round2-L §3-4).
   작물별 행끼리는 같은 작물만 짝이다(schema.json excludes).
"""
from collections.abc import Callable, Iterable, Mapping
from typing import Literal

from app.core.models import CondCheck, MatchResult, Program
from app.core.units import HA_M2

SMALL_DIRECT, AREA_DIRECT = "NAT-DIRECT-SMALL", "NAT-DIRECT-AREA"
# 택1 비교용 면적직불 단가: 진흥지역 밖 밭 2ha 이하 ha당 150만 원(면적직불 행 amount_note). 제주 밭이 대부분
# 이 칸이고, 소농직불 max_ha 0.86(= 130만 ÷ 150만)도 같은 기준이다. 금액 전체 계산은 Task 14가 한다.
AREA_DIRECT_WON_PER_HA = 1_500_000
UNDECIDED_NOTE = "택1 비교 보류"

_CANDIDATE = frozenset({"LIKELY", "CHECK"})
_VARIANT_FIELDS = frozenset({"crop_in", "crop_not_in", "area_type_in", "region_in"})

Verdict = Literal["KEEP", "LOSE", "UNDECIDED"]
AreaOf = Callable[[Program], tuple[int, int]]   # 행의 area_basis로 본 농가 면적 범위(㎡, 가장 적게·가장 많이)


def apply_already(results: tuple[MatchResult, ...], programs: Iterable[Program],
                  already_receiving: frozenset[str]) -> tuple[MatchResult, ...]:
    renew_type = {p.id: p.renew_type for p in programs}
    return tuple(_with(m, status="ALREADY", renew_annual=renew_type[m.program_id] == "매년신청")
                 if _receiving(m, already_receiving) else m for m in results)


def _receiving(m: MatchResult, already_receiving: frozenset[str]) -> bool:
    return (m.program_key in already_receiving and m.status != "OUT_OF_VALIDITY"
            and not any(c.field in _VARIANT_FIELDS and c.result == "FAIL" for c in m.conds))


def apply_excludes(results: tuple[MatchResult, ...], programs: Iterable[Program],
                   area_of: AreaOf) -> tuple[MatchResult, ...]:
    """짝의 상태는 바꾸기 전 것으로 본다. area_of는 match.py가 넘긴다(소농 행 area_basis로 면적을 잼)."""
    by_id = {p.id: p for p in programs}
    return tuple(_exclusive(m, results, by_id, area_of) for m in results)


def _exclusive(m: MatchResult, results: tuple[MatchResult, ...], by_id: Mapping[str, Program],
               area_of: AreaOf) -> MatchResult:
    if m.status not in _CANDIDATE:
        return m
    pr = by_id[m.program_id]
    verdicts = [(_versus(pr, by_id[o.program_id], o.status, area_of), o.program_key)
                for o in results if _paired(pr, by_id[o.program_id])]
    if any(v == "LOSE" for v, _ in verdicts):
        return _with(m, status="EXCLUSIVE_OTHER")
    undecided = sorted({key for v, key in verdicts if v == "UNDECIDED"})
    if not undecided:
        return m
    note = CondCheck(field="excludes", required=";".join(undecided), actual=UNDECIDED_NOTE, result="UNKNOWN",
                     prereq=False)
    return _with(m, status="CHECK", conds=m.conds + (note,), unknown_fields=m.unknown_fields + ("excludes",))


def _paired(a: Program, b: Program) -> bool:
    if a.program_key == b.program_key or (b.program_key not in a.excludes and a.program_key not in b.excludes):
        return False
    return not (a.crop_in and b.crop_in) or bool(set(a.crop_in) & set(b.crop_in))


def _versus(pr: Program, rival: Program, rival_status: str, area_of: AreaOf) -> Verdict:
    if rival_status == "ALREADY":
        return "LOSE"
    if rival_status not in _CANDIDATE or {pr.program_key, rival.program_key} != {SMALL_DIRECT, AREA_DIRECT}:
        return "KEEP"   # 짝이 후보가 아님 / 직불 아닌 쌍은 둘 다 후보여도 어르신이 고른다
    small = pr if pr.program_key == SMALL_DIRECT else rival
    keeper = _direct_keeper(small, area_of(small))
    if keeper is None:
        return "UNDECIDED"
    if keeper == pr.program_key:
        return "KEEP"
    return "LOSE"


def _direct_keeper(small: Program, area_m2: tuple[int, int]) -> str | None:
    """소농 vs 면적직불 중 금액이 큰 쪽. 면적직불 = 면적(소농 행 area_basis) × 150만 원/ha가 소농 금액보다 적으면 소농."""
    if small.amount_value is None:
        return None
    lo, hi = area_m2
    target = small.amount_value * HA_M2           # 원 × (㎡/ha): 나눗셈 없이 ㎡ × 원/ha와 견준다
    if hi * AREA_DIRECT_WON_PER_HA < target:
        return SMALL_DIRECT
    if lo * AREA_DIRECT_WON_PER_HA >= target:
        return AREA_DIRECT
    return None


def _with(m: MatchResult, **update: object) -> MatchResult:
    return MatchResult.model_validate({**dict(m), **update})  # frozen: 고친 새 결과(상태 값도 검사)
