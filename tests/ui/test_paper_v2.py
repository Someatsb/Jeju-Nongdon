"""종이 v2(2026-11-14 결과 화면 2차 3절): 종이는 앞면 한 면뿐이고(2026-11-18 뒷면을 없앴다) 결과 화면과 같은 모양(같은 조각·같은 그림·같은 글·같은 순서)이다.
넘침: 줄 높이 어림·글자 단계(0~3)·한 쪽에 안 들 때만 표가 이어진다."""
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.config import load_config
from app.core.sheet import build_sheet
from app.data_layer.tables import load_tables
from app.ui import render
from app.ui.render import (paper_group_lines, pc_wide, CARD_CAP, MORE_MM, check_overflow, front_lines, paper_row_lines,
                           render_sheet, wrap_lines)
from app.ui.result_view import build_view
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS, T2_KWARGS
from factsheet_fixtures import amount, make_fs

CFG = load_config(["--asof", "2026-11-13"])
P4_AMOUNTS = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)
T1_AMOUNTS = (amount("JEJU-FARMER-ALLOW@2026", 900_000, 900_000), amount("NAT-DIRECT-SMALL@2026", 1_300_000, 1_300_000))
NARR = {"action": ["경영체 등록부터 하시면 아래 직불을 받으실 길이 열립니다."],
        "support": ["농협을 거치는 돈은 올해 해당되지 않을 수 있습니다."],
        "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}
LONG_NARR = {"action": ["먼저 하실 일부터 차근차근 해 두시면 뒤에 받으실 수 있는 지원이 한꺼번에 열립니다. 모르시는 것은 창구에서 물어보세요."],
             "support": ["농협을 거쳐 받는 돈은 올해는 어렵지만 내년에 농협에 파시면 해당될 수 있습니다. 직접 신청하는 돈은 아래 카드를 보세요."],
             "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}
TABLES = Path(__file__).resolve().parents[2] / "data" / "tables"
ALL = ("P1", "P2", "P3", "P4", "P5", "T1", "T2")


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_front(html: str):
    """앞면 쪽들(표가 이어지면 둘 이상)의 안쪽을 한 덩어리 `.front` 로 합친 것(2026-11-17: 한 쪽에 안 들어가면 표가 다음 쪽으로 이어진다)."""
    pages = parse(html).select(".sheet.front")
    return BeautifulSoup('<div class="front">' + "".join(p.decode_contents() for p in pages) + "</div>", "html.parser").select_one(".front")


@pytest.fixture(scope="module")
def bundle():
    return load_tables(TABLES, AS_OF)


@pytest.fixture(scope="module")
def made(bundle):
    out = {}
    for name, kw, amts in (("P1", P1_KWARGS, ()), ("P2", P2_KWARGS, ()), ("P3", P3_KWARGS, ()), ("P4", P4_KWARGS, P4_AMOUNTS),
                           ("P5", P5_KWARGS, ()), ("T1", T1_KWARGS, T1_AMOUNTS), ("T2", T2_KWARGS, ())):
        fs = make_fs(kw, bundle, AS_OF, amounts=amts)
        out[name] = (build_sheet(fs, bundle, AS_OF), fs)
    return out


def paper(made, name, narr=None, bundle=None):
    sheet, fs = made[name]
    return render_sheet(sheet, fs, narr, CFG, crop_labels={}, programs=bundle.programs if bundle else ())


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


# ---------------- 앞면: 결과 화면과 같은 두 구역(2026-11-15: 지금 하실 일 · 앞으로 신청할 것) ----------------
def screen_view(made, bundle, name):
    sheet, fs = made[name]
    return build_view(sheet, fs, bundle, AS_OF, None, screen=True)


def test_front_has_check_tip_and_one_box_per_place_and_no_conclusion_box(made, bundle):
    for name in ("P1", "P2", "P3", "P4", "P5"):
        html = paper(made, name, NARR, bundle)
        front = parse_front(html)
        assert not front.select(".sh, .s1, .narr, .know, .know-t"), name              # 주황 결론 상자 · AI 문장 · 알아 두세요 상자는 없다
        assert front.select_one(".chk-tip").get_text(strip=True) == "다녀오면 □에 ✓", name
        assert not front.select(".rh, .rr, .rr-l, .rr-r"), name                      # 옛 좌우 두 칸 머리·줄은 없다
        rows = front.select(".rrw")
        assert len(rows) >= 1 and not front.select(".pb-no"), name                           # 곳 수 한도는 없다(쪽이 이어질 수 있다) · 번호 동그라미는 없다
        assert all(r.select_one(".pc .bx") and r.select_one(".pc .pb-t") for r in rows), name  # 곳마다 소분류 칸에 체크 칸 · 이름
        assert all(r.select_one(".pc-r .pb-rows") for r in rows), name                          # 그 곳의 지원 줄들은 지원 칸에
        assert front.select(".ptb .pz-now .pz-h") and front.select(".ptb .pz-later .pz-h"), name   # 대분류 칸 둘(지금 · 앞으로)이 표 하나 안에
        assert len(front.select(".foot .line")) % 3 == 0 and front.select(".foot .line"), name      # 고정 문장 세 줄(쪽마다)
        assert not front.select("button, a, .rb-edit"), name                         # 화면에만 있는 것(단추·답 고치기)은 없다


def test_front_boxes_say_the_same_in_the_same_order_as_the_screen(made, bundle):
    """같은 값·같은 글·같은 순서: 종이 「지금 하실 일」 묶음의 가실 곳 이름·전화·줄 이름·마감 날짜가 결과 화면(build_view screen=True)의 지금 구역 상자와 같다.
    종이는 줄을 하나도 줄이거나 접거나 뒷면으로 넘기지 않는다(2026-11-17). 번호 동그라미는 없다."""
    for name in ("P1", "P2", "P3", "P4", "P5"):
        view = screen_view(made, bundle, name)
        html = paper(made, name, None, bundle)
        front = parse_front(html)
        rows = front.select(".pg.rrw")
        assert len(rows) == len(view["now_cards"]), name                  # 지금 구역 상자는 하나도 빠지지 않는다
        assert not front.select(".pb-no, .pb-more, .lr-more"), name
        for row, card in zip(rows, view["now_cards"]):
            text = squash(row.get_text())
            if card["head"]:
                assert squash(card["head"]) in text, name
            if card["phone"]:
                assert squash(card["phone"]) in text, name
            shown = [squash(x.get_text()) for x in row.select(".pr-t")]
            screen = [squash(it["title"]) for it in card["rows"]]
            assert shown == screen, (name, shown, screen)                    # 종이 줄 = 화면 줄(같은 순서, 빠진 것 없이)
            for it in card["rows"]:
                if it["text"] and it.get("urgent"):
                    assert squash(re.sub(r"^오늘\s+", "", it["text"])) in text, name        # 급한 줄은 종이에 마감 날짜가 적힌다('오늘'은 뺀다)
                for note in it["notes"]:
                    assert squash(note) in text, (name, note)                # 덧말도 빠지지 않는다
            assert "is-first" not in row["class"] and row.select_one(".pb-tag") is None, name       # '먼저 하실 일'·'언제든 신청할 수 있어요' 딱지는 화면처럼 없다


def test_front_has_the_two_zone_titles_and_the_date_it_is_based_on(made, bundle):
    for name in ("P1", "P2", "P3", "P4", "P5"):
        front = parse_front(paper(made, name, None, bundle))
        titles = list(dict.fromkeys(squash(z.get_text(strip=True)) for z in front.select(".zt-h")))          # 이어진 쪽은 구역 제목을 다시 단다
        assert titles == ["지금하실일", "앞으로신청할것"], (name, titles)
        assert squash(front.select_one(".zt-d").get_text()) == "11월13일기준", name         # 종이는 며칠 뒤에도 읽으니 '지금'이 언제인지 적는다
        assert front.select_one(".ptb-note .chk-tip").get_text(strip=True) == "다녀오면 □에 ✓", name
        assert squash(front.select_one(".ptb-note").get_text()).startswith("지금=11월13일기준"), name        # 표 바로 위 한 줄: 지금 = ○월 ○일 기준 · 다녀오면 □에 ✓
        zone = front.select_one(".ptb").get_text(" ")
        assert "먼저 하실 일" not in zone and "지금 신청할 수 있어요" not in zone, name            # 상자 딱지는 없다(구역 제목이 그 뜻이다)


def test_front_later_lines_are_the_screen_later_lines_in_month_order(made, bundle):
    """「앞으로 신청할 것」은 화면의 앞으로 구역과 같은 줄·같은 순서이고, 하나도 빠지지 않는다('외 ○가지' 줄은 없다). 상자·번호는 없다."""
    for name in ("P1", "P2", "P3", "P4", "P5"):
        view = screen_view(made, bundle, name)
        later = parse_front(paper(made, name, None, bundle))
        shown = [squash(x.get_text()) for x in later.select(".pz-later .lr-t")]
        screen = [squash(r["title"]) for r in view["later_rows"]]
        assert shown == screen, (name, shown, screen)
        assert not later.select(".lr-more, .lm") and "뒷면에있어요" not in squash(later.select_one(".ptb").get_text()), name
        assert not later.select(".pz-later .pbox, .pz-later .pb-no, .pz-later svg"), name                  # 상자·번호·그림이 없다
        assert len(later.select(".pz-later .lr .bx")) == len(shown), name                                   # 줄마다 □ 하나


def test_every_screen_table_line_is_on_the_front_and_the_far_lines_are_counted(made, bundle):
    """줄은 사라지지 않는다: 화면 표의 지금·앞으로 줄은 모두 종이에 있고, 넉 달 밖 줄(화면 직원용 창에 이름이 있다)은 종이에서 '그 뒤에도 N가지' 한 줄로 센다."""
    for name in ("P1", "P2", "P3", "P4", "P5"):
        view = screen_view(made, bundle, name)
        front = squash(parse_front(paper(made, name, None, bundle)).get_text())
        titles = [it["title"] for c in view["now_cards"] for it in c["rows"] if it["kind"] == "do" or it["title"] not in ("받을 수 있는 돈", "이것을 하시면 받을 수 있는 돈")]
        titles += [r["title"] for r in view["later_rows"]]
        for title in titles:
            assert squash(re.sub(r"\s*\(농관원\)$", "", title)) in front, (name, title)
        far = view["later_far"]
        assert (squash(far["paper_text"]) in front) if far else "그뒤에도" not in front, name


def test_urgent_line_shows_the_deadline_date_as_a_pill_not_days_left(made, bundle):
    front = parse_front(paper(made, "P3", None, bundle))
    pill = front.select_one(".pr-pill")
    assert pill is not None and squash(pill.get_text()) == "오늘까지(11월13일)"                 # 마감이 기준일 당일이면 오늘이 마감임이 보이고, 며칠 뒤에 읽어도 날짜가 남는다
    text = front.get_text()
    assert "일 남음" not in text                                                                 # 종이는 며칠 뒤에도 읽는다


def test_empty_now_zone_says_so_in_one_line(made, bundle, monkeypatch):
    """지금 구역이 비면 상자 대신 한 줄(화면과 같은 말). 앞으로 구역은 그대로 있다."""
    orig = render.split_screen

    def no_now(*a, **k):
        out = orig(*a, **k)
        return out | {"now_boxes": [], "now_cards": []}
    monkeypatch.setattr(render, "split_screen", no_now)
    front = parse_front(paper(made, "P1", None, bundle))
    assert not front.select(".rrw, .pbox")
    assert front.select_one(".zempty").get_text(strip=True) == "지금 바로 하실 일은 없어요. 아래 달에 신청하시면 돼요."
    assert [squash(z.get_text()) for z in front.select(".zt-h")] == ["지금하실일", "앞으로신청할것"]


def test_front_box_has_no_side_by_side_columns_and_no_filler_word(made, bundle):
    for name in ("P1", "P2", "P3", "P4"):
        front = parse_front(paper(made, name, None, bundle))
        assert not front.select(".rt-act") and "신청하기" not in front.get_text(), name       # 채움말이 없다
        for box in front.select(".pbox"):
            assert box.select("ul.pb-rows > li.pr"), name                                      # 받는 것이 한 줄에 하나씩
            assert not box.select(".pr .pr .pr"), name


def test_front_pictures_are_hidden_from_readers_and_have_text_beside(made, bundle):
    for name in ("P1", "P4"):
        row = parse(paper(made, name, None, bundle)).select_one(".front .pg.rrw")
        svgs = row.select("svg")
        assert len(svgs) >= 3                                                                         # 가실 곳 · 전화 · 언제 달력 그림
        assert all(s.get("aria-hidden") == "true" for s in svgs)
        assert row.select_one(".pc .pc-pic svg") and not row.select(".pb-pic")                        # 소분류 칸의 곳 이름 옆에 곳 그림(화면 상자 띠와 같은 그림)


def test_paper_front_has_no_numbers_and_no_know_box(made, bundle):
    for name in ("P1", "P2", "P3", "P4"):
        front = parse_front(paper(made, name, None, bundle))
        assert not front.select(".pb-no"), name
        assert not front.select(".know, .know b.cnt") and "그 밖에:" not in front.get_text(), name       # 알아 두세요 상자는 없고 '그 밖에: N …' 줄도 없다(앞으로 구역이 대신한다)


def test_paper_says_current_notices_not_new_notices(made, bundle):
    sheet, fs = made["P1"]
    match = {"lines": [{"name": "시설현대화 지원사업", "why": "감귤 농사를 지으셔서요", "period": "11월 23일까지", "where": "지역 농·감협", "ask": ["바꾸고 싶은 시설이 있으신지요?"]}],
             "more_names": ["가", "나"]}
    html = render_sheet(sheet, fs, None, CFG, crop_labels={}, match=match, programs=bundle.programs)
    soup = parse(html)
    zone = squash(soup.select_one(".pz-now").get_text())
    assert "시설현대화지원사업" in zone and "11월23일까지" in zone                           # 「지금 하실 일」 구역에 공고 이름 · 마감 날짜 줄(자리가 모자라면 글자 단계로 맞춘다)
    assert "지금접수중인공고1개가" not in squash(soup.get_text()) and not soup.select(".back")
    assert "새로 나온 공고" not in html and "그 밖의 새 공고" not in html


def test_paper_box_estimate_tracks_band_wrapping_and_hidden_line():
    base = {"head": "지역농협", "head_go": True, "phone": None, "tel_note": None, "where": None, "hidden_n": 0, "no_n": "1", "pill": None, "now": False,
            "todo": [], "gets": [{"title": "농어업인 건강보험료 지원", "text": "상시 신청", "text_when": True, "pre": "", "amt": "", "whens": ["상시 신청"], "notes": [], "check": False, "unlocks_n": 0}]}
    assert paper_row_lines({**base, "now": True, "phone": "1577-1000"}) >= paper_row_lines(base)
    assert paper_row_lines({**base, "hidden_n": 2, "hidden_names": ["가", "나"]}) > paper_row_lines(base)
    pre = {**base, "gets": [{**base["gets"][0], "pre": "하시고 조건 맞으면", "amt": "연 약 180만~258만 원", "text": "하시고 조건 맞으면 연 약 180만~258만 원"}]}
    plain_amt = {**base, "gets": [{**base["gets"][0], "amt": "15만 원", "text": "15만 원"}]}
    assert paper_row_lines(pre) > paper_row_lines(plain_amt)           # 앞 말이 붙은 금액은 이름 아래 줄로 내려간다


def test_front_tail_lines_and_tags(made):
    front = parse(paper(made, "P4", NARR)).select_one(".front").get_text(" ")
    assert "가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요" in " ".join(front.split())         # 표 아래 줄(언제나)
    for word in ("알아 두세요", "올해는 어려운 것", "영농도우미", "재해 피해", "금액은 올해 기준이에요", "조건은 뒷면", "알아 두실 것이"):
        assert word not in front, word
    assert "지금하실일" in squash(front) and "앞으로신청할것" in squash(front)
    assert "확인할 조건 있음" not in front and "조건을 확인해야 해요" not in front                      # 화면과 같은 말로


def test_front_head_line_has_crop_place_and_date(made):
    front = parse(paper(made, "P4")).select_one(".front")
    assert "제주 농돈" in front.select_one("h1").get_text()
    assert "기준일 2026-11-13" in front.select_one(".meta").get_text()


def test_empty_paper_uses_the_same_frame(made):
    front = parse(paper(made, "T1", LONG_NARR)).select_one(".front")
    assert "cardsheet" in front["class"] and "v2" in front["class"]
    assert front.select_one(".sh .s1") and front.select_one(".chk-tip") and front.select(".rrw") and front.select(".pbox")
    assert "지키실 돈" in front.get_text()
    assert "찾지 못했어요" in front.get_text()                  # 해요체


# ---------------- 앞면 넘침 ----------------
def test_front_fits_with_long_sentences_and_keeps_numbers_the_same(made, bundle):
    for name in ALL:
        said = paper(made, name, LONG_NARR, bundle)
        assert check_overflow(said) == [], name
        plain = paper(made, name, None, bundle)
        nums = lambda html: [(s.get("data-source"), s.text) for s in parse(html).select(".front span.num")]
        assert nums(said) == nums(plain), name                # 설명 문장이 있어도 상자·앞으로 줄·숫자는 같다


def test_row_estimate_grows_with_text_and_counts_first_row_pill():
    base = {"head": "지역농협", "head_go": True, "phone": None, "tel_note": None, "act": "신청하기", "where": None, "hidden_n": 0, "wide": False,
            "first": False, "todo": [], "gets": [{"title": "농어업인 건강보험료 지원", "text": "상시 신청", "text_when": True, "whens": [], "notes": [], "check": True,
                                                  "unlocks_n": 0}]}
    longer = {**base, "head": "국립농산물품질관리원 제주지원(농관원) 제주특별자치도 농지 소재지 읍면동", "phone": "1644-8778"}
    assert paper_row_lines(longer) > paper_row_lines(base)
    assert paper_row_lines({**base, "pill": "먼저 하실 일"}) > paper_row_lines(base)
    wide = {**base, "wide": True, "gets": []}
    assert paper_row_lines(wide) > 0


def test_front_line_estimate_counts_row_wrappers():
    html = '<section class="sheet front cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="9.5">줄</div>' * 3 + '</section>'
    assert 28 < front_lines(html) < 31                         # 3 × 9.5 + 쪽 여백
    assert any("너무 길어요" in m for m in check_overflow(html.replace("9.5", "13")))
    over = '<section class="sheet front cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="1">줄</div>' * (CARD_CAP + 1) + '</section>'
    assert not any("상한" in m for m in check_overflow(over))                          # 결과가 있는 종이는 곳 수 한도가 없다(쪽이 이어진다)
    one = '<section class="sheet front cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="13">줄</div>' * 3 + '</section>'
    assert any("너무 길어요" in m for m in check_overflow(one))
    split = ('<section class="sheet front cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="13">줄</div>' + '</section>') * 2
    assert not check_overflow(split)                                                   # 같은 줄이라도 두 쪽에 나뉘면 쪽마다 한도를 본다
    empty = '<section class="sheet front empty cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="1">줄</div>' * (CARD_CAP + 1) + '</section>'
    assert any("상한" in m for m in check_overflow(empty))                              # 빈 종이는 상자 수 한도가 그대로


def test_line_limit_follows_the_text_size_tier():
    """글자 단계(data-tier)마다 줄 수 상한이 다르다(TIER_LIMIT). 단계가 없는 종이(빈 종이)는 CARD_LINE_LIMIT."""
    row = lambda n: '<div class="rrw line pt16" data-sec="Rr" data-n="%s">줄</div>' % n
    for tier, limit in enumerate(render.TIER_LIMIT):
        page = lambda n: '<section class="sheet front cardsheet v2" data-page="front" data-tier="%d">%s</section>' % (tier, row(n))
        room = limit - render.PAGE_PAD_LINES
        assert not check_overflow(page(room - 0.2)) and check_overflow(page(room + 0.2)), tier
    assert len(render.TIER_LIMIT) == len(render.TIER_K) == 4


def test_front_shows_the_whole_now_zone_and_the_whole_later_zone(made, bundle):
    for name in ("P1", "P2", "P3", "P5"):
        view = screen_view(made, bundle, name)
        front = parse_front(paper(made, name, None, bundle))
        assert len(front.select(".pg.rrw")) == len(view["now_cards"]), name                     # 지금 구역은 모두
        assert len(front.select(".pz-later .lr")) == len(view["later_rows"]), name              # 앞으로 구역도 모두(접거나 뒷면으로 넘기지 않는다)
    assert len(parse_front(paper(made, "P1", None, bundle)).select(".lr")) >= 3


def test_front_steps_the_text_size_down_before_it_runs_onto_a_second_page(made, bundle):
    """한 쪽에 안 들면 글자를 단계로 줄이고(data-tier 0 → 1 → 2 → 3) 그래도 안 들 때만 표가 다음 쪽으로 이어진다. 이어진 쪽은 머리 한 줄이 있고 표 아래 줄들은 끝 쪽에 온다."""
    seen = set()
    for name in ("P1", "P2", "P3", "P4", "P5"):
        html = paper(made, name, None, bundle)
        pages = parse(html).select(".sheet.front")
        tiers = {p["data-tier"] for p in pages}
        assert len(tiers) == 1, name
        seen.add(len(pages))
        assert not check_overflow(html), name
        if len(pages) > 1:
            assert next(iter(tiers)) == "3", name                                                 # 가장 작은 단계로도 안 들 때만 이어진다
            assert all(p.select_one(".cont-h") and "이어서" in p.select_one(".cont-h").get_text() for p in pages[1:]), name
            assert not pages[0].select(".keepl") and pages[-1].select(".keepl"), name           # 표 아래 줄들은 끝 쪽
        assert all(p.select(".foot") for p in pages), name
    assert 1 in seen


def test_estimates_match_measured_heights_within_a_few_px():
    """글자 폭 어림이 맞는지(MORE_MM: 가실 곳 상자 아래 '외 ○가지: …' 줄은 빈 종이에만 있다): 짧은 줄은 한 줄, 긴 줄은 두 줄."""
    assert wrap_lines("외 2가지: 제주형 가격안정관리제(당근) · 당근 농작물보험", 14, MORE_MM) == 1
    assert wrap_lines("외 2가지: 제주형 가격안정관리제(브로콜리) · 브로콜리 농작물보험 · 노지감귤(온주) 농작물보험 · 월동무 농작물보험", 14, MORE_MM) == 2


# ---------------- 뒷면이 없다(2026-11-18) ----------------
def test_front_has_no_hidden_or_folded_lines_and_says_nothing_about_a_back(made, bundle):
    """종이에는 '외 ○가지 · …에 있어요' 줄이 없고(화면의 줄은 전부 앞면 표에 있다), 달마다 한 줄로 접은 줄도 없다. '뒷면' 글은 종이 어디에도 없다."""
    for name in ALL:
        html = paper(made, name, NARR, bundle)
        assert "뒷면" not in html and "양면" not in html, name
        if parse(html).select_one(".sheet.front.empty"):
            continue                                                          # 이미 다 받고 있는 농가의 종이(빈 종이)는 틀을 바꾸지 않는다
        front = parse_front(html)
        text = front.get_text(" ", strip=True)
        assert not re.search(r"외\s*\d+\s*가지(?!를)", text) and "알아 두실 것이" not in text, name     # '이것을 해야 … 외 2가지를 받을 수 있어요'는 화면 글이다
        assert not front.select(".lm, .lm-i, .pb-more, .lr-more"), name


def test_all_numbers_on_v2_paper_carry_source_and_date(made):
    for name in ALL:
        soup = parse(paper(made, name, NARR))
        assert all(s.get("data-source") and s.get("data-asof") for s in soup.select("span.num")), name


# ---------------- 글자 크기·색 ----------------
CSS = (Path(__file__).resolve().parents[2] / "app" / "ui" / "static" / "print.css").read_text(encoding="utf-8")


def v2_front_block() -> str:
    return CSS[CSS.index("---------- 종이 v2"):CSS.index("---------- 화면 미리보기")]


def test_front_v2_body_text_is_at_least_14pt_and_amounts_18pt():
    block = v2_front_block()
    sizes = [(m.group(1), float(m.group(2))) for m in re.finditer(r"(\.v2[^{]*)\{[^}]*?font-size:\s*([\d.]+)pt", block)]
    assert sizes
    small = [(sel.strip(), pt) for sel, pt in sizes if pt < 14]
    assert small == [], small
    assert re.search(r"\.v2 \.pr-m \{[^}]*font-size: (?:1[89]|2\d)pt", block)          # 금액 18pt 이상
    assert re.search(r"\.v2 \.sh \.s1 \{[^}]*font-size: 22pt", block)


def test_paper_uses_one_accent_and_text_stays_near_black_and_meaning_has_borders():
    block = v2_front_block()                                                 # 색(2026-11-17 사장 지시 · color2): 글자는 먹색, 줄·테두리는 검정이 아니라 청록·모래색, 대분류 칸은 지금 = 옅은 주황 · 앞으로 = 옅은 청록
    assert "--ink: #1c1916" in block                                         # 글자는 검정에 가깝게
    assert re.search(r"\.v2 \.ptb \{[^}]*border: 2pt solid var\(--sea\)", block) and re.search(r"\.v2 \.pz \+ \.pz \{[^}]*border-top: 2\.5pt solid var\(--sea\)", block)   # 표 바깥 테두리 하나 · 구역 사이 굵은 줄(청록)
    assert re.search(r"\.v2 \.pz-h \{[^}]*background: var\(--tang-soft\); color: var\(--ink\)", block)       # 지금 하실 일 칸: 옅은 주황 바탕 + 먹색 글자(색이 빠져도 읽힌다)
    assert re.search(r"\.v2 \.pz-later \.pz-h \{[^}]*background: var\(--sea-soft\)", block)                    # 앞으로 신청할 것 칸: 옅은 청록 바탕
    assert "--tang-soft: #FFE6BF" in block and "--sand: #B8A98A" in block
    assert re.search(r"\.v2 \.pz-b > \* \+ \* \{[^}]*solid var\(--sand\)", block)                              # 곳(달) 사이 줄은 모래색
    assert re.search(r"\.v2 \.pb-tag \{[^}]*background: #fff; color: var\(--ink\); border: 1\.2pt solid var\(--sea\)", block)      # 딱지는 글로 말한다(색에 기대지 않음)
    assert "--tint" not in block


def test_typesheet_uses_the_same_frame():
    path = Path(__file__).resolve().parents[2] / "app" / "ui" / "templates" / "typesheet_doc.html"
    text = path.read_text(encoding="utf-8")
    assert 'class="sheet front v2"' in text and "_art.html" in text and "m.head()" in text and "m.foot_lines" in text


# ---------------- 앞면 표(2026-11-17 사장 지시): 대분류 | 소분류 | 지원 ----------------
def test_front_is_one_table_with_zone_column_place_or_month_column_and_support_column(made, bundle):
    """「지금 하실 일」·「앞으로 신청할 것」이 표 하나(.ptb)에 묶인다: 대분류 칸(.pz-h) | 소분류 칸(가실 곳 .pc · 때 .lg-when) | 지원 칸(.pc-r · .lg-rows)."""
    for name in ("P1", "P2", "P3", "P4", "P5"):
        front = parse_front(paper(made, name, None, bundle))
        table = front.select_one(".ptb")
        assert table is not None and len(front.select(".ptb")) >= 1, name
        now, later = table.select_one(".pz-now"), table.select_one(".pz-later")
        assert now and later and now.select_one(".pz-h") and later.select_one(".pz-h"), name
        for g in now.select(".pg.rrw"):
            assert [c.get("class")[0] for c in g.find_all(recursive=False)][:2] == ["pc", "pc-r"], name        # 소분류 칸 | 지원 칸
        for g in later.select(".lg"):
            assert [c.get("class")[0] for c in g.find_all(recursive=False)][:2] == ["lg-when", "lg-rows"], name   # 때 | 지원 칸
        assert not front.select(".rrows, .lrows, .zt"), name                                                     # 옛 따로따로 구역 틀은 없다


def test_front_has_no_conclusion_sentence_even_when_the_ai_wrote_one(made, bundle):
    for name in ("P1", "P2", "P4"):
        sheet, fs = made[name]
        said = render_sheet(sheet, fs, NARR, CFG, crop_labels={}, programs=bundle.programs)
        plain = render_sheet(sheet, fs, None, CFG, crop_labels={}, programs=bundle.programs)
        assert said == plain, name                                                              # AI 문장이 있든 없든 종이는 같다
        assert not parse_front(said).select(".sh, .narr"), name


def test_group_estimate_grows_with_rows_and_long_place_names_get_the_wide_layout():
    base = {"head": "건강보험공단 지사", "phone": "1577-1000", "tel_note": None, "where": None, "hidden_n": 0, "no_n": "1", "pill": None, "now": False,
            "rows": [{"kind": "get", "title": "농어업인 건강보험료 지원", "text": "", "text_when": False, "pre": "", "amt": "", "whens": ["언제든 신청할 수 있어요"],
                      "notes": [], "place_notes": [], "unlocks_n": 0, "unlock_text": "", "urgent": ""}]}
    two = {**base, "rows": base["rows"] * 2}
    assert paper_group_lines(two) > paper_group_lines(base) > 0                                   # 줄이 늘면 높이도 는다
    assert paper_group_lines({**two, "hidden_n": 2, "hidden_names": ["가", "나"]}) > paper_group_lines(two)
    assert pc_wide("농산물품질관리원(농관원) 제주지원") and not pc_wide("건강보험공단 지사") and not pc_wide("농협")     # 칸보다 넓은 낱말이 있으면 번호·체크 칸을 위로


def test_front_long_place_name_puts_the_marks_on_a_row_above_the_name(made, bundle):
    soup = parse(paper(made, "P4", None, bundle))
    wide = [g for g in soup.select(".front .pg.rrw") if "농산물품질관리원" in g.get_text()]
    assert wide and all("is-wide" in g.select_one(".pc")["class"] for g in wide)
    assert all(not g.select_one(".pc")["class"] == ["pc", "is-wide"] or g.select_one(".pc .pb-t wbr") for g in wide)      # '(' 앞에서 줄을 바꿀 수 있게



def test_text_size_tiers_are_18_15_then_16_14_then_15_13_then_14_12_and_never_smaller():
    css = (Path(render.__file__).parent / "static" / "print.css").read_text(encoding="utf-8")
    base = re.search(r"\.v2 \.ptb \{ --tn: ([\d.]+)pt; --td: ([\d.]+)pt;", css)
    tiers = [re.search(r'\.v2\[data-tier="%d"\] \.ptb \{ --tn: ([\d.]+)pt; --td: ([\d.]+)pt;' % i, css) for i in (0, 2, 3)]
    assert [tuple(map(float, m.groups())) for m in (tiers[0], base, *tiers[1:])] == [(18, 15), (16, 14), (15, 13), (14, 12)]
    assert len(render.TIER_K) == 4 and render.TIER_K[1] == 1.0 and list(render.TIER_K) == sorted(render.TIER_K, reverse=True)


# ---------------- 2026-11-18 사장 결정: 앞으로 신청할 것 = 넉 달 안만 · 종이 = 한 장 한 면 ----------------
@pytest.fixture(scope="module")
def demo(bundle):
    """시연 농가 다섯(data/replay/demo_inputs.json: 재생과 같은 입력). {이름: (sheet, fs)}."""
    import json

    from app.core.models import FarmProfile
    from app.core.pipeline import build_fact_sheet
    from app.data_layer.snapshot import load_snapshot
    from app.ui.forms import to_profile
    snap = load_snapshot(CFG.snapshot_dir, CFG.as_of, crops=bundle.crops)
    data = json.loads((Path(__file__).resolve().parents[2] / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
    out = {}
    for key in ("P1", "P2", "P3", "P4", "P5"):
        prof = to_profile(data[key]["form"])
        prof = FarmProfile.model_validate({**prof.model_dump(), "already_receiving": set(data[key].get("already") or ())})
        fs = build_fact_sheet(prof, bundle, snap, CFG.as_of, "test", demo_asof=True)
        out[key] = (build_sheet(fs, bundle, CFG.as_of), fs)
    return out


def demo_paper(demo, bundle, name, match=None):
    sheet, fs = demo[name]
    return render_sheet(sheet, fs, None, CFG, crop_labels={c.crop_code: c.label for c in bundle.crops}, programs=bundle.programs, match=match)


def demo_view(demo, bundle, name):
    sheet, fs = demo[name]
    return build_view(sheet, fs, bundle, AS_OF, None, screen=True)


def test_the_five_demo_farms_are_one_page_each_and_nothing_is_cut_or_overlapping(demo, bundle):
    """다섯 시연 농가는 모두 앞면 한 쪽: 쪽이 이어지지 않고, 어림 검사를 통과하고, 맨 아래 안내 글 세 줄이 있다. 뒷면은 없다(실제 PDF 쪽 수는 scripts/front_measure.py 로 센다)."""
    for name in demo:
        html = demo_paper(demo, bundle, name)
        soup = parse(html)
        pages = soup.select(".sheet.front")
        assert len(pages) == 1 and not soup.select(".back, [data-page=back], .cont-h"), name
        assert check_overflow(html) == [], name
        assert len(pages[0].select(".foot .line")) == 3 and pages[0].select(".keepl"), name
        assert pages[0]["data-tier"] in ("0", "1", "2", "3"), name


def test_no_back_word_anywhere_on_any_paper(demo, bundle, made):
    """종이(CSS 포함 전체 글)에 '뒷면'·'양면'이라는 말이 없다: 시연 농가 다섯 · 시험용 일곱(빈 종이 포함)."""
    for name in demo:
        assert "뒷면" not in demo_paper(demo, bundle, name), name
    for name in ALL:
        html = paper(made, name, NARR, bundle)
        assert "뒷면" not in html and "양면" not in html, name


def test_paper_has_no_back_template_or_back_function():
    root = Path(render.__file__).parent
    assert not (root / "templates" / "sheet_back.html").exists()
    for gone in ("check_back_overflow", "back_height_px", "BACK_LIMIT_PX", "back_rows", "BACK_TIERS"):
        assert not hasattr(render, gone), gone
    assert ".v2b" not in CSS and ".sheet.back" not in CSS


def test_front_has_the_know_lines_without_a_box(demo, bundle):
    """표 아래에는 상자·제목 없이 줄만: '가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요'(언제나) + 해당 농가의 '끊기지 않게 …' 줄 전부."""
    many = 0
    for name in demo:
        view = demo_view(demo, bundle, name)
        soup = parse(demo_paper(demo, bundle, name))
        assert not soup.select(".know, .know-t"), name
        lines = [" ".join(p.get_text(" ").split()) for p in soup.select(".front .keepl p")]
        assert lines and lines[0] == "가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요", (name, lines)
        keeps = [l for l in lines if l.startswith("끊기지 않게")]
        assert len(keeps) == len(view["keeps"]), (name, keeps)
        for k in view["keeps"]:
            assert any(squash(k["title"] + ":" + k["text"]) in squash(l) for l in keeps), (name, k)
        many += bool(keeps)
        text = " ".join(lines)
        for gone in ("조건은", "금액은 올해 기준", "알아 두실 것이", "접수 중인 공고"):
            assert gone not in text, (name, gone)
    assert many >= 1                                                                      # 끊기지 않게 줄이 있는 농가가 있다(P3 · P5)


def test_front_place_cells_have_the_same_picture_as_the_screen(demo, bundle):
    """가실 곳 칸의 이름 옆에 화면 상자 띠와 같은 그림(art.ic(icon_name) / art.place_icon(icon))이 색 그대로 있다."""
    art = render._env.get_template("_art.html").module
    for name in demo:
        view = demo_view(demo, bundle, name)
        groups = parse_front(demo_paper(demo, bundle, name)).select(".pz-now .pg.rrw")
        assert len(groups) == len(view["now_cards"]) >= 1, name
        for g, c in zip(groups, view["now_cards"]):
            want = art.ic(c["icon_name"], "ic ic-p") if c["icon_name"] else art.place_icon(c["icon"], "ic ic-p")
            pic = g.select_one(".pc .pc-pic svg")
            assert pic is not None and pic.get("aria-hidden") == "true", name
            assert squash(str(pic)) == squash(str(parse(str(want)).svg)), (name, c["head"])


def test_ai_notice_rows_have_the_screen_picture_and_sit_where_the_screen_puts_them(demo, bundle):
    """지금 접수 중인 공고(AI가 읽은 공고) 줄: 화면과 같은 곳 그림, 자리는 '언제든 신청하는 줄만 든 첫 상자' 바로 앞(없으면 맨 끝). 화면 순서는 그대로다."""
    from app.ui.result_view import notice_box
    art = render._env.get_template("_art.html").module
    match = {"lines": [{"name": "시설현대화 지원사업", "why": "감귤 농사를 지으셔서요", "period": "11월 23일까지", "where": "접수처: 지역 농·감협", "ask": ["바꾸고 싶은 시설이 있으신지요?"]},
                       {"name": "저온저장고 지원", "why": "저장고가 필요해요", "period": "11월 30일까지", "where": "접수처: 건강보험공단 지사", "ask": []}], "more_names": []}
    middle = 0
    for name in demo:
        view = demo_view(demo, bundle, name)
        always = [bool(c.get("always")) for c in view["now_cards"]]
        at = always.index(True) if True in always else len(always)
        want = ["g"] * at + ["n", "n"] + ["g"] * (len(always) - at)
        zone = parse_front(demo_paper(demo, bundle, name, match)).select_one(".pz-now .pz-b")
        got = ["n" if "rnt" in x["class"] else "g" for x in zone.find_all(True, recursive=False)]
        assert got == want, (name, got, want)
        middle += at < len(always)
        for ln, row in zip(match["lines"], zone.select(".rnt")):
            pic = row.select_one(".pc .pc-pic svg")
            assert pic is not None and squash(str(pic)) == squash(str(parse(str(art.place_icon(notice_box(ln)["place"], "ic ic-p"))).svg)), (name, ln["name"])
    assert middle >= 1                                                         # 마지막이 아닌 자리(언제든 상자 앞)가 시험된다


def test_later_zone_shows_only_the_near_rows_and_one_quiet_far_line(demo, bundle):
    """앞으로 신청할 것은 화면과 같은 가까운 줄(넉 달 안 + 때 모르는 줄)만 싣고, 먼 줄은 맨 끝 한 줄('그 뒤에도 N가지가 더 있어요 · 내년 ○월부터 신청해요 · 문자 알림을 …')."""
    for name in demo:
        view = demo_view(demo, bundle, name)
        zone = parse_front(demo_paper(demo, bundle, name)).select_one(".pz-later")
        assert [squash(x.get_text()) for x in zone.select(".lr-t")] == [squash(r["title"]) for r in view["later_rows"]], name       # 같은 글 · 같은 차례
        far = view["later_far"]
        more = zone.select(".lg-more")
        assert far and len(more) == 1 and more[0] is zone.select_one(".pz-b").find_all(recursive=False)[-1], name                     # 한 줄, 맨 끝
        assert " ".join(more[0].get_text().split()) == far["paper_text"], name
        assert far["paper_text"].endswith("문자 알림을 받으시면 그 달에 알려 드려요"), name
        assert not any(squash(r["title"]) in squash(zone.get_text()) for r in view["far_rows"]), name                                  # 먼 줄의 지원 이름은 종이에 없다


def test_a_farm_with_only_far_rows_keeps_the_later_zone_with_just_the_line(demo, bundle):
    """P4: 가까운 줄이 없고 먼 줄만 있어도 앞으로 구역은 남고 그 한 줄만 보인다('0가지'는 쓰지 않는다). '내년 8~10월'의 달 이름은 '내년 8월'이다."""
    front = parse_front(demo_paper(demo, bundle, "P4"))
    zone = front.select_one(".pz-later")
    assert zone is not None and not zone.select(".lg") and len(zone.select(".lg-more")) == 1
    text = " ".join(zone.select_one(".lg-more").get_text().split())
    assert "0가지" not in front.get_text() and text.startswith("그 뒤에도 1가지가 더 있어요 · 내년 8월부터 신청해요")
    assert "10월" not in text


def test_no_far_line_when_every_later_row_is_near_and_the_limit_is_one_constant(demo, bundle, monkeypatch):
    """먼 줄이 없는 농가는 그 한 줄이 안 나오고, 기준 상수(LATER_SHOW_MONTHS) 하나만 바꾸면 종이의 줄도 따라 바뀐다(화면과 같은 값)."""
    from app.ui import result_view
    base = {n: len(parse_front(demo_paper(demo, bundle, n)).select(".pz-later .lr")) for n in demo}
    monkeypatch.setattr(result_view, "LATER_SHOW_MONTHS", 12)
    grown = 0
    for name in demo:
        front = parse_front(demo_paper(demo, bundle, name))
        view = demo_view(demo, bundle, name)
        assert not front.select(".lg-more") and not view["later_far"], name
        shown = len(front.select(".pz-later .lr"))
        assert shown == len(view["later_rows"]) >= base[name], name
        grown += shown > base[name]
    assert grown >= 1


def test_paper_later_months_equal_the_screen_later_months_in_order(demo, bundle):
    from app.ui.render import split_when
    for name in demo:
        view = demo_view(demo, bundle, name)
        front = parse_front(demo_paper(demo, bundle, name))
        for w in front.select(".pz-later .lg-where"):
            w.decompose()
        assert [squash(w.get_text()) for w in front.select(".pz-later .lg-when")] == [squash(split_when(g["when"])[0]) for g in view["later_groups"]], name


def test_far_rows_count_on_the_paper_equals_the_staff_window_list(demo, bundle):
    """종이는 먼 줄을 한 줄 수로만 알린다. 그 수가 화면 직원용 창의 '그 뒤에 신청할 것' 목록과 같다(문자 알림 대상은 줄지 않는다: 화면 몫)."""
    for name in demo:
        view = demo_view(demo, bundle, name)
        assert len(view["detail"]["far"]) == len(view["far_rows"]) == view["later_far"]["n"], name
