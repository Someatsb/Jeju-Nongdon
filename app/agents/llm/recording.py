"""재생 모드용 녹화(Task 32, U32). 심사 PC에 API 키가 없어도 시연이 되도록, 녹화했거나 손으로 쓴 모델 답을 되돌려 준다.

형식(data/replay/<표본>.json): sample_id, recorded_at, source("recorded"=실제 호출을 녹화 | "handwritten"=손으로 쓴 시연 답),
provider, model, prompt_ver, rules_ver, as_of, input_hash(상담 지문, pipeline.fingerprint), calls[].
calls[] 한 줄 = LLM 요청 하나: purpose, section, attempt(구획 안 차례), request_hash(요청의 전송 거름망 해시, scripted와 같은 것),
response(GenResult), injected(일부러 넣은 나쁜 답이면 true. 검수 화면에 "주입"으로 보인다).

ReplayClient는 ScriptedClient를 그대로 쓴다: 해시로 찾고, 없으면 ReplayMismatch(REPLAY_MISMATCH, LLMUnavailable의 하위).
실제 호출 길(어댑터·키)은 이 파일에서 닿지 않는다. 화면 문구는 이 파일의 상수 한 곳에서 나온다.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.agents.llm.base import GenRequest, GenResult, Purpose
from app.agents.llm.payload import build_payload, input_hash
from app.agents.llm.scripted import RecordedCall as _ScriptedCall
from app.agents.llm.scripted import Recording as _ScriptedRecording
from app.agents.llm.scripted import ReplayMismatch, ScriptedClient
from app.core.models import CoreModel

REPLAY_MISMATCH_MESSAGE = "녹화와 입력이 다릅니다. 시연 농가 P1~P5를 고르세요"
BANNER_RECORDED = "녹화 응답 재생 중 — 실제 LLM 호출 아님"
BANNER_HANDWRITTEN = "손으로 쓴 시연 응답 재생 — 실제 LLM 호출 아님"
PAPER_LINE = "체험용으로 저장해 둔 AI 답변을 쓴 종이예요"   # 종이에 찍는 숫자 없는 줄(인쇄 전 검사가 숫자를 막는다)


class RecordedCall(CoreModel):
    purpose: Purpose
    section: str | None
    attempt: int = Field(ge=1)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: GenResult
    injected: bool = False


class Recording(CoreModel):
    sample_id: str
    recorded_at: datetime
    source: Literal["recorded", "handwritten"]
    provider: str
    model: str
    prompt_ver: str
    rules_ver: str
    as_of: str
    input_hash: str
    calls: tuple[RecordedCall, ...]


def load_recording(path: Path) -> Recording:
    return Recording.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_text_atomic(path: Path, text: str) -> None:
    """같은 폴더의 임시 파일에 쓰고 os.replace로 바꾼다(중간에 멈춰도 반쪽 파일이 남지 않는다)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save_recording(rec: Recording, path: Path) -> None:
    write_text_atomic(path, rec.model_dump_json(indent=2) + "\n")


def banner_for(rec: Recording) -> str:
    head = BANNER_HANDWRITTEN if rec.source == "handwritten" else BANNER_RECORDED
    return f"{head} · {rec.recorded_at.strftime('%Y-%m-%d %H:%M')} · {rec.provider} · {rec.model}"


class ReplayClient:
    """녹화한 답만 돌려주는 LLMClient. served = 지금까지 돌려준 (purpose, 구획, 주입 여부) 순서(검수 화면의 "주입" 표시용)."""

    def __init__(self, recording: Recording):
        self.recording = recording
        self.provider, self.model = recording.provider, recording.model
        self._inner = ScriptedClient(_ScriptedRecording(
            provider=recording.provider, model=recording.model, recorded_at=recording.recorded_at,
            calls=tuple(_ScriptedCall(input_hash=c.request_hash, response=c.response) for c in recording.calls)))
        self._injected: dict[str, bool] = {}
        for c in recording.calls:
            self._injected.setdefault(c.request_hash, c.injected)
        self.served: list[tuple[str, str | None, bool]] = []

    def generate(self, req: GenRequest) -> GenResult:
        result = self._inner.generate(req)          # 녹화에 없으면 ReplayMismatch
        self.served.append((req.purpose, req.section, self._injected.get(input_hash(build_payload(req)), False)))
        return result

    def banner_text(self) -> str:
        return banner_for(self.recording)


__all__ = ["REPLAY_MISMATCH_MESSAGE", "PAPER_LINE", "RecordedCall", "Recording", "ReplayClient", "ReplayMismatch",
           "load_recording", "save_recording", "write_text_atomic", "banner_for"]
