"""스냅샷 로더·신선도·as_of 절단(Task 12, U12).

가격 시리즈 키는 1361 품종 글자 그대로(crops.csv judge_cultivars·dist_cultivars와 같은 글자).
플랜의 "carrot_general"은 자리표시자라 "당근(일반)"으로 바꿨다.
"""
import csv
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.data_layer.snapshot import SnapshotError, freshness, load_snapshot, staleness_days, write_manifest
from app.data_layer.tables import load_tables

AS_OF = date(2026, 11, 13)
HUB_1361_HEAD = "baseDate,cultivar,averagePrice,transactionVolume,transactionAmount\r\n"
JASDC_HEAD = "dealDate,avg,high,low,deal,marketCd\r\n"
AGG_869_HEAD = ("crop,cultivar,market,half_start,half_end,n_days,garak_won_per_kg,garak_kg,"
                "hub1361_won_per_kg,hub1361_t,ratio\r\n")


# --- 플랜 Step 1 테스트 ------------------------------------------------------------------

def test_asof_truncates_future_rows(snapshot_dir):
    s = load_snapshot(snapshot_dir, date(2026, 11, 5))
    assert max(p[0] for p in s.prices["당근(일반)"].points) <= date(2026, 11, 5)


def test_freshness_bands():
    assert freshness(date(2026, 11, 13), date(2026, 11, 11)) == "ok" and freshness(date(2026, 11, 13), date(2026, 10, 29)) == "stale"


@pytest.fixture
def tmp_snapshot_corrupt(tmp_path, snapshot_dir):
    """배포 스냅샷을 복사하고 hub_1361.csv 한 글자를 바꾼다(manifest sha256은 그대로)."""
    d = tmp_path / "snapshot"
    shutil.copytree(snapshot_dir, d)
    p = d / "hub_1361.csv"
    raw = bytearray(p.read_bytes())
    raw[-3] = ord("9") if raw[-3] != ord("9") else ord("8")
    p.write_bytes(bytes(raw))
    return d


def test_damaged_dataset_dropped(tmp_snapshot_corrupt):
    s = load_snapshot(tmp_snapshot_corrupt, AS_OF)
    assert "hub_1361" in s.damaged and s.prices == {}


def test_stale_15_days_hides_current_half_month(snapshot_dir):
    # Task 12 몫: 1361 마지막 날(11-05)에서 15일 지난 기준일이면 stale, 14일이면 aged.
    # 진행 중 반월 TriggerResult.status == "STALE" 단언은 tests/unit/test_triggers.py::test_stale_15_days_hides_current_half_month에 있다.
    s = load_snapshot(snapshot_dir, date(2026, 11, 20))
    assert s.price_as_of == date(2026, 11, 5)
    assert staleness_days(date(2026, 11, 20), s.price_as_of) == 15
    assert freshness(date(2026, 11, 20), s.price_as_of) == "stale"
    assert freshness(date(2026, 11, 19), s.price_as_of) == "aged"


# --- 신선도 경계 -------------------------------------------------------------------------

@pytest.mark.parametrize("days, band", [(0, "ok"), (3, "ok"), (4, "aged"), (14, "aged"), (15, "stale"), (400, "stale")])
def test_freshness_band_edges(days, band):
    as_of = date(2026, 11, 13)
    data_as_of = date.fromordinal(as_of.toordinal() - days)
    assert staleness_days(as_of, data_as_of) == days
    assert freshness(as_of, data_as_of) == band


def test_freshness_rejects_data_after_asof():
    with pytest.raises(ValueError):
        freshness(date(2026, 11, 5), date(2026, 11, 6))


# --- 배포 스냅샷(실제 파일) ----------------------------------------------------------------

def _raw_1361(snapshot_dir: Path) -> list[dict[str, str]]:
    with open(snapshot_dir / "hub_1361.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_series_keys_are_crops_csv_cultivars(snapshot_dir, tables_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    crops = load_tables(tables_dir, AS_OF).crops
    named = {cv for c in crops for cv in (*c.judge_cultivars, *c.dist_cultivars)}
    in_hub = {r["cultivar"] for r in _raw_1361(snapshot_dir)}
    assert set(s.prices) == named & in_hub
    assert len(s.prices) == 10
    carrot = s.prices["당근(일반)"]
    assert (carrot.crop_code, carrot.cultivars, carrot.judge, carrot.market_scope) == ("당근", ("당근(일반)",), True, "전국")
    assert (s.prices["흙당근"].crop_code, s.prices["흙당근"].judge) == ("당근", False)   # dist_cultivars에만 있음
    assert s.prices["세척무"].crop_code == "월동무" and s.prices["깐마늘"].crop_code == "마늘"
    assert carrot.source.source_id == "hub1361" and carrot.source.as_of == s.price_as_of


def test_crop_mapping_comes_from_given_crops(snapshot_dir, tables_dir):
    carrot_only = [c for c in load_tables(tables_dir, AS_OF).crops if c.crop_code == "당근"]
    s = load_snapshot(snapshot_dir, AS_OF, crops=carrot_only)
    assert set(s.prices) == {"당근(일반)", "세척당근", "흙당근"}
    assert s.citrus is None and set(s.area) == {"당근"}


def test_1361_point_units(snapshot_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    # 원본 20261105,당근(일반) 행: averagePrice 원/kg 그대로, transactionVolume 톤 → kg(×1000)
    row = next(r for r in _raw_1361(snapshot_dir) if r["baseDate"] == "20261105" and r["cultivar"] == "당근(일반)")
    last = s.prices["당근(일반)"].points[-1]
    assert last.day == date(2026, 11, 5)
    assert last.won_per_kg == Decimal(row["averagePrice"])
    assert last.volume_kg == Decimal(row["transactionVolume"]) * 1000
    assert s.price_as_of == date(2026, 11, 5)


def test_zero_volume_rows_are_not_trading_days(snapshot_dir):
    # 원본 20261104,세척당근,8333.00,0.00 — 0.00톤(5kg 미만 반올림)은 거래일로 세지 않는다
    s = load_snapshot(snapshot_dir, AS_OF)
    assert date(2026, 11, 4) not in {p.day for p in s.prices["세척당근"].points}
    assert all(p.volume_kg > 0 for ps in s.prices.values() for p in ps.points)


def test_asof_cut_is_prefix_of_later_cut(snapshot_dir):
    later = load_snapshot(snapshot_dir, date(2026, 11, 5))
    cut = load_snapshot(snapshot_dir, date(2026, 11, 2))
    for key, series in later.prices.items():
        kept = tuple(p for p in series.points if p.day <= date(2026, 11, 2))
        assert cut.prices[key].points == kept, key
    assert cut.price_as_of <= date(2026, 11, 2) and cut.citrus_as_of == date(2026, 11, 2)
    assert later.citrus_as_of == date(2026, 11, 5)          # 수급센터 11-06 행은 잘림


def test_citrus_box_price_divided_by_five(snapshot_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    c = s.citrus
    assert c is not None and (c.crop_code, c.cultivars, c.source.source_id) == ("감귤_노지", ("kind=1",), "jasdc_kind1")
    # 원본 2026-11-06,10300,…,944.3573 → 2,060원/kg, 944,357.3kg
    assert c.points[-1] == (date(2026, 11, 6), Decimal("2060"), Decimal("944357.3"))
    assert s.citrus_as_of == date(2026, 11, 6)


def test_area_jeju_by_crop_code(snapshot_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    assert s.area["당근"][2023] == 1151.0                   # 제주도 논 0 + 밭 1151
    assert s.area["월동무"][2022] == 6102.0                 # 854 '겨울무' = crops.csv 월동무 별칭
    assert s.area["마늘"][2025] == 860.0
    assert set(s.area) == {"당근", "월동무", "양배추", "마늘", "양파"}   # 시설과채('토마토' 별칭)는 노지 면적 아님
    assert 2025 not in load_snapshot(snapshot_dir, date(2024, 12, 31)).area["마늘"]


def test_ratio_bounds_from_869_file(snapshot_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    lo, hi = s.ratio_bounds["당근"]
    assert Decimal("0.8") < lo < 1 < hi < Decimal("1.25")
    assert set(s.ratio_bounds) == {"당근"}                  # 양배추는 869 단위 정합 실패로 뺌(round2-B §3)
    with open(snapshot_dir / "agg_869_ratio.csv", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.DictReader(f))) == 42             # 2017-01~2021-08, 11~3월 반월


def test_shipped_snapshot_is_intact(snapshot_dir):
    s = load_snapshot(snapshot_dir, AS_OF)
    assert s.damaged == {} and s.built_at == date(2026, 11, 8)


# --- 손상·누락 ------------------------------------------------------------------------------

def _copy(tmp_path: Path, snapshot_dir: Path) -> Path:
    d = tmp_path / "snapshot"
    shutil.copytree(snapshot_dir, d)
    return d


def test_damaged_dataset_keeps_others(tmp_snapshot_corrupt):
    s = load_snapshot(tmp_snapshot_corrupt, AS_OF)
    assert s.price_as_of is None
    assert "sha256" in s.damaged["hub_1361"]
    assert s.citrus is not None and s.area and s.ratio_bounds
    assert set(s.damaged) == {"hub_1361"}


def test_missing_869_aggregate_is_tolerated(tmp_path, snapshot_dir):
    d = _copy(tmp_path, snapshot_dir)
    (d / "agg_869_ratio.csv").unlink()
    s = load_snapshot(d, AS_OF)
    assert s.ratio_bounds == {} and "agg_869_ratio" in s.damaged
    assert s.prices and s.citrus is not None


def test_file_missing_from_manifest_is_damaged(tmp_path, snapshot_dir):
    d = _copy(tmp_path, snapshot_dir)
    m = (d / "manifest.json").read_text(encoding="utf-8").replace('"jasdc_citrus_k1"', '"jasdc_other"')
    (d / "manifest.json").write_text(m, encoding="utf-8")
    s = load_snapshot(d, AS_OF)
    assert s.citrus is None and s.citrus_as_of is None and "jasdc_citrus_k1" in s.damaged


def test_missing_manifest_raises(tmp_path, snapshot_dir):
    d = _copy(tmp_path, snapshot_dir)
    (d / "manifest.json").unlink()
    with pytest.raises(SnapshotError):
        load_snapshot(d, AS_OF)


# --- 작은 합성 스냅샷 ------------------------------------------------------------------------

def _tiny(tmp_path: Path, hub: str, jasdc: str, agg: str | None = None) -> Path:
    d = tmp_path / "tiny"
    d.mkdir()
    (d / "hub_1361.csv").write_bytes(("﻿" + HUB_1361_HEAD + hub).encode("utf-8"))
    (d / "jasdc_citrus_k1.csv").write_bytes(("﻿" + JASDC_HEAD + jasdc).encode("utf-8"))
    (d / "hub_854_jeju_raw.csv").write_bytes("연도,시도,재배지구분,채소구분,재배면적\r\n2024,제주도,밭,당근,-\r\n".encode("cp949"))
    if agg is not None:
        (d / "agg_869_ratio.csv").write_bytes(("﻿" + AGG_869_HEAD + agg).encode("utf-8"))
    write_manifest(d, date(2026, 11, 8))
    return d


def test_tiny_snapshot_drops_rows_after_asof(tmp_path):
    d = _tiny(
        tmp_path,
        hub="20261104,당근(일반),1000.00,10.00,9.00\r\n"
            "20261105,당근(일반),1100.00,20.00,21.00\r\n"
            "20261106,당근(일반),1200.00,30.00,35.00\r\n"
            "20261106,월동무,700.00,5.00,3.00\r\n"
            "20261105,모르는품종,1.00,1.00,1.00\r\n",
        jasdc="2026-11-05,9000,1,1,100.5,\r\n2026-11-06,9500,1,1,0,\r\n2026-11-07,9500,1,1,90,\r\n",
    )
    s = load_snapshot(d, date(2026, 11, 5))
    assert s.prices["당근(일반)"].points == (
        (date(2026, 11, 4), Decimal("1000.00"), Decimal("10000")),
        (date(2026, 11, 5), Decimal("1100.00"), Decimal("20000")),
    )
    assert "월동무" not in s.prices and "모르는품종" not in s.prices   # 11-06뿐이라 잘림 / crops.csv에 없음
    assert s.price_as_of == date(2026, 11, 5)
    assert s.citrus.points == ((date(2026, 11, 5), Decimal("1800"), Decimal("100500")),)
    assert s.area == {}                                         # '-'는 값 없음(0 아님)
    assert s.ratio_bounds == {} and set(s.damaged) == {"agg_869_ratio"}

    s6 = load_snapshot(d, date(2026, 11, 6))
    assert s6.citrus_as_of == date(2026, 11, 5)                 # deal=0 행은 뺀다
    assert s6.prices["월동무"].points[-1].day == date(2026, 11, 6)


def test_tiny_ratio_bounds_are_reciprocal_p90_p10(tmp_path):
    rows = "".join(f"당근,당근(일반),서울가락도매,2018-0{i}-01,2018-0{i}-15,5,1,1,1,1,{r}\r\n"
                   for i, r in enumerate(("0.90", "0.95", "1.00", "1.05", "1.10"), start=1))
    d = _tiny(tmp_path, hub="", jasdc="", agg=rows)
    s = load_snapshot(d, AS_OF)
    # inclusive 분위수: p10 0.92, p90 1.08 → (1/1.08, 1/0.92) 소수 셋째 자리
    assert s.ratio_bounds == {"당근": (Decimal("0.926"), Decimal("1.087"))}
    assert s.prices == {} and s.price_as_of is None and s.citrus is None
    # 기준일 뒤 반월 행도 잘린다: 2018-03-15 기준이면 0.90·0.95·1.00 세 개만 → p10 0.91, p90 0.99
    assert load_snapshot(d, date(2018, 3, 15)).ratio_bounds["당근"] == (Decimal("1.010"), Decimal("1.099"))
