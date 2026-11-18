"""Task 6(U06) 실행기의 포트 고르기. 소켓은 가짜로 바꿔 끼운다.

개발 PC에서는 보안 프로그램이 소켓 호출을 가로채 bind가 가끔 WinError 10014로 실패하므로
진짜 소켓을 쓰는 시험은 흔들린다. 진짜 소켓 동작은 손 점검으로 본다(보고서 참고).
"""
from app import launch
from app.launch import candidate_ports, scan

HEALTH = {"ok": True, "as_of": "2026-11-13", "demo": True}


class FakeSock:
    def __init__(self, port):
        self.port, self.closed = port, False

    def close(self):
        self.closed = True


def fakes(busy: set[int], ours: set[int]):
    bound, probed = [], []

    def bind(port):
        bound.append(port)
        return None if port in busy else FakeSock(port)

    def probe(port):
        probed.append(port)
        return HEALTH if port in ours else None

    return bind, probe, bound, probed


def test_candidate_ports():
    assert candidate_ports(8765) == list(range(8765, 8776))
    assert candidate_ports(8774) == [8774, 8775]
    assert candidate_ports(9000) == [9000]


def test_scan_skips_busy_port_and_binds_each_port_once():
    bind, probe, bound, probed = fakes(busy={8765}, ours=set())
    running, sock = scan([8765, 8766, 8767], bind=bind, probe=probe)
    assert running is None and sock.port == 8766 and not sock.closed
    assert bound == [8765, 8766, 8767]  # 닫았다 다시 묶지 않는다
    assert probed == [8765]             # 빈 포트에는 묻지 않는다


def test_scan_finds_running_app_after_free_port():
    bind, probe, bound, probed = fakes(busy={8765, 8767}, ours={8767})
    running, sock = scan([8765, 8766, 8767, 8768], bind=bind, probe=probe)
    assert running == (8767, HEALTH) and sock is None
    assert probed == [8765, 8767]


def test_scan_all_busy():
    bind, probe, _, _ = fakes(busy={8765, 8766}, ours=set())
    assert scan([8765, 8766], bind=bind, probe=probe) == (None, None)


def test_open_browser_starts_edge_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.sys, "platform", "win32")
    monkeypatch.setattr(launch.subprocess, "Popen", lambda args: calls.append(args))
    launch.open_browser("http://127.0.0.1:8765")
    assert calls == [["cmd", "/c", "start", "", "msedge", "http://127.0.0.1:8765"]]


def _bad_tables_main(monkeypatch, tmp_path, *, snapshot=False):
    """표(또는 저장본) 폴더가 깨진 채로 main을 돌린다. 소켓은 가짜."""
    import shutil
    from dataclasses import replace

    from app.config import APP_ROOT, load_config
    cfg = load_config(["--asof", "2026-11-13"])
    tables = tmp_path / "tables"
    snap = tmp_path / "snapshot"
    shutil.copytree(APP_ROOT / "data" / "tables", tables)
    shutil.copytree(APP_ROOT / "data" / "snapshot", snap)
    if snapshot:
        (snap / "manifest.json").unlink()
    else:
        csv = tables / "supports.csv"
        lines = csv.read_text(encoding="utf-8").splitlines()
        csv.write_text("\n".join([lines[0] + ",zzz"] + [ln + "," for ln in lines[1:]]) + "\n", encoding="utf-8")
    monkeypatch.setattr(launch, "load_config", lambda argv: replace(cfg, tables_dir=tables, snapshot_dir=snap))
    sock = FakeSock(8765)
    sock.getsockname = lambda: ("127.0.0.1", 8765)
    monkeypatch.setattr(launch, "scan", lambda ports: (None, sock))
    return sock


def test_main_bad_table_prints_one_korean_line_and_exits_2(monkeypatch, tmp_path, capsys):
    sock = _bad_tables_main(monkeypatch, tmp_path)
    assert launch.main(["--nobrowser"]) == 2
    out = capsys.readouterr().out
    assert "supports.csv" in out and "tables.bat check" in out and "Traceback" not in out and sock.closed


def test_main_missing_manifest_prints_korean_line_and_exits_2(monkeypatch, tmp_path, capsys):
    _bad_tables_main(monkeypatch, tmp_path, snapshot=True)
    assert launch.main(["--nobrowser"]) == 2
    out = capsys.readouterr().out
    assert "manifest.json" in out and "tables.bat check" in out and "Traceback" not in out
