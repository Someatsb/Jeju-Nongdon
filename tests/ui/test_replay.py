"""재생 모드(Task 32): 열쇠 없이 녹화 답으로 설명을 만들고, 모든 화면에 띠를 단다."""
import json
import re

import pytest

from app.agents.llm.recording import REPLAY_MISMATCH_MESSAGE, load_recording
from app.config import APP_ROOT

DEMO = json.loads((APP_ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
P4_FORM = DEMO["P4"]["form"]   # 녹화는 시연 입력(골든 P4와 같은 12,000㎡) 기준이다. 화면 시험 공용 P4_FORM(3,600평)과 다르다.
BANNER_HEAD = "체험용으로 저장해 둔 답변을 쓴 종이예요"      # 종이 맨 위 줄(PAPER_LINE)에만 남는다. 화면에는 없다
NOTE = "체험 모드 · 미리 저장해 둔 AI 답변을 써요"   # 화면 맨 아래 작은 글씨 한 줄


def post_profile(client, form):
    assert client.post("/counsel/input", data=form).status_code == 303


def run_demo(client, sample):
    """입력 → 확인(받고 있음 표시) → 결과 화면, 시연 농가의 입력 그대로."""
    post_profile(client, DEMO[sample]["form"])
    assert client.post("/counsel/confirm", data={"already": DEMO[sample]["already"]}).status_code == 303
    return client.get("/counsel/preview")


def test_replay_p4_shows_reject_then_pass(client_replay):
    post_profile(client_replay, P4_FORM)
    html = client_replay.get("/counsel/preview").text
    assert "주입" not in html and "반려" in html and "통과" in html
    assert re.search(r"1회 반려 → 2회 통과", html)


def test_replay_note_text(client_replay):
    """체험 모드 줄은 어르신 화면에 두지 않고 직원 메뉴(/staff)에만 둔다(검수 라운드1)."""
    text = client_replay.get("/").text
    assert NOTE not in text and BANNER_HEAD not in text
    assert NOTE in client_replay.get("/staff").text


def test_replay_note_on_every_screen(client_replay):
    pages = ["/", "/counsel/input"]
    for url in pages:
        text = client_replay.get(url).text
        assert NOTE not in text and 'class="replay"' not in text and BANNER_HEAD not in text
    post_profile(client_replay, P4_FORM)
    assert NOTE not in client_replay.get("/counsel/confirm").text
    assert NOTE not in client_replay.get("/counsel/preview").text
    printed = client_replay.get("/counsel/print")
    assert printed.status_code == 200 and BANNER_HEAD in printed.text and "종이를 뽑지 못했어요" not in printed.text


def test_replay_note_on_hold_page(client_replay):
    post_profile(client_replay, P4_FORM)
    state = client_replay.app.state
    real = state.narrator
    state.narrator = lambda fs: (_ for _ in ()).throw(RuntimeError("x"))   # 종이는 나오지만
    state.replay_check = None
    # 보류 화면은 base.html을 쓰므로 띠가 같이 나온다(preflight가 막도록 지문 자리를 비운다)
    from app.ui import routes_counsel
    orig = routes_counsel.preflight
    routes_counsel.preflight = lambda html, fs, cfg: ["NO_FINGERPRINT"]
    try:
        r = client_replay.get("/counsel/print")
    finally:
        routes_counsel.preflight = orig
        state.narrator = real
    assert "종이를 뽑지 못했어요" in r.text and NOTE not in r.text


def test_replay_refuses_other_profile(client_replay):
    post_profile(client_replay, {**DEMO["P1"]["form"], "birth_year": "1953"})
    r = client_replay.get("/counsel/preview")
    assert r.status_code == 200 and "저장해 둔 AI 답변과 입력이 달라서" in r.text
    assert "기본 문장(템플릿)" in r.text or "설명 없음" in r.text      # 템플릿으로 가고 오류 화면은 아님
    assert "AI 문장 통과" not in r.text


@pytest.mark.parametrize("sample", ["P1", "P2", "P3", "P4", "P5"])
def test_replay_each_demo_farm_matches_its_recording(client_replay, sample):
    r = run_demo(client_replay, sample)
    assert r.status_code == 200 and "저장해 둔 AI 답변과 입력이 달라서" not in r.text
    assert "AI 문장 통과" in r.text
    assert client_replay.get("/counsel/print").status_code == 200


def test_screen_does_not_name_the_recording_source(client_replay):
    sample = load_recording(APP_ROOT / "data" / "replay" / "P4.json")      # P4 는 검사가 틀린 문장을 돌려보내는 장면을 보이려고 손으로 쓴 녹화
    assert sample.source == "handwritten"                                   # P1·P2·P3·P5 는 2026-11-15 에 실제 AI 로 녹화(source "recorded")
    text = client_replay.get("/").text
    assert "손으로 쓴 시연 응답 재생" not in text and "handwritten" not in text and "demo-script" not in text


def test_no_note_without_replay(client):
    text = client.get("/").text
    assert BANNER_HEAD not in text and NOTE not in text


# --- 고침 1차 ---------------------------------------------------------------------------------

def _app_with_dir(tmp_path, files):
    import shutil
    from dataclasses import replace

    from app.config import load_config
    from app.ui.app import create_app
    d = tmp_path / "replay"
    shutil.copytree(APP_ROOT / "data" / "replay", d)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return create_app(replace(load_config(["--asof", "2026-11-13", "--replay"]), replay_dir=d))


def test_corrupt_recording_does_not_break_app_and_is_named_in_banner(tmp_path):
    app = _app_with_dir(tmp_path, {"P2.json": "{깨진 파일"})
    assert "녹화 파일 1개를 읽을 수 없어요" in app.state.replay_banner


def test_mixed_recordings_banner_says_mixed(tmp_path):
    import json as j
    raw = j.loads((APP_ROOT / "data" / "replay" / "P3.json").read_text(encoding="utf-8"))
    raw["model"] = "other-model"
    app = _app_with_dir(tmp_path, {"P3.json": j.dumps(raw, ensure_ascii=False)})
    assert "녹화 여러 건(혼합)" in app.state.replay_banner and "other-model" not in app.state.replay_banner


def test_replay_note_only_in_staff_block():
    """바닥의 체험 모드 줄은 base.html의 foot_note 블록에만 있다: 기본 자식 화면에는 안 나오고, 직원 화면이 블록을 채워야 나온다."""
    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
    plain = '{% extends "base.html" %}{% block content %}{% endblock %}{% block header_actions %}{% endblock %}'
    staff = plain + '{% block foot_note %}{% if replay_note %}<span>{{ replay_note }}</span>{% endif %}{% endblock %}'
    env = Environment(loader=ChoiceLoader([DictLoader({"c.html": plain, "s.html": staff}),
                                           FileSystemLoader(str(APP_ROOT / "app" / "ui" / "templates"))]))
    ctx = dict(cfg=type("C", (), {"demo_asof": False, "service_name": "제주 농돈"})(), header=None)
    assert "체험 모드 · 줄" not in env.get_template("c.html").render(replay_note="체험 모드 · 줄", **ctx)
    assert "체험 모드 · 줄" in env.get_template("s.html").render(replay_note="체험 모드 · 줄", **ctx)
    assert "체험 모드" not in env.get_template("s.html").render(replay_note=None, **ctx)


def test_replay_log_entries_carry_replay_flag(client_replay):
    post_profile(client_replay, P4_FORM)
    client_replay.get("/counsel/preview")
    entries = client_replay.app.state.review_log.entries
    assert entries and all(e.get("replay") is True for e in entries)


def test_p4_shows_rule_codes(client_replay):
    post_profile(client_replay, P4_FORM)
    assert "숫자를 씀" in client_replay.get("/counsel/preview").text


def test_replay_uses_factory_and_replay_client(client_replay, monkeypatch):
    """UI가 실제로 가는 길(공장)에서 실제 클라이언트·네트워크가 닿으면 실패한다."""
    import socket

    import app.agents.llm.factory as factory
    from app.agents.llm.recording import ReplayClient
    monkeypatch.setattr(factory, "AnthropicClient", lambda *a, **k: pytest.fail("실제 클라이언트가 만들어짐"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("네트워크 연결"))
    built = []
    real = factory.make_llm_client
    monkeypatch.setattr("app.ui.replay.make_llm_client", lambda *a, **k: built.append(real(*a, **k)) or built[-1])
    post_profile(client_replay, DEMO["P2"]["form"])
    client_replay.post("/counsel/confirm", data={"already": DEMO["P2"]["already"]})
    assert "AI 문장 통과" in client_replay.get("/counsel/preview").text
    assert built and all(isinstance(c, ReplayClient) for c in built)


@pytest.mark.parametrize("sample", ["P1", "P2", "P3", "P4", "P5"])
def test_replay_every_demo_farmer_prints_without_hold(client_replay, sample):
    """재생 띠·종이 줄이 있어도 시연 농가 다섯 모두 인쇄 보류 없이 나온다(종이에 재생 줄은 그대로 보인다)."""
    from app.ui.preflight import preflight
    from app.ui.session import COOKIE
    assert client_replay.app.state.replay_banner
    run_demo(client_replay, sample)
    printed = client_replay.get("/counsel/print")
    assert printed.status_code == 200 and "종이를 뽑지 못했어요" not in printed.text and "replay-line" in printed.text
    paper = client_replay.app.state.sessions.get(client_replay.cookies.get(COOKIE))["job"].paper()
    assert preflight(paper["html"], paper["fs"], client_replay.app.state.cfg) == []
