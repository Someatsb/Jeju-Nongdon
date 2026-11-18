"""공고 근거 보고서(Task 29) — 직원이 초안을 확정하기 전에 보는 한 장.

왼쪽에 초안(사업별 칸과 값), 오른쪽에 원문 인용과 쪽 번호, 칸마다 ✓(문제 없음) / !(노랑, 직원이 보고 넘어갈 수 있음) / ✗(빨강, 확정 불가).
에이전트 층은 이 모듈을 부르지 않는다(명령줄 app/cli.py가 둘을 잇는다). 보고서에는 원문 전체를 싣지 않고 인용 문장만 싣는다.
"""
import re
from collections.abc import Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.agents.notice import NoticeResult
from app.config import APP_ROOT
from app.data_layer.docs_in import Doc
from app.tools.draft_checks import squash
from app.tools.models import DraftIssue

_env = Environment(loader=FileSystemLoader(APP_ROOT / "app" / "ui" / "templates"), autoescape=select_autoescape(["html"]),
                   trim_blocks=True, lstrip_blocks=True)
_ANCHOR = re.compile(r"p(\d+):L(\d+)")
DECISION_LABEL = {"DRAFT_READY": "초안 완성(직원 확인 필요)", "NEEDS_STAFF": "직원이 마무리해야 함",
                  "NOT_RELEVANT": "해당 없음(개인 농업인 대상 아님)", "BLOCKED_PII": "개인정보가 있어 AI에 보내지 않음",
                  "UNREADABLE": "읽을 수 없음"}


def field_marks(result: NoticeResult, issues: Sequence[DraftIssue]) -> dict[tuple[int, str], str]:
    """(사업 순번, 칸 이름) → ✓ / ! / ✗. 같은 칸에 빨강이 하나라도 있으면 ✗."""
    worst: dict[tuple[int, str], str] = {}
    for i in issues:
        if i.program is None:
            continue
        key = (i.program, i.field)
        if i.level == "RED" or key not in worst:
            worst[key] = "✗" if i.level == "RED" else "!"
    return {(n, name): worst.get((n, name), "✓") for n, p in enumerate(result.programs) for name in p.fields}


def _page_of(doc: Doc | None, anchor: str | None, quote: str | None) -> int | None:
    if anchor and (m := _ANCHOR.fullmatch(anchor.strip())):
        return int(m[1])
    if doc is not None and quote and squash(quote):
        want = squash(quote)
        for page in doc.pages:
            if want in squash(page.text):
                return page.number
    return None


def _value(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def render_notice_report(result: NoticeResult, issues: Sequence[DraftIssue], doc: Doc | None, title: str) -> str:
    marks = field_marks(result, issues)
    by_field: dict[tuple[int, str], list[DraftIssue]] = {}
    program_issues: dict[int, list[DraftIssue]] = {}
    for i in issues:
        if i.program is None:
            continue
        by_field.setdefault((i.program, i.field), []).append(i)
        if i.field in ("match_id", "program_key"):
            program_issues.setdefault(i.program, []).append(i)
    programs = []
    for n, p in enumerate(result.programs):
        rows = [{"name": name, "value": _value(f.value), "quote": f.quote or "", "page": _page_of(doc, f.anchor, f.quote),
                 "anchor": f.anchor, "mark": marks[(n, name)], "issues": by_field.get((n, name), [])}
                for name, f in p.fields.items()]
        tags = []
        for j, t in enumerate(p.tags):
            found = by_field.get((n, f"tags.{j}"), [])
            tags.append({"label": t.label, "quote": t.quote or "", "page": _page_of(doc, t.anchor, t.quote), "anchor": t.anchor,
                         "mark": ("✗" if any(i.level == "RED" for i in found) else "!" if found else "✓"), "issues": found})
        programs.append({"n": n + 1, "p": p, "rows": rows, "tags": tags, "issues": program_issues.get(n, [])})
    return _env.get_template("report_notice.html").render(
        title=title, result=result, decision=DECISION_LABEL[result.decision], programs=programs,
        general_issues=[i for i in issues if i.program is None], total=len(issues),
        red=sum(1 for i in issues if i.level == "RED"))
