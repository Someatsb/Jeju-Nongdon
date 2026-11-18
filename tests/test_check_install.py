"""설치 점검(scripts/check_install.py)의 판정 규칙. 소켓·디스크는 가짜로 바꿔 본다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_install as ci  # noqa: E402


def test_port_free_first():
    r = ci.check_port(8765, 8767, bind=lambda p: None, pause=0)
    assert r.level == ci.OK and "8765" in r.message


def test_port_falls_back_to_next():
    r = ci.check_port(8765, 8767, bind=lambda p: None if p == 8766 else OSError("busy"), pause=0)
    assert r.level == ci.OK and "8766" in r.message


def test_port_flake_is_retried_then_error_with_hint():
    calls = []
    def bind(p):
        calls.append(p)
        return OSError("WinError 10014")
    r = ci.check_port(8765, 8766, bind=bind, pause=0)
    assert len(calls) == 6                     # 2개 포트 x 3번
    assert r.level == ci.ERR and "보안 모듈이 localhost를 막을 수 있습니다" in r.message


def test_port_flake_recovers_on_retry():
    state = {"n": 0}
    def bind(p):
        state["n"] += 1
        return OSError("flake") if state["n"] < 3 else None
    assert ci.check_port(8765, 8765, bind=bind, pause=0).level == ci.OK


def test_python_version_ok_here():
    assert ci.check_python().level == ci.OK


def test_disk_levels(monkeypatch):
    import shutil, collections
    U = collections.namedtuple("U", "total used free")
    for mb, level in ((50, ci.ERR), (300, ci.WARN), (5000, ci.OK)):
        monkeypatch.setattr(shutil, "disk_usage", lambda _p, mb=mb: U(0, 0, mb * 1024 * 1024))
        assert ci.check_disk().level == level


def test_key_value_never_printed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-VALUE-1234")
    r = ci.check_key()
    assert "secret" not in r.message and "1234" not in r.message
