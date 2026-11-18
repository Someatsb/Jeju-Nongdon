"""결과 화면 검증 손질(2026-11-16): 빈 종이 상자 줄 · 공고 상자 자리 · 같은 달 묶음의 곳 한 번만 · 오늘까지 날짜 겹침 · 선행 조건 글 · 좁은 화면 아래 단추 한 줄.
골든 22건과 재생 P1~P5는 test_result_zones 의 픽스처를 쓴다."""
import re

import pytest
from jinja2 import Environment, FileSystemLoader

from app.core.sheet import EmptyFront
from app.ui.result_view import build_view

from .test_replay import run_demo
from .test_result_list import APP, RESULT_CSS, soup
from .test_result_rows import visible
from .test_result_simplify import NAMES, papers  # noqa: F401


def _empty_names(papers):
    return [n for n in NAMES if isinstance(papers[n][1].front, EmptyFront)]


def test_empty_paper_boxes_keep_their_lines_on_screen(papers):
    """빈 종이(이미 다 받고 있는 농가)의 상자도 줄이 보인다: 카드에 rows 가 있고 상자 조각이 그 줄 글을 적는다."""
    names = _empty_names(papers)
    assert names
    env = Environment(loader=FileSystemLoader(str(APP / "templates")), autoescape=True)
    for name in names:
        fs, sheet, bundle, as_of = papers[name]
        v = build_view(sheet, fs, bundle, as_of, screen=True)
        assert v["now_cards"]
        for c in v["now_cards"]:
            assert len(c["rows"]) == len(c["lines"]) > 0, (name, c["head"])
        html = env.from_string('{% import "_result_boxes.html" as bx %}{{ bx.boxes(cards) }}').render(cards=v["now_cards"])
        text = visible(html)
        for c in v["now_cards"]:
            for ln in c["lines"]:
                assert ln["title"] in text, (name, ln["title"])


def test_notice_box_sits_before_the_always_open_box_not_after(client_replay):
    s = soup(run_demo(client_replay, "P1").text)
    kids = [a for a in s.select("#cards article.bx")]
    assert "bx-nn" in kids[0].get("class", []) and "bx-nn" not in kids[1].get("class", [])      # 10일 남은 공고가 언제든 신청 상자보다 위
    assert s.select_one("#now .zn-n").get_text(strip=True) == "2곳"                          # 제목의 곳 수에 공고 상자도 센다


def test_later_group_shows_the_place_in_each_row_of_the_table(client_replay):
    s = soup(run_demo(client_replay, "P1").text)
    g = [x for x in s.select("#later .lt-g") if x.select_one(".lt-when").get_text(strip=True) == "내년 3월쯤"][0]
    assert all("읍·면사무소, 동 주민센터" in r.select_one(".lt-where").get_text() for r in g.select(".lt-r"))       # 표의 설명 칸: 줄마다 가실 곳(2026-11-16 사장 지시)
    assert not g.select(".lt-gp")                                                                         # 모든 줄에 같은 덧말이 없으면 묶음 아래 공통 줄도 없다
    assert [t.get_text(strip=True) for t in g.select(".lt-t")] == ["소농직불금", "여성농업인 행복이용권", "제주 농민수당"]      # 줄은 그대로


def test_urgent_today_row_does_not_repeat_the_date(papers):
    fs, sheet, bundle, as_of = papers["demo_P3"]
    v = build_view(sheet, fs, bundle, as_of, screen=True)
    row = next(r for c in v["now_cards"] for r in c["rows"] if r.get("urgent") == "오늘까지")
    assert not row["text"] and not row["whens"]


def test_prereq_screen_rows_read_together(papers):
    fs, sheet, bundle, as_of = papers["demo_P4"]
    v = build_view(sheet, fs, bundle, as_of, screen=True)
    rows = v["now_cards"][0]["rows"]
    assert rows[0]["title"] == "농업경영체 등록" and rows[1]["title"] == "이것을 하시면 받을 수 있는 돈"      # 위 띠에 농관원이 있으니 괄호는 뺀다


def test_narrow_screen_pins_only_the_print_button():
    css = RESULT_CSS.replace("\r\n", "\n")
    narrow = css[css.index("@media (max-width: 520px)"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert ".rbar .btn-print { position: fixed;" in narrow and ".rbar { position: static;" in narrow
