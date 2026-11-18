"""녹화 재생(Task 9, U09). 손으로 쓰거나 녹화한 응답을 요청의 input_hash로 찾아 돌려준다.

요청도 실제 어댑터처럼 build_payload()를 지난다. 그래서 녹화에 든 입력도 숫자·읍면동·건강 낱말이 없음이
보장되고, 해시는 거름망을 지난 Payload의 정규 JSON에서 나온다(payload.input_hash).
같은 해시가 여러 번 있으면 앞의 것을 쓴다(상태 없음, 몇 번 불러도 같은 답).
Recording 형식은 Task 32(재생 모드)·35(녹화)가 이어 쓴다.
"""
from datetime import datetime

from pydantic import Field

from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable
from app.agents.llm.payload import build_payload, input_hash
from app.core.models import CoreModel


class RecordedCall(CoreModel):
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: GenResult


class Recording(CoreModel):
    provider: str
    model: str
    recorded_at: datetime
    calls: tuple[RecordedCall, ...]


class ReplayMismatch(LLMUnavailable):
    """녹화에 없는 입력(reason "REPLAY_MISMATCH"). 화면 문구는 "녹화와 입력이 다릅니다. 시연 농가 P1~P5를
    고르세요"(Task 32가 먼저 잡는다). 그 밖의 except LLMUnavailable은 템플릿으로 간다."""

    def __init__(self, input_hash: str):
        super().__init__("REPLAY_MISMATCH", f"녹화에 없는 입력(input_hash {input_hash[:12]}…)")
        self.input_hash = input_hash


class ScriptedClient:
    def __init__(self, recording: Recording):
        self.recording = recording
        self.provider = recording.provider
        self.model = recording.model
        self._by_hash: dict[str, GenResult] = {}
        for call in recording.calls:
            self._by_hash.setdefault(call.input_hash, call.response)

    def generate(self, req: GenRequest) -> GenResult:
        h = input_hash(build_payload(req))
        if h not in self._by_hash:
            raise ReplayMismatch(h)
        return self._by_hash[h]
