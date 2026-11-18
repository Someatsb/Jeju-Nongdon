"""첫 화면 3줄의 내용(Task 23, U23): 순수 함수. 시계·파일을 읽지 않는다(기준일은 인자).

- due30: 기준일부터 30일 안에 신청이 열리거나 닫히는 제도(이름, 날짜), 날짜 빠른 순 최대 MAX_DUE개.
  열려 있으면(open_now) 마감일, 아직 안 열렸으면 시작일을 날짜로 본다. hold 행과 유효기간이 지난 행은 뺀다.
  같은 이름은 한 번만(작물별로 쪼개진 행은 이름에 작물이 들어 있어 따로 센다).
- hold_count: 표에서 status가 hold인 행 수(근거가 보류 중이라 종이에 못 찍는 제도).
"""
from datetime import date, timedelta

from app.core.calendar import apply_window
from app.core.models import CoreModel
from app.core.snapshot_models import Snapshot
from app.core.tables_models import TableBundle

DUE_DAYS = 30
MAX_DUE = 3


class HomeLines(CoreModel):
    due30: tuple[tuple[str, date], ...]
    data_line: str
    hold_count: int


def home_lines(bundle: TableBundle, snap: Snapshot, as_of: date) -> HomeLines:
    limit = as_of + timedelta(days=DUE_DAYS)
    found: dict[str, date] = {}
    for p in bundle.programs:
        if p.status == "hold" or (p.valid_to is not None and p.valid_to < as_of):
            continue
        w = apply_window(p, as_of)
        day = w.next_end if w.open_now else w.next_start
        if w.always_open or day is None or not as_of <= day <= limit:
            continue
        name = p.name or p.program_key
        if name not in found or day < found[name]:
            found[name] = day
    due = tuple(sorted(found.items(), key=lambda kv: (kv[1], kv[0]))[:MAX_DUE])
    hold = sum(p.status == "hold" for p in bundle.programs)
    line = (f"지원 표 확인 {bundle.verified_date.isoformat()} · 저장본 {snap.built_at.isoformat()} · 보류 {hold}건")
    return HomeLines(due30=due, data_line=line, hold_count=hold)
