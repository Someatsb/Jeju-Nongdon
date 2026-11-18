"""공고 에이전트 도구 6개와 등록부(Task 18) — round2-C-agent.md §6-1 표."""
import json
import re

import pytest
from notice_fixtures import (
    BUNDLE,
    DOC_N1,
    DOC_N7,
    DRAFT_N1_BAD_QUOTE,
    DRAFT_N1_GOOD,
    DRAFT_WITH_RED,
    DRAFT_WITH_YELLOW,
    LOGI,
    N7_INCOME,
    draft,
    draft_with,
    program,
    tools_for,
)
from pydantic import BaseModel

from app.core.models import Program
from app.data_layer.docs_in import extract
from app.data_layer.supports_index import ProgramIndex
from app.tools.draft_checks import squash
from app.tools.models import ToolLog
from app.tools.notice_tools import MAX_QUESTIONS, NoticeTools
from app.tools.registry import ToolError, ToolRegistry

T1 = tools_for(DOC_N1)
T7 = tools_for(DOC_N7)


# --- 플랜 Task 18 Step 1 ----------------------------------------------------------------------

def test_doc_search_n1_top3():
    anchors = [h.anchor for h in T1.doc_search("지원단가")[:3]]
    assert any("단가" in T1.doc_read(a).text for a in anchors)


def test_find_existing_logistics():
    assert T1.find_existing_program("2026년 제주산 주요 농산물 물류비 지원사업(3차)")[0].program_key == "JEJU-LOGI"


def test_validate_draft_quote_must_exist():
    issues = T1.validate_draft(DRAFT_N1_BAD_QUOTE)
    assert any(i.code == "QUOTE_NOT_IN_DOC" for i in issues)


def test_validate_draft_unit_conversion():
    assert T7.validate_draft(draft_with("3,700만원", income_max_manwon=3700)) == []


def test_finish_refuses_with_red():
    with pytest.raises(ToolError):
        tools_for(DOC_N1).finish("DRAFT_READY", "done", draft=DRAFT_WITH_RED)


# --- doc_search ------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["신청자격", "지원단가", "신청기간"])
def test_doc_search_expected_line_in_top3(query):
    top3 = T1.doc_search(query)[:3]
    assert any(squash(query) in squash(h.passage) for h in top3)
    assert all(re.fullmatch(r"p\d+:L\d+", h.anchor) for h in top3)


def test_doc_search_empty_query_is_correctable_error():
    with pytest.raises(ToolError, match="검색어"):
        T1.doc_search("   ")


def test_doc_search_absent_word_returns_empty():
    assert T1.doc_search("잠수함") == []


def test_doc_search_same_query_same_order_and_k():
    first = T1.doc_search("지원 사업", k=4)
    assert first == T1.doc_search("지원 사업", k=4)
    assert len(first) == 4
    assert [h.score for h in first] == sorted((h.score for h in first), reverse=True)


# --- doc_read --------------------------------------------------------------------------------

def test_doc_read_starts_at_search_hit():
    hit = T1.doc_search("신청기간")[0]
    read = T1.doc_read(hit.anchor, n_lines=3)
    assert read.anchor == hit.anchor
    assert read.text.splitlines()[0] == hit.passage
    assert len(read.text.splitlines()) == 3


def test_doc_read_page_end_points_to_next_page():
    last_line = len(DOC_N1.pages[0].lines)
    read = T1.doc_read(f"p1:L{last_line}", n_lines=20)
    assert read.text == DOC_N1.pages[0].lines[-1]
    assert read.next_anchor == "p2:L1"


def test_doc_read_past_last_page_returns_remaining_lines():
    n = len(DOC_N1.pages[1].lines)
    read = T1.doc_read(f"p2:L{n - 1}", n_lines=20)
    assert read.text.splitlines() == list(DOC_N1.pages[1].lines[-2:])
    assert read.next_anchor is None


@pytest.mark.parametrize("anchor, word", [("3쪽", "앵커"), ("p9:L1", "쪽"), ("p1:L999", "줄")])
def test_doc_read_bad_anchor_is_correctable_error(anchor, word):
    with pytest.raises(ToolError, match=word):
        T1.doc_read(anchor)


def test_doc_read_caps_at_sixty_lines():
    doc = extract("\n".join(f"줄 번호 {i}번" for i in range(1, 101)))
    read = tools_for(doc).doc_read("p1:L1", n_lines=100)
    assert len(read.text.splitlines()) == 60
    assert read.next_anchor == "p1:L61"


# --- find_existing_program -------------------------------------------------------------------

@pytest.mark.parametrize("name, key", [
    ("물류비 지원", "JEJU-LOGI"),
    ("물류비", "JEJU-LOGI"),
    ("소형 농기계 지원 사업", "DO-SMALL-MACHINE"),
    ("농업환경개선 칼슘유황비료 지원사업", "DO-CALCIUM-SULFUR"),
])
def test_find_existing_program_normalizes_spacing_brackets_round(name, key):
    found = T1.find_existing_program(name)
    assert found[0].program_key == key
    assert found[0].id.startswith(key) and found[0].edition and found[0].status
    assert 0 < found[0].score <= 1


def test_find_existing_program_unrelated_is_empty():
    assert T1.find_existing_program("농산물 산지유통센터 광학 선별기 구매 입찰") == []


def test_find_existing_program_tie_prefers_latest_edition():
    rows = tuple(Program(id=f"X-ROW@{e}", program_key="X-ROW", edition=e, status="confirmed", name="밭작물 관수시설 자재")
                 for e in ("2025", "2026", "2024"))
    tools = NoticeTools(DOC_N1, ProgramIndex(programs=rows), ToolLog())
    assert [m.edition for m in tools.find_existing_program("관수시설 자재 지원")] == ["2026", "2025", "2024"]
    assert tools.find_existing_program("관수시설 자재", edition="2025")[0].edition == "2025"


def test_bundle_stand_in_reads_identity_columns():
    logi = next(p for p in BUNDLE.programs if p.id == LOGI)
    assert (logi.program_key, logi.applicant, logi.status, logi.apply_cycle) == ("JEJU-LOGI", "농협경유", "prior_year_reference", "자동")
    assert len(BUNDLE.programs) == 42


# --- validate_draft / finish -----------------------------------------------------------------

def test_validate_good_n1_draft_is_clean():
    assert T1.validate_draft(DRAFT_N1_GOOD) == []


def test_finish_allows_needs_staff_with_red_and_ready_with_yellow():
    tools = tools_for(DOC_N7)
    assert tools.finish("NEEDS_STAFF", "직원 확인 필요", draft=draft(program(income_max_manwon=(37000000, N7_INCOME)))).ok
    assert tools.validate_draft(DRAFT_WITH_YELLOW) and all(i.level == "YELLOW" for i in tools.validate_draft(DRAFT_WITH_YELLOW))
    assert tools.finish("DRAFT_READY", "초안 완성", draft=DRAFT_WITH_YELLOW).ok


def test_finish_ready_uses_last_validated_draft():
    tools = tools_for(DOC_N1)
    with pytest.raises(ToolError, match="초안"):
        tools.finish("DRAFT_READY", "done")
    tools.validate_draft(DRAFT_N1_GOOD)
    result = tools.finish("DRAFT_READY", "done")
    assert (result.ok, result.decision) == (True, "DRAFT_READY")


def test_finish_ready_refuses_empty_draft_and_reports_red_count():
    tools = tools_for(DOC_N1)
    with pytest.raises(ToolError, match="사업"):
        tools.finish("DRAFT_READY", "done", draft=draft())
    with pytest.raises(ToolError, match="1개"):
        tools.finish("DRAFT_READY", "done", draft=DRAFT_WITH_RED)


def test_finish_not_relevant_needs_no_draft():
    assert tools_for(DOC_N1).finish("NOT_RELEVANT", "입찰 공고").decision == "NOT_RELEVANT"


# --- ask_staff -------------------------------------------------------------------------------

def test_ask_staff_queues_in_log_dedupes_and_caps():
    log = ToolLog()
    tools = NoticeTools(DOC_N1, BUNDLE, log)
    first = tools.ask_staff("needs_selfpay_fund", "자조금 미가입 농가 차등이 올해도 있나요?")
    assert first.queued and log.questions[0].field == "needs_selfpay_fund"
    again = tools.ask_staff("needs_selfpay_fund", "자조금 미가입 농가 차등이 올해도  있나요?")
    assert not again.queued and len(log.questions) == 1
    for i in range(MAX_QUESTIONS - 1):
        assert tools.ask_staff(f"field_{'abcd'[i]}", f"질문 {'가나다라'[i]}").queued
    with pytest.raises(ToolError, match="다섯"):
        tools.ask_staff("notes", "하나 더")
    assert len(log.questions) == MAX_QUESTIONS


def test_ask_staff_refuses_pii():
    tools = tools_for(DOC_N1)
    with pytest.raises(ToolError, match="개인정보"):
        tools.ask_staff("phone", "담당 010-1234-5678로 물어볼까요?")
    assert tools.log.questions == []


# --- 등록부 ----------------------------------------------------------------------------------

def _descriptions(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "description" and isinstance(v, str):
                yield v
            yield from _descriptions(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _descriptions(v)


def test_registry_schemas_list_six_tools_digit_free():
    schemas = T1.registry().schemas()
    assert [s["name"] for s in schemas] == ["doc_search", "doc_read", "find_existing_program",
                                            "validate_draft", "ask_staff", "finish"]
    for s in schemas:
        assert s["description"] and s["input_schema"]["type"] == "object"
    texts = list(_descriptions(schemas))
    assert len(texts) > 6 and not [t for t in texts if re.search(r"[0-9０-９]", t)]


def test_dispatch_records_success_in_log():
    log = ToolLog()
    tools = NoticeTools(DOC_N1, BUNDLE, log)
    rec = tools.registry().dispatch("doc_search", {"query": "지원단가", "k": 2}, log)
    assert rec.ok and len(rec.result["hits"]) == 2 and rec.error is None
    assert log.tool_calls == 1 and log.calls[0] == rec
    assert json.loads(rec.content())["hits"][0]["anchor"] == rec.result["hits"][0]["anchor"]


@pytest.mark.parametrize("name, args, word", [
    ("doc_search", {}, "query"),
    ("doc_read", {"anchor": "p1:L1", "n_lines": 500}, "n_lines"),
    ("no_such_tool", {}, "모르는 도구"),
    ("finish", {"decision": "DRAFT_READY", "reason": "done", "draft": DRAFT_WITH_RED.model_dump(mode="json")}, "빨간"),
])
def test_dispatch_turns_bad_calls_into_korean_error_results(name, args, word):
    log = ToolLog()
    rec = NoticeTools(DOC_N1, BUNDLE, log).registry().dispatch(name, args, log)
    assert not rec.ok and rec.result is None and word in rec.error
    assert json.loads(rec.content()) == {"error": rec.error}
    assert log.tool_calls == 1


class _Out(BaseModel):
    y: int


def _dispatch_one(fn):
    reg = ToolRegistry()
    reg.register("t", _In, _Out, fn)
    log = ToolLog()
    return reg.dispatch("t", {"x": 1}, log), log


def test_dispatch_catches_unexpected_exceptions():
    def boom(_a):
        raise RuntimeError("secret internals")
    rec, log = _dispatch_one(boom)
    assert not rec.ok and "도구 내부 오류" in rec.error and log.tool_calls == 1


def test_dispatch_separates_output_format_errors_from_argument_errors():
    rec, _ = _dispatch_one(lambda a: {"y": "not-int"})
    assert not rec.ok and "도구 결과 형식 오류" in rec.error and "인자 오류" not in rec.error
    reg = ToolRegistry()
    reg.register("t", _In, _Out, lambda a: {"y": 1})
    bad = reg.dispatch("t", {"x": "abc"}, ToolLog())
    assert "인자 오류" in bad.error and "결과 형식" not in bad.error


def test_dispatch_validate_draft_round_trips_json():
    log = ToolLog()
    rec = NoticeTools(DOC_N1, BUNDLE, log).registry().dispatch(
        "validate_draft", {"draft": DRAFT_N1_BAD_QUOTE.model_dump(mode="json")}, log)
    assert rec.ok and rec.result["errors"][0]["code"] == "QUOTE_NOT_IN_DOC"


class _In(BaseModel):
    """설명 둘."""
    x: int


class _BadIn(BaseModel):
    """설명에 숫자 3이 있음."""
    x: int


def test_register_rejects_duplicates_and_digit_descriptions():
    reg = ToolRegistry()
    reg.register("t", _In, _In, lambda a: a)
    with pytest.raises(ValueError, match="이미"):
        reg.register("t", _In, _In, lambda a: a)
    with pytest.raises(ValueError, match="숫자"):
        reg.register("u", _BadIn, _In, lambda a: a)
