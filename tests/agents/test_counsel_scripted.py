"""상담 에이전트 설명 단계(Task 28): 구획별 서술 + 검수, 예산, 키 없음."""
import logging
import re

import pytest
from counsel_fixtures import (BAD_SUPPORT, CTX_P4, CTX_T1, FS_P4, FS_T1, ClockedClient, FakeClock, JudgeRouter,
                              good_section, recording)

from app.agents.counsel import PROMPT_VER, Narrative, build_request, narrate
from app.agents.llm.base import GenResult, LLMUnavailable
from app.agents.llm.null import NullClient
from app.agents.llm.payload import build_payload
from app.agents.llm.scripted import ScriptedClient
from app.agents.reviewer import MemoryReviewLog, build_feedback
from app.agents.rules import check_rules
from app.agents.style import check_style, first_stop_label

KINDS_P4 = ("support", "insurance", "action")
PASS_V = '{"verdict": "PASS", "reason_code": null}'
DIGITS = re.compile(r"[0-9０-９①-⑳]")
DIGIT_ANY = DIGITS


def rec_good():
    return recording(CTX_P4, {k: [good_section(k)] for k in KINDS_P4})


def run(llm, **kw):
    log = MemoryReviewLog()
    return narrate(FS_P4, llm, log, **kw), log


# --- 브리프 시험 -----------------------------------------------------------------------------

def test_scripted_narrate_p4_passes_all():
    n, _ = run(ScriptedClient(rec_good()))
    assert set(n.sections) == set(KINDS_P4)
    assert all(o.source == "ai_pass" for o in n.sections.values()) and n.mode == "ai"


def test_only_failed_section_regenerated():
    ids = frozenset(i.program_id for i in CTX_P4.items)
    from app.agents.rules import parse_section
    bad, _ = parse_section(BAD_SUPPORT)
    fb = build_feedback("support", [(h.rule, h.sid) for h in sorted([*check_rules(bad, CTX_P4, ids), *check_style(bad, first_stop_label(CTX_P4))], key=lambda h: h.sid)], style=True)
    rec = recording(CTX_P4, {"support": [BAD_SUPPORT, good_section("support")],
                             "insurance": [good_section("insurance")], "action": [good_section("action")]},
                    feedback_for={"support": [fb]})
    n, log = run(ScriptedClient(rec))
    assert n.sections["support"].attempts == 2 and n.sections["insurance"].attempts == 1
    assert n.sections["support"].source == "ai_pass" and n.mode == "ai"
    assert {e["attempt"] for e in log.entries if e["section"] == "support"} >= {1, 2}


def test_no_key_all_template():
    n, _ = run(NullClient())
    assert n.mode == "template" and all(o.source == "template" for o in n.sections.values())
    assert set(n.sections) == set(KINDS_P4)


# --- 예산 ------------------------------------------------------------------------------------

def test_budget_exceeded_after_first_section_rest_template():
    clock = FakeClock()
    client = ClockedClient(JudgeRouter(ScriptedClient(rec_good())), clock, after_calls=2)  # 구획 하나: 생성 + 판정
    n, _ = run(client, clock=clock)
    assert n.sections["support"].source == "ai_pass"
    assert n.sections["insurance"].source == "template" and n.sections["action"].source == "template"
    assert n.mode == "mixed" and client.calls == 2  # 예산이 끝난 뒤에는 클라이언트를 더 부르지 않는다


def test_budget_cut_mid_regeneration_makes_no_further_calls():
    ids = frozenset(i.program_id for i in CTX_P4.items)
    from app.agents.rules import parse_section
    bad, _ = parse_section(BAD_SUPPORT)
    fb = build_feedback("support", [(h.rule, h.sid) for h in sorted([*check_rules(bad, CTX_P4, ids), *check_style(bad, first_stop_label(CTX_P4))], key=lambda h: h.sid)], style=True)
    rec = recording(CTX_P4, {"support": [BAD_SUPPORT, good_section("support")]}, feedback_for={"support": [fb]})
    clock = FakeClock()
    client = ClockedClient(JudgeRouter(ScriptedClient(rec)), clock, after_calls=1)  # 첫 생성 직후 예산 끝
    n, log = run(client, clock=clock)
    assert client.calls == 1 and n.mode == "template"
    assert all(o.source == "template" for o in n.sections.values())
    assert any(e["verdict"] == "REGEN_UNAVAILABLE" for e in log.entries)


def test_budget_budget_s_is_injectable_and_default_45():
    import inspect
    assert inspect.signature(narrate).parameters["budget_s"].default == 45


# --- 입력·출력 모양 ----------------------------------------------------------------------------

def test_empty_sheet_t1_narrates_exactly_one_empty_section():
    assert CTX_T1.empty_sheet
    rec = recording(CTX_T1, {"empty": [good_section("empty", CTX_T1)]})
    client = JudgeRouter(ScriptedClient(rec))
    n = narrate(FS_T1, client, MemoryReviewLog())
    assert set(n.sections) == {"empty"} and n.mode == "ai"
    assert sum(r.purpose == "narrate" for r in client.requests) == 1
    assert list(n.texts()) == ["empty"]


def test_empty_sheet_no_key_is_one_template_section():
    n = narrate(FS_T1, NullClient(), MemoryReviewLog())
    assert set(n.sections) == {"empty"} and n.mode == "template"


def test_judge_fail_regenerates_only_that_section_with_ordinal_feedback():
    reject = '{"verdict": "REJECT", "reason_code": "OVERPROMISE", "문장": "첫째"}'
    fb = build_feedback("support", [("OVERPROMISE", 1)], style=True)
    rec = recording(CTX_P4, {"support": [good_section("support"), good_section("support")],
                             "insurance": [good_section("insurance")], "action": [good_section("action")]},
                    feedback_for={"support": [fb]})
    client = JudgeRouter(ScriptedClient(rec), verdicts={"support": [reject, PASS_V]})
    n, log = run(client)
    assert n.sections["support"].attempts == 2 and n.sections["insurance"].attempts == 1
    assert n.sections["support"].source == "ai_pass" and n.mode == "ai"
    regen = [r for r in client.requests if r.purpose == "narrate" and "첫째 문장" in r.messages[0].text]
    assert len(regen) == 1
    build_payload(regen[0])  # 거름망 통과
    assert not DIGITS.search(regen[0].messages[0].text)
    assert any(e["section"] == "support" and e["judge"].get("verdict") == "REJECT" for e in log.entries)


def test_counsel_tools_without_bundle_give_korean_errors_not_attribute_errors():
    from app.tools.counsel_tools import CounselTools
    from app.tools.models import ToolLog
    reg = CounselTools(None).registry()
    for name, args in (("get_program_detail", {"id": "x"}), ("get_product_detail", {"id": "x"})):
        rec = reg.dispatch(name, args, ToolLog())
        assert not rec.ok and "표 묶음" in rec.error


def test_requests_pass_the_payload_filter_and_carry_no_names_or_digits():
    for kind in KINDS_P4:
        req = build_request(kind, CTX_P4)
        build_payload(req)  # 거름망 통과
        body = req.messages[0].text
        assert not DIGITS.search(body) and not DIGITS.search(req.system)
        assert all(i.official_name not in body for i in CTX_P4.items)
        assert "{P:" in req.system


def test_regen_request_carries_feedback_without_digits():
    ids = frozenset(i.program_id for i in CTX_P4.items)
    from app.agents.rules import parse_section
    bad, _ = parse_section(BAD_SUPPORT)
    fb = build_feedback("support", [(h.rule, h.sid) for h in sorted([*check_rules(bad, CTX_P4, ids), *check_style(bad, first_stop_label(CTX_P4))], key=lambda h: h.sid)], style=True)
    req = build_request("support", CTX_P4, fb)
    build_payload(req)
    assert fb.lines[0] in req.messages[0].text


def test_prompt_has_no_digits():
    from app.agents.counsel import PROMPT_PATH
    assert PROMPT_VER == "narrate-v3" and not DIGITS.search(PROMPT_PATH.read_text(encoding="utf-8"))


def test_texts_resolves_placeholders_and_matches_render_shape():
    n, _ = run(ScriptedClient(rec_good()))
    texts = n.texts()
    assert set(texts) == set(KINDS_P4)
    for sentences in texts.values():
        assert sentences and all(isinstance(s, str) and "{P:" not in s and not DIGITS.search(s) for s in sentences)
    assert any(i.official_name in s for i in CTX_P4.items for s in texts[i.section])


def test_texts_drops_digit_sentences_and_logs(caplog):
    from app.agents.rules import Section, Sentence
    from app.agents.reviewer import ReviewOutcome
    sec = Section(section="support", sentences=(Sentence(sid=1, text="문장 하나입니다.", cites=("M:x",)),
                                                Sentence(sid=2, text="삼 년 전부터 7번째입니다.", cites=("M:x",)),
                                                Sentence(sid=3, text="{P:nope} 건입니다.", cites=("M:x",))))
    n = Narrative(sections={"support": ReviewOutcome(final=sec, source="ai_pass", attempts=1)}, mode="ai", names={})
    with caplog.at_level(logging.WARNING, logger="app.agents.counsel"):
        assert n.texts() == {"support": ["문장 하나입니다."]}
    assert len(caplog.records) == 2


def test_template_section_failures_are_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="app.agents.counsel"):
        run(NullClient())
    assert any("템플릿" in r.getMessage() for r in caplog.records)


# --- 도구 ------------------------------------------------------------------------------------

def test_aliases_follow_pipeline_and_names_resolve():
    ids = [i.fact_id for i in CTX_P4.items]
    assert len(ids) == len(set(ids)) and {i.section for i in CTX_P4.items} == set(KINDS_P4)
    assert CTX_P4.aliases["jeju_farmer_allow"].startswith("JEJU-FARMER-ALLOW")
    n, _ = run(NullClient())
    assert set(n.names) == {i.program_id for i in CTX_P4.items}


def test_texts_render_in_sheet_without_digits():
    from app.config import load_config
    from app.core.sheet import build_sheet
    from app.ui.render import render_sheet
    from counsel_fixtures import BUNDLE
    from conftest import AS_OF
    n, _ = run(ScriptedClient(rec_good()))
    texts = n.texts()
    sheet = build_sheet(FS_P4, BUNDLE, AS_OF)
    html = render_sheet(sheet, FS_P4, texts, load_config([]))
    from bs4 import BeautifulSoup
    assert not DIGIT_ANY.search(" ".join(s for sentences in texts.values() for s in sentences))      # 글에는 숫자가 없다
    # 2026-11-18: 결과가 있는 종이에는 AI 문장이 없다(결론 상자·뒷면이 없다). 문장은 화면 맨 위 띠에만 실린다
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.select("p.narr, .sh, .back")
    page = soup.get_text(" ")
    assert not any(s in page for sentences in texts.values() for s in sentences)


def test_pipeline_aliases_fit_rule_formats_and_review_fixture_contexts():
    """Task 20 별칭·근거 id가 규칙(R5·R6)의 형식에 맞는다. 검수 픽스처 ctx_*.json은 규칙 시험용 손 작성 장면이라
    별칭 낱말이 달라도(예: jeju_farmer_allowance) 같은 형식 규칙을 지킨다."""
    from counsel_fixtures import CTX_T1
    from review_fixtures import CONTEXTS

    from app.agents.rules import CITE, PLACEHOLDER
    for ctx in (CTX_P4, CTX_T1, *CONTEXTS.values()):
        for i in ctx.items:
            assert re.fullmatch(CITE, i.fact_id) and re.fullmatch(PLACEHOLDER.replace(r"\{P:(", "(").replace(r")\}", ")"), i.program_id)
