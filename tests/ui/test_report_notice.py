"""공고 근거 보고서(Task 29) 시험: 왼쪽 초안, 오른쪽 원문 인용·쪽, 칸마다 ✓/!/✗."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from notice_fixtures import BUNDLE, DOC_N1  # noqa: E402
from notice_loop_fixtures import DOC_N5, GOLDEN_DRAFT_N1  # noqa: E402

from app.agents.notice import unreadable  # noqa: E402
from app.tools import draft_checks  # noqa: E402
from app.tools.models import DraftField  # noqa: E402
from app.ui.report_notice import field_marks, render_notice_report  # noqa: E402


def _issues(result):
    return draft_checks.run(result, DOC_N1, BUNDLE)


def test_golden_report_has_two_columns_page_numbers_and_ok_marks():
    html = render_notice_report(GOLDEN_DRAFT_N1, _issues(GOLDEN_DRAFT_N1), DOC_N1, "N1 물류비 공고")
    assert "초안" in html and "원문 인용" in html
    assert ">✓<" in html and ">✗<" not in html
    assert "신청기간" in html and "쪽" in html
    assert "JEJU-LOGI@2026-27" in html and "직원이 확정" in html


def test_marks_red_yellow_and_ok():
    prog = GOLDEN_DRAFT_N1.programs[0]
    fields = dict(prog.fields)
    fields["apply_start"] = DraftField(value="2026-07-23", quote=prog.fields["apply_start"].quote)   # 값이 인용과 다름 → 빨강
    bad = GOLDEN_DRAFT_N1.model_copy(update={"programs": (prog.model_copy(update={"fields": fields}),)})
    issues = _issues(bad)
    marks = field_marks(bad, issues)
    assert marks[(0, "apply_start")] == "✗" and marks[(0, "applicant")] == "✓"
    html = render_notice_report(bad, issues, DOC_N1, "x")
    assert ">✗<" in html and "VALUE_NOT_IN_QUOTE" in html


def test_quote_page_is_found_from_document_when_anchor_missing():
    html = render_notice_report(GOLDEN_DRAFT_N1, [], DOC_N1, "x")
    assert "1쪽" in html or "2쪽" in html


def test_html_is_escaped():
    prog = GOLDEN_DRAFT_N1.programs[0]
    fields = {"applicant": DraftField(value="<script>x</script>", quote="<b>")}
    r = GOLDEN_DRAFT_N1.model_copy(update={"programs": (prog.model_copy(update={"fields": fields}),)})
    html = render_notice_report(r, [], DOC_N1, "x")
    assert "<script>x" not in html and "&lt;script&gt;" in html


def test_unreadable_and_blocked_reports_show_hint_and_no_document_text():
    html = render_notice_report(unreadable("HWP는 PDF로 저장해 주세요"), [], None, "x.hwp")
    assert "읽을 수 없음" in html and "HWP는 PDF로 저장해 주세요" in html
    from app.agents.notice import run_notice
    from app.tools.models import ToolLog
    blocked = run_notice(DOC_N5, BUNDLE, None, ToolLog())      # 호출 0이라 LLM 자리는 비워도 된다
    html = render_notice_report(blocked, [], DOC_N5, "N5")
    assert "개인정보" in html and "010-" not in html and "홍길동" not in html


def test_partial_is_labeled_incomplete():
    r = GOLDEN_DRAFT_N1.model_copy(update={"partial": True, "decision": "NEEDS_STAFF", "hint": "미완 초안입니다"})
    assert "미완" in render_notice_report(r, [], DOC_N1, "x")
