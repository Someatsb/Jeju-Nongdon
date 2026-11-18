"""supports_index는 load_tables의 programs를 그대로 쓴다(Task 28에서 csv 대역을 걷어 냄)."""
from datetime import date

import pytest

from app.data_layer.supports_index import ProgramIndex, load_program_index
from app.data_layer.tables import load_tables

AS_OF = date(2026, 11, 13)


def test_index_equals_load_tables_programs(tables_dir):
    index = load_program_index(tables_dir, AS_OF)
    assert isinstance(index, ProgramIndex)
    assert index.programs == load_tables(tables_dir, AS_OF).programs


def test_index_carries_typed_columns(tables_dir):
    """식별 칸만이 아니라 로더가 형 변환한 칸(날짜 등)이 채워져 있다."""
    index = load_program_index(tables_dir, AS_OF)
    assert any(p.apply_start is not None for p in index.programs)


def test_as_of_is_optional(tables_dir):
    assert load_program_index(tables_dir).programs
