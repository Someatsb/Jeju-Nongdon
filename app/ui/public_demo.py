"""공개 체험판 모드(환경변수 JC_PUBLIC_DEMO=1일 때만 켜진다). 인터넷에 띄우는 심사용 체험판이다.

PC 한 대에서 쓰는 지금 동작은 그대로 두고, 이 모드에서만 다음을 더한다.
- Origin 검사: Origin 이 그 요청의 Host(프록시 뒤면 X-Forwarded-Host)와 같은 곳이면 통과, 다른 곳이면 막는다.
  Host 검사(127.0.0.1만)는 끈다: 인터넷 주소로 들어오기 때문이다.
- 잠금: 직원 쪽 쓰기 요청(/staff 아래 POST 등)은 막고 쉬운 말 화면을 보인다. 문자 알림 신청은 번호를 읽지도 저장하지도 않는다.
- 시연 농가로 바로 해 보기: GET /demo/P1~P5.
- 세션 수 한도, 검수 로그 길이 한도(512MB 안에서 돌게).
라우트 표와 잠근 것은 docs/8_인터넷_체험판.md 에 있다.
"""
import json
import os
from collections.abc import Mapping

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.config import APP_ROOT
from app.core.models import FarmProfile
from app.ui.replay import NO_MATCH_RECORDING
from app.ui import forms
from app.ui.session import COOKIE, set_session_cookie

ENV_NAME = "JC_PUBLIC_DEMO"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BLOCKED_LINE = "체험판에서는 쓸 수 없어요. 설치본에서 쓸 수 있어요."
REMINDER_LINE = "체험판이라 저장하지 않았어요"
FORBIDDEN_LINE = "이 프로그램 화면에서 보낸 요청만 받아요."
MAX_SESSIONS = 300          # 동시에 들고 있는 상담 수 한도(넘으면 결과 단계 전의 가장 오래 안 쓴 것부터 지운다. 150개 동시에 158MB 였다)
MAX_LOG_ENTRIES = 4000      # 검수 로그(메모리)가 이만큼 넘으면 오래된 절반을 버린다
DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")
NO_MATCH_PUBLIC = "체험판이라 이 농가는 새 공고 맞춰 보기가 없어요(시연 농가 다섯만 있어요)"
INTRO_LINE = "체험판이에요. 시연 농가 다섯은 AI 설명까지 보이고, 직접 입력하면 규칙 계산 결과가 나와요. 날짜는 2026년 11월 13일로 고정해 보여 드려요."

router = APIRouter()


def env_enabled() -> bool:
    return os.environ.get(ENV_NAME) == "1"


def _first(value: str | None) -> str:
    return (value or "").split(",")[0].strip()


def same_origin(headers: Mapping[str, str], scheme: str) -> bool:
    """Origin 이 그 요청의 Host 와 같은 곳인가. 프록시 뒤라 X-Forwarded-Proto·X-Forwarded-Host 를 먼저 본다(없으면 요청 자체의 것)."""
    origin = headers.get("origin")
    if origin is None:
        return True       # 브라우저가 보낸 요청이 아니다(지금 규칙과 같다)
    proto = _first(headers.get("x-forwarded-proto")) or scheme
    hosts = {h for h in (_first(headers.get("x-forwarded-host")), _first(headers.get("host"))) if h}
    return any(origin == f"{proto}://{h}" for h in hosts)


def is_locked(method: str, path: str) -> bool:
    """잠그는 요청: 직원 주소 아래의 쓰기 요청(새 공고 찾아보기 시작 등). 읽기만 하는 직원 화면은 연다."""
    return method in UNSAFE_METHODS and (path == "/staff" or path.startswith("/staff/"))


def _blocked_page(request: Request) -> Response:
    return request.app.state.templates.TemplateResponse(request, "demo_blocked.html", {"line": BLOCKED_LINE}, status_code=403)


def install(app: FastAPI) -> None:
    """create_app 이 공개 체험판 모드에서만 부른다(재생 모드를 먼저 켠 뒤)."""
    state = app.state
    if not state.cfg.replay:
        raise RuntimeError("공개 체험판은 재생 모드로만 켤 수 있어요(실제 AI 를 부르지 않는다)")
    log = state.review_log
    if getattr(log, "entries", None) is not None:      # 재생 모드는 상담마다 검수 로그를 몇 줄씩 쌓는다: 길이를 제한한다
        write = log.write
        log.write = lambda entry: (write(entry), _trim(log.entries))[0]
    state.demo_inputs = _load_demo_inputs()
    if state.matcher is not None:      # 직원 칸 글에 서버 파일 이름이 나오지 않게 바꾼다
        match = state.matcher

        def matcher(*args, **kwargs):
            report = match(*args, **kwargs)
            return report.model_copy(update={"note": NO_MATCH_PUBLIC}) if report.note == NO_MATCH_RECORDING else report
        state.matcher = matcher
    state.sessions.max_sessions = MAX_SESSIONS

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in UNSAFE_METHODS and not same_origin(request.headers, request.url.scheme):
            return Response(FORBIDDEN_LINE, status_code=403, media_type="text/plain; charset=utf-8")
        if request.method == "POST" and request.url.path == "/counsel/reminder":
            # 번호를 읽지도, 저장하지도, 기록하지도 않는다(요청 본문을 열지 않는다)
            return JSONResponse({"ok": False, "line": REMINDER_LINE, "errors": {}}, headers={"Cache-Control": "no-store"})
        if is_locked(request.method, request.url.path):
            return _blocked_page(request)
        response = await call_next(request)
        # 다른 사이트(제출 페이지)에서 /demo/P1 링크로 들어와도 쿠키가 붙게 Lax 로 낸다(쓰기 요청은 위 Origin 검사가 막는다). PC 모드 쿠키는 그대로 Strict
        response.raw_headers = [(k, v.replace(b"SameSite=strict", b"SameSite=lax")) if k == b"set-cookie" else (k, v)
                                for k, v in response.raw_headers]
        return response

    app.include_router(router)


def _trim(entries: list) -> None:
    if len(entries) > MAX_LOG_ENTRIES:
        del entries[:MAX_LOG_ENTRIES // 2]


def _load_demo_inputs() -> dict:
    with (APP_ROOT / "data" / "replay" / "demo_inputs.json").open(encoding="utf-8") as f:
        return json.load(f)


def demo_links(request: Request) -> list[dict]:
    """첫 화면의 "시연 농가로 해 보기" 줄: [{id, label}]. 이름은 그 농가의 작물(표의 이름)이다."""
    state = request.app.state
    labels = {c.crop_code: c.label for c in state.tables.crops}
    out = []
    for pid in DEMO_IDS:
        form = state.demo_inputs.get(pid, {}).get("form")
        if not form:
            continue
        names = [labels.get(form[k], form[k]) for k in ("crop1_crop_code", "crop2_crop_code") if form.get(k)]
        out.append({"id": pid, "label": "·".join(n.split("(")[0].split("_")[0] for n in names)})
    return out


@router.get("/demo/{pid}")
def demo_farm(request: Request, pid: str) -> Response:
    """시연 농가의 답이 채워진 확인 화면으로 보낸다(이미 받고 있는 지원 칸도 녹화와 같게 채운다). 거기서 '결과 보기'만 누르면 된다."""
    entry = request.app.state.demo_inputs.get(pid) if pid in DEMO_IDS else None
    if entry is None:
        return RedirectResponse("/", status_code=303)
    form = {k: v for k, v in entry["form"].items() if isinstance(v, str)}
    result = forms.to_profile(form, proxy=False)
    if isinstance(result, forms.FormErrors):
        return RedirectResponse("/counsel/input", status_code=303)
    profile = FarmProfile.model_validate({**result.model_dump(), "already_receiving": set(entry.get("already", ()))})
    sid = request.app.state.sessions.put(request.cookies.get(COOKIE), profile=profile, reminder=None, proxy=False, counsel_id=None,
                                         reminder_saved=None, reminder_count=0, reminder_failed=False, reminder_none=False,
                                         printed=False, form_values=dict(form), job=None)
    response = RedirectResponse("/counsel/confirm", status_code=303)
    set_session_cookie(response, sid)
    return response


def home_extra(request: Request) -> dict:
    """첫 화면 템플릿에 더할 값. 공개 체험판이 아니면 빈 dict(PC 화면은 달라지지 않는다)."""
    if not request.app.state.cfg.public_demo:
        return {}
    return {"demo_links": demo_links(request), "demo_intro": INTRO_LINE}
