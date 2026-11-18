"""재방문 문자 알림 저장소(Task 39). 동의한 번호만, 상담번호별 파일 하나, DPAPI로 암호화.

번호는 프로필·로그·LLM 입력에 들어가지 않는다. 파일: data/reminders/<상담번호>.bin
내용(암호화 전 JSON): {"phone","consent_at","items":[{"month":"2027-04","program_key","text","sent"}],"expires"}
program_key는 달력 칸의 종류(integrated/allowance_direct/insurance). 달이 없는 칸은 건너뛴다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.core.models import CalendarSlot, ReminderRequest
from app.core.reminder_text import reminder_text
from app.core.tables_models import TableBundle
from app.data_layer import dpapi

REMINDERS_DIR = Path(__file__).resolve().parents[2] / "data" / "reminders"
KEEP_MONTHS = 13
_ID = re.compile(r"[A-Z0-9]{6}")   # store 알파벳의 상위 집합: 일부러 느슨하게, 경로 문자 차단용


@dataclass(frozen=True)
class DueItem:
    session_id: str
    phone: str
    text: str


@dataclass(frozen=True)
class DueResult:
    items: list[DueItem]
    unreadable: tuple[str, ...]          # 읽을 수 없어 남겨 둔 파일의 상담번호
    deleted: tuple[str, ...]             # 만료로 지운 파일의 상담번호


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    m += 1
    try:
        return date(y, m, d.day)
    except ValueError:
        return date(y, m, 28)


def _path(session_id: str, base: Path | None) -> Path:
    if not _ID.fullmatch(session_id):
        raise ValueError(f"상담번호 형식이 아닙니다: {session_id!r}")
    return Path(base or REMINDERS_DIR) / f"{session_id}.bin"


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_bytes(dpapi.protect(json.dumps(doc, ensure_ascii=False).encode("utf-8")))
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)                  # 실패했을 때 찌꺼기를 남기지 않는다


def _read(path: Path) -> dict | None:
    """풀어서 모양까지 맞으면 dict, 아니면 None(풀 수 없음·손상·다른 PC/사용자)."""
    try:
        doc = json.loads(dpapi.unprotect(path.read_bytes()).decode("utf-8"))
        if not (isinstance(doc, dict) and isinstance(doc["phone"], str) and isinstance(doc["items"], list)
                and all(isinstance(it, dict) and isinstance(it["month"], str) and isinstance(it["text"], str)
                        for it in doc["items"])):
            return None
        date.fromisoformat(doc["expires"])
        return doc
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _next_month(month: int, as_of: date) -> str:
    year = as_of.year if month >= as_of.month else as_of.year + 1
    return f"{year}-{month:02d}"


def save(session_id: str, req: ReminderRequest, cells: Sequence[CalendarSlot], as_of: date, *,
         bundle: TableBundle | None = None, center_phone: str = "", base: Path | None = None) -> int:
    """동의했고 달이 있는 칸이 있으면 저장하고 저장한 항목 수를 돌려준다. 아니면 0, 아무것도 쓰지 않는다.

    암호화·쓰기에 실패하면 OSError/NotImplementedError를 올린다. 인쇄 경로는 잡아서 reminder_saved=False로 기록한다.
    """
    if not req.consent:
        return 0
    items = [{"month": _next_month(c.month, as_of), "program_key": c.kind, "sent": False,
              "text": reminder_text(c.kind, c.month, bundle, center_phone)}
             for c in cells if c.month is not None]
    if not items:
        return 0
    _write(_path(session_id, base), {"phone": req.phone, "consent_at": as_of.isoformat(), "items": items,
                                     "expires": _add_months(as_of, KEEP_MONTHS).isoformat()})
    return len(items)


def _files(base: Path | None) -> list[Path]:
    d = Path(base or REMINDERS_DIR)
    return sorted(d.glob("*.bin")) if d.is_dir() else []


def _expired(path: Path, doc: dict | None, now: date) -> bool:
    """내용이 읽히면 expires, 안 읽히면 파일 수정일 + 13개월을 기준으로 본다."""
    if doc is not None:
        return now > date.fromisoformat(doc["expires"])
    try:
        saved = date.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return now > _add_months(saved, KEEP_MONTHS)


def due(month: date, now: date, *, base: Path | None = None, readonly: bool = False) -> DueResult:
    """month에 보낼 미발송 항목. 만료된 파일은 읽을 때 지운다(readonly면 지우지 않는다).

    읽을 수 없는 파일은 만료 전이면 지우지 않고 unreadable에 담는다.
    """
    key, out, bad, gone = f"{month.year}-{month.month:02d}", [], [], []
    for p in _files(base):
        doc = _read(p)
        if _expired(p, doc, now):
            if not readonly:
                p.unlink(missing_ok=True)
                gone.append(p.stem)
            continue
        if doc is None:
            bad.append(p.stem)
            continue
        out += [DueItem(p.stem, doc["phone"], it["text"]) for it in doc["items"]
                if it["month"] == key and not it.get("sent")]
    return DueResult(out, tuple(bad), tuple(gone))


def mark_sent(session_id: str, month: date, *, base: Path | None = None) -> None:
    """그 달 항목을 발송 완료로 표시. 모두 발송되면 파일을 지운다."""
    p = _path(session_id, base)
    doc = _read(p) if p.exists() else None
    if doc is None:
        return
    key = f"{month.year}-{month.month:02d}"
    for it in doc["items"]:
        if it["month"] == key:
            it["sent"] = True
    if all(it.get("sent") for it in doc["items"]):
        p.unlink(missing_ok=True)
    else:
        _write(p, doc)


def forget(session_id: str, *, base: Path | None = None) -> bool:
    p = _path(session_id, base)
    if not p.exists():
        return False
    p.unlink()
    return True


def purge(now: date, *, base: Path | None = None, readonly: bool = False) -> tuple[str, ...]:
    """만료된 파일(읽을 수 없는 파일은 수정일 기준)의 상담번호를 돌려준다. readonly면 지우지 않고 목록만."""
    gone = []
    for p in _files(base):
        if _expired(p, _read(p), now):
            if not readonly:
                p.unlink(missing_ok=True)
            gone.append(p.stem)
    return tuple(gone)
