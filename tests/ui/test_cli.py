"""Task 25(U25) CLI: 표 관리(check/diff/apply/rollback)와 키(set/show/test/delete)."""
import csv
import hashlib
import io
import json
import os
import shutil
from contextlib import redirect_stdout
from datetime import time
from pathlib import Path

import pytest
from keyring.backend import KeyringBackend

from app import cli
from app.config import APP_ROOT

FAKE_KEY = "key-test-1234"
LIVE = APP_ROOT / "data" / "tables"
_CTX: dict = {}


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        from keyring.errors import PasswordDeleteError
        if (service, username) not in self.store:
            raise PasswordDeleteError("없음")
        del self.store[(service, username)]


@pytest.fixture
def tmp_tables(tmp_path, monkeypatch):
    """data/tables 복사본이 든 임시 루트. run_cli가 이 루트를 쓴다."""
    shutil.copytree(LIVE, tmp_path / "data" / "tables")
    _CTX["root"] = tmp_path
    monkeypatch.setenv("JC_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HUB_PROJECT_KEY", raising=False)
    return tmp_path


@pytest.fixture
def keyring_backend():
    return MemoryKeyring()


def run_cli(argv, root=None, backend=None):
    root = root or _CTX["root"]
    out = io.StringIO()
    kw = {"root": root, "clock": lambda: time(10, 15, 0)}
    if backend is not None:
        kw["backend"] = backend
    with redirect_stdout(out):
        rc = cli.main(["--asof", "2026-11-13", *argv], **kw)
    return rc, out.getvalue()


@pytest.fixture
def monkeypatch_getpass(monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": FAKE_KEY)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def live_supports(root):
    return root / "data" / "tables" / "supports.csv"


def make_good(root, name="good.csv"):
    """live supports.csv에서 첫 행 name 칸만 고친 후보."""
    text = live_supports(root).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    rows[1][rows[0].index("name")] = rows[1][rows[0].index("name")] + " "
    rows[1][rows[0].index("name")] = rows[1][rows[0].index("name")].strip() + "(고침)"
    out = root / name
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    return out


def make_bad(root):
    p = root / "bad.csv"
    p.write_text("id,name\n1,x\n", encoding="utf-8")
    return p


# --- 계획서 세 가지 ---------------------------------------------------------------------

def test_apply_refuses_invalid(tmp_tables):
    before = sha(live_supports(tmp_tables))
    rc, out = run_cli(["tables", "apply", str(make_bad(tmp_tables)), "--by", "KJ"])
    assert rc == 1 and "오류" in out
    assert sha(live_supports(tmp_tables)) == before
    assert not (tmp_tables / "data" / "backup").exists()


def test_apply_then_rollback(tmp_tables):
    before = sha(live_supports(tmp_tables))
    rc, out = run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    assert rc == 0, out
    assert list((tmp_tables / "data" / "backup").glob("*.csv"))
    assert sha(live_supports(tmp_tables)) != before
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 0, out
    assert sha(live_supports(tmp_tables)) == before


def test_keys_set_masked(tmp_tables, monkeypatch_getpass, keyring_backend):
    rc, out = run_cli(["keys", "set", "llm"], backend=keyring_backend)
    assert rc == 0 and FAKE_KEY not in out
    rc, out = run_cli(["keys", "show"], backend=keyring_backend)
    assert "••••" in out and "1234" in out and FAKE_KEY not in out


# --- 더하는 시험 -------------------------------------------------------------------------

def test_check_shipped_tables_ok(tmp_tables):
    rc, out = run_cli(["tables", "check"])
    assert rc == 0, out


def test_check_reports_errors_in_korean(tmp_tables):
    shutil.copy(make_bad(tmp_tables), live_supports(tmp_tables))
    rc, out = run_cli(["tables", "check"])
    assert rc == 1 and "supports.csv" in out and "오류" in out


def test_apply_writes_backup_sidecar_and_log(tmp_tables):
    live = live_supports(tmp_tables)
    before = sha(live)
    cand = make_good(tmp_tables)
    rc, out = run_cli(["tables", "apply", str(cand), "--by", "KJ"])
    assert rc == 0, out
    backups = list((tmp_tables / "data" / "backup").glob("*.csv"))
    assert len(backups) == 1 and backups[0].name == "20261113-101500_KJ.csv"
    side = backups[0].with_name(backups[0].name + ".sha256")
    assert side.read_text(encoding="utf-8").split()[0] == before
    assert sha(live) == sha(cand)
    lines = (tmp_tables / "logs" / "table_changes.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    assert rec["by"] == "KJ" and rec["sha256_before"] == before and rec["sha256_after"] == sha(cand)
    assert rec["changed"] == 1 and rec["added"] == 0 and rec["removed"] == 0
    assert rec["backup"].endswith("20261113-101500_KJ.csv")


def test_apply_twice_same_second_keeps_both_backups(tmp_tables):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    shutil.copy(LIVE / "supports.csv", tmp_tables / "again.csv")
    rc, _ = run_cli(["tables", "apply", str(tmp_tables / "again.csv"), "--by", "KJ"])
    assert rc == 0
    assert len(list((tmp_tables / "data" / "backup").glob("*.csv"))) == 2


def test_rollback_without_backup(tmp_tables):
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 1 and "백업" in out


def test_rollback_refuses_tampered_backup(tmp_tables):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    b = next((tmp_tables / "data" / "backup").glob("*.csv"))
    b.write_bytes(b.read_bytes() + b"x")
    live_before = sha(live_supports(tmp_tables))
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 1 and "sha256" in out and sha(live_supports(tmp_tables)) == live_before


def test_diff_lists_changed_columns(tmp_tables):
    rc, out = run_cli(["tables", "diff", str(make_good(tmp_tables))])
    assert rc == 0 and "바뀜" in out and "name" in out


def test_diff_added_removed(tmp_tables):
    text = live_supports(tmp_tables).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    removed_id = rows.pop(1)[0]
    p = tmp_tables / "less.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    rc, out = run_cli(["tables", "diff", str(p)])
    assert rc == 0 and "빠짐" in out and removed_id in out


def test_keys_show_without_key(tmp_tables, keyring_backend):
    rc, out = run_cli(["keys", "show"], backend=keyring_backend)
    assert rc == 0 and "저장된 키 없음" in out


def test_keys_delete_and_test(tmp_tables, monkeypatch_getpass, keyring_backend):
    run_cli(["keys", "set", "hub"], backend=keyring_backend)
    rc, out = run_cli(["keys", "delete", "hub"], backend=keyring_backend)
    assert rc == 0
    assert "저장된 키 없음" in run_cli(["keys", "show"], backend=keyring_backend)[1]
    rc, out = run_cli(["keys", "test"], backend=keyring_backend)
    assert rc == 0 and "MemoryKeyring" in out


# --- Fix round 1 ----------------------------------------------------------------------

class BrokenKeyring(MemoryKeyring):
    def _boom(self, *a):
        from keyring.errors import KeyringError
        raise KeyringError("locked")

    get_password = set_password = delete_password = _boom


@pytest.mark.parametrize("argv", [["keys", "set", "llm"], ["keys", "delete", "llm"]])
def test_keys_keyring_error_is_one_korean_line(tmp_tables, monkeypatch_getpass, argv):
    rc, out = run_cli(argv, backend=BrokenKeyring())
    assert rc == 1 and "자격 증명 저장소를 쓸 수 없습니다" in out and "Traceback" not in out
    assert len(out.strip().splitlines()) == 1


def test_keys_runtime_error_from_missing_backend(tmp_tables, monkeypatch):
    def boom():
        raise RuntimeError("no backend")
    monkeypatch.setattr("keyring.get_keyring", boom)
    rc, out = run_cli(["keys", "show"])
    assert rc == 1 and "자격 증명 저장소를 쓸 수 없습니다" in out


def test_keys_delete_requires_name(tmp_tables, monkeypatch_getpass, keyring_backend):
    run_cli(["keys", "set", "hub"], backend=keyring_backend)
    rc, out = run_cli(["keys", "delete"], backend=keyring_backend)
    assert rc == 2 and "keys delete" in out
    assert "1234" in run_cli(["keys", "show"], backend=keyring_backend)[1]


def _deny(*a, **k):
    raise PermissionError(13, "Permission denied")


def _deny_for(name_part):
    real = os.replace

    def f(src, dst, *a, **k):
        if name_part in str(dst).replace("\\", "/"):
            raise PermissionError(13, "Permission denied")
        return real(src, dst, *a, **k)
    return f


def test_apply_permission_error_leaves_live_untouched(tmp_tables, monkeypatch):
    good = make_good(tmp_tables)
    before = sha(live_supports(tmp_tables))
    monkeypatch.setattr("os.replace", _deny_for("data/tables/"))
    rc, out = run_cli(["tables", "apply", str(good), "--by", "KJ"])
    assert rc == 1 and "supports.csv" in out and "엑셀" in out
    assert sha(live_supports(tmp_tables)) == before
    assert not list((tmp_tables / "data" / "tables").glob("*.tmp"))


def test_rollback_permission_error(tmp_tables, monkeypatch):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    after = sha(live_supports(tmp_tables))
    monkeypatch.setattr("os.replace", _deny_for("data/tables/"))
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 1 and "supports.csv" in out and "엑셀" in out
    assert sha(live_supports(tmp_tables)) == after


def test_apply_backup_dir_unwritable(tmp_tables, monkeypatch):
    good = make_good(tmp_tables)
    before = sha(live_supports(tmp_tables))
    monkeypatch.setattr("os.replace", _deny_for("data/backup/"))
    rc, out = run_cli(["tables", "apply", str(good), "--by", "KJ"])
    assert rc == 1 and "backup" in out and not list((tmp_tables / "data" / "backup").glob("*.tmp"))
    assert sha(live_supports(tmp_tables)) == before


def test_rollback_backs_up_live_file_first(tmp_tables):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    edited = live_supports(tmp_tables)
    edited.write_bytes(edited.read_bytes() + b"\n")           # 손으로 고친 살아 있는 표
    edited_sha = sha(edited)
    n = len(list((tmp_tables / "data" / "backup").glob("*.csv")))
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 0, out
    backups = list((tmp_tables / "data" / "backup").glob("*.csv"))
    assert len(backups) == n + 1 and any(sha(b) == edited_sha for b in backups)


def test_rollback_same_content_refused_gently(tmp_tables):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    run_cli(["tables", "rollback"])
    n = len(list((tmp_tables / "data" / "backup").glob("*.csv")))
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 0 and "이미 같은 내용입니다" in out
    assert len(list((tmp_tables / "data" / "backup").glob("*.csv"))) == n


def test_by_rejects_trailing_newline(tmp_tables):
    rc, out = run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ\n"])
    assert rc == 1 and "--by" in out


def test_log_paths_posix_and_rollback_actor(tmp_tables):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    run_cli(["tables", "rollback"])
    recs = [json.loads(l) for l in (tmp_tables / "logs" / "table_changes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all("\\" not in r["backup"] for r in recs)
    assert recs[-1]["action"] == "rollback" and recs[-1]["by"] == "cli"


def test_data_refresh_routes_to_refresh_module(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.data_layer.refresh_cli.main", lambda argv=None: seen.setdefault("argv", argv) and 7)
    assert cli.main(["data", "refresh", "--asof", "2026-11-13"]) == 7
    assert seen["argv"] == ["--asof", "2026-11-13"]


# --- Fix round 2 ----------------------------------------------------------------------

def test_data_refresh_after_global_asof(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.data_layer.refresh_cli.main", lambda argv=None: seen.setdefault("argv", argv) and 5)
    assert cli.main(["--asof", "2026-11-01", "data", "refresh"]) == 5
    assert seen["argv"] == ["--asof", "2026-11-01"]


def test_data_refresh_help_passthrough(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.data_layer.refresh_cli.main", lambda argv=None: seen.setdefault("argv", argv) and 0) 
    cli.main(["data", "refresh", "--help"])
    assert seen["argv"] == ["--help"]


def test_by_prerollback_reserved(tmp_tables):
    for by in ("prerollback", "a_prerollback"):
        rc, out = run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", by])
        assert rc == 1 and "prerollback" in out
    assert not (tmp_tables / "data" / "backup").exists()


def test_apply_candidate_unreadable(tmp_tables, monkeypatch):
    good = make_good(tmp_tables)
    real = Path.read_bytes

    def rb(self):
        if self.name == good.name:
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    rc, out = run_cli(["tables", "apply", str(good), "--by", "KJ"])
    assert rc == 1 and "good.csv" in out and "Traceback" not in out


def test_apply_copytree_oserror(tmp_tables, monkeypatch):
    def boom(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr("shutil.copytree", boom)
    rc, out = run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    assert rc == 1 and "임시 복사" in out


def test_apply_log_failure_after_replace(tmp_tables, monkeypatch):
    good = make_good(tmp_tables)
    before = sha(live_supports(tmp_tables))
    real = Path.open

    def op(self, *a, **k):
        if self.name == "table_changes.jsonl":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "open", op)
    rc, out = run_cli(["tables", "apply", str(good), "--by", "KJ"])
    assert rc == 1 and "적용했습니다" in out and "기록" in out
    assert sha(live_supports(tmp_tables)) != before


def test_rollback_log_failure_after_replace(tmp_tables, monkeypatch):
    before = sha(live_supports(tmp_tables))
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    real = Path.open

    def op(self, *a, **k):
        if self.name == "table_changes.jsonl":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "open", op)
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 1 and "되돌렸습니다" in out and "기록" in out and "실패" not in out.split("기록")[0]
    assert sha(live_supports(tmp_tables)) == before


def test_rollback_live_unreadable_names_live_file(tmp_tables, monkeypatch):
    run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    real = Path.read_bytes

    def rb(self):
        if self.parent.name == "tables":
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 1 and "supports.csv" in out and "KJ.csv" not in out


def test_failed_apply_removes_its_backup(tmp_tables, monkeypatch):
    run_cli(["tables", "apply", str(make_good(tmp_tables, "g1.csv")), "--by", "AA"])
    bdir = tmp_tables / "data" / "backup"
    first = sorted(p.name for p in bdir.iterdir())
    second = make_good(tmp_tables, "g2.csv")
    text = second.read_text(encoding="utf-8-sig").replace("(고침)", "(또고침)")
    second.write_text(text, encoding="utf-8-sig")
    monkeypatch.setattr("os.replace", _deny_for("data/tables/"))
    rc, _ = run_cli(["tables", "apply", str(second), "--by", "BB"])
    monkeypatch.undo()
    assert rc == 1 and sorted(p.name for p in bdir.iterdir()) == first
    rc, out = run_cli(["tables", "rollback"])
    assert rc == 0 and "이미 같은 내용" not in out


def test_sidecar_failure_leaves_no_orphan_backup(tmp_tables, monkeypatch):
    real = os.replace

    def f(src, dst, *a, **k):
        if str(dst).endswith(".sha256"):
            raise PermissionError(13, "Permission denied")
        return real(src, dst, *a, **k)
    monkeypatch.setattr("os.replace", f)
    rc, _ = run_cli(["tables", "apply", str(make_good(tmp_tables)), "--by", "KJ"])
    assert rc == 1
    assert not list((tmp_tables / "data" / "backup").glob("*.csv"))
