"""검수 루프(Task 19): 오염 주입 → 재생성 통과, 전부 실패 → 템플릿, 템플릿도 규칙 통과, 지시문 숫자 0개, 판정 생략."""
import json
import re
from datetime import date

import pytest
from review_fixtures import BAD, BY_ID, CONTEXTS, sheet_ids

from app.agents.fallback_ko import KINDS, template_for
from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable
from app.agents.llm.payload import build_payload
from app.agents.reviewer import (R7_MESSAGES, FileReviewLog, Feedback, MemoryReviewLog, build_feedback,
                                 parse_verdict, review_section)
from app.agents.rules import RULE_MESSAGES, RULES_VERSION, check_rules

DIGITS = re.compile(r"[0-9０-９①-⑳]")
CTX_P4, IDS_P4 = CONTEXTS["ctx_P4"], sheet_ids(CONTEXTS["ctx_P4"])
CTX_P3, IDS_P3 = CONTEXTS["ctx_P3"], sheet_ids(CONTEXTS["ctx_P3"])
GOOD_SECOND = BY_ID["G01"].section
BAD_FIRST = next(c.section for c in BAD if c.context == "ctx_P4" and c.section.section == "support"
                 and check_rules(c.section, CTX_P4, IDS_P4))
GOOD_P3 = BY_ID["G21"].section  # insurance, ctx_P3


def scripted_regen(sections):
    queue, seen = list(sections), []

    def regen(fb: Feedback):
        seen.append(fb)
        return queue.pop(0)
    regen.seen = seen
    return regen


class FakeJudge:
    provider, model = "fake", "fake-judge"

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def generate(self, req: GenRequest) -> GenResult:
        self.requests.append(req)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return GenResult(text=r, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0,
                         provider=self.provider, model=self.model)


PASS = '{"verdict": "PASS", "reason_code": null}'
REJECT = '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": "첫째"}'


def test_inject_then_pass():
    mem_log = MemoryReviewLog()
    out = review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=scripted_regen([GOOD_SECOND]), log=mem_log)
    assert out.source == "ai_pass" and out.attempts == 2 and mem_log.entries[0]["verdict"] == "REJECT"
    assert out.final == GOOD_SECOND and mem_log.entries[1]["verdict"] == "PASS"


def test_all_fail_falls_back_to_template():
    mem_log = MemoryReviewLog()
    out = review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=lambda fb: BAD_FIRST, log=mem_log)
    assert out.source == "template" and out.attempts == 3
    assert out.final == template_for("support", CTX_P4)
    assert mem_log.entries[-1]["verdict"] == "TEMPLATE"


def test_templates_pass_rules():
    for ctx in CONTEXTS.values():
        ids = sheet_ids(ctx)
        for k in KINDS:
            if any(i.section == k for i in ctx.items):
                assert check_rules(template_for(k, ctx), ctx, ids) == [], (k, ctx.items[0].program_id)
    with pytest.raises(ValueError):
        template_for("insurance", CONTEXTS["ctx_T1"])


def test_every_context_kind_has_template():
    for ctx in CONTEXTS.values():
        for kind in {i.section for i in ctx.items}:
            assert template_for(kind, ctx).section == kind


# 규칙 단계에서 잡히지 않는 나쁜 예(R7 몫이거나 알려진 미탐). 목록이 달라지면 이 테스트가 깨진다.
NO_RULE_HIT = ["B27", "B31", "B36", "B37", "B39", "B40"]


def test_known_rule_misses_are_pinned():
    missed = [c.id for c in BAD if not check_rules(c.section, CONTEXTS[c.context], sheet_ids(CONTEXTS[c.context]))]
    assert missed == NO_RULE_HIT


@pytest.mark.parametrize("case", [c for c in BAD if c.id not in NO_RULE_HIT], ids=lambda c: c.id)
def test_feedback_has_no_digits(case):
    ctx = CONTEXTS[case.context]
    hits = check_rules(case.section, ctx, sheet_ids(ctx))
    assert hits
    fb = build_feedback(case.section.section, [(h.rule, h.sid) for h in hits])
    assert not DIGITS.search(fb.text) and fb.lines
    assert all(h.span not in fb.text for h in hits if len(h.span) > 2 and DIGITS.search(h.span))


def test_feedback_uses_korean_ordinal_and_codes():
    fb = build_feedback("support", [("NUM_DIGIT", 1), ("CERTAINTY", 2), ("SCHEMA", 0), ("NUM_DIGIT", 1)])
    assert [ln.split(":")[0] for ln in fb.lines] == ["구획 전체", "첫째 문장", "둘째 문장"]
    assert fb.codes == ("NUM_DIGIT", "CERTAINTY", "SCHEMA")


def test_regen_gets_feedback_only():
    regen = scripted_regen([GOOD_SECOND])
    review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=regen, log=MemoryReviewLog())
    assert len(regen.seen) == 1 and isinstance(regen.seen[0], Feedback) and not DIGITS.search(regen.seen[0].text)


def test_regen_unavailable_goes_to_template():
    def boom(fb):
        raise LLMUnavailable("TIMEOUT")
    out = review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=boom, log=MemoryReviewLog())
    assert out.source == "template" and out.attempts == 1


def test_log_has_codes_not_text():
    log = MemoryReviewLog()
    review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=scripted_regen([GOOD_SECOND]), log=log)
    blob = json.dumps(log.entries, ensure_ascii=False)
    for s in BAD_FIRST.sentences + GOOD_SECOND.sentences:
        assert s.text not in blob
    e = log.entries[0]
    assert e["rules_ver"] == RULES_VERSION and e["checks"] and e["judge"]["skipped"] is True
    assert {"rule", "sid"} == set(e["checks"][0])


def test_file_log_date_from_as_of(tmp_path):
    log = FileReviewLog(date(2026, 11, 12), tmp_path / "review")
    review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=scripted_regen([GOOD_SECOND]), log=log)
    lines = (tmp_path / "review" / "2026-11-12.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["verdict"] == "REJECT"


# --- 판정(R7) ---------------------------------------------------------------------------------

def test_judge_not_called_when_rules_fail_and_called_after_pass():
    judge = FakeJudge([PASS])
    out = review_section(BAD_FIRST, CTX_P4, IDS_P4, judge, regen=scripted_regen([GOOD_SECOND]), log=MemoryReviewLog())
    assert out.source == "ai_pass" and len(judge.requests) == 1
    req = judge.requests[0]
    assert req.purpose == "judge" and req.section == "support"
    build_payload(req)  # 전송 거름망 통과(숫자 없음)


def test_judge_reject_triggers_regen_with_digit_free_feedback():
    judge = FakeJudge([REJECT, PASS])
    regen = scripted_regen([GOOD_P3])
    log = MemoryReviewLog()
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, judge, regen=regen, log=log)
    assert out.source == "ai_pass" and out.attempts == 2
    assert regen.seen[0].codes == ("OVERPROMISE",) and "첫째 문장" in regen.seen[0].text
    assert not DIGITS.search(regen.seen[0].text)
    assert log.entries[0]["judge"]["reason_code"] == "OVERPROMISE" and log.entries[0]["verdict"] == "REJECT"


@pytest.mark.parametrize("reply", ["아무 말", "{}", '{"verdict": "MAYBE", "reason_code": null}',
                                   '{"verdict": "REJECT", "reason_code": "NOPE"}',
                                   '{"verdict": "PASS", "reason_code": "UNSUPPORTED"}',
                                   '{"verdict": "PASS", "reason_code": null, "extra": 1}', "[]", None])
def test_malformed_verdict_is_skipped_not_reject(reply):
    assert parse_verdict(reply) is None
    log = MemoryReviewLog()
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, FakeJudge([reply]), regen=scripted_regen([]), log=log)
    assert out.source == "ai_pass" and out.attempts == 1
    assert log.entries[0]["judge"]["reason"] == "판정 생략" and log.entries[0]["verdict"] == "PASS"


def test_judge_unavailable_logs_skip_and_continues_rules_only():
    log = MemoryReviewLog()
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, FakeJudge([LLMUnavailable("NO_KEY")]),
                         regen=scripted_regen([]), log=log)
    assert out.source == "ai_pass" and log.entries[0]["judge"] == {"skipped": True, "reason": "판정 생략",
                                                                  "unavailable": "NO_KEY"}


def test_judge_rejects_twice_then_template():
    judge = FakeJudge([REJECT, REJECT, REJECT])
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, judge, regen=lambda fb: GOOD_P3, log=MemoryReviewLog())
    assert out.source == "template" and out.attempts == 3
    assert check_rules(out.final, CTX_P3, IDS_P3) == []


def test_judge_prompt_is_digit_free_and_short():
    from app.agents.reviewer import _PROMPT_PATH
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    assert not DIGITS.search(text) and len(text.splitlines()) <= 40


# --- 수정 1차 ------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    '{"verdict": "REJECT", "reason_code": ["OVERPROMISE"], "문장": "첫째"}',
    '{"verdict": "REJECT", "reason_code": {"a": 1}, "문장": "첫째"}',
    '{"verdict": "REJECT", "reason_code": 5, "문장": "첫째"}',
    '{"verdict": "REJECT", "reason_code": null, "문장": "첫째"}',
    '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": ["첫째"]}',
    '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": {"x": "첫째"}}',
    '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": 1}',
    '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": [["첫째"]]}',
    '{"verdict": ["PASS"], "reason_code": null}',
    '{"verdict": {"v": "PASS"}, "reason_code": null}',
    '{"verdict": null, "reason_code": null}',
    '{"verdict": 1, "reason_code": null}',
    '{"verdict": "PASS", "reason_code": [], "문장": []}',
])
def test_malformed_shapes_never_raise(reply):
    assert parse_verdict(reply) is None
    log = MemoryReviewLog()
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, FakeJudge([reply]), regen=scripted_regen([]), log=log)
    assert out.source == "ai_pass" and out.attempts == 1
    assert log.entries[0]["judge"]["malformed"] is True and log.entries[0]["judge"]["reason"] == "판정 생략"


def test_null_ordinal_with_reject_is_whole_section():
    reply = '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": null}'
    assert parse_verdict(reply) == ("REJECT", "OVERPROMISE", 0)


def test_ordinal_beyond_sentence_count_is_malformed():
    n = len(GOOD_P3.sentences)
    assert n < 5
    reply = '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": "다섯째"}'
    assert parse_verdict(reply, n) is None and parse_verdict(reply) == ("REJECT", "OVERPROMISE", 5)
    first = '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": "첫째"}'
    assert parse_verdict(first, 1) == ("REJECT", "OVERPROMISE", 1)
    log = MemoryReviewLog()
    out = review_section(GOOD_P3, CTX_P3, IDS_P3, FakeJudge([reply]), regen=scripted_regen([]), log=log)
    assert out.source == "ai_pass" and log.entries[0]["judge"]["malformed"] is True


def _all_entries_have_shape(entries):
    for e in entries:
        assert {"checks", "judge", "verdict"} <= set(e), e


def test_log_entry_shape_is_uniform():
    log = MemoryReviewLog()
    review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=lambda fb: BAD_FIRST, log=log)
    assert log.entries[-1]["verdict"] == "TEMPLATE" and log.entries[-1]["checks"] == []
    assert log.entries[-1]["judge"] is None
    _all_entries_have_shape(log.entries)

    def boom(fb):
        raise LLMUnavailable("TIMEOUT")
    log2 = MemoryReviewLog()
    review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=boom, log=log2)
    assert len(log2.entries) == 3 and log2.entries[1]["verdict"] == "REGEN_UNAVAILABLE"
    _all_entries_have_shape(log2.entries)


@pytest.mark.parametrize("max_regen,attempts", [(0, 1), (1, 2)])
def test_max_regen_bounds_attempts(max_regen, attempts):
    calls = []

    def regen(fb):
        calls.append(fb)
        return BAD_FIRST
    out = review_section(BAD_FIRST, CTX_P4, IDS_P4, None, regen=regen, log=MemoryReviewLog(), max_regen=max_regen)
    assert out.source == "template" and out.attempts == attempts and len(calls) == max_regen
    assert out.final == template_for("support", CTX_P4)


def test_max_regen_zero_still_passes_good_candidate():
    out = review_section(GOOD_SECOND, CTX_P4, IDS_P4, None, regen=scripted_regen([]), log=MemoryReviewLog(), max_regen=0)
    assert out.source == "ai_pass" and out.attempts == 1


def test_every_message_forwarded_to_llm_is_digit_free():
    msgs = {**RULE_MESSAGES, **R7_MESSAGES}
    assert "UNSUPPORTED" in msgs and "NUM_DIGIT" in msgs and "BAD_CITE" in msgs
    for code, msg in msgs.items():
        assert not DIGITS.search(msg), code
        assert not DIGITS.search(build_feedback("support", [(code, 1)]).text), code
