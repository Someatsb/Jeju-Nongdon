"""Task 39: 동의한 번호의 암호 저장·발송 목록·CLI."""
import base64
import io
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path

import pytest

from app import cli
from app.core.models import CalendarSlot
from app.core.reminder_text import reminder_text
from app.data_layer import reminders
from app.data_layer.store import SessionLog
from app.ui.forms import ReminderRequest

AS_OF = date(2026, 11, 13)
CENTER_PHONE = "064-000-0000"
REQ_OK = ReminderRequest(phone="010-1234-5678", consent=True)


def slot(kind, month):
    return CalendarSlot(kind=kind, month=month, start=None, end=None, programs=(), row_status=None)


CELLS_P3 = (slot("integrated", 1), slot("allowance_direct", 3), slot("insurance", 4))


@pytest.fixture
def tmp_reminders(tmp_path, monkeypatch):
    d = tmp_path / "data" / "reminders"
    monkeypatch.setattr(reminders, "REMINDERS_DIR", d)
    d.mkdir(parents=True)
    return d


@pytest.fixture
def fake_dpapi(monkeypatch):
    monkeypatch.setattr(reminders.dpapi, "protect", lambda b: b"ENC" + base64.b64encode(b)[::-1])
    monkeypatch.setattr(reminders.dpapi, "unprotect", lambda b: base64.b64decode(b[3:][::-1]))


def run_cli(argv, root):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli.main(argv, root=root)
    return rc, out.getvalue()


def test_save_requires_consent(tmp_reminders):
    n = reminders.save("A1B2C3", ReminderRequest(phone="010-1234-5678", consent=False), CELLS_P3, AS_OF)
    assert n == 0 and not any(tmp_reminders.iterdir())


def test_save_and_due_roundtrip(tmp_reminders, fake_dpapi):
    assert reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, center_phone=CENTER_PHONE) == 3
    items = reminders.due(date(2027, 4, 1), now=AS_OF).items
    assert len(items) == 1 and items[0].phone == "010-1234-5678" and "4월" in items[0].text
    rest = items[0].text.replace("4월", "").replace(CENTER_PHONE, "")
    assert not any(ch.isdigit() for ch in rest) and len(items[0].text) <= 70


def test_slot_without_month_is_skipped(tmp_reminders, fake_dpapi):
    assert reminders.save("A1B2C3", REQ_OK, (slot("insurance", None),), AS_OF) == 0
    assert not any(tmp_reminders.iterdir())


def test_file_is_not_plaintext(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    raw = next(tmp_reminders.iterdir()).read_bytes()
    assert b"010-1234-5678" not in raw and b"1234-5678" not in raw


def test_expired_file_deleted_on_read(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    assert reminders.due(date(2028, 4, 1), now=date(2028, 4, 1)).items == [] and not any(tmp_reminders.iterdir())


def test_expiry_is_thirteen_months(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    reminders.due(date(2027, 4, 1), now=date(2027, 12, 13))     # 만료일 당일은 남는다
    assert any(tmp_reminders.iterdir())
    reminders.due(date(2027, 4, 1), now=date(2027, 12, 14))
    assert not any(tmp_reminders.iterdir())


def test_forget_and_mark_sent(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    reminders.mark_sent("A1B2C3", date(2027, 4, 1))
    assert reminders.due(date(2027, 4, 1), now=AS_OF).items == [] and any(tmp_reminders.iterdir())
    assert reminders.forget("A1B2C3") and not reminders.forget("A1B2C3")
    reminders.save("A1B2C3", REQ_OK, (slot("insurance", 4),), AS_OF)
    reminders.mark_sent("A1B2C3", date(2027, 4, 1))
    assert not any(tmp_reminders.iterdir())


def test_bad_session_id_refused(tmp_reminders, fake_dpapi):
    with pytest.raises(ValueError):
        reminders.save("../x", REQ_OK, CELLS_P3, AS_OF)


def test_reminder_text_template():
    t = reminder_text("integrated", 1, None)
    assert t.startswith("삼춘, 1월") and "센터로 전화 주세요" in t and "이에요" in t and len(t) <= 70
    assert "064-000-0000" in reminder_text("insurance", 4, None, "064-000-0000")


def test_cli_due_masks_phone(tmp_reminders, fake_dpapi, tmp_path):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=tmp_path / "data" / "reminders")
    rc, out = run_cli(["reminders", "due", "--month", "2027-04"], tmp_path)
    assert rc == 0 and "5678" in out and "010-1234-5678" not in out and "A1B2C3" in out


def test_cli_export_writes_full_csv_and_warns(tmp_reminders, fake_dpapi, tmp_path):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=tmp_path / "data" / "reminders")
    dest = tmp_path / "out.csv"
    rc, out = run_cli(["reminders", "due", "--month", "2027-04", "--export", str(dest)], tmp_path)
    assert rc == 0 and "발송 후 삭제하세요" in out and "010-1234-5678" not in out
    assert "010-1234-5678" in dest.read_text(encoding="utf-8-sig")


def test_cli_export_refused_in_demo(tmp_path):
    rc, out = run_cli(["--asof", "2026-11-13", "reminders", "due", "--month", "2027-04", "--export", "x.csv"], tmp_path)
    assert rc == 1 and "시연" in out


def test_cli_sent_forget_purge(tmp_reminders, fake_dpapi, tmp_path):
    base = tmp_path / "data" / "reminders"
    reminders.save("A1B2C3", REQ_OK, (slot("insurance", 4),), AS_OF, base=base)
    rc, out = run_cli(["reminders", "sent", "--month", "2027-04"], tmp_path)
    assert rc == 0 and not any(base.iterdir())
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=base)
    assert "지웠습니다" in run_cli(["reminders", "forget", "A1B2C3"], tmp_path)[1]
    assert "없습니다" in run_cli(["reminders", "forget", "A1B2C3"], tmp_path)[1]
    assert run_cli(["reminders", "purge"], tmp_path)[0] == 0


def test_session_log_only_flag():
    assert "reminder_phone" not in SessionLog.model_fields and "reminder_saved" in SessionLog.model_fields


# --- fix round 1 ------------------------------------------------------------------------------

def _corrupt(path):
    path.write_bytes(b"garbage-not-encrypted")


def test_unreadable_file_is_reported_and_kept(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    f = next(tmp_reminders.iterdir())
    _corrupt(f)
    r = reminders.due(date(2027, 4, 1), now=AS_OF)
    assert r.items == [] and r.unreadable == ("A1B2C3",) and f.exists()


def test_cli_due_prints_unreadable_line(tmp_reminders, fake_dpapi, tmp_path):
    base = tmp_path / "data" / "reminders"
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=base)
    _corrupt(base / "A1B2C3.bin")
    rc, out = run_cli(["reminders", "due", "--month", "2027-04"], tmp_path)
    assert rc == 0 and "읽을 수 없는 알림 파일 1건" in out and "A1B2C3" in out and "reminders forget" in out


def test_malformed_decrypted_content_is_unreadable(tmp_reminders, fake_dpapi):
    (tmp_reminders / "A1B2C3.bin").write_bytes(reminders.dpapi.protect(b'{"phone": "010-1234-5678"}'))
    (tmp_reminders / "D4E5F6.bin").write_bytes(reminders.dpapi.protect(b'[1, 2]'))
    r = reminders.due(date(2027, 4, 1), now=AS_OF)
    assert r.items == [] and r.unreadable == ("A1B2C3", "D4E5F6")


def _age(path, now):
    import os
    t = datetime.combine(now, datetime.min.time()).timestamp()
    os.utime(path, (t, t))


def test_unreadable_expired_by_mtime_is_deleted_by_due_and_purge(tmp_reminders, fake_dpapi):
    for sid in ("A1B2C3", "D4E5F6"):
        reminders.save(sid, REQ_OK, CELLS_P3, AS_OF)
        _corrupt(tmp_reminders / f"{sid}.bin")
        _age(tmp_reminders / f"{sid}.bin", AS_OF)
    r = reminders.due(date(2027, 4, 1), now=date(2027, 12, 1))
    assert r.unreadable == ("A1B2C3", "D4E5F6") and r.deleted == ()
    r = reminders.due(date(2027, 4, 1), now=date(2027, 12, 20))
    assert r.deleted == ("A1B2C3", "D4E5F6") and not any(tmp_reminders.iterdir())
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    _corrupt(tmp_reminders / "A1B2C3.bin")
    _age(tmp_reminders / "A1B2C3.bin", AS_OF)
    assert reminders.purge(date(2027, 12, 20)) == ("A1B2C3",) and not any(tmp_reminders.iterdir())


def test_readonly_deletes_nothing(tmp_reminders, fake_dpapi):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    r = reminders.due(date(2028, 4, 1), now=date(2028, 4, 1), readonly=True)
    assert r.items == [] and any(tmp_reminders.iterdir())
    assert reminders.purge(date(2030, 1, 1), readonly=True) == ("A1B2C3",) and any(tmp_reminders.iterdir())


def test_cli_demo_mode_is_read_only(tmp_reminders, fake_dpapi, tmp_path):
    base = tmp_path / "data" / "reminders"
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=base)
    for cmd in (["due", "--month", "2029-04"], ["sent", "--month", "2027-04"], ["purge"]):
        rc, out = run_cli(["--asof", "2030-01-01", "reminders", *cmd], tmp_path)
        assert rc == 0 and "시연" in out and (base / "A1B2C3.bin").exists()
    assert len(reminders.due(date(2027, 4, 1), now=AS_OF, base=base).items) == 1


def test_cli_bad_month_message(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["reminders", "due", "--month", "2027-4"], root=tmp_path)
    assert "YYYY-MM" in capsys.readouterr().err


def test_cli_export_refuses_existing_and_repo_data(tmp_reminders, fake_dpapi, tmp_path):
    reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF, base=tmp_path / "data" / "reminders")
    exist = tmp_path / "e.csv"
    exist.write_text("x")
    rc, out = run_cli(["reminders", "due", "--month", "2027-04", "--export", str(exist)], tmp_path)
    assert rc == 1 and "이미 파일이 있습니다" in out and exist.read_text() == "x"
    rc, out = run_cli(["reminders", "due", "--month", "2027-04", "--export", str(tmp_path / "data" / "o.csv")], tmp_path)
    assert rc == 1 and "data" in out and not (tmp_path / "data" / "o.csv").exists()


def test_write_cleans_tmp_on_failed_replace(tmp_reminders, fake_dpapi, monkeypatch):
    def boom(self, target):
        raise OSError("locked")
    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError):
        reminders.save("A1B2C3", REQ_OK, CELLS_P3, AS_OF)
    assert not any(tmp_reminders.iterdir())
