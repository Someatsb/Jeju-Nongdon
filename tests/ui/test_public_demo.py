"""공개 체험판 모드(JC_PUBLIC_DEMO=1): 직원 쓰기 잠금, 문자 번호 저장 안 함, 실제 AI 길 안 탐, Origin 검사, 시연 농가 바로 해 보기.

PC 모드(환경변수 없음)가 그대로인지도 함께 본다.
"""
import json
import os
import re
from pathlib import Path

import pytest

from app.config import APP_ROOT, load_config
from app.ui import public_demo
from app.ui.session import COOKIE, SessionStore

from .conftest import _started_client

DEMO = json.loads((APP_ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
HOST = "127.0.0.1:8765"
PHONE = "010" + "-7391-" + "2846"
PHONE_DIGITS = "010" + "7391" + "2846"


@pytest.fixture
def pub(monkeypatch):
    monkeypatch.setenv("JC_PUBLIC_DEMO", "1")
    c = _started_client(["--asof", "2026-11-13", "--replay"])
    yield c
    c.__exit__(None, None, None)


def test_pc_mode_is_unchanged_without_env(client_replay):
    assert load_config([]).public_demo is False
    assert "시연 농가로 해 보기" not in client_replay.get("/").text
    assert client_replay.get("/demo/P1").status_code == 404
    # PC 모드는 지금처럼 127.0.0.1:포트 Origin 만 받는다
    assert client_replay.post("/counsel/new", headers={"Origin": "https://x.example"}).status_code == 403


def test_public_mode_needs_replay(monkeypatch):
    monkeypatch.setenv("JC_PUBLIC_DEMO", "1")
    from app.ui.app import create_app
    with pytest.raises(RuntimeError):
        create_app(load_config(["--asof", "2026-11-13"]))


def test_home_has_demo_farms(pub):
    html = pub.get("/").text
    assert "시연 농가로 해 보기" in html and public_demo.INTRO_LINE in html
    assert re.findall(r'href="/demo/(P\d)"', html) == list(public_demo.DEMO_IDS)


@pytest.mark.parametrize("pid", ["P1", "P2", "P3", "P4", "P5"])
def test_demo_farm_reaches_ai_result(pub, pid):
    r = pub.get(f"/demo/{pid}")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/confirm"
    confirm = pub.get("/counsel/confirm").text
    for key in DEMO[pid]["already"]:
        assert re.search(rf'<input[^>]*value="{key}"[^>]*checked|<input[^>]*checked[^>]*value="{key}"', confirm), key
    form = {"already": DEMO[pid]["already"]}
    if DEMO[pid]["form"].get("direct_payment_education") in ("Y", "N"):
        form["direct_payment_education"] = DEMO[pid]["form"]["direct_payment_education"]
    assert pub.post("/counsel/confirm", data=form).status_code == 303
    html = pub.get("/counsel/preview").text
    assert "저장해 둔 AI 답변과 입력이 달라서" not in html      # 녹화와 같은 입력이다
    assert "AI가 쉬운 말로 설명 문장을 썼어요" in html or "일부는 미리 써 둔 기본 문장" in html
    assert pub.get("/counsel/print").status_code == 200


def test_unknown_demo_id_goes_home(pub):
    assert pub.get("/demo/P9").headers["location"] == "/"


def test_direct_input_gives_rule_result(pub):
    form = dict(DEMO["P2"]["form"], crop1_area_py="3100")
    assert pub.post("/counsel/input", data=form).status_code == 303
    assert pub.post("/counsel/confirm", data={}).status_code == 303
    html = pub.get("/counsel/preview").text
    assert "저장해 둔 AI 답변과 입력이 달라서 기본 문장으로 나왔어요" in html
    assert "data/replay" not in html and "M-P" not in html     # 서버 파일 이름이 화면에 나오지 않는다


LOCKED = [("POST", "/staff/scout"), ("POST", "/staff"), ("PUT", "/staff/notice/x"), ("DELETE", "/staff/notice/x"),
          ("PATCH", "/staff/scout"), ("POST", "/staff/tables/upload"), ("POST", "/staff/keys")]


@pytest.mark.parametrize("method,path", LOCKED)
def test_staff_writes_are_locked(pub, method, path):
    r = pub.request(method, path, headers={"Origin": f"http://{HOST}"})
    assert r.status_code == 403 and public_demo.BLOCKED_LINE in r.text
    assert pub.app.state.scout.job is None      # 새 공고 찾아보기는 시작되지 않았다


def test_staff_read_screens_stay_open_and_hide_internals(pub):
    for path in ("/staff", "/supports", "/typesheet"):
        r = pub.get(path)
        assert r.status_code == 200, path
        for secret in ("ANTHROPIC", "JC_", ".env", "C:\\", str(APP_ROOT)):
            assert secret not in r.text, (path, secret)
    assert pub.get("/staff/scout").status_code == 303      # 시작하지 않고 직원 메뉴로


def _snapshot_files() -> dict:
    out = {}
    for base in (APP_ROOT / "data", APP_ROOT / "logs"):
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file():
                    out[str(p)] = p.stat().st_mtime_ns
    return out


def test_reminder_never_stores_the_number(pub, monkeypatch, caplog):
    from app.data_layer import reminders, store
    monkeypatch.setattr(reminders, "save", lambda *a, **k: pytest.fail("체험판이 번호를 저장하려 했어요"))
    monkeypatch.setattr(store, "log", lambda *a, **k: pytest.fail("체험판이 기록을 남기려 했어요"))
    pub.get("/demo/P1")
    pub.post("/counsel/confirm", data={"already": DEMO["P1"]["already"]})
    before = _snapshot_files()
    with caplog.at_level("DEBUG"):
        r = pub.post("/counsel/reminder", data={"reminder_phone": PHONE, "reminder_consent": "on"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and body["line"] == public_demo.REMINDER_LINE
    assert PHONE not in r.text and PHONE_DIGITS not in r.text
    assert PHONE not in caplog.text and PHONE_DIGITS not in caplog.text
    assert _snapshot_files() == before             # 자료 폴더·로그 폴더에 새 파일이 없다
    held = repr(pub.app.state.sessions._by_id)
    assert PHONE not in held and PHONE_DIGITS not in held
    assert pub.get("/counsel/reminder-status").text == ""


def _guard_env(real):
    def read_text(self, *a, **k):
        assert self.name != ".env", ".env 를 읽으려 했어요"
        return real(self, *a, **k)
    return read_text


def test_real_ai_path_is_never_taken(pub, monkeypatch):
    """공개 체험판은 .env·열쇠 저장소를 읽지 않고 실제 AI 클라이언트를 만들지 않는다. 시연 농가·직원 화면까지 모두."""
    from app.agents.llm import keystore
    from app.ui import app as app_mod, replay as replay_mod

    def boom(*a, **k):
        pytest.fail("실제 AI 길을 탔어요")
    monkeypatch.setattr(keystore.KeyStore, "get", boom)
    monkeypatch.setattr(app_mod, "make_llm_client", boom)
    monkeypatch.setattr(Path, "read_text", _guard_env(Path.read_text))
    for pid in ("P1", "P3"):
        pub.get(f"/demo/{pid}")
        pub.post("/counsel/confirm", data={"already": DEMO[pid]["already"]})
        assert pub.get("/counsel/preview").status_code == 200
        assert pub.get("/counsel/ai").status_code == 200
        assert pub.get("/counsel/match-staff").status_code == 200
    assert pub.get("/staff").status_code == 200
    assert pub.post("/staff/scout", headers={"Origin": f"http://{HOST}"}).status_code == 403
    assert pub.app.state.cfg.replay and pub.app.state.scout.llm is None
    assert replay_mod.NO_MATCH_RECORDING not in pub.get("/counsel/match-staff").text


# --- Origin / Host -----------------------------------------------------------------------------------

def test_origin_same_host_passes_even_behind_https_proxy(pub):
    h = {"Host": "demo.example.onrender.com", "Origin": "https://demo.example.onrender.com", "X-Forwarded-Proto": "https"}
    assert pub.post("/counsel/new", headers=h).status_code == 303
    assert pub.post("/counsel/new", headers={"Host": HOST, "Origin": f"http://{HOST}"}).status_code == 303
    fwd = {"Host": "internal:10000", "X-Forwarded-Host": "pub.example", "X-Forwarded-Proto": "https", "Origin": "https://pub.example"}
    assert pub.post("/counsel/new", headers=fwd).status_code == 303
    assert pub.post("/counsel/new").status_code == 303      # Origin 이 없는 요청은 브라우저가 보낸 것이 아니다


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://demo.example.onrender.com",
                                    "https://demo.example.onrender.com.evil.example"])
def test_origin_other_site_is_blocked(pub, origin):
    h = {"Host": "demo.example.onrender.com", "Origin": origin, "X-Forwarded-Proto": "https"}
    assert pub.post("/counsel/new", headers=h).status_code == 403
    assert pub.post("/counsel/confirm", headers=h, data={}).status_code == 403
    assert pub.post("/staff/scout", headers=h).status_code == 403


def test_any_host_is_accepted_in_public_mode(pub):
    assert pub.get("/health", headers={"Host": "demo.example.onrender.com"}).json()["ok"] is True


def test_same_origin_helper():
    assert public_demo.same_origin({"host": "a.b"}, "http")
    assert public_demo.same_origin({"host": "a.b", "origin": "https://a.b", "x-forwarded-proto": "https"}, "http")
    assert not public_demo.same_origin({"host": "a.b", "origin": "https://a.b"}, "http")
    assert public_demo.same_origin({"host": "a.b", "origin": "https://a.b", "x-forwarded-proto": "https, http"}, "http")


# --- 세션·메모리 ---------------------------------------------------------------------------------------

def test_sessions_are_per_cookie(pub):
    from fastapi.testclient import TestClient
    other = TestClient(pub.app, base_url=str(pub.base_url), follow_redirects=False)
    pub.get("/demo/P1")
    assert pub.cookies.get(COOKIE) and other.cookies.get(COOKIE) is None
    assert other.get("/counsel/confirm").status_code == 303      # 남의 상담이 보이지 않고 입력 화면으로 간다
    other.get("/demo/P2")
    assert other.cookies.get(COOKIE) != pub.cookies.get(COOKIE)


def test_session_cap_drops_oldest():
    t = [0.0]
    s = SessionStore(clock=lambda: t[0], max_sessions=3)
    ids = []
    for i in range(5):
        t[0] += 1
        ids.append(s.put(None, n=i))
    assert len(s._by_id) == 3 and s.get(ids[0]) is None and s.get(ids[4]) == {"n": 4}


def test_session_default_has_no_cap():
    s = SessionStore()
    assert s.max_sessions is None
    for i in range(200):
        s.put(None, n=i)
    assert len(s._by_id) == 200


def test_public_mode_sets_session_cap_and_bounded_log(pub):
    assert pub.app.state.sessions.max_sessions == public_demo.MAX_SESSIONS
    log = pub.app.state.review_log
    for i in range(public_demo.MAX_LOG_ENTRIES + 10):
        log.write({"i": i})
    assert len(log.entries) <= public_demo.MAX_LOG_ENTRIES


def test_serve_builds_public_app(monkeypatch):
    monkeypatch.delenv("JC_PUBLIC_DEMO", raising=False)
    from app import serve
    try:
        app = serve.make_app(8981)
        assert os.environ["JC_PUBLIC_DEMO"] == "1"
    finally:
        os.environ.pop("JC_PUBLIC_DEMO", None)
    cfg = app.state.cfg
    assert cfg.public_demo and cfg.replay and cfg.demo_asof and cfg.as_of.isoformat() == "2026-11-13"


def test_session_cap_keeps_in_progress_over_idle():
    t = [0.0]
    s = SessionStore(clock=lambda: t[0], max_sessions=3)
    victim = s.put(None, profile=1, job=object())
    t[0] += 1
    for _ in range(10):
        t[0] += 1
        s.put(None, profile=1, job=None)
    assert s.get(victim) is not None and len(s._by_id) <= 3


def test_public_cookie_is_lax_but_pc_cookie_stays_strict(pub):
    from starlette.responses import Response
    from app.ui.session import set_session_cookie
    assert public_demo.MAX_SESSIONS >= 200
    assert "samesite=lax" in pub.get("/demo/P1", follow_redirects=False).headers["set-cookie"].lower()
    r = Response()
    set_session_cookie(r, "x")
    assert "samesite=strict" in r.headers["set-cookie"].lower()


def test_home_says_date_is_fixed(pub):
    assert "11월 13일로 고정" in pub.get("/").text
