"""빈 종이(Task 15): A·B·C·D가 모두 비면 '다 챙기고 계세요'."""
from pathlib import Path

import pytest

from app.core.sheet import EmptyFront, build_sheet, flatten
from app.data_layer.tables import load_tables
from conftest import AS_OF, T1_KWARGS
from factsheet_fixtures import amount, make_fs

T1_AMOUNTS = (amount("JEJU-FARMER-ALLOW@2026", 900_000, 900_000), amount("NAT-DIRECT-SMALL@2026", 1_300_000, 1_300_000),
              amount("JEJU-WOMEN-VOUCHER@2026", 200_000, 200_000),
              amount("NHIS-FARMER-SUPPORT@2026#읍면", None, None, kind="UNDISCLOSED"),
              amount("NAT-DIRECT-AREA@2026", 1_487_550, 2_132_155, kind="PER_AREA"))


@pytest.fixture(scope="module")
def bundle():
    return load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)


def test_empty_sheet_t1(bundle):
    s = build_sheet(make_fs(T1_KWARGS, bundle, AS_OF, amounts=T1_AMOUNTS), bundle, AS_OF)
    assert isinstance(s.front, EmptyFront) and "다 챙기고 계세요" in s.front.title and len(s.front.calendar3) == 3
    assert [c.kind for c in s.front.calendar3] == ["integrated", "allowance_direct", "insurance"]


def test_empty_sheet_keep_money_counts_already_received_only_once(bundle):
    f = build_sheet(make_fs(T1_KWARGS, bundle, AS_OF, amounts=T1_AMOUNTS), bundle, AS_OF).front
    # 농민수당 + 소농직불 + 행복이용권. 택1로 밀린 면적직불·금액 없는 건보료는 뺀다.
    assert (f.keep_low_won, f.keep_high_won) == (2_400_000, 2_400_000)


def test_empty_sheet_keep_actions_and_insurance_next(bundle):
    f = build_sheet(make_fs(T1_KWARGS, bundle, AS_OF), bundle, AS_OF).front
    texts = " ".join(l.title + l.text + (l.sub or "") for l in f.keep_actions)
    assert "경영체" in texts and "2027" in texts and "직불 교육" in texts
    assert f.insurance_next and all(l.kind == "INSURANCE" for l in f.insurance_next)


def test_empty_sheet_keeps_fixed_lines(bundle):
    s = build_sheet(make_fs(T1_KWARGS, bundle, AS_OF), bundle, AS_OF)
    assert isinstance(s.front, EmptyFront)
    assert any("영농도우미" in l.text for l in flatten(s.front))
