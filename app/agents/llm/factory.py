"""LLM 클라이언트 공장(Task 31). UI(app.state.narrator)와 notice CLI가 이 한 곳에서 클라이언트를 얻는다.

- 키가 없으면(KeyStore.get("llm") 없음) NullClient(부르면 LLMUnavailable("NO_KEY")).
- provider(기본 KeyStore.get_setting("JC_LLM_PROVIDER")="anthropic") + 키 → Guard(AnthropicClient(키, 모델)).
  model 기본은 get_setting("JC_LLM_MODEL"). anthropic 부품이 없으면 AnthropicClient가 낸 LLMUnavailable을
  그 사유 그대로 매번 올리는 클라이언트로 바꿔 앱이 템플릿으로 계속 돌게 한다.
- 모르는 provider는 한국어 설명을 단 클라이언트(사유 NETWORK). 키는 어디에도 출력하지 않는다.
- replay(녹화 파일 경로)를 주면 열쇠·제공자와 상관없이 ReplayClient(Task 32). 실제 클라이언트는 만들지 않는다.
- today_fn은 하루 상한용 날짜(기본: config의 오늘 읽는 곳 하나). 화면은 config.as_of를 넘길 수 있다.
"""
from collections.abc import Callable
from datetime import date
from pathlib import Path

from app import config
from app.agents.llm.anthropic_adapter import AnthropicClient
from app.agents.llm.base import GenRequest, GenResult, LLMClient, LLMUnavailable, UnavailableReason
from app.agents.llm.guard import Guard
from app.agents.llm.keystore import KeyStore
from app.agents.llm.null import NullClient
from app.agents.llm.recording import ReplayClient, load_recording


class UnavailableClient:
    """늘 정해진 사유로 실패하는 클라이언트(NullClient의 사유 지정판)."""

    model = "none"

    def __init__(self, reason: UnavailableReason, detail: str, provider: str = "none"):
        self.provider = provider
        self.reason = reason
        self.detail = detail

    def generate(self, req: GenRequest) -> GenResult:
        raise LLMUnavailable(self.reason, self.detail)


def make_llm_client(store: KeyStore, *, provider: str | None = None, model: str | None = None,
                    today_fn: Callable[[], date] | None = None, replay: Path | None = None) -> LLMClient:
    if replay is not None:     # 재생 모드(Task 32): 열쇠가 있어도 녹화 답만 쓴다. 아래 실제 호출 길에는 닿지 않는다
        return ReplayClient(load_recording(replay))
    key = store.get("llm")
    if not key:
        return NullClient()
    provider = (provider or store.get_setting("JC_LLM_PROVIDER")).strip().lower()
    if provider != "anthropic":
        return UnavailableClient("NETWORK", f"알 수 없는 AI 제공자입니다({provider}). 이번 실행만 템플릿으로 진행합니다.")
    try:
        inner = AnthropicClient(key, model or store.get_setting("JC_LLM_MODEL"))
    except LLMUnavailable as e:
        return UnavailableClient(e.reason, e.detail, provider="anthropic")
    return Guard(inner, today_fn=today_fn or (config.today_fn))
