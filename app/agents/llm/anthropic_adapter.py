"""Anthropic 어댑터(Task 31, U31) — 공식 anthropic SDK의 Messages API로 GenRequest를 보낸다.

- 지연 import: SDK는 AnthropicClient.__init__ 안에서만 가져온다. 이 모듈을 import하는 것만으로는
  SDK가 필요 없다. SDK가 없으면 LLMUnavailable("NETWORK", "SDK_MISSING: …")가 올라온다
  (사유 코드 목록은 base.UnavailableReason 고정이라 새 코드를 만들지 않았다. 메시지가 requirements.txt를 알려 준다).
- generate() 첫 줄에서 build_payload(req)로 거름망을 지난 Payload를 만들고, 그것만으로 요청을 조립한다.
- 요청 조립: model(생성자, 기본 claude-opus-5-5) · max_tokens = min(req.max_output_tokens, MAX_TOKENS_CAP=1024)
  (짧은 한국어 구획 한 토막이면 충분. 1024는 narrate·notice 상한이고, purpose="judge"는 구조화 판정 답이 길어
  2048까지, purpose="notice"는 도구 입력(초안 JSON)이 길어 4096까지 허용한다. 요청이 더 작게 달라면 그 값을 쓴다) · system · messages(글·tool_use·tool_result 블록) ·
  tools(input_schema 그대로) + tool_choice={"type":"auto"}(도구가 있을 때만) ·
  output_config={"format":{"type":"json_schema","schema":…}}(response_schema가 있을 때. 설치된 SDK가
  output_config를 모르면 시스템 글에 "JSON만 답하라"를 덧붙이는 대체 경로를 쓰고 호출 쪽이 파싱한다) ·
  timeout=req.timeout_s(요청별, Task 29 루프가 의존) · SDK 재시도 끔(max_retries=0: 재시도는 Guard·루프가 한다).
  effort는 보내지 않는다(제공자 사상 없음, 무시).
- 오류 사상(UI 배너용 한국어 한 줄을 detail에 담는다. 요청 내용·키는 담지 않는다):
  stop_reason "refusal" → REFUSAL · 429 → RATE_LIMIT · 529/overloaded → OVERLOADED · 401/403 → AUTH ·
  HTTP 402 또는 "credit balance" 문구 → BILLING(다른 400은 BILLING이 아니다) · 시간 초과 → TIMEOUT · 연결 실패와 그 밖의 SDK 오류 → NETWORK.
- 응답 stop_reason: end_turn/stop_sequence → end · tool_use → tool · max_tokens·model_context_window_exceeded → length ·
  pause_turn → end(서버 도구가 잠시 멈춘 것: 이 앱은 서버 도구를 안 쓰므로 받은 글까지만 쓰고 끝낸 것으로 본다).
- 차단기(스레드 안전: 세기는 threading.Lock으로 지킨다): 연속 BREAKER_LIMIT(3)번 서비스 실패(거절·거름망 거부 제외) 뒤에는 SDK를 부르지 않고
  LLMUnavailable("CIRCUIT_OPEN")로 바로 실패한다. 성공하면 세기를 0으로, reset()으로도 푼다.
- 쓰인 토큰은 GenResult.tok_in/tok_out에 담는다. 요청 내용은 어디에도 기록하지 않는다.
"""
import inspect
import logging
import threading
import time
from typing import Any

from app.agents.llm.base import PUBLIC_TEXT_PURPOSES, GenResult, GenRequest, LLMUnavailable, StopReason, ToolCall, UnavailableReason
from app.agents.llm.payload import Payload, build_payload

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS_CAP = 1024
MAX_TOKENS_CAP_JUDGE = 2048          # purpose="judge" 구조화 답은 조금 더 길다
MAX_TOKENS_CAP_NOTICE = 4096         # purpose="notice" 도구 입력(초안 JSON)이 길다. 1024면 tool_use 입력이 잘려 빈 인자가 온다(2026-11-10 실호출에서 확인)
BREAKER_LIMIT = 3
JSON_ONLY_NOTE = "\n\n반드시 주어진 JSON 스키마에 맞는 JSON 하나만 답하세요. 다른 글은 쓰지 마세요."

BANNER: dict[str, str] = {
    "REFUSAL": "AI가 이 문장을 쓰지 않았습니다. 이번 실행만 템플릿으로 진행합니다.",
    "RATE_LIMIT": "AI 요청이 너무 많습니다. 이번 실행만 템플릿으로 진행합니다.",
    "OVERLOADED": "AI 서버가 바쁩니다. 이번 실행만 템플릿으로 진행합니다.",
    "AUTH": "AI 키가 올바르지 않습니다. 키를 확인하세요. 이번 실행만 템플릿으로 진행합니다.",
    "BILLING": "AI 사용 한도(크레딧)가 부족합니다. 이번 실행만 템플릿으로 진행합니다.",
    "TIMEOUT": "AI 응답이 늦습니다. 이번 실행만 템플릿으로 진행합니다.",
    "NETWORK": "AI에 연결하지 못했습니다. 이번 실행만 템플릿으로 진행합니다.",
    "CIRCUIT_OPEN": "AI 호출이 연달아 실패해 이번 실행은 템플릿으로 진행합니다.",
    "SDK_MISSING": "anthropic 부품이 설치되지 않았습니다. requirements.txt대로 설치하세요. 이번 실행만 템플릿으로 진행합니다.",
}

_log = logging.getLogger(__name__)

# 제공자 구조화 출력이 받지 않는 JSON 스키마 키워드(실호출 400: maxItems 등). 길이·개수는 우리 쪽 검사가 지킨다.
_UNSUPPORTED_SCHEMA_KEYS = frozenset({"maxItems", "minItems", "maxLength", "minLength", "minimum", "maximum",
                                      "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "maxProperties", "minProperties"})


def provider_schema(schema: Any) -> Any:
    """스키마 복사본에서 제공자가 거절하는 키워드를 뺀다(원본은 그대로)."""
    if isinstance(schema, dict):
        return {k: provider_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [provider_schema(v) for v in schema]
    return schema


def _unavailable(reason: UnavailableReason) -> LLMUnavailable:
    return LLMUnavailable(reason, BANNER[reason])


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, key: str, model: str = DEFAULT_MODEL, *, client: Any | None = None):
        self.model = model
        self._failures = 0
        self._lock = threading.Lock()
        if client is not None:                     # 시험용 가짜
            self._client = client
        else:
            try:
                import anthropic
            except ImportError as e:
                raise LLMUnavailable("NETWORK", "SDK_MISSING: " + BANNER["SDK_MISSING"]) from e
            self._client = anthropic.Anthropic(api_key=key, max_retries=0)
        self._supports_output_config = self._detect_output_config()

    def reset(self) -> None:
        with self._lock:
            self._failures = 0

    @property
    def failures(self) -> int:
        return self._failures

    def generate(self, req: GenRequest) -> GenResult:
        payload = build_payload(req)               # 첫 줄: 거름망. PayloadRejected는 차단기에 세지 않는다
        with self._lock:
            if self._failures >= BREAKER_LIMIT:
                raise _unavailable("CIRCUIT_OPEN")
        kwargs = self.build_kwargs(payload)
        started = time.monotonic()
        try:
            resp = self._client.messages.create(**kwargs)
        except Exception as e:
            with self._lock:
                self._failures += 1
            raise self._map_error(e) from None
        if getattr(resp, "stop_reason", None) == "refusal":
            raise _unavailable("REFUSAL")          # 서비스 실패가 아니라 모델의 거절: 차단기에 세지 않는다
        with self._lock:
            self._failures = 0
        return self._parse(resp, int((time.monotonic() - started) * 1000))

    # --- 요청 조립 ---------------------------------------------------------------------------

    def build_kwargs(self, p: Payload) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": min(p.max_output_tokens, MAX_TOKENS_CAP_JUDGE if p.purpose == "judge" else MAX_TOKENS_CAP_NOTICE if p.purpose in PUBLIC_TEXT_PURPOSES else MAX_TOKENS_CAP),
            "system": p.system,
            "messages": [_message(m) for m in p.messages],
            "timeout": p.timeout_s,
        }
        if p.tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                               for t in p.tools]
            kwargs["tool_choice"] = {"type": "auto"}
        if p.response_schema is not None:
            if self._supports_output_config:
                kwargs["output_config"] = {"format": {"type": "json_schema", "schema": provider_schema(p.response_schema)}}
            else:
                kwargs["system"] = p.system + JSON_ONLY_NOTE
        return kwargs

    def _detect_output_config(self) -> bool:
        try:
            return "output_config" in inspect.signature(self._client.messages.create).parameters
        except (TypeError, ValueError, AttributeError):
            return True

    # --- 응답·오류 ---------------------------------------------------------------------------

    def _parse(self, resp: Any, latency_ms: int) -> GenResult:
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in getattr(resp, "content", None) or ():
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "tool_use":
                calls.append(ToolCall(call_id=block.id, name=block.name, args=dict(block.input)))
        raw = getattr(resp, "stop_reason", None)
        stop: StopReason = "tool" if raw == "tool_use" or calls else "length" if raw in ("max_tokens", "model_context_window_exceeded") else "end"   # pause_turn 포함
        usage = getattr(resp, "usage", None)
        return GenResult(text="".join(texts) or None, tool_calls=tuple(calls), stop=stop,
                         tok_in=int(getattr(usage, "input_tokens", 0) or 0),
                         tok_out=int(getattr(usage, "output_tokens", 0) or 0),
                         latency_ms=latency_ms, provider=self.provider, model=self.model)

    def _map_error(self, e: Exception) -> LLMUnavailable:
        import anthropic
        if isinstance(e, anthropic.APITimeoutError):
            return _unavailable("TIMEOUT")
        if isinstance(e, anthropic.APIConnectionError):
            return _unavailable("NETWORK")
        status = getattr(e, "status_code", None)
        msg = str(getattr(e, "message", "") or e).lower()
        if status == 429:
            return _unavailable("RATE_LIMIT")
        if status == 529 or isinstance(e, anthropic.OverloadedError) or "overloaded" in msg:
            return _unavailable("OVERLOADED")
        if status == 402 or "credit balance" in msg:
            return _unavailable("BILLING")
        if status in (401, 403):
            return _unavailable("AUTH")
        _log.warning("anthropic 호출 실패: %s", type(e).__name__)   # 종류만. 내용·키 없음
        return _unavailable("NETWORK")


def _message(m: Any) -> dict[str, Any]:
    if m.text is not None and not m.tool_calls and not m.tool_results:
        return {"role": m.role, "content": m.text}
    blocks: list[dict[str, Any]] = []
    if m.text is not None:
        blocks.append({"type": "text", "text": m.text})
    blocks += [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args} for c in m.tool_calls]
    blocks += [{"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
               for r in m.tool_results]
    return {"role": m.role, "content": blocks}
