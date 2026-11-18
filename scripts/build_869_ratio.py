"""869 → 반월 가락/1361 비 집계(Task 12, U12). data/snapshot/agg_869_ratio.csv를 만들고 manifest.json을 새로 쓴다.

params_by_season.csv stab_band_lo/hi(당근 0.911/1.143, round2-B §3)의 근거 파일이다. 앱은
app/data_layer/snapshot.py에서 이 파일의 반월 비로 (1/p90, 1/p10)을 계산해 Snapshot.ratio_bounds에 둔다.

방법(round1-B-data.md 부록 B "경계 비율"):
- 869 당근 원본에서 품종명 '당근(일반)', 공영 도매시장명 '서울가락도매' 행만 쓴다.
  원/kg = 평균가 ÷ 거래단량, kg = 거래량 × 거래단량. 하루 가락 값은 kg 가중 평균.
- 1361 당근(일반) averagePrice를 거래량(톤)으로 가중한다(0톤 행은 뺀다).
- 둘 다 있는 날만, 11~3월만, 반월(1~15 · 16~말)마다 가락 가중 평균 ÷ 1361 가중 평균.
- 양배추는 869 단위 정합이 안 돼(일별 차 중앙값 30%) 만들지 않는다(round2-B §3).

원본(약 14MB, cp949, 파일명이 NFD 한글)은 저장소에 넣지 않는다.
사용(jeju-chaenggim/에서):
  python -X utf8 -I scripts/build_869_ratio.py [--src <원본 CSV 또는 그 폴더>] [--built-at YYYY-MM-DD]
--src 기본값은 ../data/hub(폴더면 이름으로 찾는다). --built-at을 빼면 manifest.json의 built_at을 그대로 둔다.
"""
import argparse
import csv
import json
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.data_layer.snapshot import DATASETS, MANIFEST, write_manifest  # noqa: E402

SNAP = ROOT / "data" / "snapshot"
SRC_NAME = "869_전국도매시장 일별 경락가격_당근(최종).csv"
CROP, CULTIVAR, MARKET = "당근", "당근(일반)", "서울가락도매"
MONTHS = {11, 12, 1, 2, 3}
HEAD = ["crop", "cultivar", "market", "half_start", "half_end", "n_days", "garak_won_per_kg", "garak_kg",
        "hub1361_won_per_kg", "hub1361_t", "ratio"]


def find_src(where: Path) -> Path | None:
    """파일이면 그대로, 폴더면 그 안에서 SRC_NAME을 찾는다(원본 파일명이 NFD라 글자 그대로는 안 열림)."""
    if where.is_file():
        return where
    if where.is_dir():
        for p in where.iterdir():
            if unicodedata.normalize("NFC", p.name) == SRC_NAME:
                return p
    return None


def half(day: date) -> tuple[date, date]:
    if day.day <= 15:
        return day.replace(day=1), day.replace(day=15)
    nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return day.replace(day=16), nxt - timedelta(days=1)


def garak_daily(src: Path) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
    won: dict[date, Decimal] = defaultdict(Decimal)
    kg: dict[date, Decimal] = defaultdict(Decimal)
    with open(src, encoding="cp949", newline="") as f:
        for r in csv.DictReader(f):
            if r["품종명"] != CULTIVAR or r["공영 도매시장명"] != MARKET:
                continue
            unit, qty = Decimal(r["거래단량"]), Decimal(r["거래량"])
            if unit <= 0 or qty <= 0:
                continue
            day = date.fromisoformat(r["경락일"][:10])
            won[day] += Decimal(r["평균가"]) * qty       # (평균가 ÷ 거래단량 원/kg) × (거래량 × 거래단량 kg)
            kg[day] += qty * unit
    return won, kg


def hub_daily(path: Path) -> dict[date, tuple[Decimal, Decimal]]:
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            vol = Decimal(r["transactionVolume"])
            if r["cultivar"] == CULTIVAR and vol > 0:
                out[date.fromisoformat(r["baseDate"])] = (Decimal(r["averagePrice"]), vol)
    return out


def q(x: Decimal, step: str) -> str:
    return str(x.quantize(Decimal(step), rounding=ROUND_HALF_UP))


def build(src: Path, hub_csv: Path) -> list[list]:
    won, kg = garak_daily(src)
    hub = hub_daily(hub_csv)
    acc: dict[tuple[date, date], list] = defaultdict(lambda: [0, Decimal(0), Decimal(0), Decimal(0), Decimal(0)])
    for day in sorted(set(won) & set(hub)):
        if day.month in MONTHS:
            a, (price, ton) = acc[half(day)], hub[day]
            a[0] += 1
            a[1] += won[day]
            a[2] += kg[day]
            a[3] += price * ton
            a[4] += ton
    rows = []
    for (start, end), (n, w, k, pt, t) in sorted(acc.items()):
        garak, hub_avg = w / k, pt / t
        rows.append([CROP, CULTIVAR, MARKET, start.isoformat(), end.isoformat(), n, q(garak, "0.1"), q(k, "1"),
                     q(hub_avg, "0.1"), q(t, "0.01"), q(garak / hub_avg, "0.0001")])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="869 당근 원본 → data/snapshot/agg_869_ratio.csv + manifest.json")
    ap.add_argument("--src", type=Path, default=ROOT.parent / "data" / "hub", help="869 당근 원본 CSV(cp949) 또는 그 폴더")
    ap.add_argument("--built-at", type=date.fromisoformat, help="manifest.json built_at(빼면 그대로)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    src = find_src(a.src)
    if src is None:
        print(f"869 원본을 찾지 못했습니다. --src로 '{SRC_NAME}' 경로를 주세요.")
        return 1
    built_at = a.built_at
    if built_at is None:
        if not (SNAP / MANIFEST).exists():
            print(f"{MANIFEST}이 없어 --built-at이 필요합니다.")
            return 1
        built_at = date.fromisoformat(json.loads((SNAP / MANIFEST).read_text(encoding="utf-8"))["built_at"])

    rows = build(src, SNAP / DATASETS["hub_1361"][0])
    with open(SNAP / DATASETS["agg_869_ratio"][0], "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        w.writerows(rows)
    write_manifest(SNAP, built_at)

    ratios = [Decimal(r[-1]) for r in rows]
    p = statistics.quantiles(ratios, n=10, method="inclusive")
    print(f"{CROP} {CULTIVAR} {MARKET}: 반월 {len(rows)}개 ({rows[0][3]} ~ {rows[-1][4]}), "
          f"가락/1361 비 p10 {p[0]:.4f} · p50 {statistics.median(ratios):.4f} · p90 {p[8]:.4f}")
    print(f"→ {DATASETS['agg_869_ratio'][0]}, {MANIFEST}(built_at {built_at}) 다시 씀")
    return 0


if __name__ == "__main__":
    sys.exit(main())
