"""Task 3(U03) 표 검증기: 나쁜 표 12종은 한국어 오류, 배포 표는 오류 0건, R17~R19, Excel 행 번호."""
import csv
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.data_layer.validate import Issue, validate_tables

ROOT = Path(__file__).resolve().parents[2]
BAD = ROOT / "tests" / "fixtures" / "tables_bad"

# 픽스처마다 결함 하나만 넣었다. 나오는 오류 코드도 그 하나뿐이어야 한다(다른 칸은 깨끗하다는 뜻).
EXPECTED_ERROR_CODES = {
    "01_not_number": {"E11"},              # 금액 칸에 '50만원'
    "02_date_order": {"R02"},              # 신청 시작일 > 마감일
    "03_enum_out": {"E14"},                # 지원 형태 '현찰'
    "04_dup_id": {"R13"},                  # 같은 행 ID 두 번
    "05_unknown_crop": {"E16"},            # 대상 작물 '흙당근'(별칭일 뿐 crops.csv 코드가 아님)
    "06_e_pair": {"R06"},                  # needs_coop=E인데 needs_selfpay_fund 빈칸
    "07_source_missing_confirmed": {"R01"},
    "08_prior_no_notice_month": {"R18"},
    "09_manwon_suspect": {"R15"},          # 정액 50원(만원 단위로 넣음)
    "10_manual_check_over_60": {"R20"},    # 확인 항목 한 칸 69자
    "11_cp949_broken": {"E05"},            # cp949 파일을 UTF-8로 잘못 열어 저장한 '�'
    "12_missing_required_column": {"E02"},  # 접수처(office) 컬럼 없음
}


def bad_dirs():
    dirs = sorted(p for p in BAD.iterdir() if p.is_dir())
    assert dirs, f"no fixtures under {BAD}"
    return dirs


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


@pytest.mark.parametrize("bad", bad_dirs(), ids=lambda p: p.name)
def test_bad_tables_produce_korean_error(bad):
    issues = validate_tables(bad)
    assert any(i.level == "error" for i in issues)
    assert all(re.search(r"[가-힣]", i.message_ko) for i in issues)


def test_twelve_bad_fixtures_one_per_kind():
    assert [p.name for p in bad_dirs()] == sorted(EXPECTED_ERROR_CODES)


@pytest.mark.parametrize("name", sorted(EXPECTED_ERROR_CODES))
def test_bad_fixture_raises_only_its_own_error(name):
    got = {i.code for i in errors(validate_tables(BAD / name))}
    assert got == EXPECTED_ERROR_CODES[name]


def test_shipped_tables_have_no_errors(tables_dir):
    assert [i for i in validate_tables(tables_dir) if i.level == "error"] == []


def _date_relative(issues: list[Issue]) -> list[Issue]:
    """기준일에 따라 달라지는 경고: 확인일 180일(R15)·적용 기간 끝남(R15)·신청 마감 지남(R16)."""
    return [i for i in issues if i.level == "warning"
            and ((i.code == "R15" and i.column in ("verified_date", "valid_to")) or i.code == "R16")]


def test_without_today_date_relative_warnings_are_skipped(tables_dir, monkeypatch):
    """검증기는 시계를 읽지 않는다(오늘 날짜는 app/config.py 한 곳). today를 안 주면 날짜 경고를 건너뛴다."""
    import app.data_layer.validate as validate

    class FarFuture(date):                       # 시계를 읽으면 모든 행이 오래된 것으로 보이게
        @classmethod
        def today(cls):
            return cls(2030, 1, 1)

    monkeypatch.setattr(validate, "date", FarFuture)
    assert _date_relative(validate_tables(tables_dir)) == []
    later = _date_relative(validate_tables(tables_dir, today=date(2027, 7, 1)))   # 확인일 2026-11-07에서 236일 뒤
    assert {i.column for i in later} >= {"verified_date", "valid_to"}


def test_issue_points_at_excel_row_and_file():
    # 04_dup_id: 머리글 1행, 농민수당 2행, 연금 3행, 겹친 연금 행 4행
    (dup,) = errors(validate_tables(BAD / "04_dup_id"))
    assert (dup.file, dup.row_excel, dup.column) == ("supports.csv", 4, "id")
    assert "3행" in dup.message_ko


def test_missing_column_names_the_label():
    (e,) = errors(validate_tables(BAD / "12_missing_required_column"))
    assert e.row_excel == 1 and e.column == "office" and "접수처" in e.message_ko


# --- 배포 표를 복사해 한 칸만 바꾸는 검사 --------------------------------------------------

def _copy_tables(tables_dir: Path, dst: Path) -> Path:
    shutil.copytree(tables_dir, dst)
    return dst


def _edit_supports(d: Path, row_id: str, **changes: str) -> None:
    path = d / "supports.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        header, rows = rd.fieldnames, list(rd)
    hit = [r for r in rows if r["id"] == row_id]
    assert hit, row_id
    hit[0].update(changes)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)


def test_r19_non_hold_row_needs_verified_by(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-PENSION-SUPPORT@2026", verified_by="", verified_date="")
    errs = errors(validate_tables(d))
    assert {(e.code, e.column) for e in errs} == {("R19", "verified_by"), ("R19", "verified_date")}


def test_hold_row_may_leave_required_cells_blank(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-SAFETY-INS@2026", verified_by="", verified_date="", agency="", office="", renew_type="")
    assert errors(validate_tables(d)) == []


def test_hold_row_skips_cross_rules(tables_dir, tmp_path):
    # hold 행은 식별·형식 검사만: 연1회인데 마감일 없음(R03), 나이 기준일 없음(R04), E 짝 깨짐(R06),
    # 정액 50원(R15), 긴 확인 항목(R20), 없는 제도 키(R11)도 오류가 아니다.
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-SAFETY-INS@2026", apply_cycle="연1회", apply_end="", min_age="60", age_basis="",
                   needs_coop="E", needs_selfpay_fund="", amount_type="정액", amount_value="50",
                   manual_check="가" * 61, excludes="NO-SUCH-KEY")
    assert errors(validate_tables(d)) == []


def test_hold_row_minimal_cross_rule_case(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-SAFETY-INS@2026", apply_cycle="연1회", apply_end="")
    assert errors(validate_tables(d)) == []
    _edit_supports(d, "NAT-SAFETY-INS@2026", status="confirmed")  # 같은 칸이라도 hold가 아니면 R03
    assert "R03" in {e.code for e in errors(validate_tables(d))}


def test_hold_row_still_gets_format_checks(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-SAFETY-INS@2026", min_age="예순")
    assert {e.code for e in errors(validate_tables(d))} == {"E11"}


def test_hold_row_still_needs_identity(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-SAFETY-INS@2026", edition="")
    assert {e.code for e in errors(validate_tables(d))} == {"E10"}


def test_r18_prior_row_needs_source_url(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "JEJU-FARMER-ALLOW@2026", source_url="")
    errs = errors(validate_tables(d))
    assert errs and all(e.column == "source_url" for e in errs)


def test_r17_cp949_unsafe_dash_is_only_a_warning(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    _edit_supports(d, "NAT-PENSION-SUPPORT@2026", notes="연금 – 배우자 줄")
    issues = validate_tables(d)
    assert errors(issues) == []
    assert any(i.code == "R17" and i.level == "warning" and "–" in i.message_ko for i in issues)


def test_cp949_saved_file_is_read_with_warning(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    text = (d / "crops.csv").read_text(encoding="utf-8-sig")
    (d / "crops.csv").write_bytes(text.encode("cp949"))
    issues = validate_tables(d)
    assert errors(issues) == []
    assert any(i.code == "E00" and i.file == "crops.csv" for i in issues)


def test_missing_file_is_an_error(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    (d / "offices.csv").unlink()
    assert {(e.code, e.file) for e in errors(validate_tables(d))} == {("E04", "offices.csv")}


def test_inbox_rows_are_not_validated(tables_dir, tmp_path):
    d = _copy_tables(tables_dir, tmp_path / "t")
    (d / "inbox_k_rows.csv").write_text("완전히,깨진,파일\n", encoding="utf-8")
    assert errors(validate_tables(d)) == []


def test_every_supports_office_is_in_offices_csv(tables_dir):
    def rows(name):
        with (tables_dir / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    names = {r["name"] for r in rows("offices.csv")}
    assert {r["office"] for r in rows("supports.csv")} - names == set()
