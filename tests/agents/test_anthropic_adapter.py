"""Anthropic 어댑터(Task 31). 네트워크 없이 messages.create에 넘어간 인자와 오류 사상만 검사한다.
실호출(live)은 키가 풀릴 때만 돈다. CI·키 없는 PC에서는 `pytest -m "not live"`로 뺀다. 가짜 키는 key-test-... 만 쓴다."""
import subprocess
import sys

import anthropic
import httpx2
import pytest

from app.agents.llm.anthropic_adapter import BREAKER_LIMIT, MAX_TOKENS_CAP, AnthropicClient
from app.agents.llm.base import GenRequest, LLMUnavailable, Msg, ToolCall, ToolDef, ToolResult
from app.agents.llm.keystore import KeyStore
from app.agents.llm.payload import PayloadRejected

REQ = GenRequest(purpose="narrate", system="짧고 쉬운 말로 한 문장만 쓰세요.",
                 messages=(Msg(role="user", text="올해 감귤 농사를 응원하는 말을 해 주세요."),))
REQUEST = httpx2.Request("POST", "https://api.test/v1/messages")


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Resp:
    def __init__(self, content=(), stop_reason="end_turn", tin=11, tout=7):
        self.content, self.stop_reason = list(content), stop_reason
        self.usage = Block(input_tokens=tin, output_tokens=tout)


class FakeMessages:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def create(self, *, model, max_tokens, messages, system=None, tools=None, tool_choice=None,
               output_config=None, timeout=None):
        self.calls.append(dict(model=model, max_tokens=max_tokens, messages=messages, system=system, tools=tools,
                               tool_choice=tool_choice, output_config=output_config, timeout=timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class OldMessages(FakeMessages):                   # output_config를 모르는 옛 SDK
    def create(self, *, model, max_tokens, messages, system=None, tools=None, tool_choice=None, timeout=None):
        return FakeMessages.create(self, model=model, max_tokens=max_tokens, messages=messages, system=system,
                                   tools=tools, tool_choice=tool_choice, timeout=timeout)


def client_with(outcome, cls=FakeMessages, **kw):
    fake = Block(messages=cls(outcome))
    return AnthropicClient("key-test-1234", client=fake, **kw), fake.messages


def text_resp(text="올해도 풍년이 되시길 바랍니다."):
    return Resp([Block(type="text", text=text)])


def http_error(cls, status, message="x"):
    return cls(message, response=httpx2.Response(status, request=REQUEST), body=None)


# --- 요청 조립 -------------------------------------------------------------------------------

def test_request_assembly_basic():
    c, m = client_with(text_resp())
    out = c.generate(REQ)
    call = m.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["system"] == REQ.system
    assert call["messages"] == [{"role": "user", "content": "올해 감귤 농사를 응원하는 말을 해 주세요."}]
    assert call["max_tokens"] == MAX_TOKENS_CAP <= 1024        # 요청 2000 -> 상한으로 깎는다
    assert call["timeout"] == REQ.timeout_s
    assert call["tools"] is None and call["tool_choice"] is None and call["output_config"] is None
    assert out.text == "올해도 풍년이 되시길 바랍니다." and (out.tok_in, out.tok_out) == (11, 7)
    assert (out.provider, out.model, out.stop) == ("anthropic", "claude-opus-5-5", "end")


def test_custom_model_small_max_tokens_and_timeout():
    c, m = client_with(text_resp(), model="claude-test-model")
    c.generate(REQ.model_copy(update={"max_output_tokens": 300, "timeout_s": 30.0}))
    assert (m.calls[0]["model"], m.calls[0]["max_tokens"], m.calls[0]["timeout"]) == ("claude-test-model", 300, 30.0)


def test_tools_and_tool_round_trip_translate():
    tool = ToolDef(name="lookup_help", description="도움 항목을 찾는다", input_schema={
        "type": "object", "properties": {"sid": {"type": "string"}}, "required": ["sid"]})
    msgs = (Msg(role="user", text="알아봐 주세요."),
            Msg(role="assistant", tool_calls=(ToolCall(call_id="tu_1", name="lookup_help", args={"sid": "A"}),)),
            Msg(role="user", tool_results=(ToolResult(call_id="tu_1", content="{}", is_error=False),)))
    c, m = client_with(text_resp())
    c.generate(REQ.model_copy(update={"tools": (tool,), "messages": msgs}))
    call = m.calls[0]
    assert call["tools"] == [{"name": "lookup_help", "description": "도움 항목을 찾는다",
                              "input_schema": tool.input_schema}]
    assert call["tool_choice"] == {"type": "auto"}
    assert call["messages"][1] == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "tu_1", "name": "lookup_help", "input": {"sid": "A"}}]}
    assert call["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "{}", "is_error": False}]}


def test_structured_output_uses_output_config():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    c, m = client_with(text_resp('{"ok": true}'))
    c.generate(REQ.model_copy(update={"response_schema": schema}))
    assert m.calls[0]["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert m.calls[0]["system"] == REQ.system


def test_structured_output_fallback_for_old_sdk():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    c, m = client_with(text_resp('{"ok": true}'), cls=OldMessages)
    c.generate(REQ.model_copy(update={"response_schema": schema}))
    assert "output_config" not in m.calls[0] or m.calls[0]["output_config"] is None
    assert "JSON" in m.calls[0]["system"] and m.calls[0]["system"].startswith(REQ.system)


def test_real_sdk_has_output_config_and_zero_retries():
    sdk = AnthropicClient("key-test-1234")
    assert sdk._supports_output_config is True
    assert sdk._client.max_retries == 0                 # 재시도는 Guard·루프 몫


def test_payload_filter_runs_first_and_is_not_counted():
    c, m = client_with(text_resp())
    bad = REQ.model_copy(update={"system": "연락처 010-1234-5678"})
    for _ in range(BREAKER_LIMIT + 1):
        with pytest.raises(PayloadRejected):
            c.generate(bad)
    assert m.calls == [] and c.failures == 0


# --- 응답 해석 -------------------------------------------------------------------------------

def test_parse_text_and_tool_use_blocks():
    resp = Resp([Block(type="text", text="찾아볼게요."),
                 Block(type="tool_use", id="tu_9", name="lookup_help", input={"sid": "B"})], stop_reason="tool_use")
    c, _ = client_with(resp)
    out = c.generate(REQ)
    assert out.text == "찾아볼게요." and out.stop == "tool"
    assert out.tool_calls == (ToolCall(call_id="tu_9", name="lookup_help", args={"sid": "B"}),)


def test_max_tokens_stop_is_length():
    c, _ = client_with(Resp([Block(type="text", text="짧")], stop_reason="max_tokens"))
    assert c.generate(REQ).stop == "length"


@pytest.mark.parametrize("raw, stop", [("model_context_window_exceeded", "length"), ("pause_turn", "end"),
                                       ("stop_sequence", "end")])
def test_other_stop_reasons(raw, stop):
    c, _ = client_with(Resp([Block(type="text", text="부분")], stop_reason=raw))
    assert c.generate(REQ).stop == stop


def test_judge_purpose_allows_2048_tokens_narrate_stays_1024():
    c, m = client_with(text_resp())
    c.generate(REQ.model_copy(update={"purpose": "judge", "max_output_tokens": 5000}))
    c.generate(REQ.model_copy(update={"max_output_tokens": 5000}))
    assert [x["max_tokens"] for x in m.calls] == [2048, 1024]


def test_breaker_counter_is_thread_safe():
    import threading
    c, _ = client_with(http_error(anthropic.RateLimitError, 429))
    def run():
        try:
            c.generate(REQ)
        except LLMUnavailable:
            pass
    ts = [threading.Thread(target=run) for _ in range(3)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert c.failures == 3


def test_refusal_maps_and_does_not_trip_breaker():
    c, _ = client_with(Resp([], stop_reason="refusal"))
    for _ in range(BREAKER_LIMIT + 1):
        with pytest.raises(LLMUnavailable) as e:
            c.generate(REQ)
        assert e.value.reason == "REFUSAL" and "템플릿" in e.value.detail


# --- 오류 사상·차단기 ------------------------------------------------------------------------

@pytest.mark.parametrize("error, reason", [
    (http_error(anthropic.RateLimitError, 429), "RATE_LIMIT"),
    (http_error(anthropic.APIStatusError, 529, "Overloaded"), "OVERLOADED"),
    (http_error(anthropic.AuthenticationError, 401), "AUTH"),
    (http_error(anthropic.PermissionDeniedError, 403), "AUTH"),
    (http_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "BILLING"),
    (http_error(anthropic.APIStatusError, 402, "payment"), "BILLING"),
    (http_error(anthropic.BadRequestError, 400, "billing_address is invalid field"), "NETWORK"),
    (anthropic.APITimeoutError(request=REQUEST), "TIMEOUT"),
    (anthropic.APIConnectionError(request=REQUEST), "NETWORK"),
    (RuntimeError("뭔가 터짐"), "NETWORK"),
])
def test_error_mapping_has_korean_banner(error, reason):
    c, _ = client_with(error)
    with pytest.raises(LLMUnavailable) as e:
        c.generate(REQ)
    assert e.value.reason == reason and "템플릿" in e.value.detail
    assert "key-test" not in str(e.value) and "올해" not in str(e.value)


def test_circuit_opens_after_three_failures_and_resets():
    c, m = client_with(http_error(anthropic.RateLimitError, 429))
    for _ in range(BREAKER_LIMIT):
        with pytest.raises(LLMUnavailable) as e:
            c.generate(REQ)
        assert e.value.reason == "RATE_LIMIT"
    with pytest.raises(LLMUnavailable) as e:
        c.generate(REQ)
    assert e.value.reason == "CIRCUIT_OPEN" and len(m.calls) == BREAKER_LIMIT   # 네 번째는 SDK를 안 부른다
    c.reset()
    m.outcome = text_resp()
    assert c.generate(REQ).text and c.failures == 0


def test_success_resets_failure_count():
    c, m = client_with(http_error(anthropic.RateLimitError, 429))
    for _ in range(BREAKER_LIMIT - 1):
        with pytest.raises(LLMUnavailable):
            c.generate(REQ)
    m.outcome = text_resp()
    c.generate(REQ)
    m.outcome = http_error(anthropic.RateLimitError, 429)
    for _ in range(BREAKER_LIMIT):
        with pytest.raises(LLMUnavailable) as e:
            c.generate(REQ)
        assert e.value.reason == "RATE_LIMIT"


# --- 지연 import -----------------------------------------------------------------------------

def test_module_import_does_not_import_sdk():
    code = ("import sys; import app.agents.llm.anthropic_adapter, app.agents.llm.factory; "
            "sys.exit(1 if 'anthropic' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_missing_sdk_is_llm_unavailable_naming_requirements(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)         # import anthropic -> ImportError
    with pytest.raises(LLMUnavailable) as e:
        AnthropicClient("key-test-1234")
    assert "SDK_MISSING" in e.value.detail and "requirements.txt" in e.value.detail


# --- 실호출 ----------------------------------------------------------------------------------

@pytest.mark.live
def test_live_one_tiny_korean_prompt():
    store = KeyStore()
    key = store.get("llm")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY 없음(keyring·환경변수·.env 어디에도)")
    client = AnthropicClient(key, store.get_setting("JC_LLM_MODEL"))
    out = client.generate(GenRequest(purpose="narrate", system="한국어로 아주 짧게 한 문장만 답하세요.",
                                     messages=(Msg(role="user", text="농사 잘 되시라는 인사를 해 주세요."),),
                                     max_output_tokens=200, timeout_s=30.0))
    assert out.text and out.text.strip()
