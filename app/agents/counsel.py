"""상담 에이전트 설명 단계(Task 28, U28): 구획마다 LLM이 짧은 설명을 쓰고, 검수 루프(Task 19)를 지나, 못 지나면 템플릿.

흐름: FactSheet → pipeline.narrative_input(숫자 없는 근거) → 구획(support/insurance/action, 빈 종이면 empty 하나)마다
요청 → 후보 구획 → review_section(규칙·판정·재생성·템플릿). 실패한 구획만 재생성한다(구획은 서로 독립).

- LLM에는 제도 이름·숫자·날짜·금액이 나가지 않는다. 근거 줄은 id·상태 코드만 싣고 이름은 {P:program_id} 자리표시자로
  쓰게 한다(texts()가 종이용 글로 채운다). 요청은 build_payload(전송 거름망)를 한 번 더 지난다.
- 예산: narrate가 시작될 때 clock()을 읽고, 이후 LLM 호출(생성·판정·재생성)마다 budget_s(기본 45초)가 지났는지 본다.
  지났으면 그 호출은 LLMUnavailable("TIMEOUT") → 그 구획과 남은 구획은 템플릿. 시계는 주입한다(기본 time.monotonic).
- LLM을 쓸 수 없는 사유 중 전체에 해당하는 것(키 없음·인증·결제·하루 상한·차단·예산)은 남은 구획을 호출 없이 템플릿으로 한다.
  녹화 불일치·전송 거부는 그 요청에만 해당해 다음 구획은 계속 시도한다.
- Narrative.mode: "ai" = 모든 구획이 AI 문장으로 통과, "template" = AI 문장으로 통과한 구획이 하나도 없음(구획이 없을 때,
  LLM을 못 쓸 때, 그리고 LLM은 썼지만 모든 구획이 검수에서 떨어져 템플릿이 된 때도 — 받아들인 동작), "mixed" = 섞임(예산 초과 포함).
- parallel=True(실제 서비스 모드만)면 구획을 스레드로 동시에 돌린다. 구획마다 따로 검수 로그를 모았다가 ORDER 순서로 실제 로그에
  옮겨 쓴다(로그·결과 순서는 차례대로일 때와 같다). 예산(clock)은 모두가 같은 시작 시각을 본다. 한 구획이 예외를 내도 그 구획만
  템플릿이 된다. 기본값(False)은 차례대로: 재생·녹화·시험은 호출 순서에 기대고 있다.
- 빈 종이(ctx.empty_sheet)는 구획이 empty 하나뿐이다.
- texts()는 UI(render_sheet)가 받는 {"action"|"support"|"insurance"|"empty": [문장…]}. 자리표시자를 이름으로 바꾸고
  숫자가 든 문장·모르는 자리표시자가 든 문장은 버리며, 버릴 때마다 logging으로 남긴다(문장 원문은 싣지 않는다).
- 지시문 판(PROMPT_VER)은 narrate-v3부터 해요체다. 판이 v3 이상이면 요청의 action 구획에 먼저 하실 일의 첫 가실 곳 종류(first_stop: 농관원·농협…,
  숫자·읍면동 이름 없음)를 싣고, 검수에 말투 검사(app.agents.style: 합쇼체·행정 말·가실 곳 순서)를 더한다.
  녹화를 재생하는 클라이언트(.recording.prompt_ver)면 녹화에 적힌 판을 따른다: 요청 해시가 지시문까지 포함해 녹화와 맞아야 하고,
  옛 녹화의 합쇼체 문장이 새 말투 검사에 걸리면 안 되기 때문이다(부장이 실제 AI로 다시 녹화하면 새 판으로 재생된다).
- 로그(log)는 review_section과 같은 ReviewLog다. 이 모듈이 더하는 줄은 attempt=0, verdict="SKIPPED"/"UNPARSEABLE"로 구별한다.
"""
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from app.agents.fallback_ko import template_for
from app.agents.llm.base import GenRequest, GenResult, LLMClient, LLMUnavailable, Msg
from app.agents.llm.payload import build_payload
from app.agents.reviewer import Feedback, MemoryReviewLog, ReviewLog, ReviewOutcome, review_section
from app.agents.rules import PLACEHOLDER, RULES_VERSION, Section, SectionKind
from app.agents.style import FIRST_STOP_KEY, first_stop_label, style_check_for
from app.core.models import CoreModel, FactSheet, NarrativeInput
from app.core.pipeline import narrative_input
from app.tools.counsel_tools import CounselTools
from app.tools.registry import ToolError

_log = logging.getLogger(__name__)

PROMPT_VER = "narrate-v3"
PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VER}.txt"
HAEYO_FROM = 3       # 이 판(narrate-v<숫자>)부터 해요체 지시문: first_stop 입력과 말투 검사가 붙는다
BUDGET_S = 45.0
ORDER: tuple[SectionKind, ...] = ("support", "insurance", "action")
# 이 사유로 못 쓰면 남은 구획도 못 쓴다. REPLAY_MISMATCH·PAYLOAD_REJECTED 등은 그 요청에만 해당한다.
_DOWN = frozenset({"NO_KEY", "AUTH", "BILLING", "DAILY_CAP", "CIRCUIT_OPEN", "TIMEOUT"})
_DIGIT = re.compile(r"[0-9０-９①-⑳]")

_SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "section": {"enum": [*ORDER, "empty"]},
        "sentences": {"type": "array", "maxItems": 3, "items": {
            "type": "object",
            "properties": {"sid": {"type": "integer", "minimum": 1}, "text": {"type": "string"},
                           "cites": {"type": "array", "items": {"type": "string"}}},
            "required": ["sid", "text", "cites"], "additionalProperties": False}},
    },
    "required": ["section", "sentences"], "additionalProperties": False,
}


# --- 요청 ------------------------------------------------------------------------------------

def prompt_ver_for(llm: object) -> str:
    """이 호출이 쓸 지시문 판. 녹화를 재생하는 클라이언트(ReplayClient)면 녹화에 적힌 판(있는 파일만), 아니면 지금 판."""
    ver = getattr(getattr(llm, "recording", None), "prompt_ver", None)
    if isinstance(ver, str) and re.fullmatch(r"narrate-v\d+", ver) and (PROMPT_DIR / f"{ver}.txt").is_file():
        return ver
    return PROMPT_VER


def haeyo(ver: str) -> bool:
    return int(ver.rsplit("-v", 1)[1]) >= HAEYO_FROM


def build_request(kind: SectionKind, ctx: NarrativeInput, feedback: Feedback | None = None,
                  ver: str = PROMPT_VER) -> GenRequest:
    """kind 구획을 쓰라는 요청. 근거는 id·상태 코드만 싣는다(이름·숫자 없음). 재생성이면 지시문을 뒤에 붙인다.
    해요체 판(v3~)의 action 구획에는 먼저 하실 일의 첫 가실 곳 종류(first_stop)도 싣는다(곳의 종류 이름뿐이다)."""
    items = [{"fact_id": i.fact_id, "program_id": i.program_id, "status": i.status, "row_status": i.row_status,
              "missing": list(i.missing), "window": i.window} for i in ctx.items if i.section == kind]
    body: dict[str, Any] = {"section": kind, "items": items}
    if haeyo(ver) and kind == "action" and (stop := first_stop_label(ctx)):
        body[FIRST_STOP_KEY] = stop
    text = json.dumps(body, ensure_ascii=False)
    if feedback is not None:
        text += "\n\n" + feedback.text
    return GenRequest(purpose="narrate", system=(PROMPT_DIR / f"{ver}.txt").read_text(encoding="utf-8"),
                      messages=(Msg(role="user", text=text),), response_schema=_SECTION_SCHEMA, section=kind)


class _Budgeted:
    """예산(시계 주입)과 전송 거름망을 거는 LLMClient 장식자."""

    def __init__(self, client: LLMClient, clock: Callable[[], float], budget_s: float) -> None:
        self.client, self._clock, self._budget_s = client, clock, budget_s
        self._start = clock()
        self.provider, self.model = client.provider, client.model

    def generate(self, req: GenRequest) -> GenResult:
        if self._clock() - self._start >= self._budget_s:
            raise LLMUnavailable("TIMEOUT", "설명 예산을 다 썼습니다")
        build_payload(req)  # 거름망: 걸리면 PayloadRejected(LLMUnavailable)
        return self.client.generate(req)


# --- 결과 ------------------------------------------------------------------------------------

_JOSA = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"), "을": ("을", "를"), "를": ("을", "를"),
         "과": ("과", "와"), "와": ("과", "와"), "으로": ("으로", "로"), "로": ("으로", "로")}
_JOSA_AFTER = re.compile(r"(으로|[은는이가을를과와로])(?![가-힣])")   # 조사 뒤에 한글이 더 이어지면(예: 이름의 일부) 조사로 보지 않는다
_TAIL_CLOSERS = ")]」』>"


def _final_jamo(name: str) -> str | None:
    """이름 끝 글자의 받침: '' 받침 없음, 'ㄹ' ㄹ받침, 'x' 그 밖의 받침, None 모름. 괄호로 끝나면 괄호 안 마지막 글자."""
    stripped = name.rstrip(_TAIL_CLOSERS) if name.endswith(tuple(_TAIL_CLOSERS)) else name
    if not stripped:
        return None
    ch = stripped[-1]
    if not "가" <= ch <= "힣":
        return None
    jong = (ord(ch) - 0xAC00) % 28
    return "" if jong == 0 else "ㄹ" if jong == 8 else "x"


def fix_josa(name: str, tail: str) -> str:
    """채운 이름(name) 바로 뒤의 조사를 이름의 받침에 맞춘다(은/는·이/가·을/를·과/와·으로/로). 모르면 그대로."""
    m = _JOSA_AFTER.match(tail)
    final = _final_jamo(name)
    if m is None or final is None:
        return tail
    with_final, without = _JOSA[m.group(1)]
    if with_final == "으로":
        josa = "로" if final in ("", "ㄹ") else "으로"
    else:
        josa = without if final == "" else with_final
    return josa + tail[m.end():]


def fill_placeholders(text: str, names: dict[str, str]) -> str:
    """{P:id}를 이름으로 채우고 뒤따르는 조사를 받침에 맞춘다."""
    out, pos = [], 0
    for m in re.finditer(PLACEHOLDER, text):
        out.append(text[pos:m.start()])
        name = names.get(m.group(1), m.group(0))
        out.append(name)
        nxt = re.match(r"(으로|[은는이가을를과와로])(?![가-힣])", text[m.end():])
        if nxt and m.group(1) in names:
            out.append(fix_josa(name, nxt.group(0)))
            pos = m.end() + nxt.end()
        else:
            pos = m.end()
    out.append(text[pos:])
    return "".join(out)


class Sentence_(str):
    """종이에 찍을 설명 문장. pids = 문장이 {P:id}·cites(M:/P:)로 가리키는 제도 별칭(앞면 구역 배치용)."""
    pids: tuple[str, ...] = ()


class Narrative(CoreModel):
    sections: dict[str, ReviewOutcome]
    mode: Literal["ai", "template", "mixed"]
    names: dict[str, str]                       # program_id → 정식 이름({P:id} 채우기용)

    def texts(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for kind, outcome in self.sections.items():
            kept: list[str] = []
            for s in outcome.final.sentences:
                unknown = [pid for pid in re.findall(PLACEHOLDER, s.text) if pid not in self.names]
                text = fill_placeholders(s.text, self.names)
                if unknown:
                    _log.warning("구획 %s의 %s번째 문장을 버립니다: 종이에 없는 제도 자리표시자", kind, s.sid)
                elif _DIGIT.search(text):
                    _log.warning("구획 %s의 %s번째 문장을 버립니다: 숫자가 들어 있습니다", kind, s.sid)
                else:
                    sent = Sentence_(text)
                    refs = [*re.findall(PLACEHOLDER, s.text), *(c[2:] for c in (s.cites or ()) if c[:2] in ("M:", "P:"))]
                    sent.pids = tuple(dict.fromkeys(refs))
                    kept.append(sent)
            if kept:
                out[kind] = kept
        return out


def _template(kind: SectionKind, ctx: NarrativeInput, log: ReviewLog, reason: str, ver: str = PROMPT_VER) -> ReviewOutcome:
    _log.warning("구획 %s: 기본 문장(템플릿)으로 대체합니다 - %s", kind, reason)
    log.write({"section": kind, "attempt": 0, "rules_ver": RULES_VERSION, "checks": [], "judge": None,
               "verdict": "SKIPPED", "reason": reason, "prompt_ver": ver})
    return ReviewOutcome(final=template_for(kind, ctx), source="template", attempts=0)


def narrate(fs: FactSheet, llm: LLMClient, log: ReviewLog, *,
            clock: Callable[[], float] = time.monotonic, budget_s: float = BUDGET_S, use_judge: bool = True,
            parallel: bool = False) -> Narrative:
    """설명 단계. 근거는 core.pipeline.narrative_input(fs)가 만든다(이름은 FactSheet.facts의 name: 사실).
    use_judge=False면 LLM 판정(R7)을 건너뛴다."""
    ctx = narrative_input(fs)
    ver = prompt_ver_for(llm)                    # 재생이면 녹화의 판, 아니면 지금 판
    style = style_check_for(first_stop_label(ctx)) if haeyo(ver) else None
    client = _Budgeted(llm, clock, budget_s)
    tools = CounselTools(None)  # 표 묶음 없이 submit_narrative만 쓴다(나머지 도구는 표 묶음이 없다는 한국어 오류)
    sheet_ids = frozenset(i.program_id for i in ctx.items)
    kinds: tuple[SectionKind, ...]
    # 빈 종이는 구획 하나(empty)만 쓴다. 보험·행동 근거가 있어도 종이에는 empty 문장 하나뿐이다(Task 28 브리프).
    wanted = ("empty",) if ctx.empty_sheet else ORDER
    kinds = tuple(k for k in wanted if any(i.section == k for i in ctx.items))

    def ask(kind: SectionKind, fb: Feedback | None, wlog: ReviewLog) -> Section:
        res = client.generate(build_request(kind, ctx, fb, ver))
        try:
            return tools.submit_narrative(res.text or "").model_copy(update={"section": kind})
        except ToolError as e:
            wlog.write({"section": kind, "attempt": 0, "rules_ver": RULES_VERSION, "checks": [], "judge": None,
                        "verdict": "UNPARSEABLE", "reason": str(e)})
            return Section(section=kind, sentences=())

    down_flag = threading.Event()
    down_reason: list[str] = []

    def work(kind: SectionKind, wlog: ReviewLog, guard_exc: bool) -> ReviewOutcome:
        if down_flag.is_set():
            return _template(kind, ctx, wlog, f"LLM을 쓸 수 없음({down_reason[0]})", ver)
        try:
            candidate = ask(kind, None, wlog)
        except LLMUnavailable as e:
            if e.reason in _DOWN and not down_flag.is_set():
                down_reason.append(e.reason)
                down_flag.set()
            return _template(kind, ctx, wlog, f"LLM을 쓸 수 없음({e.reason})", ver)
        except Exception as e:  # noqa: BLE001 - 동시 모드에서는 한 구획의 예상 밖 실패가 다른 구획을 막지 않게 한다
            if not guard_exc:
                raise
            return _template(kind, ctx, wlog, f"예상하지 못한 오류({type(e).__name__})", ver)
        try:
            outcome = review_section(candidate, ctx, sheet_ids, client if use_judge else None,
                                     regen=lambda fb, k=kind: ask(k, fb, wlog), log=wlog, style=style)
        except Exception as e:  # noqa: BLE001
            if not guard_exc:
                raise
            return _template(kind, ctx, wlog, f"예상하지 못한 오류({type(e).__name__})", ver)
        if outcome.source == "template":
            _log.warning("구획 %s: 검수를 통과하지 못해 기본 문장으로 대체했습니다(시도 %s번)", kind, outcome.attempts)
        return outcome

    outcomes: dict[str, ReviewOutcome] = {}
    if parallel and len(kinds) > 1:
        logs = {k: MemoryReviewLog() for k in kinds}
        with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
            futures = {k: pool.submit(work, k, logs[k], True) for k in kinds}
        for k in kinds:                       # ORDER 순서로 모아 쓴다
            outcomes[k] = futures[k].result()
            for entry in logs[k].entries:
                log.write(entry)
    else:
        for kind in kinds:
            outcomes[kind] = work(kind, log, False)

    passed = sum(o.source == "ai_pass" for o in outcomes.values())
    mode = "ai" if outcomes and passed == len(outcomes) else "template" if passed == 0 else "mixed"
    return Narrative(sections=outcomes, mode=mode, names={i.program_id: i.official_name for i in ctx.items})
