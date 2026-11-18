"""LLM 공장(Task 31): 키 없음 -> NullClient, anthropic+키 -> Guard(AnthropicClient), 모르는 제공자 -> 한국어 사유."""
from datetime import date

import pytest

from app.agents.llm.anthropic_adapter import AnthropicClient
from app.agents.llm.base import GenRequest, LLMUnavailable, Msg
from app.agents.llm.factory import make_llm_client
from app.agents.llm.guard import Guard
from app.agents.llm.keystore import KeyStore
from app.agents.llm.null import NullClient

REQ = GenRequest(purpose="narrate", system="한 문장만 쓰세요.", messages=(Msg(role="user", text="인사해 주세요."),))


class Ring:
    def __init__(self, key=None):
        self.key = key

    def get_password(self, service, username):
        return self.key if username == "llm" else None


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "JC_LLM_PROVIDER", "JC_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JC_ENV_FILE", str(tmp_path / "missing.env"))


def store(key=None):
    return KeyStore(backend=Ring(key))


def test_no_key_is_null_client():
    c = make_llm_client(store())
    assert isinstance(c, NullClient)
    with pytest.raises(LLMUnavailable) as e:
        c.generate(REQ)
    assert e.value.reason == "NO_KEY"


def test_anthropic_with_key_is_guarded_adapter_with_default_model():
    c = make_llm_client(store("key-test-1234"), today_fn=lambda: date(2026, 11, 13))
    assert isinstance(c, Guard) and isinstance(c.client, AnthropicClient)
    assert (c.provider, c.model) == ("anthropic", "claude-opus-5-5")


def test_model_and_provider_come_from_args_then_settings(monkeypatch):
    monkeypatch.setenv("JC_LLM_MODEL", "claude-env-model")
    assert make_llm_client(store("key-test-1234")).model == "claude-env-model"
    assert make_llm_client(store("key-test-1234"), model="claude-arg-model").model == "claude-arg-model"
    monkeypatch.setenv("JC_LLM_PROVIDER", "anthropic")
    assert make_llm_client(store("key-test-1234"), provider="ANTHROPIC").provider == "anthropic"


def test_unknown_provider_is_unavailable_with_korean_reason():
    c = make_llm_client(store("key-test-1234"), provider="nope")
    with pytest.raises(LLMUnavailable) as e:
        c.generate(REQ)
    assert "제공자" in e.value.detail and "key-test" not in str(e.value)


def test_missing_sdk_degrades_to_unavailable_client(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "anthropic", None)
    c = make_llm_client(store("key-test-1234"))
    with pytest.raises(LLMUnavailable) as e:
        c.generate(REQ)
    assert "requirements.txt" in e.value.detail


# --- 시험 격리(conftest 기본 픽스처) ---------------------------------------------------------

def test_default_isolation_ignores_user_home_env_and_keyring(tmp_path):
    from app.agents.llm import keystore
    user_env = keystore.user_env_path()
    assert user_env.is_relative_to(tmp_path.parent), "사용자 .env 경로가 진짜 홈을 가리킨다"
    user_env.parent.mkdir(parents=True, exist_ok=True)
    user_env.write_text("ANTHROPIC_API_KEY=key-test-home\n", encoding="utf-8")
    default = KeyStore()                               # 기본 keyring 백엔드도 가짜여야 한다
    assert type(default._backend).__name__ == "FakeKeyring"
    assert default.get("llm") == "key-test-home"       # 격리된 임시 홈의 파일은 읽는다(경로 사상 확인)
    user_env.unlink()
    assert isinstance(make_llm_client(default), NullClient)


def test_isolation_keyring_starts_empty():
    assert KeyStore().get("llm") is None
