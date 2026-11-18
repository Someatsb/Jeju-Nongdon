"""직원 메뉴(/staff): 자료 상태 값이 보이고, 공고 보고서 보기는 공고 폴더 밖으로 나갈 수 없다."""
import pytest

from app.ui import routes_staff


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    box = tmp_path / "inbox"
    (box / "N9-abc12345").mkdir(parents=True)
    (box / "N9-abc12345" / "report.html").write_text("<html><body><h1>보고서 본문</h1></body></html>", encoding="utf-8")
    (box / "N9-abc12345" / "check.json").write_text('{"decision": "DRAFT_READY"}', encoding="utf-8")
    (box / "빈폴더").mkdir()   # report.html이 없으면 목록에 안 나온다
    (tmp_path / "secret.html").write_text("<p>밖의 파일</p>", encoding="utf-8")
    (tmp_path / "report.html").write_text("<p>한 칸 위의 보고서</p>", encoding="utf-8")
    monkeypatch.setattr(routes_staff, "INBOX_DIR", box)
    return box


def test_staff_shows_data_status_values(client_demo, inbox):
    r = client_demo.get("/staff")
    assert r.status_code == 200
    h = client_demo.app.state.header
    for label in ("지원제도 정보 확인일", "도매가격 자료 마지막 날", "감귤 가격 마지막 날", "저장본 만든 날", "준비 중인 지원제도"):
        assert label in r.text
    assert f"{h.tables_verified.year}년 {h.tables_verified.month}월 {h.tables_verified.day}일" in r.text
    assert f"{h.snapshot_built.year}년 {h.snapshot_built.month}월 {h.snapshot_built.day}일" in r.text
    holds = sum(p.status == "hold" for p in client_demo.app.state.tables.programs)
    assert f"{holds}건" in r.text
    assert "시연" not in r.text and "데모" not in r.text


def test_staff_ai_line_never_shows_key(client_demo, monkeypatch):
    assert "AI 문장" in client_demo.get("/staff").text
    secret = "sk-test-SECRET-VALUE"

    class FakeStore:
        def get(self, name):
            return secret

    monkeypatch.setattr(routes_staff, "KeyStore", FakeStore)
    text = client_demo.get("/staff").text
    assert secret not in text


def test_ai_line_values(monkeypatch):
    class Req:
        class app:
            class state:
                class cfg:
                    replay = False

    class Has:
        def get(self, name):
            return "x"

    class No:
        def get(self, name):
            return None

    monkeypatch.setattr(routes_staff, "KeyStore", Has)
    assert routes_staff.ai_line(Req) == "사용 중"
    monkeypatch.setattr(routes_staff, "KeyStore", No)
    assert routes_staff.ai_line(Req) == "기본 문장 사용 중"


def test_notice_list_and_view(client_demo, inbox):
    text = client_demo.get("/staff").text
    assert "N9-abc12345" in text and "초안 완성" in text and "빈폴더" not in text
    r = client_demo.get("/staff/notice/N9-abc12345")
    assert r.status_code == 200 and "보고서 본문" in r.text and 'href="/staff"' in r.text


@pytest.mark.parametrize("bad", ["%2e%2e", "..%2fsecret.html", "..%5csecret.html", "N9-abc12345%2f..%2f..", "C:%5cWindows", "no-such", ".hidden"])
def test_notice_path_escape_blocked(client_demo, inbox, bad):
    r = client_demo.get(f"/staff/notice/{bad}")
    assert r.status_code == 404 and "밖의 파일" not in r.text and "한 칸 위의 보고서" not in r.text


def test_staff_empty_inbox_message(client_demo, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_staff, "INBOX_DIR", tmp_path / "none")
    assert "아직 받은 공고 초안이 없어요" in client_demo.get("/staff").text


def test_notice_view_hides_internal_replay_banner(client_demo, inbox):
    (inbox / "N9-abc12345" / "report.html").write_text(
        '<html><body><div class="banner warn" role="status">손으로 쓴 시연 응답 재생 · handwritten · demo-script</div><h1>보고서 본문</h1></body></html>',
        encoding="utf-8")
    r = client_demo.get("/staff/notice/N9-abc12345")
    assert "보고서 본문" in r.text
    for w in ("시연", "handwritten", "demo-script"):
        assert w not in r.text
