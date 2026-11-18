"""AI가 읽은 공고 맞춰 보기 뒤 작업(에이전트 강화 설계서 1절, 결과 v2 6절): 결과 화면 뒤에서 설명 글 만들기와 나란히 돈다.

- 상담(AiJob) 하나에 MatchJob 하나가 딸린다. 서로 기다리지 않는다: 결과 화면·종이는 맞춰 보기를 기다리지 않고,
  설명 글이 먼저 끝나도 맞춰 보기는 따로 끝난다(/counsel/ai 의 match.state 가 run -> done|none).
  답을 고치면 프로필이 바뀌어 새 AiJob(곧 새 MatchJob)이 생기므로 옛 결과는 섞이지 않는다. 뒤 작업이 이 객체에만 쓴다.
- 볼 공고: 지원 전체 보기 목록에 '새 공고'로 올라와 있고 신청이 끝나지 않은 것(app.catalog.pool). 없으면 AI 를 부르지 않는다.
- 실패·시간 초과·키 없음·공고 0건은 조용히 state "none"(이유 한 줄은 직원 칸 match.staff.note 에만). 한 번 정해진 상태는 바뀌지 않는다.
  AI 가 멈춰 돌아오지 않아도 MATCH_HARD_S 가 지나면 none 으로 끝내고, 늦게 돌아온 답은 버린다.
- 판정·인용 검사·금액·날짜는 app.agents.match 가 한다. 이 파일은 상태를 담고 화면용 JSON 모양으로 옮기기만 한다.
  어르신 칸(lines·more_names)에는 '맞을 수 있음'과 '알 수 없음'의 이름만 나가고 '안 맞음'은 직원 칸(staff)에만 있다.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import Request

from app.agents.llm.base import LLMClient
from app.agents.match import BUDGET_S, MatchItem, MatchReport, elder_view, run_match
from app.catalog.build import Entry
from app.catalog.notices import NoticeRecord
from app.catalog.pool import load_pool
from app.core.models import FactSheet, FarmProfile
from app.core.tables_models import Crop
from app.tools.match_tools import FIT, MAYBE_UNKNOWN, NOT_FIT
from app.tools.models import ToolLog
from app.ui.routes_supports import today_of

log = logging.getLogger(__name__)

MATCH_BUDGET_S = BUDGET_S          # 기다림 예산(설계서 4절): 요청이 이 안에 끝나지 않으면 맞춰 보기를 접는다
MATCH_MAX_PARALLEL = 2             # 동시에 도는 맞춰 보기 수
MATCH_CACHE_MAX = 32               # 담아 두는 결과 수(서버가 오래 떠 있어도 늘지 않는다)
MATCH_HARD_S = BUDGET_S + 10.0     # AI 가 멈춰 돌아오지 않을 때를 위한 마지막 한도
NOTE = "조건은 창구에서 확인하세요"
VERDICTS = (FIT, MAYBE_UNKNOWN, NOT_FIT)
NOT_USED = "AI가 읽은 공고 맞춰 보기를 쓰지 않았어요"
TOO_SLOW = "AI가 읽은 공고를 맞춰 보지 못했어요: 정해 둔 시간이 지나서 끝까지 마치지 못했어요"
BROKEN = "AI가 읽은 공고를 맞춰 보지 못했어요: 예상하지 못한 문제가 있어서 끝까지 마치지 못했어요"
NO_NEW = "새로 맞춰 볼 공고가 없어요(기간이 끝났거나 표에 이미 있는 제도예요)"

Matcher = Callable[[FarmProfile, FactSheet, Sequence[NoticeRecord]], MatchReport]


def make_matcher(llm: LLMClient, crops: Sequence[Crop], as_of) -> Matcher:
    """실제(또는 시험용) AI 로 도는 맞춰 보기. 호출마다 새 기록(ToolLog)을 만들어 여러 상담이 같이 돌아도 섞이지 않는다.

    자원을 아낀다: 같은 프로필 내용(계산 지문)과 같은 공고 묶음이면 AI 로 따진 결과를 다시 쓰고(답을 다시 확인해도 AI 를 또 부르지 않는다,
    같은 것이 동시에 오면 하나만 돌고 나머지는 그 결과를 기다린다), 동시에 도는 맞춰 보기는 MATCH_MAX_PARALLEL 개까지다.
    AI 로 따지지 못한 결과(source != "ai")는 담아 두지 않아 다음에 다시 시도한다."""
    cache: dict[tuple, MatchReport] = {}
    locks: dict[tuple, threading.Lock] = {}
    guard = threading.Lock()
    slots = threading.BoundedSemaphore(MATCH_MAX_PARALLEL)

    def run(profile: FarmProfile, fs: FactSheet, notices: Sequence[NoticeRecord]) -> MatchReport:
        key = (fs.fingerprint, tuple(sorted(n.key for n in notices))) if fs.fingerprint else None
        if key is None:
            with slots:
                return run_match(profile, fs, notices, crops, llm, ToolLog(), as_of=as_of, budget_s=MATCH_BUDGET_S)
        with guard:
            hit = cache.get(key)
            lock = locks.setdefault(key, threading.Lock())
        if hit is not None:
            return hit
        with lock:                       # 같은 것이 동시에 오면 하나만 돈다
            with guard:
                hit = cache.get(key)
            if hit is not None:
                return hit
            with slots:
                report = run_match(profile, fs, notices, crops, llm, ToolLog(), as_of=as_of, budget_s=MATCH_BUDGET_S)
            if report.source == "ai":
                with guard:
                    if len(cache) >= MATCH_CACHE_MAX:
                        cache.pop(next(iter(cache)))
                    cache[key] = report
            return report
    return run


def _where_text(e: Entry) -> str:
    """새 공고 줄의 '어디서' 글: 가실 곳(접수처·신청장소) 줄만. 공고를 낸 부서 이름은 가실 곳처럼 읽히므로 뺀다.
    가실 곳 줄이 하나도 없을 때만 '공고 낸 곳: 부서'를 보인다. 글은 지원 전체 보기 자료 그대로다."""
    places = [w for w in e.new_where if w not in (e.agency, f"공고 낸 곳: {e.agency}")]
    return " · ".join(places or e.new_where)


class MatchJob:
    """상담 하나의 맞춰 보기. state: "run"(도는 중) -> "done"(AI 가 따져 봄) | "none"(없음). 먼저 정해진 쪽이 이긴다."""

    def __init__(self) -> None:
        self.state = "run"
        self.report: MatchReport | None = None      # 정해졌을 때의 보고서(none 이어도 note 가 있을 수 있다)
        self.note = ""                              # 보고서가 없을 때 직원 칸에 보일 이유 한 줄
        self.candidates = 0
        self.entries: Mapping[str, Entry] = {}      # 공고 열쇠 -> 지원 전체 보기 항목(기간·가실 곳 글)
        self.done = threading.Event()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def settle(self, report: MatchReport | None = None, note: str = "") -> bool:
        """결과를 한 번만 정한다. 이미 정해졌으면 False(늦게 돌아온 답은 버린다)."""
        with self._lock:
            if self.state != "run":
                return False
            self.report, self.note = report, note
            self.state = "done" if report is not None and report.source == "ai" else "none"
            if self._timer is not None:
                self._timer.cancel()
            self.done.set()
            return True

    def view(self) -> dict[str, Any]:
        """/counsel/ai 의 match 칸(어르신 화면·종이가 쓴다). staff 는 개수와 한 줄뿐이다(source·note·candidates·left_out·counts).
        안 맞음 공고 이름·판정 근거(items, names)는 어르신 화면이 받는 응답에 싣지 않는다: 직원이 볼 내용 칸은 staff_view() 를 쓴다."""
        state, report = self.state, self.report
        if state != "done" or report is None:
            return {"state": state, "lines": [], "more_names": [], "note": NOTE,
                    "staff": self._staff_counts(self._staff(report if state == "none" else None, state))}
        shown = elder_view(report)
        return {"state": "done", "lines": [self._line(i) for i in shown.lines], "more_names": list(shown.more_names), "note": NOTE,
                "staff": self._staff_counts(self._staff(report, state))}

    def staff_view(self) -> dict[str, Any]:
        """직원이 볼 내용 칸 자료(서버 쪽에서만 쓴다): view()["staff"] 에 더해 names(판정별 이름)와 items(이름·판정·근거·확인 기록)."""
        return self._staff(self.report if self.state != "run" else None, self.state)

    def links(self) -> list[dict[str, str]]:
        """자세히 보기 "공고 원문" 상자에 더할 맞을 수 있는 새 공고(어르신 화면에 줄로 보이는 것) 중 공고 주소가 있는 것: [{key, title, url}]."""
        if self.state != "done" or self.report is None:
            return []
        out = []
        for item in elder_view(self.report).lines:
            e = self.entries.get(item.key)
            if e is not None and e.link is not None and e.link.url:
                out.append({"key": item.key, "title": item.name, "url": e.link.url})
        return out

    @staticmethod
    def _staff_counts(staff: dict[str, Any]) -> dict[str, Any]:
        return {k: staff[k] for k in ("source", "note", "candidates", "left_out", "counts")}

    def _line(self, item: MatchItem) -> dict[str, Any]:
        e = self.entries.get(item.key)
        return {"key": item.key, "name": item.name, "why": item.why,
                "period": e.window if e is not None else item.period,
                "where": _where_text(e) if e is not None else "",
                "ask": list(item.ask_lines)}

    def _staff(self, report: MatchReport | None, state: str) -> dict[str, Any]:
        items = report.items if report is not None else ()
        names = {v: [i.name for i in items if i.verdict == v] for v in VERDICTS}
        note = report.note if report is not None and report.note else (self.note or ("AI가 읽은 공고를 맞춰 보는 중이에요" if state == "run" else ""))
        return {"source": report.source if report is not None else ("run" if state == "run" else "none"),
                "note": note, "candidates": report.candidates if report is not None else self.candidates,
                "left_out": report.left_out if report is not None else 0,
                "counts": {v: len(names[v]) for v in VERDICTS}, "names": names,
                "items": [{"key": i.key, "name": i.name, "verdict": i.verdict, "why": i.why, "period": i.period,
                           "checks": [{"kind": c.kind, "quote": c.quote, "answer": c.answer} for c in i.checks]} for i in items]}


def none_view(note: str = NOT_USED) -> dict[str, Any]:
    """맞춰 보기를 할 수 없을 때(상담 바탕을 못 만든 경우 등)의 match 칸."""
    mj = MatchJob()
    mj.settle(note=note)
    return mj.view()


def pool_for(request: Request) -> list[tuple[NoticeRecord, Entry]]:
    """지원 전체 보기와 같은 기준일·자료로 고른 맞춰 볼 새 공고."""
    st = request.app.state
    return load_pool(st.cfg.catalog_dir, st.tables, today_of(request))


def launch(mj: MatchJob, matcher: Matcher | None, profile: FarmProfile, fs: FactSheet,
           pool: Sequence[tuple[NoticeRecord, Entry]]) -> None:
    """맞춰 보기를 뒤 스레드로 띄운다(기다리지 않는다). 아무 일도 없어도 mj 는 곧 none 으로 정해진다."""
    mj.entries = {n.key: e for n, e in pool}
    mj.candidates = len(pool)
    if matcher is None:
        mj.settle(note=NOT_USED)
        return
    if not pool:
        mj.settle(MatchReport(source="skipped", note=NO_NEW))
        return

    def work() -> None:
        try:
            report = matcher(profile, fs, [n for n, _ in pool])
        except Exception:
            log.exception("AI가 읽은 공고 맞춰 보기가 멈췄습니다. 없음으로 넘어갑니다")
            mj.settle(note=BROKEN)
            return
        mj.settle(report)

    mj._timer = threading.Timer(MATCH_HARD_S, mj.settle, kwargs={"note": TOO_SLOW})
    mj._timer.daemon = True
    mj._timer.start()
    threading.Thread(target=work, name="match-job", daemon=True).start()
