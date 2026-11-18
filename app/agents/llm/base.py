"""LLM 계층 공통 타입(Task 9, U09) — research/dept/round1-C-agent.md §6-1.

- 에이전트는 LLMClient.generate(GenRequest)만 부른다. 제공자 SDK는 어댑터 안에만 있다(Task 31, 지연 import).
- 밖으로 나가는 요청은 어댑터가 generate() 첫 줄에서 payload.build_payload(req)로 Payload를 만들고,
  그 Payload만으로 제공자 요청을 조립한다. Payload는 거름망을 지나야만 만들어진다(payload.py).
- 실패는 모두 LLMUnavailable(reason) 하나로 올라온다. 부르는 쪽은 except LLMUnavailable로 그 구획을
  템플릿으로 바꾼다. 사유는 제공자 판별 코드(round1-C §6-3)와 이 계층의 두 하위 클래스다:
    PAYLOAD_REJECTED  payload.PayloadRejected(field, pattern) — 거름망이 전송을 막음(.field·.pattern)
    REPLAY_MISMATCH   scripted.ReplayMismatch(input_hash) — 녹화에 없는 입력(.input_hash)
  재생 모드(Task 32)는 ReplayMismatch를 먼저 잡아 "녹화와 입력이 다릅니다"를 띄운다.
- §6-1과 다른 점: purpose는 11-13판 셋(intake는 11-19), ToolDef.schema는 BaseModel.schema와 이름이
  겹쳐 input_schema, 도구 왕복을 담을 Msg·ToolCall·ToolResult를 정했고, GenRequest에 전송하지 않는
  꼬리표 section(종이 구획, rules.SectionKind)을 더했다(장식자·녹화가 구획을 알아야 한다).
  LLMClient에는 로그용 provider·model 이름을 더했다(주입 결과에 "fault-inject(제공자)"를 찍는다).
"""
from typing import Any, Literal, Protocol, get_args

from pydantic import Field, model_validator

from app.agents.rules import SectionKind
from app.core.models import CoreModel

Purpose = Literal["narrate", "judge", "notice", "match", "scout"]
PUBLIC_TEXT_PURPOSES = frozenset({"notice", "match", "scout"})   # 공개 공고 글을 싣는 목적(거름망은 주민번호 규칙만)
StopReason = Literal["end", "tool", "length", "refusal"]
UnavailableReason = Literal["NO_KEY", "AUTH", "BILLING", "RATE_LIMIT", "OVERLOADED", "TIMEOUT",
                            "NETWORK", "REFUSAL", "BAD_OUTPUT", "CIRCUIT_OPEN", "DAILY_CAP",
                            "PAYLOAD_REJECTED", "REPLAY_MISMATCH"]


class ToolDef(CoreModel):
    name: str
    description: str
    input_schema: dict[str, Any]               # pydantic 모델의 JSON Schema


class ToolCall(CoreModel):
    call_id: str                               # 제공자가 붙인 불투명 ID(거름망 검사에서 뺀다)
    name: str
    args: dict[str, Any]


class ToolResult(CoreModel):
    call_id: str
    content: str                               # 도구 결과 JSON 문자열. 거름망이 숫자까지 검사한다
    is_error: bool = False


class Msg(CoreModel):
    role: Literal["user", "assistant"]
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()      # assistant만
    tool_results: tuple[ToolResult, ...] = ()  # user만

    @model_validator(mode="after")
    def _shape(self) -> "Msg":
        if self.text is None and not self.tool_calls and not self.tool_results:
            raise ValueError("빈 메시지입니다.")
        if (self.role == "user" and self.tool_calls) or (self.role == "assistant" and self.tool_results):
            raise ValueError("도구 호출은 assistant, 도구 결과는 user 메시지에만 담습니다.")
        return self


class GenRequest(CoreModel):
    purpose: Purpose
    system: str
    messages: tuple[Msg, ...] = Field(min_length=1)
    tools: tuple[ToolDef, ...] = ()
    response_schema: dict[str, Any] | None = None  # 구조화 출력
    max_output_tokens: int = Field(default=2000, ge=1)
    timeout_s: float = Field(default=20.0, gt=0)
    effort: Literal["low", "default"] = "low"      # 제공자별 '생각 깊이'로 사상(없으면 무시)
    section: SectionKind | None = None             # 쓰거나 판정하는 종이 구획. 전송하지 않는 꼬리표


class GenResult(CoreModel):
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    stop: StopReason
    tok_in: int = Field(ge=0)
    tok_out: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    provider: str
    model: str


class LLMUnavailable(Exception):
    """LLM을 쓸 수 없음. reason은 위 사유 코드 중 하나. detail은 로그용(키·개인정보 금지)."""

    def __init__(self, reason: UnavailableReason, detail: str = ""):
        if reason not in get_args(UnavailableReason):
            raise ValueError(f"모르는 LLMUnavailable 사유: {reason}")
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class LLMClient(Protocol):
    provider: str                              # 로그용 이름, 예: "anthropic", "fault-inject(anthropic)"
    model: str

    def generate(self, req: GenRequest) -> GenResult: ...
