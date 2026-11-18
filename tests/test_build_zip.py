"""scripts/build_zip.py: the submission gate must not be bypassable by case, separators or .env variants."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_zip", ROOT / "scripts" / "build_zip.py")
bz = importlib.util.module_from_spec(spec)
sys.modules["build_zip"] = bz
spec.loader.exec_module(bz)


@pytest.mark.parametrize("rel", [
    ".env", ".ENV", ".env.local", ".env.production", "app/.env", "app/.ENV.bak",
    "Data/Inbox/a.pdf", "data\\inbox\\a.pdf", "data/inbox/sub/a.txt",
    "logs/x.log", "Logs/x.log", "LOGS\\x.log", "dist/a.zip", "Dist/a.zip", "research/a.md", "Research/a.md",
    "research/catalog-analyzed.csv", "data/live/a.json", "data/Live/a.json", "data/reminders/r.json", "data/hub/a.csv",
    "data/hub/869_A.CSV", "data/snapshot/869_big.csv", "a.XLSX", "data/x/a.xlsx",
    "b.PYC", "app/__pycache__/a.cpython-312.pyc", "app/sub/__PYCACHE__/a", "tests/.pytest_cache/v/x", ".pytest_cache/x",
    ".git/config", "a/.Git/config", ".gitignore", ".superpowers/x.md",
])
def test_excluded(rel):
    assert bz.excluded(rel), rel


@pytest.mark.parametrize("rel", [
    "data/inbox/.gitkeep", "Data\\Inbox\\.gitkeep", "app/static/dist/app.js", "app/research/notes.py",
    "app/logs.py", "app/core/env.py", "environment.md", "runtime/python/python.exe", "data/snapshot/agg_869_ratio.csv",
    "data/tables/crops.csv", "tests/REPORT.txt", "requirements.txt", "run.bat", "docs/install_rehearsal.md",
    "app/agents/prompts/a.txt", "samples/P1/print.pdf",
])
def test_kept(rel):
    assert not bz.excluded(rel), rel


def test_dir_forms():
    assert bz.excluded("logs", is_dir=True) and bz.excluded("Data/Live", is_dir=True)
    assert bz.excluded("app/__pycache__", is_dir=True)
    assert not bz.excluded("app/static/dist", is_dir=True) and not bz.excluded("data/inbox", is_dir=True)


def test_env_files_found_anywhere(tmp_path):
    (tmp_path / "a" / "logs").mkdir(parents=True)
    (tmp_path / "a" / "logs" / ".ENV.local").write_text("SECRET")
    (tmp_path / "ok.txt").write_text("x")
    assert bz.find_env_files(tmp_path) == ["a/logs/.ENV.local"]


def test_out_dir_rule(tmp_path):
    root = tmp_path / "pkg"
    (root / "dist").mkdir(parents=True)
    assert bz.out_dir_ok(root / "dist", root)
    assert bz.out_dir_ok(tmp_path / "elsewhere", root)
    assert not bz.out_dir_ok(root / "docs", root)
    assert not bz.out_dir_ok(root, root)


def test_manifest_matches_written_bytes(tmp_path):
    import hashlib
    import zipfile
    src = tmp_path / "pkg"
    (src / "app").mkdir(parents=True)
    (src / "app" / "a.txt").write_bytes(b"hello")
    z = tmp_path / "o.zip"
    bz.write_zip([("app/a.txt", src / "app" / "a.txt")], z)
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert names[0].startswith("jeju-nongdon/") and "jeju-nongdon/MANIFEST.sha256" in names
        line = zf.read("jeju-nongdon/MANIFEST.sha256").decode().strip()
        assert line == hashlib.sha256(zf.read("jeju-nongdon/app/a.txt")).hexdigest() + "  app/a.txt"


def test_extras_in_manifest_and_verify(tmp_path):
    import zipfile
    src = tmp_path / "a.txt"
    src.write_bytes(b"x")
    z = tmp_path / "o.zip"
    n = bz.write_zip([("a.txt", src)], z, [("RELEASE.txt", b"v\n")])
    assert n == 3
    assert bz.verify_zip(z) == 2
    with zipfile.ZipFile(z) as zf:
        assert b"RELEASE.txt" in zf.read("jeju-nongdon/MANIFEST.sha256")


def test_verify_detects_tamper(tmp_path):
    import zipfile
    src = tmp_path / "a.txt"
    src.write_bytes(b"x")
    z = tmp_path / "o.zip"
    bz.write_zip([("a.txt", src)], z)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(z) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, b"y" if n.endswith("a.txt") else zi.read(n))
    with pytest.raises(SystemExit):
        bz.verify_zip(bad)


def test_final_refuses_dirty_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build_zip.py", "--final", "--allow-dirty"])
    with pytest.raises(SystemExit):
        bz.main()


def test_env_names():
    assert bz.env_names(["a/.ENV", "x/b.py", ".env.local"]) == [".env.local", "a/.ENV"]
    assert bz.env_names(["app/environment.py", "a/b.txt"]) == []


def test_ignored_env_tolerated_but_tracked_refused(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("SECRET")
    monkeypatch.setattr(bz, "ROOT", str(tmp_path))
    monkeypatch.setattr(bz, "find_env_files", lambda root=None: [".env"])
    outs = {"status": "", "ls": "app/a.py"}

    class R:
        returncode = 0
        stdout = "OK 0 hits"
        stderr = ""

    def fake_run(cmd, **k):
        r = R()
        if cmd[0] == "git":
            r.stdout = outs["ls"] if cmd[1] == "ls-files" else outs["status"]
        return r

    monkeypatch.setattr(bz.subprocess, "run", fake_run)
    bz.preflight(False)
    out = capsys.readouterr().out
    assert ".env" in out and "SECRET" not in out
    outs["ls"] = "app/a.py" + chr(10) + ".env"
    with pytest.raises(SystemExit):
        bz.preflight(False)
