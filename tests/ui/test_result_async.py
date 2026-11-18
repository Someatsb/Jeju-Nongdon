"""결과를 먼저 보이고 AI 글은 뒤따라 채운다(결과 v2 설계 6절): 느린 가짜 narrator 로 본다. 실제로 오래 자지 않는다(이벤트로 멈췄다 푼다).

- 결과 화면은 narrator 를 기다리지 않고 뜨며 AI 글 자리 표시가 있다.
- /counsel/ai 가 run → done 으로 바뀌고 조각에 문장이 있다.
- 인쇄는 기다렸다가 문장이 든 종이를 주고, 예산을 넘기면 기본 문장 종이를 준다.
- 답을 고치면 새 작업이 뜨고 옛 결과가 섞이지 않으며, 동시에 두 상담도 섞이지 않는다.
- 재생 모드는 처음부터 채워서 온다. noscript 길(wait=1)은 다 된 화면을 준다.
"""
import threading
import time
from types import SimpleNamespace

import pytest

from app.agents.reviewer import ReviewOutcome
from app.agents.rules import Section, Sentence
from app.ui import render as render_mod, routes_counsel

from .conftest import P2_FORM, P4_FORM
from .test_replay import run_demo

DEADLINE_S = 3.0


class SlowNarrator:
    """gate 가 풀릴 때까지 멈추는 가짜 narrator(안전하게 10초 뒤엔 저절로 푼다). 문장에 상담의 읍·면 이름을 넣어 상담이 섞이는지 본다."""

    def __init__(self, *, fail=False):
        self.gate = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self.fail = fail
        self.emds: list[str] = []

    def __call__(self, fs):
        self.calls += 1
        self.emds.append(fs.profile.emd_code)
        self.started.set()
        self.gate.wait(10)
        if self.fail:
            raise RuntimeError("narrator down")
        text = f"{fs.profile.emd_code} 농가는 차분히 살펴보시면 좋습니다."
        sent = Section(section="action", sentences=(Sentence(sid=1, text=text, cites=("A:a_x",)),))
        return SimpleNamespace(sections={"action": ReviewOutcome(final=sent, source="ai_pass", attempts=1)},
                               texts=lambda: {"action": [text]})


@pytest.fixture
def slow(client_demo):
    n = SlowNarrator()
    client_demo.app.state.narrator = n
    client_demo.app.state.review_log = None
    yield client_demo, n
    n.gate.set()


def answer(client, form=None):
    assert client.post("/counsel/input", data=form or P4_FORM).status_code == 303
    assert client.post("/counsel/confirm", data={}).status_code == 303


def ai(client):
    r = client.get("/counsel/ai")
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def wait_done(client):
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end:
        j = ai(client)
        if j["state"] != "run":
            return j
        time.sleep(0.02)
    raise AssertionError("AI 글이 끝나지 않음")


def test_result_page_does_not_wait_for_narrator(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "AI_WAIT_S", 0.05)
    answer(client)
    t = time.monotonic()
    r = client.get("/counsel/preview")
    assert time.monotonic() - t < DEADLINE_S and r.status_code == 200
    assert n.started.wait(DEADLINE_S) and not n.gate.is_set()
    assert 'data-ai="run"' in r.text and "설명을 쓰고 있어요" in r.text
    assert 'class="rb-ai rb-pending" data-ai-slot="sub"' in r.text          # 결론 아래 한 문장 자리(높이를 미리 잡는 틀)
    assert 'data-ai-slot="detail_ai"' in r.text and 'data-ai-slot="staff"' in r.text
    assert 'data-ai-slot="new_notices" hidden' in r.text                     # 새로 나온 공고 자리는 비어 있으면 안 보인다
    assert "지금 하실 일" in r.text and "종이로 뽑기" in r.text               # 바탕은 그대로
    assert "차분히 살펴보" not in r.text
    assert 'href="/counsel/print?auto=1"' in r.text and "disabled" not in r.text.split('id="print-btn"')[1].split(">")[0]   # 종이로 뽑기는 처음부터 눌린다
    assert 'id="ai-wait"' in r.text and "종이를 준비하고 있어요" in r.text


def test_ai_status_goes_from_run_to_done_with_fragments(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "AI_WAIT_S", 0.05)
    answer(client)
    client.get("/counsel/preview")
    j = ai(client)
    assert j["state"] == "run" and j["fragments"] == {} and set(j) == {"state", "fragments", "match", "match_html"}     # match 는 새 공고 맞춰 보기(test_match_async.py)
    n.gate.set()
    j = wait_done(client)
    assert j["state"] == "done"
    f = j["fragments"]
    assert set(f) == {"sub", "speak", "detail_ai", "staff"}
    assert "애월읍 농가는 차분히 살펴보시면 좋습니다." in f["sub"] and j["match_html"]["new_notices"] == ""
    assert "차분히 살펴보" in f["speak"] and "차분히 살펴보" not in f["detail_ai"]     # 띠 아래 문장을 낱말 풀이 칸에서 되풀이하지 않는다
    assert "AI 문장 통과" in f["staff"] and "확인 번호" in f["staff"] and "설명을 쓰고 있어요" not in f["staff"]
    # 다 된 뒤에 화면을 다시 열면 처음부터 채워서 온다
    page = client.get("/counsel/preview").text
    assert 'data-ai="done"' in page and "설명을 쓰고 있어요" not in page and "애월읍 농가는 차분히 살펴보" in page


def test_ai_status_without_session_is_409(client_demo):
    r = client_demo.get("/counsel/ai")
    assert r.status_code == 409 and r.json() == {"state": "none", "fragments": {}}


def test_working_page_starts_job_once_and_does_not_wait(slow):
    client, n = slow
    assert client.post("/counsel/input", data=P4_FORM).status_code == 303
    t = time.monotonic()
    r = client.get("/counsel/working")
    assert r.status_code == 200 and time.monotonic() - t < DEADLINE_S
    assert n.started.wait(DEADLINE_S)
    assert "data-w-more hidden" in r.text and "/counsel/preview?wait=1" in r.text      # 오래 걸릴 때 보일 안내는 숨겨 두고, 스크립트가 꺼진 길은 다 된 화면을 받는다
    for _ in range(3):
        client.get("/counsel/working")
        client.get("/counsel/ai")
    client.get("/counsel/preview")
    client.get("/counsel/preview?view=screen")
    n.gate.set()
    wait_done(client)
    client.get("/counsel/print")
    assert n.calls == 1                                                      # 같은 상담에서 두 번 띄우지 않는다


def test_print_waits_for_narrator_and_has_sentence(slow):
    client, n = slow
    answer(client)
    threading.Timer(0.3, n.gate.set).start()
    t = time.monotonic()
    r = client.get("/counsel/print")
    assert r.status_code == 200 and 'data-page="front"' in r.text and "차분히 살펴보" not in r.text      # AI 문장은 종이에 없다(결과 화면 맨 위 띠에만)
    assert time.monotonic() - t >= 0.25 and client.get("/counsel/print-status").text == "1"


def test_print_over_budget_uses_default_sentences(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "PRINT_BUDGET_S", 0.1)
    answer(client)
    r = client.get("/counsel/print")
    assert r.status_code == 200 and 'data-page="front"' in r.text and "차분히 살펴보" not in r.text and "종이를 뽑지 못했어요" not in r.text
    n.gate.set()                                                             # 늦게 끝나도 화면은 그 뒤 값으로 채운다
    assert "차분히 살펴보" in wait_done(client)["fragments"]["sub"]


def test_noscript_wait_gives_filled_page(slow):
    client, n = slow
    answer(client)
    threading.Timer(0.2, n.gate.set).start()
    r = client.get("/counsel/preview?wait=1")
    assert 'data-ai="done"' in r.text and "설명을 쓰고 있어요" not in r.text.split('id="detail"')[0] and "차분히 살펴보" in r.text


def test_narrator_failure_is_quiet_and_state_failed(client_demo):
    n = SlowNarrator(fail=True)
    n.gate.set()
    client_demo.app.state.narrator = n
    answer(client_demo)
    j = wait_done(client_demo)
    assert j["state"] == "failed" and j["fragments"]["sub"] == "" and "차분히 살펴보" not in j["fragments"]["detail_ai"]
    page = client_demo.get("/counsel/preview").text
    assert "설명을 쓰고 있어요" not in page and "narrator down" not in page and "오류" not in page.split('id="detail"')[0]
    printed = client_demo.get("/counsel/print")
    assert printed.status_code == 200 and 'data-page="front"' in printed.text


def test_editing_answers_starts_a_new_job_without_mixing(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "AI_WAIT_S", 0.05)
    answer(client)
    client.get("/counsel/preview")
    assert n.started.wait(DEADLINE_S)
    assert client.get("/counsel/input?edit=1").status_code == 200            # 답 고치기는 AI 글을 기다리지 않는다
    answer(client, P2_FORM)                                                  # 답을 고쳐 다시 냄(애월읍 → 구좌읍)
    client.get("/counsel/preview")
    n.gate.set()
    j = wait_done(client)
    assert "구좌읍 농가는" in j["fragments"]["sub"] and "애월읍" not in j["fragments"]["sub"] and "애월읍" not in j["fragments"]["detail_ai"]
    assert sorted(n.emds) == ["구좌읍", "애월읍"]
    printed = client.get("/counsel/print").text
    assert "구좌읍" in printed and "애월읍" not in printed and "구좌읍 농가는" not in printed      # 종이는 고친 답대로, AI 문장은 종이에 없다


def test_two_counsels_do_not_mix(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "AI_WAIT_S", 0.05)
    answer(client)
    client.get("/counsel/preview")
    a = dict(client.cookies)
    client.cookies.clear()
    answer(client, P2_FORM)
    client.get("/counsel/preview")
    b = dict(client.cookies)
    n.gate.set()
    jb = wait_done(client)
    client.cookies.clear()
    client.cookies.update(a)
    ja = wait_done(client)
    assert "구좌읍 농가는" in jb["fragments"]["sub"] and "애월읍" not in jb["fragments"]["sub"]
    assert "애월읍 농가는" in ja["fragments"]["sub"] and "구좌읍" not in ja["fragments"]["sub"]
    assert a != b and sorted(n.emds) == ["구좌읍", "애월읍"]


def test_details_and_screen_paper_do_not_wait(slow, monkeypatch):
    client, n = slow
    monkeypatch.setattr(routes_counsel, "AI_WAIT_S", 0.05)
    answer(client)
    t = time.monotonic()
    page = client.get("/counsel/preview")
    screen = client.get("/counsel/preview?view=screen")
    assert time.monotonic() - t < DEADLINE_S and screen.status_code == 200 and "data-screen-zoom" in screen.text
    assert 'id="detail"' in page.text and "올해는 어려워요" in page.text      # 자세히 보기 덮개 틀은 바탕만으로 있다


def test_replay_result_is_filled_from_the_start(client_replay):
    html = run_demo(client_replay, "P4").text
    assert 'data-ai="done"' in html and "설명을 쓰고 있어요" not in html
    assert "1회 반려 → 2회 통과" in html                                      # 검수 표(직원이 볼 내용)도 처음부터
    assert ai(client_replay)["state"] == "done"
