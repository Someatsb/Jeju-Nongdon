"""FastAPI 앱 뼈대(Task 6, U06).

- 보안: Host는 127.0.0.1·localhost만(DNS 리바인딩 차단). POST·PUT·PATCH·DELETE에 Origin이 있으면
  이 앱 주소(같은 포트의 127.0.0.1·localhost)여야 한다(다른 사이트·다른 로컬 앱의 요청 차단).
  Origin이 없는 요청은 브라우저가 보낸 것이 아니므로 통과시킨다(Edge는 POST마다 Origin을 붙인다).
- 공통 머리: 모든 화면 템플릿은 templates/base.html을 상속한다. 템플릿에는 `cfg`(Config),
  `header`(core.models.Header, 아직 없으면 None), `replay_note`(재생 모드일 때만 바닥 작은 글씨, 아니면 None)가
  늘 들어간다. 뒤 작업은 `app.state.header`·`app.state.replay_banner`를 채우면 된다.
- 인쇄 연결(Task 21): `app.state.snapshot`·`data_version`·`narrator`·`review_log`. 종이 경로는 routes_counsel.py.
- 첫 화면(routes_home.py)·유형별 종이(routes_typesheet.py): Task 23.
- 상담 세션: `app.state.sessions`(ui/session.py, 쿠키로 찾는 메모리 저장소). 상담 화면은 routes_counsel.py.
"""
import logging
import threading
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agents.counsel import narrate
from app.agents.llm.factory import make_llm_client
from app.agents.llm.guard import Guard, SideCap
from app.agents.llm.keystore import KeyStore
from app.agents.reviewer import MemoryReviewLog
from app.config import APP_ROOT, Config, kst_today
from app.core.models import Header
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from app.ui import match_job, routes_confirm, routes_counsel, routes_home, routes_staff, routes_supports, routes_typesheet
from app.ui import public_demo
from app.ui.replay import install_replay
from app.ui.result_view import notice_box, tel_nb
from app.ui.scout_job import ScoutLimits, ScoutRunner
from app.ui.session import SessionStore

UI_DIR = Path(__file__).resolve().parent
REPLAY_NOTE = "체험 모드 · 미리 저장해 둔 AI 답변을 써요"
SIDE_DAILY_CAP = 60   # 맞춰 보기·새 공고 찾아보기가 하루에 쓸 수 있는 AI 호출 수(전체 200 중. 나머지는 어르신 설명 글 몫)
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
log = logging.getLogger(__name__)



class NoCacheStatic(StaticFiles):
    """화면을 고친 뒤에도 브라우저가 옛 CSS·JS 를 붙들지 않게 한다(매번 서버에 바뀌었는지 물어본다)."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _common_context(request: Request) -> dict:
    state = request.app.state
    # 재생(체험) 모드면 화면 맨 아래에 작은 글씨 한 줄만 보인다. 띠·날짜 칩은 없다.
    note = None
    if state.replay_banner:
        d = routes_supports.today_of(request)                     # 첫 화면·목록이 세는 '오늘'을 줄에 밝힌다
        note = f"{REPLAY_NOTE} · 오늘을 {d.year}년 {d.month}월 {d.day}일로 보고 보여 드려요"
    return {"cfg": state.cfg, "header": state.header, "replay_note": note}


def create_app(cfg: Config, *, llm=None) -> FastAPI:
    """llm: 시험용으로 끼우는 LLMClient. 없으면 저장된 열쇠로 만든다(열쇠가 없으면 NullClient → 템플릿 문장).
    인터넷 판(cfg.public_demo)은 날짜를 한국 시간 오늘로 정하고(요청마다 바뀌었는지 본다), 열쇠는 환경변수에서만 읽는다."""
    if cfg.public_demo:
        cfg = replace(cfg, as_of=kst_today(), demo_asof=False)      # 인터넷 판은 시연 기준일이 없다: 늘 오늘
    app = FastAPI(title="제주 농돈", docs_url=None, redoc_url=None, openapi_url=None)   # 센터 PC 안에서만 쓰므로 API 문서 화면은 끈다
    app.state.cfg = cfg
    app.state.header = None          # Header: 아래에서 표·저장본을 읽은 뒤 채운다
    app.state.replay_banner = None   # 재생 녹화 설명 문구(화면에는 안 찍고 replay_note 여부만 정한다): --replay면 ui/replay.install_replay가 채운다(Task 32)
    app.state.replay_line = None     # 종이에 찍는 숫자 없는 재생 표시 줄(재생 모드만)
    app.state.replay_check = None    # Callable[[FactSheet], str | None]: 녹화와 입력이 다르면 화면에 보일 한국어 문구
    app.state.sessions = SessionStore()
    app.state.tables = load_tables(cfg.tables_dir, cfg.as_of)   # TableBundle: 앱을 만들 때 한 번만 읽는다
    app.state.snapshot = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=app.state.tables.crops)   # Snapshot: 같다
    app.state.data_version = f"표{app.state.tables.verified_date.isoformat()}+저장본{app.state.snapshot.built_at.isoformat()}"
    tables, snap = app.state.tables, app.state.snapshot
    app.state.header = Header(price_as_of=snap.price_as_of, citrus_as_of=snap.citrus_as_of, tables_verified=tables.verified_date,
                              snapshot_built=snap.built_at, refresh_ok=None, demo_asof=cfg.demo_asof)
    app.state.narrator = None        # Callable[[FactSheet], Narrative] | None: 설명 문장 에이전트(Task 28)
    app.state.matcher = None         # Callable[[FarmProfile, FactSheet, notices], MatchReport] | None: 새 공고 맞춰 보기(match_job). 없으면 맞춰 보기는 없음
    app.state.ai_live = False        # 실제 AI 클라이언트가 있나(키가 있고 공급자를 아는 것): 인터넷 판 직원 화면 한 줄·찾아보기 시작 점검이 쓴다
    app.state.scout = ScoutRunner(replay=cfg.replay, as_of=cfg.as_of, replay_dir=cfg.replay_dir,
                                  catalog_dir=None if cfg.catalog_dir == APP_ROOT / "data" / "catalog" else cfg.catalog_dir)   # 직원 메뉴 새 공고 찾아보기(scout_job). 실제 AI 는 아래에서 끼운다
    app.state.review_log = None      # 검수 로그(MemoryReviewLog 등, .entries): 있으면 검수 과정 보기에 걸린 규칙을 보인다
    app.state.templates = templates = Jinja2Templates(
        directory=UI_DIR / "templates", context_processors=[_common_context])
    templates.env.filters["tel"] = tel_nb          # 전화번호 한 덩어리(줄바꿈 금지)
    templates.env.filters["nnv"] = notice_box      # "지금 접수 중인 공고" 상자의 띠·남은 날 글
    if cfg.replay:
        install_replay(app, cfg.replay_dir)   # 띠·종이 줄·녹화 설명(narrator)·검수 로그. 실제 LLM은 만들지 않는다
    else:
        if cfg.public_demo:
            # 인터넷 판: 키는 환경변수에서만(열쇠 저장소·.env 를 열지 않는다), 날짜는 한국 시간 오늘, 하루 한도는 JC_AI_DAILY_MAX. 세는 곳은 Guard 한 군데
            cap = public_demo.daily_max()
            if llm is not None:
                client = Guard(llm, daily_cap=cap, today_fn=kst_today)
            else:
                client = make_llm_client(KeyStore.env_only(), today_fn=kst_today, daily_cap=cap)
            today_of_ai = kst_today
        else:
            client = llm if llm is not None else make_llm_client(KeyStore(), today_fn=lambda: cfg.as_of)
            today_of_ai = lambda: cfg.as_of      # noqa: E731
        app.state.ai_live = getattr(client, "provider", "none") != "none"
        app.state.review_log = log = MemoryReviewLog()
        side = SideCap(client, public_demo.daily_max() if cfg.public_demo else SIDE_DAILY_CAP, today_fn=today_of_ai)   # 맞춰 보기·찾아보기 몫(설명 글 몫은 남긴다). 인터넷 판은 따로 몫을 두지 않는다: 하루 한도(JC_AI_DAILY_MAX)는 Guard 하나만 센다
        app.state.scout.llm = side        # 전체 하루 한도(Guard)는 상담과 같은 클라이언트가 세고, 이 몫은 따로 센다
        if cfg.public_demo:
            app.state.scout.limits = ScoutLimits(cooldown_s=public_demo.scout_cooldown_min() * 60, has_ai=lambda: app.state.ai_live,
                                                 exhausted=lambda: side.exhausted() or (isinstance(client, Guard) and client.exhausted()))
        app.state.matcher = match_job.make_matcher(side, tables.crops, cfg.as_of)    # 열쇠가 없으면 NullClient 라 AI 호출 없이 없음으로 끝난다
        app.state.narrator = lambda fs: narrate(fs, client, log, parallel=True)   # 구획을 동시에(재생은 차례대로). 열쇠가 없으면 NullClient라 모델 호출 없이 템플릿 문장
    allowed_origins = frozenset(f"http://{host}:{cfg.port}" for host in ALLOWED_HOSTS)

    if cfg.public_demo:
        app.state.roll_today = _make_roll_today(app, side if not cfg.replay else None)
        public_demo.install(app)      # 인터넷 판: Origin 은 요청의 Host 와 같은 곳이면 통과, 직원 쓰기(찾아보기 제외)·문자 번호 저장은 잠근다. Host 검사는 하지 않는다(인터넷 주소)
    else:
        @app.middleware("http")
        async def check_origin(request: Request, call_next):
            origin = request.headers.get("origin")
            if request.method in UNSAFE_METHODS and origin is not None and origin not in allowed_origins:
                return PlainTextResponse("이 프로그램 화면에서 보낸 요청만 받아요.", status_code=403)
            return await call_next(request)

        # 나중에 더한 미들웨어가 바깥에서 먼저 돈다: Host 검사 → Origin 검사 → 경로.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS))
    app.mount("/static", NoCacheStatic(directory=UI_DIR / "static"), name="static")
    app.include_router(routes_counsel.router)
    app.include_router(routes_confirm.router)
    app.include_router(routes_home.router)
    app.include_router(routes_typesheet.router)
    app.include_router(routes_staff.router)
    app.include_router(routes_supports.router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        """브라우저로 없는 주소를 열면 쉬운 한국어 화면을 보여 준다(그 밖의 요청은 기본 응답 그대로)."""
        if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
            return templates.TemplateResponse(request, "error.html", {}, status_code=404)
        return await http_exception_handler(request, exc)

    @app.get("/health")
    def health() -> dict:
        c = app.state.cfg      # 인터넷 판은 날짜가 바뀔 수 있어 매번 지금 설정을 읽는다
        return {"ok": True, "as_of": c.as_of.isoformat(), "demo": c.demo_asof}

    return app


def _make_roll_today(app: FastAPI, side):
    """인터넷 판: 한국 시간 날짜가 바뀌면 그날 기준으로 설정·표·저장본·맞춰 보기를 다시 만든다. 하루에 한 번만 일어나고, 실패하면 옛 것을 그대로 쓴다."""
    lock = threading.Lock()

    def roll_today() -> None:
        with lock:
            today = kst_today()
            state = app.state
            if state.cfg.as_of == today:
                return
            new_cfg = replace(state.cfg, as_of=today)
            try:
                tables = load_tables(new_cfg.tables_dir, today)
                snap = load_snapshot(new_cfg.snapshot_dir, today, crops=tables.crops)
            except Exception:       # 표·저장본을 못 읽어도 어제 것으로 계속 돈다(다음 요청에서 다시 해 본다)
                log.exception("날짜가 바뀌어 표를 다시 읽다가 실패했어요. 어제 것으로 계속해요")
                return
            state.data_version = f"표{tables.verified_date.isoformat()}+저장본{snap.built_at.isoformat()}"
            state.header = Header(price_as_of=snap.price_as_of, citrus_as_of=snap.citrus_as_of, tables_verified=tables.verified_date,
                                  snapshot_built=snap.built_at, refresh_ok=None, demo_asof=False)
            state.tables, state.snapshot = tables, snap
            state.scout.as_of = today
            if side is not None:
                state.matcher = match_job.make_matcher(side, tables.crops, today)
            state.cfg = new_cfg      # 맨 나중에: 이 줄이 보이는 순간 새 날짜와 새 자료가 함께 보이게
    return roll_today
