"""Task 20: 파이프라인 조립, 계산 지문, 사실(Fact) 채우기."""
import re
from datetime import date
from functools import lru_cache

from app.core.models import FarmProfile
from app.core.pipeline import META_FACT_PREFIXES, build_fact_sheet, fingerprint, is_meta_fact
from app.data_layer.snapshot import load_snapshot
from app.data_layer.tables import load_tables
from conftest import AS_OF, P1_KWARGS, P3_KWARGS, P4_KWARGS, ROOT

P4 = FarmProfile(**P4_KWARGS)


@lru_cache(maxsize=None)
def tables():
    return load_tables(ROOT / "data" / "tables", AS_OF)


@lru_cache(maxsize=None)
def snap():
    return load_snapshot(ROOT / "data" / "snapshot", AS_OF, crops=tables().crops)


def build(profile=P4, as_of=AS_OF, version="v"):
    return build_fact_sheet(profile, tables(), snap(), as_of, version)


def test_same_input_same_fingerprint():
    assert fingerprint(build()) == fingerprint(build())


def test_fingerprint_is_8_hex_and_stored_on_sheet():
    fs = build()
    assert re.fullmatch(r"[0-9a-f]{8}", fingerprint(fs)) and fs.fingerprint == fingerprint(fs)


def test_asof_changes_fingerprint():
    assert fingerprint(build(as_of=date(2026, 11, 13))) != fingerprint(build(as_of=date(2026, 11, 14)))


def test_data_version_and_profile_change_fingerprint():
    assert fingerprint(build(version="v")) != fingerprint(build(version="w"))
    assert fingerprint(build()) != fingerprint(build(FarmProfile(**{**P4_KWARGS, "birth_year": 1962})))


def test_fingerprint_ignores_its_own_slot():
    fs = build()
    assert fingerprint(fs.model_copy(update={"fingerprint": "zzzzzzzz"})) == fingerprint(fs)


def test_pipeline_order_and_shape():
    fs = build()
    assert fs.as_of == AS_OF and fs.data_version == "v"
    assert fs.matches and fs.amounts and fs.insurance and fs.actions
    assert fs.header.tables_verified == tables().verified_date and fs.header.snapshot_built == snap().built_at
    assert fs.header.price_as_of == snap().price_as_of and fs.header.demo_asof is False
    assert [t.rule_id for t in fs.triggers].count("PRICE_STAB") == len(fs.profile.crops)


def test_two_crops_get_triggers_each():
    fs = build(FarmProfile(**P3_KWARGS))
    assert [t.rule_id for t in fs.triggers].count("PRICE_STAB") == 2


def test_source_hold_reaches_fact_sheet_for_nh_safety():
    fs = build()
    safety = [r for r in fs.insurance if r.product_id.startswith("nh_safety")]
    assert safety and all("source_hold" in r.reasons for r in safety)
    crop = [r for r in fs.insurance if not r.product_id.startswith("nh_safety")]
    assert all("source_hold" not in r.reasons for r in crop)


def test_actions_limit_keeps_at_least_8():
    from app.core.actions import next_actions
    fs = build(FarmProfile(**{**P4_KWARGS, "mgmt_status": "over_2y", "mgmt_last_reg_year": 2024, "spouse": "registered"}))
    every = next_actions(fs.profile, tables(), fs.matches, fs.insurance, fs.amounts, fs.triggers, fs.as_of, limit=100)
    assert len(every) > 5 and len(fs.actions) == min(8, len(every))


def test_expected_notice_month_on_prior_year_facts():
    fs = build()
    prior = [f for f in fs.facts if f.row_status == "prior_year_reference"]
    assert prior
    by_id = {p.id: p for p in tables().programs}
    for f in prior:
        pid = f.fact_id.split(":", 1)[1]
        assert f.expected_notice_month == by_id[pid].expected_notice_month
    assert any(f.expected_notice_month for f in prior)
    assert all(f.expected_notice_month is None for f in fs.facts if f.row_status != "prior_year_reference")


def test_demo_asof_flag_passes_through():
    fs = build_fact_sheet(P4, tables(), snap(), AS_OF, "v", demo_asof=True)
    assert fs.header.demo_asof is True


def test_meta_fact_helper_marks_name_and_office_facts():
    fs = build()
    meta = [f for f in fs.facts if is_meta_fact(f)]
    assert meta and all(f.fact_id.startswith(META_FACT_PREFIXES) for f in meta)
    assert all(not is_meta_fact(f) for f in fs.facts if not f.fact_id.startswith(META_FACT_PREFIXES))


def test_insurance_office_fact_is_per_product_not_per_source():
    b = tables()
    rows = [p for p in b.insurance if p.product_id == "crop_disaster" and "감귤_노지" in (p.crop_keys or ())]
    assert len(rows) == 1
    only_nojigi = rows[0].model_copy(update={"crop_keys": ("감귤_노지",), "office_id": "office_x"})
    only_mangam = rows[0].model_copy(update={"crop_keys": ("감귤_만감",), "office_id": "office_y"})
    rest = tuple(p for p in b.insurance if p is not rows[0])
    bundle = b.model_copy(update={"insurance": (only_nojigi, only_mangam, *rest)})
    kw = {**P1_KWARGS, "crops": ({"crop_code": "감귤_노지", "area_m2": 4959, "sales_channel": "coop", "selfpay_fund": "unknown"},
                                 {"crop_code": "감귤_만감", "area_m2": 1000, "sales_channel": "coop", "selfpay_fund": "unknown"})}
    fs = build_fact_sheet(FarmProfile(**kw), bundle, snap(), AS_OF, "v")
    office = {f.fact_id: f.value for f in fs.facts if f.fact_id.startswith("office:crop_disaster")}
    assert office == {"office:crop_disaster:감귤_노지": "office_x", "office:crop_disaster:감귤_만감": "office_y"}
