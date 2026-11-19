"""인터넷 판 모드(환경변수 JC_PUBLIC_DEMO=1일 때만 켜진다). 인터넷에 띄우는 실제 서비스다(Render 등).

PC 한 대에서 쓰는 지금 동작은 그대로 두고, 이 모드에서만 다음을 더한다.
- 날짜는 오늘(한국 시간): 요청마다 날짜가 바뀌었는지 보고 바뀌면 그날 기준으로 표·저장본을 다시 읽는다(app.state.roll_today).
- 실제 AI: 키는 환경변수 ANTHROPIC_API_KEY 에서만 읽는다(.env·열쇠 저장소는 열지 않는다). 하루 호출 한도(JC_AI_DAILY_MAX)는 AI 클라이언트를 감싸는
  Guard 한 곳이 센다(app.py). 직원 메뉴 "공고 찾아보기"는 한 번에 하나, 끝난 뒤 JC_SCOUT_COOLDOWN_MIN 분 쉰다(scout_job.ScoutLimits).
- Origin 검사: Origin 이 그 요청의 Host(프록시 뒤면 X-Forwarded-Host)와 같은 곳이면 통과, 다른 곳이면 막는다.
  Host 검사(127.0.0.1만)는 끈다: 인터넷 주소로 들어오기 때문이다.
- 잠금: 직원 쪽 쓰기 요청(/staff 아래 POST 등)은 막고 쉬운 말 화면을 보인다(공고 찾아보기 POST /staff/scout 만 연다). 문자 알림 신청은 번호를 읽지도 저장하지도 않는다.
- 농가 바로 해 보기: GET /demo/P1~P5(답을 채워 확인 화면으로 보낸다. 결과는 오늘 날짜·실제 AI 로 나온다).
- 세션 수 한도, 검수 로그 길이 한도(512MB 안에서 돌게).
라우트 표와 잠근 것은 docs/8_인터넷_체험판.md 에 있다.
"""
import json
import os
from collections.abc import Mapping

from fastapi import APIRouter, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.config import APP_ROOT, kst_today
from app.core.models import FarmProfile
from app.ui import forms
from app.ui.session import COOKIE, set_session_cookie

ENV_NAME = "JC_PUBLIC_DEMO"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
OPEN_WRITES = frozenset({("POST", "/staff/scout")})     # 인터넷 판에서 여는 직원 쪽 쓰기(공고 찾아보기). 쉬는 시간·한도는 ScoutLimits 가 지킨다
BLOCKED_LINE = "인터넷 판에서는 쓸 수 없어요. 설치본에서 쓸 수 있어요."
REMINDER_LINE = "인터넷 판이라 번호는 저장하지 않았어요"
FORBIDDEN_LINE = "이 프로그램 화면에서 보낸 요청만 받아요."
MAX_SESSIONS = 300          # 동시에 들고 있는 상담 수 한도(넘으면 결과 단계 전의 가장 오래 안 쓴 것부터 지운다. 150개 동시에 158MB 였다)
MAX_LOG_ENTRIES = 4000      # 검수 로그(메모리)가 이만큼 넘으면 오래된 절반을 버린다
DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")
DAILY_MAX_ENV, DAILY_MAX_DEFAULT = "JC_AI_DAILY_MAX", 400
COOLDOWN_ENV, COOLDOWN_DEFAULT = "JC_SCOUT_COOLDOWN_MIN", 10

router = APIRouter()


def env_enabled() -> bool:
    return os.environ.get(ENV_NAME) == "1"


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        value = int((os.environ.get(name) or "").strip())
    except ValueError:
        return default
    return value if value >= minimum else default


def daily_max() -> int:
    """하루 AI 호출 한도(JC_AI_DAILY_MAX, 기본 400). 숫자가 아니거나 1 미만이면 기본값."""
    return _int_env(DAILY_MAX_ENV, DAILY_MAX_DEFAULT, 1)


def scout_cooldown_min() -> int:
    """공고 찾아보기가 끝난 뒤 쉬는 분(JC_SCOUT_COOLDOWN_MIN, 기본 10). 0 이면 쉬지 않는다. 숫자가 아니거나 음수면 기본값."""
    return _int_env(COOLDOWN_ENV, COOLDOWN_DEFAULT, 0)


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
    """잠그는 요청: 직원 주소 아래의 쓰기 요청. 공고 찾아보기 시작(POST /staff/scout)만 연다. 읽기만 하는 직원 화면도 연다.
    경로 끝의 / 는 같은 주소로 본다(주소를 살짝 바꿔 잠금을 피하지 못하게)."""
    if method not in UNSAFE_METHODS or not (path == "/staff" or path.startswith("/staff/")):
        return False
    return (method, path.rstrip("/") or "/") not in OPEN_WRITES


def _blocked_page(request: Request) -> Response:
    return request.app.state.templates.TemplateResponse(request, "demo_blocked.html", {"line": BLOCKED_LINE}, status_code=403)


def install(app: FastAPI) -> None:
    """create_app 이 인터넷 판 모드에서만 부른다."""
    state = app.state
    log = state.review_log
    if getattr(log, "entries", None) is not None:      # 상담마다 검수 로그를 몇 줄씩 쌓는다: 길이를 제한한다
        write = log.write
        log.write = lambda entry: (write(entry), _trim(log.entries))[0]
    state.demo_inputs = _load_demo_inputs()
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
        if kst_today() != state.cfg.as_of:      # 자정(한국 시간)이 지났다: 이 요청부터 새 날짜(표·저장본을 그날 기준으로 다시 읽는다. 하루에 한 번)
            await run_in_threadpool(state.roll_today)
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


@router.get("/demo/{pid}")
def demo_farm(request: Request, pid: str) -> Response:
    """농가 P1~P5 의 답이 채워진 확인 화면으로 보낸다(이미 받고 있는 지원 칸도 채운다). 거기서 '결과 보기'만 누르면 된다."""
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
