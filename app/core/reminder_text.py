"""재방문 문자 문구(Task 39). 템플릿만 쓴다. 이름·금액 없음, 숫자는 달과 센터 전화번호뿐, 70자 이하."""
from __future__ import annotations

from app.core.tables_models import TableBundle

MAX_LEN = 70
_KIND_LABEL = {
    "integrated": "지원사업 공고가 나오는 달",
    "allowance_direct": "수당·직불금을 신청하는 달",
    "insurance": "농작물 보험에 드는 달",
}
_NO_PHONE = "센터로 전화 주세요"


def reminder_text(program_key: str, month: int, bundle: TableBundle | None = None, center_phone: str = "") -> str:
    """program_key는 달력 칸의 종류(integrated/allowance_direct/insurance) 또는 제도 id.

    제도 id면 표에서 이름을 찾되, 숫자가 들어 있으면 일반 문구로 돌린다.
    """
    label = _KIND_LABEL.get(program_key)
    if label is None and bundle is not None:
        prog = next((p for p in bundle.programs if p.id == program_key), None)
        if prog is not None and prog.name and not any(c.isdigit() for c in prog.name):
            label = f"{prog.name} 신청하는 달"
    label = label or "지원사업을 신청하는 달"
    phone = center_phone.strip()
    contact = f"센터({phone})로 전화 주세요" if phone else _NO_PHONE
    text = f"삼춘, {month}월은 {label}이에요. 궁금하시면 {contact}."
    if len(text) > MAX_LEN:
        text = f"삼춘, {month}월은 신청하는 달이에요. 궁금하시면 {contact}."
    return text[:MAX_LEN]
