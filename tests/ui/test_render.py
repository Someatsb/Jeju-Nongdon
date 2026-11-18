"""인쇄 템플릿(Task 17): 배지·빈 종이·넘침 검사. 종이는 앞면 한 면뿐이다(2026-11-18)."""
import re
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.config import load_config
from app.core.models import Fact, SourceRef
from app.core.sheet import build_sheet
from app.data_layer.tables import load_tables
from app.ui import render as render_mod
from app.ui.render import CARD_CAP, check_overflow, render_sheet
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS, T2_KWARGS
from factsheet_fixtures import amount, make_fs, trigger

CFG = load_config([])
CFG_DEMO = load_config(["--asof", "2026-11-13"])
P4_AMOUNTS = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)
T1_AMOUNTS = (amount("JEJU-FARMER-ALLOW@2026", 900_000, 900_000), amount("NAT-DIRECT-SMALL@2026", 1_300_000, 1_300_000))
NARR_P4 = {"action": ["경영체 등록부터 하시면 아래 직불을 받으실 길이 열립니다."],
           "support": ["농협을 거치는 돈은 올해 해당되지 않을 수 있습니다."],
           "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


@pytest.fixture(scope="module")
def bundle():
    return load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", AS_OF)


@pytest.fixture(scope="module")
def made(bundle):
    """이름 → (Sheet, FactSheet)."""
    out = {}
    for name, kw, amts in (("P1", P1_KWARGS, ()), ("P2", P2_KWARGS, ()), ("P3", P3_KWARGS, ()),
                           ("P4", P4_KWARGS, P4_AMOUNTS), ("P5", P5_KWARGS, ()), ("T1", T1_KWARGS, T1_AMOUNTS),
                           ("T2", T2_KWARGS, ())):
        fs = make_fs(kw, bundle, AS_OF, amounts=amts)
        out[name] = (build_sheet(fs, bundle, AS_OF), fs)
    return out


def test_prior_row_renders_badge(made):
    sheet, fs = made["P1"]
    html = render_sheet(sheet, fs, None, CFG)
    assert "2026년 기준 · 2027년 공고 전" in html


def test_result_paper_has_no_ai_sentence_and_no_back(made):
    """결과가 있는 종이에는 AI 한 문장이 없다(결론 상자가 없다: 화면 맨 위 띠에만 있다). 뒷면도 없어서 어디에도 문장이 실리지 않는다."""
    sheet, fs = made["P4"]
    soup = parse(render_sheet(sheet, fs, NARR_P4, CFG))
    assert not soup.select("p.narr, .sh") and not soup.select(".back, [data-page=back]")
    assert not any(s in soup.get_text() for sentences in NARR_P4.values() for s in sentences)


def test_digit_narrative_sentence_is_dropped(made):
    sheet, fs = made["P4"]
    soup = parse(render_sheet(sheet, fs, {"action": ["180만 원을 받으실 수 있습니다."]}, CFG))
    assert soup.select("p.narr") == []


def test_every_num_has_source_and_asof(made):
    for sheet, fs in made.values():
        soup = parse(render_sheet(sheet, fs, None, CFG))
        nums = soup.select("span.num")
        assert nums
        assert all(s.get("data-source") and s.get("data-asof") for s in nums)


def test_no_overflow_p1_to_p5(made):
    for name in ("P1", "P2", "P3", "P4", "P5"):
        sheet, fs = made[name]
        assert check_overflow(render_sheet(sheet, fs, None, CFG)) == [], name


LONG_NARR = {"action": ["먼저 하실 일부터 차근차근 해 두시면 뒤에 받으실 수 있는 지원이 한꺼번에 열립니다. 모르시는 것은 창구에서 물어보세요."],
             "support": ["농협을 거쳐 받는 돈은 올해는 어렵지만 내년에 농협에 파시면 해당될 수 있습니다. 직접 신청하는 돈은 아래 카드를 보세요."],
             "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}


def test_no_overflow_with_two_line_sentences(made):
    """한마디로 칸의 설명 문장이 두 줄씩이어도 앞면이 한 장에 든다(자리가 모자라면 문장을 뒷면으로 내려서). 설명 문장이 없는 종이와 카드·숫자가 같다."""
    for name in ("P1", "P2", "P3", "P4", "P5", "T1", "T2"):
        sheet, fs = made[name]
        said = render_sheet(sheet, fs, LONG_NARR, CFG)
        assert check_overflow(said) == [], name
        plain = render_sheet(sheet, fs, None, CFG)
        nums = lambda html: [(s.get("data-source"), s.text) for s in parse(html).select(".front span.num")]
        assert nums(said) == nums(plain), name


def test_demo_badge_on_the_front(made):
    sheet, fs = made["P4"]
    assert render_sheet(sheet, fs, None, CFG_DEMO).count("기준일 2026-11-13") >= 1
    assert "(시연)" not in render_sheet(sheet, fs, None, CFG_DEMO)
    assert "(시연)" not in render_sheet(sheet, fs, None, CFG)


def test_header_shows_service_name(made):
    sheet, fs = made["P4"]
    assert CFG.service_name == "제주 농돈"
    assert "제주 농돈" in render_sheet(sheet, fs, None, CFG)


def test_empty_sheet_renders_banner_and_has_no_calendar_or_back(made):
    sheet, fs = made["T1"]
    soup = parse(render_sheet(sheet, fs, None, CFG))
    assert "다 챙기고 계세요" in soup.get_text()
    assert "지키실 돈" in soup.get_text()
    assert not soup.select(".front .cal, .back") and len(soup.select(".sheet")) == 1      # 달력 세 칸도 뒷면도 없다


def test_filled_sheet_has_the_disclaimer_and_one_face(made):
    sheet, fs = made["P4"]
    soup = parse(render_sheet(sheet, fs, None, CFG))
    assert not soup.select(".front .cal, .back") and len(soup.select(".sheet")) == 1
    assert "공문서가 아니에요" in soup.select_one(".front .foot").text


def test_no_safe_filter_on_narrative():
    root = Path(__file__).resolve().parents[2] / "app" / "ui" / "templates"
    for name in ("sheet_front.html", "sheet_front_empty.html", "_sheet_macros.html"):
        assert "|safe" not in (root / name).read_text(encoding="utf-8").replace(" ", ""), name


def test_narrative_is_escaped(made):
    sheet, fs = made["P4"]
    html = render_sheet(sheet, fs, {"action": ["<script>x</script>"]}, CFG)
    assert "<script>x</script>" not in html


def test_overflow_check_flags_synthetic_40_line_front():
    # 16pt 줄 43개 = 상한(FRONT_LINE_LIMIT 41.0)을 넘는 합성 앞면
    rows = "".join(f'<div class="line pt16" data-sec="C">줄</div>' for _ in range(43))
    html = f'<section class="sheet front">{rows}</section><section class="sheet back" data-page="back"></section>'
    msgs = check_overflow(html)
    assert msgs and all(isinstance(m, str) for m in msgs)
    assert any("종이" in m and "너무 길어요" in m for m in msgs)


def test_overflow_check_flags_section_cap():
    rows = "".join('<div class="it line pt16" data-sec="A">줄</div>' for _ in range(3))
    html = f'<section class="sheet front">{rows}</section><section data-page="back"></section>'
    assert any("급한 것" in m for m in check_overflow(html))


def test_overflow_check_flags_more_than_the_card_cap():
    cards = "".join('<div class="cd line pt16" data-sec="K" data-n="0">카드</div>' for _ in range(CARD_CAP + 1))
    html = f'<section class="sheet front empty cardsheet">{cards}</section><section data-page="back"></section>'
    assert any("카드" in m and "상한" in m for m in check_overflow(html))         # 빈 종이의 상자 수 한도(결과가 있는 종이는 쪽이 이어져 곳 수 한도가 없다)


def test_card_front_is_one_page_and_has_no_conclusion_box(made, bundle):
    for name in ("P1", "P2", "P3", "P4", "P5"):
        sheet, fs = made[name]
        html = render_sheet(sheet, fs, NARR_P4, CFG, programs=bundle.programs)
        soup = parse(html)
        assert not soup.select(".back") and len(soup.select(".sheet.front")) == (2 if name == "P5" else 1), name        # 뒷면 없음 · 한 쪽(시험용 P5 는 줄이 많아 이어진다. 시연 P5 는 test_paper_v2 가 한 쪽임을 본다)
        assert soup.select(".front .pg.rrw"), name
        assert check_overflow(html) == [], name
        assert not soup.select(".front .sh, .front .s1, .front .narr"), name                   # 주황 결론 상자·AI 문장은 종이에 없다


def test_print_css_has_page_rules():
    css = (Path(__file__).resolve().parents[2] / "app" / "ui" / "static" / "print.css").read_text(encoding="utf-8")
    assert "@page" in css and "A4" in css and "break-after" in css and "@media print" in css


# --- 수정 1차(리뷰) -------------------------------------------------------------------------------

def _visible_text_without_nums(html: str) -> str:
    soup = parse(html)
    for tag in soup.select("style, span.num"):
        tag.decompose()
    return soup.get_text(" ")


@pytest.mark.parametrize("name", ["P1", "P2", "P3", "P4", "P5", "T1", "T2"])
@pytest.mark.parametrize("cfg", [CFG, CFG_DEMO], ids=["plain", "demo"])
def test_no_digit_outside_num_span(made, name, cfg):
    sheet, fs = made[name]
    left = _visible_text_without_nums(render_sheet(sheet, fs, NARR_P4, cfg))
    assert not re.search(r"[0-9①-⑳]", left), re.findall(r".{12}[0-9①-⑳].{12}", left)[:5]


def test_documents_line_is_not_printed_but_the_window_tells_them(made):
    """종이 앞면에는 '가져오실 서류' 줄이 없다(화면과 같다). 서류는 '가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요' 한 줄이 맡는다."""
    sheet, fs = made["P1"]
    front = parse(render_sheet(sheet, fs, None, CFG)).select_one(".front").get_text(" ")
    assert "신규: 경작사실확인서" not in front
    assert "가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요" in " ".join(front.split())


def test_disaster_detail_printed(bundle):
    fs = make_fs({**P2_KWARGS, "flags": {"disaster_damage": True, "direct_payment_education": "Y"}}, bundle, AS_OF)
    sheet = build_sheet(fs, bundle, AS_OF)
    line = sheet.front.sections["A"][0]
    assert line.detail
    text = parse(render_sheet(sheet, fs, None, CFG)).select_one(".front").get_text("")
    assert "".join(line.detail.split())[:20] in "".join(text.split())


def test_subtitle_from_config_on_both_fronts(made):
    cfg = load_config([])
    assert cfg.service_subtitle == "농가가 받을 돈, 한 장으로"
    for name in ("P4", "T1"):
        sheet, fs = made[name]
        html = render_sheet(sheet, fs, None, cfg)
        assert "농가가 받을 돈, 한 장으로" in html
        assert "어르신께 해당될 수 있는 돈과 보험" not in html


def test_title_uses_korean_crop_label(made):
    sheet, fs = made["T1"]
    html = render_sheet(sheet, fs, None, CFG, crop_labels={"감귤_노지": "노지감귤"})
    assert "노지감귤" in parse(html).select_one("h1").text and "감귤_노지" not in parse(html).select_one(".front").text
    assert "감귤_노지" in parse(render_sheet(sheet, fs, None, CFG)).select_one("h1").text   # 표가 없으면 코드 그대로


def test_badge_not_smaller_than_13pt():
    css = (Path(__file__).resolve().parents[2] / "app" / "ui" / "static" / "print.css").read_text(encoding="utf-8")
    assert not re.search(r"font-size:\s*12pt", css)


def test_no_overflow_empty_sheets(made):
    for name in ("T1", "T2"):
        sheet, fs = made[name]
        assert check_overflow(render_sheet(sheet, fs, None, CFG)) == [], name


def test_overflow_counts_borders_and_detail():
    rows = "".join('<div class="it line pt16" data-sec="B">줄</div>' for _ in range(7))
    ok = f'<section class="sheet front">{rows}</section><section data-page="back"></section>'
    assert check_overflow(ok) == []
    many = "".join('<div class="line pt16" data-sec="C">줄</div>' for _ in range(33))
    box = "".join('<div class="pl line pt16" data-sec="F">줄</div>' for _ in range(1))
    html = f'<section class="sheet front">{many}{rows}{box}</section><section data-page="back"></section>'
    assert check_overflow(html)                                      # 테두리·여백 환산으로 35를 넘는다
    detail = '<p class="dt line pt13" data-n="60" data-sec="D">긴 설명</p>'
    assert check_overflow(f'<section class="sheet front">{detail}</section><section data-page="back"></section>')


def test_overflow_is_logged(made, caplog):
    import logging
    sheet, fs = made["P4"]
    big = sheet.model_copy()
    import app.ui.render as r
    orig = r.check_overflow
    r.check_overflow = lambda html, extra=0.0: ["앞면이 너무 깁니다(시험)"]
    try:
        with caplog.at_level(logging.WARNING, logger="app.ui.render"):
            render_sheet(big, fs, None, CFG)
    finally:
        r.check_overflow = orig
    assert any("앞면이 너무 깁니다" in rec.getMessage() for rec in caplog.records)


def test_narrative_slot_keeps_first_sentence_only():
    out = render_mod._narrative_slots({"action": ["첫째 문장입니다.", "둘째 문장입니다."]})
    assert out == {"action": ("첫째 문장입니다.",)}


