"""공고 에이전트 루프(Task 29) 시험 픽스처.

REC_N1·REC_N6은 '말하는 쪽'의 답 목록(SCRIPT_*)을 loop가 내는 요청에 맞춰 해시해 만든 녹화다(요청이 바뀌면 녹화도 함께 바뀐다).
GOLDEN_DRAFT_N1은 tests/fixtures/notices/GOLDEN_DRAFT_N1.json(N1 원문 인용으로 만든 정답 초안)이다.
"""
import json
from datetime import datetime

from notice_fixtures import BUNDLE, DOC_N1, DRAFT_N1_GOOD, LOGI, NOTICES, extract

from app.agents.llm.base import GenRequest, GenResult, ToolCall
from app.agents.llm.payload import build_payload, input_hash
from app.agents.llm.scripted import RecordedCall, Recording
from app.agents.notice import NoticeResult, run_notice
from app.tools.models import ToolLog

DOC_N5 = extract(NOTICES / "N5.txt")
DOC_N6 = extract(NOTICES / "N6.txt")
DOC_N8 = extract(NOTICES / "N8.pdf")
GOLDEN_DRAFT_N1 = NoticeResult.model_validate_json((NOTICES / "GOLDEN_DRAFT_N1.json").read_text(encoding="utf-8"))


def result(calls: tuple[ToolCall, ...] = (), text: str | None = None) -> GenResult:
    return GenResult(text=text, tool_calls=calls, stop="tool" if calls else "end", tok_in=0, tok_out=0,
                     latency_ms=0, provider="rec", model="rec")


def call(n: int, tool: str, /, **args) -> ToolCall:
    return ToolCall(call_id=f"c{n}", name=tool, args=args)


SCRIPT_N1 = [
    result((call(1, "doc_search", query="신청기간"),)),
    result((call(2, "find_existing_program", name="물류비 지원사업", agency="감귤유통과"),)),
    result((call(3, "validate_draft", draft=DRAFT_N1_GOOD.model_dump(mode="json")),)),
    result((call(4, "finish", decision="DRAFT_READY", reason=GOLDEN_DRAFT_N1.reason),)),
]
SCRIPT_N6 = [
    result((call(1, "doc_search", query="농업인 신청자격"),)),
    result((call(2, "finish", decision="NOT_RELEVANT", reason="농협 입찰 공고라 개인 농업인 지원이 아닙니다"),)),
]


class RecordingClient:
    """정해진 답을 차례로 내면서 (요청 해시, 답)을 녹화한다."""
    provider = model = "rec"

    def __init__(self, script: list[GenResult]):
        self.script, self.calls = list(script), []

    def generate(self, req: GenRequest) -> GenResult:
        res = self.script.pop(0)
        self.calls.append(RecordedCall(input_hash=input_hash(build_payload(req)), response=res))
        return res

    def recording(self) -> Recording:
        return Recording(provider="rec", model="rec", recorded_at=datetime(2026, 11, 8), calls=tuple(self.calls))


def record(doc, script) -> Recording:
    rc = RecordingClient(script)
    run_notice(doc, BUNDLE, rc, ToolLog())
    return rc.recording()


REC_N1 = record(DOC_N1, SCRIPT_N1)
REC_N6 = record(DOC_N6, SCRIPT_N6)


class CountingClient:
    provider = model = "count"

    def __init__(self):
        self.calls = 0

    def generate(self, req: GenRequest) -> GenResult:
        self.calls += 1
        raise AssertionError("LLM을 부르면 안 됩니다")


class LoopingClient:
    """끝내지 않고 doc_search만 계속 부른다."""
    provider = model = "loop"

    def __init__(self):
        self.calls = 0

    def generate(self, req: GenRequest) -> GenResult:
        self.calls += 1
        return result((call(self.calls, "doc_search", query="신청기간"),))


class FakeClock:
    def __init__(self, step: float):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def golden_json() -> str:
    return json.dumps(GOLDEN_DRAFT_N1.model_dump(mode="json"), ensure_ascii=False, indent=2)
