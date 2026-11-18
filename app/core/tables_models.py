"""표 행 모델(Task 3, U03). 코어가 읽는 표 한 행씩과 표 묶음(TableBundle).

- 필드 이름·허용값은 data/tables/schema.json 컬럼 그대로. CSV 해석·파일 읽기는 하지 않는다
  (app/data_layer/tables.py가 칸을 형 변환해 넘긴다). 빈칸은 None, ';' 목록 칸은 tuple.
- InsuranceProduct는 round1-C-agent.md §3-2 ④ 그대로. insurance.csv는 Task 11이 만든다.
- supports.csv 한 행은 app/core/models.py의 Program이다.
"""
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, field_serializer, field_validator

from app.core.models import CoreModel, Program, SourceRef

ParamGrade = Literal["공표", "공고", "보도", "역산", "계산", "추정", "미확인"]


class SeasonParam(CoreModel):
    """params_by_season.csv 한 행. value는 단위(unit)에 따라 숫자·날짜·목록 글자라 str로 둔다."""

    season: str                                 # 2025-26 / 2026 / '-'(시즌 무관)
    crop: str                                   # crops.csv 코드
    param: str                                  # schema.json param_dict 키
    value: str | None = None                    # status=미확인이면 None
    unit: str
    status: ParamGrade
    method: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    verified_date: date
    verified_by: str


class Crop(CoreModel):
    """crops.csv 한 행."""

    crop_code: str
    label: str
    aliases: tuple[str, ...]
    groups: tuple[str, ...] = ()
    judge_source: Literal["hub1362_garak", "hub1361_amount", "jasdc_kind1", "없음"]
    judge_cultivars: tuple[str, ...] = ()
    dist_cultivars: tuple[str, ...] = ()
    season_months: tuple[int, ...] = ()
    notes: str | None = None


class Intervention(CoreModel):
    """interventions.csv 한 행(시즌별 시장격리·수매 등 정부 개입 기록)."""

    season: str
    crop: str
    type: Literal["시장격리", "수매", "산지폐기", "자율감축", "정부비축", "출하정지", "없음"]
    scale: str | None = None
    confirmed: Literal["확인", "보도1건", "추정", "미확인"]
    source_title: str | None = None
    source_url: str | None = None
    verified_date: date
    notes: str | None = None


class InsuranceProduct(CoreModel):
    """insurance.csv 한 행(round1-C-agent.md §3-2 ④)."""

    product_id: Literal["income_stab", "crop_disaster", "nh_safety"]
    crop_keys: tuple[str, ...] | None           # 품종 단위. None = 작물 무관(안전보험)
    windows: tuple[tuple[str, str], ...]        # ("08-01", "10-31") 월-일
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_age: int | None = Field(default=None, ge=0, le=120)
    needs_mgmt: bool
    office_id: str
    subsidy_text: str
    extra_requirement: str | None = None        # 당근 재해보험 "출현율 요건" 등
    source: SourceRef


class Office(CoreModel):
    """offices.csv 한 행. name은 supports.csv 접수처(office) 칸과 같은 글자."""

    office_id: str
    name: str
    phone: str | None = None
    address_hint: str | None = None


class TableBundle(CoreModel):
    """load_tables가 돌려주는 표 묶음. hold 행도 programs에 들어 있다(인쇄 여부는 코어가 정함)."""

    programs: tuple[Program, ...]
    params: tuple[SeasonParam, ...]
    crops: tuple[Crop, ...]
    interventions: tuple[Intervention, ...]
    insurance: tuple[InsuranceProduct, ...]
    offices: Mapping[str, Office]               # office_id → Office, 읽기 전용(MappingProxyType)
    verified_date: date                         # 지원 표 확인일: 종이에 나갈 수 있는 행 중 가장 오래된 확인일

    @field_validator("offices", mode="after")
    @classmethod
    def _read_only(cls, v: Mapping[str, Office]) -> Mapping[str, Office]:
        return MappingProxyType(dict(v))        # frozen 모델 안의 dict를 밖에서 고치지 못하게

    @field_serializer("offices")
    def _offices_dict(self, v: Mapping[str, Office], info: Any) -> dict[str, Any]:
        return {k: o.model_dump(mode=info.mode) for k, o in v.items()}

    def office_named(self, name: str | None) -> Office | None:
        """supports.csv 접수처 글자로 창구를 찾는다. 없으면 None."""
        return next((o for o in self.offices.values() if o.name == name), None)
