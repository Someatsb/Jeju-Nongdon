"""공고 이름표(tags): 에이전트가 중요한 조건을 3~4개 뽑고, 근거 문장을 원문과 글자 그대로 대조한다(설계서 B-2, B-3)."""
import json

from notice_fixtures import BUNDLE, DOC_N1, N1_APPLICANT, N1_CROPS, N1_TAGS, draft, program
from notice_loop_fixtures import GOLDEN_DRAFT_N1, call, result

from app.agents.notice import PROMPT_PATH, run_notice
from app.tools.draft_checks import TAG_MAX_LABEL, run, squash, strip_bad_tags, tag_problem
from app.tools.models import DraftTag, ToolLog
from app.tools.notice_tools import NoticeTools
from app.ui.report_notice import render_notice_report

SQ = squash(DOC_N1.text)


def issues_for(*tags: tuple[str, str]):
    return [(i.code, i.field, i.level) for i in run(draft(program(tags=tags)), DOC_N1, BUNDLE)]


def test_good_tags_have_no_issue():
    assert issues_for(*N1_TAGS) == []


def test_tag_problems_are_red_with_the_tag_position():
    got = issues_for(("월동무·양배추", N1_CROPS), ("", N1_CROPS), ("가" * (TAG_MAX_LABEL + 1), N1_CROPS),
                     ("원문에 없는 말", "이 문장은 공고에 없습니다"), ("근거 없음", ""), ("연락 받기", "문의 010-1234-5678"))
    assert got == [("TAG_EMPTY", "tags.1", "RED"), ("TAG_TOO_LONG", "tags.2", "RED"),
                   ("TAG_QUOTE_NOT_IN_DOC", "tags.3", "RED"), ("TAG_QUOTE_MISSING", "tags.4", "RED"),
                   ("PII_IN_DRAFT", "tags.5", "RED")]


def test_quote_is_matched_like_field_quotes_ignoring_spaces():
    assert tag_problem(DraftTag(label="농협이 신청", quote=N1_APPLICANT), SQ) is None
    assert tag_problem(DraftTag(label="농협이 신청", quote="지역농협및영농조합법인"), SQ) is None      # 공백만 다름
    assert tag_problem(DraftTag(label="농협이 신청", quote="지역농협 또는 영농조합법인"), SQ)[0] == "TAG_QUOTE_NOT_IN_DOC"


def test_label_with_personal_info_is_pii():
    assert tag_problem(DraftTag(label="홍길동 010-1234-5678", quote=N1_CROPS), SQ)[0] == "PII_IN_DRAFT"
    assert tag_problem(DraftTag(label="a@b.com", quote=N1_CROPS), SQ)[0] == "PII_IN_DRAFT"


def test_validate_draft_tool_returns_tag_errors_to_the_model():
    tools = NoticeTools(DOC_N1, BUNDLE, ToolLog())
    errors = tools.validate_draft(draft(program(tags=(("지어낸 조건", "지어낸 문장입니다"),))))
    assert [(e.code, e.field) for e in errors] == [("TAG_QUOTE_NOT_IN_DOC", "tags.0")]


def test_strip_bad_tags_keeps_only_matching_ones():
    d = draft(program(tags=(*N1_TAGS[:2], ("지어낸 조건", "지어낸 문장입니다"))))
    kept, dropped = strip_bad_tags(d, DOC_N1)
    assert [t.label for t in kept.programs[0].tags] == [t[0] for t in N1_TAGS[:2]] and dropped == ("지어낸 조건",)
    same, none = strip_bad_tags(draft(program(tags=N1_TAGS)), DOC_N1)
    assert none == () and len(same.programs[0].tags) == 4


class Script:
    provider = model = "x"

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def generate(self, req):
        self.seen.append(req)
        return self.steps.pop(0)


def test_loop_returns_tag_errors_and_drops_tags_that_never_match():
    bad = draft(program(tags=(*N1_TAGS[:3], ("지어낸 조건", "지어낸 문장입니다")))).model_dump(mode="json")
    client = Script(result((call(1, "validate_draft", draft=bad),)),
                    result((call(2, "finish", decision="NEEDS_STAFF", reason="이름표 근거를 못 맞췄습니다"),)))
    res = run_notice(DOC_N1, BUNDLE, client, ToolLog())
    assert "TAG_QUOTE_NOT_IN_DOC" in client.seen[1].messages[-1].tool_results[0].content      # 모델이 고치게 돌려줌
    assert res.dropped_tags == ("지어낸 조건",)
    assert [t.label for t in res.programs[0].tags] == [t[0] for t in N1_TAGS[:3]]


def test_finish_ready_is_refused_while_a_tag_is_wrong():
    bad = draft(program(tags=(("지어낸 조건", "지어낸 문장입니다"),))).model_dump(mode="json")
    log = ToolLog()
    client = Script(result((call(1, "finish", decision="DRAFT_READY", reason="끝", draft=bad),)),
                    result((call(2, "finish", decision="NEEDS_STAFF", reason="고치지 못함"),)))
    res = run_notice(DOC_N1, BUNDLE, client, log)
    assert not log.calls[0].ok and "TAG_QUOTE_NOT_IN_DOC" in log.calls[0].error and res.decision == "NEEDS_STAFF"


def test_golden_draft_has_four_verified_tags():
    tags = GOLDEN_DRAFT_N1.programs[0].tags
    assert len(tags) == 4 and all(tag_problem(t, SQ) is None for t in tags) and GOLDEN_DRAFT_N1.dropped_tags == ()


def test_prompt_asks_for_three_or_four_easy_tags_with_quotes():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "tags" in text and "3~4개" in text and "12자 안팎" in text and "쉬운 말" in text and "원문" in text
    assert PROMPT_PATH.name == "notice-v4.txt"


def test_tag_fields_are_in_the_tool_schema_and_registry_still_accepts_them():
    schemas = {s["name"]: s for s in NoticeTools(DOC_N1, BUNDLE, ToolLog()).registry().schemas()}   # 설명에 숫자가 있으면 등록이 실패한다
    text = json.dumps(schemas["validate_draft"]["input_schema"], ensure_ascii=False)
    assert '"tags"' in text and '"DraftTag"' in text and '"label"' in text and '"quote"' in text


def test_report_shows_tags_with_marks_and_quotes():
    html = render_notice_report(GOLDEN_DRAFT_N1, run(GOLDEN_DRAFT_N1, DOC_N1, BUNDLE), DOC_N1, "N1")
    assert "농협·조합법인이 신청" in html and "자조금 가입 증명서 농협은 명단 제출" in html and "목록에 보이는 이름표" in html
    assert ">✓<" in html and ">✗<" not in html


def test_report_marks_a_wrong_tag_red_and_lists_dropped_tags():
    bad = draft(program(tags=(("지어낸 조건", "지어낸 문장입니다"),)))
    issues = run(bad, DOC_N1, BUNDLE)
    res = GOLDEN_DRAFT_N1.model_copy(update={"programs": bad.programs, "dropped_tags": ("옛 이름표",)})
    html = render_notice_report(res, issues, DOC_N1, "x")
    assert ">✗<" in html and "TAG_QUOTE_NOT_IN_DOC" in html and "옛 이름표" in html
