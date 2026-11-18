"""Task 13(U13) 판정 값 보기: params_by_season.csv 긴 표 → 작물 하나의 SeasonParams.

시즌은 7월~이듬해 6월("2026-27"). 이번 시즌 값이 없으면 바로 앞 시즌 값 + carried_from(배지).
추정·미확인 행은 쓰지 않는다(브로콜리 기준가 2,420원 추정 → 판정에 안 씀).
"""
from datetime import date
from decimal import Decimal
from functools import lru_cache

import json

from app.core.params_view import JUDGE_OK, season_of, season_params, season_value
from app.core.tables_models import SeasonParam, TableBundle
from app.data_layer.tables import load_tables
from conftest import AS_OF, ROOT


@lru_cache(maxsize=None)
def bundle() -> TableBundle:
    return load_tables(ROOT / "data" / "tables", AS_OF)


def test_season_label_july_to_june():
    assert season_of(date(2026, 11, 13)) == "2026-27"
    assert season_of(date(2026, 3, 15)) == "2025-26"
    assert season_of(date(2026, 7, 1)) == "2026-27" and season_of(date(2026, 6, 30)) == "2025-26"
    assert season_of(date(2099, 12, 1)) == "2099-00"


def test_carrot_1113_carries_last_season_base():
    p = season_params(bundle(), "당근", AS_OF)
    assert p.season == "2026-27" and p.carried_from == "2025-26"   # 2026-27 기준가 미발표 → 직전 시즌 + 배지
    assert (p.stab_base, p.stab_floor, p.stab_paid_avg) == (Decimal(1088), Decimal(816), Decimal(71))
    assert p.stab_months == (11, 12, 1, 2, 3) and p.stab_hits_official == 8
    assert (p.stab_band_lo, p.stab_band_hi) == (Decimal("0.911"), Decimal("1.143"))
    assert p.stab_price_basis == "1361_averagePrice_반월가중"
    assert p.logi_won_per_kg == Decimal(16) and p.logi_months == ("2025-11", "2026-01")
    assert p.breakeven_lo is None and p.breakeven_hi is None       # 당근 물류비 판정 끔(미확인)
    assert p.season_months == (11, 12, 1, 2, 3)
    assert p.sources["stab_base"].source_id == "params:2025-26:당근:stab_base"
    assert p.sources["stab_base"].url == "http://www.ihalla.com/article.php?aid=1782278604787452010"


def test_carrot_in_season_not_carried():
    p = season_params(bundle(), "당근", date(2026, 3, 15))
    assert p.season == "2025-26" and p.carried_from is None and p.stab_base == Decimal(1088)


def test_citrus_reference_history_two_seasons_back_not_used():
    # 2023-24 공표 기준가 1,387원은 참고 이력. 바로 앞 시즌(2025-26)에도 없으므로 기준가 없음.
    p = season_params(bundle(), "감귤_노지", AS_OF)
    assert p.stab_base is None and p.stab_months == (10, 11, 12, 1) and p.carried_from is None


def test_broccoli_estimated_base_not_used():
    p = season_params(bundle(), "브로콜리", AS_OF)
    assert p.stab_base is None and p.stab_floor is None


def test_cabbage_estimated_band_falls_back_to_carrot_band():
    p = season_params(bundle(), "양배추", date(2026, 1, 20))
    assert p.stab_base == Decimal(723) and (p.stab_band_lo, p.stab_band_hi) == (Decimal("0.911"), Decimal("1.143"))
    assert (p.breakeven_lo, p.breakeven_hi) == (Decimal(648), Decimal(795))


def test_winter_radish_breakeven_carried_and_crop_season():
    p = season_params(bundle(), "월동무", AS_OF)
    assert (p.breakeven_lo, p.breakeven_hi) == (Decimal(529), Decimal(584)) and p.carried_from == "2025-26"
    assert p.season_months == (12, 1, 2, 3, 4) and p.stab_base is None


def test_no_rows_or_unknown_crop_gives_none():
    assert season_params(bundle(), "감자", AS_OF) is None
    assert season_params(bundle(), "carrot", AS_OF) is None


def test_season_value_reads_one_param_in_the_same_order():
    """보기 밖 칸(Task 14 금액 계산용): 이번 시즌 → 바로 앞 시즌 → 시즌 무관, 추정·미확인 제외."""
    value, src = season_value(bundle(), "양배추", "yield_kg_10a", AS_OF)
    assert value == "4711" and src.source_id == "params:2025-26:양배추:yield_kg_10a"
    assert season_value(bundle(), "양배추", "stab_share", AS_OF)[0] == "0.9"
    assert season_value(bundle(), "양파", "yield_kg_10a", AS_OF)[0] == "6314"          # 시즌 무관('-')
    assert season_value(bundle(), "브로콜리", "stab_base", AS_OF) is None               # 추정 → 안 씀
    assert season_value(bundle(), "양배추", "stab_base", date(2028, 1, 10)) is None     # 두 시즌 앞 값은 안 씀


# --- fix round 1 ---------------------------------------------------------------------------

def test_judge_ok_mirrors_schema_json():
    d = json.loads((ROOT / "data" / "tables" / "schema.json").read_text(encoding="utf-8"))
    assert {k: frozenset(v["judge_ok"]) for k, v in d["tables"]["params_by_season"]["param_dict"].items()
            if k in JUDGE_OK} == dict(JUDGE_OK)


def _row(season, param, value, status, crop="당근"):
    return SeasonParam(season=season, crop=crop, param=param, value=value, unit="x", status=status,
                       verified_date=date(2026, 11, 7), verified_by="B")


def _with(*rows):
    b = bundle()
    return b.model_copy(update={"params": tuple(r for r in b.params if r.crop != "당근") + rows})


def test_per_parameter_grades_breakeven_needs_derived_base_accepts_report():
    rows = (_row("2026-27", "stab_base", "1100", "보도"),            # stab_base: 보도 허용
            _row("2026-27", "breakeven_lo", "500", "공표"),          # breakeven: 역산만 → 공표는 안 씀
            _row("2026-27", "breakeven_hi", "600", "역산"),
            _row("2026-27", "stab_price_basis", "1361_averagePrice_반월가중", "역산"))   # 계산만 → 역산은 안 씀
    p = season_params(_with(*rows), "당근", AS_OF)
    assert p.stab_base == Decimal(1100) and p.breakeven_lo is None and p.breakeven_hi == Decimal(600)
    assert p.stab_price_basis is None
    assert season_value(_with(*rows), "당근", "stab_base", AS_OF)[0] == "1100"
    assert season_value(_with(*rows), "당근", "breakeven_lo", AS_OF) is None


def test_carried_is_per_parameter():
    rows = (_row("2026-27", "stab_base", "1100", "공표"), _row("2025-26", "stab_floor", "800", "공표"))
    p = season_params(_with(*rows), "당근", AS_OF)
    assert p.stab_base == Decimal(1100) and p.stab_floor == Decimal(800)
    assert p.carried == {"stab_floor": "2025-26"} and "stab_base" not in p.carried
    assert p.carried_from == "2025-26"
    q = season_params(bundle(), "당근", AS_OF)
    assert q.carried["stab_base"] == "2025-26"
