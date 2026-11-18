"""게시판 목록 읽기(app/data_layer/notice_board.py): 저장해 둔 HTML 로만 시험한다(인터넷에 나가지 않는다)."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.data_layer.notice_board import (
    BOARDS,
    BoardClient,
    KnownNotices,
    RequestLimit,
    board_named,
    canonical_url,
    clean_dept,
    fixture_hash,
    fixture_http,
    list_url,
    normalize_url,
    parse_list,
    read_list,
    url_inbox_id,
)
from app.data_layer.notice_url import ALLOWED_HOSTS, NoticeUrlError

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "fixtures" / "boards"


def _rows(key: str, name: str):
    return parse_list(board_named(key), (FX / name).read_text(encoding="utf-8"))


def test_four_boards_on_allowed_hosts():
    assert [b.key for b in BOARDS] == ["seogwipo", "jejusi", "jejusi_farm", "jeju_farm"]
    for b in BOARDS:
        assert b.url.startswith("https://") and b.url.split("/")[2] in ALLOWED_HOSTS


def test_board_named_accepts_name_or_key_ignoring_spaces():
    assert board_named("서귀포시알림마당").key == "seogwipo"
    assert board_named("제주시 농수축산국 부서소식").key == "jejusi_farm"
    assert board_named("jeju_farm").key == "jeju_farm"
    assert board_named("네이버 카페") is None


def test_list_urls():
    sgp, jsi, farm, doc = BOARDS
    assert list_url(sgp) == "https://www.seogwipo.go.kr/info/news/notice.htm"
    assert list_url(sgp, "FTA", 2) == "https://www.seogwipo.go.kr/info/news/notice.htm?q=FTA&qType=title&page=2"
    assert list_url(jsi, "유기질", 1).startswith("https://www.jejusi.go.kr/information/intro/news.do?searchText=%")
    assert list_url(farm, "", 3) == "https://www.jejusi.go.kr/part/farm/intro/news.do?currentPageNo=3&recordCountPerPage=30"
    assert list_url(doc) == "https://www.jeju.go.kr/farm/notice/notice/notice1.htm"


def test_seogwipo_list_uses_full_title_date_and_department():
    rows, dropped = _rows("seogwipo", "seogwipo_list.html")
    assert dropped == 0 and len(rows) == 12
    first, fta = rows[0], rows[7]
    assert first.title == "서귀포시 주간행사계획(2026. 11.16.~11.22.)" and first.dept == "자치행정과"
    assert fta.title == "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업 신청·접수계획 알림"   # 화면에는 ".." 로 잘려 있다
    assert fta.posted == date(2026, 11, 12) and fta.dept == "대륜동"
    assert fta.url == "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"
    assert rows[3].dept == ""                      # 부서 칸이 빈 글


def test_jejusi_list_keeps_notice_id_and_drops_page_number():
    rows, dropped = _rows("jejusi", "jejusi_list.html")
    assert dropped == 0 and len(rows) == 10
    assert rows[0].url == ("https://www.jejusi.go.kr/information/intro/news.do"
                           "?mode=detail&notice_id=5fece901319943ae96c46640fa085aaf")
    assert rows[0].dept == "일도1동" and rows[0].posted == date(2026, 11, 14)
    farm, _ = _rows("jejusi_farm", "jejusi_farm_list.html")
    assert farm[1].url.startswith("https://www.jejusi.go.kr/part/farm/intro/news.do?mode=detail&notice_id=16a47b83")
    assert farm[1].dept == "친환경농정과 농정팀" and farm[0].dept == ""


def test_dochung_list_and_old_dates():
    rows, dropped = _rows("jeju_farm", "jeju_farm_list.html")
    assert dropped == 0 and len(rows) == 10
    assert max(r.posted for r in rows) == date(2026, 8, 18)
    assert rows[0].url == "https://www.jeju.go.kr/farm/notice/notice/notice1.htm?act=view&seq=2030570"


def test_search_page_has_old_rows_too():
    rows, _ = _rows("seogwipo", "seogwipo_search_fta.html")
    assert len(rows) == 9 and rows[4].dept == "감귤유통과" and rows[-1].posted == date(2026, 1, 7)


def test_link_to_another_site_is_dropped_and_counted():
    html = """<table><tr><th>제목</th></tr>
    <tr><td class="title"><a href="https://evil.example.com/x?mode=detail&notice_id=abc">나쁜 글</a></td>
    <td class="writer">산업팀</td><td class="date">2026-11-13</td></tr>
    <tr><td class="title"><a href="https://www.seogwipo.go.kr/info/news/notice.htm?mode=detail&notice_id=abc">다른 사이트 글</a></td>
    <td class="writer">산업팀</td><td class="date">2026-11-13</td></tr>
    <tr><td class="title"><a href="/information/intro/news.do?mode=detail&notice_id=ok1">좋은 글</a></td>
    <td class="writer">산업팀</td><td class="date">2026-11-13</td></tr></table>"""
    rows, dropped = parse_list(board_named("jejusi"), html)
    assert [r.title for r in rows] == ["좋은 글"] and dropped == 2


def test_http_link_and_missing_id_are_dropped():
    html = """<table><tr><td class="title"><a href="http://www.jejusi.go.kr/information/intro/news.do?mode=detail&notice_id=a">x</a></td></tr>
    <tr><td class="title"><a href="/information/intro/news.do?mode=detail">아이디 없음</a></td></tr></table>"""
    rows, dropped = parse_list(board_named("jejusi"), html)
    assert rows == [] and dropped == 2


def test_canonical_url_rejects_other_hosts():
    sgp = board_named("seogwipo")
    with pytest.raises(NoticeUrlError):
        canonical_url(sgp, "https://www.jejusi.go.kr/information/intro/news.do?act=view&seq=1")
    assert canonical_url(sgp, "/info/news/notice.htm?act=view&seq=9&page=3") == \
        "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=9"


def test_person_like_department_is_blanked():
    assert clean_dept("홍길동") == "" and clean_dept("김철수") == ""
    assert clean_dept("대륜동") == "대륜동" and clean_dept("감귤유통과") == "감귤유통과"
    assert clean_dept(" 친환경농정과   농정팀 ") == "친환경농정과 농정팀" and clean_dept("주민자치") == "주민자치"
    assert clean_dept("일도1동") == "일도1동" and clean_dept("") == ""


def test_normalize_url_drops_page_number():
    a = "https://www.jejusi.go.kr/information/intro/news.do?mode=detail&notice_id=abc&currentPageNo=1"
    assert normalize_url(a) == "https://www.jejusi.go.kr/information/intro/news.do?mode=detail&notice_id=abc"
    assert normalize_url("https://www.korea.kr/x?a=1") == "https://www.korea.kr/x?a=1"


# --- 받기: 요청 수·쉬는 시간 ------------------------------------------------------------------

def test_client_sleeps_between_requests_and_counts():
    sleeps, got = [], []
    client = BoardClient(http=lambda u: got.append(u) or b"x", sleep=sleeps.append)
    for _ in range(3):
        client.fetch("https://www.seogwipo.go.kr/info/news/notice.htm")
    assert client.count == 3 and sleeps == [1.0, 1.0] and len(got) == 3


def test_client_refuses_after_forty_requests():
    client = BoardClient(http=lambda u: b"x", sleep=lambda s: None)
    for _ in range(40):
        client.fetch("https://www.jejusi.go.kr/a")
    with pytest.raises(RequestLimit):
        client.fetch("https://www.jejusi.go.kr/a")
    assert client.count == 40 and client.left == 0


def test_client_only_fetches_allowed_addresses():
    called = []
    client = BoardClient(http=lambda u: called.append(u) or b"x", sleep=lambda s: None)
    for bad in ("https://example.com/a", "http://www.jejusi.go.kr/a", "https://user@www.jejusi.go.kr/a"):
        with pytest.raises(NoticeUrlError):
            client.fetch(bad)
    assert called == [] and client.count == 0


def test_read_list_goes_through_the_client():
    client = BoardClient(http=fixture_http(FX), sleep=lambda s: None)
    rows, _ = read_list(client, board_named("seogwipo"), "FTA")
    assert len(rows) == 9 and client.count == 1
    with pytest.raises(NoticeUrlError):
        read_list(client, board_named("seogwipo"), "고정본에 없는 검색어")


# --- 이미 읽은 글 ----------------------------------------------------------------------------

def test_known_notices_from_catalog_and_inbox(tmp_path):
    cat = tmp_path / "data" / "catalog" / "notices"
    cat.mkdir(parents=True)
    url_a = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"
    (cat / "a.json").write_text(json.dumps({"url": url_a}), encoding="utf-8")
    (cat / "b.json").write_text("{깨진 글", encoding="utf-8")
    (cat / "c.json").write_text(json.dumps({"url": None}), encoding="utf-8")
    url_b = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155830189"
    done = tmp_path / "data" / "inbox" / url_inbox_id(url_b)
    done.mkdir(parents=True)
    (done / "check.json").write_text(json.dumps({"decision": "DRAFT_READY", "partial": False}), encoding="utf-8")
    known = KnownNotices.from_root(tmp_path)
    assert url_a in known and url_b in known
    assert "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=1" not in known


def test_known_notices_empty_root(tmp_path):
    assert "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=1" not in KnownNotices.from_root(tmp_path)


def test_url_inbox_id_matches_notice_url_command():
    from app import cli
    u = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"
    assert url_inbox_id(u) == cli._url_inbox_id(u)


# --- 고정본 ----------------------------------------------------------------------------------

def test_every_index_entry_has_a_file_and_every_detail_is_indexed():
    index = json.loads((FX / "index.json").read_text(encoding="utf-8"))
    assert all((FX / name).is_file() for name in index.values())
    assert {p.name for p in FX.glob("detail_*.html")} <= set(index.values())


def test_replay_copy_of_fixtures_is_identical():
    copy = ROOT / "data" / "replay" / "boards"
    assert fixture_hash(copy) == fixture_hash(FX)


def test_fixtures_hold_no_personal_data():
    import re
    from app.tools.draft_checks import pii_labels
    for p in FX.glob("*.html"):
        text = p.read_text(encoding="utf-8")
        assert "phone" not in pii_labels(text), p.name       # 주소 속 글자 묶음이 주민번호처럼 보일 수 있어 휴대전화만 본다
        assert not re.search(r"[\w.]+@[\w.]+", text), p.name
        assert "010-" not in text, p.name
    for name in ("detail_jsi_fta_citrus_2027_a.html", "detail_jsi_farm_youth_loan.html"):
        text = (FX / name).read_text(encoding="utf-8")
        assert "문보라" not in text and "유지언" not in text


def test_fixture_hash_ignores_line_endings(tmp_path):
    shutil.copytree(FX, tmp_path / "a")
    shutil.copytree(FX, tmp_path / "b")
    p = tmp_path / "b" / "seogwipo_list.html"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert fixture_hash(tmp_path / "a") == fixture_hash(tmp_path / "b")


# --- 검수 지적 반영 ----------------------------------------------------------------------------

def test_three_letter_names_ending_like_an_org_are_blanked():
    for name in ("김지원", "이정원", "박성도", "정민국", "한승회", "조현단", "최소연", "강유진", "윤서시"):
        assert clean_dept(name) == "", name
    for dept in ("농정과", "감귤유통과", "산업팀", "농업기술센터", "자치행정과", "주민자치", "대륜동", "한림읍"):
        assert clean_dept(dept) == dept, dept


def _client(html: str) -> BoardClient:
    return BoardClient(lambda u: html.encode("utf-8"), sleep=lambda s: None)


def test_unrecognised_page_layout_is_reported_not_called_empty():
    for key in ("seogwipo", "jejusi", "jejusi_farm", "jeju_farm"):
        with pytest.raises(NoticeUrlError, match="모양이 달라져"):
            read_list(_client("<html><body><div>new layout</div></body></html>"), board_named(key))


def test_real_list_without_rows_is_not_a_layout_error():
    html = '<table><thead><tr><th>제목</th></tr></thead><tbody><tr><td colspan="4">검색 결과가 없습니다</td></tr></tbody></table>'
    for key in ("seogwipo", "jejusi"):
        assert read_list(_client(html), board_named(key)) == ([], 0)


def test_canonical_url_pins_path_keys_and_host_case():
    sgp = board_named("seogwipo")
    with pytest.raises(NoticeUrlError):
        canonical_url(sgp, "/tool/synap/convert.jsp?act=view&seq=1")
    with pytest.raises(NoticeUrlError):
        canonical_url(sgp, "?act=download&act=view&seq=5")
    ok = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=9"
    assert canonical_url(sgp, "https://WWW.SEOGWIPO.GO.KR/info/news/notice.htm?act=view&seq=9") == ok


def test_known_notices_count_only_finished_inbox_reads(tmp_path):
    inbox = tmp_path / "data" / "inbox"
    cases = {"url-done": {"decision": "DRAFT_READY", "partial": False}, "url-notrel": {"decision": "NOT_RELEVANT", "partial": False},
             "url-staff": {"decision": "NEEDS_STAFF", "partial": True}, "url-unread": {"decision": "UNREADABLE", "partial": False}}
    for name, check in cases.items():
        (inbox / name).mkdir(parents=True)
        (inbox / name / "check.json").write_text(json.dumps(check), encoding="utf-8")
    (inbox / "url-nocheck").mkdir()
    (inbox / "scout-20261114-090000").mkdir()
    known = KnownNotices.from_root(tmp_path)
    assert known.inbox_ids == {"url-done", "url-notrel"}
