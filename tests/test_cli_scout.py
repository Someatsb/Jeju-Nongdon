"""notice --scout (app/cli.py): 고정본 게시판(http 인자)과 대본 LLM 으로 돈다. 인터넷·실제 AI 없음."""
import json
import shutil
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents"))

from scout_fixtures import FX, HAPPY, JSI, SGP, Script  # noqa: E402

from app.agents.llm.base import LLMUnavailable  # noqa: E402
from app.agents.llm.null import NullClient  # noqa: E402
from app.cli import main  # noqa: E402
from app.data_layer.notice_board import fixture_http  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARGS = ["--asof", "2026-11-14", "notice", "--scout"]
NOT_RELEVANT = [("finish", {"decision": "NOT_RELEVANT", "reason": "시험용으로 해당 없음 처리"})]


def _fertilizer_steps():
    """유기질비료(추가) 공고를 읽는 손으로 쓴 단계(시연 답 파일 S1 에서 가져온다)."""
    steps = json.loads((ROOT / "data" / "replay" / "answers" / "S1.json").read_text(encoding="utf-8"))["notice"][4:8]
    assert [c["tool_calls"][0]["name"] for c in steps] == ["doc_search", "find_existing_program", "validate_draft", "finish"]
    return [[(c["name"], c["args"]) for c in st["tool_calls"]] for st in steps]


FULL = HAPPY + [NOT_RELEVANT] + _fertilizer_steps() + [NOT_RELEVANT]      # 찾기 대본 뒤에 고른 글 셋(유기농업자재·유기질비료·FTA)을 읽는 대본


def _root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "data" / "tables", tmp_path / "data" / "tables")
    return tmp_path


def _scout_dir(root: Path) -> Path:
    (d,) = [p for p in (root / "data" / "inbox").iterdir() if p.name.startswith("scout-")]
    return d


def _run(root, steps, extra=(), http=None, llm=None, clock=lambda: time(9, 30, 5)):
    llm = llm or Script(steps)
    sleeps: list[float] = []
    code = main(ARGS + list(extra), root=root, llm=llm, http=http or fixture_http(FX), sleep=sleeps.append, clock=clock)
    return code, llm, sleeps


def test_scout_picks_reads_and_publishes(tmp_path, capsys):
    root = _root(tmp_path)
    code, llm, sleeps = _run(root, FULL)
    assert code == 0
    out = _scout_dir(root)
    assert out.name == "scout-20261114-093005" and sorted(p.name for p in out.iterdir()) == ["report.html", "report.json"]
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["as_of"] == "2026-11-14" and data["days"] == 30 and data["dry_run"] is False and data["stop"] == ""
    assert [p["row"] for p in data["picks"]] == [6, 7, 16]
    assert [p["decision"] for p in data["picks"]] == ["NOT_RELEVANT", "DRAFT_READY", "NOT_RELEVANT"]
    fert = data["picks"][1]
    assert fert["published"] and fert["inbox"].startswith("data/inbox/url-") and fert["dept"] == "대륜동"
    assert "올리지 않았습니다" not in fert["note"]
    assert data["picks"][0]["not_published"] and "농가에 닿는 지원사업이 아니라서" in data["picks"][0]["not_published"][0]
    assert len(data["skips"]) == 13 and data["requests"] == 5 and len(sleeps) == 4      # 목록 둘 + 본문 셋, 사이마다 쉼
    assert [b["name"] for b in data["boards"]][0] == SGP
    # 글마다 공고 에이전트의 결과가 받은 함에 쌓이고, 올린 사업은 지원 전체 보기 목록 파일이 된다
    assert len([p for p in (root / "data" / "inbox").iterdir() if p.name.startswith("url-")]) == 3
    notices = list((root / "data" / "catalog" / "notices").glob("*.json"))
    assert len(notices) == 1
    record = json.loads(notices[0].read_text(encoding="utf-8"))
    assert record["url"].endswith("seq=155891809") and record["decision"] == "DRAFT_READY"
    said = capsys.readouterr().out
    assert "고른 글 3건" in said and "보고서:" in said and "지원 전체 보기에 올렸습니다" in said


def test_report_html_is_readable_korean_and_escaped(tmp_path):
    root = _root(tmp_path)
    _run(root, FULL)
    text = (_scout_dir(root) / "report.html").read_text(encoding="utf-8")
    assert "<body>" in text and "공고 찾기 결과" in text
    for must in ("게시판별로 본 글", "고른 글 3건", "건너뛴 글 13건", "서귀포시 알림마당", "제주도청 농축산 소식",
                 "이번에는 열지 않았어요", "초안 완성(직원 확인 필요)", "해당 없음(개인 농업인 대상 아님)",
                 "감귤유통과가 올린 원문 공고", "같은 사업의 읍면동 글", "AI가 정리한 말"):
        assert must in text, must
    assert 'href="https://www.seogwipo.go.kr/info/news/notice.htm?act=view&amp;seq=155891809"' in text
    for code_word in ("DRAFT_READY", "NOT_RELEVANT", "NEEDS_STAFF", "None", "null", "Traceback"):
        assert code_word not in text, code_word


def test_dry_run_stops_after_picking(tmp_path):
    root = _root(tmp_path)
    code, llm, _ = _run(root, HAPPY, ["--dry-run"])         # 공고 읽기 대본이 없다: 불렀다면 대본이 모자라 실패한다
    assert code == 0 and len(llm.requests) == 5
    out = _scout_dir(root)
    names = [p.name for p in (root / "data" / "inbox").iterdir()]
    assert names == [out.name] and not (root / "data" / "catalog").exists()
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["dry_run"] is True and len(data["picks"]) == 3 and data["requests"] == 2
    assert all(p["decision"] is None and "읽지 않았습니다" in p["note"] for p in data["picks"])
    assert "고르기까지만" in (out / "report.html").read_text(encoding="utf-8")


def test_days_option_changes_the_window(tmp_path):
    root = _root(tmp_path)
    _, llm, _ = _run(root, [[("list_board", {"board": SGP})], [("finish", {"summary": "끝"})]], ["--days", "2"])
    assert "최근 2일 안에" in llm.requests[0].messages[0].text
    listed = json.loads(llm.requests[1].messages[-1].tool_results[0].content)
    assert {r["posted"] for r in listed["rows"]} == {"2026-11-12", "2026-11-13"} and listed["hidden_old"] == 3
    assert json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))["days"] == 2


def test_no_key_reports_why_and_exits_nonzero(tmp_path, capsys):
    root = _root(tmp_path)
    code = main(ARGS, root=root, llm=NullClient(), http=fixture_http(FX), sleep=lambda s: None)
    said = capsys.readouterr().out
    assert code == 1 and "AI 열쇠가 없어" in said and "keys.bat" in said
    data = json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))
    assert data["picks"] == [] and data["requests"] == 0 and data["unavailable"] == "NO_KEY"
    assert "AI 열쇠가 없어" in (_scout_dir(root) / "report.html").read_text(encoding="utf-8")


def test_ai_failing_midway_keeps_what_was_picked(tmp_path):
    root = _root(tmp_path)
    steps = HAPPY[:2] + [LLMUnavailable("OVERLOADED")] + [NOT_RELEVANT, NOT_RELEVANT]
    code, _, _ = _run(root, steps)
    assert code == 0
    data = json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))
    assert [p["row"] for p in data["picks"]] == [6, 7] and "AI가 잠시 바빠서" in data["stop"]
    assert [p["decision"] for p in data["picks"]] == ["NOT_RELEVANT", "NOT_RELEVANT"]


def test_option_misuse(tmp_path, capsys):
    root = _root(tmp_path)
    llm = Script([])
    for argv, text in ((["notice", "--scout", "공고.txt"], "같이 쓸 수 없습니다"),
                       (["notice", "--scout", "--url", "https://www.jejusi.go.kr/a"], "같이 쓸 수 없습니다"),
                       (["notice", "--scout", "--days", "0"], "1에서 365"),
                       (["notice", "--scout", "--days", "400"], "1에서 365"),
                       (["notice", "--days", "5", "x.txt"], "--scout 와 함께만"),
                       (["notice", "--dry-run", "x.txt"], "--scout 와 함께만")):
        assert main(argv, root=root, llm=llm, http=fixture_http(FX), sleep=lambda s: None) == 2
        assert text in capsys.readouterr().out
    assert llm.requests == [] and not (root / "data" / "inbox").exists()


def test_no_catalog_neither_publishes_nor_marks_read(tmp_path):
    root = _root(tmp_path)
    _run(root, FULL, ["--no-catalog"])
    assert not (root / "data" / "catalog").exists()
    data = json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))
    assert data["no_catalog"] is True and "올리지 않았습니다(--no-catalog)" in data["picks"][1]["note"]
    # 받은 함에 url-* 가 생겼어도 --no-catalog 로 다시 찾으면 이미 읽음 표시를 하지 않는다
    shutil.rmtree(root / "data" / "inbox" / _scout_dir(root).name)
    _, llm, _ = _run(root, [[("list_board", {"board": SGP})], [("finish", {"summary": "끝"})]], ["--no-catalog"], clock=lambda: time(9, 31, 0))
    listed = json.loads(llm.requests[1].messages[-1].tool_results[0].content)
    assert not any(r["already_read"] for r in listed["rows"])


def test_second_scout_marks_the_first_ones_as_already_read(tmp_path):
    root = _root(tmp_path)
    _run(root, FULL)
    steps = [[("list_board", {"board": SGP})], [("list_board", {"board": SGP, "query": "FTA"})], [("finish", {"summary": "끝"})]]
    _, llm, _ = _run(root, steps, clock=lambda: time(9, 31, 0))
    first = json.loads(llm.requests[1].messages[-1].tool_results[0].content)
    second = json.loads(llm.requests[2].messages[-1].tool_results[0].content)
    # 7번은 목록 파일로, 6·16번은 받은 함 폴더로 이미 읽은 글이다(어느 쪽에 있어도 표시)
    assert [r["row"] for r in first["rows"] if r["already_read"]] == [6, 7]
    assert [r["row"] for r in second["rows"] if r["already_read"]] == [16]


def test_unreadable_pick_is_reported_not_fatal(tmp_path):
    root = _root(tmp_path)
    steps = [[("list_board", {"board": SGP})], [("pick", {"row": 1, "reason": "시험"})], [("finish", {"summary": "끝"})]]
    code, _, _ = _run(root, steps)       # 1번 글(주간행사계획)은 고정본에 상세가 없다
    assert code == 0
    pick = json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))["picks"][0]
    assert pick["decision"] is None and "고정본에 없는" in pick["error"]
    assert "읽지 못했어요" in (_scout_dir(root) / "report.html").read_text(encoding="utf-8")


def test_a_board_that_will_not_open_is_in_the_report(tmp_path):
    def http(url):
        if "seogwipo" in url:
            raise OSError("연결 안 됨")
        return fixture_http(FX)(url)
    root = _root(tmp_path)
    steps = [[("list_board", {"board": SGP})], [("list_board", {"board": "제주시 농수축산국 부서소식"})], [("finish", {"summary": "끝"})]]
    code, _, _ = _run(root, steps, http=http)
    assert code == 0
    boards = {b["name"]: b for b in json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))["boards"]}
    assert "받지 못했습니다" in boards[SGP]["error"] and boards["제주시 농수축산국 부서소식"]["seen"] == 5
    assert "받지 못했습니다" in (_scout_dir(root) / "report.html").read_text(encoding="utf-8")


def test_report_has_no_person_names_and_escapes_titles(tmp_path):
    html = ('<table><tr><th>제목</th></tr><tr><td class="title"><a href="/information/intro/news.do?mode=detail&notice_id=zz1">'
            '&lt;script&gt;alert(1)&lt;/script&gt; 지원 안내</a></td><td class="writer">홍길동</td><td class="date">2026-11-13</td></tr></table>').encode()
    root = _root(tmp_path)
    steps = [[("list_board", {"board": JSI})], [("skip", {"row": 1, "reason": "안내 글"})], [("finish", {"summary": "끝"})]]
    _run(root, steps, http=lambda u: html)
    out = _scout_dir(root)
    page = (out / "report.html").read_text(encoding="utf-8")
    text = page + (out / "report.json").read_text(encoding="utf-8")
    assert "홍길동" not in text and "<script>" not in page and "&lt;script&gt;" in page


def test_notice_bat_forwards_scout_arguments():
    bat = (ROOT / "notice.bat").read_bytes()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    assert b'if /i "%~1"=="--scout" (\r\n  "%PY%" -X utf8 -m app.cli notice %*\r\n  exit /b %errorlevel%\r\n)' in bat
    assert '"%PY%" -X utf8 -m app.cli notice "%~1"'.encode() in bat          # 기존 파일 읽기 줄은 그대로


def test_existing_file_notice_still_rejects_scout_only_flags_without_scout(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["notice"], root=root, llm=Script([])) == 2          # 아무것도 안 넣으면 예전처럼 사용법
    assert "사용법" in capsys.readouterr().out


def test_failed_reading_does_not_mark_the_posts_as_already_read(tmp_path):
    root = _root(tmp_path)
    steps = HAPPY[:2] + [LLMUnavailable("OVERLOADED")] * 6
    code, _, _ = _run(root, steps)
    assert code == 1                                      # 읽는 중 AI 를 못 써도 알린다
    data = json.loads((_scout_dir(root) / "report.json").read_text(encoding="utf-8"))
    assert [p["decision"] for p in data["picks"]] == ["NEEDS_STAFF", "NEEDS_STAFF"]
    assert "AI가 잠시 바빠서" in data["stop"] and "읽는 중" in data["stop"]
    assert all("다시 찾으면 또 나옵니다" in " ".join(p["not_published"]) for p in data["picks"])
    shutil.rmtree(root / "data" / "inbox" / _scout_dir(root).name)
    _, llm, _ = _run(root, [[("list_board", {"board": SGP})], [("finish", {"summary": "끝"})]], clock=lambda: time(9, 31, 0))
    listed = json.loads(llm.requests[1].messages[-1].tool_results[0].content)
    assert not any(r["already_read"] for r in listed["rows"])


def test_catalog_dir_option_moves_notices_and_inbox(tmp_path):
    root = _root(tmp_path)
    cat = tmp_path / "elsewhere" / "catalog"
    llm = Script(FULL)
    code = main(ARGS + ["--catalog-dir", str(cat)], root=root, llm=llm, http=fixture_http(FX), sleep=lambda s: None,
                clock=lambda: time(9, 30, 5))
    assert code == 0
    assert len(list((cat / "notices").glob("*.json"))) == 1
    inbox = tmp_path / "elsewhere" / "inbox"
    assert len([p for p in inbox.iterdir() if p.name.startswith("url-")]) == 3 and any(p.name.startswith("scout-") for p in inbox.iterdir())
    assert not (root / "data" / "catalog").exists() and not (root / "data" / "inbox").exists()


def test_catalog_dir_keyword_for_tests(tmp_path):
    root = _root(tmp_path)
    cat = tmp_path / "elsewhere" / "catalog"
    code = main(ARGS, root=root, llm=Script(FULL), http=fixture_http(FX), sleep=lambda s: None, catalog_dir=cat)
    assert code == 0 and list((cat / "notices").glob("*.json")) and not (root / "data" / "catalog").exists()
