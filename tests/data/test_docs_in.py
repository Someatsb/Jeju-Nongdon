"""공고 문서 읽기와 받은편지함(Task 18)."""
import os
from pathlib import Path

import pytest

from app.data_layer import inbox
from app.data_layer.docs_in import UnsupportedFormat, extract

NOTICES = Path(__file__).resolve().parents[1] / "fixtures" / "notices"
_N1_ENV = os.environ.get("JC_NOTICE_N1_PDF")
N1_PDF = Path(_N1_ENV) if _N1_ENV else None
LONG = "가" * 60


def test_scanned_pdf_detected():
    doc = extract(NOTICES / "N8.pdf")
    assert doc.scanned and len(doc.pages) == 1 and doc.pages[0].lines == ()


@pytest.mark.skipif(N1_PDF is None or not N1_PDF.exists(),
                    reason="환경변수 JC_NOTICE_N1_PDF(원본 N1 PDF 4.3MB 경로)가 없다")
def test_n1_pdf_extracts_directly():
    doc = extract(N1_PDF)
    assert len(doc.pages) == 2 and not doc.scanned
    assert "물류비" in doc.text and "2547" in doc.text.replace(" ", "")


def test_text_fixture_pages_split_on_form_feed():
    doc = extract(NOTICES / "N1.txt")
    assert [p.number for p in doc.pages] == [1, 2] and not doc.scanned
    assert all(line == line.strip() and line for p in doc.pages for line in p.lines)


def test_raw_text_and_path_string_both_accepted():
    assert extract(f"{LONG}\n{LONG}").pages[0].lines == (LONG, LONG)
    assert extract(str(NOTICES / "N6.txt")).pages[0].lines[0].startswith("○○농협 공고")


def test_scanned_needs_most_pages_thin():
    assert extract(f"{LONG}\f짧음").scanned is False        # 절반: 본문이 있는 문서
    assert extract(f"{LONG}\f짧음\f표지").scanned is True    # 절반을 넘으면 스캔본
    assert extract("짧음").scanned and extract("").scanned
    assert extract(f"{LONG}\f   \n  ").scanned is False


@pytest.mark.parametrize("name", ["a.hwp", "B.HWPX"])
def test_hwp_is_refused_in_korean(name):
    with pytest.raises(UnsupportedFormat, match="PDF로 저장해 주세요"):
        extract(NOTICES / name)
    with pytest.raises(UnsupportedFormat, match="PDF로 저장해 주세요"):
        extract(name)


def test_unknown_suffix_path_is_refused(tmp_path):
    with pytest.raises(UnsupportedFormat, match="PDF나 텍스트"):
        extract(tmp_path / "x.png")


def test_inbox_lists_and_takes(tmp_path):
    (tmp_path / "b.txt").write_text(LONG, encoding="utf-8")
    (tmp_path / "a.pdf").write_bytes((NOTICES / "N8.pdf").read_bytes())
    (tmp_path / "memo.docx").write_bytes(b"x")
    assert inbox.list_inbox(tmp_path) == ("a.pdf", "b.txt")
    assert inbox.take("b.txt", tmp_path).pages[0].lines == (LONG,)
    assert inbox.take("a.pdf", tmp_path).scanned
    assert inbox.list_inbox(tmp_path / "없음") == ()


@pytest.mark.parametrize("name", ["../b.txt", "no.txt", "memo.docx", ""])
def test_inbox_take_rejects_missing_and_outside_names(tmp_path, name):
    (tmp_path / "b.txt").write_text(LONG, encoding="utf-8")
    (tmp_path.parent / "b.txt").write_text(LONG, encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="받은편지함"):
        inbox.take(name, tmp_path)


def test_inbox_list_names_alias_kept(tmp_path):
    (tmp_path / "b.txt").write_text(LONG, encoding="utf-8")
    assert inbox.list_names(tmp_path) == inbox.list_inbox(tmp_path) == ("b.txt",)
    assert not hasattr(inbox, "list")


@pytest.mark.parametrize("raw", [b"not a pdf", b"", (NOTICES / "N8.pdf").read_bytes()[:120]])
def test_corrupt_pdf_becomes_korean_unsupported_format(tmp_path, raw):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(raw)
    with pytest.raises(UnsupportedFormat, match="본문을 붙여넣"):
        extract(bad)


def test_missing_file_path_string_is_korean(tmp_path):
    with pytest.raises(FileNotFoundError, match="파일을 찾을 수 없습니다"):
        extract(str(tmp_path / "없음.pdf"))
    with pytest.raises(FileNotFoundError, match="파일을 찾을 수 없습니다"):
        extract("없는공고.txt")
