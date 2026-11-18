"""스냅샷 로더(Task 12, U12). data/snapshot의 이름이 정해진 파일만 읽어 Snapshot으로 넘긴다.

| 데이터셋 이름 | 파일 | 들어가는 곳 |
|---|---|---|
| hub_1361 | hub_1361.csv | prices: 1361 품종 글자 → 일별 (날짜, averagePrice 원/kg, 거래량 톤×1000 kg) |
| jasdc_citrus_k1 | jasdc_citrus_k1.csv | citrus: 노지온주 일별 (날짜, avg 원/5kg ÷ 5, deal 톤×1000 kg) |
| hub_854_jeju_raw | hub_854_jeju_raw.csv | area: 작물 코드(groups에 밭작물) → 연도 → 제주 재배면적 ha(논+밭) |
| agg_869_ratio | agg_869_ratio.csv | ratio_bounds: 작물 코드 → (1/p90, 1/p10) 가락/1361 반월 비 |

1. manifest.json의 sha256과 파일 바이트가 다르거나, 파일·manifest 항목이 없거나, 읽다 깨지면 그
   데이터셋은 비우고(None·{}) Snapshot.damaged[이름]에 이유를 적는다. manifest.json 자체가 없으면 SnapshotError.
2. as_of 절단: 기준일 뒤 날짜의 행은 버린다(869는 반월 끝날, 854는 연도 > 기준일 연도).
3. 1361 품종 → 작물 코드는 crops.csv(judge_cultivars·dist_cultivars)에서 온다. crops.csv에 없는 품종은 버린다.
   거래량 0(0.00톤 = 5kg 미만 반올림)이나 가격 0 이하인 행은 거래가 없던 날로 보고 버린다.
4. 수급센터 감귤은 crops.csv judge_source=jasdc_kind1 작물로 붙이고, deal=0 행은 뺀다.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

from app.core.models import SourceRef
from app.core.snapshot_models import Freshness, PricePoint, PriceSeries, Snapshot, freshness, staleness_days
from app.core.tables_models import Crop
from app.data_layer.tables import load_tables

__all__ = ["DATASETS", "Freshness", "PricePoint", "PriceSeries", "Snapshot", "SnapshotError",
           "freshness", "load_snapshot", "staleness_days", "write_manifest"]

MANIFEST = "manifest.json"
SHIPPED_TABLES = Path(__file__).resolve().parents[2] / "data" / "tables"
HUB_URL = "https://jejudatahub.net"
JASDC_URL = "https://jasdc.or.kr"
KG_PER_TON = Decimal(1000)
CITRUS_BOX_KG = Decimal(5)
FIELD_GROUP = "밭작물"                                   # crops.csv groups 값. 854 재배면적을 붙이는 작물

# 이름 → (파일, manifest.json에 적는 출처 설명)
DATASETS: dict[str, tuple[str, str]] = {
    "hub_1361": ("hub_1361.csv", "제주데이터허브 1361 품종별 일일 거래 통계(전국 도매시장). "
                 "averagePrice 원/kg(시장·법인 행 단순평균), transactionVolume 톤, transactionAmount 백만원"),
    "jasdc_citrus_k1": ("jasdc_citrus_k1.csv", "감귤출하연합회 수급관리센터 term-day.jsp kind=1(노지온주) 일별. "
                        "avg 원/5kg 상자, deal 톤, deal=0 행 제외"),
    "hub_854_jeju_raw": ("hub_854_jeju_raw.csv", "제주데이터허브 854 시도별 노지채소 재배면적(ha). cp949 원본, 전 시도"),
    "agg_869_ratio": ("agg_869_ratio.csv", "제주데이터허브 869 전국도매시장 일별 경락가격(당근) 원본에서 "
                      "scripts/build_869_ratio.py로 만든 반월 가락/1361 비"),
}


class SnapshotError(Exception):
    """스냅샷 전체를 읽을 수 없음(manifest.json 없음·깨짐, crops.csv 품종 중복)."""


# --- manifest -------------------------------------------------------------------------------

def write_manifest(snapshot_dir: Path, built_at: date) -> dict[str, Any]:
    """폴더에 있는 DATASETS 파일의 sha256으로 manifest.json을 새로 쓴다(스냅샷을 다시 만든 스크립트가 부른다)."""
    d = Path(snapshot_dir)
    datasets = {name: {"file": file, "sha256": hashlib.sha256((d / file).read_bytes()).hexdigest(), "source": source}
                for name, (file, source) in DATASETS.items() if (d / file).exists()}
    manifest = {"built_at": built_at.isoformat(), "datasets": datasets}
    (d / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _read_manifest(d: Path) -> tuple[date, dict[str, Any]]:
    try:
        m = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
        return date.fromisoformat(m["built_at"]), dict(m["datasets"])
    except FileNotFoundError as e:
        raise SnapshotError(f"스냅샷 폴더에 {MANIFEST}이 없습니다: {d}") from e
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise SnapshotError(f"{MANIFEST}을 읽지 못했습니다: {e}") from e


def _checked_bytes(d: Path, name: str, datasets: dict[str, Any]) -> tuple[bytes | None, str]:
    """(바이트, '') 또는 (None, 읽지 않은 이유)."""
    path = d / DATASETS[name][0]
    if not path.exists():
        return None, "파일이 없습니다."
    entry = datasets.get(name)
    if not isinstance(entry, dict) or "sha256" not in entry:
        return None, f"{MANIFEST}에 없는 파일입니다."
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        return None, f"sha256이 {MANIFEST}과 다릅니다(파일이 바뀌었거나 손상됨)."
    return raw, ""


# --- CSV ------------------------------------------------------------------------------------

def _rows(raw: bytes, need: tuple[str, ...]) -> csv.DictReader:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")                       # 854 원본(허브 내려받기 그대로)
    rd = csv.DictReader(io.StringIO(text, newline=""), restval="")   # 짧은 행 → 빈칸 → 변환 오류(손상)
    missing = [c for c in need if c not in (rd.fieldnames or [])]
    if missing:
        raise ValueError(f"컬럼이 없습니다: {', '.join(missing)}")
    return rd


def _cultivar_owner(crops: Iterable[Crop]) -> dict[str, tuple[str, bool]]:
    """1361 품종 글자 → (작물 코드, judge 여부). 한 품종이 두 작물에 있으면 SnapshotError."""
    owner: dict[str, tuple[str, bool]] = {}
    for c in crops:
        for cv, judge in [(x, True) for x in c.judge_cultivars] + [(x, False) for x in c.dist_cultivars]:
            if cv in owner and owner[cv][0] != c.crop_code:
                raise SnapshotError(f"crops.csv에서 품종 '{cv}'가 두 작물({owner[cv][0]}, {c.crop_code})에 있습니다.")
            owner.setdefault(cv, (c.crop_code, judge))
    return owner


def _prices_1361(raw: bytes, owner: dict[str, tuple[str, bool]], as_of: date) -> tuple[dict[str, PriceSeries], date | None]:
    pts: dict[str, list[PricePoint]] = defaultdict(list)
    for r in _rows(raw, ("baseDate", "cultivar", "averagePrice", "transactionVolume")):
        day = date.fromisoformat(r["baseDate"].strip())  # YYYYMMDD
        cv = r["cultivar"].strip()
        if day > as_of or cv not in owner:
            continue
        price, vol = Decimal(r["averagePrice"]), Decimal(r["transactionVolume"])
        if price > 0 and vol > 0:
            pts[cv].append(PricePoint(day, price, vol * KG_PER_TON))
    last = max((p.day for ps in pts.values() for p in ps), default=None)
    if last is None:
        return {}, None
    src = SourceRef(source_id="hub1361", url=HUB_URL, as_of=last)
    return {cv: PriceSeries(crop_code=owner[cv][0], cultivars=(cv,), judge=owner[cv][1], market_scope="전국",
                            points=tuple(sorted(ps)), source=src)
            for cv, ps in sorted(pts.items())}, last


def _citrus(raw: bytes, crops: Iterable[Crop], as_of: date) -> PriceSeries | None:
    crop = next((c for c in crops if c.judge_source == "jasdc_kind1"), None)
    rows = _rows(raw, ("dealDate", "avg", "deal"))
    if crop is None:
        return None
    pts = []
    for r in rows:
        day = date.fromisoformat(r["dealDate"].strip()[:10])
        if day > as_of:
            continue
        avg, deal = Decimal(r["avg"]), Decimal(r["deal"])
        if avg > 0 and deal > 0:
            pts.append(PricePoint(day, avg / CITRUS_BOX_KG, deal * KG_PER_TON))
    if not pts:
        return None
    pts.sort()
    return PriceSeries(crop_code=crop.crop_code, cultivars=crop.judge_cultivars, judge=True, market_scope="전국",
                       points=tuple(pts), source=SourceRef(source_id="jasdc_kind1", url=JASDC_URL, as_of=pts[-1].day))


def _area(raw: bytes, crops: Iterable[Crop], as_of: date) -> dict[str, dict[int, float]]:
    """제주 행만 연도별 논+밭 합. '-'는 값 없음(0 아님). 854는 노지채소라 crops.csv groups에 '밭작물'이 있는
    작물만 붙인다(시설과채의 별칭 '토마토'가 노지 토마토에 붙지 않게). 채소구분은 작물 코드, 없으면 별칭 순서로 찾는다."""
    by_name: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for r in _rows(raw, ("연도", "시도", "채소구분", "재배면적")):
        v, year = r["재배면적"].strip(), int(r["연도"])
        if r["시도"].strip().startswith("제주") and v not in ("", "-") and year <= as_of.year:
            by_name[r["채소구분"].strip()][year] += float(v)
    out = {}
    for c in crops:
        if FIELD_GROUP not in c.groups:
            continue
        name = next((n for n in (c.crop_code, *c.aliases) if n in by_name), None)
        if name is not None:
            out[c.crop_code] = dict(sorted(by_name[name].items()))
    return out


def _ratio_bounds(raw: bytes, as_of: date) -> dict[str, tuple[Decimal, Decimal]]:
    """반월 비(가락/1361)의 inclusive 분위수 p10·p90 → (1/p90, 1/p10), 소수 셋째 자리.
    1361 평균 < 기준가 × 1/p90이면 가락 평균도 기준가 아래일 가능성이 90%라는 뜻(round2-B §3)."""
    ratios: dict[str, list[Decimal]] = defaultdict(list)
    for r in _rows(raw, ("crop", "half_end", "ratio")):
        if date.fromisoformat(r["half_end"].strip()) <= as_of:
            ratios[r["crop"].strip()].append(Decimal(r["ratio"]))
    out = {}
    for crop, xs in sorted(ratios.items()):
        if len(xs) < 2:
            continue
        q = statistics.quantiles(xs, n=10, method="inclusive")
        lo, hi = (_milli(1 / q[8]), _milli(1 / q[0]))
        if not lo < hi:
            raise ValueError(f"{crop} 반월 비가 모두 같아 경계 구간을 만들 수 없습니다.")
        out[crop] = (lo, hi)
    return out


def _milli(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --- 로더 -----------------------------------------------------------------------------------

def load_snapshot(snapshot_dir: Path, as_of: date, *, crops: Iterable[Crop] | None = None) -> Snapshot:
    """스냅샷 폴더를 읽어 기준일(as_of) 뒤 행을 잘라 낸 Snapshot을 돌려준다.
    crops를 주지 않으면 배포 표(data/tables)의 crops.csv를 쓴다(앱은 load_tables 결과의 crops를 넘긴다)."""
    d = Path(snapshot_dir)
    built_at, datasets = _read_manifest(d)
    crops = tuple(crops) if crops is not None else load_tables(SHIPPED_TABLES, as_of).crops
    owner = _cultivar_owner(crops)
    damaged: dict[str, str] = {}

    def guarded(name: str, parse: Callable[[bytes], Any], empty: Any) -> Any:
        raw, reason = _checked_bytes(d, name, datasets)
        if raw is not None:
            try:
                return parse(raw)
            except (ValueError, ArithmeticError, TypeError, csv.Error, statistics.StatisticsError) as e:
                reason = f"읽지 못했습니다: {e}"
        damaged[name] = reason
        return empty

    prices, price_as_of = guarded("hub_1361", lambda raw: _prices_1361(raw, owner, as_of), ({}, None))
    citrus = guarded("jasdc_citrus_k1", lambda raw: _citrus(raw, crops, as_of), None)
    area = guarded("hub_854_jeju_raw", lambda raw: _area(raw, crops, as_of), {})
    bounds = guarded("agg_869_ratio", lambda raw: _ratio_bounds(raw, as_of), {})
    return Snapshot(prices=prices, citrus=citrus, area=area, ratio_bounds=bounds, built_at=built_at,
                    price_as_of=price_as_of, citrus_as_of=citrus.source.as_of if citrus else None, damaged=damaged)
