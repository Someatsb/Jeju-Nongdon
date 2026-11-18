"""지원 전체 보기 화면이 쓰는 묶음·한눈에 띠·작물 표(app/catalog/layout.py): 있는 글을 묶고 나눌 뿐 새 글을 만들지 않는다."""
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.catalog import build_catalog
from app.catalog.layout import (
    ENDED_MAIN,
    GROUPS,
    SEP,
    glance,
    group_of,
    groups_of,
    list_where,
    split_window,
    variant_table,
)
from app.catalog.texts import PRIOR_NOTE
from app.core.office_say import office_say
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 14)
CATALOG = build_catalog(load_tables(ROOT / "data" / "tables", TODAY), TODAY)


def entry(key: str):
    e = CATALOG.get(key)
    assert e is not None, key
    return e


def test_every_entry_lands_in_exactly_one_of_five_groups_in_fixed_order():
    groups = groups_of(CATALOG.entries)
    ids = [g.id for g in groups]
    assert ids == [i for i, _ in GROUPS if i in ids]
    assert sum(g.count for g in groups) == CATALOG.count == 28
    assert all(g.count for g in groups)                                   # 빈 묶음은 만들지 않는다
    by = {g.id: {r.entry.key for r in g.rows} for g in groups}
    assert "NAT-CROP-INS" in by["open"] and "NAT-PENSION-SUPPORT" in by["always"] and "JEJU-FARMER-ALLOW" in by["ended"] and "JEJU-HAPPY-TAXI" in by["unknown"]
    assert group_of(entry("NAT-CROP-INS")) == "open"


def test_open_rows_split_the_period_and_days_left_and_are_sorted_by_urgency():
    rows = next(g for g in groups_of(CATALOG.entries) if g.id == "open").rows
    assert [r.entry.window_days for r in rows] == sorted(r.entry.window_days for r in rows)
    crop = next(x for x in rows if x.entry.key == "NAT-CROP-INS")             # 작물마다 기간이 다르면 작물 이름은 날짜에서 떼어 덧말로
    assert crop.entry.window == "양파 " + crop.main + SEP + crop.sub.removesuffix(SEP + "양파가 제일 먼저예요") and crop.sub.endswith("양파가 제일 먼저예요")
    assert "남음" in crop.sub and not crop.low
    assert all(r.main + SEP + r.sub == r.entry.window for r in rows if "제일 먼저예요" not in r.sub and "아직 확인 중" not in r.sub)
    assert split_window("언제든 신청할 수 있어요") == ("언제든 신청할 수 있어요", "")


def test_low_rows_carry_only_the_next_time_and_open_rows_carry_period_and_days():
    for g in groups_of(CATALOG.entries):
        for r in g.rows:
            if g.id in ("ended", "unknown"):
                assert r.low and r.main and r.gray == r.sub and not r.urgent and (r.sub or g.id == "unknown")
            else:
                assert not r.low and r.main and not r.gray
    ended = next(g for g in groups_of(CATALOG.entries) if g.id == "ended")
    assert {(r.main, r.sub) for r in ended.rows if r.entry.key == "JEJU-FARMER-ALLOW"} == {(ENDED_MAIN, "내년 3월쯤 다시 받아요")}
    unknown = next(g for g in groups_of(CATALOG.entries) if g.id == "unknown")
    assert all(r.main == "언제 받는지는 창구에 물어보세요" and r.sub == "" for r in unknown.rows if r.entry.hold)           # 첫 줄이 이미 창구에 물어보라고 하니 "아직 확인 중"을 또 적지 않는다


def test_table_rows_have_no_amount_and_where_is_the_office_text_as_it_is():
    for g in groups_of(CATALOG.entries):
        for r in g.rows:
            assert not hasattr(r, "who")                                                                           # 누가 이름표는 목록에서 뺐다
            assert r.entry.amount not in r.where or r.entry.amount in r.entry.tags
            assert r.where and all(w in [office_say(c.office) for c in r.entry.contacts] for w in r.where)          # 글은 자료 그대로(곳 이름 표기만 한 가지로)
    where = {r.entry.key: r.where for g in groups_of(CATALOG.entries) for r in g.rows}
    assert where["NAT-CROP-INS"] == ("지역농협",) and where["NAT-PENSION-SUPPORT"] == ("국민연금공단 지사",)
    assert where["NHIS-FARMER-SUPPORT"] == ("건강보험공단 지사",)


def test_where_dedups_offices_keeps_at_most_two_and_counts_the_rest():
    base = entry("NAT-CROP-INS")
    C = type(base.contacts[0])
    def w(*offices, phone=None):
        return list_where(replace(base, contacts=tuple(C(o, phone) for o in offices)))
    assert w("지역농협", "지역농협") == ("지역농협",)
    assert w("가 읍·면·동", "나 농협", "가 읍·면·동") == ("가 읍·면·동", "나 농협")
    assert w("가", "나", "다") == ("가", "나", "외 1곳")
    assert w("가", "나", "다", "나", "라", "마") == ("가", "나", "외 3곳")
    assert w("농지 소재지 읍·면·동 (비대면: 농업e지·ARS 1334)", phone="1334") == ("농지 소재지 읍·면·동 (비대면: 농업e지·ARS 1334)",)      # 전화번호 칸은 목록에 넣지 않는다
    assert list_where(replace(base, contacts=())) == ()


def test_where_of_a_new_notice_is_its_first_line_without_the_label_word():
    base = replace(entry("NAT-CROP-INS"), kind="notice", contacts=())
    cases = {"접수처: 지역 농·감협": "지역 농·감협", "신청장소: 농지 소재지 읍면동사무소": "농지 소재지 읍면동사무소",
             "신청방법: 서귀포시 감귤유통과 직접 방문 접수(문의: 064-760-2883)": "서귀포시 감귤유통과 직접 방문 접수(문의: 064-760-2883)"}
    for raw, want in cases.items():
        assert list_where(replace(base, new_where=(raw, "둘째 줄"))) == (want,)
    assert list_where(replace(base, new_where=("서귀포시청 방문",))) == ("서귀포시청 방문",)       # 앞머리가 없으면 그대로
    assert list_where(replace(base, new_where=())) == ()


def test_rows_are_in_remaining_days_order_and_ended_rows_by_the_nearest_next_season():
    groups = groups_of(CATALOG.entries, None, TODAY)
    assert [g.id for g in groups] == ["open", "always", "ended", "unknown"]
    open_days = [r.entry.window_days for r in groups[0].rows]
    assert open_days == sorted(open_days)
    ended = next(g for g in groups if g.id == "ended")
    months = [int(m.group(1)) for r in ended.rows for m in [re.search(r"(\d+)월쯤", r.sub)]]
    gaps = [(m - TODAY.month) % 12 for m in months]
    assert gaps == sorted(gaps) and months[0] == 1 and months[-1] == 9                       # 11월 → 1월이 가장 가깝고 9월이 가장 멀다
    same = [r.entry.title for r in ended.rows if r.sub == "다음은 1월쯤"]
    assert same == sorted(same)                                                              # 같은 때는 이름순


def test_urgent_only_for_open_rows_within_seven_days():
    e = entry("NAT-CROP-INS")
    for days, urgent in ((0, True), (7, True), (8, False), (13, False)):
        row = next(r for g in groups_of([replace(e, window_days=days)]) for r in g.rows)
        assert row.urgent is urgent and not row.low
    ended = next(r for g in groups_of([replace(entry("JEJU-FARMER-ALLOW"), window_days=2)]) for r in g.rows)
    assert not ended.urgent


def test_glance_has_three_cells_and_keeps_the_table_texts():
    e = entry("NAT-PENSION-SUPPORT")
    amount, when, where = glance(e)
    assert (amount.title, when.title, where.title) == ("얼마나", "언제 신청해요", "어디서 신청해요")
    assert amount.items[0].big == e.amount and when.items[0].big == "언제든 신청할 수 있어요"
    assert where.items[0].phone and where.items[0].big == e.phone and where.items[0].small == (e.contacts[0].office,)
    crop = glance(entry("NAT-CROP-INS"))
    assert crop[1].items[0].big == "작물·지역마다 달라요" and PRIOR_NOTE in crop[1].items[0].small          # 작년 기준은 덧말로
    allow = glance(entry("JEJU-FARMER-ALLOW"))[1].items[0]
    assert allow.big == "올해 신청은 끝났어요" and allow.small[0] == "내년 3월쯤 다시 받아요" and PRIOR_NOTE in allow.small


def test_variant_table_only_when_rows_differ_and_has_a_row_per_variant():
    t = variant_table(entry("NAT-CROP-INS"))
    assert t and len(t.rows) == 7 and t.label_head == "작물" and t.show_window and t.show_condition and not t.show_amount
    assert all(r.window for r in t.rows) and any(r.prior is False for r in t.rows) and any(r.prior for r in t.rows)
    assert variant_table(entry("JEJU-FARMER-ALLOW")) is None                # 줄이 하나뿐
    taxi = variant_table(entry("JEJU-HAPPY-TAXI"))
    assert taxi and taxi.label_head == "지역" and taxi.show_condition and not taxi.show_window
    same = replace(entry("NAT-CROP-INS"), variants=tuple(replace(v, window="같은 때", conditions=(), amount="같은 돈") for v in entry("NAT-CROP-INS").variants))
    assert variant_table(same) is None                                      # 모든 줄이 같은 값이면 표를 만들지 않는다


def test_citrus_focus_uses_the_citrus_row_period_not_the_first_crop_s():
    plain = {r.entry.key: g.id for g in groups_of(CATALOG.entries) for r in g.rows}
    assert plain["NAT-CROP-INS"] == "open" and plain["NAT-INCOME-INS"] == "open"
    citrus = CATALOG.select("citrus")
    got = {r.entry.key: (g.id, r) for g in groups_of(citrus, "citrus") for r in g.rows}
    gid, row = got["NAT-CROP-INS"]
    assert gid == "ended" and row.low and row.gray == "감귤 · 내년 4월쯤 다시 받아요"            # 양파 날짜가 아니라 감귤 줄의 기간
    assert got["NAT-INCOME-INS"][0] == "ended" and got["NAT-INCOME-INS"][1].gray == "만감류 · 내년 4월쯤 다시 받아요"
    assert sum(len(g.rows) for g in groups_of(citrus, "citrus")) == len(citrus)           # 줄 수는 그대로
    assert {r.entry.key: g.id for g in groups_of(CATALOG.entries, "field") for r in g.rows} == plain      # 감귤 걸러 보기가 아니면 그대로


def test_citrus_focus_glance_and_table_put_the_citrus_row_first():
    e = entry("NAT-CROP-INS")
    when = glance(e, "citrus")[1].items[0]
    assert when.big == "올해 신청은 끝났어요" and when.small[0] == "내년 4월쯤 다시 받아요" and any(x.startswith("감귤 ") for x in when.small)
    assert glance(e)[1].items[0].big == "작물·지역마다 달라요"                              # 걸러 보기가 없으면 그대로
    t = variant_table(e, "citrus")
    assert t.by_condition and t.sections[0].rows[0].focus and t.sections[0].rows[0].label == "감귤" and t.sections[0].rows[0].window.endswith("내년 4월쯤 다시 받아요")
    assert sum(1 for s in t.sections for r in s.rows if r.focus) == 1


def test_table_sections_write_each_condition_once_and_merge_equal_rows_without_losing_a_crop():
    e = entry("NAT-CROP-INS")
    t = variant_table(e)
    assert len(t.sections) == 2 and [s.caption for s in t.sections] == [e.variants[0].conditions[1], e.variants[2].conditions[1]]
    labels = {x for s in t.sections for r in s.rows for x in r.label.split(" · ")}
    assert labels == {v.label for v in e.variants}                                         # 작물이 하나도 빠지지 않는다
    merged = next(r for s in t.sections for r in s.rows if "월동무" in r.label)
    assert merged.label == "월동무 · 브로콜리" and merged.window == e.variants[2].window    # 같은 시기끼리 한 줄
    for s in t.sections:
        for r in s.rows:
            for x in r.label.split(" · "):
                v = next(v for v in e.variants if v.label == x)
                assert (v.window, v.amount) == (r.window, r.amount)


def test_notice_helpers_cut_only_the_label_and_the_slash_and_fold_legal_lines():
    from app.catalog.layout import amount_lines, is_legal, split_legal, where_line
    assert where_line("접수처: 지역 농·감협") == "지역 농·감협" and where_line("신청장소: 농지 소재지 읍면동사무소") == "농지 소재지 읍면동사무소"
    assert where_line("신청방법: 서귀포시 직접 방문") == "서귀포시 직접 방문"          # 칸 제목이 '어디서 신청해요'라 앞 이름은 목록과 같이 뗀다
    assert amount_lines(["가: 1원 / 나: 2원"]) == ("가: 1원", "나: 2원") and "".join(amount_lines(["가: 1원 / 나: 2원"])).replace(" ", "") == "가:1원나:2원"
    law = "｢농어업경영체 육성 및 지원에 관한 법률｣ 제2조제3호"
    assert is_legal(law) and not is_legal("농업경영체(농업인 및 법인)")
    assert split_legal(["농업경영체(농업인 및 법인)", law]) == (("농업경영체(농업인 및 법인)",), (law,))
    assert split_legal([law]) == ((law,), ())                                               # 법률 줄뿐이면 접지 않는다


def test_where_parts_mark_phone_numbers_and_rejoin_to_the_original_text():
    from app.catalog.layout import where_parts
    t = "서귀포시 감귤유통과 직접 방문 접수(문의: 064-760-2883)"
    parts = where_parts(t)
    assert "".join(x for x, _ in parts) == t and [x for x, ph in parts if ph] == ["064-760-2883"]
    assert where_parts("지역농협") == (("지역농협", False),) and where_parts("") == ()
    assert [x for x, ph in where_parts("농업e지·ARS 1334") if ph] == []
