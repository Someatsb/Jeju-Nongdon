"""표의 경계 배수 = 동봉 저장본에서 다시 계산한 값 (2026-11-11 평가 지적 고정)."""
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
ASOF = date(2026, 11, 13)


def _param(bundle, crop: str, name: str) -> Decimal:
    rows = [r for r in bundle.params if r.crop == crop and r.param == name]
    assert rows, (crop, name)
    return Decimal(str(rows[0].value))


def test_carrot_band_matches_snapshot_recompute():
    snap = load_snapshot(ROOT / "data" / "snapshot", ASOF)
    tables = load_tables(ROOT / "data" / "tables", ASOF)
    lo, hi = snap.ratio_bounds["당근"]
    assert _param(tables, "당근", "stab_band_lo") == lo
    assert _param(tables, "당근", "stab_band_hi") == hi
