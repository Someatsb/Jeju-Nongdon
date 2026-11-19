"""직원 메뉴(설계서 3-6): GET /staff(자료 상태·공고 초안 목록), GET /staff/notice/{id}(공고 초안 보고서 보기).

어르신 화면에서 뺀 날짜·보류 건수를 여기서 보여 준다. 열쇠(키) 값은 어디에도 내지 않고 "쓰는지 아닌지"만 말한다.
공고 폴더 이름은 글자·숫자·한글·._- 만 받고, 열려는 파일이 공고 폴더 밖이면 404로 막는다.
"""
import json
import logging
import re
from datetime import date, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.agents.llm.keystore import KeyStore
from app.config import APP_ROOT
from app.ui.report_notice import DECISION_LABEL
from app.ui.routes_supports import load_catalog_for, staff_line
from app.ui.scout_job import REPLAY_NOTE, ScoutRefused

log = logging.getLogger(__name__)
router = APIRouter(prefix="/staff")
INBOX_DIR = APP_ROOT / "data" / "inbox"
_SAFE_ID = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣._-]*$")
# 이미 저장된 보고서도 작은 창에서 글자가 16px 아래로 내려가지 않고 폭을 넘지 않게 한다(저장된 파일은 고치지 않고 보낼 때만 덧붙인다)
FIT_CSS = ("<style>body{overflow-wrap:anywhere}.page,.issue,.note{font-size:1rem!important}"
           "@media(max-width:700px){body{margin:.8rem!important}"
           # 좁은 창에서는 표 한 줄을 카드 하나로 쌓아, 글이 두세 글자씩 꺾이지 않게 한다
           "thead{display:none}table,tbody,tr,td{display:block;width:auto!important}"
           "tr{border:2px solid #999;margin:.7rem 0;padding:.3rem}"
           "td{border:0!important;padding:.2rem .4rem!important;word-break:normal!important;overflow-wrap:anywhere}"
           "td.mark{text-align:left!important}td.name{font-weight:bold}"
           'td:nth-child(3)::before{content:"초안: ";color:#555}td:nth-child(4)::before{content:"원문 인용: ";color:#555}}</style>')
BACK_LINK = '<p style="margin:.6rem 1.5rem"><a href="/staff">&larr; 직원 메뉴로 돌아가기</a></p>'


STALE_DAYS = 7      # 확인일이 이만큼 지나면 "다시 확인 필요" 경고


def _day(d: date | None) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일" if d else "자료 없음"


def _old(d: date | None, today: date) -> str:
    """확인일이 오래됐으면 경고 글(없으면 빈 문자열)."""
    return f"{(today - d).days}일 지남 · 다시 확인 필요" if d and (today - d).days >= STALE_DAYS else ""


def ai_line(request: Request) -> str:
    """AI 문장을 쓰는지 한 줄로. 열쇠 값은 읽어도 내지 않는다."""
    if request.app.state.cfg.replay:
        return "미리 저장해 둔 답변 사용 중"
    if getattr(request.app.state.cfg, "public_demo", False):        # 인터넷 판: 열쇠 저장소·.env 는 열지 않는다(환경변수로 만든 클라이언트가 있는지만 본다)
        return "사용 중" if request.app.state.ai_live else "기본 문장 사용 중"
    try:
        has_key = bool(KeyStore().get("llm"))
    except Exception:       # 자격 증명 저장소를 못 열면 열쇠가 없는 것으로 본다
        has_key = False
    return "사용 중" if has_key else "기본 문장 사용 중"


def _title(d) -> str:
    """공고 초안 제목: 보고서의 <title>이나 첫 제목. 없으면 빈 글."""
    try:
        html = (d / "report.html").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"<title>(.*?)</title>", html, re.S) or re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:60] if m else ""


def notice_list() -> list[dict]:
    """data/inbox 아래 report.html이 있는 폴더들(최근 것 먼저)."""
    if not INBOX_DIR.is_dir():
        return []
    rows = []
    for d in INBOX_DIR.iterdir():
        report = d / "report.html"
        if not (d.is_dir() and _SAFE_ID.match(d.name) and report.is_file()):
            continue
        decision = ""
        try:
            decision = DECISION_LABEL.get(json.loads((d / "check.json").read_text(encoding="utf-8")).get("decision", ""), "")
        except (OSError, ValueError):
            pass
        made = datetime.fromtimestamp(report.stat().st_mtime)
        rows.append({"id": d.name, "title": _title(d), "decision": decision or "결과 표시 없음", "made": f"{made.year}년 {made.month}월 {made.day}일", "_t": made})
    rows.sort(key=lambda r: r["_t"], reverse=True)
    return rows


@router.get("", response_class=HTMLResponse)
def staff(request: Request) -> Response:
    st = request.app.state
    h, tables = st.header, st.tables
    today = st.cfg.as_of
    holds = sorted({p.name or p.program_key for p in tables.programs if p.status == "hold"})       # 이름이 같은 두 건(읍면·동)은 한 가지로 센다: 칸의 숫자와 목록 길이가 같다
    status = [
        ("지원제도 정보 확인일", _day(h.tables_verified), _old(h.tables_verified, today)),
        ("도매가격 자료 마지막 날", _day(h.price_as_of), _old(h.price_as_of, today)),
        ("감귤 가격 마지막 날", _day(h.citrus_as_of), _old(h.citrus_as_of, today)),
        ("저장본 만든 날", _day(h.snapshot_built), ""),
        ("준비 중인 지원제도", f"{len(holds)}건", ""),
    ]
    job = st.scout.job
    return st.templates.TemplateResponse(request, "staff.html", {"status": status, "ai": ai_line(request), "notices": notice_list(),
                                                                  "scout_state": job.snapshot()["state"] if job else "none",
                                                                  "support_line": staff_line(load_catalog_for(request)),
                                                                  "holds": holds})


@router.get("/notice/{notice_id}", response_class=HTMLResponse)
def notice(request: Request, notice_id: str) -> Response:
    missing = HTMLResponse("<p>그 공고 보고서를 찾지 못했어요. <a href='/staff'>직원 메뉴로</a></p>", status_code=404)
    if not _SAFE_ID.match(notice_id):
        return missing
    path = (INBOX_DIR / notice_id / "report.html").resolve()
    if path.parent.parent != INBOX_DIR.resolve() or not path.is_file():
        return missing
    html = path.read_text(encoding="utf-8")
    # 체험(저장 답변) 때 보고서 맨 위에 붙는 내부용 띠("시연 응답 재생 … handwritten")는 화면에 보이지 않게 뺀다
    html = re.sub(r'<div class="banner warn"[^>]*>.*?</div>\s*', "", html, count=1, flags=re.S)
    html = html.replace("</head>", FIT_CSS + "</head>", 1) if "</head>" in html else FIT_CSS + html
    html = html.replace("<body>", "<body>" + BACK_LINK, 1) if "<body>" in html else BACK_LINK + html
    return HTMLResponse(html)


@router.post("/scout")
def scout_start(request: Request) -> Response:
    """공고 찾아보기를 뒤 작업으로 시작한다. 이미 도는 중이면 새로 시작하지 않고 진행 화면으로 간다.
    다른 사이트에서 온 POST 는 앱의 Origin 검사(app.py)가 막는다."""
    try:
        request.app.state.scout.start()
    except ScoutRefused as e:      # 인터넷 판: 쉬는 시간·오늘 한도·AI 없음
        return request.app.state.templates.TemplateResponse(request, "demo_blocked.html", {"line": e.line, "back": "/staff"}, status_code=429)
    return RedirectResponse("/staff/scout", status_code=303)


@router.get("/scout/status")
def scout_status(request: Request) -> Response:
    job = request.app.state.scout.job
    return JSONResponse(job.snapshot() if job else {"state": "none"}, headers={"Cache-Control": "no-store"})


@router.get("/scout", response_class=HTMLResponse)
def scout_page(request: Request) -> Response:
    """진행 화면(도는 중) 또는 보고 화면(끝난 뒤). 찾은 적이 없으면 직원 메뉴로. 열기만 해서는 시작하지 않는다."""
    job = request.app.state.scout.job
    if job is None:
        return RedirectResponse("/staff", status_code=303)
    return request.app.state.templates.TemplateResponse(request, "scout.html", {"job": job.snapshot(), "d": job.data, "replay_text": REPLAY_NOTE},
                                                       headers={"Cache-Control": "no-store"})
