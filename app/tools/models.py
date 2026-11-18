"""공고 도구 모델(Task 18). app/core/models.py에 NoticeDraft·DraftIssue·ToolLog가 없어 여기에 둔다.

도구 입력·출력 모델의 독스트링과 Field 설명은 모델에 보이는 글이므로 숫자를 쓰지 않는다
(registry.register가 막는다). 초안 모델은 JSON으로 오가므로 core 모델처럼 바꿀 수 없고 모르는 키는 거부한다.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from app.core.models import CoreModel

Level = Literal["RED", "YELLOW"]
Decision = Literal["DRAFT_READY", "NEEDS_STAFF", "NOT_RELEVANT", "BLOCKED_PII", "UNREADABLE"]


# --- 초안 -----------------------------------------------------------------------------------

class DraftField(CoreModel):
    """표 한 칸의 초안. 값과 원문에서 그대로 옮긴 인용 문장을 함께 낸다."""

    value: Any = None
    quote: str | None = Field(default=None, description="공고 원문에 있는 그대로의 문장")
    anchor: str | None = Field(default=None, description="인용을 찾은 자리(쪽과 줄 앵커)")


class DraftTag(CoreModel):
    """농가가 먼저 알아야 할 중요한 조건 하나. 짧은 이름표와 그 근거가 되는 공고 원문 문장."""

    label: str = Field(description="조건을 짧고 쉬운 말로 적은 이름표")
    quote: str | None = Field(default=None, description="공고 원문에 있는 그대로의 근거 문장")
    anchor: str | None = Field(default=None, description="인용을 찾은 자리(쪽과 줄 앵커)")


class DraftProgram(CoreModel):
    """공고 속 사업 하나의 초안. 새 사업, 기존 행 갱신, 기존 행과 같음 중 하나."""

    action: Literal["NEW", "UPDATE", "SAME"] = "UPDATE"
    match_id: str | None = Field(default=None, description="갱신하거나 같다고 본 기존 행의 식별자")
    program_key: str | None = Field(default=None, description="새 사업이면 새로 붙일 사업 키")
    fields: dict[str, DraftField] = Field(default_factory=dict, description="표 칸 이름별 초안")
    questions: tuple[str, ...] = Field(default=(), description="직원에게 물을 질문")
    tags: tuple[DraftTag, ...] = Field(default=(), description="농가가 가장 먼저 알아야 할 중요한 조건 이름표 목록. 각 이름표에 원문 근거 문장을 붙인다")


class Skipped(CoreModel):
    """초안에 넣지 않은 사업과 이유."""

    title: str
    reason: str


class NoticeDraft(CoreModel):
    """공고 한 건의 초안. 사업별 초안과 넣지 않은 사업 목록."""

    programs: tuple[DraftProgram, ...] = ()
    skipped: tuple[Skipped, ...] = ()


class DraftIssue(CoreModel):
    """초안 검사에서 나온 문제 하나. 빨강은 확정을 막고 노랑은 직원이 보고 넘어갈 수 있다."""

    program: int | None = Field(default=None, description="사업 순번(영부터). 초안 전체 문제면 비어 있다")
    field: str
    level: Level
    code: str
    message: str


# --- 도구 결과 -------------------------------------------------------------------------------

class Hit(CoreModel):
    """문서 검색 결과 한 줄."""

    anchor: str
    passage: str
    score: float


class ReadResult(CoreModel):
    """앵커부터 읽은 글과 이어서 읽을 앵커."""

    anchor: str
    text: str
    next_anchor: str | None = None


class ProgramMatch(CoreModel):
    """표에 있는 사업 후보."""

    id: str
    program_key: str
    name: str | None
    edition: str
    status: str
    score: float


class AskResult(CoreModel):
    """직원 질문 접수 결과."""

    queued: bool
    message: str


class FinishResult(CoreModel):
    """끝내기 결과."""

    ok: bool
    decision: Decision
    reason: str


# --- 기록 ------------------------------------------------------------------------------------

class ToolRecord(CoreModel):
    """도구 호출 한 번의 기록. 성공이면 result, 실패면 고칠 수 있는 한국어 error."""

    name: str
    args: dict[str, Any]
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None

    def content(self) -> str:
        """모델에게 돌려줄 JSON 글."""
        body = self.result if self.ok else {"error": self.error}
        return json.dumps(body, ensure_ascii=False)


@dataclass(frozen=True)
class StaffQuestion:
    field: str
    question: str


@dataclass
class ToolLog:
    """한 번의 공고 처리에서 일어난 도구 호출과 직원 질문."""

    calls: list[ToolRecord] = field(default_factory=list)
    questions: list[StaffQuestion] = field(default_factory=list)

    @property
    def tool_calls(self) -> int:
        return len(self.calls)
