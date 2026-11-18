"""최종 검토 보완(11-13): 설명 에이전트 연결, 머리 날짜, 세션 정리, 문자 저장 결과 줄."""
import json

from app.agents.llm.base import GenResult
from app.ui.session import COOKIE, SessionStore

from .conftest import P4_FORM, _started_client

TEXT = {"support": "{P:%s}은 맞는지 창구에서 확인해 보세요.",
        "insurance": "{P:%s}은 가입할 수 있는 때를 농협 창구에서 알아보세요.",
        "action": "{P:%s}부터 챙기면 다른 제도 신청이 쉬워져요.",
        "empty": "{P:%s}은 그대로 이어가세요."}


class GoodClient:
    """요청의 첫 근거를 인용하는 규칙 통과 문장을 돌려주는 가짜 LLM. 판정 요청에는 통과."""
    provider = model = "fake"

    def __init__(self):
        self.calls = 0

    def generate(self, req):
        self.calls += 1
        if req.purpose == "judge":
            text = '{"verdict": "PASS", "reason_code": null}'
        else:
            item = json.loads(req.messages[0].text.split("\n\n")[0])["items"][0]
            text = json.dumps({"section": req.section, "sentences": [
                {"sid": 1, "text": TEXT[req.section] % item["program_id"], "cites": [item["fact_id"]]}]}, ensure_ascii=False)
        return GenResult(text=text, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0, provider="fake", model="fake")


def walk(client, form=P4_FORM):
    assert client.post("/counsel/input", data=form).status_code == 303
    client.post("/counsel/confirm", data={})


def test_injected_llm_gives_ai_pass_in_preview():
    fake = GoodClient()
    c = _started_client(["--asof", "2026-11-13"], llm=fake)
    try:
        walk(c)
        assert "AI 문장 통과" in c.get("/counsel/preview").text and fake.calls > 0
    finally:
        c.__exit__(None, None, None)


def test_no_key_app_has_narrator_but_uses_template(client_demo):
    assert client_demo.app.state.narrator is not None and client_demo.app.state.review_log is not None
    walk(client_demo)
    panel = client_demo.get("/counsel/preview").text
    assert "기본 문장(템플릿)" in panel and "AI 문장 통과" not in panel


def test_header_dates_not_shown_on_input_screen(client_demo):
    st = client_demo.app.state
    h = st.header
    assert h is not None and h.refresh_ok is None
    text = client_demo.get("/counsel/input").text
    assert 'class="fresh"' not in text
    for d in (h.price_as_of, h.tables_verified, h.snapshot_built):
        assert d.isoformat() not in text


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_idle_session_expires_and_input_says_so(client_demo):
    clock = Clock()
    client_demo.app.state.sessions = SessionStore(ttl_s=1800, clock=clock)
    walk(client_demo)
    assert client_demo.get("/counsel/print").status_code == 200
    clock.now += 1799
    assert client_demo.get("/counsel/print").status_code == 200      # 만질 때마다 시계가 새로 시작
    clock.now += 1801
    r = client_demo.get("/counsel/print")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/input"
    page = client_demo.get("/counsel/input").text
    assert "오래 쉬어서 처음부터 다시 해요" in page
    assert client_demo.get("/counsel/preview").status_code == 303


def test_fresh_input_page_has_no_expiry_notice(client_demo):
    assert "시간이 지나 새 상담으로 시작해요" not in client_demo.get("/counsel/input").text
