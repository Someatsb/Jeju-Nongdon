"""원문 링크 표 data/catalog/links.csv 와 그 로더(app/catalog/links.py): 공식 사이트 https 주소만(설계서 B-4)."""
import csv
from datetime import date
from pathlib import Path

import pytest

from app.catalog.links import COLUMNS, LINK_KINDS, LinkTableError, is_official_url, load_links

ROOT = Path(__file__).resolve().parents[2]
LINKS = ROOT / "data" / "catalog" / "links.csv"
HEAD = ",".join(COLUMNS)


def write(tmp_path, *lines, head=HEAD) -> Path:
    p = tmp_path / "links.csv"
    p.write_text("\n".join([head, *lines]) + "\n", encoding="utf-8-sig")
    return p


def test_real_links_file_loads_and_every_address_is_official_https():
    links = load_links(LINKS)
    assert len(links) == 19
    for key, link in links.items():
        assert is_official_url(link.url), (key, link.url)
        assert link.url.startswith("https://") and "&amp;" not in link.url and "¬" not in link.url and "¤" not in link.url
        assert link.kind in LINK_KINDS and link.checked == date(2026, 11, 14) and link.title


def test_real_links_keys_are_scheme_keys_of_the_table():
    from app.data_layer.tables import load_tables

    keys = {p.program_key.split("@")[0].split("#")[0] for p in load_tables(ROOT / "data" / "tables", date(2026, 11, 14)).programs}
    links = load_links(LINKS)
    assert set(links) <= keys


def test_real_links_rules_from_the_research():
    links = load_links(LINKS)
    assert links["NAT-DIRECT-AREA"].url == links["NAT-DIRECT-SMALL"].url == "https://www.gov.kr/portal/service/serviceInfo/154300000409"
    assert links["NAT-DIRECT-AREA"].kind == "신청 안내(정부24)"
    assert "JEJU-CITRUS-PSTAB" not in links                       # 다른 내용이라 넣지 않는다
    for key in ("JEJU-SMALLFARM", "JEJU-PSTAB", "JEJU-LOGI", "NAT-FARM-HELPER", "JEJU-HAPPY-TAXI", "JEJU-SOIL-ECO", "NAT-DISASTER-RECOVERY",
                "NAT-PRICE-STAB-GO"):
        assert key not in links                                   # 공식 주소를 못 찾은 지원은 링크를 달지 않는다
    integrated = {k for k, v in links.items() if v.kind == "통합 공고"}
    assert integrated == {"DO-CALCIUM-SULFUR", "DO-SMALL-MACHINE", "DO-IRRIGATION", "JS-WINDBREAK", "JS-MANDARIN-BAG", "JS-BIODEG",
                          "SGP-WINDBREAK", "SGP-MANDARIN-BAG"}
    assert all(links[k].note == "자세한 내용은 공고에 붙은 파일에 있어요" for k in integrated)
    assert links["JS-WINDBREAK"].url.endswith("notice_id=c8b59d4780ae4444b911e79efd76297a&currentPageNo=8")   # 주소 속 & 가 그대로다


def test_no_press_or_private_sites():
    hosts = {link.url.split("/")[2] for link in load_links(LINKS).values()}
    assert hosts == {"www.gov.kr", "www.fbo.or.kr", "www.apfs.kr", "www.nps.or.kr", "www.nhis.or.kr", "www.jeju.go.kr", "www.bizinfo.go.kr",
                     "www.jejusi.go.kr", "www.seogwipo.go.kr"}


@pytest.mark.parametrize("url,ok", [
    ("https://www.jeju.go.kr/farm/x", True), ("https://jeju.go.kr/", True), ("https://www.gov.kr/portal", True),
    ("https://www.nps.or.kr/x", True), ("https://www.apfs.kr/front/x", True), ("https://apfs.kr", True),
    ("http://www.jeju.go.kr/x", False), ("https://evilgo.kr/x", False), ("https://go.kr.evil.example/x", False),
    ("https://www.jeju.go.kr@evil.example/x", False), ("https://user:pw@www.jeju.go.kr/x", False), ("https://www.jeju.go.kr:8080/x", False),
    ("https://newsseoul.co.kr/news/1", False), ("https://www.naver.com", False), ("ftp://x.go.kr", False), ("", False),
    ("javascript:alert(1)", False), ("https://www.thevc.kr/x", False)])
def test_official_url_rule(url, ok):
    assert is_official_url(url) is ok


def row(**kw):
    base = dict(program_key="NAT-X", url="https://www.gov.kr/a", link_kind="사업 안내", page_title="제목", checked_date="2026-11-14", note="")
    return ",".join(str({**base, **kw}[c]) for c in COLUMNS)


def test_loader_reads_a_valid_file_and_missing_file_is_empty(tmp_path):
    assert load_links(tmp_path / "nope.csv") == {}
    got = load_links(write(tmp_path, row(), row(program_key="NAT-Y", note="메모")))
    assert set(got) == {"NAT-X", "NAT-Y"} and got["NAT-Y"].note == "메모" and got["NAT-X"].checked == date(2026, 11, 14)


@pytest.mark.parametrize("bad,word", [
    (row(url="http://www.gov.kr/a"), "공식 사이트"), (row(url="https://news.example.com/a"), "공식 사이트"),
    (row(link_kind="보도자료"), "링크 종류"), (row(checked_date="어제"), "날짜"), (row(program_key=""), "열쇠")])
def test_loader_refuses_bad_rows_with_a_korean_message(tmp_path, bad, word):
    with pytest.raises(LinkTableError) as e:
        load_links(write(tmp_path, bad))
    assert word in str(e.value) and "2번째 줄" in str(e.value)


def test_loader_refuses_duplicate_keys_and_wrong_columns(tmp_path):
    with pytest.raises(LinkTableError, match="겹칩니다"):
        load_links(write(tmp_path, row(), row()))
    with pytest.raises(LinkTableError, match="열이 맞지"):
        load_links(write(tmp_path, "a,b", head="a,b"))


def test_file_is_plain_csv_a_staff_can_edit():
    with LINKS.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert tuple(rows[0]) == COLUMNS and len({r["program_key"] for r in rows}) == len(rows)
