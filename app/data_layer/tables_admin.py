"""표 관리(Task 25, U25): supports.csv 비교·적용·되돌리기. 출력은 app/cli.py가 맡고 여기는 값만 돌려준다.

시계는 읽지 않는다. 시각은 호출하는 쪽이 `stamp`(datetime)로 넘긴다(app/cli.py가 기준일 + 시계 한 곳에서 만든다).
폴더 모양: <root>/data/tables(살아 있는 표), <root>/data/backup, <root>/logs/table_changes.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from app.data_layer.validate import Issue, read_csv_rows, validate_tables

SUPPORTS = "supports.csv"
PRE = "prerollback"          # 되돌리기 직전 백업의 이름 꼬리(_free_stamp의 by 자리)
BY_PATTERN = re.compile(r"[\w가-힣]{1,20}")


class AdminError(Exception):
    """직원에게 그대로 보여 주는 한국어 메시지를 담는다."""


class LogFailed(AdminError):
    """표는 이미 바뀌었고 변경 기록만 쓰지 못했다."""


class AlreadySame(AdminError):
    """되돌릴 내용이 지금 표와 같다(오류 아님)."""


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: dict[str, list[str]] = field(default_factory=dict)   # id -> 바뀐 컬럼


@dataclass
class ApplyResult:
    backup: Path
    sha256_before: str
    sha256_after: str
    diff: Diff
    warnings: list[Issue]
    log_error: str = ""          # 표는 바뀌었으나 기록을 못 쓴 경우의 한국어 안내


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(tables_dir: Path, today: date) -> list[Issue]:
    return validate_tables(Path(tables_dir), today=today)


def _by_id(path: Path) -> dict[str, dict[str, str]]:
    try:
        _, rows = read_csv_rows(path)
    except (OSError, UnicodeError) as e:
        raise AdminError(f"{path.name} 파일을 읽을 수 없습니다: {e}") from None
    return {r.get("id", ""): r for r in rows}


def diff_supports(live: Path, new: Path) -> Diff:
    old, cand = _by_id(live), _by_id(new)
    d = Diff(added=[i for i in cand if i not in old], removed=[i for i in old if i not in cand])
    for i in cand:
        if i in old:
            cols = [c for c in cand[i] if cand[i][c] != old[i].get(c, "")] + \
                   [c for c in old[i] if c not in cand[i]]
            if cols:
                d.changed[i] = cols
    return d


def _check_by(by: str) -> str:
    if not BY_PATTERN.fullmatch(by or ""):
        raise AdminError("--by에는 이니셜(글자·숫자, 20자 이내)을 넣어 주세요. 예: --by KJ")
    if by.lower().endswith(PRE):
        raise AdminError(f"--by에는 '{PRE}'로 끝나는 이름을 쓸 수 없습니다(되돌리기 백업 전용 이름입니다).")
    return by


def _backup_dir(root: Path) -> Path:
    return Path(root) / "data" / "backup"


def _free_stamp(bdir: Path, stamp: datetime, by: str) -> tuple[str, str]:
    """같은 초에 또 적용해도 덮어쓰지 않도록 한 번에 1초씩 미룬다(이름순 = 시간순이 유지된다)."""
    while True:
        base = f"{stamp:%Y%m%d-%H%M%S}_{by}"
        if not (bdir / f"{base}.csv").exists():
            return base, stamp.isoformat(timespec="seconds")
        stamp += timedelta(seconds=1)


def _log(root: Path, record: dict) -> None:
    logs = Path(root) / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "table_changes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        raise LogFailed(f"표는 바뀌었지만 변경 기록(logs/table_changes.jsonl)을 쓰지 못했습니다: {e.strerror or e}\n"
                        "기록 파일이 다른 프로그램에서 열려 있지 않은지 확인하세요. 표 교체 자체는 끝났습니다.") from None


def _os_error(path: Path, e: OSError) -> AdminError:
    return AdminError(f"{path.name} 파일을 쓸 수 없습니다({path.parent.as_posix()}): {e.strerror or e}\n"
                      "다른 프로그램(엑셀)에서 열려 있으면 닫고 다시 실행하세요. 폴더가 없거나 쓰기 금지인지도 확인하세요. "
                      "표는 바뀌지 않았습니다.")


def _write_atomic(dest: Path, data: bytes) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 교체한다. 실패하면 임시 파일을 지우고 dest는 그대로 둔다."""
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _replace_live(live: Path, data: bytes) -> None:
    try:
        _write_atomic(live, data)
    except OSError as e:
        raise _os_error(live, e) from None


def _make_backup(bdir: Path, base: str, live: Path, live_sha: str) -> Path:
    """확인 파일(.sha256)을 먼저, 백업(.csv)을 나중에 쓴다. 중간에 실패해도 짝 없는 최신 .csv는 남지 않는다."""
    backup = bdir / f"{base}.csv"
    side = bdir / f"{base}.csv.sha256"
    try:
        bdir.mkdir(parents=True, exist_ok=True)
        data = live.read_bytes()
    except OSError as e:
        raise _os_error(live if live.exists() else bdir, e) from None
    try:
        _write_atomic(side, f"{live_sha}  {backup.name}\n".encode("utf-8"))
        _write_atomic(backup, data)
    except OSError as e:
        side.unlink(missing_ok=True)
        raise _os_error(backup, e) from None
    return backup


def apply(root: Path, candidate: Path, by: str, stamp: datetime) -> ApplyResult:
    """후보를 임시 복사본에서 먼저 검사하고, 오류가 없을 때만 백업 → 교체 → 기록한다."""
    root, candidate = Path(root), Path(candidate)
    by = _check_by(by)
    tables = root / "data" / "tables"
    live = tables / SUPPORTS
    if not candidate.is_file():
        raise AdminError(f"파일을 찾을 수 없습니다: {candidate}")
    try:
        data = candidate.read_bytes()
    except OSError as e:
        raise AdminError(f"{candidate.name} 파일을 읽을 수 없습니다: {e.strerror or e}\n"
                         "엑셀 등 다른 프로그램에서 열려 있지 않은지 확인하세요. 표는 바뀌지 않았습니다.") from None
    try:
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td) / "tables"
            shutil.copytree(tables, stage)
            (stage / SUPPORTS).write_bytes(data)
            issues = validate_tables(stage, today=stamp.date())
    except OSError as e:
        raise AdminError(f"검사용 임시 복사에 실패했습니다: {e.strerror or e}\n"
                         "data/tables 폴더와 임시 폴더를 쓸 수 있는지 확인하세요. 표는 바뀌지 않았습니다.") from None
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise AdminError(f"오류 {len(errors)}건이 있어 적용하지 않았습니다. 살아 있는 표는 그대로입니다.\n"
                         + "\n".join(format_issue(i) for i in errors))
    diff = diff_supports(live, candidate)
    try:
        before = sha256_file(live)
    except OSError as e:
        raise AdminError(f"{live.name} 파일을 읽을 수 없습니다: {e.strerror or e}\n표는 바뀌지 않았습니다.") from None
    bdir = _backup_dir(root)
    base, ts = _free_stamp(bdir, stamp, by)
    backup = _make_backup(bdir, base, live, before)
    try:
        _replace_live(live, data)
    except AdminError:
        # 방금 만든 백업은 지금 표와 같다. 남기면 뒤의 되돌리기가 "이미 같은 내용"에서 멈춘다.
        backup.unlink(missing_ok=True)
        backup.with_name(backup.name + ".sha256").unlink(missing_ok=True)
        raise
    after = hashlib.sha256(data).hexdigest()
    log_error = ""
    try:
        _log(root, {"ts": ts, "action": "apply", "by": by, "backup": backup.relative_to(root).as_posix(),
                    "sha256_before": before, "sha256_after": after,
                    "added": len(diff.added), "removed": len(diff.removed), "changed": len(diff.changed)})
    except LogFailed as e:
        log_error = str(e)
    return ApplyResult(backup, before, after, diff, [i for i in issues if i.level == "warning"], log_error)


def rollback(root: Path, stamp: datetime, actor: str = "cli") -> Path:
    """가장 최근 백업(이름순 마지막)을 sha256 확인 후 되돌린다. 백업 파일은 남긴다.

    되돌리기 전에 지금 표를 `_prerollback` 백업으로 남기고(이 백업은 되돌릴 후보에서 뺀다),
    지금 표가 이미 그 백업과 같으면 AlreadySame을 올린다.
    """
    root = Path(root)
    live = root / "data" / "tables" / SUPPORTS
    bdir = _backup_dir(root)
    backups = sorted(b for b in bdir.glob("*.csv") if not b.stem.endswith("_" + PRE)) if bdir.is_dir() else []
    if not backups:
        raise AdminError("되돌릴 백업이 없습니다. (data/backup 폴더가 비어 있습니다)")
    backup = backups[-1]
    side = backup.with_name(backup.name + ".sha256")
    try:
        expected = side.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        raise AdminError(f"{backup.name}의 sha256 확인 파일이 없어 되돌리지 않았습니다.") from None
    try:
        data = backup.read_bytes()
    except OSError as e:
        raise AdminError(f"{backup.name} 파일을 읽을 수 없습니다: {e.strerror or e}") from None
    try:
        before = sha256_file(live) if live.exists() else ""
    except OSError as e:
        raise AdminError(f"{live.name} 파일을 읽을 수 없습니다: {e.strerror or e}\n"
                         "엑셀에서 열려 있으면 닫고 다시 실행하세요. 표는 바뀌지 않았습니다.") from None
    if hashlib.sha256(data).hexdigest() != expected:
        raise AdminError(f"{backup.name}의 sha256이 맞지 않습니다(파일이 바뀜). 되돌리지 않았습니다.")
    if before == expected:
        raise AlreadySame(f"이미 같은 내용입니다. 지금 표가 {backup.name}과 같아 되돌리지 않았습니다.")
    if live.exists():
        base, _ = _free_stamp(bdir, stamp, PRE)
        _make_backup(bdir, base, live, before)
    _replace_live(live, data)
    _log(root, {"ts": stamp.isoformat(timespec="seconds"), "action": "rollback", "by": actor, "actor": actor,
                "backup": backup.relative_to(root).as_posix(), "sha256_before": before,
                "sha256_after": expected, "added": 0, "removed": 0, "changed": 0})
    return backup


def format_issue(i: Issue) -> str:
    level = "오류" if i.level == "error" else "경고"
    row = f"{i.row_excel}행" if i.row_excel else "파일 전체"
    parts = [f"{level} {i.code}", i.file, row, i.column or "-", i.message_ko]
    return " · ".join(parts) + (f" ({i.hint_ko})" if i.hint_ko else "")
