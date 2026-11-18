"""지원 전체 보기 자료(app/catalog): 28가지 묶기, 신청 기간·금액·접수처 글, 걸러 보기, 새 공고 합치기(설계서 B-1, B-5)."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.catalog import build_catalog, key_for_name, load_catalog, load_notices
from app.catalog.links import load_links
from app.catalog.build import BADGE_NEW, BADGE_TABLE, FILTER_ALL, FILTER_NEW, FILTER_OPEN
from app.catalog.notices import NoticeRecord, NoticeTag
from app.catalog.texts import ASK_AMOUNT, ASK_OFFICE, HOLD_NOTE, NO_TIMING, PRIOR_NOTE, amount_of, window_of, won
from app.core.models import Program
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 14)
BUNDLE = load_tables(ROOT / "data" / "tables", TODAY)
ROWS = {p.id: p for p in BUNDLE.programs}
# 표 28가지만 본다. 실제 새 공고 폴더(data/catalog/notices)는 공고가 올라올 때마다 바뀌므로 여기서 읽지 않는다.
CATALOG = build_catalog(BUNDLE, TODAY, load_links(ROOT / "data" / "catalog" / "links.csv"))


def row(pid: str, **change) -> Program:
    return Program.model_validate({**ROWS[pid].model_dump(), **change})


def entry(key: str):
    e = CATALOG.get(key)
    assert e is not None, key
    return e


# --- 묶기 ------------------------------------------------------------------------------------

def test_forty_two_rows_become_twenty_eight_schemes():
    assert CATALOG.count == 28 == len({e.key for e in CATALOG.entries})
    assert all(e.kind == "table" and e.badge == BADGE_TABLE for e in CATALOG.entries)
    assert sum(len(e.variants) for e in CATALOG.entries) == 42
    assert not any("@" in e.key or "#" in e.key for e in CATALOG.entries)


def test_scheme_names_drop_the_crop_in_parentheses_when_rows_are_split_by_crop():
    assert entry("NAT-CROP-INS").title == "농작물재해보험"
    assert entry("NAT-INCOME-INS").title == "농업수입안정보험"
    assert entry("JEJU-PSTAB").title == "제주형 가격안정관리제"
    assert entry("JS-WINDBREAK").title == "감귤원 방풍수 정비(제주시)"          # 시마다 다른 제도라 괄호를 둔다
    assert entry("NAT-PRICE-STAB-GO").title == "정부 농산물가격안정제(마늘·양파)"
    assert entry("NHIS-FARMER-SUPPORT").title == "농어업인 건강보험료 지원"


def test_crops_list_and_variants():
    e = entry("NAT-CROP-INS")
    assert e.crops == "감귤 · 당근 · 월동무 · 양배추 · 마늘 · 양파 · 브로콜리"
    assert [v.label for v in e.variants] == ["감귤", "당근", "월동무", "양배추", "마늘", "양파", "브로콜리"]
    assert entry("NHIS-FARMER-SUPPORT").variants[0].label == "읍·면 지역" and entry("NHIS-FARMER-SUPPORT").variants[1].label == "동 지역"
    assert entry("KRC-FARMLAND-PENSION").variants[0].label is None and entry("KRC-FARMLAND-PENSION").crops == ""


def test_every_entry_has_three_or_four_tags_and_a_link_path():
    for e in CATALOG.entries:
        assert 3 <= len(e.tags) <= 4, e.key
        assert e.href == f"/supports/{e.key}"
        assert e.window and e.amount and e.verified_text.endswith("확인했어요")


# --- 신청 기간 글 ----------------------------------------------------------------------------

def test_headline_picks_the_closing_variant_and_names_it():
    e = entry("NAT-CROP-INS")
    assert e.window == "양파 11월 27일까지 · 13일 남음" and e.open_now and e.window_rank == 0 and e.window_days == 13
    assert entry("NAT-INCOME-INS").window == "마늘 11월 30일까지 · 16일 남음"
    by = {v.label: v.window for v in e.variants}
    assert by["마늘"] == "올해 신청은 끝났어요 · 내년 10월쯤 다시 받아요" and by["양파"] == "11월 27일까지 · 13일 남음"
    assert by["당근"] == "올해 신청은 끝났어요 · 내년 7월쯤 다시 받아요"


@pytest.mark.parametrize("asof,text,rank", [
    (date(2026, 11, 14), "11월 27일까지 · 13일 남음", 0), (date(2026, 11, 27), "11월 27일까지 · 오늘 마감", 0),
    (date(2026, 10, 5), "10월 19일부터 · 14일 뒤 열려요", 1), (date(2026, 11, 28), "올해 신청은 끝났어요 · 내년 10월쯤 다시 받아요", 3)])
def test_window_of_confirmed_yearly_row(asof, text, rank):
    w = window_of(ROWS["NAT-CROP-INS@2026#양파"], asof)
    assert (w.text, w.rank) == (text, rank) and w.open_now == (rank == 0)


def test_window_of_other_kinds():
    assert window_of(ROWS["KRC-FARMLAND-PENSION@2026"], TODAY).text == "언제든 신청할 수 있어요"
    assert window_of(ROWS["NAT-DISASTER-RECOVERY@2026"], TODAY).text == "재해가 난 뒤에 신청해요"
    assert window_of(ROWS["NAT-FARM-HELPER@2026"], TODAY).text == "사고가 난 뒤에 신청해요"
    assert window_of(ROWS["JEJU-LOGI@2026-27"], TODAY).text == "농협이 대신 신청해요"
    assert window_of(ROWS["NAT-SAFETY-INS@2026"], TODAY).text == NO_TIMING          # 보류 행은 시기를 말하지 않는다
    assert window_of(ROWS["JEJU-FARMER-ALLOW@2026"], TODAY).text == "올해 신청은 끝났어요 · 내년 3월쯤 다시 받아요"
    assert window_of(ROWS["JEJU-FARMER-ALLOW@2026"], date(2027, 1, 10)).text == "올해 공고 전이에요 · 3월쯤 받아요"
    assert not window_of(ROWS["JEJU-FARMER-ALLOW@2026"], TODAY).open_now            # 작년 기준 행은 '지금 받는 것'이 아니다


def test_open_now_filter_counts_confirmed_rows_only():
    open_keys = {e.key for e in CATALOG.select(FILTER_OPEN)}
    assert open_keys == {"NAT-CROP-INS", "NAT-INCOME-INS", "NHIS-FARMER-SUPPORT", "NAT-PENSION-SUPPORT", "NAT-DISASTER-RECOVERY",
                         "KRC-FARMLAND-PENSION", "NAT-RETIRE-DIRECT", "NAT-FARM-HELPER"}


def test_sorted_with_closing_first_then_always_then_later():
    ranks = [e.window_rank for e in CATALOG.entries]
    assert ranks == sorted(ranks)
    assert CATALOG.entries[0].key == "NAT-CROP-INS" and CATALOG.entries[1].key == "NAT-INCOME-INS"


# --- 금액 글 ---------------------------------------------------------------------------------

def test_amount_uses_the_note_as_written_else_builds_from_amount_columns():
    assert entry("NAT-PENSION-SUPPORT").amount == "보험료 50%, 월 최대 50,350원(2026)"
    assert amount_of(ROWS["NAT-DIRECT-SMALL@2026"]) == "1년에 130만 원"           # amount_note 없음 → 칸으로
    assert amount_of(ROWS["JEJU-WOMEN-VOUCHER@2026"]) == "1년에 20만 원"
    assert amount_of(ROWS["JEJU-SMALLFARM@2026"]) == "1년에 15만 원"


@pytest.mark.parametrize("change,text", [
    (dict(amount_type="단위당", amount_value=79200, unit_name="상자(2,000매)", period=None), "상자(2,000매)당 7만 9,200원"),
    (dict(amount_type="kg당", amount_value=16, period=None), "kg당 16원"),
    (dict(amount_type="면적비례", amount_value=1500000, period="연"), "면적에 따라 150만 원"),
    (dict(amount_type="보조율", rate_pct_min=60, rate_pct_max=85, cap_won=6210000), "60~85% 지원, 최대 621만 원"),
    (dict(amount_type="보조율", rate_pct_max=90), "90% 지원"),
    (dict(amount_type="정액", amount_min=400000, amount_max=500000), "40만 원~50만 원"),
    (dict(amount_type="정액", amount_max=500000), "최대 50만 원"),
    (dict(amount_type="규칙"), None)])
def test_amount_builder_from_columns(change, text):
    blank = dict(amount_note=None, amount_value=None, period=None)
    p = row("NAT-DIRECT-SMALL@2026", **{**blank, **change})
    assert amount_of(p) == text


def test_won_text_is_exact_never_rounded():
    assert [won(n) for n in (500, 58800, 79200, 168000, 1300000, 4400000, 6210000)] == [
        "500원", "5만 8,800원", "7만 9,200원", "16만 8,000원", "130만 원", "440만 원", "621만 원"]


def test_unknown_amount_says_ask_the_office():
    rows = tuple(row(p.id, amount_note=None, amount_type="규칙", amount_value=None, period=None, amount_min=None,
                     amount_max=None, rate_pct_min=None, rate_pct_max=None, cap_won=None, unit_name=None, units_per_ha=None)
                 if p.program_key == "KRC-FARMLAND-PENSION" else p for p in BUNDLE.programs)
    cat = build_catalog(BUNDLE.model_copy(update={"programs": rows}), TODAY)
    assert cat.get("KRC-FARMLAND-PENSION").amount == ASK_AMOUNT == "금액은 창구에 물어보세요"


def test_group_with_different_amounts_points_to_the_rows():
    rows = tuple(row(p.id, amount_note=f"보조 {p.id[-2:]}") if p.program_key == "NHIS-FARMER-SUPPORT" else p for p in BUNDLE.programs)
    e = build_catalog(BUNDLE.model_copy(update={"programs": rows}), TODAY).get("NHIS-FARMER-SUPPORT")
    assert "마다 달라요" in e.amount and len({v.amount for v in e.variants}) == 2


# --- 접수처·전화·준비물·링크·확인 날짜·안내 ---------------------------------------------------------

def test_contacts_use_row_phone_then_office_phone_and_keep_office_name_alone_otherwise():
    assert entry("JEJU-FARMER-ALLOW").contacts[0].phone == "064-710-4092"                 # 행의 phone
    assert entry("NHIS-FARMER-SUPPORT").contacts[0].phone == "1577-1000"                  # offices.csv 의 phone
    c = entry("SGP-WINDBREAK").contacts[0]
    assert c.office == "과원 소재지 읍·면·동" and c.phone is None                          # 전화가 없으면 접수처 이름만
    assert entry("JEJU-FARMER-ALLOW").phone == "064-710-4092" and entry("SGP-WINDBREAK").phone is None


def test_documents_notes_and_verified_date():
    assert entry("KRC-FARMLAND-PENSION").documents == ("신분증, 담보농지 등기부등본, 경영체 등록확인서, 영농경력 증빙",)
    assert entry("NAT-DIRECT-SMALL").documents == ()
    assert PRIOR_NOTE in entry("JEJU-FARMER-ALLOW").notes and entry("JEJU-FARMER-ALLOW").prior_year
    assert PRIOR_NOTE in entry("NAT-CROP-INS").notes                                       # 일부 작물만 작년 기준
    assert entry("KRC-FARMLAND-PENSION").notes == () and not entry("KRC-FARMLAND-PENSION").prior_year
    assert entry("NAT-SAFETY-INS").hold and HOLD_NOTE in entry("NAT-SAFETY-INS").notes
    assert entry("JEJU-FARMER-ALLOW").verified_date == date(2026, 11, 5) or entry("JEJU-FARMER-ALLOW").verified_date == date(2026, 11, 7)
    assert entry("NAT-CROP-INS").verified_text.startswith("2026년 11월 ") and entry("NAT-CROP-INS").verified_text.endswith("에 확인했어요")


def test_conditions_are_plain_words_common_to_all_rows_and_checks_are_table_text():
    e = entry("KRC-FARMLAND-PENSION")
    assert e.conditions == ("나이: 60세 이상 (그해 연말의 나이)", "땅: 내 땅이어야 해요 (2년 이상 가지고 있어야 해요)", "농사 경력: 5년 이상")
    assert "지목 전·답·과수원이고 실제 농사짓는 땅" in e.checks
    crop = entry("NAT-CROP-INS")
    assert crop.conditions == ("농업경영체에 등록해야 해요",)
    assert any("넓이" in c for c in crop.variants[0].conditions) and "넓이" not in " ".join(crop.conditions)
    for e in CATALOG.entries:                                                              # 화면에 코드 낱말이 새지 않는다
        blob = " ".join([e.title, e.window, e.amount, *e.conditions, *e.tags, e.badge, *e.notes])
        for bad in ("program_key", "prior_year", "confirmed", "CHECK", "hold", "None", "NAT-", "JEJU-"):
            assert bad not in blob, (e.key, bad)


def test_links_come_from_links_csv_and_nineteen_schemes_have_one():
    linked = {e.key: e.link for e in CATALOG.entries if e.link}
    assert len(linked) == 19
    assert linked["NAT-DIRECT-AREA"].url == linked["NAT-DIRECT-SMALL"].url
    assert "JEJU-CITRUS-PSTAB" not in linked and "JEJU-LOGI" not in linked
    assert linked["SGP-WINDBREAK"].kind == "통합 공고" and linked["SGP-WINDBREAK"].note == "자세한 내용은 공고에 붙은 파일에 있어요"
    assert linked["JEJU-FARMER-ALLOW"].kind == "공고 원문"


def test_key_for_name_finds_the_scheme_for_home_cards():
    assert key_for_name(BUNDLE.programs, "농작물재해보험(양파)") == "NAT-CROP-INS"
    assert key_for_name(BUNDLE.programs, "농업수입안정보험(마늘)") == "NAT-INCOME-INS"
    assert key_for_name(BUNDLE.programs, "없는 지원") is None
    assert CATALOG.key_for_name("농업수입안정보험(양파)") == "NAT-INCOME-INS" and CATALOG.key_for_name("없음") is None


def test_every_due_name_of_the_home_screen_maps_to_a_catalog_entry():
    due = {p.name or p.program_key for p in BUNDLE.programs}            # home_lines 가 쓰는 이름은 모두 표 행의 이름이다
    for name in due:
        assert CATALOG.get(CATALOG.key_for_name(name)) is not None, name


# --- 걸러 보기 -------------------------------------------------------------------------------

def test_filters_are_built_from_values_and_hide_empty_groups():
    f = {x.id: x.count for x in CATALOG.filters()}
    assert f[FILTER_ALL] == 28 and f[FILTER_OPEN] == 8
    assert f["citrus"] == 7 and f["field"] == 10 and f["senior"] == 3 and f["women"] == 1 and f["insurance"] == 5
    assert FILTER_NEW not in f                                                              # 새 공고가 없으면 단추도 없다
    assert [x.label for x in CATALOG.filters()][:2] == ["전체", "지금·언제든 신청"]
    assert {e.key for e in CATALOG.select("women")} == {"JEJU-WOMEN-VOUCHER"}
    assert {e.key for e in CATALOG.select("senior")} == {"KRC-FARMLAND-PENSION", "NAT-RETIRE-DIRECT", "JEJU-HAPPY-TAXI"}
    assert CATALOG.select("모름") == CATALOG.entries == CATALOG.select(None) == CATALOG.select(FILTER_ALL)


# --- 새 공고 ---------------------------------------------------------------------------------

def notice(**kw) -> NoticeRecord:
    base = dict(key="new-샘플", name="2027년 샘플 지원사업", agency="서귀포시 농업정책과", apply_period="신청기간: 2026. 11. 9. ~ 11. 23.",
                target="사업을 희망하는 농가", content="16개 사업", tags=(NoticeTag("감귤 농가", "감귤 고품질시설"), NoticeTag("농협에서 접수", "접수처: 지역 농·감협")),
                url="https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=1", read_date=date(2026, 11, 14),
                decision="DRAFT_READY", table_key=None)
    return NoticeRecord(**{**base, **kw})


def test_new_notice_card_comes_first_with_quotes_and_link():
    cat = build_catalog(BUNDLE, TODAY, notices=[notice()])
    first = cat.entries[0]
    assert cat.count == 29 and first.kind == "notice" and first.key == "new-샘플" and first.badge == BADGE_NEW
    assert first.tags == ("감귤 농가", "농협에서 접수") and first.window == "11월 23일까지 · 9일 남음" and first.window_end == date(2026, 11, 23)
    assert first.new_quotes == (("감귤 농가", "감귤 고품질시설"), ("농협에서 접수", "접수처: 지역 농·감협"))
    assert first.link.url.startswith("https://www.seogwipo.go.kr/") and first.link.kind == "공고 원문"
    assert first.amount == ASK_AMOUNT and first.href == "/supports/new-%EC%83%98%ED%94%8C"
    assert {f.id: f.count for f in cat.filters()}[FILTER_NEW] == 1 and cat.select(FILTER_NEW) == (first,)
    assert cat.get("new-샘플") is first


def test_new_notice_matching_a_table_scheme_makes_no_duplicate_card():
    cat = build_catalog(BUNDLE, TODAY, notices=[notice(table_key="JEJU-LOGI"), notice(key="new-b", name="다른 사업")])
    assert cat.count == 29 and cat.hidden_notices == 1 and cat.get("new-샘플") is None and cat.get("new-b")


def test_new_notice_without_link_and_loader_reads_the_folder(tmp_path):
    folder = tmp_path / "data" / "catalog" / "notices"
    folder.mkdir(parents=True)
    rec = {"version": 1, "name": "손으로 만든 공고", "agency": "제주시", "apply_period": "11. 20.까지", "target": "농가", "content": "자재",
           "tags": [{"label": "하나", "quote": "원문 하나"}, {"label": "둘", "quote": "원문 둘"}], "url": "https://evil.example/x",
           "read_date": "2026-11-14", "decision": "DRAFT_READY", "table_key": None}
    (folder / "손으로 만든 공고.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (folder / "깨진.json").write_text("{ 깨짐", encoding="utf-8")
    (folder / "태그부족.json").write_text(json.dumps({**rec, "name": "태그부족", "apply_period": "", "tags": rec["tags"][:1]}, ensure_ascii=False), encoding="utf-8")
    cat = load_catalog(tmp_path, BUNDLE, TODAY)                    # links.csv 가 없어도 된다
    assert cat.count == 29 and cat.entries[0].title == "손으로 만든 공고"
    assert cat.entries[0].link is None                              # 공식 주소가 아니면 링크를 달지 않는다
    assert all(e.link is None for e in cat.entries)


def test_empty_data_folders_are_fine(tmp_path):
    assert load_catalog(tmp_path, BUNDLE, TODAY).count == 28


def test_hand_made_example_files_in_the_fixture_folder():
    folder = ROOT / "tests" / "fixtures" / "catalog_notices"
    records = load_notices(folder)
    assert [r.name for r in records] == ["2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업", "제주산 농산물 물류비 지원"]    # 읽은 날이 늦은 것이 먼저
    cat = build_catalog(BUNDLE, TODAY, notices=records)
    assert cat.count == 29 and cat.hidden_notices == 1                      # 둘째는 표의 물류비 지원과 같아 카드가 없다
    first = cat.entries[0]
    assert first.title.startswith("2027년 FTA기금") and first.tags == ("감귤 시설 사업", "지역 농·감협에서 접수", "16개 사업 중 고르기")
    assert first.new_period.startswith("가. 신청기간") and first.link.url.startswith("https://www.seogwipo.go.kr/")
    assert [q for _, q in first.new_quotes][1] == "나. 접수처: 지역 농·감협"


def test_new_notice_about_citrus_is_in_the_citrus_filter_but_an_office_name_is_not_enough():
    citrus = build_catalog(BUNDLE, TODAY, notices=[notice()]).get("new-샘플")
    assert "citrus" in citrus.filters and "new" in citrus.filters
    other = notice(key="new-b", name="다른 사업", target="", tags=(NoticeTag("시청 방문 신청", "서귀포시 감귤유통과 직접 방문 접수"), NoticeTag("농가", "농가")))
    assert "citrus" not in build_catalog(BUNDLE, TODAY, notices=[other]).get("new-b").filters      # 근거 문장 속 부서 이름만으로는 감귤 농가 대상이 아니다
    named = notice(key="new-c", name="감귤 농가 지원사업", tags=(NoticeTag("농가", "농가"), NoticeTag("접수", "접수")))
    assert "citrus" in build_catalog(BUNDLE, TODAY, notices=[named]).get("new-c").filters
