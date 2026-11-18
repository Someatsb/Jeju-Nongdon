"""새 공고 카드: 신청 기간을 표의 지원과 같은 말투로, 마감 가까운 순 정렬, 지금 신청 받는 것 걸러 보기, 칸별 글(설계서 B절)."""
from datetime import date
from pathlib import Path

from app.catalog import build_catalog, load_notices
from app.catalog.build import FILTER_NEW, FILTER_OPEN
from app.catalog.texts import RANK_ENDED, RANK_OPEN, RANK_SOON, RANK_UNKNOWN, notice_window
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 14)
BUNDLE = load_tables(ROOT / "data" / "tables", TODAY)
FOLDER = ROOT / "tests" / "fixtures" / "catalog_notices_polish"
CAT = build_catalog(BUNDLE, TODAY, notices=load_notices(FOLDER))
NEW = {e.title: e for e in CAT.entries if e.kind == "notice"}


def test_window_text_matches_the_table_voice():
    assert NEW["FTA기금 과수(감귤) 고품질시설현대화 지원사업"].window == "11월 23일까지 · 9일 남음"
    assert NEW["유기질비료 지원사업"].window == "12월 4일까지 · 20일 남음"
    assert NEW["유기농업자재 지원사업"].window == "12월 31일까지 · 47일 남음"
    assert NEW["곧 열리는 자재 지원사업"].window == "11월 20일부터 · 6일 뒤 열려요"
    assert NEW["지난 시설 지원사업"].window == "신청이 끝났어요"
    assert NEW["출산 농가도우미 지원사업"].window == "언제 받는지는 창구에 물어보세요"
    assert NEW["출산 농가도우미 지원사업"].window_end is None


def test_last_day_and_original_line_is_kept():
    w, s, e = notice_window("가. 신청기간: 2026. 11. 9. ~ 11. 14.", TODAY, TODAY)
    assert w.text == "11월 14일까지 · 오늘 마감" and w.rank == RANK_OPEN and w.days == 0 and w.open_now and e == TODAY
    w, _, _ = notice_window("연중 상시", TODAY, TODAY)
    assert w.text == "연중 상시" and w.rank == RANK_UNKNOWN and not w.open_now      # 읽지 못하면 원문 글(앞머리만 뗌)
    first = NEW["FTA기금 과수(감귤) 고품질시설현대화 지원사업"]
    assert first.new_period.startswith("가. 신청기간") and first.new_period_line.startswith("신청기간: 2026. 11. 9.")


def test_new_notices_sorted_by_closing_then_unknown_then_ended():
    new_titles = [e.title for e in CAT.entries if e.kind == "notice"]
    assert new_titles == ["FTA기금 과수(감귤) 고품질시설현대화 지원사업", "유기질비료 지원사업", "유기농업자재 지원사업", "곧 열리는 자재 지원사업",
                          "농촌융복합산업 자금(융자) 지원사업", "출산 농가도우미 지원사업", "지난 시설 지원사업"]
    ranks = [e.window_rank for e in CAT.entries if e.kind == "notice"]
    assert ranks == [RANK_OPEN] * 3 + [RANK_SOON, RANK_UNKNOWN, RANK_UNKNOWN, RANK_ENDED]
    assert all(e.kind == "table" for e in CAT.entries[7:])                    # 새 공고가 모두 앞, 표의 지원이 뒤


def test_open_filter_includes_new_notices_inside_their_period_only():
    opened = {e.title for e in CAT.select(FILTER_OPEN) if e.kind == "notice"}
    assert opened == {"FTA기금 과수(감귤) 고품질시설현대화 지원사업", "유기질비료 지원사업", "유기농업자재 지원사업"}
    assert len(CAT.select(FILTER_NEW)) == 7 and all(FILTER_NEW in e.filters for e in NEW.values())
    citrus_new = {e.title for e in CAT.select("citrus") if e.kind == "notice"}
    assert citrus_new == {"FTA기금 과수(감귤) 고품질시설현대화 지원사업"}              # 감귤 농가 대상 새 공고는 감귤 걸러 보기에도 나온다(부서 이름 '감귤유통과'만 든 것은 아니다)


def test_who_box_uses_target_or_the_tag_quotes_without_bullets_or_repeats():
    fta = NEW["FTA기금 과수(감귤) 고품질시설현대화 지원사업"]
    assert fta.new_target_lines == ()                      # 공고 이름을 되풀이한 글은 대상이 아니다
    assert fta.new_who == (("감귤 농가 대상", ""), ("시설 16종 중 골라 신청", "신청사업: 16개사업"))
    assert fta.new_where == ("접수처: 지역 농·감협",) and fta.new_rest == ()
    fert = NEW["유기질비료 지원사업"]
    assert fert.new_who[0] == ("농업경영체 등록 농가·법인", "신청자격: 농업경영체(농업인 및 법인)")
    assert fert.new_content_lines == ("유기질비료(3종): 보조 1,700원 ~ 2,000원/20kg / 부숙유기질비료(2종): 보조 1,300원 ~ 1,900원/20kg",)
    assert all("20kg" not in q for _, q in fert.new_who)       # 금액 줄은 '얼마나'에만
    birth = NEW["출산 농가도우미 지원사업"]
    assert birth.new_target_lines == ("지원대상: 도내 출산(예정) 여성농업인",) and birth.new_who == ()
    assert [lab for lab, _ in birth.new_rest] == ["직장인은 농외소득 제한"]


def test_where_box_agency_then_register_line():
    loan = NEW["농촌융복합산업 자금(융자) 지원사업"]
    assert loan.new_where == ("신청방법: 서귀포시 감귤유통과 직접 방문 접수(문의: 064-760-2883)",)    # 기관 이름이 줄 안에 있으니 한 번만
    assert NEW["유기농업자재 지원사업"].new_where == ("신청장소: 농지 소재지 읍면동사무소",)
    assert NEW["출산 농가도우미 지원사업"].new_where == ()
