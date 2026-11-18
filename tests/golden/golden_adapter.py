"""골든 케이스 JSON(profile 키, golden-spec/2) → FarmProfile.

골든 JSON은 1라운드 필드명을 쓴다. tests/conftest.py 머리의 대응표와 같은 규칙으로 옮긴다(그 표가 정본).
make_samples.py도 이 파일을 쓴다(샘플 입력 = 골든 입력).

대응표에 근거가 있는 규칙(Task 34에서 추측을 걷어 냈다):
  coop_shipping=Y → sales_channel "coop", 아니고 field_sold_contract=Y → "field_contract_done", 둘 다 아니면 "unknown"
  selfpay_fund_member Y/N/? → paid/not_paid/unknown (자조금 품목이 아니면 na)
  owns_farmland=Y → land_tenure "own_all" (골든 JSON에는 '일부 내 땅'을 가리는 칸이 없다), N → "rent_all"
  owned_area_ge_15500m2는 5a 질문이 나오는 구간(총 1,000~9,554㎡)이고 내 땅이 있을 때만 owned_over_4700py로 옮긴다
  mgmt_registered Y + mgmt_years ≥ 2 → over_2y, Y + 2년 미만 → under_2y, N → none
  spouse_sex는 사례 JSON이 적은 곳(P2·P3·P5·G13: 아내)에서만 옮기고 없으면 None(추측하지 않는다)
  1라운드 칸 중 FarmProfile에 짝이 없는 것(매핑 없음): coop_member, offfarm_income_band, disaster_end_date, flags 목록,
  farmland_owned_years의 숫자(→ land_held_2y 참/거짓만), jeju_residence_years의 숫자(→ residence_3y만)
"""
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core.models import FarmProfile, SourceRef
from app.core.snapshot_models import PricePoint, PriceSeries, Snapshot
from app.ui.forms import SELFPAY_CROPS

CASES_DIR = Path(__file__).resolve().parent / "cases"
CROP_CODE = {"노지온주": "감귤_노지", "만감류": "감귤_만감"}


def load_case(case_id: str) -> dict:
    return json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def _channel(coop: str | None, field: str | None) -> str:
    if coop == "Y":
        return "coop"
    if field == "Y":
        return "field_contract_done"
    return "unknown"


def _fund(code: str, answer: str | None) -> str:
    if code not in SELFPAY_CROPS:
        return "na"
    return {"Y": "paid", "N": "not_paid"}.get(answer or "?", "unknown")


def to_profile(p: dict) -> FarmProfile:
    enrolled = set(p.get("insurance_enrolled") or ())
    disaster_ins = True if "disaster" in enrolled else None
    code = CROP_CODE.get(p["crop_key"], p["crop_key"])
    crops = [{"crop_code": code, "area_m2": p["area_m2"], "ins_disaster": disaster_ins,
              "sales_channel": _channel(p["coop_shipping"], p["field_sold_contract"]),
              "selfpay_fund": _fund(code, p["selfpay_fund_member"])}]
    if p.get("crop2_key"):
        code2 = CROP_CODE.get(p["crop2_key"], p["crop2_key"])
        crops.append({"crop_code": code2, "area_m2": p["crop2_area_m2"], "ins_disaster": disaster_ins,
                      "sales_channel": _channel(p["crop2_coop_shipping"], p["crop2_field_sold_contract"]),
                      "selfpay_fund": _fund(code2, p["crop2_selfpay_fund_member"])})
    owns = p["owns_farmland"] == "Y"
    total = p["total_farm_area_m2"]
    big = p["owned_area_ge_15500m2"] == "Y"
    years = p.get("farmland_owned_years")
    spouse = {"registered": "registered", "unregistered": "cofarming_unregistered"}.get(p["spouse_status"], "none")
    mgmt_years = p.get("mgmt_years") or 0
    mgmt = "none" if p["mgmt_registered"] != "Y" else ("over_2y" if mgmt_years >= 2 else "under_2y")
    ins_safety = set()
    if "safety" in enrolled:
        ins_safety = {"owner", "spouse"} if spouse == "registered" else {"owner"}
    return FarmProfile(
        visitor="family_proxy" if p["visitor"] == "family" else "self",
        owner_sex=p["sex"], emd_code=p.get("eupmyeon") or p["region"],
        birth_year=p["birth_year"], birth_year_approx=p["birth_year_approx"],
        crops=tuple(crops), total_area_m2=total,
        land_tenure="own_all" if owns else "rent_all",
        land_held_2y=(years is None or years >= 2) if owns else None,
        owned_over_4700py=big if owns and 1000 <= total <= 9554 else None,
        mgmt_status=mgmt, mgmt_last_reg_year=p.get("mgmt_last_registered_year") if mgmt != "none" else None,
        spouse=spouse, spouse_birth_year=p.get("spouse_birth_year"), spouse_sex=p.get("spouse_sex"),
        farming_years=p["farming_years"], farming_10y_plus=p["farming_years"] >= 10,
        residence_3y=p["jeju_residence_years"] >= 3,
        health_ins="unknown" if p["health_insurance"] == "?" else p["health_insurance"],
        flags={"disaster_damage": p["disaster_damage"] == "Y", "direct_payment_education": p["direct_payment_education"]},
        already_receiving=frozenset(k.split("#")[0] for k in p["already_receiving"]),
        ins_safety=frozenset(ins_safety),
    )


def build_paper(profile: FarmProfile, bundle, snap, cfg, *, data_version: str | None = None):
    """상담 한 건의 종이를 만든다(앱 routes_counsel과 같은 순서). (fs, sheet, html)."""
    from app.core.pipeline import build_fact_sheet
    from app.core.sheet import build_sheet
    from app.ui.render import render_sheet

    version = data_version or f"표{bundle.verified_date.isoformat()}+저장본{snap.built_at.isoformat()}"
    fs = build_fact_sheet(profile, bundle, snap, cfg.as_of, version, demo_asof=cfg.demo_asof)
    sheet = build_sheet(fs, bundle, cfg.as_of)
    sheet = sheet.model_copy(update={"back": sheet.back.model_copy(update={"fingerprint_slot": f"계산 지문 {fs.fingerprint}"})})
    html = render_sheet(sheet, fs, None, cfg, crop_labels={c.crop_code: c.label for c in bundle.crops}, programs=bundle.programs)
    return fs, sheet, html


# --- 사례별 환경(기준일·표·스냅샷·fixture) ---------------------------------------------------------------

@dataclass(frozen=True)
class CaseEnv:
    cfg: object
    bundle: object
    snap: Snapshot


def _synthetic_prices(snap: Snapshot, ov: dict) -> Snapshot:
    """fixture.price_override(규칙 PRICE_STAB): 그 작물 판정 시리즈의 해당 반월을 합성 평균 가격 n일치로 바꾼다.
    합성 점은 거래량 1,000kg의 하루치씩이라 거래량 가중 평균이 곧 avg_won_per_kg다. 시험 전용이며 스냅샷 파일은 건드리지 않는다."""
    first, _ = (date.fromisoformat(x) for x in ov["half_month"].split("~"))
    last = date.fromisoformat(ov["half_month"].split("~")[1])
    days = [date.fromordinal(first.toordinal() + i) for i in range(ov["n_days_with_data"])]
    assert days[-1] <= last, "합성 일수가 반월을 넘습니다"
    prices, seeded = {}, False
    for key, s in snap.prices.items():
        if s.crop_code == ov["crop_key"] and s.judge:
            keep = tuple(p for p in s.points if not first <= p.day <= last)
            fake = () if seeded else tuple(PricePoint(d, Decimal(ov["avg_won_per_kg"]), Decimal(1000)) for d in days)
            seeded = seeded or bool(fake)
            s = s.model_copy(update={"points": tuple(sorted(keep + fake, key=lambda p: p.day))})
        prices[key] = s
    return snap.model_copy(update={"prices": prices})


def _saved_citrus(snap: Snapshot, saved: str) -> Snapshot:
    """fixture.jasdc "saved_YYYYMMDD": 인터넷이 없어 수급센터 저장본이 그 날짜까지인 상황. 그 뒤 점을 자르고 기준일 표시를 그 날로."""
    day = date(int(saved[-8:-4]), int(saved[-4:-2]), int(saved[-2:]))
    c = snap.citrus
    if c is None:
        return snap
    c = c.model_copy(update={"points": tuple(p for p in c.points if p.day <= day), "source": c.source.model_copy(update={"as_of": day})})
    return snap.model_copy(update={"citrus": c, "citrus_as_of": day})


def case_env(case: dict) -> CaseEnv:
    """사례의 as_of로 설정·표·스냅샷을 읽고 fixture(합성 가격, 저장본 감귤)를 입힌다."""
    from app.config import load_config
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables

    cfg = load_config(["--asof", case["as_of"]])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    fx = case.get("fixture") or {}
    if (ov := fx.get("price_override")) and ov.get("rule") == "PRICE_STAB":
        snap = _synthetic_prices(snap, ov)
    if (saved := fx.get("jasdc", "")).startswith("saved_"):
        snap = _saved_citrus(snap, saved)
    return CaseEnv(cfg, bundle, snap)
