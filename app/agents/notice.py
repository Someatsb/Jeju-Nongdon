"""공고 에이전트 루프(Task 29, U29) — 새 공고(PDF·글)를 읽고 도구(Task 18)로 표와 견주어 초안과 근거를 만든다.

에이전트는 제안하고 직원이 정한다. 표 반영은 이 모듈이 하지 않는다(직원 확정만).

- 결정은 Decision 다섯 가지: DRAFT_READY | NEEDS_STAFF | NOT_RELEVANT | BLOCKED_PII | UNREADABLE (finish 도구가 고정한다).
- LLM을 부르기 전에 막는 것(호출 0): 스캔본 → UNREADABLE(직원이 볼 한국어 안내 hint), 문서에 주민번호·휴대전화·메일 → BLOCKED_PII.
  주민번호 규칙은 전송 거름망(payload.RRN)과 같은 것을 쓴다. 걸린 글자는 결과에 담지 않고 종류만 적는다.
- 루프: 도구 호출(dispatch) 합계 ≤ max_tools, 시간 ≤ timeout_s(주입 시계, 기본 time.monotonic). 상한에 닿거나 LLM을 못 쓰거나
  모델이 도구 없이 말만 하면 partial=True, 결정 NEEDS_STAFF, 지금까지 만든 초안(마지막으로 검사한 초안)을 담는다.
- validate_draft·finish의 실패는 예외가 아니라 도구 결과(error 기록)로 모델에게 돌아가 고치게 한다. log.tool_calls는 dispatch 횟수다.
- 모든 LLM 요청은 build_payload(purpose="notice")를 한 번 더 지난다. 거부·녹화 불일치도 LLMUnavailable이라 같은 길로 간다.
"""
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from pydantic import Field

from app.agents.llm.base import GenRequest, LLMClient, LLMUnavailable, Msg, ToolDef, ToolResult
from app.agents.llm.payload import RRN, build_payload
from app.core.models import Program
from app.data_layer.docs_in import Doc
from app.tools.draft_checks import ProgramBundle, pii_labels, strip_bad_tags
from app.tools.models import Decision, NoticeDraft, ToolLog
from app.tools.notice_tools import NoticeTools

_log = logging.getLogger(__name__)

PROMPT_VER = "notice-v4"
PROMPT_DIR = Path(__file__).parent / "prompts"
LEGACY_BEFORE = date(2026, 11, 15)      # notice-v4 가 생긴 날. 그 전에 녹은 찾기 녹화(S1)는 안의 공고 읽기가 notice-v3 이다
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VER}.txt"
MAX_TOOLS = 12
TIMEOUT_S = 90.0
HEAD_LINES = 12
SCAN_HINT = ("글자를 읽을 수 없는 스캔본 PDF입니다. 공고 본문을 복사해 붙여 넣거나, 글자가 선택되는 PDF를 넣어 주세요 "
             "(본문을 붙여 넣으면 바로 읽습니다)")


class NoticeResult(NoticeDraft):
    """NoticeDraft에 결정과 처리 상태를 더한 결과. 초안 모델(도구 입력)은 건드리지 않는다."""

    decision: Decision
    reason: str = ""
    partial: bool = Field(default=False, description="상한·시간·LLM 문제로 끝까지 못 간 미완 초안")
    hint: str | None = Field(default=None, description="직원에게 보일 안내(읽을 수 없음 등)")
    staff_questions: tuple[str, ...] = ()
    dropped_tags: tuple[str, ...] = Field(default=(), description="근거 문장이 원문과 맞지 않아 결과에서 뺀 이름표")


def unreadable(message: str) -> NoticeResult:
    """읽을 수 없는 문서(UnsupportedFormat 메시지 또는 스캔본 안내). LLM 호출 0."""
    return NoticeResult(decision="UNREADABLE", reason="문서를 읽을 수 없습니다", hint=message)


def _pii_found(text: str) -> tuple[str, ...]:
    labels = list(pii_labels(text))
    if re.search(RRN, text) and "rrn" not in labels:
        labels.append("rrn")
    return tuple(labels)


_KIND = {"rrn": "주민번호", "phone": "휴대전화 번호", "email": "메일 주소"}


def _tool_defs(tools: NoticeTools) -> tuple[ToolDef, ...]:
    return tuple(ToolDef(**s) for s in tools.registry().schemas())


def _opening(doc: Doc) -> str:
    head = "\n".join(line for page in doc.pages for line in page.lines[:HEAD_LINES][:HEAD_LINES])[:1500]
    columns = ", ".join(Program.model_fields)
    return (f"공고 문서는 {len(doc.pages)}쪽입니다. 앞부분은 아래와 같습니다. 나머지는 doc_search와 doc_read로 읽으세요.\n"
            f"{head}\n\n표 칸 이름: {columns}")


def _system_prompt(llm: LLMClient) -> str:
    """지시문 글. 녹화를 재생하는 클라이언트(ReplayClient)면 녹화에 적힌 판을 따른다: 요청 해시가 지시문까지 포함해 녹화와 맞아야 하기 때문이다.
    판 이름은 prompts 폴더의 notice-v<숫자>.txt 모양만 받고, 모르는 이름이면 지금 판을 쓴다.
    찾기(scout) 녹화처럼 녹화의 판 이름이 공고 판이 아니면(안에서 공고를 읽는 요청이 함께 녹화돼 있다), v4가 생기기 전(LEGACY_BEFORE)에 녹은 것은 notice-v3로 읽는다."""
    rec = getattr(llm, "recording", None)
    ver = getattr(rec, "prompt_ver", None)
    if isinstance(ver, str) and re.fullmatch(r"notice-v\d+", ver) and (PROMPT_DIR / f"{ver}.txt").is_file():
        return (PROMPT_DIR / f"{ver}.txt").read_text(encoding="utf-8")
    at = getattr(rec, "recorded_at", None)
    if isinstance(ver, str) and isinstance(at, datetime) and at.date() < LEGACY_BEFORE:
        return (PROMPT_DIR / "notice-v3.txt").read_text(encoding="utf-8")
    return PROMPT_PATH.read_text(encoding="utf-8")


def run_notice(doc: Doc, bundle: ProgramBundle, llm: LLMClient, log: ToolLog, max_tools: int = MAX_TOOLS,
               timeout_s: float = TIMEOUT_S, clock: Callable[[], float] = time.monotonic) -> NoticeResult:
    if doc.scanned:
        return unreadable(SCAN_HINT)
    found = _pii_found(doc.text)
    if found:
        kinds = ", ".join(_KIND[k] for k in found)
        _log.warning("공고에 개인정보(%s)가 있어 LLM에 보내지 않습니다", ",".join(found))
        return NoticeResult(decision="BLOCKED_PII", reason=f"문서에 개인정보({kinds})가 있어 AI에 보내지 않았습니다",
                            hint="개인 명단·연락처가 든 문서입니다. 직원이 직접 확인하세요.")

    tools = NoticeTools(doc, bundle, log)
    registry = tools.registry()
    defs = _tool_defs(tools)
    system = _system_prompt(llm)
    messages = [Msg(role="user", text=_opening(doc))]
    start = clock()
    final: tuple[Decision, str] | None = None
    stop = ""
    last_invalid: str | None = None         # 바로 앞 validate_draft가 빨간 오류로 돌려보낸 초안(글). 똑같이 다시 내면 멈춘다
    offered: NoticeDraft | None = None      # finish에 실려 온 초안(검사를 거치지 않은 것도 직원에게 보인다)

    while final is None and not stop:
        if clock() - start >= timeout_s:
            stop = "시간이 다 되어(제한 시간 초과)"
            break
        if log.tool_calls >= max_tools:
            stop = f"도구 호출 한도({max_tools}회)에 닿아"
            break
        try:
            req = GenRequest(purpose="notice", system=system, messages=tuple(messages), tools=defs, max_output_tokens=4096, timeout_s=60.0)
            res = llm.generate(build_payload(req))
        except LLMUnavailable as e:
            _log.warning("공고 처리 중 AI를 쓸 수 없습니다: %s", e.reason)
            stop = f"AI를 쓸 수 없어({e.reason})"
            break
        if not res.tool_calls:
            stop = "AI가 도구를 쓰지 않고 말만 해서"
            break
        messages.append(Msg(role="assistant", text=res.text, tool_calls=res.tool_calls))
        results = []
        for tc in res.tool_calls:
            if log.tool_calls >= max_tools:
                stop = f"도구 호출 한도({max_tools}회)에 닿아"
                break
            if clock() - start >= timeout_s:
                stop = "시간이 다 되어(제한 시간 초과)"
                break
            rec = registry.dispatch(tc.name, tc.args, log)
            results.append(ToolResult(call_id=tc.call_id, content=rec.content(), is_error=not rec.ok))
            if tc.name == "validate_draft":
                red = rec.ok and any(e["level"] == "RED" for e in rec.result["errors"])
                sig = json.dumps(tc.args, sort_keys=True, ensure_ascii=False)
                if red and sig == last_invalid:
                    stop = "같은 초안을 고치지 않고 다시 내서"
                    break
                last_invalid = sig if red else None
            if tc.name == "finish" and rec.ok:
                final = (rec.result["decision"], rec.result["reason"])
                if tc.args.get("draft"):
                    offered = NoticeDraft.model_validate(tc.args["draft"])   # dispatch가 이미 형식을 확인했다
                break
        if results and final is None:
            messages.append(Msg(role="user", tool_results=tuple(results)))

    draft = offered or tools.last_draft or NoticeDraft()
    draft, dropped = strip_bad_tags(draft, doc)    # 끝까지 근거가 안 맞은 이름표는 결과에 싣지 않는다
    questions = tuple(q.question for q in log.questions)
    if final is not None:
        decision, reason = final
        if decision in ("NOT_RELEVANT", "BLOCKED_PII", "UNREADABLE"):
            draft = NoticeDraft(skipped=draft.skipped)
        return NoticeResult(programs=draft.programs, skipped=draft.skipped, decision=decision, reason=reason,
                            staff_questions=questions, dropped_tags=dropped)
    return NoticeResult(programs=draft.programs, skipped=draft.skipped, decision="NEEDS_STAFF", partial=True,
                        reason=f"{stop} 끝까지 마치지 못했습니다. 지금까지의 초안을 직원이 확인하세요",
                        hint="미완 초안입니다. 원문을 보고 직원이 마무리하세요", staff_questions=questions, dropped_tags=dropped)


def dump_json(result: NoticeResult) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
