"""같은 가실 곳을 다르게 적은 접수처를 최대한 한 상자로 합친다(2026-11-15 사장 지시) + "에 가세요" 없음 + 종이 딱지 '언제든' + 어르신 화면의 '새 공고' 말.
합치는 것은 두 무리: (가) 읍·면·동(주소지·농지 소재·과원 소재지·피해 농지·교통복지카드) (나) 농협(지역농협류와 읍·면에 맞춰 뽑은 농협).
AI 입력·FactSheet 은 build_cards 를 쓰지 않으므로 바뀌지 않는다."""
import csv
import re
from pathlib import Path

import pytest

from app.core.sheet_cards import COOP_KEY, EMD_KEY, FARMLAND_NOTE, MERGED_OFFICE, _office_key, build_cards, line_notes, merge_group
from app.ui.result_view import SCREEN_MAX_CARDS, SCREEN_MAX_LINES, _days_to_next, _line_window, build_view, ieyo, office_display, order_boxes

from .test_paper_v2 import AS_OF, CFG, bundle, made, paper, parse  # noqa: F401

TABLES = Path(__file__).resolve().parents[2] / "data" / "tables"
EMD = ["주소지 읍·면·동", "주소지 읍·면사무소, 동 주민센터", "주소지 읍(면)사무소", "거주지 주민센터", "농지 소재 읍·면·동", "농지 소재지 읍·면·동",
       "농지 소재지 읍·면·동 (비대면: 농업e지·ARS 1334)", "농지가 있는 읍·면·동", "농지가 있는 읍·면·동 (집에서는 농업e지나 전화 1334)",
       "과원 소재지 읍·면·동", "피해 농지 또는 주소지 읍·면·동", "읍·면·동 (교통복지카드)"]
COOP = ["지역농협", "지역농협(신청 주체)", "지역 농·감협", "지역 농·축협", "거주지 지역농협", "농지 소재지 지역농협", "서귀포시 관내 지역 농·감협",
        "성산·구좌·표선·애월·한림·한경·대정농협, 수급관리센터"]
APART = ["농지은행 1577-7770", "농지은행 1577-7770 → 농어촌공사 제주지사", "건보공단 지사", "건강보험공단 지사", "국민연금공단 지사", "국립농산물품질관리원 제주지원(농관원)",
         "별도 신청 없음(경영체 정보 기준) - 지역농협·농관원 확인"]


def test_two_groups_merge_and_nothing_else():
    assert {merge_group(o) for o in EMD} == {EMD_KEY} and {_office_key(o) for o in EMD} == {EMD_KEY}
    assert {merge_group(o) for o in COOP} == {COOP_KEY} and {_office_key(o) for o in COOP} == {COOP_KEY}
    for o in APART:
        assert merge_group(o) is None and _office_key(o) == o.split("(")[0].strip(), o


def test_every_office_name_in_the_tables_lands_in_the_expected_group():
    with open(TABLES / "offices.csv", encoding="utf-8-sig") as f:
        names = {r["name"] for r in csv.DictReader(f)}
    with open(TABLES / "supports.csv", encoding="utf-8-sig") as f:
        names |= {r["office"] for r in csv.DictReader(f) if r["office"]}
    got = {n: merge_group(n) for n in names}
    assert {n for n, g in got.items() if g == EMD_KEY} == {n for n in EMD if n in names}
    assert {n for n, g in got.items() if g == COOP_KEY} == {n for n in COOP if n in names}
    assert {n for n, g in got.items() if g is None} <= set(APART)      # 자료에 새 접수처 이름이 생기면 여기서 알린다(합칠지 따로 둘지 정한다)


def test_line_notes_only_where_the_source_name_differs():
    assert line_notes("주소지 읍·면사무소, 동 주민센터", "대정읍") == () and line_notes("주소지 읍·면·동", "대정읍") == ()          # 주소지 쪽 줄에는 없다
    assert line_notes("농지 소재 읍·면·동", "대정읍") == (FARMLAND_NOTE,) and line_notes("과원 소재지 읍·면·동", "대정읍") == (FARMLAND_NOTE,)
    assert line_notes("농지 소재지 읍·면·동 (비대면: 농업e지·ARS 1334)", "대정읍") == (FARMLAND_NOTE, "집에서는 농업e지나 전화 1334")      # 번호는 자료 그대로
    assert line_notes("읍·면·동 (교통복지카드)", "대정읍") == ()
    assert line_notes("지역농협", "대정읍") == () and line_notes("지역농협(신청 주체)", "대정읍") == ("지역농협(신청 주체)",)
    assert line_notes("성산·구좌·표선·애월·한림·한경·대정농협, 수급관리센터", "대정읍") == ("대정농협",)
    assert line_notes("성산·구좌·표선·애월·한림·한경·대정농협, 수급관리센터", "구좌읍") == ("구좌농협",)
    assert line_notes("농지 소재지 지역농협", "대정읍") == ("농지가 있는 곳의 지역농협",) and line_notes("지역 농·감협", "대정읍") == ("지역 농·감협",)
    assert line_notes("서귀포시 관내 지역 농·감협", "대정읍") == ("서귀포시 안의 지역 농·감협",)        # '관내'는 풀어 쓴다
    assert line_notes("건보공단 지사", "대정읍") == () and line_notes(None, "대정읍") == ()


# 합치기 전(2026-11-15 ff2c556) -> 후 상자 수
@pytest.mark.parametrize("name,before,after", [("P1", 4, 3), ("P2", 6, 3), ("P3", 6, 4), ("P4", 3, 3), ("P5", 6, 4)])
def test_box_counts_drop_where_names_differed(made, bundle, name, before, after):
    sheet, fs = made[name]
    cs = build_cards(sheet, fs, None, max_cards=SCREEN_MAX_CARDS, max_lines=SCREEN_MAX_LINES)
    assert len(cs.cards) == after <= before
    heads = [office_display(c.place) for c in cs.cards]
    assert sum(h == MERGED_OFFICE[EMD_KEY] for h in heads) <= 1 and sum(h == MERGED_OFFICE[COOP_KEY] for h in heads) <= 1
    lines = sum(len(c.all_lines) for c in cs.cards)
    assert lines == sum(len(c.all_lines) for c in build_cards(sheet, fs, None, max_cards=99, max_lines=99).cards)   # 줄은 하나도 잃지 않는다


def test_merged_boxes_have_no_phone_and_notes_sit_on_the_lines(made, bundle):
    for name in ("P1", "P2", "P3", "P5"):
        sheet, fs = made[name]
        v = build_view(sheet, fs, bundle, AS_OF, None, screen=True)
        for c in v["cards"]:
            if c["head"] in MERGED_OFFICE.values():
                assert not c["phone"] and not c["tel_note"], (name, c["head"])      # 전화·덧말은 상자 띠가 아니라 그 지원의 줄로
        farm_notes = [n for c in v["cards"] for it in (*c["todo"], *c["gets"]) for n in it["place_notes"]]
        assert FARMLAND_NOTE in farm_notes, name
    sheet, fs = made["P3"]
    v = build_view(sheet, fs, bundle, AS_OF, None, screen=True)
    rows = {it["title"]: it["place_notes"] for c in v["cards"] for it in (*c["todo"], *c["gets"])}
    assert rows["면적직불금"] == [FARMLAND_NOTE, "집에서는 농업e지나 전화 1334"] and rows["토양생태환경보전(월동채소 면적조절)"] == ["대정농협"]
    assert rows["제주 농민수당"] == [] and rows["마늘 농작물보험"] == []


def test_screen_and_paper_places_agree_after_merging(made, bundle):
    """합친 뒤에도 종이 앞면의 가실 곳 묶음은 화면 지금 구역의 상자와 같은 이름·같은 순서다(번호 동그라미는 화면에도 종이에도 없다)."""
    for name in ("P2", "P3", "P5"):
        soup = parse(paper(made, name, None, bundle))
        assert not soup.select(".front .pb-no"), name
        sheet, fs = made[name]
        now = build_view(sheet, fs, bundle, AS_OF, None, screen=True)["now_cards"]
        heads = [h.get_text(" ", strip=True) for h in soup.select(".front .pg.rrw .pb-t")]
        assert len(heads) == len(now) >= 1, name
        for c, h in zip(now, heads):            # 종이 가실 곳 묶음은 화면 지금 구역 순서 그대로(같은 이름)
            assert office_display(c["head"]).replace(" ", "") in h.replace(" ", ""), (name, h)


