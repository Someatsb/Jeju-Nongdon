"""공고 에이전트 도구 6개(Task 18) — research/dept/round2-C-agent.md §6-1 표.

NoticeTools(doc, bundle, log) 한 개가 공고 한 건을 맡는다. 메서드는 도메인 값을 돌려주고 잘못된 호출은 ToolError를 던진다.
registry()가 LLM에 보일 여섯 도구(입력·출력 모델)를 만든다. 입력 모델의 설명에는 숫자를 쓰지 않는다.
"""
import re

from pydantic import BaseModel, Field

from app.data_layer.docs_in import Doc
from app.tools import draft_checks
from app.tools.draft_checks import ProgramBundle, squash
from app.tools.models import (
    AskResult,
    Decision,
    DraftIssue,
    FinishResult,
    Hit,
    NoticeDraft,
    ProgramMatch,
    ReadResult,
    StaffQuestion,
    ToolLog,
)
from app.tools.registry import ToolError, ToolRegistry

MAX_QUESTIONS = 5
MAX_READ_LINES = 60
MAX_HITS = 20
MIN_MATCH_SCORE = 0.35
_ANCHOR = re.compile(r"p(\d+):L(\d+)")
_STOP = ("지원사업", "지원", "사업", "공고", "모집")
_NOISE = re.compile(r"\d+\s*년|\d+\s*차|[()\[\]]")


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def _name_key(name: str) -> str:
    """사업 이름 비교용: 연도·차수·괄호 기호·'지원사업' 같은 흔한 말을 걷어 낸 squash."""
    t = _NOISE.sub(" ", name)
    for word in _STOP:
        t = t.replace(word, " ")
    return squash(t)


def _name_score(query: str, row: str) -> float:
    if not query or not row:
        return 0.0
    a, b = _bigrams(query), _bigrams(row)
    dice = 2 * len(a & b) / (len(a) + len(b))
    shorter, longer = sorted((query, row), key=len)
    return max(dice, 0.9 if len(shorter) >= 3 and shorter in longer else 0.0)


class NoticeTools:
    def __init__(self, doc: Doc, bundle: ProgramBundle, log: ToolLog) -> None:
        self.doc, self.bundle, self.log = doc, bundle, log
        self._last_draft: NoticeDraft | None = None
        self._lines = [(f"p{p.number}:L{n}", line, squash(line)) for p in doc.pages for n, line in enumerate(p.lines, 1)]

    @property
    def last_draft(self) -> NoticeDraft | None:
        """마지막으로 검사(validate_draft)한 초안. 없으면 None."""
        return self._last_draft

    # --- 문서 -------------------------------------------------------------------------------

    def doc_search(self, query: str, k: int = 5) -> list[Hit]:
        tokens = re.findall(r"[0-9A-Za-z가-힣]+", query)
        if not tokens:
            raise ToolError("검색어가 비어 있습니다. 찾을 낱말을 적어 주세요 (예: 지원단가, 신청기간)")
        wanted = set().union(*(_bigrams(squash(t)) for t in tokens))
        phrase = squash("".join(tokens))
        scored = []
        for pos, (anchor, line, flat) in enumerate(self._lines):
            coverage = sum(1 for g in wanted if g in flat) / len(wanted)
            if not coverage:
                continue
            scored.append((round(coverage + (1.0 if phrase in flat else 0.0), 4), pos, Hit(anchor=anchor, passage=line, score=0.0)))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [h.model_copy(update={"score": sc}) for sc, _pos, h in scored[:max(1, min(k, MAX_HITS))]]

    def doc_read(self, anchor: str, n_lines: int = 20) -> ReadResult:
        m = _ANCHOR.fullmatch(anchor.strip())
        if not m:
            raise ToolError(f"앵커 형식이 아닙니다: {anchor}. doc_search 결과의 앵커를 그대로 쓰세요 (예: p1:L3)")
        page_no, line_no = int(m[1]), int(m[2])
        if not 1 <= page_no <= len(self.doc.pages):
            raise ToolError(f"{page_no}쪽이 없습니다. 문서는 1쪽부터 {len(self.doc.pages)}쪽까지입니다")
        lines = self.doc.pages[page_no - 1].lines
        if not 1 <= line_no <= len(lines):
            raise ToolError(f"{page_no}쪽에 {line_no}번 줄이 없습니다. 그 쪽은 {len(lines)}줄까지입니다")
        end = min(line_no - 1 + max(1, min(n_lines, MAX_READ_LINES)), len(lines))
        if end < len(lines):
            nxt = f"p{page_no}:L{end + 1}"
        else:
            nxt = f"p{page_no + 1}:L1" if page_no < len(self.doc.pages) and self.doc.pages[page_no].lines else None
        return ReadResult(anchor=f"p{page_no}:L{line_no}", text="\n".join(lines[line_no - 1:end]), next_anchor=nxt)

    # --- 표 ---------------------------------------------------------------------------------

    def find_existing_program(self, name: str, agency: str | None = None, edition: str | None = None) -> list[ProgramMatch]:
        query = _name_key(name)
        found = []
        for row in self.bundle.programs:
            if edition and getattr(row, "edition", None) != edition:
                continue
            score = _name_score(query, _name_key(row.name or ""))
            if score < MIN_MATCH_SCORE:
                continue
            row_agency = getattr(row, "agency", None)
            if agency and row_agency and (squash(agency) in squash(row_agency) or squash(row_agency) in squash(agency)):
                score += 0.1
            found.append(ProgramMatch(id=row.id, program_key=row.program_key, name=row.name, edition=getattr(row, "edition", ""),
                                      status=getattr(row, "status", ""), score=round(min(score, 1.0), 3)))
        found.sort(key=lambda m: m.id)
        found.sort(key=lambda m: m.edition, reverse=True)       # 안정 정렬을 겹쳐서: 점수 내림차순, 같으면 최신 edition
        found.sort(key=lambda m: -m.score)
        return found[:5]

    # --- 초안 -------------------------------------------------------------------------------

    def validate_draft(self, draft: NoticeDraft) -> list[DraftIssue]:
        self._last_draft = draft
        return draft_checks.run(draft, self.doc, self.bundle)

    def ask_staff(self, field: str, question: str) -> AskResult:
        if draft_checks.pii_labels(f"{field} {question}"):
            raise ToolError("질문에 개인정보(전화번호·주민번호·메일)가 있어 접수하지 않았습니다. 지우고 다시 물어 주세요")
        key = (field, squash(question))
        if any((q.field, squash(q.question)) == key for q in self.log.questions):
            return AskResult(queued=False, message="같은 질문이 이미 접수되어 있습니다")
        if len(self.log.questions) >= MAX_QUESTIONS:
            raise ToolError("직원 질문은 다섯 개까지만 받습니다. 가장 중요한 것만 남기고 끝내기를 부르세요")
        self.log.questions.append(StaffQuestion(field, question))
        return AskResult(queued=True, message="직원 질문으로 접수했습니다. 답을 기다리지 말고 계속 진행하세요")

    def finish(self, decision: Decision, reason: str, draft: NoticeDraft | None = None) -> FinishResult:
        if decision == "DRAFT_READY":
            draft = draft or self._last_draft
            if draft is None:
                raise ToolError("초안이 없습니다. 먼저 validate_draft로 초안을 검사하거나 finish에 초안을 함께 넘기세요")
            if not draft.programs:
                raise ToolError("초안에 사업이 하나도 없습니다. 사업이 없으면 NOT_RELEVANT로 끝내세요")
            red = [i for i in self.validate_draft(draft) if i.level == "RED"]
            if red:
                listed = "; ".join(f"{i.field}({i.code})" for i in red[:5])
                raise ToolError(f"빨간 오류가 {len(red)}개 남아 있어 끝낼 수 없습니다: {listed}. 고치거나 NEEDS_STAFF로 끝내세요")
        return FinishResult(ok=True, decision=decision, reason=reason)

    # --- 등록부 -----------------------------------------------------------------------------

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register("doc_search", SearchIn, SearchOut, lambda a: SearchOut(hits=self.doc_search(a.query, a.k)))
        reg.register("doc_read", ReadIn, ReadResult, lambda a: self.doc_read(a.anchor, a.n_lines))
        reg.register("find_existing_program", FindIn, FindOut,
                     lambda a: FindOut(matches=self.find_existing_program(a.name, a.agency, a.edition)))
        reg.register("validate_draft", ValidateIn, ValidateOut, lambda a: ValidateOut(errors=self.validate_draft(a.draft)))
        reg.register("ask_staff", AskIn, AskResult, lambda a: self.ask_staff(a.field, a.question))
        reg.register("finish", FinishIn, FinishResult, lambda a: self.finish(a.decision, a.reason, a.draft))
        return reg


# --- 도구 입력·출력 모델(독스트링·설명에 숫자 금지) ---------------------------------------------

class SearchIn(BaseModel):
    """공고 문서에서 낱말로 줄을 찾는다. 결과는 앵커와 그 줄의 글, 점수이며 점수가 높을수록 가깝다."""

    query: str = Field(description="찾을 낱말. 예를 들어 신청자격, 지원단가, 신청기간")
    k: int = Field(default=5, ge=1, le=MAX_HITS, description="돌려줄 결과 개수")


class SearchOut(BaseModel):
    hits: list[Hit]


class ReadIn(BaseModel):
    """앵커 자리부터 공고 문서를 줄 단위로 읽는다. 한 쪽 안에서만 읽고 이어서 읽을 앵커를 돌려준다."""

    anchor: str = Field(description="doc_search가 돌려준 앵커")
    n_lines: int = Field(default=20, ge=1, le=200, description="읽을 줄 수. 한 번에 읽을 수 있는 상한이 있다")


class FindIn(BaseModel):
    """공고의 사업 이름으로 표에 이미 있는 사업을 찾는다. 같은 점수면 최신 판이 앞에 온다."""

    name: str = Field(description="공고에 적힌 사업 이름")
    agency: str | None = Field(default=None, description="담당 기관 이름")
    edition: str | None = Field(default=None, description="찾을 판(연도). 비우면 모든 판")


class FindOut(BaseModel):
    matches: list[ProgramMatch]


class ValidateIn(BaseModel):
    """초안을 코드로 검사한다. 빨간 오류가 없어야 끝낼 수 있고 노란 경고는 직원이 본다."""

    draft: NoticeDraft


class ValidateOut(BaseModel):
    errors: list[DraftIssue]


class AskIn(BaseModel):
    """공고만으로 정할 수 없는 것을 직원에게 묻는다. 같은 질문은 한 번만 받고 개수에 상한이 있다. 개인정보는 넣지 않는다."""

    field: str = Field(description="질문이 걸린 표 칸 이름")
    question: str = Field(description="직원이 답하기 쉬운 한 문장")


class FinishIn(BaseModel):
    """처리를 끝낸다. 초안 완성은 빨간 오류가 없을 때만 받는다."""

    decision: Decision = Field(description="끝내는 방식")
    reason: str = Field(description="그렇게 끝낸 이유 한 문장")
    draft: NoticeDraft | None = Field(default=None, description="초안 완성일 때 넘기는 초안. 비우면 마지막으로 검사한 초안")

