"""notice 명령(Task 29): 파일 하나 → data/inbox/<id>/{draft.json,check.json,report.html}."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents"))

from notice_fixtures import NOTICES, ROOT  # noqa: E402
from notice_loop_fixtures import GOLDEN_DRAFT_N1, REC_N1, CountingClient  # noqa: E402

from app.agents.llm.scripted import ScriptedClient  # noqa: E402
from app.cli import main  # noqa: E402


def _root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "data" / "tables", tmp_path / "data" / "tables")
    return tmp_path


def _out(root: Path) -> Path:
    (d,) = [p for p in (root / "data" / "inbox").iterdir() if p.is_dir()]
    return d


def test_notice_writes_three_files(tmp_path, capsys):
    root = _root(tmp_path)
    code = main(["notice", str(NOTICES / "N1.txt")], root=root, llm=ScriptedClient(REC_N1))
    assert code == 0
    out = _out(root)
    assert sorted(p.name for p in out.iterdir()) == ["check.json", "draft.json", "report.html"]
    draft = json.loads((out / "draft.json").read_text(encoding="utf-8"))
    assert draft == json.loads(GOLDEN_DRAFT_N1.model_dump_json())
    check = json.loads((out / "check.json").read_text(encoding="utf-8"))
    assert check["decision"] == "DRAFT_READY" and check["issues"] == [] and check["tool_calls"] == 4
    assert "✓" in (out / "report.html").read_text(encoding="utf-8")
    assert "report.html" in capsys.readouterr().out


def test_notice_pii_document_never_reaches_llm(tmp_path):
    root = _root(tmp_path)
    c = CountingClient()
    assert main(["notice", str(NOTICES / "N5.txt")], root=root, llm=c) == 0
    assert c.calls == 0
    out = _out(root)
    text = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    assert "BLOCKED_PII" in text and "010-" not in text


def test_notice_scanned_pdf_is_unreadable_report(tmp_path):
    root = _root(tmp_path)
    assert main(["notice", str(NOTICES / "N8.pdf")], root=root, llm=CountingClient()) == 0
    assert "UNREADABLE" in (_out(root) / "check.json").read_text(encoding="utf-8")


def test_notice_hwp_gives_korean_hint(tmp_path):
    root = _root(tmp_path)
    f = tmp_path / "공고.hwp"
    f.write_bytes(bytes([0xff, 0xfe, 0, 0x62, 0x80, 0x81]))
    assert main(["notice", str(f)], root=root, llm=CountingClient()) == 0
    assert "HWP는 PDF로 저장해 주세요" in (_out(root) / "report.html").read_text(encoding="utf-8")


def test_notice_missing_file_exits_nonzero(tmp_path, capsys):
    assert main(["notice", str(tmp_path / "없음.pdf")], root=_root(tmp_path), llm=CountingClient()) == 2
    assert "찾을 수 없습니다" in capsys.readouterr().out


def test_notice_bat_calls_cli_with_utf8():
    bat = (ROOT / "notice.bat").read_bytes()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    assert '"%PY%" -X utf8 -m app.cli notice'.encode() in bat
    assert rb"runtime\python\python.exe" in bat  # clean PC: embedded runtime, not a system python


def test_notice_corrupt_text_file_gives_korean_report_not_traceback(tmp_path):
    root = _root(tmp_path)
    f = tmp_path / "깨짐.txt"
    f.write_bytes(bytes([0xff, 0xfe, 0, 0x62, 0x80, 0x81]))
    assert main(["notice", str(f)], root=root, llm=CountingClient()) == 0
    out = _out(root)
    assert "UNREADABLE" in (out / "check.json").read_text(encoding="utf-8")
    assert "붙여" in (out / "report.html").read_text(encoding="utf-8")


def test_notice_outputs_are_atomic_and_report_is_last(tmp_path, monkeypatch):
    import os

    import app.cli as cli
    root = _root(tmp_path)
    real, order = os.replace, []

    def spy(src, dst):
        order.append(Path(dst).name)
        if Path(dst).name == "report.html":
            raise OSError("디스크 오류")
        real(src, dst)

    monkeypatch.setattr(cli.os, "replace", spy)
    try:
        main(["notice", str(NOTICES / "N1.txt")], root=root, llm=ScriptedClient(REC_N1))
    except OSError:
        pass
    out = _out(root)
    assert order == ["draft.json", "check.json", "report.html"] and not (out / "report.html").exists()


def test_notice_leaves_no_tmp_files(tmp_path):
    root = _root(tmp_path)
    main(["notice", str(NOTICES / "N1.txt")], root=root, llm=ScriptedClient(REC_N1))
    assert not list(_out(root).glob("*.tmp"))
