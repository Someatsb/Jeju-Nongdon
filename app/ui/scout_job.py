"""직원 메뉴 "공고 찾아보기" 뒤 작업(에이전트 강화 설계서 2절·3절).

단추를 누르면 뒤 작업 하나가 명령줄과 같은 길(app.cli.scout_run: 게시판 훑기 -> 고른 글 읽기 -> 원문 대조 -> 목록 올리기)을 돈다.
화면은 이 객체의 상태(snapshot)를 2~3초마다 받아 보인다. 이 파일은 상태를 담고 보고서를 화면 모양으로 옮기기만 한다.

- 한 번에 하나만 돈다. 이미 도는 중이면 새로 시작하지 않는다(start 가 도는 일을 그대로 돌려준다).
  뒤 작업이 멈춰 돌아오지 않을 때를 위해 RUN_MAX_S 가 지나면 도는 중이어도 새로 시작할 수 있다(옛 일의 결과는 옛 객체에만 쓴다).
- 하루 호출 한도·예산은 명령줄과 같다: 앱이 가진 AI 클라이언트(Guard)를 그대로 쓰고, 한도·요청 수·시간 한도는 run_scout·BoardClient 가 센다.
- 인터넷 판(limits 를 주면): 끝난 뒤 쉬는 시간 동안, AI 가 없거나 오늘 한도를 다 썼을 때는 새로 시작하지 않고 ScoutRefused(쉬운 말 한 줄)를 올린다.
  도는 중이면 이미 도는 일을 돌려준다(겹쳐 돌지 않는다).
- 재생 모드: data/replay/S1.json 녹화와 boards 고정본으로 돈다. 올리는 곳은 임시 폴더라 실제 data/catalog·data/inbox 는 바뀌지 않는다.
- 판정·금액·날짜는 여기서 만들지 않는다. 보고서의 글은 모두 공고 에이전트가 원문과 대조한 것이다.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from app import cli
from app.agents.llm.base import LLMClient
from app.agents.llm.recording import ReplayClient, load_recording
from app.agents.scout import NOT_CHOSEN, unavailable_text
from app.catalog.links import is_official_url
from app.config import APP_ROOT
from app.data_layer.notice_board import fixture_hash, fixture_http
from app.data_layer.notice_url import Http

log = logging.getLogger(__name__)

RUN_MAX_S = 900.0
REPLAY_PACE_S = 0.4
REPLAY_NOTE = "저장해 둔 실행 기록을 다시 보여 주는 것이에요. 실제 게시판과 AI는 쓰지 않았고, 올린 공고도 임시 폴더에만 있어서 지원 전체 보기는 바뀌지 않아요."
NOT_CHOSEN_TEXT = "농가 지원 공고가 아니라고 보고 넘어갔어요"
BROKEN = "찾는 중에 예상하지 못한 문제가 생겼어요. 잠시 뒤 다시 눌러 보고, 계속되면 담당자에게 알려 주세요."
FIXTURE_CHANGED = "저장해 둔 게시판 고정본이 바뀌었어요. 저장해 둔 실행 기록(S1)과 맞지 않아 시연을 멈췄어요. 담당자가 S1을 다시 녹화해야 해요."
NO_REPLAY = "재생할 저장 기록(data/replay/S1.json과 boards 폴더)이 없어요. 담당자에게 알려 주세요."
NO_BOARDS = "게시판에 연결하지 못했어요. 인터넷 연결을 확인하고 잠시 뒤 다시 눌러 보세요."
CAP_LINE = "오늘은 AI 사용량이 다 찼어요. 내일 다시 해 주세요."
NO_AI_LINE = "AI 키가 설정되지 않아 지금은 공고를 찾아볼 수 없어요."
NOT_ADDED = {"원문 대조": "원문 대조 실패로 안 올림", "이미 있는": "이미 있는 사업이라 안 올림"}


class ScoutRefused(Exception):
    """인터넷 판에서 지금은 시작하지 않는다(.line 은 화면에 그대로 보이는 쉬운 말)."""

    def __init__(self, line: str) -> None:
        super().__init__(line)
        self.line = line


class ScoutLimits:
    """인터넷 판의 찾아보기 제한(요금): 끝난 뒤 cooldown_s 초 쉬고, AI 가 없거나 오늘 한도를 다 썼으면 시작하지 않는다."""

    def __init__(self, *, cooldown_s: float, has_ai: Callable[[], bool], exhausted: Callable[[], bool]) -> None:
        self.cooldown_s, self.has_ai, self.exhausted = cooldown_s, has_ai, exhausted

    def refusal(self, since_finish: float | None) -> str | None:
        if not self.has_ai():
            return NO_AI_LINE
        if self.exhausted():
            return CAP_LINE
        if since_finish is not None and since_finish < self.cooldown_s:
            left = max(1, -int(-(self.cooldown_s - since_finish) // 60))      # 올림, 최소 1분
            return f"조금 전에 찾아봤어요. {left}분 뒤에 다시 해 주세요."
        return None


class ScoutJob:
    """찾아오기 한 판의 상태. state: run -> done | failed. 먼저 정해진 쪽이 이긴다."""

    def __init__(self, replay: bool) -> None:
        self.replay = replay
        self.state = "run"
        self.stage = "게시판 목록을 읽는 중"
        self.stages: list[str] = [self.stage]
        self.seen = 0
        self.picked = 0
        self.read_i = 0
        self.read_total = 0
        self.t0 = time.monotonic()
        self.elapsed = 0.0
        self.data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def set(self, stage: str | None = None, **kw: int) -> None:
        with self._lock:
            if self.state != "run":
                return
            for k, v in kw.items():
                setattr(self, k, v)
            if stage and stage != self.stage:
                self.stage = stage
                self.stages.append(stage)

    def finish(self, state: str, data: dict[str, Any]) -> None:
        with self._lock:
            if self.state != "run":
                return
            self.elapsed = time.monotonic() - self.t0
            self.data, self.state = data, state
            self.stage = "끝났어요" if state == "done" else "끝내지 못했어요"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {"state": self.state, "stage": self.stage, "seen": self.seen, "picked": self.picked,
                                   "read_i": self.read_i, "read_total": self.read_total, "replay": self.replay,
                                   "elapsed_s": round(self.elapsed if self.state != "run" else time.monotonic() - self.t0)}
            return out


class ScoutRunner:
    """앱에 하나(app.state.scout). 필드는 시험이 바꿔 끼운다(root·http·sleep·replay_dir·pace_s)."""

    def __init__(self, *, replay: bool, as_of: date, llm: LLMClient | None = None, root: Path = APP_ROOT,
                 replay_dir: Path | None = None, http: Http | None = None,
                 sleep: Callable[[float], None] | None = None, catalog_dir: Path | None = None,
                 limits: ScoutLimits | None = None) -> None:
        self.limits = limits                 # 인터넷 판만 둔다(PC 설치본은 None: 제한 없음)
        self.finished_at: float | None = None
        self.replay = replay
        self.as_of = as_of
        self.llm = llm
        self.root = Path(root)
        self.catalog_dir = Path(catalog_dir) if catalog_dir else None     # None 이면 root/data/catalog. 서버의 --catalog-dir 설정을 따른다
        self.replay_dir = Path(replay_dir) if replay_dir else self.root / "data" / "replay"
        self.http = http
        self.sleep = sleep
        self.pace_s = REPLAY_PACE_S if replay else 0.0
        self.job: ScoutJob | None = None
        self._lock = threading.Lock()

    # --- 시작 ----------------------------------------------------------------------------------

    def start(self) -> tuple[ScoutJob, bool]:
        """(일, 새로 시작했는지). 이미 도는 중이면 새로 시작하지 않고 그 일을 돌려준다."""
        with self._lock:
            j = self.job
            if j is not None and j.state == "run" and time.monotonic() - j.t0 < RUN_MAX_S:
                return j, False
            if self.limits is not None:
                since = None if self.finished_at is None else time.monotonic() - self.finished_at
                line = self.limits.refusal(since)
                if line:
                    raise ScoutRefused(line)
            j = self.job = ScoutJob(self.replay)
            threading.Thread(target=self._work, args=(j,), daemon=True, name="scout-job").start()
            return j, True

    def _work(self, job: ScoutJob) -> None:
        try:
            data = self._replay(job) if self.replay else self._real(job)
            if self.limits is not None and data.get("unavailable") == "DAILY_CAP":
                data["trouble"], data["fatal"] = [CAP_LINE], True
            job.finish("done", view(data, job))
        except Exception:
            log.exception("공고 찾아보기 중 오류")
            job.finish("failed", {"replay": self.replay, "trouble": [BROKEN], "fatal": True, "picks": [], "skips": [], "boards": []})
        finally:
            self.finished_at = time.monotonic()      # 쉬는 시간은 끝난 때부터 센다(성공·실패 모두)

    # --- 진행 표시 -----------------------------------------------------------------------------

    def _progress(self, job: ScoutJob) -> Callable[..., None]:
        def tick(stage: str, **info: Any) -> None:
            if stage == "scout":
                tools, last = info["tools"], info["last"]
                job.set("게시판 목록을 읽는 중" if (not tools.shown or last == "list_board") else "공고를 고르는 중",
                        seen=sum(s.seen for s in tools.stats.values()), picked=len(tools.picks))
            elif stage == "read":
                job.set(f"고른 공고 {info['total']}건 가운데 {info['n']}번째를 읽는 중", read_i=info["n"], read_total=info["total"])
            elif stage == "verify":
                job.set("원문과 맞춰 보는 중")
            elif stage == "write":
                job.set("보고서를 정리하는 중")
            if self.pace_s:
                time.sleep(self.pace_s)      # 시연 재생은 빨라서 진행 화면이 안 보이므로 천천히 보여 준다
        return tick

    # --- 실제 ----------------------------------------------------------------------------------

    def _real(self, job: ScoutJob) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("AI 클라이언트가 없습니다")
        stamp = datetime.combine(self.as_of, datetime.now().time().replace(microsecond=0))
        data, out, _ = cli.scout_run(self.root, self.llm, self.as_of, stamp, self.http, self.sleep, progress=self._progress(job),
                                  catalog_dir=self.catalog_dir)
        outcomes(data, self.root, links=True, catalog_dir=self.catalog_dir)
        data["inbox_id"] = out.name
        return data

    # --- 시연 재생 -----------------------------------------------------------------------------

    def _replay(self, job: ScoutJob) -> dict[str, Any]:
        rec_path, boards = self.replay_dir / "S1.json", self.replay_dir / "boards"
        base = {"replay": True, "picks": [], "skips": [], "boards": [], "fatal": True}
        if not rec_path.is_file() or not (boards / "index.json").is_file():
            return {**base, "trouble": [NO_REPLAY]}
        rec = load_recording(rec_path)
        if fixture_hash(boards) != rec.input_hash:
            return {**base, "trouble": [FIXTURE_CHANGED]}
        read_date = date.fromisoformat(rec.as_of)
        with tempfile.TemporaryDirectory() as tmp:        # 올리는 곳은 임시 폴더: 실제 data/catalog·data/inbox 는 건드리지 않는다
            work = Path(tmp)
            shutil.copytree(self.root / "data" / "tables", work / "data" / "tables")
            stamp = datetime.combine(read_date, datetime.now().time().replace(microsecond=0))
            data, _, _ = cli.scout_run(work, ReplayClient(rec), read_date, stamp, self.http or fixture_http(boards),
                                       self.sleep or (lambda s: None), progress=self._progress(job))
            outcomes(data, work, links=False)
        data["replay"] = True
        return data


# --- 보고서를 화면 모양으로 ------------------------------------------------------------------------

def _record(root: Path, filename: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    try:
        return json.loads(((Path(catalog_dir) if catalog_dir else root / "data" / "catalog") / "notices" / filename).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def outcomes(data: dict[str, Any], root: Path, *, links: bool, catalog_dir: Path | None = None) -> None:
    """고른 글마다 읽기 결과를 한 가지로 정해 data["picks"][i]["outcome"]·"outcome_label"·"details"·"links" 에 적는다.
    올린 사업이 표의 같은 제도(table_key)와 겹치면 지원 전체 보기에서 표의 것만 보이므로 '이미 있는 사업'으로 센다."""
    for p in data["picks"]:
        listed, dup, details, found = [], [], [], []
        if p.get("error"):
            code, label = "unread", "읽지 못함"
            details.append(p["error"])
        elif p.get("note") and not p.get("published") and not p.get("decision"):
            code, label = "unread", "읽지 않음"
            details.append(p["note"])
        else:
            for fn in p.get("published", []):
                rec = _record(root, fn, catalog_dir)
                name = rec.get("name") or fn.removesuffix(".json")
                (dup if rec.get("table_key") else listed).append(name)
                if links and not rec.get("table_key"):
                    found.append({"name": name, "key": "new-" + fn.removesuffix(".json")})
            why = [w for w in p.get("not_published", [])]
            if listed:
                code, label = "listed", "목록에 올림"
                details.append("올린 공고: " + ", ".join(listed))
                if dup:
                    details.append("표의 지원과 겹쳐 따로 보이지 않는 사업: " + ", ".join(dup))
                details += p.get("upgraded", [])
            elif dup:
                code, label = "duplicate", "이미 있는 사업이라 안 올림"
                details.append("표에 이미 있는 지원과 같은 사업이에요: " + ", ".join(dup))
            elif any("이미 목록에 있는 사업" in w for w in why):         # 주소는 다르지만 이름이 같은 사업(publish 가 막은 것)
                code, label = "duplicate", "이미 있는 사업이라 안 올림"
            elif any("원문" in w or "이름표" in w for w in why):
                code, label = "check_failed", "원문 대조 실패로 안 올림"
            else:
                code, label = "not_listed", "올리지 않음"
            details += why
        if p.get("decision_label"):
            details.insert(0, "공고 읽기 결정: " + p["decision_label"])
        p.update(outcome=code, outcome_label=label, details=details, links=found)


def _fmt_secs(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}분 {s % 60}초" if s >= 60 else f"{s}초"


def trouble(data: dict[str, Any]) -> tuple[list[str], bool]:
    """(쉬운 말 까닭들, 아무것도 못 했는지)."""
    out: list[str] = []
    boards = data.get("boards", [])
    code = data.get("unavailable") or ""
    fatal = False
    if code:
        fatal = True
        out.append(f"{unavailable_text(code)} 공고를 찾지 못했어요." +
                   (" keys.bat 으로 열쇠를 넣은 뒤 다시 눌러 주세요." if code == "NO_KEY" else " 잠시 뒤 다시 눌러 보세요."))
    elif boards and any(b.get("error") for b in boards) and not any(b.get("pages") for b in boards):
        fatal = True
        out.append(NO_BOARDS)
    elif data.get("stop"):
        out.append(data["stop"])
    bad = [b["name"] for b in boards if b.get("error") and b.get("pages") is not None]
    if bad and not fatal:
        out.append("열지 못한 게시판이 있어요: " + ", ".join(bad))
    for limit in data.get("limits", []):
        out.append(f"한도에 닿았어요: {limit}")
    return out, fatal


def view(data: dict[str, Any], job: ScoutJob) -> dict[str, Any]:
    """보고 화면이 그대로 쓰는 모양. 글은 모두 공식 게시판 글이고 링크는 공식 사이트 https 주소만 건다."""
    if "trouble" not in data:
        data["trouble"], data["fatal"] = trouble(data)
    boards = data.get("boards", [])
    data["seen_total"] = sum(b.get("seen", 0) for b in boards)
    data["elapsed_text"] = _fmt_secs(job.elapsed or (time.monotonic() - job.t0))
    for p in data.get("picks", []):
        p["href"] = p.get("url") if is_official_url(p.get("url") or "") else ""
    for s in data.get("skips", []):
        s["href"] = s.get("url") if is_official_url(s.get("url") or "") else ""
        if not s.get("reason") or s["reason"] == NOT_CHOSEN:
            s["reason"] = NOT_CHOSEN_TEXT
    return data
