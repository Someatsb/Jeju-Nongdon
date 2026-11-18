"""결과 화면 3차 점검 반영(2026-11-15 새벽 점검·사용자 시험 지적): 보험 줄의 공고 원문, 같은 주소 한 줄, 딱지 한 가지 말, 급한 마감 표시,
확인 줄만 있는 줄의 하실 일 줄, 전화 줄 글, 금액 아닌 글, 링크 복사 대체 동작, 아래 띠 안내 글 자리, 큰 화면 받을 것 가로 칸, 종이 알아 두세요 상자 안 덧말."""
import re

import pytest

from .test_replay import run_demo
from .test_result_list import (APP, COPY_CSS, DEMO_IDS, LINKS, PRINT_CSS, RESULT_CSS, assert_floor, classes, declared, paper_html, rows_of, soup)  # noqa: F401


def detail_links(html: str) -> list:
    return soup(html).select("#detail .lk-box li.lk")


# ---------------- 공고 원문: 보험 줄도, 같은 주소는 한 줄 ----------------
@pytest.mark.parametrize("pid,key", [("P4", "NAT-CROP-INS"), ("P3", "NAT-CROP-INS")])
def test_insurance_rows_have_their_notice_link_in_detail(client_replay, pid, key):
    """보험 줄(양배추 농작물보험 등)은 제도 열쇠가 없어 빠져 있었다. 줄이 말하는 보험의 공식 주소(links.csv)가 있어야 한다."""
    lis = [li for li in detail_links(run_demo(client_replay, pid).text) if key in li["data-keys"].split()]
    assert len(lis) == 1, (pid, key)
    assert lis[0].select_one("a.lk-open")["href"] == LINKS[key].url == lis[0].select_one("button.lk-copy")["data-copy-url"]
    assert "보험" in lis[0].select_one(".lk-name").get_text()


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_one_line_per_address_and_buttons_sit_side_by_side_under_the_name(client_replay, pid):
    html = run_demo(client_replay, pid).text
    urls = [li.select_one("a.lk-open")["href"] for li in detail_links(html)]
    assert len(urls) == len(set(urls)), "같은 곳으로 가는 단추가 여럿이면 헷갈린다"
    for li in detail_links(html):
        kids = [classes(e)[0] for e in li.find_all(recursive=False)]
        assert kids[:2] == ["lk-name", "lk-btns"], kids                      # 이름 → 단추 둘(한 줄에 나란히)
        assert li.select_one(".lk-btns a.lk-open") and li.select_one(".lk-btns button.lk-copy")


def test_same_address_supports_are_named_together(client_replay):
    names = [li.select_one(".lk-name").get_text() for li in detail_links(run_demo(client_replay, "P2").text)]
    assert any(" · " in n for n in names), names


# ---------------- 딱지·급한 마감·확인 줄·전화·금액 아닌 글 ----------------
@pytest.mark.parametrize("pid", DEMO_IDS)
def test_pills_are_two_phrases_only(client_replay, pid):
    """상자 띠의 딱지는 둘뿐이다(2026-11-15 4차): 먼저 하실 일 · 지금 신청할 수 있어요. 옛 .rr-pill 은 없다."""
    s = soup(run_demo(client_replay, pid).text)
    assert {p.get_text(strip=True) for p in s.select(".bx-tag.is-first")} <= {"먼저 하실 일"}
    assert {p.get_text(strip=True) for p in s.select(".bx-tag.is-now")} <= {"지금 신청할 수 있어요"}
    assert not s.select(".rr-pill")


def test_urgent_row_shows_the_days_left_as_a_red_mark_and_the_paper_does_not(client_replay, paper_html):
    s = soup(run_demo(client_replay, "P3").text)
    mark = s.select_one(".bx-rows .bxr-left .left-pill")
    assert mark and mark.get_text(strip=True) == "오늘까지" and "is-urgent" in classes(mark)
    assert "11월 13일까지" not in s.select_one(".bx-rows").get_text()      # '오늘까지' 딱지가 같은 말이라 날짜는 되풀이하지 않는다
    assert not soup(paper_html["P3"]).select(".front .rx-urgent, .front .left-pill")              # 종이는 다음 날 읽는다


def test_box_with_only_a_confirm_line_leads_with_that_row(client_replay):
    html = run_demo(client_replay, "P5").text
    box = soup(rows_of(html)[0]).select_one(".bx")
    rows = box.select(".bx-rows > li")
    assert "is-confirm" in classes(rows[0]) and rows[0].select_one(".bxr-t").get_text(strip=True) == "배우자가 경영체에 등록했는지 확인"
    assert rows[0].select_one("svg") and "농산물품질관리원에 물어보세요" in rows[0].get_text()


def test_phone_line_text_is_big_and_bold_even_without_a_number():
    assert_floor(RESULT_CSS, ".bx-tel-note", 22)
    assert declared(RESULT_CSS, ".bx-tel-note", "font-weight")[-1][1] == "800"
    assert declared(RESULT_CSS, ".bx-tel b", "white-space")[-1][1] == "nowrap"          # 전화번호는 줄바꿈 금지


def test_non_money_text_in_the_money_slot_is_not_styled_like_money(client_replay):
    html = run_demo(client_replay, "P5").text
    s = soup(html)
    texts = s.select(".bxr-m.is-text")
    assert all(not t.select_one(".bxr-amt") for t in texts)
    later = [r for r in s.select("#later .lt-r") if "작년처럼 다시 신청하세요" in r.get_text()]
    assert later and all(not r.select_one(".lt-amt") for r in later)      # 금액이 아닌 글은 앞으로 구역에서도 주황 금액이 아니다
    assert declared(RESULT_CSS, ".bxr-m.is-text", "font-size")[0][1] == "24px"
    assert declared(RESULT_CSS, ".bxr-amt", "white-space")[-1][1] == "nowrap"      # 금액이 두 동강 나지 않게
    assert "tang-deep" in declared(RESULT_CSS, ".bxr-amt", "color")[-1][1] and not declared(RESULT_CSS, ".bxr-m.is-text", "color")


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_band_says_how_many_places_and_the_counts_agree(client_replay, pid):
    """위 띠 "가실 곳은 N곳이에요"는 상자 수, 결론 "○가지"는 상자 안 받는 것(data-n 줄) 수와 맞는다."""
    html = run_demo(client_replay, pid).text
    s = soup(html)
    n = len(rows_of(html)) + len(s.select("#cards article.bx-nn"))          # 지금 접수 중인 공고 상자도 가실 곳으로 센다
    assert s.select_one(".rb-n").get_text(strip=True) == f"지금 가실 곳은 {n}곳이에요"
    assert not s.select(".rh"), "옛 머리 줄(하실 일 모두 ○가지)은 없다"
    m = re.search(r"(\d+)가지", s.select_one(".rb-h").get_text())
    if m and "를 찾았어요" in s.select_one(".rb-h").get_text():
        far = s.select_one("#later .lt-more")          # 넉 달 밖으로 줄인 줄도 결론의 가짓수에는 든다(한 줄 안내가 그 수를 적는다)
        assert int(m[1]) == len(s.select("#cards .bxr[data-n], #later .lt-r[data-n]")) + (int(far["data-counted"]) if far else 0), pid      # 받는 것 가짓수 = 지금 구역 줄 + 앞으로 구역 줄 + 줄인 먼 줄


def test_unlock_line_on_screen_opens_the_detail(client_replay):
    t = soup(run_demo(client_replay, "P4").text).select_one(".bxr-opens")      # 지원 이름으로 말한다(2026-11-15 두 구역)
    assert t.get_text(strip=True).startswith("이것을 해야 ") and t.get_text(strip=True).endswith("받을 수 있어요") and "가지를 받을 수" in t.get_text()


# ---------------- 아래 띠 안내 글 ----------------
def test_price_note_is_20px_and_moves_into_the_know_box_in_small_windows(client_replay):
    assert_floor(RESULT_CSS, ".rbar-note", 20)
    html = run_demo(client_replay, "P4").text
    assert soup(html).select_one(".know .rn-note").get_text(strip=True).startswith("금액은 올해 기준이에요")
    css = RESULT_CSS.replace("\r\n", "\n")
    assert re.search(r"@media \(max-width: 1499px\) \{[^}]*\.rbar-note \{ display: none; \}[^}]*\.rn-note \{ display: list-item; \}", css)
    assert declared(RESULT_CSS, ".rn-note", "display")[0][1] == "list-item"        # 넓은 화면에서도 같은 안내가 보인다(폭에 따라 안내가 빠지지 않는다)


# ---------------- 큰 화면 한 화면: 받을 것 가로 칸 ----------------
def test_wide_window_never_lays_things_to_receive_side_by_side():
    """옛 1500px 이상 가로 칸(받을 것 둘·셋을 나란히)은 없앴다: 상자 안의 줄은 어느 창에서나 세로로만 쌓인다."""
    assert ":has(" not in RESULT_CSS.split("/* ---------- 알아 두세요 상자")[0]
    assert not declared(RESULT_CSS, ".bx-rows", "grid-template-columns") and declared(RESULT_CSS, ".bx-rows", "flex-direction")[-1][1] == "column"      # 줄과 줄은 세로로만(2026-11-16 표: 한 줄 안에서만 이름 칸 | 설명 칸)


# ---------------- 링크 복사하기: 안 될 때 ----------------
def test_copy_fallback_only_says_copied_when_the_browser_confirms_and_keeps_the_box():
    js = (APP / "static" / "copylink.js").read_text(encoding="utf-8").replace("\r\n", "\n")
    manual = js[js.index("function manual"):js.index("document.addEventListener")]
    assert "copied(wrap)" not in manual, "입력칸을 숨기고 복사했다고 말하는 길은 클립보드가 실제로 됐을 때만"
    assert "say(wrap)" in manual and "주소가 선택됐어요" in manual
    assert "hidden = true" not in manual


def test_copy_message_is_a_visible_box_with_reserved_height():
    css = COPY_CSS.replace("\r\n", "\n")
    assert declared(COPY_CSS, ".lk-done", "border")[-1][1].startswith("3px solid")
    assert "visibility: hidden" in css and ".lk-done:empty" in css                # 자리는 그대로(나타날 때 줄이 흔들리지 않는다)
    assert_floor(COPY_CSS, ".lk-done", 44, prop="min-height")


# ---------------- 종이: 표 아래 줄들(상자·제목 없이) ----------------
@pytest.mark.parametrize("pid", DEMO_IDS)
def test_paper_notes_live_in_the_lines_below_the_table(paper_html, pid):
    s = soup(paper_html[pid])
    box = s.select_one(".front .keepl")
    assert box and not s.select(".front .know, .front p.fx")
    assert [p.get_text(strip=True)[:4] for p in box.select("p")][0] == "가실 때"      # 맨 위는 언제나 가실 때 줄


def test_paper_check_tip_is_a_boxed_label_apart_from_the_column_title():
    block = PRINT_CSS.replace("\r\n", "\n")
    m = re.search(r"\.v2 \.chk-tip \{([^}]*)\}", block)
    assert m and "border:" in m[1] and "padding:" in m[1]


def test_paper_front_unlock_line_is_the_screen_line(paper_html):
    """앞면 '이것을 해야 ○○을 받을 수 있어요'(화면과 같은 글)가 종이에 그대로 있다. 종이에는 뒷면이 없다."""
    s = soup(paper_html["P4"])
    front = s.select_one(".front")
    text = re.sub(r"\s+", " ", front.get_text(" ", strip=True))
    assert re.search(r"이것을 해야 \S.*[을를] 받을 수 있어요", text), text
    assert not s.select(".back")
