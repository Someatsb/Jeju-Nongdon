# -*- coding: utf-8 -*-
"""앱의 가격안정관리제 반월 판정 vs 공식 발동 횟수 대조 (2026-11-11).

질문: 앱이 1361 반월 가중 평균으로 내는 '아래(MET)·근처(NEAR)·위(NOT_MET)' 판정을 2025-26 시즌의 모든 반월에
      적용하면, 공식 발동 횟수(params stab_hits_official: 당근 8회·양배추 9회, 도 보도 2026-06-24)와 몇 회나 맞는가?
방법: 시즌 달(stab_months)의 반월 끝날마다 as_of를 두고 동봉 저장본(data/snapshot)을 그 날짜로 잘라
      app.core.triggers.check_triggers를 그대로 부른다(앱과 같은 코드·같은 표). 공식 발동 '날짜'는 공개되지 않아
      횟수만 비교한다. 선택으로 다른 경계 배수(--band lo,hi)를 넣어 같은 표를 다시 낸다.
실행(jeju-chaenggim 폴더에서): python -X utf8 scripts/compare_official_hits.py [--season 2025-26] [--band 0.911,1.143]
키·인터넷은 쓰지 않는다. 출력은 표준 출력(마크다운 표)이며 파일을 바꾸지 않는다.
"""
import argparse
import calendar
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.params_view import season_params  # noqa: E402
from app.core.triggers import check_triggers  # noqa: E402
from app.data_layer.snapshot import load_snapshot  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402

CROPS = ("당근", "양배추")


def half_ends(season: str, months: tuple[int, ...]):
    y0 = int(season[:4])
    out = []
    for m in months:
        y = y0 if m >= 7 else y0 + 1
        out.append(date(y, m, 15))
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--band", default=None, help="예: 0.911,1.143 (비우면 표의 값)")
    a = ap.parse_args()
    band = tuple(Decimal(x) for x in a.band.split(",")) if a.band else None
    tables_dir, snap_dir = ROOT / "data" / "tables", ROOT / "data" / "snapshot"
    bundle0 = load_tables(tables_dir, date(2026, 11, 13))
    print(f"# 가격안정관리제 반월 판정 vs 공식 발동 횟수 — 시즌 {a.season}" + (f", 경계 {band[0]}/{band[1]}" if band else ", 경계 표 값"))
    for crop in CROPS:
        p0 = season_params(bundle0, crop, date(int(a.season[:4]), 12, 1))
        months = p0.stab_months or p0.season_months
        official = next((r.value for r in bundle0.params if r.crop == crop and r.param == "stab_hits_official"
                         and r.season == a.season), None)
        print(f"\n## {crop} — 기준가 {p0.stab_base}원/kg, 대상 달 {months}, 공식 발동 {official}회")
        print("| 반월 | 거래일 | 반월 가중 평균(원/kg) | 기준가 대비 | 판정 |")
        print("|---|---|---|---|---|")
        counts = {}
        for end in half_ends(a.season, tuple(months)):
            bundle = load_tables(tables_dir, end)
            snap = load_snapshot(snap_dir, end, crops=bundle.crops)
            params = season_params(bundle, crop, end)
            if band:
                params = params.model_copy(update={"stab_band_lo": band[0], "stab_band_hi": band[1]})
            r = check_triggers(crop, snap, params, bundle.interventions, end)[0]
            counts[r.status] = counts.get(r.status, 0) + 1
            ratio = f"{(r.observed / p0.stab_base):.3f}" if r.observed is not None else "—"
            obs = f"{r.observed:,.1f}" if r.observed is not None else "—"
            start = end.replace(day=1) if end.day == 15 else end.replace(day=16)
            print(f"| {start.isoformat()}~{end.day}일 | {r.n_days_with_data} | {obs} | {ratio} | {r.status}{' (잠정)' if r.provisional else ''} |")
        print(f"\n집계: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) +
              f" / 공식 발동 {official}회 (반월 {len(half_ends(a.season, tuple(months)))}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
