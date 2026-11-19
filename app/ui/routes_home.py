"""첫 화면: GET /(그림·한 문장·큰 단추·이용 방법·곧 마감되는 지원 카드), GET /counsel(상담 시작 -> 입력 화면).
"""
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.catalog import key_for_name, support_href
from app.core.calendar import apply_window
from app.catalog.layout import URGENT_DAYS
from app.core.home import DUE_DAYS, home_lines
from app.ui.routes_supports import load_catalog_for, today_of

router = APIRouter()


def _md(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def _flag(left: int, closing: bool) -> str:
    if not closing:
        return f"{left}일 뒤 열려요"
    return "오늘 마감" if left == 0 else "내일 마감" if left == 1 else f"{left}일 남음"


def _notice_cards(entries, as_of: date) -> list[tuple[date, dict]]:
    """새 공고 중 끝 날짜를 읽었고 아직 안 끝난 것: 30일 안에 닫히거나 열리는 것만(표의 지원과 같은 기준)."""
    out = []
    for e in entries:
        if e.kind != "notice" or e.window_end is None or e.window_end < as_of:
            continue
        closing = e.window_start is None or e.window_start <= as_of
        day = e.window_end if closing else e.window_start
        left = (day - as_of).days
        if left > DUE_DAYS:
            continue
        out.append((day, {"name": e.title, "href": e.href, "date_text": _md(day) + ("까지" if closing else "부터"), "closing": closing,
                          "urgent": left <= URGENT_DAYS and closing, "flag": _flag(left, closing), "new": True}))
    return out


def due_cards(tables, as_of: date, due30, notices=()) -> list[dict]:
    """곧 마감되는 지원 카드(최대 3개). 열려 있으면 "○월 ○일까지", 아직 안 열렸으면 "○월 ○일부터".
    표의 지원(due30)과 새 공고(notices: 목록 자료의 새 공고 항목)를 합쳐 날짜가 빠른 순으로 3개를 고른다."""
    cards = []
    dated: list[tuple[date, dict]] = []
    for name, day in due30:
        closing = False
        for p in tables.programs:
            if (p.name or p.program_key) != name:
                continue
            w = apply_window(p, as_of)
            if w.open_now and w.next_end == day:
                closing = True
                break
        left = (day - as_of).days
        if left < 0:       # 이미 지난 마감은 보이지 않는다
            continue
        key = key_for_name(tables.programs, name)      # 카드를 누르면 그 지원의 안내 화면으로 간다
        dated.append((day, {"name": name, "href": support_href(key) if key else None, "date_text": _md(day) + ("까지" if closing else "부터"),
                            "closing": closing, "urgent": left <= URGENT_DAYS and closing, "flag": _flag(left, closing), "new": False}))
    dated.extend(_notice_cards(notices, as_of))
    dated.sort(key=lambda t: t[0])                      # 날짜 빠른 순(같은 날이면 표의 지원이 먼저: 정렬은 안정적이다)
    cards = [c for _, c in dated]
    return cards[:3]


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    st = request.app.state
    cfg = st.cfg
    # 시연 기준일(--asof)로 띄워도 첫 화면의 "곧 마감되는 지원"은 오늘 날짜로 센다(마감 계산에 쓰는 것은 공고표뿐이라 안전하다) - 목록과 같은 기준일(today_of)
    today = today_of(request)
    lines = home_lines(st.tables, st.snapshot, today)
    catalog = load_catalog_for(request, today)
    return st.templates.TemplateResponse(request, "home.html", {"due_cards": due_cards(st.tables, today, lines.due30, catalog.entries), "as_of_md": _md(today),
                                                                "support_count": catalog.count})


@router.get("/counsel")
def counsel_start() -> Response:
    return RedirectResponse("/counsel/input", status_code=303)
