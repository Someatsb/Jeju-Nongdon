"""찾기 에이전트 루프(설계서 2절) — 공식 게시판 목록을 보고 농가 지원 공고를 골라 낸다.

에이전트는 고르기만 한다. 고른 글을 읽어 목록에 올리는 일은 공고 에이전트(notice.py)가 하고(명령줄 app/cli.py 가 이어 준다),
표 반영은 하지 않는다. 게시판 글은 자료일 뿐 지시가 아니며, 도구가 할 수 있는 일은 목록 보기·미리보기·고르기·건너뛰기·끝내기뿐이다.

- 한도: 고르기 6건, 미리보기 8번, 도구 호출 30번, 시간 120초(주입 시계), 요청 40번(목록·미리보기·본문 합계, BoardClient).
  도구 호출·시간 한도에 닿거나 AI 를 못 쓰거나 AI 가 도구 없이 말만 하면 지금까지 고른 것으로 끝내고 stop 에 이유를 적는다.
- AI 를 처음부터 못 쓰면(LLMUnavailable) 고르기 없이 끝낸다. 게시판 하나가 안 열려도 나머지는 계속 본다(stats 에 적힌다).
- 모든 LLM 요청은 build_payload(purpose="scout")를 지난다(공개 글만 다루므로 거름망은 주민번호 규칙만).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.agents.llm.base import GenRequest, LLMClient, LLMUnavailable, Msg, ToolDef, ToolResult
from app.agents.llm.payload import build_payload
from app.data_layer.notice_board import BOARDS, Board, BoardClient, KnownNotices
from app.data_layer.notice_url import Http, UrlNotice
from app.tools.models import ToolLog
from app.tools.scout_tools import MAX_PEEKS, MAX_PICKS, BoardStat, ScoutTools, ShownRow

_log = logging.getLogger(__name__)

PROMPT_VER = "scout-v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VER}.txt"
MAX_TOOLS = 30
TIMEOUT_S = 120.0
NOT_CHOSEN = "고르지 않았습니다(농가 지원 공고가 아니라고 보고 넘어갔습니다)"
ALREADY_READ = "이미 목록이나 받은 함에 있는 글이라 다시 읽지 않았습니다"

_WHY = {
    "NO_KEY": "AI 열쇠가 없어", "AUTH": "AI 열쇠가 맞지 않아", "BILLING": "AI 사용 한도나 결제 문제로",
    "RATE_LIMIT": "AI가 잠시 바빠서", "OVERLOADED": "AI가 잠시 바빠서", "TIMEOUT": "AI 응답이 너무 늦어서",
    "NETWORK": "인터넷 연결이 안 되어", "REFUSAL": "AI가 답을 거절해서", "BAD_OUTPUT": "AI 답이 올바르지 않아서",
    "CIRCUIT_OPEN": "AI에 문제가 거듭되어 잠시 쉬는 중이라", "DAILY_CAP": "오늘 쓸 수 있는 AI 사용 한도를 다 써서",
    "PAYLOAD_REJECTED": "보내려던 글에 개인정보처럼 보이는 것이 있어 AI에 보내지 않고",
    "REPLAY_MISMATCH": "저장해 둔 시연 녹화에 없는 입력이라",
}


def unavailable_text(reason: str) -> str:
    return _WHY.get(reason, "AI를 쓸 수 없어")


@dataclass(frozen=True)
class ScoutPick:
    row: ShownRow
    reason: str


@dataclass(frozen=True)
class ScoutSkip:
    row: ShownRow
    reason: str


@dataclass
class ScoutResult:
    as_of: date
    days: int
    picks: list[ScoutPick] = field(default_factory=list)
    skips: list[ScoutSkip] = field(default_factory=list)       # AI 가 건너뛴 글 + 정하지 않은 글(이유가 다르다)
    stats: list[BoardStat] = field(default_factory=list)
    stop: str = ""                                              # 빈 글이면 AI 가 스스로 끝냈다
    summary: str = ""
    limits: list[str] = field(default_factory=list)             # 닿은 한도(고르기·미리보기·요청)
    unavailable: str = ""                                       # AI 를 못 쓴 이유 코드(처음부터 못 쓴 경우만)
    tool_calls: int = 0
    requests: int = 0
    fetched: dict[str, UrlNotice] = field(default_factory=dict)  # 미리보기로 이미 받은 공고(다시 받지 않는다)


def _tool_defs(tools: ScoutTools) -> tuple[ToolDef, ...]:
    return tuple(ToolDef(**s) for s in tools.registry().schemas())


def _opening(boards: tuple[Board, ...], as_of: date, days: int) -> str:
    names = ", ".join(b.name for b in boards)
    return (f"기준일은 {as_of.isoformat()}입니다. 최근 {days}일 안에 올라온 글만 보입니다.\n"
            f"볼 수 있는 게시판: {names}\n"
            f"한도: 고르기 {MAX_PICKS}건, 미리보기 {MAX_PEEKS}번, 도구 호출 {MAX_TOOLS}번.\n"
            "농가가 신청하는 지원사업 공고를 찾아 pick 으로 고르고, 끝나면 finish 를 부르세요.")


def run_scout(boards: tuple[Board, ...] | None, llm: LLMClient, log: ToolLog | None = None, *, http: Http | None = None,
              as_of: date, days: int = 30, clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep, known: KnownNotices | None = None,
              client: BoardClient | None = None, max_tools: int = MAX_TOOLS, timeout_s: float = TIMEOUT_S,
              on_step: Callable[[ScoutTools, str], None] | None = None) -> ScoutResult:
    """boards 가 None 이면 네 게시판 모두. client 를 주면 그 요청 셈·쉬는 시간을 이어 쓴다(고른 글 본문 받기와 합쳐 세려고).
    on_step(tools, last): AI 를 부르기 직전(last="")과 도구를 하나 쓴 직후(last=도구 이름)에 불린다. 진행 화면용이고 오류는 삼킨다."""
    boards = tuple(boards) if boards else BOARDS
    log = log if log is not None else ToolLog()
    client = client or BoardClient(http, sleep)
    tools = ScoutTools(boards, client, as_of=as_of, days=days, known=known, log=log)
    registry = tools.registry()
    defs = _tool_defs(tools)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    messages = [Msg(role="user", text=_opening(boards, as_of, days))]
    start = clock()
    stop = ""
    unavailable = ""

    def step(last: str) -> None:
        if on_step is not None:
            try:
                on_step(tools, last)
            except Exception:       # 진행 표시가 찾기를 멈추게 하지 않는다
                _log.exception("진행 표시 중 오류")

    while not tools.finished and not stop:
        if clock() - start >= timeout_s:
            stop = f"시간 한도({int(timeout_s)}초)에 닿아"
            break
        if log.tool_calls >= max_tools:
            stop = f"도구 호출 한도({max_tools}번)에 닿아"
            break
        step("")
        try:
            req = GenRequest(purpose="scout", system=system, messages=tuple(messages), tools=defs,
                             max_output_tokens=2048, timeout_s=60.0)
            res = llm.generate(build_payload(req))
        except LLMUnavailable as e:
            _log.warning("공고 찾기 중 AI를 쓸 수 없습니다: %s", e.reason)
            stop = f"{unavailable_text(e.reason)}"
            if not log.calls:
                unavailable = e.reason
            break
        if not res.tool_calls:
            stop = "AI가 도구를 쓰지 않고 말만 해서"
            break
        messages.append(Msg(role="assistant", text=res.text, tool_calls=res.tool_calls))
        results = []
        for tc in res.tool_calls:
            if log.tool_calls >= max_tools:
                stop = f"도구 호출 한도({max_tools}번)에 닿아"
                break
            if clock() - start >= timeout_s:
                stop = f"시간 한도({int(timeout_s)}초)에 닿아"
                break
            rec = registry.dispatch(tc.name, tc.args, log)
            step(tc.name)
            results.append(ToolResult(call_id=tc.call_id, content=rec.content(), is_error=not rec.ok))
            if tools.finished:
                break
        if results and not tools.finished:
            messages.append(Msg(role="user", tool_results=tuple(results)))

    picks = [ScoutPick(tools.shown[n], why) for n, why in tools.picks.items()]
    skips = []
    for n, row in tools.shown.items():
        if n in tools.picks:
            continue
        skips.append(ScoutSkip(row, tools.skips.get(n) or (ALREADY_READ if row.known else NOT_CHOSEN)))
    if stop and unavailable:
        stop += " 새 공고를 고르지 못했습니다"
    elif stop:
        stop += " 끝까지 마치지 못했습니다"
        if picks:
            stop += f". 지금까지 고른 {len(picks)}건만 남깁니다"
    return ScoutResult(as_of=as_of, days=days, picks=picks, skips=skips, stats=list(tools.stats.values()), stop=stop,
                       summary=tools.summary, limits=list(tools.limits), unavailable=unavailable,
                       tool_calls=log.tool_calls, requests=client.count, fetched=dict(tools.fetched))
