"""열쇠 없는 끝에서 끝(Task 21): P4 입력 → 확인 → 인쇄. LLM 호출 0회, 인쇄 보류, 미리보기, 검수 과정 보기."""
from types import SimpleNamespace

from app.agents.counsel import narrate
from app.agents.llm.null import NullClient
from app.agents.reviewer import MemoryReviewLog, ReviewOutcome
from app.agents.rules import Section, Sentence

import logging

import pytest

from .conftest import P2_FORM, P4_FORM


def post_profile(client, form=None):
    assert client.post("/counsel/input", data=form or P4_FORM).status_code == 303


class CountingNarrator:
    """Task 28의 narrate를 대신하는 가짜: 호출 횟수를 센다. Narrative처럼 sections·texts()를 가진다.
    log를 주면 P4(애월읍) 상담일 때만 걸린 규칙(NUM_DIGIT)을 그 검수 로그에 쓴다."""

    def __init__(self, log=None):
        self.calls = 0
        self.log = log

    def __call__(self, fs):
        self.calls += 1
        if self.log is not None and fs.profile.emd_code == "애월읍":
            self.log.write({"section": "action", "attempt": 1, "checks": [{"rule": "NUM_DIGIT", "sid": 1}], "verdict": "REJECT"})
        sent = Section(section="action", sentences=(Sentence(sid=1, text="경영체 등록부터 하시면 좋습니다.", cites=("A:a_x",)),))
        return SimpleNamespace(
            sections={"action": ReviewOutcome(final=sent, source="ai_pass", attempts=2),
                      "support": ReviewOutcome(final=Section(section="support", sentences=()), source="template", attempts=3)},
            texts=lambda: {"action": ["경영체 등록부터 하시면 좋습니다."]})


class SpyClient:
    """NullClient처럼 열쇠가 없는 LLMClient. generate가 불리면(=narrate가 첫 구획에서 LLM을 찾아봄) 횟수를 세고
    LLMUnavailable("NO_KEY")를 올린다. 모델까지 간 호출(reached_model)은 늘 0이어야 한다."""
    provider = "none"
    model = "none"

    def __init__(self):
        self.probes = 0
        self.reached_model = 0
        self._inner = NullClient()

    def generate(self, req):
        self.probes += 1
        result = self._inner.generate(req)      # 열쇠가 없으면 여기서 LLMUnavailable("NO_KEY")
        self.reached_model += 1                  # 여기까지 오면 모델이 답을 돌려준 것
        return result


@pytest.fixture
def client_nokey(client_demo):
    """열쇠 없는 앱: 진짜 narrate(Task 28)를 쓰되 LLM은 SpyClient다. 템플릿 문장으로 간다."""
    state = client_demo.app.state
    state.llm_spy = spy = SpyClient()
    state.review_log = log = MemoryReviewLog()
    state.narrator = lambda fs: narrate(fs, spy, log)
    return client_demo


def llm_calls(client) -> int:
    return client.app.state.llm_spy.reached_model


def test_nokey_e2e_p4_prints(client_nokey):
    client = client_nokey
    post_profile(client)
    client.post("/counsel/confirm", data={})
    r = client.get("/counsel/print")
    assert r.status_code == 200 and 'data-page="front"' in r.text and 'data-page="back"' not in r.text and "종이를 뽑지 못했어요" not in r.text      # 종이는 앞면 한 면뿐이다
    assert llm_calls(client) == 0 and client.app.state.llm_spy.probes == 1      # 열쇠 확인에서 멈추고 모델에는 가지 않는다
    panel = client.get("/counsel/preview").text
    assert "기본 문장(템플릿)" in panel and "AI 문장 통과" not in panel


def test_print_without_session_goes_to_input(client_demo):
    r = client_demo.get("/counsel/print")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/input"


def test_print_hold_page_lists_reasons(client_demo, monkeypatch):
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    monkeypatch.setattr("app.ui.routes_counsel.preflight", lambda html, fs, cfg: ["OVERFLOW", "HOLD_ROW"])
    r = client_demo.get("/counsel/print")
    assert r.status_code == 200 and "종이를 뽑지 못했어요" in r.text
    assert "종이 한 쪽에 글이 다 안 들어갈 수 있어요." in r.text and "근거를 확인 중인 지원의 숫자가 찍혔어요." in r.text and "뒷면" not in r.text
    assert "OVERFLOW" in r.text and 'data-page="front"' not in r.text


def test_screen_preview_differs_only_by_zoom_css(client_demo):
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    printed = client_demo.get("/counsel/print").text
    screen = client_demo.get("/counsel/preview?view=screen").text
    assert screen != printed and "data-screen-zoom" in screen
    assert screen.replace(screen[screen.index("<style data-screen-zoom"):screen.index("</style>", screen.index("data-screen-zoom")) + 9], "") == printed


def test_result_page_has_review_panel_without_narrator(client_demo):
    client_demo.app.state.narrator = None      # 설명 에이전트 자체가 없는 앱
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    r = client_demo.get("/counsel/preview")
    assert r.status_code == 200 and "직원이 볼 내용" in r.text and "설명 없음 · 템플릿" in r.text
    assert "/counsel/preview?view=screen" in r.text and "/counsel/print" in r.text


def test_review_panel_shows_attempts_rules_and_source(client_demo):
    log = MemoryReviewLog()
    client_demo.app.state.review_log = log
    narrator = client_demo.app.state.narrator = CountingNarrator(log)
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    r = client_demo.get("/counsel/preview")
    assert narrator.calls == 1
    assert "숫자를 씀" in r.text and "AI 문장 통과" in r.text and "기본 문장" in r.text
    assert "경영체 등록부터" not in client_demo.get("/counsel/print").text      # 설명 문장은 종이에 없다(결과 화면 맨 위 띠에만 있다)


def test_api_docs_are_off(client_demo):
    assert all(client_demo.get(p).status_code == 404 for p in ("/docs", "/redoc", "/openapi.json"))


def test_review_rules_do_not_leak_between_sessions(client_demo):
    log = MemoryReviewLog()
    client_demo.app.state.review_log = log
    client_demo.app.state.narrator = CountingNarrator(log)
    post_profile(client_demo)                                   # 첫 상담(P4): 규칙이 걸린다
    client_demo.post("/counsel/confirm", data={})
    assert "숫자를 씀" in client_demo.get("/counsel/preview").text
    client_demo.cookies.clear()
    post_profile(client_demo, P2_FORM)                          # 다른 상담(P2): 로그에는 앞 상담 기록이 남아 있다
    client_demo.post("/counsel/confirm", data={})
    assert log.entries and "숫자를 씀" not in client_demo.get("/counsel/preview").text


def test_narrator_failure_still_prints_without_narrative(client_demo, caplog):
    def boom(fs):
        raise RuntimeError("narrator down")
    client_demo.app.state.narrator = boom
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    with caplog.at_level(logging.ERROR):
        r = client_demo.get("/counsel/print")
    assert r.status_code == 200 and "종이를 뽑지 못했어요" not in r.text and 'data-page="front"' in r.text
    assert "narrator down" in caplog.text


def test_fact_sheet_failure_shows_hold_page_not_500(client_demo, monkeypatch, caplog):
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})

    def boom(*a, **k):
        raise ValueError("bad table")
    monkeypatch.setattr("app.ui.routes_counsel.build_fact_sheet", boom)
    with caplog.at_level(logging.ERROR):
        for path in ("/counsel/print", "/counsel/preview", "/counsel/preview?view=screen"):
            r = client_demo.get(path)
            assert r.status_code == 200 and "종이를 뽑지 못했어요" in r.text and "종이를 만들지 못했어요" in r.text, path
    assert "bad table" in caplog.text


def test_paper_built_once_per_consultation(client_demo, monkeypatch):
    import app.ui.routes_counsel as rc
    calls = []
    real = rc.build_fact_sheet
    monkeypatch.setattr(rc, "build_fact_sheet", lambda *a, **k: calls.append(1) or real(*a, **k))
    post_profile(client_demo)
    client_demo.post("/counsel/confirm", data={})
    for path in ("/counsel/preview", "/counsel/preview?view=screen", "/counsel/print"):
        assert client_demo.get(path).status_code == 200
    assert len(calls) == 1
