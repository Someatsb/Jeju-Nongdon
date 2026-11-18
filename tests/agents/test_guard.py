"""LLM 클라이언트(Task 9): 키 없음 · 녹화 재생 · 틀린 문장 주입 · 하루 상한 · 설명 예산."""
from datetime import date

import pytest
from review_fixtures import CONTEXTS

from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable, Msg
from app.agents.llm.fault import FaultInjectClient
from app.agents.llm.guard import Guard
from app.agents.llm.null import NullClient
from app.agents.llm.payload import PayloadRejected, build_payload, input_hash
from app.agents.llm.scripted import RecordedCall, Recording, ReplayMismatch, ScriptedClient
from app.agents.rules import Section, Sentence, parse_section

D = date(2026, 11, 13)
SYSTEM = "어르신께 드릴 설명 문장을 쓰세요."
REQ = GenRequest(purpose="narrate", section="support", system=SYSTEM, messages=(Msg(role="user", text="구획을 쓰세요."),))


def req(**changes) -> GenRequest:
    return GenRequest(**{**REQ.model_dump(), **changes})


def req_for(ctx_name: str) -> GenRequest:
    return req(messages=(Msg(role="user", text=CONTEXTS[ctx_name].model_dump_json()),))


def result(text: str, provider: str = "anthropic") -> GenResult:
    return GenResult(text=text, tool_calls=(), stop="end", tok_in=3610, tok_out=512, latency_ms=7420,
                     provider=provider, model="claude-opus-5-5")


GOOD_P4 = result('{"section":"support","sentences":[{"sid":1,"text":"{P:logistics}은 농협에 물어보실 수 있습니다.",'
                 '"cites":["M:logistics"]}]}')
REC_P4 = Recording(provider="anthropic", model="claude-opus-5-5", recorded_at="2026-11-08T10:00:00+09:00",
                   calls=(RecordedCall(input_hash=input_hash(build_payload(req_for("ctx_P4"))), response=GOOD_P4),))
BAD_SUPPORT = Section(section="support", sentences=(
    Sentence(sid=1, text="농민수당 50만 원을 확정적으로 받으실 수 있습니다.", cites=("M:jeju_farmer_allowance",)),))


class CountingClient:
    provider = "counting"
    model = "fake"

    def __init__(self):
        self.calls = 0

    def generate(self, req: GenRequest) -> GenResult:
        self.calls += 1
        return result("{}", provider=self.provider)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# --- 키 없음 ---------------------------------------------------------------------------------

def test_null_client_raises_no_key():
    with pytest.raises(LLMUnavailable) as e:
        NullClient().generate(REQ)
    assert e.value.reason == "NO_KEY"


def test_unavailable_reason_must_be_known():
    with pytest.raises(ValueError):
        LLMUnavailable("SOMETHING")


# --- 녹화 재생 --------------------------------------------------------------------------------

def test_scripted_replays_recorded_response():
    client = ScriptedClient(REC_P4)
    assert client.generate(req_for("ctx_P4")) == GOOD_P4
    assert (client.provider, client.model) == ("anthropic", "claude-opus-5-5")


def test_scripted_rejects_other_input():
    with pytest.raises(ReplayMismatch) as e:
        ScriptedClient(REC_P4).generate(req_for("ctx_P1"))
    assert e.value.input_hash == input_hash(build_payload(req_for("ctx_P1")))


def test_replay_mismatch_is_llm_unavailable():
    """일반 except LLMUnavailable은 템플릿으로 가고, 재생 모드(Task 32)는 ReplayMismatch를 먼저 잡는다."""
    e = ReplayMismatch("a" * 64)
    assert isinstance(e, LLMUnavailable) and e.reason == "REPLAY_MISMATCH" and e.input_hash == "a" * 64
    with pytest.raises(LLMUnavailable):
        ScriptedClient(REC_P4).generate(req_for("ctx_P1"))


def test_scripted_goes_through_the_payload_gate():
    with pytest.raises(PayloadRejected):
        ScriptedClient(REC_P4).generate(req(system="애월읍 농가입니다"))


def test_recording_round_trips_as_json():
    assert Recording.model_validate_json(REC_P4.model_dump_json()) == REC_P4
    with pytest.raises(ValueError):
        RecordedCall(input_hash="not-a-hash", response=GOOD_P4)


# --- 틀린 문장 주입 ---------------------------------------------------------------------------

def test_fault_inject_first_attempt_of_one_section_only():
    inner = CountingClient()
    fault = FaultInjectClient(inner, first_attempt_bad=BAD_SUPPORT)
    assert fault.generate(req(purpose="judge")).provider == "counting"       # 판정 요청은 주입하지 않음
    assert fault.generate(req(section="insurance")).provider == "counting"   # 다른 구획도 그대로
    first, second = fault.generate(REQ), fault.generate(REQ)
    assert parse_section(first.text) == (BAD_SUPPORT, [])
    assert (first.provider, first.model, first.tok_in, first.tok_out, first.latency_ms) == ("fault-inject(counting)", "fake", 0, 0, 0)
    assert second.provider == "counting" and inner.calls == 3
    assert (fault.provider, fault.model) == ("fault-inject(counting)", "fake")


# --- 하루 상한 · 설명 예산 ----------------------------------------------------------------------

def test_guard_daily_cap():
    g = Guard(CountingClient(), daily_cap=2, today_fn=lambda: D)
    g.generate(REQ); g.generate(REQ)
    with pytest.raises(LLMUnavailable) as e:
        g.generate(REQ)
    assert e.value.reason == "DAILY_CAP"


def test_guard_cap_resets_on_a_new_day_and_refused_calls_never_reach_the_client():
    inner, days = CountingClient(), [D]
    g = Guard(inner, daily_cap=1, today_fn=lambda: days[0])
    g.generate(REQ)
    with pytest.raises(LLMUnavailable):
        g.generate(REQ)
    days[0] = date(2026, 11, 14)
    g.generate(REQ)
    assert inner.calls == 2


def test_guard_is_an_llm_client_and_composes():
    """Guard는 LLMClient 모양이라 장식자로 감쌀 수 있고, provider·model은 안쪽 것을 그대로 보인다."""
    inner = CountingClient()
    g = Guard(inner, today_fn=lambda: D)
    assert (g.provider, g.model) == ("counting", "fake")
    fault = FaultInjectClient(g, first_attempt_bad=BAD_SUPPORT)
    assert fault.provider == "fault-inject(counting)"
    assert parse_section(fault.generate(REQ).text) == (BAD_SUPPORT, [])
    assert fault.generate(REQ).provider == "counting" and inner.calls == 1


def test_guard_budget_window():
    clock, inner = FakeClock(), CountingClient()
    g = Guard(inner, budget_s=45, today_fn=lambda: D, clock=clock)
    clock.t += 1000
    g.generate(REQ)                              # 창 밖에서는 예산 없음(헛 TIMEOUT 없음)
    with g.budget():
        clock.t += 44
        g.generate(REQ)
        clock.t += 1
        with pytest.raises(LLMUnavailable) as e:
            g.generate(REQ)
        assert e.value.reason == "TIMEOUT" and inner.calls == 2
    clock.t += 1000
    g.generate(REQ)                              # 창이 닫히면 다시 예산 없음
    with g.budget():                             # 다음 상담은 새 창
        g.generate(REQ)
    assert inner.calls == 4


def test_guard_start_budget_alias_opens_a_window():
    clock = FakeClock()
    g = Guard(CountingClient(), budget_s=45, today_fn=lambda: D, clock=clock)
    g.start_budget()
    clock.t += 45
    with pytest.raises(LLMUnavailable) as e:
        g.generate(REQ)
    assert e.value.reason == "TIMEOUT"


def test_guard_passes_client_errors_through():
    with pytest.raises(LLMUnavailable) as e:
        Guard(NullClient(), today_fn=lambda: D).generate(REQ)
    assert e.value.reason == "NO_KEY"
