"""상담 설명 단계(Task 28) 시험 픽스처. FS_P4·FS_T1은 실제 표·스냅샷으로 build_fact_sheet가 만든 FactSheet다.

근거(CTX_*)는 core.pipeline.narrative_input이 만들고 별칭 규칙도 그쪽 것이다.
녹화(recording)는 narrate가 내는 요청을 그대로 해시해 만든다(요청이 바뀌면 녹화도 함께 바뀐다).
"""
import json
from datetime import datetime

from conftest import AS_OF, P4_KWARGS, ROOT, T1_KWARGS

from app.agents.counsel import build_request
from app.agents.llm.base import GenRequest, GenResult
from app.agents.llm.payload import build_payload, input_hash
from app.agents.llm.scripted import RecordedCall, Recording
from app.core.models import FarmProfile
from app.core.pipeline import build_fact_sheet, narrative_input
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables

BUNDLE = load_tables(ROOT / "data" / "tables", AS_OF)
SNAP = load_snapshot(ROOT / "data" / "snapshot", AS_OF, crops=BUNDLE.crops)
PASS_VERDICT = '{"verdict": "PASS", "reason_code": null}'

FS_P4 = build_fact_sheet(FarmProfile(**P4_KWARGS), BUNDLE, SNAP, AS_OF, "test")
FS_T1 = build_fact_sheet(FarmProfile(**T1_KWARGS), BUNDLE, SNAP, AS_OF, "test")
CTX_P4 = narrative_input(FS_P4)
CTX_T1 = narrative_input(FS_T1)


def good_section(kind: str, ctx=CTX_P4) -> str:
    """kind 구획의 규칙을 통과하는 문장 하나(첫 근거를 인용)."""
    item = next(i for i in ctx.items if i.section == kind)
    text = {"support": "{P:%s}은 맞는지 창구에서 확인해 보세요.",
            "insurance": "{P:%s}은 가입할 수 있는 때를 농협 창구에서 알아보세요.",
            "action": "{P:%s}부터 챙기면 다른 제도 신청이 쉬워져요.",
            "empty": "{P:%s}은 그대로 이어가세요."}[kind] % item.program_id
    return json.dumps({"section": kind, "sentences": [{"sid": 1, "text": text, "cites": [item.fact_id]}]}, ensure_ascii=False)


BAD_SUPPORT = json.dumps({"section": "support", "sentences": [
    {"sid": 1, "text": "신청하시면 오십만 원을 받으실 수 있습니다.", "cites": [CTX_P4.items[0].fact_id]}]}, ensure_ascii=False)


def _result(text: str) -> GenResult:
    return GenResult(text=text, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0, provider="rec", model="rec")


def recording(ctx, replies: dict[str, list[str]], feedback_for: dict[str, list] | None = None) -> Recording:
    """구획마다 [첫 답, 재생성 답…]을 녹화한다. 재생성 요청은 앞선 후보의 규칙 지적(Feedback)에 따라 달라지므로
    feedback_for[kind]에 그 지시문(build_feedback 결과)을 순서대로 준다."""
    calls = []
    for kind, texts in replies.items():
        reqs = [build_request(kind, ctx)] + [build_request(kind, ctx, fb) for fb in (feedback_for or {}).get(kind, [])]
        for req, text in zip(reqs, texts):
            calls.append(RecordedCall(input_hash=input_hash(build_payload(req)), response=_result(text)))
    return Recording(provider="rec", model="rec", recorded_at=datetime(2026, 11, 8), calls=tuple(calls))


class JudgeRouter:
    """purpose="judge" 요청은 verdicts[구획]의 답을 차례로(없으면 통과) 돌려주고, 나머지는 녹화(ScriptedClient)에 맡긴다.
    받은 요청을 모두 requests에 쌓는다(호출 수·재생성 지시문 확인용)."""

    def __init__(self, scripted, verdicts: dict[str, list[str]] | None = None) -> None:
        self.scripted, self.verdicts = scripted, {k: list(v) for k, v in (verdicts or {}).items()}
        self.requests: list[GenRequest] = []
        self.provider, self.model = scripted.provider, scripted.model

    @property
    def judge_calls(self) -> int:
        return sum(r.purpose == "judge" for r in self.requests)

    def generate(self, req: GenRequest) -> GenResult:
        self.requests.append(req)
        if req.purpose == "judge":
            queue = self.verdicts.get(req.section or "", [])
            return _result(queue.pop(0) if queue else PASS_VERDICT)
        return self.scripted.generate(req)


class FakeClock:
    """주입용 시계. advance로만 흐른다."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ClockedClient:
    """호출마다 세고, after_calls번째 호출이 끝나면 시계를 jump초 앞으로 보내는 클라이언트 장식자."""

    def __init__(self, inner, clock: FakeClock, after_calls: int, jump: float = 50.0) -> None:
        self.inner, self.clock, self.after_calls, self.jump, self.calls = inner, clock, after_calls, jump, 0
        self.provider, self.model = inner.provider, inner.model

    def generate(self, req: GenRequest) -> GenResult:
        self.calls += 1
        res = self.inner.generate(req)
        if self.calls == self.after_calls:
            self.clock.advance(self.jump)
        return res
