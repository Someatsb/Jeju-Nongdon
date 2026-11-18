"""맞춰 보기·찾아보기가 하루 호출 한도(설명 글과 같이 쓰는 것)를 닳게 하지 않는다.

- 같은 프로필 내용이면(답을 다시 확인해도) 맞춰 보기 결과를 다시 쓰고 AI 를 또 부르지 않는다.
- 동시에 도는 맞춰 보기 수를 제한한다.
- 맞춰 보기와 찾아보기는 따로 하루 한도를 갖고, 설명 글 몫은 남는다.
"""
import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest
from .test_match_async import CITRUS_FORM, DEADLINE_S, MatchLLM, ai, answer, app_client, catalog_dir, wait_match  # noqa: F401

from app.agents.llm.base import GenRequest, LLMUnavailable, Msg
from app.agents.llm.guard import Guard, SideCap
from app.agents.match import MatchReport
from app.ui import match_job


def test_same_answers_confirmed_again_do_not_call_the_ai_again(app_client):
    llm = MatchLLM()
    client = app_client(llm)
    answer(client, CITRUS_FORM)
    first = wait_match(client)["match"]
    assert first["state"] == "done"
    n = len(llm.requests)
    assert n > 0
    for _ in range(3):
        answer(client, CITRUS_FORM)
        assert wait_match(client)["match"]["lines"] == first["lines"]
    assert len(llm.requests) == n


def _fake_run(monkeypatch, gate=None):
    seen = {"calls": 0, "now": 0, "max": 0}
    lock = threading.Lock()

    def run(profile, fs, notices, crops, llm, log, **kw):
        with lock:
            seen["calls"] += 1
            seen["now"] += 1
            seen["max"] = max(seen["max"], seen["now"])
        if gate is not None:
            gate.wait(5)
        time.sleep(0.05)
        with lock:
            seen["now"] -= 1
        return MatchReport(source="ai")
    monkeypatch.setattr(match_job, "run_match", run)
    return seen


def test_same_fingerprint_at_the_same_time_runs_once(monkeypatch):
    seen = _fake_run(monkeypatch)
    m = match_job.make_matcher(object(), [], date(2026, 11, 13))
    fs, notices = SimpleNamespace(fingerprint="abc"), [SimpleNamespace(key="n1")]
    ts = [threading.Thread(target=m, args=(object(), fs, notices)) for _ in range(4)]
    [t.start() for t in ts]
    [t.join(DEADLINE_S) for t in ts]
    assert seen["calls"] == 1
    m(object(), fs, [SimpleNamespace(key="n2")])        # 볼 공고가 달라지면 새로 본다
    assert seen["calls"] == 2


def test_running_matches_are_limited(monkeypatch):
    seen = _fake_run(monkeypatch)
    m = match_job.make_matcher(object(), [], date(2026, 11, 13))
    ts = [threading.Thread(target=m, args=(object(), SimpleNamespace(fingerprint=f"f{i}"), [SimpleNamespace(key="n")])) for i in range(8)]
    [t.start() for t in ts]
    [t.join(DEADLINE_S * 2) for t in ts]
    assert seen["calls"] == 8 and seen["max"] <= match_job.MATCH_MAX_PARALLEL


class Counting:
    provider = model = "fake"

    def __init__(self):
        self.n = 0

    def generate(self, req):
        self.n += 1
        return "ok"


REQ = GenRequest(purpose="match", section=None, system="s", messages=(Msg(role="user", text="q"),))


def test_side_cap_stops_helpers_and_leaves_the_rest_for_narration():
    inner = Counting()
    guard = Guard(inner, daily_cap=10, today_fn=lambda: date(2026, 11, 13))
    side = SideCap(guard, cap=4, today_fn=lambda: date(2026, 11, 13))
    for _ in range(4):
        side.generate(REQ)
    with pytest.raises(LLMUnavailable) as e:
        side.generate(REQ)
    assert e.value.reason == "DAILY_CAP" and inner.n == 4
    for _ in range(6):                                    # 설명 글 몫은 그대로 남아 있다
        guard.generate(REQ)
    assert inner.n == 10
    assert side.provider == "fake" and side.model == "fake"


def test_side_cap_resets_next_day():
    day = [date(2026, 11, 13)]
    side = SideCap(Counting(), cap=1, today_fn=lambda: day[0])
    side.generate(REQ)
    with pytest.raises(LLMUnavailable):
        side.generate(REQ)
    day[0] = date(2026, 11, 14)
    side.generate(REQ)
