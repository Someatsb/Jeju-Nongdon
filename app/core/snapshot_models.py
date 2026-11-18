"""스냅샷 모델(Task 12, U12). 가격 시리즈·재배면적·경계 배수 묶음과 신선도 판정.

- 파일 읽기·sha256·as_of 절단은 app/data_layer/snapshot.py가 한다. 여기는 모양과 순수 함수만.
- 가격 점은 (날짜, 원/kg, 거래량 kg). 1361 averagePrice는 시장·법인 행 단순평균이라
  반월 평균은 Task 13이 이 거래량으로 가중한다. 판정(발동 여부)은 여기서 하지 않는다.
- 신선도: 기준일과 자료 마지막 날의 차이(일) ≤3 ok, 4~14 aged(노란 배지), ≥15 stale(빨간 배지,
  진행 중 반월 판정 생략).
"""
from datetime import date
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import model_validator

from app.core.models import CoreModel, SourceRef

Freshness = Literal["ok", "aged", "stale"]
OK_MAX_DAYS = 3
AGED_MAX_DAYS = 14


class PricePoint(NamedTuple):
    """하루치 가격. 튜플이라 p[0]·p[1]·p[2]로도 읽힌다."""

    day: date
    won_per_kg: Decimal
    volume_kg: Decimal


class PriceSeries(CoreModel):
    """품종 하나의 일별 가격(날짜순, 같은 날 한 번). 거래량 0인 날은 들어 있지 않다."""

    crop_code: str                              # crops.csv 작물 코드("당근")
    cultivars: tuple[str, ...]                  # 1361 품종 글자("당근(일반)") 또는 수급센터 ("kind=1",)
    judge: bool                                 # crops.csv judge_cultivars에 있으면 True, dist_cultivars에만 있으면 False
    market_scope: Literal["전국", "가락"]
    points: tuple[PricePoint, ...]
    source: SourceRef                           # as_of = 그 데이터셋의 마지막 날(기준일 이하)

    @model_validator(mode="after")
    def _ordered_positive(self) -> "PriceSeries":
        days = [p.day for p in self.points]
        if any(a >= b for a, b in zip(days, days[1:])):
            raise ValueError("가격 점은 날짜순이어야 하고 같은 날이 두 번 있으면 안 됩니다.")
        if any(p.won_per_kg <= 0 or p.volume_kg <= 0 for p in self.points):
            raise ValueError("가격과 거래량은 0보다 커야 합니다.")
        return self


class Snapshot(CoreModel):
    """load_snapshot이 돌려주는 묶음. 기준일(as_of) 뒤 날짜의 값은 하나도 들어 있지 않다."""

    prices: dict[str, PriceSeries]              # 1361 품종 글자 → 시리즈
    citrus: PriceSeries | None                  # 수급센터 노지온주(kind=1), 원/kg = 5kg 상자값 ÷ 5
    area: dict[str, dict[int, float]]           # 작물 코드 → 연도 → 제주 재배면적(ha, 854)
    ratio_bounds: dict[str, tuple[Decimal, Decimal]]  # 작물 코드 → (아래 배수, 위 배수), 869 가락/1361 비
    built_at: date                              # manifest.json의 스냅샷 만든 날
    price_as_of: date | None                    # 1361 마지막 날(기준일 이하). 손상·자료 없음이면 None
    citrus_as_of: date | None
    damaged: dict[str, str] = {}                # 데이터셋 이름 → 읽지 않은 이유(sha256 불일치·파일 없음 등)

    @model_validator(mode="after")
    def _bounds_ordered(self) -> "Snapshot":
        for crop, (lo, hi) in self.ratio_bounds.items():
            if not 0 < lo < hi:
                raise ValueError(f"{crop} 경계 배수는 0 < 아래 < 위 여야 합니다: {lo}, {hi}")
        return self


def staleness_days(as_of: date, data_as_of: date) -> int:
    """기준일과 자료 마지막 날 사이의 날 수. 자료가 기준일보다 뒤면(절단 누락) ValueError."""
    days = (as_of - data_as_of).days
    if days < 0:
        raise ValueError(f"자료 날짜 {data_as_of}가 기준일 {as_of}보다 뒤입니다.")
    return days


def freshness(as_of: date, data_as_of: date) -> Freshness:
    """≤3일 ok, 4~14일 aged, ≥15일 stale."""
    days = staleness_days(as_of, data_as_of)
    if days <= OK_MAX_DAYS:
        return "ok"
    return "aged" if days <= AGED_MAX_DAYS else "stale"
