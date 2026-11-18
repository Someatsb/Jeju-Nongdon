"""공고 주소로 공고 읽기(설계서 B-3). 주소를 주면 그 페이지를 받아 본문 글을 원문 그대로 뽑아 Doc 으로 만든다.

- 받을 수 있는 곳은 서귀포시(seogwipo.go.kr), 제주시(jejusi.go.kr), 제주도청(jeju.go.kr)뿐이다. 허용 목록(ALLOWED_HOSTS)에 없는
  주소, https 가 아닌 주소, 사용자 정보·특수 포트가 든 주소는 받지 않고, 받는 도중 다른 곳으로 넘어가도 따라가지 않는다.
- 본문 틀은 사이트마다 다르다(서귀포시·도청: div.board-view, 제주시: div.view-wrap). 못 찾으면 NoticeUrlError.
- 본문은 글 그대로다(요약·고침 없음). 휴대전화 번호·메일 주소가 든 줄은 뺀다(원문에 그런 줄이 있었다는 것만 removed 로 알린다).
- 외부 부품 없이 표준 라이브러리만 쓴다. 시험은 http 인자로 저장해 둔 HTML 을 넘긴다(인터넷에 나가지 않는다).
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from app.data_layer.docs_in import Doc, extract
from app.tools.draft_checks import pii_labels

ALLOWED_HOSTS = frozenset({"seogwipo.go.kr", "www.seogwipo.go.kr", "jejusi.go.kr", "www.jejusi.go.kr",
                           "jeju.go.kr", "www.jeju.go.kr"})
SOURCE_PREFIX = "출처:"
TIMEOUT_S = 30
MAX_BYTES = 5_000_000
USER_AGENT = "Mozilla/5.0 (jeju-chaenggim notice reader)"
NOT_FOUND = "본문을 찾지 못했습니다. 본문을 복사해 파일로 넣어 주세요"
MIN_BODY_CHARS = 30

Http = Callable[[str], bytes]


class NoticeUrlError(Exception):
    """주소로 공고를 읽지 못했다. 메시지는 직원에게 그대로 보여 줄 한국어 안내다."""


@dataclass(frozen=True)
class UrlNotice:
    doc: Doc
    url: str
    title: str
    removed_lines: int          # 개인정보(휴대전화·메일)가 있어 뺀 줄 수


# --- 주소 확인과 받기 ------------------------------------------------------------------------

def check_url(url: str) -> str:
    """허용된 공고 주소인지 확인해 다듬은 주소를 돌려준다. 아니면 NoticeUrlError."""
    url = url.strip()
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise NoticeUrlError("공고 주소 모양이 맞지 않습니다") from None
    if parts.scheme != "https" or not host or parts.username or parts.password or port not in (None, 443):
        raise NoticeUrlError("공고 주소는 https:// 로 시작하는 서귀포시·제주시·제주도청 주소만 받습니다")
    if host not in ALLOWED_HOSTS:
        raise NoticeUrlError("받을 수 있는 곳은 서귀포시(seogwipo.go.kr), 제주시(jejusi.go.kr), "
                             "제주도청(jeju.go.kr) 공고뿐입니다. 다른 곳은 본문을 복사해 파일로 넣어 주세요")
    return url


class _SameSiteOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_url(newurl)
        except NoticeUrlError:
            raise NoticeUrlError("공고 페이지가 다른 곳으로 넘어가서 받지 않았습니다") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen_bytes(url: str) -> bytes:
    opener = urllib.request.build_opener(_SameSiteOnly)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:
            data = resp.read(MAX_BYTES + 1)
    except NoticeUrlError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise NoticeUrlError(f"공고 페이지를 받지 못했습니다({type(e).__name__}). 인터넷 연결이나 주소를 확인하세요") from e
    if len(data) > MAX_BYTES:
        raise NoticeUrlError("공고 페이지가 너무 커서 받지 않았습니다")
    return data


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --- HTML 읽기(표준 라이브러리 html.parser 로 가벼운 나무를 만든다) ----------------------------

_VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "col", "area", "base", "embed", "source", "track", "wbr"})
_BLOCK = frozenset({"p", "div", "li", "tr", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt", "dd",
                    "section", "br", "article", "header", "footer"})
_SKIP = frozenset({"script", "style"})


class Node:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag, self.attrs, self.kids = tag, attrs, []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def walk(self):
        for k in self.kids:
            if isinstance(k, Node):
                yield k
                yield from k.walk()

    def find(self, tag: str | None = None, cls: str | None = None, id_: str | None = None) -> Node | None:
        return next(iter(self.find_all(tag, cls, id_)), None)

    def find_all(self, tag: str | None = None, cls: str | None = None, id_: str | None = None) -> list[Node]:
        return [n for n in self.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())
                and (id_ is None or n.attrs.get("id") == id_)]


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].kids.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def parse_html(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def _text(node: Node) -> str:
    parts: list[str] = []

    def go(n: Node) -> None:
        if n.tag in _SKIP:
            return
        block = n.tag in _BLOCK
        if block:
            parts.append("\n")
        for k in n.kids:
            if isinstance(k, str):
                parts.append(k)
            else:
                go(k)
        if n.tag in ("td", "th"):
            parts.append(" ")
        if block:
            parts.append("\n")

    go(node)
    return "".join(parts)


def lines_of(node: Node | None) -> list[str]:
    """노드 안의 글을 줄 단위로(공백을 한 칸으로, 빈 줄 없이)."""
    if node is None:
        return []
    raw = _text(node).replace("\xa0", " ").replace("​", "")
    return [ln for ln in (re.sub(r"[ \t\r]+", " ", s).strip() for s in raw.split("\n")) if ln]


def _one(node: Node | None) -> str:
    return " ".join(lines_of(node))


# --- 사이트별 본문 뽑기 ----------------------------------------------------------------------

@dataclass(frozen=True)
class _Page:
    title: str
    dept: str
    posted: str
    tel: str
    body: list[str]
    files: list[str]


def _board_view(root: Node) -> _Page | None:
    """서귀포시·도청 게시판: div.board-view (제목 p.title, 정보 p.info, 본문 div.view-contents)."""
    view = root.find("div", "board-view")
    body_node = view.find("div", "view-contents") if view else None
    if view is None or body_node is None:
        return None
    infos = view.find_all("p", "info")
    info = " ".join(_one(p) for p in infos)
    def grab(label: str) -> str:
        m = re.search(label + r"\s*:\s*(\S+(?: \d{2}:\d{2}:\d{2})?)", info)
        return m.group(1).strip(" ·") if m else ""

    files = [_one(a) for p in infos if "첨부" in _one(p) for a in p.find_all("a")
             if "act=download" in a.attrs.get("href", "")]
    return _Page(_one(view.find("p", "title")), grab("작성자"), grab("작성일"), grab("담당자연락처"), lines_of(body_node),
                 list(dict.fromkeys(f for f in files if f)))


def _view_wrap(root: Node) -> _Page | None:
    """제주시 게시판: div.view-wrap (머리 div.view-header, 본문 div.view-content div.memo)."""
    wrap = root.find("div", "view-wrap")
    content = wrap.find("div", "view-content") if wrap else None
    if wrap is None or content is None:
        return None
    header = wrap.find("div", "view-header")
    info: dict[str, str] = {}
    for dl in (header.find_all("dl") if header else []):
        dt, dd = dl.find("dt"), dl.find("dd")
        if dt is not None and dd is not None:
            info[_one(dt)] = _one(dd)
    title_node = header.find(None, "title") if header else None
    files = [_one(a) for a in (header.find_all("a") if header else []) if "download" in a.attrs and "download" not in a.classes()]
    return _Page(_one(title_node), info.get("부서", ""), info.get("작성일", ""), info.get("연락처", ""),
                 lines_of(content.find("div", "memo") or content), list(dict.fromkeys(f for f in files if f)))


_EXTRACTORS: dict[str, tuple[Callable[[Node], _Page | None], ...]] = {
    "seogwipo.go.kr": (_board_view,), "jejusi.go.kr": (_view_wrap,), "jeju.go.kr": (_board_view, _view_wrap)}


def _site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_notice_page(url: str, html: str) -> UrlNotice:
    """저장해 둔 공고 HTML 에서 본문을 뽑는다(받기와 분리해 시험하기 쉽게)."""
    root = parse_html(html)
    page = next((p for fn in _EXTRACTORS[_site(url)] if (p := fn(root)) is not None), None)
    if page is None or not page.title or sum(len(ln.replace(" ", "")) for ln in page.body) < MIN_BODY_CHARS:
        raise NoticeUrlError(NOT_FOUND)
    body, removed = [], 0
    for ln in page.body:
        if pii_labels(ln):
            removed += 1
        else:
            body.append(ln)
    head = [f"{SOURCE_PREFIX} {url}", f"제목: {page.title}"]
    for label, value in (("작성 부서", page.dept), ("작성일", page.posted), ("담당자 연락처", page.tel)):
        if value and not pii_labels(value):
            head.append(f"{label}: {value}")
    text = "\n".join(head + ["", "[본문]", *body, "", "[첨부 파일]", *(page.files or ["(없음)"])]) + "\n"
    return UrlNotice(doc=extract(text), url=url, title=page.title, removed_lines=removed)


def fetch_notice(url: str, http: Http | None = None) -> UrlNotice:
    """공고 주소를 받아 읽는다. http 는 시험용 대체(주소 → 바이트)."""
    url = check_url(url)
    html = _decode((http or urlopen_bytes)(url))
    return parse_notice_page(url, html)


def source_url_of(doc: Doc) -> str | None:
    """파일로 넣은 공고의 첫 줄이 '출처: <주소>' 이면 그 주소(https 만)."""
    first = next((ln for page in doc.pages for ln in page.lines), "")
    if first.startswith(SOURCE_PREFIX):
        url = first[len(SOURCE_PREFIX):].strip()
        if url.startswith("https://") and " " not in url:
            return url
    return None
