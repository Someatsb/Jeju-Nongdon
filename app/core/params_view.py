"""작물·시즌별 판정 값 보기(Task 13, U13). params_by_season.csv 긴 표(SeasonParam 행)를 작물 하나의
SeasonParams로 모은다. Task 3은 긴 표 행(SeasonParam)만 내므로 이 보기를 여기서 만든다.

- 시즌: 7월~이듬해 6월이 한 시즌 "YYYY-YY"(as_of 2026-11-13 → 2026-27, 2026-03-15 → 2025-26).
- 값 찾는 순서: 이번 시즌 → 바로 앞 시즌(carried_from에 적음 → 배지 "2025-26 기준") → 시즌 무관('-').
  carried(param → 시즌)에 param마다 적어, 올해 값과 작년 값이 섞여도 배지가 값마다 맞다. 두 시즌 이상 앞 값은 쓰지 않는다(노지감귤 2022-23·2023-24 기준가 같은 참고 이력이 끼지 않게).
- 쓰는 등급은 param마다 다르다(JUDGE_OK = schema.json param_dict의 judge_ok). 기준가는 공표·공고·보도, 손익분기
  역산 구간은 역산만이다. 추정·미확인 행은 쓰지 않는다. 브로콜리 기준가 2,420원(추정)은 판정에 없고, 양배추 경계 배수(추정, 당근 구간
  임시 적용)는 기본값 0.911·1.143(당근 869 저장본 재계산값)으로 같은 값이 된다.
"""
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from app.core.models import CoreModel, SourceRef
from app.core.tables_models import SeasonParam, TableBundle

# schema.json params_by_season.param_dict[*].judge_ok 복사본(core는 파일을 읽지 않는다. 같은지 test_params_view가 비교한다).
JUDGE_OK: dict[str, frozenset[str]] = {k: frozenset(v.split()) for k, v in {
    "stab_base": "공표 공고 보도", "stab_floor": "공표 공고 보도 계산", "stab_share": "공표 보도",
    "stab_months": "공표 보도", "stab_market": "공표 보도", "stab_window": "공표 보도", "stab_price_basis": "계산",
    "stab_band_lo": "계산", "stab_band_hi": "계산", "stab_hits_official": "공표 보도", "stab_paid_avg": "공표 보도",
    "stab_enroll_end": "공표 보도", "logi_won_per_kg": "공고", "logi_months": "공고 보도", "breakeven_lo": "역산",
    "breakeven_hi": "역산", "breakeven_reported": "", "area_ha": "공표 보도", "area_change_pct": "공표 보도",
    "yield_kg_10a": "공표 계산"}.items()}
SEASONLESS = "-"
BAND_LO = Decimal("0.911")   # 1/p90(1.0977), 1361 반월 평균 < 기준가 × 이 배수 → '아래'
BAND_HI = Decimal("1.143")   # 1/p10(0.8746), 1361 반월 평균 ≥ 기준가 × 이 배수 → '위'


def _ints(v: str) -> tuple[int, ...]:
    return tuple(int(t) for t in v.split(";") if t.strip())


def _strs(v: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in v.split(";") if t.strip())


# param 이름 → 값 변환. 여기에 없는 param(area_ha 등)은 보기에 넣지 않는다.
_PARSE: dict[str, Callable[[str], object]] = {
    "stab_base": Decimal, "stab_floor": Decimal, "stab_paid_avg": Decimal, "stab_hits_official": int,
    "stab_months": _ints, "stab_band_lo": Decimal, "stab_band_hi": Decimal, "stab_price_basis": str,
    "logi_won_per_kg": Decimal, "logi_months": _strs, "breakeven_lo": Decimal, "breakeven_hi": Decimal,
}


class SeasonParams(CoreModel):
    """작물 하나, 기준일 시즌 하나의 판정·금액 값. 원/kg 값은 Decimal, 없으면 None."""

    crop: str                                   # crops.csv 코드
    season: str                                 # 기준일 시즌 "2026-27"
    carried_from: str | None = None             # 바로 앞 시즌 값을 하나라도 썼으면 그 시즌("2025-26"). 값별 배지는 carried
    carried: dict[str, str] = {}                # param 이름 → 바로 앞 시즌 값을 쓴 그 시즌. 이번 시즌 값은 안 들어온다
    base_unconfirmed: bool = False              # 기준가 행에 값은 있으나 등급이 추정·미확인이라 못 씀(값이 빈 행은 아님)
    season_months: tuple[int, ...] = ()         # crops.csv season_months(물류비 판정 달)
    stab_base: Decimal | None = None            # 가격안정관리제 기준가 원/kg
    stab_floor: Decimal | None = None           # 하한가 원/kg
    stab_months: tuple[int, ...] = ()           # 가격안정관리제 대상 달
    stab_band_lo: Decimal = BAND_LO
    stab_band_hi: Decimal = BAND_HI
    stab_price_basis: str | None = None         # "1361_averagePrice_반월가중"
    stab_hits_official: int | None = None       # 지난 시즌 공식 발동 횟수
    stab_paid_avg: Decimal | None = None        # 지난 시즌 kg당 평균 지급액
    logi_won_per_kg: Decimal | None = None      # 물류비 단가
    logi_months: tuple[str, ...] = ()           # 지난 시즌 물류비 대상 달 "2025-11"
    breakeven_lo: Decimal | None = None         # 물류비 손익분기 역산 구간 (lo, hi]
    breakeven_hi: Decimal | None = None
    sources: dict[str, SourceRef] = {}          # param 이름 → 그 값의 표 행 출처


def season_of(as_of: date) -> str:
    """기준일이 든 시즌 라벨. 7월부터 다음 시즌이다."""
    y = as_of.year if as_of.month >= 7 else as_of.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _previous(season: str) -> str:
    y = int(season[:4]) - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _source(row: SeasonParam) -> SourceRef:
    return SourceRef(source_id=f"params:{row.season}:{row.crop}:{row.param}", url=row.source_url, as_of=row.verified_date)


def _usable(row: SeasonParam) -> bool:
    return row.value is not None and row.status in JUDGE_OK.get(row.param, frozenset())


def season_value(bundle: TableBundle, crop_code: str, param: str, as_of: date) -> tuple[str, SourceRef] | None:
    """보기(SeasonParams)에 없는 param 한 칸(stab_share·yield_kg_10a 등)의 (값 글자, 출처). 금액 계산(Task 14)이 쓴다.

    찾는 순서·쓰는 등급은 season_params와 같다(이번 시즌 → 바로 앞 시즌 → 시즌 무관, 추정·미확인 제외).
    carried_from 배지에는 넣지 않는다(작년 수확량처럼 원래 지난 시즌 값인 칸이 판정 배지를 바꾸지 않게).
    """
    season = season_of(as_of)
    usable = {r.season: r for r in bundle.params if r.crop == crop_code and r.param == param and _usable(r)}
    row = next((usable[s] for s in (season, _previous(season), SEASONLESS) if s in usable), None)
    return None if row is None else (row.value, _source(row))


def season_params(bundle: TableBundle, crop_code: str, as_of: date) -> SeasonParams | None:
    """기준일 시즌의 crop_code 값 보기. crops.csv에 없거나 params 행이 하나도 없는 작물은 None."""
    crop = next((c for c in bundle.crops if c.crop_code == crop_code), None)
    rows = [r for r in bundle.params if r.crop == crop_code]
    if crop is None or not rows:
        return None
    season = season_of(as_of)
    prev = _previous(season)
    usable = {(r.season, r.param): r for r in rows if _usable(r)}
    seasons = (season, prev, SEASONLESS)
    values: dict[str, object] = {}
    sources: dict[str, SourceRef] = {}
    carried: dict[str, str] = {}
    for param, parse in _PARSE.items():
        row = next((usable[(s, param)] for s in seasons if (s, param) in usable), None)
        if row is None:
            continue
        values[param] = parse(row.value)
        sources[param] = _source(row)
        if row.season == prev:
            carried[param] = prev
    # 기준가: 쓸 수 있는 행이 없는데 값이 적힌 행(추정 등)이 이번·앞 시즌·무관에 있으면 "기준가 미확인". 값이 빈 행은 아니다.
    unconfirmed = "stab_base" not in values and any(
        r.param == "stab_base" and r.value is not None and r.season in seasons for r in rows)
    return SeasonParams(crop=crop_code, season=season, carried_from=prev if carried else None, carried=carried,
                        base_unconfirmed=unconfirmed, season_months=crop.season_months, sources=sources, **values)
