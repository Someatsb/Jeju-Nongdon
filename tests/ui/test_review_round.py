"""결과 화면·종이 2차 점검 반영(2026-11-14 밤, 부장 점검 + 사용자 시험 지적): 먼저 하실 일 표시는 한 줄만 · 급한 보험은 받을 수 있는 것 쪽 ·
어르신 말로 고친 글 · 번호는 큰 숫자 · 종이는 '오늘' 대신 날짜 · 종이 앞면 줄임에서도 이름·금액이 남음 · 로고·인쇄 탭 단추 색 · 문자 덮개 말."""
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from .test_replay import run_demo

STATIC = Path(__file__).resolve().parents[2] / "app" / "ui" / "static"
TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "ui" / "templates"
DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")


def soup(html):
    return BeautifulSoup(html, "html.parser")


def text(el):
    return re.sub(r"\s+", " ", el.get_text(" ")).strip()


@pytest.fixture(params=DEMO_IDS)
def page(request, client_replay):
    r = run_demo(client_replay, request.param)
    assert r.status_code == 200
    return request.param, r.text, client_replay


# ---------------- 먼저 하실 일: 한 줄에만 ----------------
def test_pill_and_orange_border_belong_to_the_same_single_row(page):
    pid, html, _ = page
    rows = soup(html).select("article.bx")
    assert rows and not [r for r in rows if "is-first" in r["class"]]          # 2026-11-15 두 구역: 구역 제목이 "지금 하실 일"이라 딱지·굵은 주황 테두리는 없다
    assert not soup(html).select(".bx-tag")


# ---------------- 번호는 큰 숫자 ----------------
def test_number_badge_is_a_plain_digit_not_a_circled_glyph(page):
    pid, html, _ = page
    for i, n in enumerate(soup(html).select("article.bx .bx-no"), 1):
        assert text(n) == str(i)


# ---------------- P3: 마늘 보험(오늘까지)은 받을 수 있는 것 쪽에 월동무와 나란히 ----------------
def test_p3_urgent_insurance_sits_with_the_other_insurance_on_the_right(client_replay):
    html = run_demo(client_replay, "P3").text
    s = soup(html)
    body = text(s.select_one("article.bx .bx-rows"))
    assert "마늘 농작물보험" in body and "오늘까지" in body and "11월 13일까지" not in body      # 빨간 딱지가 오늘을 말하니 날짜 줄은 없다
    assert "월동무 농작물보험" not in text(s.select_one("#later")) and "월동무 농작물보험" in text(s.select_one(".staff-far"))        # 내년 8~10월 보험은 넉 달 밖: 표에는 없고 직원용 창 목록에 있다(2026-11-18)
    assert "신청하기" not in body and "가입하기" not in body


# ---------------- 어르신 말 ----------------
OLD_WORDS = ("소재지", "ARS", "비대면", "해당 제도", "카드마다", "한 번 더 쉽게")


def test_screen_has_no_hard_words(page):
    pid, html, _ = page
    s = soup(re.sub(r'<details class="staff">.*?</details>', "", html, flags=re.S))
    for t in s(["script", "style"]):
        t.decompose()
    body = text(s)
    for w in OLD_WORDS:
        assert w not in body, w


def test_remind_button_is_not_the_same_word_as_the_row_action(page):
    pid, html, _ = page
    btn = soup(html).select_one("#rm-send")
    assert text(btn) == "알려 주세요"


def test_after_print_notice_keeps_the_rows_visible():
    css = (STATIC / "result.css").read_text(encoding="utf8")
    printed = [l for l in css.splitlines() if l.startswith(".printed .rband")]
    assert printed and ".rrows" not in printed[0]                # 종이를 뽑은 뒤에도 결과 줄은 그대로 보인다


def test_amount_is_the_only_orange_part_of_the_money_text(client_replay):
    html = run_demo(client_replay, "P4").text
    amts = soup(html).select(".bxr-m .bxr-amt")
    assert amts and all(re.search(r"\d.*원", text(a)) for a in amts)
    css = (STATIC / "result.css").read_text(encoding="utf8")
    assert re.search(r"\.bxr-amt\s*\{[^}]*tang-deep", css) and not re.search(r"\.bxr-m\.is-text\s*\{[^}]*tang-deep", css)


def test_hidden_count_note_points_to_the_detail_not_to_paper(page):
    pid, html, _ = page
    for n in soup(html).select(".rn-more"):
        assert "종이에 있어요" not in text(n) and "자세히 보기" in text(n)


# ---------------- 로고·인쇄 탭 ----------------
def test_logo_keeps_its_colors_on_the_result_screen():
    css = (STATIC / "result.css").read_text(encoding="utf8")
    assert not re.search(r"\.page-r a\.brand svg[^{]*\{[^}]*fill", css)         # 2026-11-16 사장: 맨 위 로고는 첫 화면과 같은 색(색 빼는 규칙 없음)


def test_auto_print_bar_button_is_white_with_black_border():
    src = (Path(__file__).resolve().parents[2] / "app" / "ui" / "routes_counsel.py").read_text(encoding="utf8")
    block = src[src.index("AUTO_PRINT = ("):src.index("@router.get", src.index("AUTO_PRINT = ("))]
    assert "#A94607" not in block and "#FFF6E3" not in block


# ---------------- 종이 ----------------
@pytest.fixture
def paper(page):
    pid, html, client = page
    r = client.get("/counsel/print")
    assert r.status_code == 200
    s = soup(r.text)
    return pid, s.select_one("section.front"), r.text


def test_paper_says_dates_not_today(paper):
    """종이는 며칠 뒤에도 읽으니 '오늘 …까지'·'○일 남음' 대신 날짜를 적는다. 마감이 기준일 당일이면 '오늘까지(11월 13일)'처럼 오늘이 마감임이 보이게 날짜를 함께 적는다(2026-11-16)."""
    pid, front, _ = paper
    said = re.sub(r"오늘까지\(\s*\d+\s*월\s*\d+\s*일\)", "", text(front))
    assert "오늘" not in said and "일 남음" not in said


def test_paper_footer_and_date_are_easy_korean(paper):
    pid, front, raw = paper
    foot = text(front.select_one(".foot"))
    assert "공문서가 아니에요" in foot and "합니다" not in foot and "해요" in foot
    assert "합니다" not in text(front)


def test_paper_replay_line_has_no_english(paper):
    pid, front, raw = paper
    assert "AI 답변" not in raw


def test_paper_lists_every_line_by_name(client_replay):
    """종이는 줄을 줄이지 않는다(2026-11-17): 앞으로 구역에는 가까운 줄이 때와 함께 이름이 있고, 넉 달 밖(월동무 보험 · 내년 8~10월)은 맨 끝 '그 뒤에도 ○가지' 한 줄이 알린다(2026-11-18)."""
    run_demo(client_replay, "P3")
    pages = soup(client_replay.get("/counsel/print").text).select("section.front")
    first = text(pages[0].select_one(".rrw"))
    assert "마늘 농작물보험" in first and "자조금 가입 확인" in first
    later = " ".join(text(p.select_one(".pz-later")) for p in pages if p.select_one(".pz-later"))
    sq = later.replace(" ", "")
    assert not re.search(r"외\s*\d+\s*가지", later) and "월동무 농작물보험" not in later and "월" in later and "그뒤에도2가지가더있어요" in sq


