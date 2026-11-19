"""키 저장(Task 9, U09) — round1-C-agent.md §6-2, 스펙 §12-B 5.

읽기 순서 get(name): ① keyring(service "jeju-chaenggim", username "llm"|"hub")
→ ② 환경변수(ANTHROPIC_API_KEY | HUB_PROJECT_KEY) → ③ env 파일의 같은 이름 줄. 처음 비어 있지 않은 값.
env 파일(사장 결정 2026-11-08, 스펙 §12-B 5행): 위에서부터 차례로 보고 변수마다 처음 비어 있지 않은 값을 쓴다.
  ① 환경변수 JC_ENV_FILE이 가리키는 파일 ② <프로젝트 루트>/.env(app/ 옆. 실행 폴더가 아니라 이 패키지 위치 기준,
  git 무시 대상) ③ 사용자 폴더(%USERPROFILE%)의 .jeju-chaenggim/.env(프로젝트 밖이라 git·zip에 안 든다).
  변수: ANTHROPIC_API_KEY, JC_LLM_PROVIDER=anthropic, JC_LLM_MODEL=claude-opus-5-5.
자격 증명 저장소를 못 쓰는 PC(백엔드가 어떤 예외든 내면)는 ①을 건너뛴다. env 파일이 없거나 UTF-8이
아니면(메모장 ANSI 저장) 빈 파일로 본다.
인터넷 판(KeyStore.env_only())은 위 ①③을 건너뛰고 ②환경변수만 읽는다(키·공급자·모델 모두). 열쇠 저장소·.env 파일은 열지 않는다.
set()은 keyring에만 쓴다(파일은 사장이 직접 채운다). delete()도 keyring만 지운다.
get_setting(name): JC_LLM_PROVIDER·JC_LLM_MODEL을 환경변수 → env 파일 → 기본값 순으로 읽는다.
키 값은 어디에도 출력·기록하지 않는다. 화면에는 get_masked()의 끝 4자리만("••••ab12").
"""
import os
from pathlib import Path
from typing import NamedTuple

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

SERVICE = "jeju-chaenggim"
ENV_NAMES = {"llm": "ANTHROPIC_API_KEY", "hub": "HUB_PROJECT_KEY"}
SETTING_DEFAULTS = {"JC_LLM_PROVIDER": "anthropic", "JC_LLM_MODEL": "claude-opus-5-5"}
MASK = "••••"
_PROBE = "selftest"                              # test()가 잠깐 쓰고 지우는 username


class KeyringCheck(NamedTuple):
    ok: bool
    backend: str                                 # 예: "WinVaultKeyring"(설치 점검, Task 27)


def _env_name(name: str) -> str:
    if name not in ENV_NAMES:
        raise KeyError(f"모르는 키 이름: {name} (llm 또는 hub)")
    return ENV_NAMES[name]


PROJECT_ENV = Path(__file__).resolve().parents[3] / ".env"   # jeju-chaenggim/.env (app/ 옆)


def user_env_path() -> Path:
    return Path.home() / ".jeju-chaenggim" / ".env"


def env_file_paths() -> tuple[Path, ...]:
    custom = os.environ.get("JC_ENV_FILE")
    return (*((Path(custom),) if custom else ()), PROJECT_ENV, user_env_path())


def read_env_value(name: str) -> str:
    """env 파일 후보를 순서대로 보아 처음 비어 있지 않은 값. 없으면 ''."""
    for path in env_file_paths():
        value = read_env_file(path).get(name, "").strip()
        if value:
            return value
    return ""


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE 한 줄씩. '#' 주석·빈 줄·'=' 없는 줄은 무시, 앞뒤 공백과 둘러싼 따옴표는 벗긴다.
    메모장이 붙이는 BOM도 벗긴다. 파일이 없거나 못 읽으면 빈 dict."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):           # 없음·권한·UTF-8 아님(메모장 ANSI 저장 등)
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


class KeyStore:
    def __init__(self, backend: KeyringBackend | None = None, *, env_only: bool = False):
        self._env_only = env_only
        self._backend = None if env_only else (backend if backend is not None else keyring.get_keyring())

    @classmethod
    def env_only(cls) -> "KeyStore":
        """인터넷 판용: 환경변수만 읽는다(열쇠 저장소 백엔드를 만들지도 않는다. 리눅스에는 백엔드가 없어 예외가 날 수 있다)."""
        return cls(env_only=True)

    def get(self, name: str) -> str | None:
        env_name = _env_name(name)
        if self._env_only:
            return (os.environ.get(env_name) or "").strip() or None
        sources = (lambda: self._from_keyring(name), lambda: os.environ.get(env_name),
                   lambda: read_env_value(env_name))
        for source in sources:
            value = (source() or "").strip()
            if value:
                return value
        return None

    def get_masked(self, name: str) -> str | None:
        value = self.get(name)
        if value is None:
            return None
        return MASK + value[-4:] if len(value) > 4 else MASK

    def set(self, name: str, value: str) -> None:
        _env_name(name)
        self._need_backend()
        value = value.strip()
        if not value:
            raise ValueError("빈 키는 저장하지 않습니다.")
        self._backend.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        _env_name(name)
        self._need_backend()
        try:
            self._backend.delete_password(SERVICE, name)
        except PasswordDeleteError:
            pass

    def test(self) -> KeyringCheck:
        """자격 증명 저장소 점검: 시험값 저장 → 읽기 → 삭제 → 읽기(None). 저장된 키는 건드리지 않는다."""
        probe = "jeju-chaenggim-selftest"
        if self._backend is None:
            return KeyringCheck(ok=False, backend="env-only")
        try:
            self._backend.set_password(SERVICE, _PROBE, probe)
            ok = self._backend.get_password(SERVICE, _PROBE) == probe
            self._backend.delete_password(SERVICE, _PROBE)
            ok = ok and self._backend.get_password(SERVICE, _PROBE) is None
        except Exception:                        # 점검이므로 어떤 실패든 "안 됨"으로 보고한다
            ok = False
        return KeyringCheck(ok=ok, backend=type(self._backend).__name__)

    def get_setting(self, name: str) -> str:
        default = SETTING_DEFAULTS[name]
        value = (os.environ.get(name) or ("" if self._env_only else read_env_value(name)) or "").strip()
        return value or default

    def _need_backend(self) -> None:
        if self._backend is None:
            raise RuntimeError("환경변수만 읽는 열쇠 보관(인터넷 판)은 키를 저장하거나 지우지 않습니다.")

    def _from_keyring(self, name: str) -> str | None:
        if self._backend is None:
            return None
        try:
            return self._backend.get_password(SERVICE, name)
        except Exception:                        # 어떤 백엔드 오류든 건너뛰고 환경변수·env 파일을 본다
            return None
