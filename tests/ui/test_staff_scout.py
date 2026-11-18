"""직원 메뉴의 "공고 찾아보기": 단추 -> 진행 -> 보고 흐름. 가짜 AI·저장된 게시판 틀로만 돈다(인터넷·실제 AI 없음)."""
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from scout_fixtures import FX, HAPPY, Script  # noqa: E402

from app.agents.llm.null import NullClient  # noqa: E402
from app.config import APP_ROOT  # noqa: E402
from app.data_layer.notice_board import fixture_http  # noqa: E402
from app.data_layer.notice_url import ALLOWED_HOSTS, NoticeUrlError  # noqa: E402
from app.ui.scout_job import NOT_CHOSEN_TEXT, REPLAY_NOTE  # noqa: E402

from .conftest import _started_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOT_RELEVANT = [("finish", {"decision": "NOT_RELEVANT", "reason": "시험용으로 해당 없음 처리"})]


def _fertilizer_steps():
    steps = json.loads((ROOT / "data" / "replay" / "answers" / "S1.json").read_text(encoding="utf-8"))["notice"][4:8]
    return [[(c["name"], c["args"]) for c in st["tool_calls"]] for st in steps]


FULL = HAPPY + [NOT_RELEVANT] + _fertilizer_steps() + [NOT_RELEVANT]


def _tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else []


@pytest.fixture
def work(tmp_path):
    shutil.copytree(ROOT / "data" / "tables", tmp_path / "data" / "tables")
    return tmp_path


def _make(work, llm, http=None, argv=("--asof", "2026-11-14")):
    c = _started_client(list(argv), llm=llm)
    run = c.app.state.scout
    run.root, run.sleep, run.pace_s = work, (lambda s: None), 0
    seen: list[str] = []
    base = http or fixture_http(FX)

    def spy(url):
        seen.append(url)
        return base(url)
    run.http = spy
    c.urls = seen
    return c


@pytest.fixture
def scout_client(work):
    c = _make(work, Script(FULL))
    yield c
    c.__exit__(None, None, None)


def _wait(c, want=("done", "failed"), secs=20):
    end = time.monotonic() + secs
    j = {}
    while time.monotonic() < end:
        j = c.get("/staff/scout/status").json()
        if j["state"] in want:
            return j
        time.sleep(0.05)
    raise AssertionError(f"끝나지 않았습니다: {j}")


def test_staff_menu_has_the_button_and_one_line(client_demo):
    t = client_demo.get("/staff").text
    assert 'action="/staff/scout"' in t and 'method="post"' in t.lower()
    assert "공고 찾아보기" in t
    assert "공식 게시판에서 농가 지원 공고를 찾아 읽고, 원문과 맞는 것만 지원 전체 보기에 올려요" in t


def test_no_job_yet(client_demo):
    assert client_demo.get("/staff/scout/status").json() == {"state": "none"}
    r = client_demo.get("/staff/scout")
    assert r.status_code == 303 and r.headers["location"] == "/staff"


def test_button_progress_report_flow(scout_client, work):
    real_before = _tree(APP_ROOT / "data" / "catalog")
    r = scout_client.post("/staff/scout")
    assert r.status_code == 303 and r.headers["location"] == "/staff/scout"
    j = _wait(scout_client)
    assert j["state"] == "done" and j["seen"] == 16 and j["picked"] == 3 and j["stage"] == "끝났어요"
    page = scout_client.get("/staff/scout").text
    for must in ("본 글", "고른 글 3건", "건너뛴 글", "유기농업자재", "감귤유통과가 올린 원문 공고", "목록에 올림",
                 "지원 전체 보기에서 보기", "해당 없음", "걸린 시간", "게시판 요청", "도구 호출"):
        assert must in page, must
    assert NOT_CHOSEN_TEXT in page and "고르지 않았습니다(" not in page
    assert 'href="/supports/new-' in page and 'href="/supports"' in page
    assert REPLAY_NOTE not in page
    # 올린 곳은 이 시험의 임시 폴더, 실제 data/catalog 는 그대로
    assert list((work / "data" / "catalog" / "notices").glob("*.json"))
    assert _tree(APP_ROOT / "data" / "catalog") == real_before
    # 받은 주소는 허용된 도메인뿐
    assert scout_client.urls and all(u.split("/")[2] in ALLOWED_HOSTS for u in scout_client.urls)


def test_progress_json_while_running_and_double_press(work):
    gate = threading.Event()

    class Slow(Script):
        def generate(self, req):
            if len(self.requests) == 1:       # 목록을 본 뒤 두 번째 답에서 멈춰 서서 진행 화면을 본다
                assert gate.wait(10)
            return super().generate(req)

    llm = Slow(FULL)
    c = _make(work, llm)
    try:
        first = c.post("/staff/scout")
        end = time.monotonic() + 10
        while time.monotonic() < end and c.get("/staff/scout/status").json().get("seen", 0) < 1:
            time.sleep(0.05)
        j = c.get("/staff/scout/status").json()
        assert j["state"] == "run" and j["seen"] == 12 and j["picked"] == 0 and j["stage"]
        prog = c.get("/staff/scout")
        assert prog.status_code == 200 and "찾는 중" in prog.text and "/staff/scout/status" in prog.text
        second = c.post("/staff/scout")
        assert first.status_code == second.status_code == 303 and second.headers["location"] == "/staff/scout"
        gate.set()
        assert _wait(c)["state"] == "done"
        assert len([x for x in llm.requests if x.purpose == "scout"]) == 5     # 두 번 눌러도 한 번만 돌았다
    finally:
        gate.set()
        c.__exit__(None, None, None)


def test_stage_texts_follow_the_steps(scout_client):
    scout_client.post("/staff/scout")
    _wait(scout_client)
    stages = scout_client.app.state.scout.job.stages
    assert stages[0] == "게시판 목록을 읽는 중" and "공고를 고르는 중" in stages
    reading = [s for s in stages if s.startswith("고른 공고 3건 가운데 ")]
    assert [s[-9:] for s in reading] == ["1번째를 읽는 중", "2번째를 읽는 중", "3번째를 읽는 중"]
    assert "원문과 맞춰 보는 중" in stages and stages.index("원문과 맞춰 보는 중") > stages.index(reading[0])
    assert stages[-1] == "보고서를 정리하는 중"


def test_no_key_is_told_in_plain_words(work):
    c = _make(work, NullClient())
    try:
        c.post("/staff/scout")
        assert _wait(c)["state"] == "done"
        page = c.get("/staff/scout").text
        assert "AI 열쇠" in page and "공고를 찾지 못했어요" in page and "고른 글 0건" in page
        assert "Traceback" not in page and "NO_KEY" not in page
    finally:
        c.__exit__(None, None, None)


def test_no_network_is_told_in_plain_words(work):
    def down(url):
        raise NoticeUrlError("페이지를 받지 못했습니다(OSError). 인터넷 연결을 확인하세요")

    steps = [[("list_board", {"board": b})] for b in ("seogwipo", "jejusi")] + [[("finish", {"summary": "열린 게시판이 없어요"})]]
    c = _make(work, Script(steps), http=down)
    try:
        c.post("/staff/scout")
        assert _wait(c)["state"] == "done"
        assert "게시판에 연결하지 못했어요" in c.get("/staff/scout").text
    finally:
        c.__exit__(None, None, None)


def test_crash_becomes_failed_page(work):
    class Boom(Script):
        def generate(self, req):
            raise RuntimeError("터짐")

    c = _make(work, Boom([]))
    try:
        c.post("/staff/scout")
        assert _wait(c)["state"] == "failed"
        page = c.get("/staff/scout").text
        assert "예상하지 못한 문제" in page and "RuntimeError" not in page
        c.post("/staff/scout")                  # 끝난 뒤에는 다시 시작할 수 있다
        assert c.get("/staff/scout/status").json()["state"] in ("run", "failed")
    finally:
        c.__exit__(None, None, None)


def test_cross_origin_post_is_refused_and_starts_nothing(scout_client):
    r = scout_client.post("/staff/scout", headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert scout_client.get("/staff/scout/status").json() == {"state": "none"}
    r = scout_client.post("/staff/scout", headers={"origin": f"http://127.0.0.1:{scout_client.app.state.cfg.port}"})
    assert r.status_code == 303


def test_get_does_not_start_a_job(scout_client):
    scout_client.get("/staff/scout")
    assert scout_client.get("/staff/scout/status").json() == {"state": "none"}


def test_replay_mode_shows_saved_run_and_leaves_real_folders(client_replay):
    before = (_tree(APP_ROOT / "data" / "catalog"), _tree(APP_ROOT / "data" / "inbox"))
    assert "공고 찾아보기" in client_replay.get("/staff").text
    client_replay.app.state.scout.pace_s = 0
    assert client_replay.post("/staff/scout").status_code == 303
    assert _wait(client_replay)["state"] == "done"
    page = client_replay.get("/staff/scout").text
    assert REPLAY_NOTE in page and "고른 글 3건" in page and "대륜동" in page
    assert "목록에 올림" in page and 'href="/supports/new-' not in page       # 임시 폴더에 올렸으니 실제 지원 안내 화면은 없다
    assert (_tree(APP_ROOT / "data" / "catalog"), _tree(APP_ROOT / "data" / "inbox")) == before


def test_progress_hint_does_not_promise_minutes_in_replay_mode(client_replay):
    client_replay.app.state.scout.pace_s = 0.3                                   # 진행 화면이 잠깐 보이게 천천히
    assert client_replay.post("/staff/scout").status_code == 303
    page = client_replay.get("/staff/scout").text
    assert "찾는 중" in page and "저장해 둔 기록을 다시 보여 드려요" in page and "1~2분" not in page
    client_replay.app.state.scout.pace_s = 0
    assert _wait(client_replay)["state"] == "done"


def test_progress_hint_keeps_the_minutes_in_real_mode(work):
    gate = threading.Event()

    class Slow(Script):
        def generate(self, req):
            if len(self.requests) == 1:
                assert gate.wait(10)
            return super().generate(req)

    c = _make(work, Slow(FULL))
    try:
        c.post("/staff/scout")
        page = c.get("/staff/scout").text
        assert "1~2분쯤 걸려요" in page and "저장해 둔 기록을 다시" not in page
    finally:
        gate.set()
        _wait(c)
        c.__exit__(None, None, None)


def test_replay_refuses_changed_fixtures(client_replay, tmp_path):
    replay = tmp_path / "replay"
    shutil.copytree(APP_ROOT / "data" / "replay", replay)
    page = replay / "boards" / "seogwipo_list.html"
    page.write_text(page.read_text(encoding="utf-8") + "\n<!-- 바뀜 -->\n", encoding="utf-8")
    run = client_replay.app.state.scout
    run.replay_dir, run.pace_s = replay, 0
    client_replay.post("/staff/scout")
    assert _wait(client_replay)["state"] == "done"
    assert "고정본이 바뀌었어요" in client_replay.get("/staff/scout").text


def test_button_follows_catalog_dir_setting(work):
    """서버를 --catalog-dir 로 띄우면 올린 공고(과 읽은 것을 두는 inbox)는 그 폴더 옆에만 쓰고, 기본 폴더는 그대로다."""
    cat = work / "elsewhere" / "catalog"
    c = _make(work, Script(FULL), argv=("--asof", "2026-11-14", "--catalog-dir", str(cat)))
    try:
        real_before = _tree(APP_ROOT / "data" / "catalog")
        real_inbox = _tree(APP_ROOT / "data" / "inbox")
        c.post("/staff/scout")
        assert _wait(c)["state"] == "done"
        assert list((cat / "notices").glob("*.json"))
        inbox = work / "elsewhere" / "inbox"
        assert any(p.name.startswith("url-") for p in inbox.iterdir()) and any(p.name.startswith("scout-") for p in inbox.iterdir())
        assert not (work / "data" / "catalog").exists() and not (work / "data" / "inbox").exists()
        assert _tree(APP_ROOT / "data" / "catalog") == real_before and _tree(APP_ROOT / "data" / "inbox") == real_inbox
        page = c.get("/supports").text            # 화면은 같은 폴더를 읽는다
        assert "유기농업자재" in page or "유기질" in page
    finally:
        c.__exit__(None, None, None)


def test_outcomes_say_when_the_business_was_already_listed_or_upgraded(tmp_path):
    from app.ui.scout_job import outcomes
    cat = tmp_path / "notices"
    cat.mkdir()
    (cat / "a.json").write_text(json.dumps({"name": "유기농업자재 지원사업", "table_key": None}, ensure_ascii=False), encoding="utf-8")
    data = {"picks": [
        {"published": [], "not_published": ["이미 목록에 있는 사업이라 올리지 않았습니다: 유기농업자재 지원사업"], "decision": "DRAFT_READY", "decision_label": "초안"},
        {"published": ["a.json"], "not_published": [], "upgraded": ["같은 사업의 더 온전한 글로 바꿨습니다: 유기농업자재 지원사업"],
         "decision": "DRAFT_READY", "decision_label": "초안"}]}
    outcomes(data, tmp_path, links=True, catalog_dir=tmp_path)
    first, second = data["picks"]
    assert first["outcome"] == "duplicate" and first["outcome_label"] == "이미 있는 사업이라 안 올림"
    assert any("이미 목록에 있는 사업이라 올리지 않았습니다: 유기농업자재 지원사업" in d for d in first["details"])
    assert second["outcome"] == "listed" and any("더 온전한 글로 바꿨습니다" in d for d in second["details"])
