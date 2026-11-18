"""Task 15 테스트용 FactSheet 조립기. 판정(match·insurance·actions)은 코어를 돌리고, 금액·트리거만 손으로 붙인다.

트리거 모듈(Task 13)·금액 모듈(Task 14)은 이 레인에 없으므로 결과 모델(TriggerResult·AmountLine)만 쓴다.
"""
from datetime import date

from app.core.actions import next_actions
from app.core.insurance import check_insurance
from app.core.match import match_supports
from app.core.models import AmountLine, FactSheet, FarmProfile, Header, SourceRef, TriggerResult

SRC = SourceRef(source_id="test", url=None, as_of=date(2026, 11, 7))


def amount(program_id: str, low: int | None, high: int | None, *, kind: str = "FIXED", check: bool = False) -> AmountLine:
    return AmountLine(program_id=program_id, kind=kind, low_won=low, high_won=high, terms=(), excluded=(),
                      conditional_on=(), pay_timing=None, check_note="확인할 조건 있음" if check else None)


def trigger(rule_id: str, status: str) -> TriggerResult:
    return TriggerResult(rule_id=rule_id, status=status, provisional=False, metric="test", observed=None,
                         threshold=None, window=None, n_days_with_data=0, data_as_of=None, staleness_days=None,
                         history_hits=None, sources=())


def make_fs(kwargs: dict, bundle, as_of: date, *, amounts=(), triggers=(), matches=None, profile=None) -> FactSheet:
    profile = profile or FarmProfile(**kwargs)
    matches = matches if matches is not None else match_supports(profile, bundle.programs, as_of, crops=bundle.crops)
    insurance = check_insurance(profile, bundle.insurance, as_of)
    actions = next_actions(profile, bundle, matches, insurance, tuple(amounts), tuple(triggers), as_of)
    header = Header(price_as_of=None, citrus_as_of=None, tables_verified=bundle.verified_date,
                    snapshot_built=date(2026, 11, 12), refresh_ok=None, demo_asof=True)
    return FactSheet(profile=profile, matches=matches, triggers=tuple(triggers), amounts=tuple(amounts),
                     insurance=insurance, actions=actions, facts=(), header=header, as_of=as_of, data_version="test")
