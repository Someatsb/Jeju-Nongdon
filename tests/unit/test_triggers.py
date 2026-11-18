"""Task 13(U13) 발동 판정: 가격안정관리제(반월)·물류비(월)·수매·격리 이력.

플랜의 작물 자리표시자는 crops.csv 코드로 바꿨다: carrot → 당근, cabbage → 양배추,
onion_early → 양파(crops.csv에 조생양파 코드가 따로 없고 양파 한 줄이 조생·저장양파 품종을 가짐),
citrus_open → 감귤_노지. snap_half(end)는 배포 스냅샷을 반월 끝날로 자른 것이다.
"""
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

import pytest

from app.core.calendar import half_month
from app.core.models import SourceRef, TriggerResult
from app.core.params_view import SeasonParams, season_params
from app.core.snapshot_models import PricePoint, PriceSeries, Snapshot
from app.core.tables_models import TableBundle
from app.core.triggers import check_triggers
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from conftest import AS_OF, ROOT


@lru_cache(maxsize=None)
def bundle() -> TableBundle:
    return load_tables(ROOT / "data" / "tables", AS_OF)


@lru_cache(maxsize=None)
def snap_half(end: date) -> Snapshot:
    return load_snapshot(ROOT / "data" / "snapshot", end, crops=bundle().crops)


def _half_ends(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        end = half_month(d)[1]
        out.append(end)
        d = end + timedelta(days=1)
    return out


HALF_ENDS_CARROT = _half_ends(date(2025, 11, 1), date(2026, 3, 31))   # 2025-26 당근 stab_months 11~3월, 반월 10개
SNAP_1113 = snap_half(AS_OF)
SNAP_0315 = snap_half(date(2026, 3, 15))
CARROT_PARAMS = season_params(bundle(), "당근", AS_OF)
CARROT_PARAMS_2526 = season_params(bundle(), "당근", date(2026, 3, 15))   # 2025-26 시즌 보기(검증표 반월 10개)
CABBAGE_PARAMS = season_params(bundle(), "양배추", AS_OF)
ONION_PARAMS = season_params(bundle(), "양파", date(2026, 3, 15))
HIST = bundle().interventions


def rule(results: tuple[TriggerResult, ...], rule_id: str) -> TriggerResult:
    return next(t for t in results if t.rule_id == rule_id)


# --- 플랜 Step 1 테스트 ------------------------------------------------------------------

def test_provisional_3_days():
    r = check_triggers("당근", SNAP_1113, CARROT_PARAMS, HIST, date(2026, 11, 13))[0]
    assert r.n_days_with_data == 3 and r.provisional


def test_out_of_season_status():
    assert check_triggers("양배추", SNAP_1113, CABBAGE_PARAMS, HIST, date(2026, 11, 13))[0].status == "OUT_OF_SEASON"


def test_onion_logistics_not_applicable():
    assert [t.status for t in check_triggers("양파", SNAP_0315, ONION_PARAMS, HIST, date(2026, 3, 15))
            if t.rule_id == "LOGISTICS"] == ["NOT_APPLICABLE"]


def test_citrus_no_isolation_rule():
    assert all(t.rule_id != "ISOLATION_HISTORY" for t in check_triggers("감귤_노지", SNAP_1113, None, HIST, AS_OF))


# --- 검증표 원문 그대로 ----------------------------------------------------------------------

def test_b_validation_table_carrot():
    # round2-B §3: 1361 판정 '아래' 2개(11월 두 반월, 가락도 아래) + '근처' 8개(가락 아래 7·가락 위 1), '위' 0개.
    res = [check_triggers("당근", snap_half(end), CARROT_PARAMS_2526, HIST, end)[0] for end in HALF_ENDS_CARROT]
    assert [r.status for r in res] == ["MET", "MET"] + ["NEAR"] * 8
    assert all(not r.provisional and r.n_days_with_data >= 9 for r in res)
    assert [r.window for r in res[:2]] == [(date(2025, 11, 1), date(2025, 11, 15)), (date(2025, 11, 16), date(2025, 11, 30))]


# --- 가격안정관리제 -------------------------------------------------------------------------

def test_carrot_1113_above_base_is_not_met_with_base_as_threshold():
    # 골든 P2·T2: 11.1~11.15 반월, 11-05까지 2,000원대 → '아직'. 기준가는 2025-26 값 1,088원.
    r = check_triggers("당근", SNAP_1113, CARROT_PARAMS, HIST, AS_OF)[0]
    assert (r.rule_id, r.status, r.threshold) == ("PRICE_STAB", "NOT_MET", Decimal(1088))
    assert r.window == (date(2026, 11, 1), date(2026, 11, 15)) and r.data_as_of == date(2026, 11, 5)
    assert r.staleness_days == 8 and r.observed > Decimal(1249)
    assert r.metric == "1361_averagePrice_반월가중"
    assert [s.source_id for s in r.sources] == ["hub1361"] + [f"params:2025-26:당근:{n}" for n in ("stab_base", "stab_band_lo", "stab_band_hi")]


def test_fewer_than_min_days_is_no_data():
    r = check_triggers("당근", snap_half(date(2026, 11, 3)), CARROT_PARAMS, HIST, date(2026, 11, 3))[0]
    assert (r.status, r.n_days_with_data, r.observed, r.provisional) == ("NO_DATA", 1, None, False)
    r1 = check_triggers("당근", snap_half(date(2026, 11, 3)), CARROT_PARAMS, HIST, date(2026, 11, 3), min_days=1)[0]
    assert r1.status == "NOT_MET" and r1.provisional


def test_stale_15_days_hides_current_half_month():
    # Task 12 test_stale_15_days_hides_current_half_month의 트리거 쪽 단언: 1361 마지막 날 11-05에서 15일.
    r = check_triggers("당근", snap_half(date(2026, 11, 20)), CARROT_PARAMS, HIST, date(2026, 11, 20))[0]
    assert (r.status, r.staleness_days, r.observed, r.provisional) == ("STALE", 15, None, False)
    aged = check_triggers("당근", snap_half(date(2026, 11, 19)), CARROT_PARAMS, HIST, date(2026, 11, 19))[0]
    assert (aged.status, aged.staleness_days) == ("NO_DATA", 14)   # 14일은 aged: 판정은 하되 16~19일 거래가 없음


def test_no_base_is_not_applicable_before_season_check():
    # 기준가 행이 없거나 값이 빈 노지감귤 → NOT_APPLICABLE. 7월(시즌 밖)이어도 먼저 걸린다.
    r = check_triggers("감귤_노지", SNAP_1113, season_params(bundle(), "감귤_노지", AS_OF), HIST, AS_OF)[0]
    assert (r.rule_id, r.status, r.window, r.sources, r.note) == ("PRICE_STAB", "NOT_APPLICABLE", None, (), None)
    assert check_triggers("감귤_노지", snap_half(date(2026, 7, 10)), None, HIST, date(2026, 7, 10))[0].status == "NOT_APPLICABLE"


def test_out_of_season_points_to_next_judged_window():
    # 골든 B01·B07 "12월부터": 시즌 밖이면 window가 다음에 판정할 반월(물류비는 달)이고 숫자는 없다.
    cab = check_triggers("양배추", SNAP_1113, CABBAGE_PARAMS, HIST, AS_OF)[0]
    assert (cab.window, cab.observed, cab.threshold) == ((date(2026, 12, 1), date(2026, 12, 15)), None, None)
    radish = rule(check_triggers("월동무", SNAP_1113, season_params(bundle(), "월동무", AS_OF), HIST, AS_OF), "LOGISTICS")
    assert (radish.window, radish.threshold) == ((date(2026, 12, 1), date(2026, 12, 31)), None)
    carrot_july = check_triggers("당근", snap_half(date(2026, 7, 10)), CARROT_PARAMS, HIST, date(2026, 7, 10))[0]
    assert carrot_july.window == (date(2026, 11, 1), date(2026, 11, 15))


def test_out_of_season_checked_before_stale():
    assert check_triggers("양배추", snap_half(date(2026, 11, 20)), CABBAGE_PARAMS, HIST, date(2026, 11, 20))[0].status == "OUT_OF_SEASON"


# 합성 스냅샷: 기준가 1,000원이면 경계가 911.0·1,143.0원으로 딱 떨어진다.
P1000 = SeasonParams(crop="당근", season="2025-26", stab_base=Decimal(1000), stab_months=(11, 12, 1, 2, 3),
                     stab_price_basis="1361_averagePrice_반월가중")


def synth(*series: tuple[str, bool, list[tuple[date, str, str]]], crop: str = "당근", last: date | None = None) -> Snapshot:
    last = last or max(d for _, _, pts in series for d, _, _ in pts)
    src = SourceRef(source_id="hub1361", url=None, as_of=last)
    prices = {cv: PriceSeries(crop_code=crop, cultivars=(cv,), judge=judge, market_scope="전국",
                              points=tuple(PricePoint(d, Decimal(p), Decimal(v)) for d, p, v in pts), source=src)
              for cv, judge, pts in series}
    return Snapshot(prices=prices, citrus=None, area={}, ratio_bounds={}, built_at=last, price_as_of=last, citrus_as_of=None)


def days(start: date, prices: list[str], vol: str = "1000") -> list[tuple[date, str, str]]:
    return [(start + timedelta(days=i), p, vol) for i, p in enumerate(prices)]


@pytest.mark.parametrize("price, status", [("910.9", "MET"), ("911.0", "NEAR"), ("1142.9", "NEAR"), ("1143.0", "NOT_MET")])
def test_band_edges(price, status):
    s = synth(("당근(일반)", True, days(date(2025, 12, 1), [price] * 5)))
    r = check_triggers("당근", s, P1000, (), date(2025, 12, 5))[0]
    assert (r.status, r.observed, r.n_days_with_data, r.provisional) == (status, Decimal(price), 5, False)


def test_half_month_mean_is_volume_weighted_over_judge_series_only():
    # 당근(일반) 600원×3,000kg + 1,200원×1,000kg×4일, 세척당근 800원×1,000kg×3일(같은 날들).
    # 거래량 가중: (1.8M + 4.8M + 2.4M) / 10,000kg = 900(아래). 세척당근을 빼면 942.9, 행 단순평균이면 975(둘 다 근처).
    judge = [(date(2025, 12, 16), "600", "3000")] + days(date(2025, 12, 17), ["1200"] * 4)
    washed = days(date(2025, 12, 16), ["800"] * 3)                      # 같은 작물의 다른 판정 품종도 합친다
    dist_only = days(date(2025, 12, 16), ["100"] * 5, vol="999999")    # 판정 품종이 아닌 시리즈는 뺀다
    before = days(date(2025, 12, 10), ["5"] * 3)                         # 앞 반월 점은 뺀다
    s = synth(("당근(일반)", True, before + judge), ("세척당근", True, washed), ("흙당근", False, dist_only))
    r = check_triggers("당근", s, P1000, (), date(2025, 12, 20))[0]
    assert r.observed == Decimal("900.0") and r.n_days_with_data == 5 and r.status == "MET"
    assert r.window == (date(2025, 12, 16), date(2025, 12, 31))


def test_points_after_as_of_ignored():
    s = synth(("당근(일반)", True, days(date(2025, 12, 1), ["1000"] * 4) + [(date(2025, 12, 9), "1", "1000000")]),
              last=date(2025, 12, 8))
    r = check_triggers("당근", s, P1000, (), date(2025, 12, 8))[0]
    assert r.observed == Decimal("1000.0") and r.n_days_with_data == 4 and r.provisional


@pytest.mark.parametrize("basis", ["1362_가락", None])
def test_price_basis_other_than_1361_half_month_not_judged(basis):
    # 경계 배수 0.911·1.143은 1361 반월가중 정의로 보정됐다. 다른 정의(또는 정의 없음)면 판정하지 않는다.
    p = SeasonParams(crop="당근", season="2025-26", stab_base=Decimal(1000), stab_months=(12,), stab_price_basis=basis)
    s = synth(("당근(일반)", True, days(date(2025, 12, 1), ["500"] * 5)))
    assert check_triggers("당근", s, p, (), date(2025, 12, 5))[0].status == "NOT_APPLICABLE"


def test_params_for_another_crop_rejected():
    with pytest.raises(ValueError):
        check_triggers("양배추", SNAP_1113, CARROT_PARAMS, HIST, AS_OF)


def test_no_price_dataset_is_no_data():
    s = Snapshot(prices={}, citrus=None, area={}, ratio_bounds={}, built_at=AS_OF, price_as_of=None, citrus_as_of=None,
                 damaged={"hub_1361": "sha256이 다릅니다."})
    r = check_triggers("당근", s, CARROT_PARAMS, HIST, AS_OF)[0]
    assert (r.status, r.data_as_of, r.staleness_days, r.n_days_with_data) == ("NO_DATA", None, None, 0)


# --- 물류비 ---------------------------------------------------------------------------------

def test_logistics_off_for_carrot_and_out_of_season_for_radish_in_november():
    # 골든 T2·B12: 당근 물류비 판정 끔. 골든 B07: 월동무 11월은 '12월부터'(crops.csv season_months).
    assert rule(check_triggers("당근", SNAP_1113, CARROT_PARAMS, HIST, AS_OF), "LOGISTICS").status == "NOT_APPLICABLE"
    radish = rule(check_triggers("월동무", SNAP_1113, season_params(bundle(), "월동무", AS_OF), HIST, AS_OF), "LOGISTICS")
    assert radish.status == "OUT_OF_SEASON"
    assert rule(check_triggers("감귤_노지", SNAP_1113, None, HIST, AS_OF), "LOGISTICS").status == "NOT_APPLICABLE"


@pytest.mark.parametrize("price, status", [("648.0", "MET_ESTIMATED"), ("648.1", "NEAR"), ("795.0", "NEAR"), ("795.1", "NOT_MET")])
def test_cabbage_logistics_month_mean_against_breakeven_interval(price, status):
    # 손익분기 역산 구간 (648, 795]: 이하면 추정 조건 성립, 구간 안이면 근처(농협 확인), 위면 아님.
    params = season_params(bundle(), "양배추", date(2026, 1, 20))
    half1 = days(date(2026, 1, 2), [price] * 3, vol="500")
    half2 = days(date(2026, 1, 16), [price] * 3, vol="700")
    s = synth(("양배추(일반)", True, half1 + half2), crop="양배추")
    r = rule(check_triggers("양배추", s, params, (), date(2026, 1, 20)), "LOGISTICS")
    assert (r.status, r.observed, r.n_days_with_data, r.provisional) == (status, Decimal(price), 6, False)
    assert r.window == (date(2026, 1, 1), date(2026, 1, 31)) and r.threshold == Decimal(795)


def test_logistics_needs_min_days_in_month():
    params = season_params(bundle(), "월동무", date(2026, 1, 20))
    s = synth(("월동무", True, days(date(2026, 1, 2), ["500"] * 2)), crop="월동무")
    r = rule(check_triggers("월동무", s, params, (), date(2026, 1, 5)), "LOGISTICS")
    assert (r.status, r.n_days_with_data) == ("NO_DATA", 2)


# --- 수매·격리 이력 -------------------------------------------------------------------------

def test_isolation_history_counts_confirmed_past_seasons():
    # 확인·보도1건 행이 있는 지난 시즌만 센다(추정·미확인 행은 n에도 m에도 넣지 않음).
    # 월동무: 2017-18·2020-21·2023-24·2025-26 개입, 2024-25 없음 → 5번 중 4번.
    expected = {"월동무": (4, 5), "양배추": (2, 3), "당근": (1, 2)}
    for crop, hits in expected.items():
        r = rule(check_triggers(crop, SNAP_1113, season_params(bundle(), crop, AS_OF), HIST, AS_OF), "ISOLATION_HISTORY")
        assert (r.status, r.history_hits) == ("MET", hits)
        assert r.sources and all(s.source_id.startswith("interventions:") for s in r.sources)


def test_isolation_history_ignores_current_season():
    # 2026-03-15는 2025-26 시즌 중 → 지난 시즌은 2024-25(없음)뿐.
    r = rule(check_triggers("당근", SNAP_0315, season_params(bundle(), "당근", date(2026, 3, 15)), HIST, date(2026, 3, 15)),
             "ISOLATION_HISTORY")
    assert (r.status, r.history_hits) == ("NOT_MET", (0, 1))


def test_isolation_history_without_records_is_no_data():
    r = rule(check_triggers("당근", SNAP_1113, CARROT_PARAMS, (), AS_OF), "ISOLATION_HISTORY")
    assert (r.status, r.history_hits) == ("NO_DATA", None)


def test_rule_order_and_isolation_crops_only():
    assert [t.rule_id for t in check_triggers("당근", SNAP_1113, CARROT_PARAMS, HIST, AS_OF)] == \
        ["PRICE_STAB", "LOGISTICS", "ISOLATION_HISTORY"]
    for crop in ("마늘", "양파", "브로콜리", "감자"):
        assert [t.rule_id for t in check_triggers(crop, SNAP_1113, season_params(bundle(), crop, AS_OF), HIST, AS_OF)] == \
            ["PRICE_STAB", "LOGISTICS"]


# --- fix round 1 ---------------------------------------------------------------------------

def test_broccoli_base_with_unusable_grade_is_no_data_base_unconfirmed():
    # 브로콜리 2,420원(추정)은 값이 있으나 판정에 못 쓴다 → NO_DATA + "기준가 미확인"(NOT_APPLICABLE 아님).
    p = season_params(bundle(), "브로콜리", AS_OF)
    assert p.stab_base is None and p.base_unconfirmed
    r = check_triggers("브로콜리", SNAP_1113, p, HIST, AS_OF)[0]
    assert (r.rule_id, r.status, r.note, r.window, r.observed) == ("PRICE_STAB", "NO_DATA", "기준가 미확인", None, None)
    # 시즌 밖 달이어도 먼저 걸린다(strict 판정 정의 검사보다도 앞).
    july = date(2026, 7, 10)
    assert check_triggers("브로콜리", snap_half(july), season_params(bundle(), "브로콜리", july), HIST, july)[0].note == "기준가 미확인"


def test_citrus_empty_base_value_is_not_applicable_without_note():
    p = season_params(bundle(), "감귤_노지", AS_OF)
    assert not p.base_unconfirmed
    r = check_triggers("감귤_노지", SNAP_1113, p, HIST, AS_OF)[0]
    assert (r.status, r.note) == ("NOT_APPLICABLE", None)


def test_band_parameter_sources_are_in_result_sources():
    r = check_triggers("당근", SNAP_1113, CARROT_PARAMS, HIST, AS_OF)[0]
    ids = {s.source_id for s in r.sources}
    assert {f"params:2025-26:당근:{n}" for n in ("stab_base", "stab_band_lo", "stab_band_hi")} <= ids


def test_params_for_another_season_rejected():
    with pytest.raises(ValueError, match="시즌"):
        check_triggers("당근", SNAP_0315, CARROT_PARAMS, HIST, date(2026, 3, 15))
