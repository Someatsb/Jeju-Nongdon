"""공고 주소로 공고 읽기(app/data_layer/notice_url.py): 받아 둔 HTML 로만 시험한다(인터넷에 나가지 않는다)."""
from pathlib import Path

import pytest

from app.data_layer.docs_in import extract
from app.data_layer.notice_url import (
    ALLOWED_HOSTS,
    NOT_FOUND,
    NoticeUrlError,
    check_url,
    fetch_notice,
    parse_notice_page,
    source_url_of,
)

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "notice_pages"
SGP = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"
JSI = "https://www.jejusi.go.kr/information/intro/news.do?mode=detail&notice_id=889db4f45941441eabfacd8ac973ab13"


def _http(name: str):
    html = (PAGES / name).read_bytes()
    return lambda url: html


def test_seogwipo_page_body_is_copied_verbatim():
    got = fetch_notice(SGP, http=_http("sgp_fta_citrus_facility_2027.html"))
    text = got.doc.text
    assert text.splitlines()[0] == f"출처: {SGP}"
    assert "제목: 2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업 신청·접수계획 알림" in text
    assert "가. 신청기간: 2026. 11. 9.(월) ~ 11. 23.(월) (15일간)" in text
    assert "나. 접수처: 지역 농·감협" in text
    assert "⑮ 재해예방용 차광막 등 해가림시설 ⑯ 보급형 스마트팜" in text
    assert "[첨부 파일]" in text and "hwpx" in text
    assert "작성 부서: 대륜동" in text and "작성일: 2026-11-12 12:59:05" in text
    assert "담당자 연락처: 064-760-4763" in text and "·" not in text.split("담당자 연락처:")[1].splitlines()[0]
    assert got.title.startswith("2027년 FTA기금") and got.removed_lines == 0 and not got.doc.scanned


def test_jejusi_page_body_is_copied_verbatim():
    got = fetch_notice(JSI, http=_http("jsi_fta_citrus_2027_a.html"))
    text = got.doc.text
    assert "제목: 2027년 FTA기금 고품질과수(감귤) 생산시설 현대화사업 신청·접수 알림" in text
    assert "작성 부서: 산업팀" in text and "작성일: 2026-11-09 14:41:23" in text
    assert "(신청을 위한 구비서류 중, 실적확인서는 농지소재지 읍면동 주민센터에서 발급가능합니다)" in text
    assert "★2027년 FTA기금 과수(감귤)고품질시설 현대화사업 신청접수 계획.hwpx" in text.split("[첨부 파일]")[1]


def test_navigation_and_other_posts_are_not_in_the_text():
    text = fetch_notice(SGP, http=_http("sgp_fta_citrus_facility_2027.html")).doc.text
    assert len(text.splitlines()) < 30                      # 사이트 메뉴·다른 글 목록·바닥글이 섞이지 않았다
    assert "로그인" not in text and "개인정보처리방침" not in text


def test_result_is_a_normal_doc_for_the_agent():
    doc = fetch_notice(SGP, http=_http("sgp_fta_citrus_facility_2027.html")).doc
    assert source_url_of(doc) == SGP                       # 첫 줄이 출처 → 원문 링크로 쓴다
    assert extract(doc.text).text == doc.text


BOARD = """<html><body><div class="board-view"><p class="title">2027년 새 사업 안내 공고</p>
<p class="info">· 작성자 : 감귤유통과 ·작성일 : 2026-11-10 09:00:00 · 담당자연락처 : 064-710-3272</p>
<div class="view-contents"><p>신청 기간은 2026. 11. 20.부터 11. 30.까지입니다.</p><p>문의 010-1234-5678 홍길동</p>
<p>메일 test@example.com</p><p>제주도에 사는 농업인이면 신청할 수 있습니다.</p></div></div></body></html>"""


def test_jeju_province_page_uses_same_board_and_drops_personal_lines():
    got = parse_notice_page("https://www.jeju.go.kr/farm/notice/notice/notice1.htm?act=view&seq=1", BOARD)
    assert "010-1234-5678" not in got.doc.text and "test@example.com" not in got.doc.text
    assert got.removed_lines == 2
    assert "신청 기간은 2026. 11. 20.부터 11. 30.까지입니다." in got.doc.text
    assert "담당자 연락처: 064-710-3272" in got.doc.text


@pytest.mark.parametrize("html", ["<html><body><p>점검 중입니다</p></body></html>",
                                  "<div class='board-view'><p class='title'>제목</p><div class='view-contents'>짧음</div></div>",
                                  ""])
def test_page_without_body_says_so(html):
    with pytest.raises(NoticeUrlError) as e:
        parse_notice_page(SGP, html)
    assert str(e.value) == NOT_FOUND and "복사" in NOT_FOUND


@pytest.mark.parametrize("url", [
    "https://www.naver.com/x", "http://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=1",
    "https://evil.example/www.seogwipo.go.kr", "https://www.seogwipo.go.kr.evil.example/x",
    "https://user:pw@www.seogwipo.go.kr/x", "https://www.seogwipo.go.kr:8443/x", "https://agri.jeju.go.kr/agri/notice/job.htm",
    "https://bizinfo.go.kr/x", "file:///c:/windows/win.ini", "javascript:alert(1)", "", "ftp://www.jeju.go.kr/x"])
def test_urls_outside_the_allowlist_are_refused_before_any_request(url):
    called = []
    with pytest.raises(NoticeUrlError):
        fetch_notice(url, http=lambda u: called.append(u) or b"")
    assert called == []


def test_allowed_hosts_are_exactly_three_sites():
    assert {h.removeprefix("www.") for h in ALLOWED_HOSTS} == {"seogwipo.go.kr", "jejusi.go.kr", "jeju.go.kr"}
    for host in ALLOWED_HOSTS:
        assert check_url(f"https://{host}/a?b=1") == f"https://{host}/a?b=1"


def test_source_line_is_only_taken_from_the_first_line():
    assert source_url_of(extract("출처: https://www.jejusi.go.kr/x\n본문 글")) == "https://www.jejusi.go.kr/x"
    assert source_url_of(extract("제목\n출처: https://www.jejusi.go.kr/x")) is None
    assert source_url_of(extract("출처: 없음\n본문")) is None
    assert source_url_of(extract("출처: http://insecure.example/x\n본문")) is None


def test_redirect_to_another_site_is_not_followed():
    import urllib.request

    from app.data_layer.notice_url import _SameSiteOnly

    handler, req = _SameSiteOnly(), urllib.request.Request(SGP)
    with pytest.raises(NoticeUrlError):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/steal")
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://www.jeju.go.kr/other") is not None
