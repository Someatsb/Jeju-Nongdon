"""검수 루프(Task 19, U19): 규칙 R1~R6 → (선택) LLM 판정 R7 → 숫자 없는 지시문 → 재생성(최대 두 번) → 템플릿.

- attempts는 후보에 규칙 검사를 건 횟수다(처음 + 재생성). 끝까지 실패하면 3회, source="template".
- LLM으로 나가는 지시문(Feedback)은 규칙 코드와 RULE_MESSAGES, 한글로 쓴 문장 순서("첫째 문장")만 쓴다.
  Hit.span은 문장 원문 조각이라 숫자를 담을 수 있어 절대 싣지 않는다.
- 재생성은 새 요청이다. regen은 Feedback만 받는다(앞선 도구 호출을 되풀이해 보내지 않는다).
- 판정(R7)은 규칙을 통과한 문장에만 건다. 판정이 못 쓰이거나 답이 깨졌으면 "판정 생략"으로 기록하고 규칙만으로 간다.
- 로그는 규칙 코드와 문장 순서만 적는다(문장 원문 없음). 시각은 읽지 않고 파일 날짜는 as_of로 정한다.
"""
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Literal, Protocol

from app.agents.fallback_ko import template_for
from app.agents.llm.base import GenRequest, LLMClient, LLMUnavailable, Msg
from app.agents.rules import R7_CODES, RULE_MESSAGES, RULES_VERSION, Hit, Section, check_rules
from app.agents.style import STYLE_VERSION, StyleCheck, style_message
from app.core.models import CoreModel, NarrativeInput

JUDGE_PROMPT_VER = "judge-v1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{JUDGE_PROMPT_VER}.txt"

R7_MESSAGES: dict[str, str] = {
    "UNSUPPORTED": "근거에 없는 내용을 말했습니다. 인용한 근거에서 나오는 말만 쓰세요.",
    "WRONG_STATUS": "근거의 상태와 어긋나게 말했습니다. 상태에 맞게 다시 쓰세요.",
    "OVERPROMISE": "받을 것처럼 부풀렸습니다. '해당될 수 있습니다'처럼 조심스럽게 쓰세요.",
}
_ORDINALS = {1: "첫째", 2: "둘째", 3: "셋째", 4: "넷째", 5: "다섯째", 6: "여섯째", 7: "일곱째", 8: "여덟째"}
_SID_BY_ORDINAL = {w: n for n, w in _ORDINALS.items()}
_INSTRUCTION = "아래 지적을 고쳐, 같은 형식(JSON)으로 이 구획을 다시 쓰세요."


class Feedback(CoreModel):
    """재생성 지시문. 숫자 없음: 사유 설명은 고정 문장, 문장 위치는 한글 서수."""
    section: str
    codes: tuple[str, ...]
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join((_INSTRUCTION, *self.lines))


class ReviewOutcome(CoreModel):
    final: Section
    source: Literal["ai_pass", "template"]
    attempts: int


class ReviewLog(Protocol):
    def write(self, entry: dict[str, Any]) -> None: ...


class MemoryReviewLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def write(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


class FileReviewLog:
    """logs/review/YYYY-MM-DD.jsonl 에 한 줄씩 덧붙인다. 날짜는 시계가 아니라 생성자의 as_of."""

    def __init__(self, as_of: date, log_dir: Path = Path("logs") / "review") -> None:
        self.path = log_dir / f"{as_of.isoformat()}.jsonl"

    def write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _where(sid: int) -> str:
    return "구획 전체" if sid == 0 else f"{_ORDINALS.get(sid, '뒤쪽')} 문장"


def _message(code: str, style: bool) -> str:
    if style and (msg := style_message(code)):      # 해요체 판(narrate-v3~)이면 말투 지적과 해요체로 바꾼 권고 문구
        return msg
    return RULE_MESSAGES.get(code) or R7_MESSAGES[code]


def build_feedback(kind: str, hits: list[tuple[str, int]], style: bool = False) -> Feedback:
    """(규칙 코드, sid) 목록 → 지시문. span은 받지 않는다. style=True면 말투 지적(STYLE_*)도 문구가 있고, 권고 문구가 해요체다."""
    by_sid: dict[int, list[str]] = {}
    for code, sid in hits:
        if code not in by_sid.setdefault(sid, []):
            by_sid[sid].append(code)
    lines = tuple(f"{_where(sid)}: " + " ".join(_message(c, style) for c in codes)
                  for sid, codes in sorted(by_sid.items()))
    return Feedback(section=kind, codes=tuple(dict.fromkeys(c for c, _ in hits)), lines=lines)


# --- 판정(R7) --------------------------------------------------------------------------------

_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"enum": ["PASS", "REJECT"]},
                   "reason_code": {"enum": [*sorted(R7_CODES), None]},
                   "문장": {"enum": list(_ORDINALS.values())}},
    "required": ["verdict", "reason_code"], "additionalProperties": False,
}


def parse_verdict(text: str | None, n_sentences: int | None = None) -> tuple[str, str | None, int] | None:
    """엄격히 읽는다. (verdict, reason_code, sid) 또는 깨졌으면 None. 문장 순서는 한글 서수로 받고, 없으면 sid 0(구획 전체).
    값이 문자열이 아니거나 서수가 문장 수(n_sentences)를 넘으면 깨진 판정이다."""
    try:
        obj = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(obj, dict) or not {"verdict", "reason_code"} <= obj.keys() \
            or not obj.keys() <= {"verdict", "reason_code", "문장"}:
        return None
    verdict, code = obj["verdict"], obj["reason_code"]
    ordinal = obj.get("문장")
    if not isinstance(verdict, str) or not (code is None or isinstance(code, str)):
        return None
    if ordinal is not None and (not isinstance(ordinal, str) or ordinal not in _SID_BY_ORDINAL):
        return None
    sid = _SID_BY_ORDINAL[ordinal] if ordinal is not None else 0
    if n_sentences is not None and sid > n_sentences:
        return None
    if verdict == "PASS" and code is None and sid == 0:
        return "PASS", None, 0
    if verdict == "REJECT" and code in R7_CODES:
        return "REJECT", code, sid
    return None


def _judge(judge: LLMClient, section: Section, ctx: NarrativeInput) -> tuple[dict[str, Any], tuple[str, int] | None]:
    """판정 한 번. (로그용 judge 항목, 반려 시 (코드, sid))."""
    body = {"items": [i.model_dump(mode="json") for i in ctx.items],
            "sentences": [{"문장": _ORDINALS.get(s.sid, "뒤쪽"), "text": s.text, "cites": list(s.cites or ())} for s in section.sentences]}
    req = GenRequest(purpose="judge", system=_PROMPT_PATH.read_text(encoding="utf-8"),
                     messages=(Msg(role="user", text=json.dumps(body, ensure_ascii=False)),),
                     response_schema=_VERDICT_SCHEMA, section=section.section)
    try:
        res = judge.generate(req)
    except LLMUnavailable as e:
        return {"skipped": True, "reason": "판정 생략", "unavailable": e.reason}, None
    parsed = parse_verdict(res.text, len(section.sentences))
    base = {"prompt_ver": JUDGE_PROMPT_VER, "provider": res.provider, "model": res.model}
    if parsed is None:
        return {**base, "skipped": True, "reason": "판정 생략", "malformed": True}, None
    verdict, code, sid = parsed
    if verdict == "PASS":
        return {**base, "skipped": False, "verdict": "PASS"}, None
    return {**base, "skipped": False, "verdict": "REJECT", "reason_code": code, "sid": sid}, (code or "", sid)


# --- 루프 ------------------------------------------------------------------------------------

def review_section(candidate: Section, ctx: NarrativeInput, sheet_ids: frozenset[str], judge: LLMClient | None,
                   regen: Callable[[Feedback], Section], log: ReviewLog, max_regen: int = 2,
                   style: StyleCheck | None = None) -> ReviewOutcome:
    """style: 말투 검사(app.agents.style.style_check_for). 주면 규칙 R1~R6 뒤에 걸고(해요체·행정 말·가실 곳 순서) 로그에 style_ver를 남긴다."""
    attempts = 0
    current = candidate
    while True:
        attempts += 1
        hits: list[Hit] = check_rules(current, ctx, sheet_ids)
        if style is not None:
            hits = sorted([*hits, *style(current)], key=lambda h: h.sid)       # 안정 정렬: 같은 sid 안에서는 규칙, 말투 차례
        r7: tuple[str, int] | None = None
        if hits:
            judge_log: dict[str, Any] = {"skipped": True, "reason": "규칙 단계에서 반려"}
        elif judge is None:
            judge_log = {"skipped": True, "reason": "판정기 없음"}
        else:
            judge_log, r7 = _judge(judge, current, ctx)
        pairs = [(h.rule, h.sid) for h in hits] + ([r7] if r7 else [])
        fb = build_feedback(current.section, pairs, style=style is not None) if pairs else None
        log.write({"section": current.section, "attempt": attempts, "rules_ver": RULES_VERSION,
                   **({"style_ver": STYLE_VERSION} if style is not None else {}),
                   "sentences": len(current.sentences),
                   "checks": [{"rule": c, "sid": s} for c, s in pairs], "judge": judge_log,
                   "verdict": "REJECT" if fb else "PASS", "feedback": list(fb.lines) if fb else []})
        if fb is None:
            return ReviewOutcome(final=current, source="ai_pass", attempts=attempts)
        if attempts > max_regen:
            break
        try:
            current = regen(fb)
        except LLMUnavailable as e:
            log.write({"section": candidate.section, "attempt": attempts, "rules_ver": RULES_VERSION,
                       "checks": [], "judge": None, "verdict": "REGEN_UNAVAILABLE", "regen_unavailable": e.reason})
            break
    final = template_for(candidate.section, ctx)
    log.write({"section": candidate.section, "attempt": attempts, "rules_ver": RULES_VERSION,
               "checks": [], "judge": None, "verdict": "TEMPLATE", "reason": "기본 문장으로 대체"})
    return ReviewOutcome(final=final, source="template", attempts=attempts)
