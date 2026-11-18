"""첫 화면 3줄(Task 23): 코어 home_lines는 시계·파일 없이 표·저장본·기준일만 본다."""
from datetime import date
from functools import lru_cache

from app.core.home import DUE_DAYS, MAX_DUE, home_lines
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from conftest import AS_OF, ROOT


@lru_cache(maxsize=None)
def B():
    return load_tables(ROOT / "data" / "tables", AS_OF)


@lru_cache(maxsize=None)
def S():
    return load_snapshot(ROOT / "data" / "snapshot", AS_OF, crops=B().crops)


def test_home_due30_on_1113_includes_onion_1127():
    h = home_lines(B(), S(), date(2026, 11, 13))
    assert any(d == date(2026, 11, 27) for _, d in h.due30)


def test_home_hold_count_matches_tables():
    assert home_lines(B(), S(), AS_OF).hold_count == sum(p.status == "hold" for p in B().programs)


def test_due30_sorted_capped_and_within_window():
    h = home_lines(B(), S(), date(2026, 11, 13))
    assert 0 < len(h.due30) <= MAX_DUE
    days = [d for _, d in h.due30]
    assert days == sorted(days)
    assert all(0 <= (d - date(2026, 11, 13)).days <= DUE_DAYS for d in days)


def test_due30_empty_after_validity_ends():
    assert home_lines(B(), S(), date(2027, 3, 3)).due30 == ()


def test_data_line_has_dates_and_hold():
    h = home_lines(B(), S(), AS_OF)
    assert B().verified_date.isoformat() in h.data_line and S().built_at.isoformat() in h.data_line
    assert f"보류 {h.hold_count}건" in h.data_line
