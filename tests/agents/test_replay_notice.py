"""notice.bat --replay N1 (Task 32): 녹화한 공고 답을 run_notice에 재생한다."""
import json
import shutil
from pathlib import Path

from app.config import APP_ROOT
from app.replay_cli import main


def _root(tmp_path: Path) -> Path:
    shutil.copytree(APP_ROOT / "data" / "tables", tmp_path / "data" / "tables")
    shutil.copytree(APP_ROOT / "data" / "replay", tmp_path / "data" / "replay")
    return tmp_path


def _out(root: Path) -> Path:
    (d,) = [p for p in (root / "data" / "inbox").iterdir() if p.is_dir()]
    return d


def test_replay_n1_gives_draft_ready_with_banner(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["N1"], root=root) == 0
    text = capsys.readouterr().out
    assert "실제 LLM 호출 아님" in text and "DRAFT_READY" in text
    out = _out(root)
    assert json.loads((out / "check.json").read_text(encoding="utf-8"))["decision"] == "DRAFT_READY"
    assert "실제 LLM 호출 아님" in (out / "report.html").read_text(encoding="utf-8")


def test_replay_refuses_a_changed_notice(tmp_path, capsys):
    root = _root(tmp_path)
    src = root / "data" / "replay" / "N1.txt"
    src.write_text(src.read_text(encoding="utf-8") + "\n다른 줄\n", encoding="utf-8")
    assert main(["N1"], root=root) == 1
    assert "녹화와 입력이 다릅니다" in capsys.readouterr().out
    assert not (root / "data" / "inbox").exists()


def test_replay_unknown_sample(tmp_path, capsys):
    assert main(["N9"], root=_root(tmp_path)) == 2


def test_save_recording_is_atomic(tmp_path, monkeypatch):
    import os

    from app.agents.llm.recording import load_recording, save_recording
    rec = load_recording(APP_ROOT / "data" / "replay" / "N1.json")
    path = tmp_path / "N1.json"
    save_recording(rec, path)
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("중단")))
    try:
        save_recording(rec.model_copy(update={"model": "x"}), path)
    except OSError:
        pass
    assert path.read_text(encoding="utf-8") == before and [p.name for p in tmp_path.iterdir()] == ["N1.json"]


def test_replay_cli_usage_and_wording(tmp_path, capsys):
    assert main(["N9"], root=_root(tmp_path)) == 2
    assert "data/replay" in capsys.readouterr().out


def test_replay_cli_mismatch_says_notice(tmp_path, capsys):
    root = _root(tmp_path)
    src = root / "data" / "replay" / "N1.txt"
    src.write_text(src.read_text(encoding="utf-8") + "\n다른 줄\n", encoding="utf-8")
    main(["N1"], root=root)
    assert "시연 공고 N1을 고르세요" in capsys.readouterr().out


def test_replay_cli_fails_loudly_when_banner_not_inserted(tmp_path, capsys, monkeypatch):
    import app.cli as cli
    root = _root(tmp_path)
    real = cli.main

    def fake(argv, **kw):
        code = real(argv, **kw)
        for r in (root / "data" / "inbox").rglob("report.html"):
            r.write_text("<html></html>", encoding="utf-8")
        return code
    monkeypatch.setattr(cli, "main", fake)
    assert main(["N1"], root=root) == 1
    assert "띠" in capsys.readouterr().out
