"""발동 판정(Task 13, U13). 도매가격으로 시장 연동 제도의 '조건 성립' 상태만 정한다. 전망은 하지 않는다.

PRICE_STAB(가격안정관리제): 기준일이 든 반월(1~15일, 16일~말일)의 1361 averagePrice를 1361 거래량으로 가중한
  평균(기준일까지의 점만, 0.1원 반올림). 품종은 그 작물의 판정 품종(crops.csv judge_cultivars → 시리즈 judge=True)을
  모두 합친다. 대상 달은 stab_months, 그 행이 없으면 crops.csv season_months로 대신한다. 확인 순서:
    기준가 행에 값은 있으나 등급이 추정·미확인(브로콜리) → NO_DATA, note "기준가 미확인"
    → 기준가 행이 없거나 값이 빈 행(노지감귤 2026-27)·판정 정의(stab_price_basis)가 1361 반월가중이 아님 → NOT_APPLICABLE
    → 기준일 달이 stab_months 밖 → OUT_OF_SEASON(window = 다음에 판정할 반월, "12월부터")
    → 1361 마지막 날에서 15일 이상 → STALE(진행 중 반월 판정 생략, 평균을 내보내지 않음)
    → 거래일 < min_days → NO_DATA
    → 평균 < 기준가 × 0.911 → MET, ≥ 기준가 × 1.143 → NOT_MET, 사이 → NEAR("근처 — 농협 확인").
  거래일이 min_days 이상 5일 미만이면 provisional=True("잠정(거래 n일)"). threshold는 기준가다.
LOGISTICS(물류비): 양배추·월동무만, 그 밖 작물은 NOT_APPLICABLE(당근·양파 판정 끔). 기준일 달의 거래량 가중
  월평균(기준일까지). 손익분기는 원문에 없어 역산 구간 (breakeven_lo, breakeven_hi]만 안다:
  ≤ lo → MET_ESTIMATED("추정 조건"), 구간 안 → NEAR, > hi → NOT_MET. threshold는 breakeven_hi.
  시즌은 crops.csv season_months(월동무 11월은 OUT_OF_SEASON, "12월부터"). 나머지 순서는 PRICE_STAB과 같다.
ISOLATION_HISTORY(수매·격리 이력): 월동무·당근·양배추만, 다른 작물은 결과 자체가 없다. 기준일 시즌보다 앞선
  시즌 중 확인·보도1건 행이 있는 시즌 n개, 그중 개입(type ≠ 없음)이 있던 시즌 m개 → history_hits=(m, n).
  추정·미확인 행은 세지 않는다(round2-I REQ-STAT-1 "출처 있는 행만"). 사실 문장용이다: m ≥ 1 MET, m = 0 NOT_MET,
  n = 0 NO_DATA.

스냅샷은 as_of로 자른 것이어야 한다(자료 마지막 날이 as_of 뒤면 staleness_days가 ValueError).
"""
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.calendar import half_month
from app.core.models import SourceRef, TriggerResult
from app.core.params_view import SeasonParams, season_of
from app.core.snapshot_models import PriceSeries, Snapshot, freshness, staleness_days
from app.core.tables_models import Intervention

PRICE_BASIS = "1361_averagePrice_반월가중"   # params stab_price_basis. 869 경계 배수가 이 정의로 보정됐다
LOGISTICS_METRIC = "1361_averagePrice_월가중"
ISOLATION_METRIC = "seasons_with_intervention"
LOGISTICS_CROPS = frozenset({"양배추", "월동무"})
ISOLATION_CROPS = frozenset({"월동무", "당근", "양배추"})
FULL_DAYS = 5                                  # 거래일이 이보다 적으면 잠정
SOURCED = frozenset({"확인", "보도1건"})        # interventions.confirmed 중 셀 수 있는 값
TENTH = Decimal("0.1")

Window = tuple[date, date]


def _result(rule_id: str, status: str, metric: str, *, observed: Decimal | None = None, threshold: Decimal | None = None,
            window: Window | None = None, n_days: int = 0, data_as_of: date | None = None, staleness: int | None = None,
            provisional: bool = False, history_hits: tuple[int, int] | None = None,
            sources: tuple[SourceRef, ...] = (), note: str | None = None) -> TriggerResult:
    return TriggerResult(rule_id=rule_id, status=status, provisional=provisional, metric=metric, observed=observed,
                         threshold=threshold, window=window, n_days_with_data=n_days, data_as_of=data_as_of,
                         staleness_days=staleness, history_hits=history_hits, sources=sources, note=note)


def _month(d: date) -> Window:
    return d.replace(day=1), half_month(d.replace(day=16))[1]


def _next_in_season(as_of: date, months: tuple[int, ...]) -> date | None:
    """as_of 달 다음부터 처음 오는 판정 달의 1일."""
    for k in range(1, 13):
        y, m0 = divmod(as_of.month - 1 + k, 12)
        if m0 + 1 in months:
            return date(as_of.year + y, m0 + 1, 1)
    return None


def _wavg(series: list[PriceSeries], start: date, end: date) -> tuple[Decimal | None, int]:
    """start~end(양끝 포함) 점의 거래량 가중 평균(0.1원 반올림)과 거래일 수."""
    pts = [p for s in series for p in s.points if start <= p.day <= end]
    if not pts:
        return None, 0
    avg = sum(p.won_per_kg * p.volume_kg for p in pts) / sum(p.volume_kg for p in pts)
    return avg.quantize(TENTH, rounding=ROUND_HALF_UP), len({p.day for p in pts})


def _price_rule(rule_id: str, metric: str, threshold: Decimal, months: tuple[int, ...],
                window_of: Callable[[date], Window], classify: Callable[[Decimal], str], series: list[PriceSeries],
                param_sources: tuple[SourceRef, ...], as_of: date, min_days: int) -> TriggerResult:
    """PRICE_STAB·LOGISTICS 공통: OUT_OF_SEASON → STALE → NO_DATA → classify(평균)."""
    if as_of.month not in months:
        nxt = _next_in_season(as_of, months)
        return _result(rule_id, "OUT_OF_SEASON", metric, window=window_of(nxt) if nxt else None)
    window = window_of(as_of)
    data_as_of = max((s.source.as_of for s in series), default=None)
    if data_as_of is None:
        return _result(rule_id, "NO_DATA", metric, threshold=threshold, window=window, sources=param_sources)
    common = dict(threshold=threshold, window=window, data_as_of=data_as_of, staleness=staleness_days(as_of, data_as_of),
                  sources=tuple(dict.fromkeys(s.source for s in series)) + param_sources)
    observed, n = _wavg(series, window[0], min(window[1], as_of))
    if freshness(as_of, data_as_of) == "stale":
        return _result(rule_id, "STALE", metric, n_days=n, **common)
    if n < min_days:
        return _result(rule_id, "NO_DATA", metric, n_days=n, **common)
    return _result(rule_id, classify(observed), metric, observed=observed, n_days=n, provisional=n < FULL_DAYS, **common)


def _sources(params: SeasonParams, *names: str) -> tuple[SourceRef, ...]:
    return tuple(params.sources[n] for n in names if n in params.sources)


def _price_stab(params: SeasonParams | None, series: list[PriceSeries], as_of: date, min_days: int) -> TriggerResult:
    if params is not None and params.stab_base is None and params.base_unconfirmed:
        return _result("PRICE_STAB", "NO_DATA", PRICE_BASIS, note="기준가 미확인")
    if params is None or params.stab_base is None or params.stab_price_basis != PRICE_BASIS:
        return _result("PRICE_STAB", "NOT_APPLICABLE", PRICE_BASIS)
    base = params.stab_base
    below, above = base * params.stab_band_lo, base * params.stab_band_hi

    def classify(avg: Decimal) -> str:
        return "MET" if avg < below else "NOT_MET" if avg >= above else "NEAR"

    return _price_rule("PRICE_STAB", PRICE_BASIS, base, params.stab_months or params.season_months, half_month,
                       classify, series, _sources(params, "stab_base", "stab_band_lo", "stab_band_hi"), as_of, min_days)


def _logistics(crop_code: str, params: SeasonParams | None, series: list[PriceSeries], as_of: date,
               min_days: int) -> TriggerResult:
    if crop_code not in LOGISTICS_CROPS or params is None or params.breakeven_lo is None or params.breakeven_hi is None:
        return _result("LOGISTICS", "NOT_APPLICABLE", LOGISTICS_METRIC)
    lo, hi = params.breakeven_lo, params.breakeven_hi

    def classify(avg: Decimal) -> str:
        return "MET_ESTIMATED" if avg <= lo else "NOT_MET" if avg > hi else "NEAR"

    return _price_rule("LOGISTICS", LOGISTICS_METRIC, hi, params.season_months, _month, classify, series,
                       _sources(params, "breakeven_lo", "breakeven_hi"), as_of, min_days)


def _before(season: str, as_of: date) -> bool:
    """season이 기준일 시즌보다 앞선 시즌인지. 라벨 앞 네 자리(첫 해)로 비교한다."""
    return season[:4].isdigit() and int(season[:4]) < int(season_of(as_of)[:4])


def _isolation(crop_code: str, history: tuple[Intervention, ...], as_of: date) -> TriggerResult:
    rows = sorted((h for h in history if h.crop == crop_code and h.confirmed in SOURCED and _before(h.season, as_of)),
                  key=lambda h: (h.season, h.type))
    seasons = {h.season for h in rows}
    if not seasons:
        return _result("ISOLATION_HISTORY", "NO_DATA", ISOLATION_METRIC)
    m = len({h.season for h in rows if h.type != "없음"})
    sources = tuple(dict.fromkeys(SourceRef(source_id=f"interventions:{h.season}:{h.crop}:{h.type}", url=h.source_url,
                                            as_of=h.verified_date) for h in rows))
    return _result("ISOLATION_HISTORY", "MET" if m else "NOT_MET", ISOLATION_METRIC, history_hits=(m, len(seasons)),
                   sources=sources)


def check_triggers(crop_code: str, snap: Snapshot, params: SeasonParams | None, history: tuple[Intervention, ...],
                   as_of: date, min_days: int = 3) -> tuple[TriggerResult, ...]:
    """(PRICE_STAB, LOGISTICS[, ISOLATION_HISTORY]) 순서. ISOLATION_HISTORY는 월동무·당근·양배추에만 있다."""
    if params is not None and params.crop != crop_code:
        raise ValueError(f"{crop_code} 판정에 {params.crop} 판정 값을 넘겼습니다.")
    if params is not None and params.season != season_of(as_of):
        raise ValueError(f"기준일 {as_of}은 {season_of(as_of)} 시즌인데 {params.season} 시즌 판정 값을 넘겼습니다.")
    series = [s for s in snap.prices.values() if s.crop_code == crop_code and s.judge]
    results = (_price_stab(params, series, as_of, min_days), _logistics(crop_code, params, series, as_of, min_days))
    if crop_code in ISOLATION_CROPS:
        results += (_isolation(crop_code, history, as_of),)
    return tuple(r.model_copy(update={"crop_code": crop_code}) for r in results)
