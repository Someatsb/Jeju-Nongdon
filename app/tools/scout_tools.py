"""찾기 에이전트 도구 다섯 개(설계서 2-2): list_board · peek · pick · skip · finish.

ScoutTools 한 개가 한 번의 찾기를 맡는다. AI 에게는 주소를 주지 않고 줄 번호로만 다룬다. pick·peek·skip 은 list_board 가 돌려준
줄 번호만 받는다(AI 가 주소를 지어낼 수 없다). 게시판 글은 자료일 뿐이고, 도구가 할 수 있는 일은 목록 보기·고르기뿐이다.

- list_board: 최근 N일(기준일 as_of 에서) 글만 돌려준다. 이미 목록·받은 함에 있는 글은 "이미 읽음" 표시.
- peek: 본문 앞 스무 줄(notice_url 본문 뽑기). 한 번 찾기에 여덟 번까지. 같은 글을 다시 보는 것은 세지 않는다.
- pick: 여섯 건까지. 같은 제목의 글을 이미 골랐으면 거절한다(같은 사업은 하나만). 다만 먼저 고른 글이 읍면동 글이고 새 글이 부서(과·팀) 글이면 먼저 고른 글을 건너뛴 것으로 바꾸고 새 글을 고른다.
- 요청(목록·미리보기·본문)은 합쳐 마흔 번까지다. 고른 글의 본문을 받을 요청을 남겨 두려고 목록·미리보기는 그만큼 일찍 멈춘다
  (고를 몫 여섯 건을 늘 남기므로 실제로 쓸 수 있는 목록·미리보기 요청은 서른네 번이다).
도구 입력 모델의 독스트링·설명에는 숫자를 쓰지 않는다(registry.register 가 막는다).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, Field

from app.data_layer import notice_url
from app.data_layer.notice_board import (
    MAX_QUERY_CHARS,
    Board,
    BoardClient,
    KnownNotices,
    RequestLimit,
    is_dept_like,
    read_list,
)
from app.data_layer.notice_url import NoticeUrlError, UrlNotice
from app.tools.draft_checks import pii_labels, squash
from app.tools.models import ToolLog
from app.tools.registry import ToolError, ToolRegistry

MAX_PICKS = 6
MAX_PEEKS = 8
MAX_PEEK_LINES = 20
MAX_LINE_CHARS = 300
MAX_PAGE = 5
MAX_REASON_CHARS = 200
MAX_SUMMARY_CHARS = 500      # 끝낼 때의 요약(직원 보고에만 보인다. AI 에게 다시 보내지 않으므로 글자 수를 넉넉히 둔다)
MAX_SKIP_ROWS = 40


@dataclass(frozen=True)
class ShownRow:
    no: int
    board: Board
    title: str
    posted: date | None
    dept: str
    url: str
    known: bool


@dataclass
class BoardStat:
    name: str
    pages: int = 0
    seen: int = 0              # AI 에게 보여 준 최근 글 수(겹치는 글은 한 번만)
    hidden_old: int = 0        # 기간 밖이라 보여 주지 않은 글 수
    undated: int = 0           # 날짜를 읽지 못해 보여 주지 않은 글 수(게시판 틀이 바뀌었을 수 있다)
    dropped: int = 0           # 주소가 맞지 않아 버린 글 수
    error: str = ""


# --- 도구 입력·출력 모델(독스트링·설명에 숫자 금지) ---------------------------------------------

class RowOut(BaseModel):
    row: int
    title: str
    posted: str
    dept: str
    already_read: bool
    decided: str = ""


class ListOut(BaseModel):
    rows: list[RowOut]
    hidden_old: int
    more_pages: bool
    note: str = ""


class PeekOut(BaseModel):
    row: int
    title: str
    posted: str
    dept: str
    lines: list[str]
    more_lines: bool


class DecideOut(BaseModel):
    ok: bool
    message: str
    picks_left: int


class FinishOut(BaseModel):
    ok: bool


class ListIn(BaseModel):
    """게시판 한 쪽의 글 목록을 본다. 기간 안의 글만 줄 번호와 함께 돌려준다. 이미 읽은 글은 표시가 붙는다. 검색어는 제목 검색이다."""

    board: str = Field(description="게시판 이름. 예를 들어 서귀포시 알림마당, 제주시 공지사항, 제주시 농수축산국 부서소식, 제주도청 농축산 소식")
    query: str | None = Field(default=None, description="제목에서 찾을 낱말. 비우면 최신 글을 그대로 본다")
    page: int = Field(default=1, ge=1, le=MAX_PAGE, description="볼 쪽. 앞쪽이 가장 최근 글이다")


class PeekIn(BaseModel):
    """제목만으로 알 수 없는 글의 본문 앞부분을 읽는다. 횟수에 상한이 있으니 꼭 필요할 때만 쓴다."""

    row: int = Field(description="list_board 가 돌려준 줄 번호")


class PickIn(BaseModel):
    """농가가 신청하는 지원사업 공고를 고른다. 고른 글은 이 도구가 아니라 뒤의 공고 읽기가 읽는다. 같은 사업은 하나만 고른다."""

    row: int = Field(description="list_board 가 돌려준 줄 번호")
    reason: str = Field(description="고른 이유 한 문장. 쉬운 말로 쓴다")


class SkipIn(BaseModel):
    """고르지 않는 글을 이유와 함께 알린다. 같은 이유의 글은 줄 번호를 여러 개 한꺼번에 줄 수 있다."""

    row: int | list[int] = Field(description="list_board 가 돌려준 줄 번호 하나, 또는 같은 이유로 건너뛸 줄 번호 목록")
    reason: str = Field(description="건너뛰는 이유 한 문장. 쉬운 말로 쓴다")


class FinishIn(BaseModel):
    """찾기를 끝낸다. 무엇을 보고 왜 그렇게 골랐는지 쉬운 말로 요약한다."""

    summary: str = Field(description="찾은 결과 요약 두세 문장")


def _clip(text: str, limit: int) -> str:
    """limit 글자를 넘으면 마지막 문장 끝(. ! ?)에서 끊고 " …"를 붙인다. 문장 끝이 없으면 낱말 끝에서 끊는다(낱말 가운데서 자르지 않는다)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [i for i, ch in enumerate(cut) if ch in ".!?。"]
    if ends and ends[-1] + 1 >= limit // 3:
        return cut[: ends[-1] + 1].rstrip() + " …"
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip() + " …"


def _plain(text: str, what: str, clip_to: int | None = None) -> str:
    text = " ".join(text.split())
    if not text:
        raise ToolError(f"{what}을 비워 둘 수 없습니다. 쉬운 말로 한 문장 적어 주세요")
    if pii_labels(text):
        raise ToolError(f"{what}에 개인정보(전화번호·주민번호·메일)가 있어 받지 않았습니다. 지우고 다시 적어 주세요")
    return text[:MAX_REASON_CHARS] if clip_to is None else _clip(text, clip_to)    # 이유는 글자 수로 자르고, 요약은 문장 끝에서 끊는다


class ScoutTools:
    def __init__(self, boards: tuple[Board, ...], client: BoardClient, *, as_of: date, days: int = 30,
                 known: KnownNotices | None = None, log: ToolLog | None = None) -> None:
        self.boards = boards
        self.client = client
        self.as_of = as_of
        self.days = days
        self.cutoff = as_of - timedelta(days=days)
        self.known = known
        self.log = log or ToolLog()
        self.shown: dict[int, ShownRow] = {}
        self._by_url: dict[str, int] = {}
        self.picks: dict[int, str] = {}
        self.skips: dict[int, str] = {}
        self.stats: dict[str, BoardStat] = {b.key: BoardStat(b.name) for b in boards}
        self.fetched: dict[str, UrlNotice] = {}
        self.peeks = 0
        self.summary = ""
        self.finished = False
        self.limits: list[str] = []

    # --- 도우미 -----------------------------------------------------------------------------

    def _limit(self, text: str) -> None:
        if text not in self.limits:
            self.limits.append(text)

    def _budget(self) -> None:
        """목록·미리보기 한 번을 더 받아도 고를 글의 본문을 받을 요청이 남는지 본다."""
        if self.client.left - 1 < MAX_PICKS - len(self.picks):
            self._limit(f"요청 {self.client.max_requests}번 중 고른 글의 본문을 받을 몫만 남아 더 보지 않았습니다")
            raise ToolError("요청 한도에 가까워 더 볼 수 없습니다. 지금까지 본 글에서 고른 뒤 끝내기를 부르세요")

    def _row(self, no: int) -> ShownRow:
        row = self.shown.get(no)
        if row is None:
            raise ToolError(f"줄 번호 {no}은 list_board 가 돌려준 적이 없습니다. 먼저 list_board 로 글 목록을 보세요")
        return row

    def _status(self, no: int) -> str:
        return "골랐음" if no in self.picks else "건너뜀" if no in self.skips else ""

    # --- 도구 -------------------------------------------------------------------------------

    def list_board(self, board: str, query: str | None = None, page: int = 1) -> ListOut:
        b = next((x for x in self.boards if x.key == board or x.name.replace(" ", "") == board.replace(" ", "")), None)
        if b is None:
            raise ToolError("그 게시판은 이번에 볼 수 없습니다. 볼 수 있는 곳: " + ", ".join(x.name for x in self.boards))
        q = " ".join((query or "").split())
        if len(q) > MAX_QUERY_CHARS or pii_labels(q):
            raise ToolError("검색어는 짧은 낱말 하나로 적어 주세요")
        self._budget()
        stat = self.stats[b.key]
        try:
            rows, dropped = read_list(self.client, b, q, page)
        except RequestLimit:
            self._limit(f"요청 {self.client.max_requests}번을 다 써서 더 보지 않았습니다")
            raise ToolError("요청 한도를 다 썼습니다. 지금까지 본 글에서 고른 뒤 끝내기를 부르세요") from None
        except NoticeUrlError as e:
            stat.error = str(e)
            raise ToolError(f"{b.name} 게시판을 열지 못했습니다({e}). 다른 게시판은 계속 볼 수 있습니다") from None
        stat.pages += 1
        stat.dropped += dropped
        shown: list[RowOut] = []
        hidden = 0
        for r in rows:
            if r.posted is None:
                stat.undated += 1
                continue
            if r.posted < self.cutoff:
                hidden += 1
                continue
            no = self._by_url.get(r.url)
            if no is None:
                no = len(self.shown) + 1
                self._by_url[r.url] = no
                self.shown[no] = ShownRow(no, b, r.title, r.posted, r.dept, r.url, bool(self.known and r.url in self.known))
                stat.seen += 1
            row = self.shown[no]
            shown.append(RowOut(row=no, title=row.title, posted=r.posted.isoformat(), dept=row.dept,
                                already_read=row.known, decided=self._status(no)))
        stat.hidden_old += hidden
        more = bool(rows) and rows[-1].posted is not None and rows[-1].posted >= self.cutoff
        note = ""
        if not shown and rows and all(r.posted is None for r in rows):
            note = "글 날짜를 읽지 못했습니다. 게시판 모양이 달라졌을 수 있어 이 게시판은 직원이 확인해야 합니다"
            stat.error = stat.error or note
        elif not shown:
            newest = max((r.posted for r in rows if r.posted), default=None)
            note = f"최근 {self.days}일 안에 올라온 글이 없습니다" + (f"(가장 최근 글은 {newest.isoformat()})" if newest else "")
        return ListOut(rows=shown, hidden_old=hidden, more_pages=more, note=note)

    def peek(self, row: int) -> PeekOut:
        r = self._row(row)
        if r.known:
            raise ToolError("이미 읽은 공고라 볼 필요가 없습니다")
        got = self.fetched.get(r.url)
        if got is None:
            if self.peeks >= MAX_PEEKS:
                self._limit(f"미리보기 {MAX_PEEKS}번을 다 써서 더 보지 않았습니다")
                raise ToolError("미리보기는 여덟 번까지입니다. 제목으로 가려 고르세요")
            self._budget()
            self.peeks += 1
            try:
                got = notice_url.fetch_notice(r.url, http=self.client.fetch)
            except RequestLimit:
                self._limit(f"요청 {self.client.max_requests}번을 다 써서 더 보지 않았습니다")
                raise ToolError("요청 한도를 다 썼습니다") from None
            except NoticeUrlError as e:
                raise ToolError(f"글을 읽지 못했습니다({e}). 제목으로 정하세요") from None
            self.fetched[r.url] = got
        body = got.doc.text.split("[본문]\n", 1)[-1].split("\n[첨부 파일]", 1)[0].splitlines()
        body = [ln[:MAX_LINE_CHARS] for ln in body if ln.strip() and not pii_labels(ln)]
        return PeekOut(row=row, title=r.title, posted=r.posted.isoformat() if r.posted else "", dept=r.dept,
                       lines=body[:MAX_PEEK_LINES], more_lines=len(body) > MAX_PEEK_LINES)

    def pick(self, row: int, reason: str) -> DecideOut:
        r = self._row(row)
        text = _plain(reason, "이유")
        if row in self.picks or row in self.skips:
            raise ToolError("이미 정한 줄입니다")
        if r.known:
            raise ToolError("이미 읽은 공고입니다. 건너뛰기로 알리세요")
        if len(self.picks) >= MAX_PICKS:
            self._limit(f"고르기 {MAX_PICKS}건을 다 채워 더 고르지 않았습니다")
            raise ToolError("고르기는 여섯 건까지입니다. 끝내기를 부르세요")
        twin = next((n for n in self.picks if squash(self.shown[n].title) == squash(r.title)), None)
        if twin is not None:
            if is_dept_like(r.dept) and not is_dept_like(self.shown[twin].dept):
                del self.picks[twin]       # 같은 사업의 부서 글이 나타났으니 먼저 고른 읍면동 글을 부서 글로 바꾼다
                self.skips[twin] = f"같은 사업의 부서 글(줄 {row})로 바꿨습니다(먼저 고른 읍면동 글은 뺍니다)"
            else:
                raise ToolError(f"줄 {twin}과 제목이 같아 같은 사업으로 보입니다. 같은 사업은 하나만 고릅니다(부서 글이 있으면 그쪽으로)")
        self.picks[row] = text
        return DecideOut(ok=True, message="골랐습니다", picks_left=MAX_PICKS - len(self.picks))

    def skip(self, row: int | list[int], reason: str) -> DecideOut:
        rows = [row] if isinstance(row, int) else list(dict.fromkeys(row))
        if not rows or len(rows) > MAX_SKIP_ROWS:
            raise ToolError(f"줄 번호는 하나 이상 {MAX_SKIP_ROWS}개까지 줄 수 있습니다")
        for n in rows:
            self._row(n)
        text = _plain(reason, "이유")
        done = 0
        for n in rows:
            if n not in self.picks and n not in self.skips:
                self.skips[n] = text
                done += 1
        return DecideOut(ok=True, message=f"{done}건을 건너뛰기로 적었습니다", picks_left=MAX_PICKS - len(self.picks))

    def finish(self, summary: str) -> FinishOut:
        self.summary = _plain(summary, "요약", MAX_SUMMARY_CHARS)
        self.finished = True
        return FinishOut(ok=True)

    # --- 등록부 -----------------------------------------------------------------------------

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register("list_board", ListIn, ListOut, lambda a: self.list_board(a.board, a.query, a.page))
        reg.register("peek", PeekIn, PeekOut, lambda a: self.peek(a.row))
        reg.register("pick", PickIn, DecideOut, lambda a: self.pick(a.row, a.reason))
        reg.register("skip", SkipIn, DecideOut, lambda a: self.skip(a.row, a.reason))
        reg.register("finish", FinishIn, FinishOut, lambda a: self.finish(a.summary))
        return reg
