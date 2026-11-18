"""마감 전 문자 안내는 결과 화면에서 따로 받는다(사장 지시 2026-11-14): 단추와 덮개, POST /counsel/reminder, 번호가 남지 않는 규칙."""
import logging

import pytest

from app.ui.routes_counsel import NO_SLOT_LINE
from app.ui.session import COOKIE

from .conftest import P4_FORM, _session

PHONE = "010-1234-5678"


class FakeSave:
    def __init__(self, fail=None, count=3):
        self.calls, self.fail, self.count = [], fail, count

    def __call__(self, session_id, req, cells, as_of, **kw):
        self.calls.append((session_id, req, cells, as_of, kw))
        if self.fail:
            raise self.fail
        return self.count


def _result(client, monkeypatch, fake, *, proxy=False):
    monkeypatch.setattr("app.data_layer.reminders.save", fake)
    path = "/counsel/input?mode=proxy" if proxy else "/counsel/input"
    form = {k: v for k, v in P4_FORM.items() if k != "visitor"} if proxy else P4_FORM
    assert client.post(path, data=form).status_code == 303
    client.post("/counsel/confirm", data={})
    return client.get("/counsel/preview").text


def _post(client, phone=PHONE, consent=True):
    data = {"reminder_phone": phone}
    if consent:
        data["reminder_consent"] = "on"
    return client.post("/counsel/reminder", data=data)


def test_result_screen_has_the_button_and_the_overlay(client_demo, monkeypatch):
    html = _result(client_demo, monkeypatch, FakeSave())
    assert "마감 전에 문자로 알려 드릴까요?" in html and 'id="rm-modal"' in html and "닫기" in html
    for line in ("모으는 것은 휴대폰 번호뿐이에요.", "보험에 들거나 신청할 때가 되면 문자로 알려 드리는 데만 써요.",
                 "알림을 다 보내면 지우고, 늦어도 13개월 뒤에는 지워요.", "동의하지 않으셔도 상담과 종이에 불이익이 없어요."):
        assert line in html                                                  # 동의 글은 법으로 알려야 하는 네 가지(모으는 것·쓰는 곳·지우는 때·동의 안 해도 불이익 없음)를 모두 해요체로
    assert 'name="reminder_phone"' in html and "data-numpad" in html and 'id="numpad"' in html   # 화면 숫자판
    assert 'value="010' not in html


def test_printed_notice_has_the_same_button(client_demo, monkeypatch):
    html = _result(client_demo, monkeypatch, FakeSave())
    after = html[html.index('id="after-print"'):html.index('id="summary"')]
    assert "data-rm-open" in after and "문자 알림 받기" in after


@pytest.mark.parametrize("phone", [PHONE, "01012345678"])      # 숫자판으로 넣은 숫자 11자리도 같은 번호로 받는다
def test_valid_request_saves_once_and_tells_in_one_line(client_demo, monkeypatch, phone):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    r = _post(client_demo, phone)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(fake.calls) == 1
    sid, req, cells, as_of, kw = fake.calls[0]
    assert len(sid) == 6 and req.phone == PHONE and req.consent and len(cells) == 3 and as_of == client_demo.app.state.cfg.as_of
    assert kw["bundle"] is client_demo.app.state.tables and "center_phone" in kw
    line = "문자 알림을 3개 저장했어요"          # 어르신 화면 글에는 상담번호를 싣지 않는다(직원이 볼 내용 칸에만)
    assert r.json()["line"] == line and r.json()["sid"] == sid
    page = client_demo.get("/counsel/preview").text
    assert line in page and PHONE not in page and "01012345678" not in page
    assert f'data-reminder-sid>문자 알림 상담번호 <b>{sid}</b>' in page and f"상담번호 {sid})" not in page
    assert page.count("문자 알림 신청했어요") >= 3
    assert client_demo.get("/counsel/reminder-status").text == line


def test_phone_is_nowhere_in_session_or_log(client_demo, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _result(client_demo, monkeypatch, FakeSave())
    _post(client_demo)
    assert PHONE not in repr(_session(client_demo)) and "1234-5678" not in caplog.text and "12345678" not in caplog.text
    assert _session(client_demo)["reminder"] is None
    assert PHONE not in client_demo.get("/counsel/input?edit=1").text


@pytest.mark.parametrize("phone,consent,field", [(PHONE, False, "reminder_consent"), ("010-1234", True, "reminder_phone"),
                                                 ("", True, "reminder_phone"), ("011-1234-5678", True, "reminder_phone")])
def test_bad_request_saves_nothing_and_says_which_field(client_demo, monkeypatch, phone, consent, field):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    r = _post(client_demo, phone, consent)
    assert r.status_code == 200 and r.json()["ok"] is False and field in r.json()["errors"]
    assert fake.calls == [] and _session(client_demo).get("reminder_saved") is None
    assert client_demo.get("/counsel/reminder-status").text == ""


def test_consent_without_phone_stores_nothing(client_demo, monkeypatch):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    assert "reminder_phone" in client_demo.post("/counsel/reminder", data={"reminder_consent": "on"}).json()["errors"]
    assert fake.calls == []


def test_save_failure_is_told_and_logged_without_the_number(client_demo, monkeypatch, caplog):
    fake = FakeSave(fail=NotImplementedError("dpapi"))
    _result(client_demo, monkeypatch, fake)
    with caplog.at_level(logging.ERROR):
        r = _post(client_demo)
    assert r.json()["ok"] is False and "저장하지 못했어요" in r.json()["line"] and "dpapi" in caplog.text
    assert "1234-5678" not in caplog.text and PHONE not in repr(_session(client_demo))
    assert "저장하지 못했어요" in client_demo.get("/counsel/reminder-status").text


def test_no_month_on_the_paper_means_nothing_saved_and_says_so(client_demo, monkeypatch):
    _result(client_demo, monkeypatch, FakeSave(count=0))
    r = _post(client_demo)
    assert r.json()["ok"] is False and r.json()["line"] == NO_SLOT_LINE


def test_without_a_session_it_is_refused(client_demo):
    r = _post(client_demo)
    assert r.status_code == 409 and r.json()["ok"] is False


def test_proxy_consultation_can_apply_on_the_result_screen(client_demo, monkeypatch):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake, proxy=True)
    assert _post(client_demo).json()["ok"] is True and len(fake.calls) == 1


def test_applying_again_keeps_the_same_counsel_number(client_demo, monkeypatch):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    _post(client_demo)
    _post(client_demo, "010-0000-0000")
    assert len(fake.calls) == 2 and fake.calls[0][0] == fake.calls[1][0] and fake.calls[1][1].phone == "010-0000-0000"


def test_new_counsel_on_the_same_browser_gets_a_new_number(client_demo, monkeypatch):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    _post(client_demo)
    _result(client_demo, monkeypatch, fake)
    assert client_demo.get("/counsel/reminder-status").text == ""        # 새 상담: 앞 상담 저장 표시가 비워진다
    _post(client_demo)
    assert len(fake.calls) == 2 and fake.calls[0][0] != fake.calls[1][0]


def test_print_does_not_save_anything_any_more(client_demo, monkeypatch):
    fake = FakeSave()
    _result(client_demo, monkeypatch, fake)
    assert client_demo.get("/counsel/print").status_code == 200
    assert fake.calls == []


def test_question_form_drops_the_old_phone_fields(client_demo, monkeypatch):
    fake = FakeSave()
    monkeypatch.setattr("app.data_layer.reminders.save", fake)
    assert client_demo.post("/counsel/input", data={**P4_FORM, "reminder_phone": PHONE, "reminder_consent": "on"}).status_code == 303
    client_demo.post("/counsel/confirm", data={})
    client_demo.get("/counsel/print")
    assert fake.calls == [] and PHONE not in repr(_session(client_demo))
    assert COOKIE in client_demo.cookies
