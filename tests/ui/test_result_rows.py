"""결과 화면 2차(2026-11-14 설계 result-v2 2·5절): 좌우로 나눈 줄 · 뜻 그림(위치 핀 없음) · 줄 이름표 · 금액 글이 카드 층과 같음 ·
어르신 화면에 속 일을 설명하는 말이 없고(직원이 볼 내용에는 남아 있음) 줄임말이 풀려 있다. 재생 P1~P5."""
import html as htmllib
import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from app.ui.result_view import office_display, split_small

from .test_replay import run_demo

DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")
TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "ui" / "templates"
# 어르신 화면에 나오면 안 되는, 프로그램·AI가 속에서 하는 일을 설명하는 말과 행정 줄임말
FORBIDDEN = ("쉬운 말로 풀고", "설명 문장", "기본 문장", "대조", "건보공단", "검사를 통과", "틀린 곳을 검사", "하십시오", "확인할 조건 있음")


def visible(html: str) -> str:
    """어르신이 보는 글: 스크립트·스타일·직원이 볼 내용은 뺀다."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    html = re.sub(r'<details class="staff">.*?</details>', " ", html, flags=re.S)
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


def later_of(html: str) -> str:
    """앞으로 신청할 것 구역의 글."""
    i = html.index('id="later"')
    return visible(html[i:html.index("</section>", i)])


def rows_of(html: str) -> list[str]:
    """가실 곳 상자들(2026-11-15 4차: 가실 곳마다 상자 하나, 받는 것은 한 줄에 하나씩). 이름은 옛 시험에서 그대로 쓴다."""
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "html.parser")          # "지금 접수 중인 공고" 상자(.bx-nn)도 #cards 안에 끼어 있다: 가실 곳 상자만 센다
    return [str(a) for a in s.select("#cards article.bx") if "bx-nn" not in a.get("class", [])]


@pytest.fixture(params=DEMO_IDS)
def page(request, client_replay):
    r = run_demo(client_replay, request.param)
    assert r.status_code == 200
    return request.param, r.text


# ---------------- 상자 구조 ----------------
def test_every_box_has_a_band_and_one_row_per_thing_and_no_old_heads(page):
    pid, html = page
    body = html[html.index('id="cards"'):html.index("</section>", html.index('id="cards"'))]
    assert 'class="rh"' not in body and "모두 3가지" not in body and "어디로 가서 무엇을" not in body      # 옛 머리 줄은 없다
    rows = rows_of(html)
    assert len(rows) >= 1
    assert sum("is-first" in r.split(">", 1)[0] for r in rows) <= len(rows)
    for r in rows:
        assert 'class="bx-band"' in r and "bx-t" in r and "에 가세요" not in r
        assert 'class="bx-rows"' in r and 'class="bxr ' in r
        assert "신청하기" not in r                                        # 정보 없는 채움말은 없다
        assert 'class="rr-r"' not in r and "rr-arrow" not in r           # 좌우 칸·화살표 없음(세로로만)


def test_every_row_has_a_place_icon_and_no_location_pin(page):
    pid, html = page
    for r in rows_of(html):
        pic = re.search(r'<span class="bx-pic">(.*?)</span>', r, flags=re.S)[1]
        assert "<svg" in pic and 'aria-hidden="true"' in pic
    assert "M20 3 C12 3" not in html and "pin(" not in html          # 위치 핀 그림이 없다


def test_every_picture_has_text_beside_it_and_is_hidden_from_readers(page):
    pid, html = page
    assert 'role="img"' not in html
    for m in re.finditer(r'<svg class="ic[^"]*"[^>]*>', html):
        assert 'aria-hidden="true"' in m[0]
    for r in rows_of(html):
        for li in re.findall(r'<li class="bxr .*?</li>', r, flags=re.S):
            assert re.search(r"[가-힣]", re.sub(r"<svg.*?</svg>", "", li, flags=re.S))


def test_line_labels_money_umbrella_calendar_magnifier(page):
    pid, html = page
    blob = " ".join(rows_of(html))
    if "bxr-when" in blob:
        assert "M6 20 h36 V15" in blob                              # 시기는 달력 그림
    assert "조건을 확인해야 해요" not in blob and "bxr-check" not in blob       # 줄마다 붙던 말은 없다(2026-11-15: 알아 두세요 한 줄 + 뒷면 같이 확인해요 표)


def test_hidden_lines_stay_one_note_per_row(page):
    pid, html = page
    for r in rows_of(html):
        assert "rr-more" not in r                 # 화면에는 "외 ○가지"가 없다(한도가 없다)


# ---------------- 사례별 왼쪽·오른쪽이 말이 된다 ----------------
def test_p4_first_box_is_the_task_with_the_money_under_it(client_replay):
    rows = rows_of(run_demo(client_replay, "P4").text)
    first = visible(rows[0])
    assert "농산물품질관리원(농관원) 제주지원" in first and "1644-8778" in first and "농업경영체 등록" in first and "먼저 하실 일" not in first
    assert "조건이 맞으면 연 약 180만~258만 원" in first and "직불은 내년 3~5월쯤 신청해요" in first and "이것을 해야 제주 농민수당" in first
    second = visible(rows[1])
    assert "건강보험공단 지사" in second and "1577-1000" in second and "언제든 신청할 수 있어요" in second      # 줄임말 건보공단을 풀어 쓴다
    from .test_result_list import soup
    html = run_demo(client_replay, "P4").text
    later = later_of(html)          # 내년 8~10월 보험은 넉 달 밖이라 표에는 없고 한 줄 안내 + 직원용 창 목록에 있다(2026-11-18)
    assert len(rows) == 2 and "양배추 농작물보험" not in later and "그뒤에도1가지가더있어요·내년8월부터신청해요" in later.replace(" ", "") and "신청하기" not in visible(" ".join(rows))
    assert "양배추 농작물보험" in " ".join(soup(html).select_one(".staff-far").get_text().split())


def test_p3_urgent_and_next_insurance_sit_in_the_same_box(client_replay):
    html = run_demo(client_replay, "P3").text
    rows = rows_of(html)
    first = visible(rows[0])
    assert "자조금 가입 확인" in first and "마늘 농작물보험" in first and "오늘까지" in first and "11월 13일까지" not in first and "오늘 11월 13일까지" not in first      # 딱지가 오늘을 말하니 같은 뜻의 날짜 줄은 적지 않는다(2026-11-16 검증)
    later = later_of(html)          # 내년 8~10월 보험은 넉 달 밖: 지금 상자에도 표에도 없고 직원용 창 목록에 있다
    assert "월동무 농작물보험" not in first and "월동무 농작물보험" not in later and "그뒤에도2가지가더있어요·내년5월부터신청해요" in later.replace(" ", "")
    from .test_result_list import soup
    far = " ".join(soup(html).select_one(".staff-far").get_text().split())
    assert "월동무 농작물보험" in far and "내년 8~10월에 가입해요" in far
    assert "배우자가 경영체에 등록했는지 확인" in visible(rows[1])


def test_p2_and_p5_confirm_lines_in_plain_words(client_replay):
    for pid in ("P2", "P5"):
        rows = rows_of(run_demo(client_replay, pid).text)
        assert "먼저 하실 일" not in visible(" ".join(rows)) and "조건을 확인해야 해요" not in visible(" ".join(rows))
        assert "확인할 조건 있음" not in visible(" ".join(rows))


def test_p1_every_box_names_the_place_and_lists_what_you_get(client_replay):
    rows = rows_of(run_demo(client_replay, "P1").text)
    assert len(rows) == 1                                           # 지금 하실 일 상자는 건강보험공단 하나(나머지는 내년이라 앞으로 구역)
    for r in rows:
        assert "에 가세요" not in visible(r)
    later = later_of(run_demo(client_replay, "P1").text)
    assert "소농직불금" in later and "130만 원" in later and "집에서는 농업e지나 전화 1334" in later and "읍·면사무소, 동 주민센터" in later


# ---------------- 금액 글이 카드 층과 같다 ----------------
def test_money_text_equals_the_card_layer(client_replay, monkeypatch):
    import app.ui.result_view as rv
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 13)          # 줄이지 않는 기준으로 본다(줄인 모습은 test_later_window.py)
    from tests.ui.conftest import _session
    from app.core.sheet_cards import build_cards
    from app.ui.routes_counsel import _paper
    for pid in DEMO_IDS:
        html = run_demo(client_replay, pid).text
        paper = _paper(type("R", (), {"app": client_replay.app, "cookies": client_replay.cookies})(), _session(client_replay))
        cs = build_cards(paper["sheet"], paper["fs"], max_cards=12, max_lines=99)
        text = visible(" ".join(rows_of(html))) + " " + later_of(html)          # 줄은 지금 구역 아니면 앞으로 구역에 있다
        for c in cs.cards:
            assert not c.hidden and not cs.others            # 화면은 가실 곳도 줄도 전부 보인다
            for cl in c.lines:
                assert cl.title in text or re.sub(r"\s*\([^)]+\)$", "", cl.title) in text, (pid, cl.title)      # 위 띠에 기관 이름이 있으면 줄 이름 끝 괄호(농관원)는 뺀다
                assert all(piece in text for piece in cl.text.split(" · ")) or (cl.text.startswith("오늘 ") and "오늘까지" in text), (pid, cl.text)      # 앞으로 구역은 때 · 덧말을 줄로 나눠 적는다      # 빨간 딱지가 '오늘'을 대신한다
        for cl in cs.card_lines:
            assert cl.role in ("do", "confirm", "insurance", "benefit")
            assert cl.role in ("do", "confirm") if cl.todo else cl.role in ("insurance", "benefit")


# ---------------- 문구 ----------------
def test_elder_result_screen_has_no_inside_talk(page):
    pid, html = page
    text = visible(html)
    for w in FORBIDDEN:
        assert w not in text, w
    assert "AI가 쉬운 말로 설명 문장" not in text


def test_staff_fold_keeps_the_inside_talk(client_replay):
    html = run_demo(client_replay, "P4").text
    staff = html[html.index('<details class="staff">'):html.index("</details>", html.index('<details class="staff">'))]
    assert "AI가" in staff and "직원이 볼 내용" in staff and ("기본 문장" in staff or "문장" in staff)
    assert "AI가 쉬운 말로 설명 문장" not in visible(html)


def test_working_and_other_elder_screens_have_no_inside_talk(client_replay):
    assert client_replay.get("/counsel/input").status_code == 200
    run_demo(client_replay, "P4")
    for path in ("/counsel/input", "/counsel/confirm", "/counsel/working"):
        r = client_replay.get(path)
        if r.status_code != 200:
            continue
        text = visible(re.sub(r'<div class="w-more".*?</ul>.*?</div>', "", r.text, flags=re.S))      # 오래 걸릴 때만 보이는 세 줄(hidden)은 test_flow_elder 에서 따로 시험
        for w in FORBIDDEN:
            assert w not in text, (path, w)
    working = re.sub(r'<div class="w-more".*?</ul>.*?</div>', "", client_replay.get("/counsel/working").text, flags=re.S)
    assert "받을 수 있는 지원을 찾고 있어요" in working and "쉬운 말로" not in working and "틀린 곳" not in working


def test_staff_screens_may_still_name_the_inside_work(client_demo):
    html = client_demo.get("/staff").text
    assert "AI" in html


# ---------------- 단위 ----------------
def test_office_display_and_split_small():
    assert office_display("건보공단 지사") == "건강보험공단 지사"
    assert office_display("농관원 제주지원") == "농산물품질관리원(농관원) 제주지원"
    assert office_display("지역농협") == "지역농협" and office_display(None) is None
    assert split_small("예년 3월 · 확인할 조건 있음", False) == (["예년 3월"], [], True)
    assert split_small("재해보험·수입안정보험 둘 중 하나만", False) == ([], ["재해보험·수입안정보험 둘 중 하나만"], False)
    assert split_small(None, True) == ([], [], True)


def _render(expr: str) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    return env.from_string('{% import "_art.html" as art %}' + expr).render()


@pytest.mark.parametrize("name,marker", [
    ("지역농협", "M4 21 L24 7"), ("구좌농협", "M4 21 L24 7"), ("서귀포감협", "M4 21 L24 7"),
    ("농관원 제주지원", "M8 4 h20 l9 9"), ("국립농산물품질관리원 제주지원(농관원)", "M8 4 h20 l9 9"),
    ("건보공단 지사", "M24 4 L40 9"), ("건강보험공단 지사", "M24 4 L40 9"),
    ("국민연금공단 지사", "M13 19 l2 -6 l7 3"), ("농지은행", "M6 24 L21 8"),
    ("주소지 읍·면사무소, 동 주민센터", "M5 22 L24 12"), ("제주시청", "M5 22 L24 12"), ("행정시", "M5 22 L24 12"),
    ("알 수 없는 곳", "M9 43 V9"), ("", "M9 43 V9"),
])
def test_place_name_picks_the_icon_by_words_in_the_name(name, marker):
    svg = _render('{{ art.place_icon("' + name + '", "ic") }}')
    assert marker in svg and 'aria-hidden="true"' in svg


def test_every_named_icon_renders_small_and_hidden():
    names = ("pencil", "confirm", "coin", "umbrella", "calendar", "magnify", "phone", "list", "printer", "chat", "home", "hourglass", "book", "cycle", "note", "staff",
             "pi_coop", "pi_qa", "pi_health", "pi_pension", "pi_farmland", "pi_gov", "pi_building")
    seen = set()
    for n in names:
        svg = _render('{{ art.ic("' + n + '", "ic") }}')
        assert svg.count("<svg") == 1 and 'viewBox="0 0 48 48"' in svg and 'aria-hidden="true"' in svg, n
        assert "<text" not in svg                                  # 글자·상표를 그려 넣지 않는다
        seen.add(svg)
    assert len(seen) == len(names)                                 # 서로 다른 그림


def test_bottom_bar_buttons_and_detail_headings_have_pictures(client_replay):
    html = run_demo(client_replay, "P4").text
    bar = html[html.index('class="rbar"'):html.index('id="detail"')]
    assert bar.count("<svg") >= 3      # 처음으로 · 문자 알림 받기 · 종이로 뽑기(자세히 보기 단추는 없다)
    assert "자세히 보기" not in bar and "직원용 · 자세한 내용 보기" in html and html.index("직원용 · 자세한 내용 보기") < html.index('class="rbar"')      # 여는 길은 맨 아래 작은 글 링크 하나
    detail = html[html.index('id="detail"'):]
    for head in ("올해는 어려워요", "같이 확인해요", "어려운 말 풀이"):
        at = detail.index(head)
        assert detail[max(0, at - 1800):at].rstrip().endswith("<span>"), head          # 제목 글 바로 앞 <span> 앞에 그림이 붙어 있다
        assert "</svg><span>" in detail[max(0, at - 12):at + 1] or detail[max(0, at - 1800):at].rstrip().rsplit("</svg>", 1)[1].strip() == "<span>", head
