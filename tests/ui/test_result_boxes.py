"""결과 화면 4차(2026-11-15 설계 result-v4): 가실 곳마다 상자 · 화면에는 한도가 없다 · 상자 순서 · 종이는 지금처럼.
순서·한도는 화면용 값(result_view.build_view(screen=True))에서만 바뀐다. AI 에 보내는 입력·FactSheet 지문·종이(screen=False, render.py)는 그대로다.
골든 22건 + 재생 5건(test_result_simplify.papers 픽스처)."""
import re

import pytest

from app.core.sheet import EmptyFront
from app.core.sheet_cards import MAX_CARD_LINES, MAX_CARDS, build_cards
from app.ui.result_view import SCREEN_MAX_CARDS, build_view, notice_box, order_boxes

from .test_result_list import DEMO_IDS, soup
from .test_replay import run_demo
from .test_result_rows import rows_of, visible
from .test_result_simplify import NAMES, papers  # noqa: F401


def _screen_cards(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    return build_view(sheet, fs, bundle, as_of, screen=True), build_view(sheet, fs, bundle, as_of)


@pytest.mark.parametrize("name", NAMES)
def test_screen_shows_every_place_and_every_line_but_paper_limits_stay(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    if isinstance(sheet.front, EmptyFront):
        pytest.skip("빈 종이는 카드 묶음이 없다(test_empty_front_screen_does_not_break)")
    screen = build_view(sheet, fs, bundle, as_of, screen=True)
    paper = build_view(sheet, fs, bundle, as_of)
    assert len(paper["cards"]) <= MAX_CARDS and all(c["hidden_n"] == 0 or len(c["lines"]) == MAX_CARD_LINES for c in paper["cards"])      # 종이용 한도는 그대로
    full = build_cards(sheet, fs, None, max_cards=SCREEN_MAX_CARDS, max_lines=99)
    assert not full.others and all(not c.hidden for c in full.cards)
    assert len(screen["cards"]) == len(full.cards) >= len(paper["cards"])
    assert screen["others_n"] == 0 and all(c["hidden_n"] == 0 for c in screen["cards"])
    assert not [k for k in screen["know"] if k["kind"] == "more" and "그 밖에" in k["text"]]            # "그 밖에 ○가지 · 자세히 보기에서"는 화면에서 사라진다
    shown = sum(len(c["lines"]) for c in screen["cards"])
    assert shown == sum(len(c.lines) for c in full.cards) >= sum(len(c["lines"]) for c in paper["cards"])


@pytest.mark.parametrize("name", NAMES)
def test_paper_view_is_unchanged_by_the_screen_rules(papers, name):
    """종이가 쓰는 build_view(screen=False)는 순서·번호가 지금과 같다: 번호 ①②③ 은 build_cards 의 순서 그대로."""
    fs, sheet, bundle, as_of = papers[name]
    if isinstance(sheet.front, EmptyFront):
        pytest.skip("빈 종이는 카드 묶음이 없다")
    paper = build_view(sheet, fs, bundle, as_of)
    cs = build_cards(sheet, fs, None)
    assert [c["no"] for c in paper["cards"]] == [c.no for c in cs.cards] and [c["head"] is not None for c in paper["cards"]]
    assert all(c["now"] is False for c in paper["cards"])


@pytest.mark.parametrize("name", NAMES)
def test_box_order_first_then_open_now_then_next_month(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    if isinstance(sheet.front, EmptyFront):
        pytest.skip("빈 종이는 상자 순서 규칙 밖")
    v = build_view(sheet, fs, bundle, as_of, screen=True)
    cards = v["cards"]
    kinds = ["first" if c["first"] else "now" if c["now"] else "rest" for c in cards]
    assert kinds == sorted(kinds, key=("first", "now", "rest").index), (name, kinds)               # 먼저 하실 일 → 지금 신청할 수 있어요 → 나머지
    assert [c["no_n"] for c in cards] == [str(i + 1) for i in range(len(cards))]                     # 번호는 새 순서대로
    assert [c["no"] for c in cards] == list("①②③④⑤⑥⑦⑧⑨⑩⑪⑫")[:len(cards)]


@pytest.mark.parametrize("name", NAMES)
def test_order_changes_no_input_to_the_ai_or_the_fact_sheet(papers, name):
    """순서는 CardSet 의 화면용 복사본에서만 바뀐다. FactSheet(지문)과 Sheet 는 건드리지 않고, 입력은 같은 FactSheet 에서 만들어진다."""
    fs, sheet, bundle, as_of = papers[name]
    before = (fs.fingerprint, sheet.model_dump_json())
    build_view(sheet, fs, bundle, as_of, screen=True)
    assert (fs.fingerprint, sheet.model_dump_json()) == before
    cs = build_cards(sheet, fs, None, max_cards=SCREEN_MAX_CARDS, max_lines=99)
    if not cs.empty:
        prog_of = {p.id: p for p in bundle.programs}
        ordered, now = order_boxes(cs, prog_of, as_of)
        assert sorted(c.office or "" for c in ordered.cards) == sorted(c.office or "" for c in cs.cards) and len(now) == len(cs.cards)
        assert sorted(ordered.ref) == sorted(cs.ref) and ordered.count == cs.count


def html_of(client, pid="P1"):
    return run_demo(client, pid).text


def test_p1_order_open_now_box_comes_first_then_nearest_month(client_replay):
    boxes = rows_of(run_demo(client_replay, "P1").text)
    heads = [re.sub(r"\s+", " ", soup(b).select_one(".bx-t").get_text(" ", strip=True)).replace(" 에", "에") for b in boxes]
    assert heads == ["건강보험공단 지사"] and "언제든 신청할 수 있어요" in visible(boxes[0])      # 상시 신청 = 지금 할 수 있다(지금 구역은 이 상자 하나)
    s = soup(html_of(client_replay))
    assert [w.get_text(strip=True) for w in s.select("#later .lt-when")][:2] == ["내년 2월쯤", "내년 3월쯤"]      # 앞으로 구역은 가까운 달부터
    assert not [1 for b in boxes if soup(b).select_one(".bx-no")]      # 번호 동그라미는 없다


def test_every_screen_line_row_has_no_filler_word(client_replay):
    for pid in DEMO_IDS:
        assert "신청하기" not in visible(" ".join(rows_of(run_demo(client_replay, pid).text))), pid


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_top_band_counts_match_the_boxes(client_replay, pid):
    html = run_demo(client_replay, pid).text
    s = soup(html)
    boxes = rows_of(html) + s.select("#cards article.bx-nn")          # 지금 접수 중인 공고 상자도 가실 곳으로 센다
    assert s.select_one(".rb-n").get_text(strip=True) == f"지금 가실 곳은 {len(boxes)}곳이에요"
    head = s.select_one(".rb-h").get_text(strip=True)
    m = re.search(r"받을 수 있는 지원 (\d+)가지를 찾았어요", head)
    if m:
        far = s.select_one("#later .lt-more")          # 넉 달 밖으로 줄인 줄도 결론의 가짓수에는 든다
        assert int(m[1]) == len(s.select("#cards .bxr[data-n], #later .lt-r[data-n]")) + (int(far["data-counted"]) if far else 0)


def test_speak_text_follows_the_screen_order_and_has_no_old_names(client_replay):
    html = run_demo(client_replay, "P1").text
    speak = soup(html).select_one(".btn-speak[data-speak]")["data-speak"]
    assert speak.index("지금 하실 일이에요") < speak.index("건강보험공단") < speak.index("앞으로 신청할 것이에요") < speak.index("내년 2월쯤") < speak.index("그 뒤에도 1가지가 더 있어요")
    assert "새로 나온 공고" not in speak and "그 밖에" not in speak and "가세요" not in speak
    assert "내년 4월부터 신청해요" in speak and "농작물보험" not in speak          # 먼 줄은 화면처럼 이름 없이 한 줄로 읽는다


def test_empty_front_screen_does_not_break(client_demo):
    from tests.golden.golden_adapter import build_paper as bp, case_env as ce, load_case as lc, to_profile as tp
    case = lc("T2")
    env = ce(case)
    fs, sheet, _ = bp(tp(case["profile"]), env.bundle, env.snap, env.cfg)
    if not isinstance(sheet.front, EmptyFront):
        pytest.skip("T2가 빈 종이가 아님")
    v = build_view(sheet, fs, env.bundle, env.cfg.as_of, screen=True)
    assert v["empty"] and v["cards"] and all(c["now"] is False and c["first"] is False for c in v["cards"])
    from jinja2 import Environment, FileSystemLoader

    from .test_result_list import TEMPLATES
    env_j = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    env_j.filters["tel"] = lambda x: x
    html = env_j.from_string('{% import "_result_boxes.html" as bx %}{{ bx.boxes(cards) }}').render(cards=v["cards"])
    s = soup(html)
    assert len(s.select("article.bx")) == len(v["cards"]) and s.select("article.bx .bx-band") and not s.select(".bx-no")


def test_no_box_tags_and_urgent_pill_is_red(client_replay):
    s = soup(run_demo(client_replay, "P3").text)
    assert not s.select(".bx-tag, .bx.is-first") and "먼저 하실 일" not in s.get_text() and "지금 신청할 수 있어요" not in s.get_text()      # 구역 제목이 그 뜻이다
    assert s.select_one("article.bx .bxr-left .left-pill.is-urgent")


# ---------------- "지금 접수 중인 공고" 상자 글 가르기 ----------------
def test_notice_box_splits_place_days_left_and_date():
    v = notice_box({"where": "접수처: 지역 농·감협", "period": "11월 23일까지 · 10일 남음"})
    assert v == {"place": "지역 농·감협", "other": "", "left": "10일 남음", "urgent": False, "date": "11월 23일까지"}
    v = notice_box({"where": "공고 낸 곳: 감귤유통과", "period": "11월 15일까지 · 오늘 마감"})
    assert v["place"] == "" and v["other"] == "" and v["left"] == "오늘 마감" and v["urgent"] and v["date"] == "11월 15일까지"
    v = notice_box({"where": "신청방법: 온라인 접수", "period": "시기는 창구에서 확인"})
    assert v["place"] == "" and v["other"] == "신청방법: 온라인 접수" and v["left"] == "" and not v["urgent"] and v["date"] == "시기는 창구에서 확인"
    assert notice_box({"where": "신청장소: 읍·면사무소", "period": "11월 20일까지 · 7일 남음"})["urgent"]          # 7일 안은 빨강 바탕
