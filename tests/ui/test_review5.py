"""검증에서 나온 지적(2026-11-15 5차): 하실 일 줄의 같은 글 두 번 · 가격 줄의 반월·잠정 · 직원 메뉴 숫자 · 곳 이름 한 표기."""
import re

from bs4 import BeautifulSoup
from markupsafe import Markup

from app.ui import render
from app.ui.result_view import price_say, split_small

ITEM = {"role": "do", "title": "끊기지 않게 · 직불 교육", "text": "올해 직불 교육을 들어 주세요", "text_when": True, "pre": "", "amt": "",
        "whens": [], "notes": [], "check": False, "unlocks_n": 0, "urgent": "", "counted": False, "place_notes": []}


def _macro(template: str, name: str, *args) -> str:
    return str(getattr(render._env.get_template(template).module, name)(*args))


def test_do_row_says_a_when_like_text_only_once_on_screen_and_paper():
    for tpl, macro in (("_result_boxes.html", "do_row"), ("_paper_boxes.html", "do_row")):
        html = _macro(tpl, macro, ITEM)
        assert html.count("올해 직불 교육을 들어 주세요") == 1, tpl
    got = BeautifulSoup(_macro("_result_boxes.html", "get_row", {**ITEM, "role": "insurance", "text": "내년 7월 1일부터 가입할 수 있어요"}), "html.parser")
    assert got.get_text().count("내년 7월 1일부터 가입할 수 있어요") == 1             # 받을 것 줄은 때 글이 달력 줄에 한 번(전과 같다)


def test_price_line_says_plain_words_not_banwol_or_jamjeong():
    assert price_say("이번 반월 아직(잠정)") == "이번 달은 아직 열리지 않았어요 · 거래 날이 적어 바뀔 수 있어요"
    assert price_say("이번 반월 열림") == "이번 달은 열렸어요"
    assert price_say("내년 10월쯤") == "내년 10월쯤"
    whens, notes, _ = split_small("내년 10월쯤 · 이번 반월 아직(잠정)", False)
    assert whens == ["내년 10월쯤"] and notes == ["이번 달은 아직 열리지 않았어요 · 거래 날이 적어 바뀔 수 있어요"]
    assert "반월" not in " ".join(notes) and "잠정" not in " ".join(notes)


# ---- 종이: 곳 이름(test_paper_v2 의 made·bundle 픽스처를 쓴다) ----
from .test_paper_v2 import ALL, NARR, bundle, made, paper, parse  # noqa: E402,F401


def test_paper_uses_plain_place_names(made, bundle):
    for name in ALL:
        soup = parse(paper(made, name, NARR, bundle))
        text = soup.get_text(" ")
        assert "건보공단" not in text and "읍면동" not in text, name
