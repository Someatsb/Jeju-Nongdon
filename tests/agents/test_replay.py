"""재생 모드(Task 32): 녹화 형식, ReplayClient, 띠 문구, 공장 연결."""
import json
from datetime import datetime

import pytest

from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable, Msg
from app.agents.llm.factory import make_llm_client
from app.agents.llm.keystore import KeyStore
from app.agents.llm.payload import build_payload, input_hash
from app.agents.llm.recording import (REPLAY_MISMATCH_MESSAGE, RecordedCall, Recording, ReplayClient,
                                      load_recording, save_recording)
from app.agents.llm.scripted import ReplayMismatch

REQ = GenRequest(purpose="narrate", system="한 문장만 쓰세요.", messages=(Msg(role="user", text="인사해 주세요."),),
                 section="action")
OTHER = GenRequest(purpose="narrate", system="두 문장 쓰세요.", messages=(Msg(role="user", text="인사해 주세요."),))


def result(text: str) -> GenResult:
    return GenResult(text=text, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0,
                     provider="handwritten", model="demo")


def make(source="handwritten", **kw) -> Recording:
    call = RecordedCall(purpose="narrate", section="action", attempt=1,
                        request_hash=input_hash(build_payload(REQ)), response=result("안녕하세요."), injected=False)
    base = dict(sample_id="P9", recorded_at=datetime(2026, 11, 8, 9, 30), source=source, provider="handwritten",
                model="demo-script", prompt_ver="narrate-v2", rules_ver="r1", as_of="2026-11-13",
                input_hash="abcd1234", calls=(call,))
    return Recording(**(base | kw))


def test_recording_json_round_trip(tmp_path):
    rec = make()
    path = tmp_path / "P9.json"
    save_recording(rec, path)
    assert load_recording(path) == rec
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"sample_id", "recorded_at", "source", "provider", "model", "prompt_ver", "rules_ver",
                        "as_of", "input_hash", "calls"}
    assert set(raw["calls"][0]) == {"purpose", "section", "attempt", "request_hash", "response", "injected"}
    assert "\r" not in path.read_text(encoding="utf-8")


def test_recording_rejects_unknown_source():
    with pytest.raises(ValueError):
        make(source="live")


def test_replay_client_serves_by_request_hash():
    c = ReplayClient(make())
    assert c.generate(REQ).text == "안녕하세요."
    assert c.generate(REQ).text == "안녕하세요."          # 상태 없음: 몇 번 불러도 같은 답


def test_replay_mismatch_message_and_reason():
    c = ReplayClient(make())
    with pytest.raises(ReplayMismatch) as e:
        c.generate(OTHER)
    assert isinstance(e.value, LLMUnavailable) and e.value.reason == "REPLAY_MISMATCH"
    assert REPLAY_MISMATCH_MESSAGE == "녹화와 입력이 다릅니다. 시연 농가 P1~P5를 고르세요"


def test_banner_text_recorded_and_handwritten():
    rec = ReplayClient(make("recorded", provider="anthropic", model="claude-x")).banner_text()
    assert rec == "녹화 응답 재생 중 — 실제 LLM 호출 아님 · 2026-11-08 09:30 · anthropic · claude-x"
    hand = ReplayClient(make("handwritten")).banner_text()
    assert hand == "손으로 쓴 시연 응답 재생 — 실제 LLM 호출 아님 · 2026-11-08 09:30 · handwritten · demo-script"


def test_replay_client_reports_injected_flags():
    rec = make()
    bad = rec.calls[0].model_copy(update={"injected": True})
    c = ReplayClient(rec.model_copy(update={"calls": (bad,)}))
    c.generate(REQ)
    assert c.served == [("narrate", "action", True)]


def test_factory_returns_replay_client_even_with_a_key(tmp_path):
    class Ring:
        def get_password(self, service, username):
            return "key-test-1234"

    path = tmp_path / "P9.json"
    save_recording(make(), path)
    c = make_llm_client(KeyStore(backend=Ring()), replay=path)
    assert isinstance(c, ReplayClient)
    assert c.generate(REQ).text == "안녕하세요."
    with pytest.raises(ReplayMismatch):
        c.generate(OTHER)            # 키가 있어도 실제 호출 길로 새지 않는다
