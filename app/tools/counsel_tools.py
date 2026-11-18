"""상담 에이전트 도구 3개(Task 28) — get_program_detail, get_product_detail, submit_narrative.

CounselTools(bundle)이 표 묶음(programs·insurance 속성)을 읽는다. 도구가 돌려주는 값에는 숫자가 없다(금액·날짜·나이 칸은
싣지 않는다): 설명 단계의 LLM에는 숫자가 나가지 않기 때문이다. 등록 방식은 notice_tools와 같다(ToolRegistry).
submit_narrative는 모델이 낸 구획 JSON을 읽어 Section으로 돌려주고, 못 읽으면 고칠 수 있는 한국어 오류(ToolError)를 던진다.
"""
import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.rules import Section, parse_section
from app.tools.registry import ToolError, ToolRegistry

_DIGIT = re.compile(r"[0-9０-９①-⑳]")
_KIND_LABEL = {"crop_disaster": "농작물재해보험", "income_stab": "농업수입안정보험", "nh_safety": "농업인 안전보험"}


def _clean(text: str | None) -> str | None:
    """숫자가 든 글은 싣지 않는다(None)."""
    return None if text is None or _DIGIT.search(text) else text


class ProgramDetail(BaseModel):
    id: str
    name: str | None
    agency: str | None
    office: str | None
    kind: str | None
    applicant: str | None
    row_status: str
    needs_mgmt: bool
    needs_coop: bool
    needs_selfpay_fund: bool


class ProductDetail(BaseModel):
    product_id: str
    label: str
    crops: list[str]
    office_id: str
    needs_mgmt: bool


class SubmitOut(BaseModel):
    section: dict[str, Any]


class ProgramIn(BaseModel):
    """제도 한 건의 숫자 없는 설명(이름, 담당 기관, 접수처, 먼저 갖출 조건)을 본다. 근거 줄의 제도 식별자를 넣는다."""

    id: str = Field(description="제도 식별자(표의 id)")


class ProductIn(BaseModel):
    """보험 상품 한 종류의 숫자 없는 설명(이름, 대상 작물, 접수 창구)을 본다."""

    id: str = Field(description="보험 상품 식별자. 종류 이름이나 종류:작물 모양")


class SubmitIn(BaseModel):
    """다 쓴 구획을 JSON 글자로 낸다. 형식이 틀리면 어디가 틀렸는지 알려 준다."""

    section_json: str = Field(description="구획 JSON. section과 sentences를 갖춘 것")


class CounselTools:
    def __init__(self, bundle: Any) -> None:
        self.bundle = bundle

    def _need_bundle(self) -> Any:
        if self.bundle is None:
            raise ToolError("표 묶음이 연결되어 있지 않아 이 도구를 쓸 수 없습니다. submit_narrative만 쓰세요")
        return self.bundle

    def get_program_detail(self, id: str) -> ProgramDetail:
        self._need_bundle()
        row = next((p for p in self.bundle.programs if p.id == id), None)
        if row is None:
            raise ToolError(f"표에 {id} 제도가 없습니다. 근거 줄의 제도 식별자를 그대로 쓰세요")
        return ProgramDetail(id=row.id, name=_clean(row.name), agency=_clean(row.agency), office=_clean(row.office),
                             kind=row.kind, applicant=row.applicant, row_status=row.status,
                             needs_mgmt=row.needs_mgmt == "Y", needs_coop=row.needs_coop is not None,
                             needs_selfpay_fund=row.needs_selfpay_fund is not None)

    def get_product_detail(self, id: str) -> ProductDetail:
        self._need_bundle()
        kind, _, crop = id.partition(":")
        rows = [p for p in self.bundle.insurance if p.product_id == kind and (not crop or p.crop_keys is None or crop in p.crop_keys)]
        if not rows:
            raise ToolError(f"표에 {id} 보험 상품이 없습니다. 보험 종류 이름(예: crop_disaster)이나 종류:작물 모양으로 쓰세요")
        crops = sorted({c for p in rows for c in (p.crop_keys or ())})
        return ProductDetail(product_id=kind, label=_KIND_LABEL.get(kind, kind), crops=crops,
                             office_id=rows[0].office_id, needs_mgmt=any(p.needs_mgmt for p in rows))

    def submit_narrative(self, section_json: str) -> Section:
        section, hits = parse_section(section_json)
        if section is None:
            raise ToolError(f"구획 형식 오류 - {hits[0].span}. section과 sentences(sid, text, cites)를 갖춘 JSON으로 다시 내세요")
        return section

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register("get_program_detail", ProgramIn, ProgramDetail, lambda a: self.get_program_detail(a.id))
        reg.register("get_product_detail", ProductIn, ProductDetail, lambda a: self.get_product_detail(a.id))
        reg.register("submit_narrative", SubmitIn, SubmitOut,
                     lambda a: SubmitOut(section=self.submit_narrative(a.section_json).model_dump(mode="json")))
        return reg
