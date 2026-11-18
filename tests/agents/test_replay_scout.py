"""notice.bat --replay S1: 고정본 게시판과 손으로 쓴 답 녹화로 새 공고 찾기를 재생한다(인터넷·열쇠 없음)."""
import json
import shutil
from pathlib import Path

from app.agents.llm.recording import load_recording
from app.config import APP_ROOT
from app.replay_cli import main


def _root(tmp_path: Path) -> Path:
    shutil.copytree(APP_ROOT / "data" / "tables", tmp_path / "data" / "tables")
    shutil.copytree(APP_ROOT / "data" / "replay", tmp_path / "data" / "replay")
    return tmp_path


def _scout_dir(root: Path) -> Path:
    (d,) = [p for p in (root / "data" / "inbox").iterdir() if p.name.startswith("scout-")]
    return d


def test_replay_s1_picks_three_and_marks_the_report(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["S1"], root=root) == 0
    said = capsys.readouterr().out
    assert "실제 LLM 호출 아님" in said and "고른 글 3건" in said
    out = _scout_dir(root)
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["as_of"] == "2026-11-13" and data["stop"] == "" and data["unavailable"] == ""
    assert [p["dept"] for p in data["picks"]] == ["대륜동", "대륜동", "감귤유통과"]
    assert [p["decision"] for p in data["picks"]] == ["DRAFT_READY"] * 3 and data["no_catalog"] is True
    reasons = {s["reason"] for s in data["skips"]}
    assert "신청 기간이 이미 끝난 공고입니다" in reasons          # 미리보기로 본문을 읽고 기간이 끝난 글을 건너뛴다
    assert data["requests"] == 7 and data["tool_calls"] == 13
    assert "실제 LLM 호출 아님" in (out / "report.html").read_text(encoding="utf-8")
    assert not (root / "data" / "catalog").exists()               # 시연은 목록에 올리지 않는다


def test_replay_s1_can_run_twice_in_the_same_folder(tmp_path):
    root = _root(tmp_path)
    assert main(["S1"], root=root) == 0
    assert main(["S1"], root=root) == 0


def test_replay_s1_recording_matches_its_fixtures():
    rec = load_recording(APP_ROOT / "data" / "replay" / "S1.json")
    assert rec.sample_id == "S1" and rec.source == "handwritten" and rec.prompt_ver == "scout-v1"
    assert {c.purpose for c in rec.calls} == {"scout", "notice"} and len(rec.calls) == 20


def test_replay_refuses_changed_fixtures(tmp_path, capsys):
    root = _root(tmp_path)
    page = root / "data" / "replay" / "boards" / "seogwipo_list.html"
    page.write_text(page.read_text(encoding="utf-8") + "\n<!-- 바뀜 -->\n", encoding="utf-8")
    assert main(["S1"], root=root) == 1
    assert "녹화와 입력이 다릅니다" in capsys.readouterr().out
    assert not (root / "data" / "inbox").exists()


def test_replay_scout_unknown_or_missing(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["S9"], root=root) == 2
    assert "S1" in capsys.readouterr().out
    shutil.rmtree(root / "data" / "replay" / "boards")
    assert main(["S1"], root=root) == 2


def test_recording_is_what_record_replay_makes_from_the_answers_file(monkeypatch):
    """S1.json 은 손으로 쓴 답(answers/S1.json)과 지금 프롬프트·도구로 다시 만들어도 같아야 한다(어긋나면 다시 녹화).
    S1 은 공고 읽기 지시문 v4 가 생기기 전에 녹았으므로(안의 공고 읽기는 notice-v3) 옛 녹화 날짜로 재생 장치처럼 판을 따르게 한다."""
    import sys
    from datetime import datetime
    from types import SimpleNamespace
    sys.path.insert(0, str(APP_ROOT / "scripts"))
    import record_replay as rr
    monkeypatch.setattr(rr.Recorder, "recording", SimpleNamespace(prompt_ver="scout-v1", recorded_at=datetime(2026, 11, 14, 18)), raising=False)
    answers = json.loads((APP_ROOT / "data" / "replay" / "answers" / "S1.json").read_text(encoding="utf-8"))
    rec, in_hash = rr.record_scout(rr.HandwrittenClient(answers), "2026-11-13")
    saved = load_recording(APP_ROOT / "data" / "replay" / "S1.json")
    assert in_hash == saved.input_hash
    assert [c.request_hash for c in rec.calls] == [c.request_hash for c in saved.calls]
    assert [c.response.model_dump() for c in rec.calls] == [c.response.model_dump() for c in saved.calls]


def test_replay_s1_leaves_no_read_posts_in_the_installed_inbox(tmp_path):
    root = _root(tmp_path)
    assert main(["S1"], root=root) == 0
    assert [p.name for p in (root / "data" / "inbox").iterdir() if not p.name.startswith("scout-")] == []
