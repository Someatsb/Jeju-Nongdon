"""공식 게시판 목록 읽기(찾기 에이전트의 눈). 게시판 글 목록을 받아 줄(BoardRow)로 만든다. 본문은 notice_url 이 읽는다.

- 보는 곳은 네 게시판뿐이다: 서귀포시 알림마당, 제주시 공지사항, 제주시 농수축산국 부서소식, 제주도청 농축산 소식.
  받을 수 있는 주소는 notice_url 의 허용 목록(ALLOWED_HOSTS)과 같다. 목록에서 뽑은 상세 주소도 notice_url.check_url 을 지나야 하고,
  게시판과 다른 사이트로 넘어가는 주소는 버린다(버린 수만 알린다).
- GET 만 쓴다. 로그인·쿠키 없음. 요청 사이에 1초 이상 쉰다(쉬는 함수는 밖에서 주입). 한 번 찾기에 요청은 40번까지이고
  목록·미리보기·본문 받기가 한 BoardClient 로 합쳐 센다.
- 표준 라이브러리만 쓴다. HTML 읽기·주소 검사·받기는 notice_url 것을 다시 쓴다. 시험은 http 인자로 저장해 둔 HTML 을 넘긴다.
- 작성 부서 칸에 사람 이름이 들어온 글이 있어(서귀포 일부) 부서 이름처럼 보이지 않는 값은 비운다.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app.data_layer.notice_url import Http, Node, NoticeUrlError, check_url, lines_of, parse_html, urlopen_bytes
from app.data_layer.notice_url import _decode as _decode_html

MAX_REQUESTS = 40
MIN_GAP_S = 1.0
JEJUSI_PAGE_SIZE = 30
MAX_QUERY_CHARS = 40
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class Board:
    key: str
    name: str
    url: str
    engine: str          # "act": 서귀포시·도청(act=view&seq=) / "mode": 제주시(mode=detail&notice_id=)


BOARDS: tuple[Board, ...] = (
    Board("seogwipo", "서귀포시 알림마당", "https://www.seogwipo.go.kr/info/news/notice.htm", "act"),
    Board("jejusi", "제주시 공지사항", "https://www.jejusi.go.kr/information/intro/news.do", "mode"),
    Board("jejusi_farm", "제주시 농수축산국 부서소식", "https://www.jejusi.go.kr/part/farm/intro/news.do", "mode"),
    Board("jeju_farm", "제주도청 농축산 소식", "https://www.jeju.go.kr/farm/notice/notice/notice1.htm", "act"),
)
_DETAIL_KEEP = {"act": ("act", "seq"), "mode": ("mode", "notice_id")}


def board_named(text: str, boards: Iterable[Board] = BOARDS) -> Board | None:
    """이름(또는 영문 열쇠)으로 게시판을 찾는다. 공백은 무시한다."""
    want = re.sub(r"\s+", "", text or "").casefold()
    return next((b for b in boards if want in (re.sub(r"\s+", "", b.name).casefold(), b.key)), None)


class RequestLimit(Exception):
    """한 번 찾기에 허용한 요청 수를 다 썼다."""


class BoardClient:
    """게시판·공고 페이지 받기 한 곳. 요청 수를 세고, 요청 사이에 쉰다. http·sleep 은 시험용 대체."""

    def __init__(self, http: Http | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_requests: int = MAX_REQUESTS, gap_s: float = MIN_GAP_S) -> None:
        self._http = http or urlopen_bytes
        self._sleep = sleep
        self.max_requests = max_requests
        self.gap_s = gap_s
        self.count = 0

    @property
    def left(self) -> int:
        return self.max_requests - self.count

    def fetch(self, url: str) -> bytes:
        url = check_url(url)
        if self.count >= self.max_requests:
            raise RequestLimit(f"한 번 찾기에 받을 수 있는 요청 {self.max_requests}번을 다 썼습니다")
        if self.count:
            self._sleep(self.gap_s)
        self.count += 1
        try:
            return self._http(url)
        except NoticeUrlError:
            raise
        except (OSError, ValueError) as e:
            raise NoticeUrlError(f"페이지를 받지 못했습니다({type(e).__name__}). 인터넷 연결을 확인하세요") from e


@dataclass(frozen=True)
class BoardRow:
    board: str                 # Board.key
    title: str
    posted: date | None
    dept: str
    url: str


# --- 주소 ------------------------------------------------------------------------------------

def _site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def list_url(board: Board, query: str = "", page: int = 1) -> str:
    """목록(또는 검색) 주소. 검색어는 제목 검색이다."""
    query = query.strip()
    params: list[tuple[str, str]] = []
    if board.engine == "act":
        if query:
            params += [("q", query), ("qType", "title")]
        if page > 1:
            params.append(("page", str(page)))
    else:
        if query:
            params.append(("searchText", query))
        if page > 1:
            params.append(("currentPageNo", str(page)))
        params.append(("recordCountPerPage", str(JEJUSI_PAGE_SIZE)))
    return board.url + ("?" + urlencode(params) if params else "")


def canonical_url(board: Board, href: str) -> str:
    """목록 줄의 링크를 상세 주소로 다듬는다(쪽 번호 같은 군더더기는 뗀다). 허용되지 않는 주소는 NoticeUrlError."""
    full = urljoin(board.url, href.strip())
    parts = urlsplit(full)
    keep = _DETAIL_KEEP[board.engine]
    if parts.path != urlsplit(board.url).path:
        raise NoticeUrlError("게시판 글이 아닌 주소는 받지 않습니다")
    all_keys = [k for k, _ in parse_qsl(parts.query)]
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in keep]
    if sorted(k for k, _ in query) != sorted(keep) or any(all_keys.count(k) != 1 for k in keep):
        raise NoticeUrlError("목록 줄의 상세 주소 모양이 맞지 않습니다")
    url = check_url(urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(sorted(query)), "")))
    if _site(url) != _site(board.url):
        raise NoticeUrlError("다른 사이트로 넘어가는 주소는 받지 않습니다")
    return url


def normalize_url(url: str) -> str:
    """같은 글인지 비교하려고 주소의 군더더기(쪽 번호 등)를 뗀다. 모르는 모양이면 그대로."""
    parts = urlsplit(url)
    for board in BOARDS:
        if _site(url) == _site(board.url) and parts.path == urlsplit(board.url).path:
            try:
                return canonical_url(board, url)
            except NoticeUrlError:
                return url
    return url


def url_inbox_id(url: str) -> str:
    """주소로 읽은 공고의 받은 함 폴더 이름(notice --url 과 같다)."""
    return f"url-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"


# --- 목록 읽기 -------------------------------------------------------------------------------

_ORG_END = re.compile(r"(과|팀|소|실|국|센터|자치|시|청|원|단|부|계|담당관|본부|사업소|위원회|회|도)$")
_SURE_ORG_END = re.compile(r"(과|팀|센터|자치|담당관|본부|사업소|위원회)$")     # 짧은 값에서 사람 이름과 겹치지 않는 끝말
DEPT_LIKE = re.compile(r"(과|팀|센터|담당관|본부|사업소|위원회|국)$")
_PLACE_END = re.compile(r"(동|읍|면)$")


@cache
def _place_names() -> frozenset[str]:
    from app.agents.llm.payload import load_emd_names
    try:
        return load_emd_names()
    except ValueError:
        return frozenset()


def clean_dept(text: str) -> str:
    """작성 부서 칸. 부서·읍면동 이름처럼 보이지 않는 짧은 한글(사람 이름일 수 있음)은 비운다."""
    t = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    if not re.fullmatch(r"[가-힣]{2,4}", t):
        return t[:40]      # 두 단어 이상이거나 다섯 글자 이상인 값은 사람 이름이 아니다
    if _SURE_ORG_END.search(t):
        return t
    if _PLACE_END.search(t) and t in _place_names():
        return t
    return ""


def is_dept_like(dept: str) -> bool:
    """부서(과·팀 …) 이름인가. 읍면동 이름이나 빈 칸이면 아니다."""
    return any(DEPT_LIKE.search(w) for w in (dept or "").split())


def _one(node: Node | None) -> str:
    return " ".join(lines_of(node))


def _date_in(text: str) -> date | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


_HREF = re.compile(r'href="([^"]*)"')
_BARE_AMP = re.compile(r"&(?!amp;)")


def _protect_href_ampersands(html: str) -> str:
    """제주시 목록의 링크는 &를 그대로 쓴다(&notice_id, &currentPageNo). 파이썬 HTML 읽기가 이를 &not·&curren 글자 참조로
    잘못 바꾸므로, 링크 안의 &는 읽기 전에 &amp; 로 바꿔 둔다."""
    return _HREF.sub(lambda m: 'href="' + _BARE_AMP.sub("&amp;", m.group(1)) + '"', html)


def parse_list(board: Board, html: str) -> tuple[list[BoardRow], int]:
    """저장해 둔 목록 HTML 에서 줄을 뽑는다. (줄들, 주소가 맞지 않아 버린 수). 같은 주소는 한 번만."""
    root = parse_html(_protect_href_ampersands(html))
    rows: list[BoardRow] = []
    seen: set[str] = set()
    dropped = 0
    for tr in root.find_all("tr"):
        if board.engine == "act":
            a = next((x for x in tr.find_all("a") if "act=view" in x.attrs.get("href", "")), None)
            tds = tr.find_all("td")
            dept_node = tds[-3] if len(tds) >= 3 else None
            date_text = " ".join(_one(td) for td in tds)
            title = re.sub(r"\s+", " ", (a.attrs.get("title") or "") if a else "").strip() or (_one(a) if a else "")
        else:
            cell = tr.find("td", "title")
            a = cell.find("a") if cell else None
            dept_node = tr.find("td", "writer")
            date_node = tr.find("td", "date")
            date_text = _one(date_node)
            title = _one(a) if a else ""
        if a is None or not title:
            continue
        try:
            url = canonical_url(board, a.attrs.get("href", ""))
        except NoticeUrlError:
            dropped += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(BoardRow(board.key, title, _date_in(date_text), clean_dept(_one(dept_node)), url))
    return rows, dropped


def read_list(client: BoardClient, board: Board, query: str = "", page: int = 1) -> tuple[list[BoardRow], int]:
    """게시판 한 쪽을 받아 줄로 만든다. 못 받으면 NoticeUrlError, 요청을 다 썼으면 RequestLimit."""
    html = _decode_html(client.fetch(list_url(board, query, page)))
    rows, dropped = parse_list(board, html)
    if not rows and not dropped and "<table" not in html.lower():
        raise NoticeUrlError("게시판 모양이 달라져 글을 읽지 못했습니다")
    return rows, dropped


# --- 이미 읽은 글 ----------------------------------------------------------------------------

_FINISHED = ("DRAFT_READY", "NOT_RELEVANT", "BLOCKED_PII")


def _finished_read(folder: Path) -> bool:
    """받은 함 폴더가 끝까지 읽힌 공고인가(AI 가 못 돌았거나 미완이거나 읽을 수 없던 글은 다시 읽어야 하므로 아니다)."""
    try:
        check = json.loads((folder / "check.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(check, dict) and check.get("decision") in _FINISHED and not check.get("partial")


class KnownNotices:
    """지원 전체 보기 목록(data/catalog/notices/*.json 의 url)과, 받은 함(data/inbox/url-*)에서 끝까지 읽은 주소."""

    def __init__(self, urls: Iterable[str] = (), inbox_ids: Iterable[str] = ()) -> None:
        self.urls = {normalize_url(u) for u in urls if u}
        self.inbox_ids = set(inbox_ids)

    def __contains__(self, url: str) -> bool:
        return normalize_url(url) in self.urls or url_inbox_id(url) in self.inbox_ids

    @classmethod
    def from_root(cls, root: Path, catalog_dir: Path | None = None) -> KnownNotices:
        root = Path(root)
        cat = Path(catalog_dir) if catalog_dir is not None else root / "data" / "catalog"
        urls: list[str] = []
        for p in sorted((cat / "notices").glob("*.json")):
            try:
                url = json.loads(p.read_text(encoding="utf-8")).get("url")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(url, str):
                urls.append(url)
        inbox = cat.parent / "inbox"          # 기본(root/data/catalog)이면 root/data/inbox
        ids = [d.name for d in sorted(inbox.glob("url-*")) if _finished_read(d)] if inbox.is_dir() else []
        return cls(urls, ids)


# --- 고정본(재생·시험) -----------------------------------------------------------------------

def fixture_hash(directory: Path) -> str:
    """고정본 폴더의 내용 지문(재생 녹화가 어느 고정본으로 만들어졌는지 알아보는 데 쓴다)."""
    h = hashlib.sha256()
    for p in sorted(Path(directory).iterdir()):
        if p.is_file() and p.suffix in (".html", ".json"):
            h.update(p.name.encode("utf-8") + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()[:8]


def fixture_http(directory: Path) -> Http:
    """directory/index.json({"주소": "파일 이름"})에 적힌 주소만 그 파일 내용으로 답하는 가짜 받기. 없는 주소는 NoticeUrlError."""
    directory = Path(directory)
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))

    def http(url: str) -> bytes:
        name = index.get(url)
        if name is None:
            raise NoticeUrlError("고정본에 없는 주소라 받지 못했습니다")
        return (directory / name).read_bytes()
    return http
