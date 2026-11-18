"""설명 문장(AI 한마디)과 종이(2026-11-18 사장 결정): 결과가 있는 종이에는 주황 결론 상자가 없어서 AI 문장도 없다(화면 맨 위 띠에만 있다). 빈 종이(새로 받을 돈이 없는 농가)만 결론 칸에 첫 문장을 싣는다."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.config import load_config
from app.core.sheet import build_sheet
from app.data_layer.tables import load_tables
from app.ui import render as render_mod
from app.ui.render import render_sheet
from conftest import AS_OF, P4_KWARGS, T1_KWARGS
from factsheet_fixtures import amount, make_fs

T1_AMOUNTS = (amount("JEJU-FARMER-ALLOW@2026", 900_000, 900_000), amount("NAT-DIRECT-SMALL@2026", 1_300_000, 1_300_000))
ALL_SLOTS = {"action": ["경영체 등록부터 하세요."], "support": ["건강보험료 지원은 접수처에서 확인하세요."], "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}


@pytest.fixture(scope="module")
def made():
    bundle = load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)
    fs = make_fs(P4_KWARGS, bundle, AS_OF, amounts=(amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),))
    return build_sheet(fs, bundle, AS_OF), fs


@pytest.fixture(scope="module")
def made_empty():
    bundle = load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)
    fs = make_fs(T1_KWARGS, bundle, AS_OF, amounts=T1_AMOUNTS)
    return build_sheet(fs, bundle, AS_OF), fs


def test_result_paper_never_carries_an_ai_sentence(made):
    """할 일·지원·보험 문장 어느 것도 결과가 있는 종이에 찍히지 않는다: 문장이 있든 없든 종이는 글자 하나 다르지 않다."""
    sheet, fs = made
    cfg = load_config([])
    bare = render_sheet(sheet, fs, None, cfg)
    for slots in (ALL_SLOTS, {"action": ALL_SLOTS["action"]}, {"insurance": ALL_SLOTS["insurance"]}):
        html = render_sheet(sheet, fs, slots, cfg)
        assert html == bare
        soup = BeautifulSoup(html, "html.parser")
        assert not soup.select("p.narr, .sh, .s1, .back")
        assert not any(s in soup.get_text() for sentences in slots.values() for s in sentences)


def test_the_paper_has_no_room_reserved_for_the_sentence(made):
    """문장 자리를 미리 비우지 않는다: 줄·곳 묶음·숫자가 문장과 상관없이 같다(위 시험과 같은 말을 줄 수로)."""
    sheet, fs = made
    cfg = load_config([])
    rows = lambda h: [x.get_text(strip=True) for x in BeautifulSoup(h, "html.parser").select(".sheet.front .pr-t, .sheet.front .lr-t")]
    assert rows(render_sheet(sheet, fs, ALL_SLOTS, cfg)) == rows(render_sheet(sheet, fs, None, cfg))


def test_empty_paper_keeps_the_first_sentence_in_its_band(made_empty):
    """빈 종이는 옛 틀 그대로 결론 칸에 설명 문장 첫 하나를 싣는다(남는 자리가 있을 때)."""
    sheet, fs = made_empty
    said = "새로 받을 돈은 없지만 일을 놓치지 마세요."
    html = render_sheet(sheet, fs, {"empty": [said, "둘째 문장입니다."]}, load_config([]))
    soup = BeautifulSoup(html, "html.parser")
    assert [p.get_text(strip=True) for p in soup.select(".front .sh p.narr")] == [said]
    assert render_mod.check_overflow(html) == [] and not soup.select(".back")
