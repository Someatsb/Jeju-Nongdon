"""build_runtime.py의 약속: 부품 목록 완비, 스모크 대상, 풀기는 한 번에(반쯤 풀린 폴더 없음), x64만."""
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_runtime as br  # noqa: E402

REQUIRED = {"keyring", "pypdf", "anthropic", "fastapi", "uvicorn", "jinja2", "pydantic", "multipart"}


def _pinned() -> set[str]:
    names = set()
    for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.\-]+)==", ln.strip())
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    return names


def test_smoke_imports_cover_required():
    assert REQUIRED <= set(br.SMOKE_MODULES)


def test_requirements_pin_keyring_pypdf_and_their_deps():
    assert {"keyring", "pypdf", "anthropic", "pywin32-ctypes", "jaraco.classes", "more-itertools"} <= _pinned()


def test_unpack_is_atomic(tmp_path, monkeypatch):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("python.exe", "x")
        f.writestr("python312._pth", "x")
    rt = tmp_path / "runtime"
    rt.mkdir()
    br.unpack(z, rt)
    assert (rt / "python" / "python.exe").exists()
    assert not [p for p in rt.iterdir() if p.name.startswith("python.tmp")]
    # 풀다 죽은 흔적이 있어도 지우고 다시 푼다
    (rt / "python").rename(rt / "gone")
    (rt / "python.tmp").mkdir()
    (rt / "python.tmp" / "half").write_text("x")
    br.unpack(z, rt)
    assert (rt / "python" / "python.exe").exists() and not (rt / "python.tmp").exists()


def test_refuses_non_x64(monkeypatch):
    monkeypatch.setattr(br.platform, "machine", lambda: "ARM64")
    with pytest.raises(SystemExit) as e:
        br.require_x64()
    assert "64" in str(e.value)


def test_pip_command_pins_platform():
    cmd = br.pip_command(Path("t"), Path("r.txt"))
    for flag in ("--python-version", "3.12", "--platform", "win_amd64", "--implementation", "cp", "--only-binary=:all:"):
        assert flag in cmd
