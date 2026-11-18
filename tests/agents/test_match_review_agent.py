"""새 공고 맞춰 보기 모듈 - 검수 지적 반영 시험(기다림 상한, 끝 날짜 읽기, 공용 기록, 주민번호 꼴 글)."""
from datetime import date

import pytest
from conftest import AS_OF
from counsel_fixtures import BUNDLE, SNAP
from match_fixtures import CROPS, FTA, NOTICES, ScriptClient, StepClock, call, custom_notice, profile, result

from app.agents import match as match_mod
from app.agents.match import run_match
from app.core.pipeline import build_fact_sheet
from app.tools.match_tools import MatchTools
from app.tools.models import ToolLog

FTA_Q = "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"


def go(p, client, notices, log=None, **kw):
    fs = build_fact_sheet(p, BUNDLE, SNAP, AS_OF, "test")
    kw.setdefault("clock", StepClock())
    return run_match(p, fs, notices, CROPS, client, log if log is not None else ToolLog(), as_of=AS_OF, **kw)


def one_round():
    return result(call(1, "check_farmer", notice_key=FTA, kind="작물", quote=FTA_Q, crops=["감귤"]),
                  call(2, "submit_matches", items=[{"notice_key": FTA, "why": "감귤 농가라 맞을 수 있어요"}]))


def test_default_budget_is_thirty_seconds():
    assert match_mod.BUDGET_S == 30


def test_request_timeout_never_exceeds_time_left():
    seen = []

    class Spy(ScriptClient):
        def generate(self, req):
            seen.append(req.timeout_s)
            return super().generate(req)

    def noop(n):
        return result(call(n, "check_farmer", notice_key=FTA, kind="그 밖", quote=FTA_Q + " " * n))

    go(profile(), Spy(noop(1), noop(2), noop(3)), [NOTICES[FTA]], clock=StepClock(9.9), budget_s=20)
    # 시계는 호출마다 9.9초씩 간다: 첫 요청 때 남은 시간 10.1초, 둘째 때 0.2초(1초 하한이 있으면 남은 시간보다 길어진다)
    assert len(seen) == 2 and seen[0] <= 10.1 + 1e-6 and 0 < seen[1] <= 0.2 + 1e-6


def test_expired_notice_with_money_decimal_is_screened_out():
    n = custom_notice("new-old", apply_period="2026. 10. 1.(목) ~ 10. 20.(화) 지원한도 1.5억")
    assert go(profile(), ScriptClient(), [n]).source == "skipped"


def test_shared_log_does_not_eat_the_tool_budget():
    log = ToolLog()
    other = MatchTools(profile(), [NOTICES[FTA]], CROPS, AS_OF)
    reg = other.registry()
    for _ in range(45):
        reg.dispatch("check_farmer", {"notice_key": FTA, "kind": "그 밖", "quote": FTA_Q}, log)
    assert log.tool_calls >= 45
    rep = go(profile(), ScriptClient(one_round()), [NOTICES[FTA]], log=log)
    assert rep.source == "ai"


def test_only_the_notice_with_resident_number_is_left_out():
    bad = custom_notice("new-bad", target="문의 900101-1234567 로 하세요")
    client = ScriptClient(one_round())
    rep = go(profile(), client, [bad, NOTICES[FTA]])
    assert rep.source == "ai" and [i.key for i in rep.items] == [FTA]
    assert "900101" not in client.requests[0].messages[0].text and "보낼 수 없는" in rep.note
