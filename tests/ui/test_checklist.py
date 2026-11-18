"""같이 확인해요 표(2026-11-15 사장 지시): 직원용 · 자세한 내용 보기 창의 표. 종이에는 없다(2026-11-18 뒷면을 없앴다)."""
import pytest
from bs4 import BeautifulSoup

from app.ui.checklist import money_value
from app.ui.check_items import load_items
from app.ui.preflight import preflight
from .test_paper_v2 import ALL, CFG, TABLES, bundle, made, paper, parse  # noqa: F401

ASK_CASES = ("P1", "P2", "P3", "P4", "P5")


def test_money_value():
    assert money_value("연 약 180만~258만 원") == 2_580_000 and money_value("") == 0


@pytest.mark.parametrize("name", ASK_CASES)
def test_paper_has_no_ask_block_and_no_old_check_words(made, bundle, name):
    """같이 확인해요 표는 종이에 없다(2026-11-18 뒷면을 없앴다): 직원용 창에만 있다. 종이는 '조건은 …에서 직원과 같이 확인해요' 줄도, 옛 '조건을 확인해야 해요'도 싣지 않는다."""
    html = paper(made, name, None, bundle)
    soup = parse(html)
    assert not soup.select(".bk-ask, .back")
    text = " ".join(soup.get_text(" ").split())
    assert "같이 확인해요" not in text and "직원과 같이" not in text and "조건을 확인해야 해요" not in text
    assert "다 맞으면 신청하세요" not in text


@pytest.mark.parametrize("name", ASK_CASES)
def test_ask_lines_stay_on_the_screen_detail_window(made, bundle, name):
    """직원용 · 자세한 내용 보기 창(result_view.build_view)의 같이 확인해요 표는 종이와 상관없이 그대로 있다."""
    from app.ui.result_view import build_view
    from conftest import AS_OF
    sheet, fs = made[name]
    easy = {v[1] for v in load_items().values() if v[0] == "ask"}
    asks = build_view(sheet, fs, bundle, AS_OF, None, screen=True)["detail"]["asks"]
    for e in asks:
        assert all(a in easy for a in e["asks"]), (name, e)


@pytest.mark.parametrize("name", ASK_CASES)
def test_preflight_passes_without_ask_block(made, bundle, name):
    sheet, fs = made[name]
    html = paper(made, name, None, bundle)
    codes = preflight(html, fs, CFG)
    assert not [c for c in codes if c in ("NO_SOURCE", "NO_ASOF", "NARR_DIGIT", "OVERFLOW")], codes
