"""공고 에이전트 루프(Task 29) 시험."""
import json

import pytest
from notice_fixtures import BUNDLE, DOC_N1
from notice_loop_fixtures import (DOC_N5, DOC_N6, DOC_N8, GOLDEN_DRAFT_N1, REC_N1, REC_N6, CountingClient, FakeClock,
                                  LoopingClient, call, result)

from app.agents.llm.base import LLMUnavailable
from app.agents.llm.null import NullClient
from app.agents.llm.scripted import ScriptedClient
from app.agents.notice import PROMPT_PATH, NoticeResult, run_notice, unreadable
from app.data_layer.docs_in import extract
from app.tools.models import ToolLog


def test_n1_scripted_loop_matches_golden_draft():
    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, ScriptedClient(REC_N1), log)
    assert d.programs[0].action == "UPDATE" and d.programs[0].match_id.startswith("JEJU-LOGI") and d == GOLDEN_DRAFT_N1
    assert log.tool_calls == 4 and [c.name for c in log.calls][-1] == "finish"


def test_n5_pii_blocks_without_llm():
    c = CountingClient()
    log = ToolLog()
    d = run_notice(DOC_N5, BUNDLE, c, log)
    assert d.decision == "BLOCKED_PII" and c.calls == 0 and log.tool_calls == 0
    assert "010" not in d.reason and "010" not in (d.hint or "")      # 걸린 번호 자체는 남기지 않는다


def test_rrn_in_document_blocks_without_llm():
    c = CountingClient()
    d = run_notice(extract(("지원사업 신청자 명단 공고입니다. " * 4) + chr(10) + "900101-1234567 홍길동 신청"), BUNDLE, c, ToolLog())
    assert d.decision == "BLOCKED_PII" and c.calls == 0


def test_n6_not_relevant():
    d = run_notice(DOC_N6, BUNDLE, ScriptedClient(REC_N6), ToolLog())
    assert d.decision == "NOT_RELEVANT" and not d.programs and not d.partial


def test_loop_stops_at_12():
    c, log = LoopingClient(), ToolLog()
    d = run_notice(DOC_N1, BUNDLE, c, log)
    assert d.partial and log.tool_calls == 12 and d.decision == "NEEDS_STAFF" and c.calls == 12


def test_scanned_pdf_is_unreadable_without_llm():
    assert DOC_N8.scanned
    c = CountingClient()
    d = run_notice(DOC_N8, BUNDLE, c, ToolLog())
    assert d.decision == "UNREADABLE" and c.calls == 0 and "붙여" in d.hint


def test_unreadable_helper_carries_korean_hint():
    d = unreadable("HWP는 PDF로 저장해 주세요")
    assert d.decision == "UNREADABLE" and d.hint == "HWP는 PDF로 저장해 주세요" and not d.programs


def test_timeout_returns_partial_needs_staff():
    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, LoopingClient(), log, timeout_s=90, clock=FakeClock(step=40))
    assert d.partial and d.decision == "NEEDS_STAFF" and log.tool_calls < 12


def test_validate_failure_goes_back_as_tool_result_not_raised():
    bad = {"programs": [{"action": "UPDATE", "match_id": "JEJU-LOGI@2026-27",
                         "fields": {"apply_start": {"value": "2026-07-22", "quote": "원문에 없는 문장"}}}]}

    class Client:
        provider = model = "x"
        def __init__(self):
            self.seen = []
            self.script = [result((call(1, "validate_draft", draft=bad),)),
                           result((call(2, "finish", decision="NEEDS_STAFF", reason="인용을 못 찾았습니다"),))]

        def generate(self, req):
            self.seen.append(req)
            return self.script.pop(0)

    c = Client()
    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, c, log)
    assert d.decision == "NEEDS_STAFF" and log.calls[0].ok          # 검사 도구 자체는 성공, 오류는 결과 안에
    last_results = c.seen[1].messages[-1].tool_results
    assert "QUOTE_NOT_IN_DOC" in last_results[0].content
    assert d.programs and d.programs[0].match_id == "JEJU-LOGI@2026-27"       # 마지막 검사 초안을 남긴다


def test_no_key_gives_empty_needs_staff_draft():
    d = run_notice(DOC_N1, BUNDLE, NullClient(), ToolLog())
    assert d.decision == "NEEDS_STAFF" and d.partial and not d.programs and "NO_KEY" in d.reason


def test_llm_text_only_reply_ends_partial():
    class Client:
        provider = model = "x"

        def generate(self, req):
            return result(text="끝")

    d = run_notice(DOC_N1, BUNDLE, Client(), ToolLog())
    assert d.partial and d.decision == "NEEDS_STAFF"


def test_payload_rejection_is_unavailable_not_crash():
    class Client:
        provider = model = "x"

        def generate(self, req):
            raise LLMUnavailable("REPLAY_MISMATCH", "x")

    d = run_notice(DOC_N1, BUNDLE, Client(), ToolLog())
    assert d.partial and "REPLAY_MISMATCH" in d.reason


def test_finish_with_red_errors_is_refused_then_loop_continues():
    bad = {"programs": [{"action": "UPDATE", "match_id": "JEJU-LOGI@2026-27",
                         "fields": {"apply_start": {"value": "2026-07-23", "quote": "신청기간  : 수 화 2026. 7. 22.( ) ~ 8. 4.( )"}}}]}

    class Client:
        provider = model = "x"

        def __init__(self):
            self.script = [result((call(1, "finish", decision="DRAFT_READY", reason="끝", draft=bad),)),
                           result((call(2, "finish", decision="NEEDS_STAFF", reason="고치지 못함"),))]

        def generate(self, req):
            return self.script.pop(0)

    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, Client(), log)
    assert d.decision == "NEEDS_STAFF" and not log.calls[0].ok


def test_staff_questions_are_carried():
    class Client:
        provider = model = "x"

        def __init__(self):
            self.script = [result((call(1, "ask_staff", field="applicant", question="신청 주체가 농협뿐인가요"),)),
                           result((call(2, "finish", decision="NEEDS_STAFF", reason="질문 있음"),))]

        def generate(self, req):
            return self.script.pop(0)

    d = run_notice(DOC_N1, BUNDLE, Client(), ToolLog())
    assert d.staff_questions == ("신청 주체가 농협뿐인가요",)


def test_prompt_is_korean_and_forbids_inventing():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "인용" in text and "지어내" in text and "금액" in text


def test_golden_json_roundtrip():
    assert NoticeResult.model_validate(json.loads(GOLDEN_DRAFT_N1.model_dump_json())) == GOLDEN_DRAFT_N1


def test_identical_invalid_draft_twice_stops_with_needs_staff():
    bad = {"programs": [{"action": "UPDATE", "match_id": "JEJU-LOGI@2026-27",
                         "fields": {"apply_start": {"value": "2026-07-22", "quote": "원문에 없는 문장"}}}]}
    c = LoopingDraft(bad)
    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, c, log)
    assert d.decision == "NEEDS_STAFF" and d.partial and log.tool_calls == 2 and c.calls == 2
    assert "같은" in d.reason and d.programs


def test_changed_invalid_draft_keeps_going():
    def bad(q):
        return {"programs": [{"action": "UPDATE", "match_id": "JEJU-LOGI@2026-27",
                              "fields": {"apply_start": {"value": "2026-07-22", "quote": q}}}]}

    class Client:
        provider = model = "x"

        def __init__(self):
            self.script = [result((call(1, "validate_draft", draft=bad("없는 문장 하나")),)),
                           result((call(2, "validate_draft", draft=bad("없는 문장 둘")),)),
                           result((call(3, "finish", decision="NEEDS_STAFF", reason="고치지 못함"),))]

        def generate(self, req):
            return self.script.pop(0)

    log = ToolLog()
    d = run_notice(DOC_N1, BUNDLE, Client(), log)
    assert log.tool_calls == 3 and "같은" not in d.reason


class LoopingDraft:
    provider = model = "x"

    def __init__(self, draft):
        self.draft, self.calls = draft, 0

    def generate(self, req):
        self.calls += 1
        return result((call(self.calls, "validate_draft", draft=self.draft),))
