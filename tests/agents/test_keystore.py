"""키 저장(Task 9). 읽기 순서: keyring → 환경변수 → env 파일(JC_ENV_FILE → 프로젝트 .env → ~/.jeju-chaenggim/.env).

진짜 자격 증명 저장소와 진짜 env 파일은 건드리지 않는다: keyring은 메모리 가짜(또는
keyring.backends.fail)로 바꾸고, env 파일은 tmp_path에 둔다. 가짜 키는 key-test-…만 쓴다.
"""
from pathlib import Path

import keyring.backends.fail
import pytest
from keyring.errors import PasswordDeleteError

from app.agents.llm import keystore
from app.agents.llm.keystore import SERVICE, KeyStore, env_file_paths, read_env_file


class MemoryBackend:
    """keyring 백엔드 가짜. 실제 백엔드처럼 없는 항목 삭제는 PasswordDeleteError."""

    def __init__(self, data: dict[tuple[str, str], str] | None = None):
        self.data = dict(data or {})

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise PasswordDeleteError("없음")
        del self.data[(service, username)]


class EmptyBackend(MemoryBackend):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise AssertionError("이 테스트는 keyring에 쓰지 않는다")


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "HUB_PROJECT_KEY", "JC_LLM_PROVIDER", "JC_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JC_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(keystore, "PROJECT_ENV", tmp_path / "no-project" / ".env")   # 진짜 프로젝트 .env는 보지 않는다
    monkeypatch.setattr(keystore, "user_env_path", lambda: tmp_path / "no-home" / ".jeju-chaenggim" / ".env")


def env_file(tmp_path, monkeypatch, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("JC_ENV_FILE", str(path))
    return path


# --- 읽기 순서 --------------------------------------------------------------------------------

def test_keystore_env_file_fallback(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# c\nANTHROPIC_API_KEY=key-test-1234\nJC_LLM_MODEL=claude-opus-5-5\n")
    monkeypatch.setenv("JC_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ks = KeyStore(backend=EmptyBackend())
    assert ks.get("llm") == "key-test-1234" and ks.get_setting("JC_LLM_MODEL") == "claude-opus-5-5"


def test_keystore_keyring_wins_over_env_file(tmp_path, monkeypatch):
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-test-5678")
    ks = KeyStore(backend=MemoryBackend({(SERVICE, "llm"): "key-test-9999"}))
    assert ks.get("llm") == "key-test-9999"


def test_keystore_env_var_wins_over_env_file(tmp_path, monkeypatch):
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-test-5678")
    assert KeyStore(backend=EmptyBackend()).get("llm") == "key-test-5678"


def test_keystore_blank_values_fall_through(tmp_path, monkeypatch):
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert KeyStore(backend=MemoryBackend({(SERVICE, "llm"): " "})).get("llm") == "key-test-1234"


def test_keystore_broken_keyring_falls_through(tmp_path, monkeypatch):
    """자격 증명 저장소를 못 쓰는 PC(keyring.backends.fail)에서도 env 파일 키를 읽는다."""
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    assert KeyStore(backend=keyring.backends.fail.Keyring()).get("llm") == "key-test-1234"


class ExplodingBackend(MemoryBackend):
    """keyring 오류가 아닌 예외를 내는 백엔드(예: Windows 자격 증명 API 오류가 그대로 올라오는 경우)."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("자격 증명 API 오류")


def test_keystore_any_keyring_exception_falls_through(tmp_path, monkeypatch):
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    assert KeyStore(backend=ExplodingBackend()).get("llm") == "key-test-1234"


def test_keystore_nothing_anywhere_is_none():
    assert KeyStore(backend=EmptyBackend()).get("llm") is None
    assert KeyStore(backend=EmptyBackend()).get_masked("llm") is None


def test_keystore_hub_key_uses_its_own_names(tmp_path, monkeypatch):
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\nHUB_PROJECT_KEY=key-test-hub1\n")
    assert KeyStore(backend=EmptyBackend()).get("hub") == "key-test-hub1"
    ks = KeyStore(backend=MemoryBackend({(SERVICE, "hub"): "key-test-hub2"}))
    assert ks.get("hub") == "key-test-hub2" and ks.get("llm") == "key-test-1234"


def test_keystore_unknown_name():
    with pytest.raises(KeyError):
        KeyStore(backend=EmptyBackend()).get("openai")


# --- 쓰기·가림·삭제·점검 --------------------------------------------------------------------------

def test_keystore_mask():
    ks = KeyStore(backend=MemoryBackend())
    ks.set("llm", "key-test-abcdef1234")
    assert ks.get_masked("llm") == "••••1234"


def test_keystore_mask_never_shows_a_short_key_whole():
    ks = KeyStore(backend=MemoryBackend({(SERVICE, "llm"): "abcd"}))
    assert ks.get_masked("llm") == "••••"


def test_keystore_set_writes_keyring_only(tmp_path, monkeypatch):
    path = env_file(tmp_path, monkeypatch, "# 빈 템플릿\nANTHROPIC_API_KEY=\n")
    backend = MemoryBackend()
    KeyStore(backend=backend).set("llm", "  key-test-4321 ")
    assert backend.data == {(SERVICE, "llm"): "key-test-4321"}
    assert path.read_text(encoding="utf-8") == "# 빈 템플릿\nANTHROPIC_API_KEY=\n"
    with pytest.raises(ValueError):
        KeyStore(backend=backend).set("llm", "   ")


def test_keystore_delete(tmp_path, monkeypatch):
    backend = MemoryBackend({(SERVICE, "llm"): "key-test-9999"})
    ks = KeyStore(backend=backend)
    ks.delete("llm")
    assert backend.data == {} and ks.get("llm") is None
    ks.delete("llm")                                # 없는 항목 삭제는 조용히 넘어간다
    env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=key-test-1234\n")
    assert ks.get("llm") == "key-test-1234"         # 삭제는 keyring만. 파일 키는 남는다


def test_keystore_test_round_trip():
    backend = MemoryBackend({(SERVICE, "llm"): "key-test-9999"})
    check = KeyStore(backend=backend).test()
    assert check.ok and check.backend == "MemoryBackend"
    assert backend.data == {(SERVICE, "llm"): "key-test-9999"}   # 점검 항목은 지우고 키는 그대로
    failed = KeyStore(backend=keyring.backends.fail.Keyring()).test()
    assert not failed.ok and failed.backend == "Keyring"


# --- 설정·env 파일 --------------------------------------------------------------------------

def test_get_setting_defaults_file_and_env(tmp_path, monkeypatch):
    ks = KeyStore(backend=EmptyBackend())
    assert (ks.get_setting("JC_LLM_PROVIDER"), ks.get_setting("JC_LLM_MODEL")) == ("anthropic", "claude-opus-5-5")
    env_file(tmp_path, monkeypatch, "JC_LLM_MODEL=claude-test-model\n")
    assert ks.get_setting("JC_LLM_MODEL") == "claude-test-model"
    monkeypatch.setenv("JC_LLM_MODEL", "claude-env-model")
    assert ks.get_setting("JC_LLM_MODEL") == "claude-env-model"
    with pytest.raises(KeyError):
        ks.get_setting("ANTHROPIC_API_KEY")         # 키는 get()으로만


def test_read_env_file_rules(tmp_path):
    path = tmp_path / ".env"
    path.write_text("﻿# 주석\n\n  ANTHROPIC_API_KEY = \"key-test-1234\"  \nJC_LLM_MODEL='claude-opus-5-5'\n"
                    "export NOT_A_PAIR\nEMPTY=\nURL=https://x.test/a=b#c\n", encoding="utf-8")
    assert read_env_file(path) == {"ANTHROPIC_API_KEY": "key-test-1234", "JC_LLM_MODEL": "claude-opus-5-5",
                                   "EMPTY": "", "URL": "https://x.test/a=b#c"}
    assert read_env_file(tmp_path / "none.env") == {}


def test_read_env_file_not_utf8_is_empty(tmp_path, monkeypatch):
    """메모장 'ANSI'(CP949)로 저장한 파일은 읽지 못한 것으로 보고 빈 dict(예외 없음)."""
    path = tmp_path / "cp949.env"
    path.write_bytes("# 키를 여기에 넣으세요\nANTHROPIC_API_KEY=key-test-1234\n".encode("cp949"))
    assert read_env_file(path) == {}
    monkeypatch.setenv("JC_ENV_FILE", str(path))
    ks = KeyStore(backend=EmptyBackend())
    assert ks.get("llm") is None and ks.get_setting("JC_LLM_MODEL") == "claude-opus-5-5"


def test_env_file_order_and_project_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(keystore, "user_env_path", lambda: home / ".jeju-chaenggim" / ".env")
    monkeypatch.delenv("JC_ENV_FILE")
    assert env_file_paths() == (tmp_path / "no-project" / ".env",
                                home / ".jeju-chaenggim" / ".env")
    monkeypatch.setenv("JC_ENV_FILE", str(tmp_path / "custom.env"))
    assert env_file_paths()[0] == tmp_path / "custom.env" and len(env_file_paths()) == 3


def test_project_env_is_next_to_app_not_cwd(tmp_path, monkeypatch):
    import app
    monkeypatch.undo()                              # 진짜 PROJECT_ENV 상수만 본다(파일은 읽지 않는다)
    assert keystore.PROJECT_ENV == Path(app.__file__).resolve().parent.parent / ".env"
    monkeypatch.chdir(tmp_path)
    assert keystore.PROJECT_ENV.name == ".env" and keystore.PROJECT_ENV.parent.name == "jeju-chaenggim"


def test_env_file_lookup_falls_through_in_order(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".jeju-chaenggim").mkdir(parents=True)
    monkeypatch.setattr(keystore, "user_env_path", lambda: home / ".jeju-chaenggim" / ".env")
    project = tmp_path / "proj.env"
    monkeypatch.setattr(keystore, "PROJECT_ENV", project)
    custom = tmp_path / "custom.env"
    monkeypatch.setenv("JC_ENV_FILE", str(custom))
    ks = KeyStore(backend=EmptyBackend())
    (home / ".jeju-chaenggim" / ".env").write_text("ANTHROPIC_API_KEY=key-test-home\nJC_LLM_MODEL=m-home\n", encoding="utf-8")
    assert ks.get("llm") == "key-test-home"         # 셋째: 사용자 폴더
    project.write_text("ANTHROPIC_API_KEY=key-test-proj\n", encoding="utf-8")
    assert ks.get("llm") == "key-test-proj"         # 둘째가 셋째를 이긴다
    assert ks.get_setting("JC_LLM_MODEL") == "m-home"   # 변수마다 따로 내려간다
    custom.write_text("ANTHROPIC_API_KEY=key-test-custom\n", encoding="utf-8")
    assert ks.get("llm") == "key-test-custom"       # 첫째(JC_ENV_FILE)가 이긴다
    assert KeyStore(backend=MemoryBackend({(SERVICE, "llm"): "key-test-ring"})).get("llm") == "key-test-ring"  # keyring이 먼저
