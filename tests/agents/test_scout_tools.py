"""찾기 에이전트 도구(app/tools/scout_tools.py): 고정본 게시판(http 인자)으로 시험한다. 인터넷·실제 AI 없음."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.data_layer.notice_board import BOARDS, BoardClient, KnownNotices, fixture_http
from app.tools.models import ToolLog
from app.tools.registry import ToolError
from app.tools.scout_tools import MAX_PEEKS, MAX_PICKS, ScoutTools

FX = Path(__file__).resolve().parents[1] / "fixtures" / "boards"
AS_OF = date(2026, 11, 14)
SGP, JSI, FARM, DOCHE = "서귀포시 알림마당", "제주시 공지사항", "제주시 농수축산국 부서소식", "제주도청 농축산 소식"


def make(days=30, known=None, http=None, max_requests=40):
    sleeps: list[float] = []
    client = BoardClient(http or fixture_http(FX), sleep=sleeps.append, max_requests=max_requests)
    tools = ScoutTools(BOARDS, client, as_of=AS_OF, days=days, known=known, log=ToolLog())
    return tools, client, sleeps


def test_list_board_returns_numbered_rows_without_addresses():
    tools, _, _ = make()
    out = tools.list_board(SGP)
    assert [r.row for r in out.rows] == list(range(1, 13))
    assert out.rows[7].title.startswith("2027년 FTA기금") and out.rows[7].dept == "대륜동" and out.rows[7].posted == "2026-11-12"
    dumped = json.dumps(out.model_dump(), ensure_ascii=False)
    assert "http" not in dumped and "seq=" not in dumped
    assert out.hidden_old == 0 and out.more_pages is True      # 이 쪽의 맨 끝 글도 기간 안이라 다음 쪽이 있을 수 있다


def test_list_board_hides_posts_older_than_the_window():
    tools, _, _ = make()
    out = tools.list_board(FARM)
    assert [r.posted for r in out.rows] == ["2026-11-10", "2026-10-29", "2026-10-15", "2026-10-15", "2026-10-15"]
    assert out.hidden_old == 5 and out.more_pages is False
    out = make(days=60)[0].list_board(FARM)
    assert len(out.rows) == 10


def test_window_edge_is_inclusive():
    tools, _, _ = make(days=30)           # 2026-10-15 은 기준일에서 정확히 30일 전
    assert any(r.posted == "2026-10-15" for r in tools.list_board(FARM).rows)
    assert not any(r.posted == "2026-10-15" for r in make(days=29)[0].list_board(FARM).rows)


def test_board_with_no_recent_posts_says_so():
    tools, _, _ = make()
    out = tools.list_board(DOCHE)
    assert out.rows == [] and out.hidden_old == 10
    assert "최근 30일" in out.note and "2026-08-18" in out.note
    assert tools.stats["jeju_farm"].seen == 0 and tools.stats["jeju_farm"].hidden_old == 10


def test_same_post_keeps_its_number_across_lists():
    tools, _, _ = make()
    first = tools.list_board(SGP)
    fta = next(r.row for r in first.rows if r.title.startswith("2027년 FTA기금"))
    second = tools.list_board(SGP, query="FTA")
    assert second.rows[0].row == fta
    assert [r.row for r in second.rows] == [fta, 13, 14, 15, 16] and second.hidden_old == 4
    assert tools.stats["seogwipo"].seen == 16 and tools.stats["seogwipo"].pages == 2


def test_already_read_rows_are_marked_and_cannot_be_picked():
    known = KnownNotices(urls=["https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"])
    tools, _, _ = make(known=known)
    out = tools.list_board(SGP)
    assert [r.row for r in out.rows if r.already_read] == [8]
    with pytest.raises(ToolError, match="이미 읽은"):
        tools.pick(8, "농가 지원")
    with pytest.raises(ToolError, match="이미 읽은"):
        tools.peek(8)
    tools.skip(8, "이미 읽음")


def test_unknown_board_and_bad_query_are_refused():
    tools, client, _ = make()
    with pytest.raises(ToolError, match="볼 수 없습니다"):
        tools.list_board("네이버 카페")
    with pytest.raises(ToolError, match="검색어"):
        tools.list_board(SGP, query="가" * 50)
    assert client.count == 0


def test_rows_not_listed_cannot_be_picked_peeked_or_skipped():
    tools, client, _ = make()
    for call in (lambda: tools.pick(1, "이유"), lambda: tools.peek(1), lambda: tools.skip(1, "이유")):
        with pytest.raises(ToolError, match="list_board"):
            call()
    tools.list_board(SGP)
    with pytest.raises(ToolError, match="list_board"):
        tools.pick(99, "이유")
    assert client.count == 1


def test_failed_board_does_not_stop_the_others():
    def http(url):
        if "jejusi.go.kr" in url:
            raise OSError("연결 안 됨")
        return fixture_http(FX)(url)
    tools, _, _ = make(http=http)
    with pytest.raises(ToolError, match="제주시 공지사항 게시판을 열지 못했습니다"):
        tools.list_board(JSI)
    assert tools.stats["jejusi"].error and "OSError" in tools.stats["jejusi"].error
    assert len(tools.list_board(SGP).rows) == 12


def test_peek_reads_body_lines_and_caches():
    tools, client, _ = make()
    tools.list_board(SGP)
    out = tools.peek(6)                       # 유기농업자재(대륜동)
    assert out.title.startswith("2027년 유기농업자재") and out.dept == "대륜동"
    assert out.lines[0].startswith("2027년 유기농업자재 지원사업 신청 접수 계획을")
    assert any("200만원/ha" in ln for ln in out.lines) and not any("출처" in ln or "http" in ln for ln in out.lines)
    assert "[본문]" not in out.lines and "[첨부 파일]" not in out.lines
    before = client.count
    assert tools.peek(6) == out and client.count == before and tools.peeks == 1


def test_peek_limit_and_unreadable_post():
    tools, _, _ = make()
    tools.list_board(SGP)
    tools.list_board(SGP, query="FTA")
    tools.list_board(FARM)
    # 고정본에 없는 상세(1·2·3번)는 읽지 못했다고 알리고, 횟수는 그래도 쓴다
    with pytest.raises(ToolError, match="글을 읽지 못했습니다"):
        tools.peek(1)
    for n in (6, 7, 8, 16, 18):
        assert tools.peek(n).lines
    for n in (2, 3):
        with pytest.raises(ToolError):
            tools.peek(n)
    assert tools.peeks == MAX_PEEKS
    with pytest.raises(ToolError, match="여덟 번"):
        tools.peek(4)
    assert tools.peek(6).lines                          # 이미 읽은 글은 한도와 상관없이 다시 볼 수 있다
    assert any("미리보기" in x for x in tools.limits)


def test_pick_limit_duplicates_and_reason_checks():
    tools, _, _ = make()
    tools.list_board(SGP)
    tools.list_board(SGP, query="FTA")
    out = tools.pick(16, "과에서 올린 원문 공고입니다")
    assert out.ok and out.picks_left == MAX_PICKS - 1
    with pytest.raises(ToolError, match="이미 정한"):
        tools.pick(16, "다시")
    with pytest.raises(ToolError, match="이유"):
        tools.pick(6, "  ")
    with pytest.raises(ToolError, match="개인정보"):
        tools.pick(6, "문의는 010-1234-5678")
    # 제목이 같은 글(공백만 다른 경우 포함)은 같은 사업이라 하나만
    tools.pick(14, "다른 글")
    with pytest.raises(ToolError, match="같은 사업"):
        tools.pick(15, "제목이 같음")


def test_pick_stops_at_six():
    tools, _, _ = make()
    tools.list_board(SGP)
    for n in range(1, MAX_PICKS + 1):
        tools.pick(n, "농가 지원사업")
    with pytest.raises(ToolError, match="여섯 건"):
        tools.pick(7, "하나 더")
    assert any("고르기" in x for x in tools.limits) and len(tools.picks) == MAX_PICKS


def test_skip_accepts_one_or_many_rows():
    tools, _, _ = make()
    tools.list_board(SGP)
    assert "3건" in tools.skip([1, 2, 2, 3], "농가 지원이 아닌 안내").message
    assert set(tools.skips) == {1, 2, 3}
    assert "1건" in tools.skip(4, "모집 공고").message
    assert "0건" in tools.skip([4], "또").message          # 이미 정한 줄은 그대로 둔다
    with pytest.raises(ToolError, match="list_board"):
        tools.skip([5, 500], "이유")
    assert 5 not in tools.skips                           # 하나라도 틀리면 아무것도 적지 않는다
    with pytest.raises(ToolError):
        tools.skip([], "이유")
    with pytest.raises(ToolError, match="40개"):
        tools.skip(list(range(1, 60)), "이유")


def test_finish_records_summary():
    tools, _, _ = make()
    assert tools.finish("서귀포시에서 세 건을 골랐습니다").ok and tools.finished
    assert tools.summary.startswith("서귀포시")
    with pytest.raises(ToolError, match="개인정보"):
        tools.finish("문의 abc@example.com")


def test_request_budget_exact_boundary():
    tools, client, _ = make(max_requests=8)
    tools.list_board(SGP)                          # 남은 7
    tools.list_board(SGP, query="FTA")             # 남은 6 (7-1=6 >= 6 허용)
    with pytest.raises(ToolError, match="요청 한도"):
        tools.list_board(FARM)                     # 6-1=5 < 6 거절
    assert client.count == 2 and any("본문을 받을 몫" in x for x in tools.limits)
    tools.pick(16, "과 원문")                       # 고른 만큼 몫이 줄어 한 번 더 볼 수 있다
    assert len(tools.list_board(FARM).rows) == 5


def test_requests_are_spaced_and_counted_across_tools():
    tools, client, sleeps = make()
    tools.list_board(SGP)
    tools.list_board(FARM)
    tools.peek(6)
    assert client.count == 3 and sleeps == [1.0, 1.0]


def test_schemas_have_no_digits_and_only_five_tools():
    schemas = ScoutTools(BOARDS, BoardClient(sleep=lambda s: None), as_of=AS_OF).registry().schemas()
    assert [s["name"] for s in schemas] == ["list_board", "peek", "pick", "skip", "finish"]


def test_dispatch_turns_bad_calls_into_error_records():
    tools, _, _ = make()
    reg = tools.registry()
    log = ToolLog()
    rec = reg.dispatch("pick", {"row": 1, "reason": "이유"}, log)
    assert not rec.ok and "list_board" in rec.error
    rec = reg.dispatch("list_board", {"board": SGP, "page": 99}, log)
    assert not rec.ok
    rec = reg.dispatch("list_board", {"board": SGP}, log)
    assert rec.ok and len(rec.result["rows"]) == 12
    rec = reg.dispatch("skip", {"row": [1, 2], "reason": "안내"}, log)
    assert rec.ok
    rec = reg.dispatch("open_url", {"url": "https://example.com"}, log)       # 주소를 여는 도구는 없다
    assert not rec.ok and "모르는 도구" in rec.error


# --- 검수 지적 반영 ----------------------------------------------------------------------------

def test_unrecognised_board_layout_is_told_to_the_ai_and_recorded():
    tools, _, _ = make(http=lambda u: b"<html><body><div>new layout</div></body></html>")
    with pytest.raises(ToolError, match="모양이 달라져"):
        tools.list_board(SGP)
    assert "모양이 달라져" in tools.stats["seogwipo"].error


def test_rows_with_unreadable_dates_are_counted_apart_from_old_ones():
    html = ('<table><tr><td class="title"><a href="/information/intro/news.do?mode=detail&notice_id=a1">날짜 없는 글</a></td>'
            '<td class="writer">산업팀</td><td class="date"></td></tr>'
            '<tr><td class="title"><a href="/information/intro/news.do?mode=detail&notice_id=a2">옛 글</a></td>'
            '<td class="writer">산업팀</td><td class="date">2020-01-01</td></tr></table>').encode()
    tools, _, _ = make(http=lambda u: html)
    out = tools.list_board(JSI)
    assert out.rows == [] and tools.stats["jejusi"].undated == 1 and tools.stats["jejusi"].hidden_old == 1


def _twin_http():
    def row(n, dept, title):
        return (f'<tr><td class="title"><a href="/information/intro/news.do?mode=detail&notice_id=t{n}">{title}</a></td>'
                f'<td class="writer">{dept}</td><td class="date">2026-11-13</td></tr>')
    html = "<table>" + row(1, "대륜동", "2027년 시험 지원사업 신청 알림") + row(2, "친환경농정과", "2027년 시험 지원사업 신청 알림")         + row(3, "중문동", "2027년 시험 지원사업 신청 알림") + "</table>"
    return lambda u: html.encode()


def test_department_post_replaces_an_earlier_dong_post_of_the_same_project():
    tools, _, _ = make(http=_twin_http())
    tools.list_board(JSI)
    tools.pick(1, "읍면동 글")
    out = tools.pick(2, "부서 글이 있어 바꿉니다")
    assert out.ok and list(tools.picks) == [2] and "바꿨" in tools.skips[1]
    assert out.picks_left == MAX_PICKS - 1
    with pytest.raises(ToolError, match="같은 사업"):       # 읍면동 글은 이미 고른 부서 글이 있으면 그대로 거절
        tools.pick(3, "또 읍면동 글")


def test_long_summary_is_cut_at_a_sentence_end_not_mid_word():
    from app.tools.scout_tools import MAX_SUMMARY_CHARS
    tools, _, _ = make()
    sentence = "서귀포시와 제주시 게시판을 살펴 농가에 닿는 글을 골랐습니다."
    text = " ".join([sentence] * 20) + " 마지막 문장은 길어서 잘릴 수 있습니다"
    assert len(text) > MAX_SUMMARY_CHARS
    tools.finish(text)
    assert tools.summary.endswith(sentence + " …") and len(tools.summary) <= MAX_SUMMARY_CHARS + 2
    assert tools.summary.count("…") == 1
    tools.finish("한 문장 " * 200)                                       # 마침표가 없으면 낱말 끝에서 끊고 …
    assert tools.summary.endswith("…") and tools.summary.removesuffix(" …").endswith("문장") and len(tools.summary) <= MAX_SUMMARY_CHARS + 2
    tools.finish("짧은 요약입니다.")
    assert tools.summary == "짧은 요약입니다."
