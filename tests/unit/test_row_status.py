"""Task 3(U03) 표 로더: 행 상태 3단계, superseded, 이름 지정 파일만 읽기, 표 확인일."""
import csv
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.models import Program
from app.core.tables_models import Crop, InsuranceProduct, Intervention, Office, SeasonParam, TableBundle
from app.data_layer.tables import TableLoadError, load_tables, mark_superseded

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 11, 13)


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames), list(rd)


def _write(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)


def _add_edition(d: Path, src_id: str, new_id: str, **changes: str) -> None:
    header, rows = _rows(d / "supports.csv")
    src = next(r for r in rows if r["id"] == src_id)
    rows.append({**src, "id": new_id, **changes})
    _write(d / "supports.csv", header, rows)


@pytest.fixture
def tmp_tables_with_2027_confirmed(tables_dir, tmp_path) -> Path:
    d = tmp_path / "tables"
    shutil.copytree(tables_dir, d)
    _add_edition(
        d, "JEJU-FARMER-ALLOW@2026", "JEJU-FARMER-ALLOW@2027",
        edition="2027", status="confirmed", valid_from="2027-01-01", valid_to="2027-12-31",
        apply_start="2027-03-08", apply_end="2027-03-31", expected_notice_month="",
    )
    return d


def test_prior_row_superseded_by_confirmed(tmp_tables_with_2027_confirmed):
    b = load_tables(tmp_tables_with_2027_confirmed, date(2027, 1, 10))
    rows = [p for p in b.programs if p.program_key == "JEJU-FARMER-ALLOW"]
    assert {p.status for p in rows} == {"confirmed", "hold"}


def test_superseded_row_keeps_its_data_and_says_why(tmp_tables_with_2027_confirmed):
    b = load_tables(tmp_tables_with_2027_confirmed, date(2027, 1, 10))
    old = next(p for p in b.programs if p.id == "JEJU-FARMER-ALLOW@2026")
    new = next(p for p in b.programs if p.id == "JEJU-FARMER-ALLOW@2027")
    assert (old.status, old.hold_reason) == ("hold", "superseded")
    assert (new.status, new.hold_reason) == ("confirmed", None)
    assert old.amount_value == 500000 and old.expected_notice_month == 3


def test_no_supersede_before_the_confirmed_year(tmp_tables_with_2027_confirmed):
    # 2026년 기준일에는 2027 confirmed가 '올해' 행이 아니다.
    b = load_tables(tmp_tables_with_2027_confirmed, date(2026, 11, 13))
    old = next(p for p in b.programs if p.id == "JEJU-FARMER-ALLOW@2026")
    assert old.status == "prior_year_reference"


def _program(pid: str, status: str, **kw) -> Program:
    key, _, rest = pid.partition("@")
    return Program(id=pid, program_key=key, edition=rest.partition("#")[0], status=status, **kw)


def test_supersede_matches_season_edition_by_its_first_year():
    progs = (
        _program("JEJU-PSTAB@2026-27#당근", "prior_year_reference", expected_notice_month=9),
        _program("JEJU-PSTAB@2027-28#당근", "confirmed"),
    )
    out = mark_superseded(progs, date(2027, 9, 1))
    assert [(p.id, p.status, p.hold_reason) for p in out] == [
        ("JEJU-PSTAB@2026-27#당근", "hold", "superseded"),
        ("JEJU-PSTAB@2027-28#당근", "confirmed", None),
    ]


def test_season_confirmed_still_current_in_january_of_its_second_year():
    # 2028-01-10은 2027-28 시즌 한복판. 2026-27 참고 행이 다시 살아나 같은 제도가 두 번 인쇄되면 안 된다.
    progs = (
        _program("JEJU-PSTAB@2026-27#당근", "prior_year_reference", expected_notice_month=9),
        _program("JEJU-PSTAB@2027-28#당근", "confirmed"),
    )
    out = {p.id: (p.status, p.hold_reason) for p in mark_superseded(progs, date(2028, 1, 10))}
    assert out == {"JEJU-PSTAB@2026-27#당근": ("hold", "superseded"), "JEJU-PSTAB@2027-28#당근": ("confirmed", None)}


def test_season_2026_27_confirmed_supersedes_2025_26_on_2027_01_10():
    progs = (
        _program("JEJU-LOGI@2025-26", "prior_year_reference", expected_notice_month=4),
        _program("JEJU-LOGI@2026-27", "confirmed"),
    )
    out = {p.id: p.status for p in mark_superseded(progs, date(2027, 1, 10))}
    assert out == {"JEJU-LOGI@2025-26": "hold", "JEJU-LOGI@2026-27": "confirmed"}


def test_older_confirmed_edition_is_superseded_too():
    progs = (
        _program("NAT-PENSION-SUPPORT@2026", "confirmed"),
        _program("NAT-PENSION-SUPPORT@2027", "confirmed"),
    )
    out = {p.id: (p.status, p.hold_reason) for p in mark_superseded(progs, date(2027, 3, 1))}
    assert out == {"NAT-PENSION-SUPPORT@2026": ("hold", "superseded"), "NAT-PENSION-SUPPORT@2027": ("confirmed", None)}


def test_future_confirmed_edition_does_not_count():
    # 2026-11 기준일에 미리 올려 둔 2027 confirmed는 아직 현재 회차가 아니다(지금 회차 2026이 남는다).
    progs = (_program("NAT-PENSION-SUPPORT@2026", "confirmed"), _program("NAT-PENSION-SUPPORT@2027", "confirmed"))
    assert [p.status for p in mark_superseded(progs, date(2026, 11, 13))] == ["confirmed", "confirmed"]


def test_latest_confirmed_wins_over_three_seasons():
    progs = (
        _program("JEJU-PSTAB@2025-26#당근", "confirmed"),
        _program("JEJU-PSTAB@2026-27#당근", "prior_year_reference", expected_notice_month=9),
        _program("JEJU-PSTAB@2027-28#당근", "confirmed"),
    )
    out = [p.status for p in mark_superseded(progs, date(2028, 2, 1))]
    assert out == ["hold", "hold", "confirmed"]


def test_hold_rows_from_the_table_keep_no_reason():
    progs = (_program("X-A@2026", "hold"), _program("X-A@2027", "confirmed"))
    assert mark_superseded(progs, date(2027, 5, 1))[0].hold_reason is None


def test_supersede_is_per_crop_variant():
    # 2027 마늘 보험이 확정돼도 2026 감귤 보험 참고 행은 그대로 둔다.
    progs = (
        _program("NAT-CROP-INS@2026#감귤", "prior_year_reference", expected_notice_month=4),
        _program("NAT-CROP-INS@2026#마늘", "prior_year_reference", expected_notice_month=10),
        _program("NAT-CROP-INS@2027#마늘", "confirmed"),
    )
    out = {p.id: p.status for p in mark_superseded(progs, date(2027, 10, 1))}
    assert out == {"NAT-CROP-INS@2026#감귤": "prior_year_reference", "NAT-CROP-INS@2026#마늘": "hold",
                   "NAT-CROP-INS@2027#마늘": "confirmed"}


def test_whole_program_confirmed_supersedes_every_variant():
    progs = (
        _program("NHIS-FARMER-SUPPORT@2026#읍면", "prior_year_reference", expected_notice_month=1),
        _program("NHIS-FARMER-SUPPORT@2027", "confirmed"),
    )
    assert mark_superseded(progs, date(2027, 2, 1))[0].status == "hold"


def test_supersede_rebuild_is_validated():
    # model_copy(update=)는 검증을 건너뛴다. 다시 만든 행도 검증을 거쳐야 한다.
    progs = (_program("X-A@2026", "prior_year_reference", expected_notice_month=3), _program("X-A@2027", "confirmed"))
    out = mark_superseded(progs, date(2027, 5, 1))
    assert Program.model_validate(out[0].model_dump()) == out[0]


def test_shipped_tables_load(tables_dir):
    b = load_tables(tables_dir, AS_OF)
    assert isinstance(b, TableBundle)
    assert len(b.programs) == 42 and all(isinstance(p, Program) for p in b.programs)
    assert len(b.params) == 74 and all(isinstance(p, SeasonParam) for p in b.params)
    assert len(b.crops) == 11 and all(isinstance(c, Crop) for c in b.crops)
    assert len(b.interventions) == 16 and all(isinstance(i, Intervention) for i in b.interventions)
    assert len(b.insurance) == 13 and all(isinstance(p, InsuranceProduct) for p in b.insurance)  # Task 11 insurance.csv
    assert b.offices and all(isinstance(o, Office) and k == o.office_id for k, o in b.offices.items())
    assert all(b.office_named(p.office) is not None for p in b.programs)  # 접수처 글자로 창구를 찾는다
    assert b.offices["coop"].name == "지역농협"


def test_hold_rows_are_kept_and_marked(tables_dir):
    b = load_tables(tables_dir, AS_OF)
    hold = {p.id for p in b.programs if p.status == "hold"}
    assert {"NAT-SAFETY-INS@2026", "JEJU-HAPPY-TAXI@2026#읍면", "JEJU-CITRUS-PSTAB@2026-27"} <= hold
    assert all(p.hold_reason is None for p in b.programs)  # 2026 기준일엔 superseded 없음


def test_prior_rows_carry_expected_notice_month(tables_dir):
    b = load_tables(tables_dir, AS_OF)
    prior = [p for p in b.programs if p.status == "prior_year_reference"]
    assert prior and all(p.expected_notice_month is not None for p in prior)
    farmer = next(p for p in prior if p.id == "JEJU-FARMER-ALLOW@2026")
    assert farmer.expected_notice_month == 3


def test_cells_are_typed(tables_dir):
    b = load_tables(tables_dir, AS_OF)
    farmer = next(p for p in b.programs if p.id == "JEJU-FARMER-ALLOW@2026")
    assert farmer.valid_from == date(2026, 1, 1) and farmer.min_residence_years == 3
    assert farmer.health_ins_in == ("지역", "피부양자") and farmer.payout_timing.startswith("탐나는전")
    carrot = next(c for c in b.crops if c.crop_code == "당근")
    assert carrot.season_months == (11, 12, 1, 2, 3) and "월동채소" in carrot.groups
    base = next(p for p in b.params if (p.season, p.crop, p.param) == ("2025-26", "당근", "stab_base"))
    assert base.value == "1088" and base.status == "보도"


def test_tables_verified_is_the_oldest_printable_row(tables_dir):
    # 시연 문서(round2-A §) "지원 표 확인일 2026-11-05": 종이에 나갈 수 있는 행 중 가장 오래된 확인일
    assert load_tables(tables_dir, AS_OF).verified_date == date(2026, 11, 5)


def test_only_named_files_are_loaded(tables_dir):
    # inbox_k_rows.csv(K의 초안)는 supports와 같은 머리글이지만 읽지 않는다.
    ids = {p.id for p in load_tables(tables_dir, AS_OF).programs}
    assert not {i for i in ids if i.startswith(("NAQS-MGMT-REG", "KRC-LEASE-TRUST", "MOIS-STORM-INS"))}


def test_bad_tables_refuse_to_load():
    with pytest.raises(TableLoadError) as e:
        load_tables(ROOT / "tests" / "fixtures" / "tables_bad" / "02_date_order", AS_OF)
    assert "신청 기간" in str(e.value) and e.value.issues


def test_optional_insurance_csv_is_parsed(tables_dir, tmp_path):
    d = tmp_path / "tables"
    shutil.copytree(tables_dir, d)
    header = ["product_id", "crop_keys", "windows", "min_age", "max_age", "needs_mgmt", "office_id",
              "subsidy_text", "extra_requirement", "source_id", "source_url", "verified_date"]
    _write(d / "insurance.csv", header, [{
        "product_id": "crop_disaster", "crop_keys": "마늘;양파", "windows": "09-15~11-13", "min_age": "",
        "max_age": "", "needs_mgmt": "Y", "office_id": "coop", "subsidy_text": "보험료 최대 90% 지원",
        "extra_requirement": "", "source_id": "notice:NH 2026 마늘", "source_url": "https://example.org/a",
        "verified_date": "2026-11-07",
    }])
    (p,) = load_tables(d, AS_OF).insurance
    assert isinstance(p, InsuranceProduct)
    assert (p.crop_keys, p.windows, p.needs_mgmt, p.min_age) == (("마늘", "양파"), (("09-15", "11-13"),), True, None)
    assert p.source.source_id == "notice:NH 2026 마늘" and p.source.as_of == date(2026, 11, 7)


def test_insurance_csv_with_misspelled_header_refuses_to_load(tables_dir, tmp_path):
    # 'crop_key'(s 빠짐) 머리글이면 crop_keys가 빈칸 = '모든 작물'로 읽힐 뻔했다.
    d = tmp_path / "tables"
    shutil.copytree(tables_dir, d)
    header = ["product_id", "crop_key", "windows", "min_age", "max_age", "needs_mgmt", "office_id",
              "subsidy_text", "extra_requirement", "source_id", "source_url", "verified_date"]
    _write(d / "insurance.csv", header, [{
        "product_id": "income_stab", "crop_key": "양배추", "windows": "08-01~09-30", "min_age": "", "max_age": "",
        "needs_mgmt": "Y", "office_id": "coop", "subsidy_text": "보험료 일부 지원", "extra_requirement": "",
        "source_id": "notice:x", "source_url": "", "verified_date": "2026-11-07",
    }])
    with pytest.raises(TableLoadError) as e:
        load_tables(d, AS_OF)
    assert "'crop_keys' 컬럼이 없습니다" in str(e.value)
    assert [(i.file, i.row_excel, i.column) for i in e.value.issues] == [("insurance.csv", 1, "crop_keys")]


def test_offices_mapping_is_read_only(tables_dir):
    b = load_tables(tables_dir, AS_OF)
    with pytest.raises(TypeError):
        b.offices["coop"] = b.offices["emd_home"]  # type: ignore[index]
    assert b.offices["coop"].name == "지역농협" and b.office_named("건보공단 지사").office_id == "nhis_branch"
    again = TableBundle.model_validate(b.model_dump())
    assert again.offices == b.offices and b.model_dump_json()  # 직렬화도 된다
