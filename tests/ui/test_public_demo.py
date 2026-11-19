"""인터넷 판 모드(JC_PUBLIC_DEMO=1): 오늘 날짜(한국 시간), 환경변수 키로 만든 실제 AI 길(가짜 어댑터), 하루 한도, 공고 찾아보기 제한,
직원 쓰기 잠금, 문자 번호 저장 안 함, Origin 검사, 농가 바로 해 보기. 인터넷·실제 AI 는 쓰지 않는다(가짜 AI).

PC 모드(환경변수 없음)가 그대로인지도 함께 본다.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from scout_fixtures import FX, HAPPY, Script  # noqa: E402

from app import config  # noqa: E402
from app.agents.llm.base import GenResult, LLMUnavailable  # noqa: E402
from app.config import APP_ROOT, load_config  # noqa: E402
from app.data_layer.notice_board import fixture_http  # noqa: E402
from app.ui import public_demo, scout_job  # noqa: E402
from app.ui.session import COOKIE, SessionStore  # noqa: E402

from .conftest import P4_FORM, _started_client  # noqa: E402

DEMO = json.loads((APP_ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
HOST = "127.0.0.1:8765"
ORIGIN = {"Origin": f"http://{HOST}"}
PHONE = "010" + "-7391-" + "2846"
PHONE_DIGITS = "010" + "7391" + "2846"
BANNED = ("체험판", "시연", "고정")
TEXT = {"support": "{P:%s}은 맞는지 창구에서 확인해 보세요.",
        "insurance": "{P:%s}은 가입할 수 있는 때를 농협 창구에서 알아보세요.",
        "action": "{P:%s}부터 챙기면 다른 제도 신청이 쉬워져요.",
        "empty": "{P:%s}은 그대로 이어가세요."}


class FakeAI:
    """요청의 첫 근거를 인용하는 규칙 통과 문장을 돌려주는 가짜 AI(설명·판정만. 맞춰 보기 따위는 못 쓰는 것으로 한다). 부른 횟수를 센다."""
    provider = model = "fake"

    def __init__(self):
        self.calls = 0
        self.purposes: list[str] = []

    def generate(self, req):
        self.calls += 1
        self.purposes.append(req.purpose)
        if req.purpose == "judge":
            text = '{"verdict": "PASS", "reason_code": null}'
        elif req.purpose == "narrate":
            item = json.loads(req.messages[0].text.split("\n\n")[0])["items"][0]
            text = json.dumps({"section": req.section, "sentences": [
                {"sid": 1, "text": TEXT[req.section] % item["program_id"], "cites": [item["fact_id"]]}]}, ensure_ascii=False)
        else:
            raise LLMUnavailable("NO_KEY")
        return GenResult(text=text, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0, provider="fake", model="fake")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    """인터넷 판의 시계(UTC). 기본은 2026-11-19 03:00 UTC(= 한국 12시). now 를 바꾸면 다음 요청부터 그 시각이다."""
    box = {"now": utc(2026, 11, 19, 3, 0)}
    monkeypatch.setattr(config, "_utcnow", lambda: box["now"])
    return box


def _public(monkeypatch, clock, llm=None, **env):
    monkeypatch.setenv("JC_PUBLIC_DEMO", "1")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    c = _started_client([], llm=llm)
    return c


@pytest.fixture
def ai():
    return FakeAI()


@pytest.fixture
def pub(monkeypatch, clock, ai):
    c = _public(monkeypatch, clock, ai)
    c.ai = ai
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def pub_nokey(monkeypatch, clock):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = _public(monkeypatch, clock)
    yield c
    c.__exit__(None, None, None)


def visible(html: str) -> str:
    """화면에 보이는 글만(스타일·스크립트와 HTML 주석은 뺀다. 종이 HTML 맨 위의 개발자용 주석에 '고정 높이' 같은 말이 있다)."""
    no_blocks = re.sub(r"<(style|script).*?</(style|script)>", "", html, flags=re.S | re.I)
    return re.sub(r"<!--.*?-->", "", no_blocks, flags=re.S)


def walk(c, form=P4_FORM):
    assert c.post("/counsel/input", data=form, headers=ORIGIN).status_code == 303
    assert c.post("/counsel/confirm", data={}, headers=ORIGIN).status_code == 303


def result_page(c, secs=5.0) -> str:
    """결과 화면을 열고 AI 글이 끝날 때까지 기다린 뒤 다시 연다(끝난 뒤 화면)."""
    c.get("/counsel/preview")
    end = time.monotonic() + secs
    while time.monotonic() < end and c.get("/counsel/ai").json()["state"] == "run":
        time.sleep(0.05)
    return c.get("/counsel/preview").text


# --- PC 모드는 그대로 -------------------------------------------------------------------------------

def test_pc_mode_is_unchanged_without_env(client_replay):
    assert load_config([]).public_demo is False
    assert client_replay.get("/demo/P1").status_code == 404
    # PC 모드는 지금처럼 127.0.0.1:포트 Origin 만 받는다
    assert client_replay.post("/counsel/new", headers={"Origin": "https://x.example"}).status_code == 403
    assert not hasattr(client_replay.app.state, "roll_today")
    assert client_replay.app.state.scout.limits is None


# --- 날짜: 한국 시간 오늘 -----------------------------------------------------------------------------

@pytest.mark.parametrize("now,want", [
    (utc(2026, 11, 18, 14, 59), "2026-11-18"),     # 한국 23시 59분
    (utc(2026, 11, 18, 15, 0), "2026-11-19"),      # 한국 자정: UTC 로는 아직 전날 밤이다
    (utc(2026, 11, 18, 23, 30), "2026-11-19"),
    (utc(2026, 12, 31, 15, 0), "2027-01-01"),
])
def test_today_is_korean_time(monkeypatch, clock, ai, now, want):
    clock["now"] = now
    c = _public(monkeypatch, clock, ai)
    try:
        assert config.kst_today().isoformat() == want
        body = c.get("/health").json()
        assert body["ok"] is True and body["as_of"] == want and body["demo"] is False
        assert c.app.state.cfg.as_of.isoformat() == want and c.app.state.cfg.demo_asof is False
    finally:
        c.__exit__(None, None, None)


def test_date_rolls_over_on_next_request_without_restart(pub, clock):
    st = pub.app.state
    assert pub.get("/health").json()["as_of"] == "2026-11-19"
    tables_before, matcher_before = st.tables, st.matcher
    clock["now"] = utc(2026, 11, 19, 14, 59)        # 한국 23시 59분: 아직 같은 날
    assert pub.get("/health").json()["as_of"] == "2026-11-19" and st.tables is tables_before
    clock["now"] = utc(2026, 11, 19, 15, 1)         # 한국 자정이 지났다
    assert pub.get("/health").json()["as_of"] == "2026-11-20"
    assert st.cfg.as_of.isoformat() == "2026-11-20" and st.scout.as_of.isoformat() == "2026-11-20"
    assert st.tables is not tables_before and st.matcher is not matcher_before     # 그날 기준으로 다시 읽었다
    assert pub.get("/health").json()["as_of"] == "2026-11-20"
    walk(pub)                                       # 새 날짜로 결과도 정상
    assert pub.get("/counsel/preview").status_code == 200


def test_screens_follow_the_current_date(pub, clock):
    """결과 화면·첫 화면이 요청마다 오늘 날짜를 쓴다: 날짜가 바뀌면 상담 설명 지문(날짜 포함)이 달라진다."""
    walk(pub)
    first = pub.get("/counsel/preview").text
    fp1 = re.search(r"계산 지문 ([0-9a-f]+)", first)
    clock["now"] = utc(2026, 11, 22, 3, 0)
    pub.post("/counsel/new", headers=ORIGIN)
    walk(pub)
    second = pub.get("/counsel/preview").text
    assert pub.app.state.cfg.as_of.isoformat() == "2026-11-22"
    fp2 = re.search(r"계산 지문 ([0-9a-f]+)", second)
    assert fp1 and fp2 and fp1.group(1) != fp2.group(1)


def test_rollover_failure_keeps_old_data(pub, clock, monkeypatch):
    from app.ui import app as app_mod
    before = pub.app.state.tables

    def boom(*a, **k):
        raise OSError("디스크 오류")
    monkeypatch.setattr(app_mod, "load_tables", boom)
    clock["now"] = utc(2026, 11, 25, 3, 0)
    r = pub.get("/health")
    assert r.status_code == 200 and r.json()["as_of"] == "2026-11-19"      # 어제 것으로 계속
    assert pub.app.state.tables is before
    monkeypatch.undo()
    monkeypatch.setattr(config, "_utcnow", lambda: utc(2026, 11, 25, 3, 0))
    assert pub.get("/health").json()["as_of"] == "2026-11-25"               # 다음 요청에서 다시 해 보고 성공한다


# --- 실제 AI 길(가짜 어댑터) -----------------------------------------------------------------------------

class FakeAnthropic(FakeAI):
    """AnthropicClient 를 갈아 끼우는 가짜(어댑터 자리): 받은 키·모델을 기억한다."""
    made: list = []

    def __init__(self, key, model="m"):
        super().__init__()
        self.key, self.model = key, model
        self.provider = "anthropic"
        FakeAnthropic.made.append(self)


def test_env_key_builds_the_real_path_and_adds_ai_sentences(monkeypatch, clock):
    from app.agents.llm import factory
    FakeAnthropic.made = []
    monkeypatch.setattr(factory, "AnthropicClient", FakeAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-only-0000")
    monkeypatch.setenv("JC_LLM_MODEL", "claude-test-model")
    c = _public(monkeypatch, clock)
    try:
        assert c.app.state.ai_live is True
        assert FakeAnthropic.made          # 이 PC 의 소켓 오류로 앱을 다시 만들면 둘 이상일 수 있다: 마지막 것이 지금 앱의 클라이언트
        fake = FakeAnthropic.made[-1]
        assert (fake.key, fake.model) == ("sk-test-only-0000", "claude-test-model")
        walk(c)
        html = result_page(c)
        assert "AI 문장 통과" in html and fake.calls > 0
        assert "사용 중" in c.get("/staff").text
        assert "sk-test-only-0000" not in html and "sk-test-only-0000" not in c.get("/staff").text
    finally:
        c.__exit__(None, None, None)


def test_unknown_provider_falls_back_without_crashing(monkeypatch, clock):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-only-0000")
    monkeypatch.setenv("JC_LLM_PROVIDER", "nobody")
    c = _public(monkeypatch, clock)
    try:
        assert c.app.state.ai_live is False
        walk(c)
        assert c.get("/counsel/preview").status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_no_key_gives_rule_result_and_does_not_crash(pub_nokey):
    st = pub_nokey.app.state
    assert st.ai_live is False and not st.cfg.replay
    walk(pub_nokey)
    html = result_page(pub_nokey)
    assert "기본 문장(템플릿)" in html and "AI 문장 통과" not in html
    assert pub_nokey.get("/counsel/ai").json()["state"] == "done"
    assert pub_nokey.get("/counsel/match-staff").status_code == 200
    assert "기본 문장 사용 중" in pub_nokey.get("/staff").text
    assert pub_nokey.get("/counsel/print").status_code == 200


def test_env_file_and_keyring_are_never_read(monkeypatch, clock, tmp_path):
    """인터넷 판은 .env 파일·열쇠 저장소를 열지 않는다(리눅스에는 열쇠 저장소가 없어 예외가 날 수 있다)."""
    import keyring
    from app.agents.llm import factory, keystore
    envfile = tmp_path / "custom.env"
    envfile.write_text("ANTHROPIC_API_KEY=sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("JC_ENV_FILE", str(envfile))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    real_read = Path.read_text

    def read_text(self, *a, **k):
        assert self.name not in (".env", "custom.env"), f"{self.name} 를 읽으려 했어요"
        return real_read(self, *a, **k)

    def boom(*a, **k):
        pytest.fail("열쇠 저장소·.env 읽기 길을 탔어요")
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(keyring, "get_keyring", boom)
    monkeypatch.setattr(keystore, "read_env_file", boom)
    monkeypatch.setattr(keystore, "read_env_value", boom)
    monkeypatch.setattr(factory, "AnthropicClient", lambda *a, **k: pytest.fail("키가 없는데 실제 어댑터를 만들었어요"))
    c = _public(monkeypatch, clock)
    try:
        assert c.app.state.ai_live is False
        walk(c)
        assert c.get("/counsel/preview").status_code == 200
        assert c.get("/staff").status_code == 200
        assert "기본 문장 사용 중" in c.get("/staff").text
    finally:
        c.__exit__(None, None, None)


def test_env_only_keystore_unit(monkeypatch):
    from app.agents.llm.keystore import KeyStore
    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-x ")
    monkeypatch.delenv("JC_LLM_MODEL", raising=False)
    store = KeyStore.env_only()
    assert store.get("llm") == "sk-x" and store.get_setting("JC_LLM_MODEL") == "claude-opus-5-5"
    assert store.get("hub") is None
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert store.get("llm") is None
    with pytest.raises(RuntimeError):
        store.set("llm", "x")
    assert store.test().ok is False


# --- 하루 한도 -------------------------------------------------------------------------------------------

def test_daily_cap_stops_ai_and_screens_stay_normal(monkeypatch, clock, ai):
    c = _public(monkeypatch, clock, ai, JC_AI_DAILY_MAX="3")
    try:
        walk(c)
        result_page(c)
        assert ai.calls == 3                                   # 셋째까지만 나가고 더 부르지 않았다
        html = result_page(c)
        assert c.get("/counsel/preview").status_code == 200 and "기본 문장" in html
        assert c.get("/counsel/print").status_code == 200
        c.post("/counsel/new", headers=ORIGIN)
        walk(c, {**P4_FORM, "crop1_area_py": "3200", "total_area_py": "3200"})
        result_page(c)
        assert ai.calls == 3 and c.get("/counsel/ai").json()["state"] == "done"     # 다른 상담도 AI 를 안 부르고 정상
        # 다음 날(한국 시간)이면 다시 열린다
        clock["now"] = utc(2026, 11, 19, 16, 0)
        c.get("/health")
        c.post("/counsel/new", headers=ORIGIN)
        walk(c, {**P4_FORM, "crop1_area_py": "3300", "total_area_py": "3300"})
        result_page(c)
        assert ai.calls > 3
    finally:
        c.__exit__(None, None, None)


def test_daily_max_env_parsing(monkeypatch):
    monkeypatch.delenv("JC_AI_DAILY_MAX", raising=False)
    assert public_demo.daily_max() == 400
    for text, want in (("50", 50), ("abc", 400), ("0", 400), ("-3", 400), ("", 400)):
        monkeypatch.setenv("JC_AI_DAILY_MAX", text)
        assert public_demo.daily_max() == want
    monkeypatch.delenv("JC_SCOUT_COOLDOWN_MIN", raising=False)
    assert public_demo.scout_cooldown_min() == 10
    monkeypatch.setenv("JC_SCOUT_COOLDOWN_MIN", "0")
    assert public_demo.scout_cooldown_min() == 0
    monkeypatch.setenv("JC_SCOUT_COOLDOWN_MIN", "x")
    assert public_demo.scout_cooldown_min() == 10


def test_guard_counts_only_requests_that_go_out():
    from datetime import date
    from app.agents.llm.guard import Guard
    from app.agents.llm.base import GenRequest, Msg
    inner = FakeAI()
    day = [date(2026, 11, 19)]
    g = Guard(inner, daily_cap=2, today_fn=lambda: day[0])
    req = GenRequest(purpose="match", system="s", messages=(Msg(role="user", text="t"),))     # FakeAI 는 match 를 못 써서 매번 실패하지만 부른 수는 센다
    assert g.exhausted() is False
    for _ in range(2):
        with pytest.raises(LLMUnavailable) as e:
            g.generate(req)
        assert e.value.reason == "NO_KEY"
    assert inner.calls == 2 and g.exhausted() is True
    with pytest.raises(LLMUnavailable) as e:
        g.generate(req)
    assert e.value.reason == "DAILY_CAP" and inner.calls == 2
    day[0] = date(2026, 11, 20)
    assert g.exhausted() is False


# --- 공고 찾아보기: 열림·한 번에 하나·쉬는 시간·한도 ----------------------------------------------------------

NOT_RELEVANT = [("finish", {"decision": "NOT_RELEVANT", "reason": "시험용으로 해당 없음 처리"})]


def _fertilizer_steps():
    steps = json.loads((APP_ROOT / "data" / "replay" / "answers" / "S1.json").read_text(encoding="utf-8"))["notice"][4:8]
    return [[(c["name"], c["args"]) for c in st["tool_calls"]] for st in steps]


FULL = HAPPY + [NOT_RELEVANT] + _fertilizer_steps() + [NOT_RELEVANT]


@pytest.fixture
def scout_pub(monkeypatch, clock, tmp_path):
    import shutil
    shutil.copytree(APP_ROOT / "data" / "tables", tmp_path / "data" / "tables")
    script = Script(FULL * 3)
    c = _public(monkeypatch, clock, script)
    run = c.app.state.scout
    run.root, run.sleep, run.pace_s = tmp_path, (lambda s: None), 0
    run.http = fixture_http(FX)
    c.script, c.work = script, tmp_path
    yield c
    c.__exit__(None, None, None)


def _wait_scout(c, secs=20):
    end = time.monotonic() + secs
    j = {}
    while time.monotonic() < end:
        j = c.get("/staff/scout/status").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"끝나지 않았습니다: {j}")


def test_scout_opens_runs_and_then_rests(scout_pub):
    c = scout_pub
    r = c.post("/staff/scout", headers=ORIGIN)
    assert r.status_code == 303 and r.headers["location"] == "/staff/scout"
    j = _wait_scout(c)
    assert j["state"] == "done" and j["picked"] == 3
    assert list((c.work / "data" / "catalog" / "notices").glob("*.json"))       # 올린 공고는 서버 쪽 자리에 썼다
    assert "목록에 올림" in c.get("/staff/scout").text
    asked = len(c.script.requests)
    r = c.post("/staff/scout", headers=ORIGIN)           # 끝난 직후: 쉬는 시간
    assert r.status_code == 429 and "조금 전에 찾아봤어요. 10분 뒤에 다시 해 주세요." in r.text
    assert len(c.script.requests) == asked                # AI 를 더 부르지 않았다
    run = c.app.state.scout
    run.finished_at -= 4 * 60 + 30                         # 4분 30초 지남: 남은 5.5분 → 6분 뒤
    assert "6분 뒤에 다시 해 주세요" in c.post("/staff/scout", headers=ORIGIN).text
    run.finished_at -= 6 * 60                              # 10분이 지났다: 다시 돈다
    assert c.post("/staff/scout", headers=ORIGIN).status_code == 303
    assert _wait_scout(c)["state"] == "done"
    for body in (c.get("/staff").text, c.get("/staff/scout").text):
        assert not any(w in body for w in BANNED)


def test_scout_does_not_overlap(monkeypatch, clock, tmp_path):
    import shutil
    shutil.copytree(APP_ROOT / "data" / "tables", tmp_path / "data" / "tables")
    gate = threading.Event()

    class Slow(Script):
        def generate(self, req):
            if len(self.requests) == 1:
                assert gate.wait(10)
            return super().generate(req)
    llm = Slow(FULL)
    c = _public(monkeypatch, clock, llm)
    run = c.app.state.scout
    run.root, run.sleep, run.pace_s, run.http = tmp_path, (lambda s: None), 0, fixture_http(FX)
    try:
        assert c.post("/staff/scout", headers=ORIGIN).status_code == 303
        end = time.monotonic() + 10
        while time.monotonic() < end and c.get("/staff/scout/status").json().get("seen", 0) < 1:
            time.sleep(0.05)
        second = c.post("/staff/scout", headers=ORIGIN)           # 도는 중에 또 눌러도 새로 시작하지 않고 진행 화면으로
        assert second.status_code == 303 and second.headers["location"] == "/staff/scout"
        gate.set()
        assert _wait_scout(c)["state"] == "done"
        assert len([x for x in llm.requests if x.purpose == "scout"]) == 5
    finally:
        gate.set()
        c.__exit__(None, None, None)


def test_scout_refused_when_daily_cap_is_used(monkeypatch, clock, tmp_path):
    script = Script(FULL)
    c = _public(monkeypatch, clock, script, JC_AI_DAILY_MAX="1")
    try:
        from app.agents.llm.base import GenRequest, Msg
        req = GenRequest(purpose="narrate", system="s", messages=(Msg(role="user", text="t"),))
        guard = c.app.state.scout.limits
        assert guard.exhausted() is False
        c.app.state.scout.llm.generate(req)          # 한도 1: 한 번 부르면 오늘은 끝
        assert guard.exhausted() is True
        before = len(script.requests)
        r = c.post("/staff/scout", headers=ORIGIN)
        assert r.status_code == 429 and scout_job.CAP_LINE in r.text and "오늘은 AI 사용량이 다 찼어요. 내일 다시 해 주세요." in r.text
        assert len(script.requests) == before and c.app.state.scout.job is None
    finally:
        c.__exit__(None, None, None)


def test_matching_calls_do_not_use_up_scout_budget(monkeypatch, clock, ai):
    """맞춰 보기가 60번을 넘게 불려도(전체 한도 400 안) 찾아보기는 막히지 않는다. 인터넷 판은 한 몫을 따로 두지 않는다."""
    c = _public(monkeypatch, clock, ai)
    try:
        from app.agents.llm.base import GenRequest, Msg
        req = GenRequest(purpose="judge", system="s", messages=(Msg(role="user", text="t"),))
        assert c.app.state.scout.llm.cap == public_demo.daily_max() == 400
        for _ in range(61):
            c.app.state.scout.llm.generate(req)
        assert c.app.state.scout.limits.exhausted() is False
    finally:
        c.__exit__(None, None, None)


def test_scout_refused_without_key(pub_nokey):
    r = pub_nokey.post("/staff/scout", headers=ORIGIN)
    assert r.status_code == 429 and scout_job.NO_AI_LINE in r.text and pub_nokey.app.state.scout.job is None


def test_scout_disk_failure_does_not_kill_the_screens(scout_pub, monkeypatch):
    from app import cli

    def boom(*a, **k):
        raise PermissionError("읽기 전용 디스크")
    monkeypatch.setattr(cli, "scout_run", boom)
    assert scout_pub.post("/staff/scout", headers=ORIGIN).status_code == 303
    j = _wait_scout(scout_pub)
    assert j["state"] == "failed"
    assert scout_pub.get("/staff/scout").status_code == 200 and scout_pub.get("/staff").status_code == 200
    assert scout_job.BROKEN in scout_pub.get("/staff/scout").text


# --- 첫 화면·농가 바로 해 보기 ---------------------------------------------------------------------------------

def test_home_is_like_the_installed_one_and_has_no_demo_words(pub):
    html = pub.get("/").text
    assert not any(w in html for w in BANNED), [w for w in BANNED if w in html]
    assert "/demo/" not in html and "demo.css" not in html and "demo-only-note" not in html
    for pid in public_demo.DEMO_IDS:
        assert pub.get(f"/demo/{pid}", follow_redirects=False).status_code in (302, 303)


def test_no_demo_words_on_any_screen(pub):
    pages = ["/", "/staff", "/supports", "/typesheet", "/counsel/input", "/counsel/input?mode=proxy", "/no-such-page"]
    pub.get("/demo/P1")
    pub.post("/counsel/confirm", data={"already": DEMO["P1"]["already"]}, headers=ORIGIN)
    pages += ["/counsel/confirm"]
    for path in pages:
        r = pub.get(path, headers={"accept": "text/html"})
        assert not any(w in visible(r.text) for w in BANNED), (path, [w for w in BANNED if w in visible(r.text)])
    html = visible(result_page(pub))
    assert not any(w in html for w in BANNED), [w for w in BANNED if w in html]
    paper = visible(pub.get("/counsel/print").text)
    for w in BANNED:
        assert w not in paper, (w, paper[max(0, paper.index(w) - 80):paper.index(w) + 60])
    assert not any(w in visible(pub.get("/supports").text) for w in BANNED)
    locked = pub.post("/staff/keys", headers=ORIGIN)
    assert locked.status_code == 403 and not any(w in locked.text for w in BANNED)
    reminder = pub.post("/counsel/reminder", data={"reminder_phone": PHONE}, headers=ORIGIN).text
    assert not any(w in reminder for w in BANNED)


@pytest.mark.parametrize("pid", ["P1", "P2", "P3", "P4", "P5"])
def test_demo_farm_reaches_the_confirm_screen_and_ai_result(pub, pid):
    r = pub.get(f"/demo/{pid}")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/confirm"
    confirm = pub.get("/counsel/confirm").text
    for key in DEMO[pid]["already"]:
        assert re.search(rf'<input[^>]*value="{key}"[^>]*checked|<input[^>]*checked[^>]*value="{key}"', confirm), key
    form = {"already": DEMO[pid]["already"]}
    if DEMO[pid]["form"].get("direct_payment_education") in ("Y", "N"):
        form["direct_payment_education"] = DEMO[pid]["form"]["direct_payment_education"]
    assert pub.post("/counsel/confirm", data=form, headers=ORIGIN).status_code == 303
    html = result_page(pub)
    assert "AI 문장 통과" in html and pub.ai.calls > 0           # 가짜 AI 가 실제 길로 문장을 붙였다
    assert "2026년 11월 13일" not in html
    assert pub.get("/counsel/print").status_code == 200


def test_unknown_demo_id_goes_home(pub):
    assert pub.get("/demo/P9").headers["location"] == "/"


def test_direct_input_gives_result(pub):
    walk(pub, dict(DEMO["P2"]["form"], crop1_area_py="3100"))
    html = result_page(pub)
    assert "data/replay" not in html and "M-P" not in html
    assert pub.get("/counsel/preview").status_code == 200


# --- 직원 쪽 주소 표: 잠금 ---------------------------------------------------------------------------------------

OPEN_WRITE = ("POST", "/staff/scout")
LOCKED = [("POST", "/staff"), ("PUT", "/staff/notice/x"), ("DELETE", "/staff/notice/x"), ("POST", "/staff/notice/x"),
          ("PATCH", "/staff/scout"), ("PUT", "/staff/scout"), ("DELETE", "/staff/scout"),
          ("POST", "/staff/tables/upload"), ("POST", "/staff/keys"), ("DELETE", "/staff/keys"), ("PUT", "/staff/keys"),
          ("POST", "/staff/tables"), ("POST", "/staff/tables/edit"), ("DELETE", "/staff/tables/x"), ("POST", "/staff/backup"),
          ("POST", "/staff/restore"), ("POST", "/staff/refresh"), ("POST", "/staff/notice/x/publish"), ("POST", "/staff/notice/x/discard"),
          ("POST", "/staff/scout/status"), ("POST", "/staff/scout/x"), ("POST", "/staff/"), ("POST", "/staff//scout")]


@pytest.mark.parametrize("method,path", LOCKED)
def test_staff_writes_are_locked(pub, method, path):
    r = pub.request(method, path, headers=ORIGIN)
    assert r.status_code == 403 and public_demo.BLOCKED_LINE in r.text, (method, path)
    assert public_demo.BLOCKED_LINE == "인터넷 판에서는 쓸 수 없어요. 설치본에서 쓸 수 있어요."
    assert pub.app.state.scout.job is None      # 새 공고 찾아보기는 시작되지 않았다
    assert pub.ai.calls == 0


def test_is_locked_rules():
    assert not public_demo.is_locked("GET", "/staff") and not public_demo.is_locked("GET", "/staff/scout")
    assert not public_demo.is_locked("POST", "/staff/scout") and not public_demo.is_locked("POST", "/staff/scout/")
    assert public_demo.is_locked("POST", "/staff/scout/x") and public_demo.is_locked("DELETE", "/staff/scout")
    assert public_demo.is_locked("POST", "/staff") and public_demo.is_locked("POST", "/staff/")
    assert not public_demo.is_locked("POST", "/counsel/input") and not public_demo.is_locked("POST", "/typesheet")


def test_every_write_route_is_classified(pub):
    """앱의 쓰기 주소(POST/PUT/PATCH/DELETE)가 하나라도 늘면 이 표를 먼저 고쳐야 한다(직원 쪽이면 잠금 표에도 넣는다)."""
    found = set()
    for route in pub.app.routes:
        for r in (getattr(route, "original_router", route).routes if hasattr(route, "original_router") else [route]):
            for m in getattr(r, "methods", None) or ():
                if m in public_demo.UNSAFE_METHODS:
                    found.add((m, r.path))
    assert found == {("POST", "/counsel/input"), ("POST", "/counsel/confirm"), ("POST", "/counsel/new"), ("POST", "/counsel/reminder"),
                     ("POST", "/typesheet"), ("POST", "/staff/scout")}
    staff = {(m, p) for m, p in found if p.startswith("/staff")}
    assert staff == {OPEN_WRITE}
    assert all(public_demo.is_locked(m, p) is False for m, p in staff)


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
    monkeypatch.setattr(reminders, "save", lambda *a, **k: pytest.fail("인터넷 판이 번호를 저장하려 했어요"))
    monkeypatch.setattr(store, "log", lambda *a, **k: pytest.fail("인터넷 판이 기록을 남기려 했어요"))
    pub.get("/demo/P1")
    pub.post("/counsel/confirm", data={"already": DEMO["P1"]["already"]})
    before = _snapshot_files()
    with caplog.at_level("DEBUG"):
        r = pub.post("/counsel/reminder", data={"reminder_phone": PHONE, "reminder_consent": "on"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and body["line"] == "인터넷 판이라 번호는 저장하지 않았어요"
    assert PHONE not in r.text and PHONE_DIGITS not in r.text
    assert PHONE not in caplog.text and PHONE_DIGITS not in caplog.text
    assert _snapshot_files() == before             # 자료 폴더·로그 폴더에 새 파일이 없다
    held = repr(pub.app.state.sessions._by_id)
    assert PHONE not in held and PHONE_DIGITS not in held
    assert pub.get("/counsel/reminder-status").text == ""


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
    assert pub.app.state.scout.job is None and pub.ai.calls == 0


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
    # with 로 열어 둔다: 가진 포털 없이 만든 클라이언트는 이 PC 의 소켓 오류(WinError 10014)에 걸려 전체 시험에서 흔들렸다
    with TestClient(pub.app, base_url=str(pub.base_url), follow_redirects=False) as other:
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


# --- 실행기·배포 파일·리눅스 -------------------------------------------------------------------------------

def test_serve_builds_public_live_app(monkeypatch, clock):
    monkeypatch.delenv("JC_PUBLIC_DEMO", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app import serve
    try:
        app = serve.make_app(8981)
        assert os.environ["JC_PUBLIC_DEMO"] == "1"
    finally:
        os.environ.pop("JC_PUBLIC_DEMO", None)
    cfg = app.state.cfg
    assert cfg.public_demo and not cfg.replay and not cfg.demo_asof and cfg.as_of.isoformat() == "2026-11-19"
    assert app.state.ai_live is False and app.state.narrator is not None


def test_serve_uses_korean_today_not_utc(monkeypatch, clock):
    clock["now"] = utc(2026, 11, 18, 20, 0)          # UTC 로는 18일 밤, 한국은 19일 새벽
    from app import serve
    try:
        app = serve.make_app(8982)
    finally:
        os.environ.pop("JC_PUBLIC_DEMO", None)
    assert app.state.cfg.as_of.isoformat() == "2026-11-19"


def test_render_yaml_env_vars():
    text = (APP_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "plan: starter" in text
    for key in ("JC_PUBLIC_DEMO", "PYTHON_VERSION", "ANTHROPIC_API_KEY", "JC_LLM_PROVIDER", "JC_LLM_MODEL", "JC_AI_DAILY_MAX"):
        assert f"key: {key}" in text, key
    block = text.split("key: ANTHROPIC_API_KEY")[1].split("- key:")[0]
    assert "sync: false" in block and "value" not in block          # 키 값은 파일에 두지 않는다
    assert 'value: "anthropic"' in text.split("key: JC_LLM_PROVIDER")[1].split("- key:")[0]
    assert 'value: "claude-opus-5-5"' in text.split("key: JC_LLM_MODEL")[1].split("- key:")[0]
    assert 'value: "400"' in text.split("key: JC_AI_DAILY_MAX")[1].split("- key:")[0]


def test_serve_does_not_pull_in_windows_only_code():
    """리눅스(Render)에서 뜨는 길: 시작과 공고 찾아보기 길이 PC 실행기·Windows 전용 모듈을 부르지 않는다."""
    code = ("import sys, os; os.environ['JC_PUBLIC_DEMO']='1'; import app.serve, app.ui.scout_job; "
            "print(sorted(m for m in sys.modules if m in ('app.tools.build_zip',) or m.startswith('app.launch')))")
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT), "PYTHONUTF8": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(APP_ROOT), env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout


def test_no_windows_only_imports_in_server_code():
    """서버가 닿는 모든 앱 코드에서 winreg·msvcrt·win32 를 직접 가져오는 곳이 없다(PC 전용 launch.py·tools 는 서버가 부르지 않는다)."""
    bad = re.compile(r"^\s*(import|from)\s+(winreg|msvcrt|win32\w*|_winapi|pywintypes)\b", re.M)
    for path in (APP_ROOT / "app").rglob("*.py"):
        rel = path.relative_to(APP_ROOT / "app").as_posix()
        if rel.startswith("tools/") or rel == "launch.py":
            continue
        assert not bad.search(path.read_text(encoding="utf-8")), rel
    dpapi = (APP_ROOT / "app" / "data_layer" / "dpapi.py").read_text(encoding="utf-8")
    assert 'sys.platform != "win32"' in dpapi and dpapi.index('sys.platform != "win32"') < dpapi.index("import ctypes")
