"""때를 말하는 글을 기준일에서 본 말로(2026-11-15 표현 정리): '예년 3월'이 아니라 '내년 3월쯤'(올해 안이면 '올해 12월쯤').
한 곳(app/core/when_text.py)에서 만들고, 종이 줄 글(sheet_rules.window_text)·지원 전체 보기 글(catalog.texts.window_of)이 같이 쓴다.
기준일이 달라져도 맞아야 해서 11월·1월·같은 달·12월 말을 모두 본다."""
from datetime import date
from pathlib import Path

import pytest

from app.catalog.texts import RANK_LATER, window_of
from app.core.models import ApplyWindow
from app.core.sheet_rules import window_text
from app.data_layer.tables import load_tables
from app.core.when_text import ALWAYS, ASK_WHEN, day_when, month_when, month_when_of, months_when, year_word, year_word_of


@pytest.mark.parametrize("as_of,month,text", [
    (date(2026, 11, 13), 3, "내년 3월쯤"),       # 11월 기준 3월은 이미 지났다 → 내년
    (date(2026, 11, 13), 12, "올해 12월쯤"),     # 뒤에 오는 달은 올해
    (date(2026, 1, 20), 3, "올해 3월쯤"),        # 1월 기준 3월은 올해
    (date(2026, 11, 13), 11, "내년 11월쯤"),     # 달만 아는 철은 같은 달이면 이미 지난 철이다(기준일보다 뒤여야 올해)
    (date(2026, 12, 31), 1, "내년 1월쯤"),
    (date(2026, 12, 31), 12, "내년 12월쯤"),
    (date(2026, 1, 17), 1, "내년 1월쯤"),
    (date(2026, 1, 17), 2, "올해 2월쯤")])
def test_month_when_follows_the_as_of_month(as_of, month, text):
    assert month_when(month, as_of) == text
    assert year_word(month, as_of) == text.split()[0]


@pytest.mark.parametrize("as_of,first,text", [
    (date(2026, 1, 17), date(2027, 1, 2), "내년 1월쯤"),         # 같은 달이어도 다음 신청 첫 날이 내년이면 내년(이번 달 마감이 이미 지났다)
    (date(2026, 1, 17), date(2026, 1, 25), "올해 1월쯤"),         # 같은 달이고 아직 앞이면 올해
    (date(2026, 11, 13), date(2026, 12, 3), "올해 12월쯤"),
    (date(2026, 12, 30), date(2027, 1, 2), "내년 1월쯤")])
def test_dated_season_says_the_year_of_its_date(as_of, first, text):
    assert month_when_of(first, as_of) == text


def test_sheet_window_text_same_month_already_passed_says_next_year():
    """as_of 1월 17일, 연 1회 제도의 이번 달 마감이 지나 다음 첫 날이 2027-01-02이면 '내년 1월쯤'(달만 보고 '올해 1월쯤'이라 하지 않는다)."""
    w = ApplyWindow(always_open=False, open_now=False, next_start=date(2027, 1, 2), next_end=date(2027, 1, 16))
    assert window_text(w, "prior_year_reference", date(2026, 1, 17)) == "내년 1월쯤"


def test_months_range_and_day_use_the_first_month_and_the_date_year():
    assert months_when(3, 5, date(2026, 11, 13)) == "내년 3~5월쯤"
    assert months_when(3, 5, date(2026, 1, 20)) == "올해 3~5월쯤"
    assert months_when(8, 8, date(2026, 11, 13)) == "내년 8월쯤"
    assert day_when(date(2027, 4, 27), date(2026, 11, 13)) == "내년 4월 27일"
    assert day_when(date(2026, 12, 3), date(2026, 11, 13)) == "올해 12월 3일"
    assert year_word_of(date(2027, 1, 2), date(2026, 12, 30)) == "내년"


def _w(**kw):
    base = dict(always_open=False, open_now=False, next_start=date(2027, 3, 9), next_end=date(2027, 3, 31))
    return ApplyWindow(**{**base, **kw})


@pytest.mark.parametrize("as_of,text", [
    (date(2026, 11, 13), "내년 3월쯤"), (date(2027, 1, 10), "올해 3월쯤"), (date(2027, 3, 1), "올해 3월쯤")])
def test_sheet_window_text_for_a_prior_year_row_says_the_year_from_the_as_of(as_of, text):
    assert window_text(_w(), "prior_year_reference", as_of) == text
    assert "예년" not in window_text(_w(), "prior_year_reference", as_of)


def test_sheet_window_text_other_kinds():
    as_of = date(2026, 11, 13)
    assert window_text(_w(always_open=True, next_start=None, next_end=None), "confirmed", as_of) == ALWAYS == "언제든 신청할 수 있어요"
    assert window_text(_w(next_start=None, next_end=None), "confirmed", as_of) == ASK_WHEN
    assert window_text(_w(open_now=True, next_start=date(2026, 11, 1), next_end=date(2026, 11, 20)), "confirmed", as_of) == "지금 신청할 수 있어요 · 11월 20일까지"
    assert window_text(_w(open_now=True, next_start=date(2026, 11, 1), next_end=date(2026, 11, 20)), "prior_year_reference", as_of) == "지금도 신청할 수 있어요"



BUNDLE = load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", date(2026, 11, 13))


def _row(bundle, pid):
    return next(p for p in bundle.programs if p.id == pid)


@pytest.fixture
def bundle():
    return BUNDLE


@pytest.mark.parametrize("as_of,expect_year,expect_rank", [
    (date(2026, 11, 28), "내년", RANK_LATER),      # 양파 신청이 끝난 뒤 → 다음 철은 내년 10월쯤
])
def test_catalog_window_of_ended_row_gives_a_structured_month_and_the_year_word(bundle, as_of, expect_year, expect_rank):
    w = window_of(_row(bundle, "NAT-CROP-INS@2026#양파"), as_of)
    assert w.rank == expect_rank and w.month == 10
    assert w.text == f"올해 신청은 끝났어요 · {expect_year} 10월쯤 다시 받아요"


def test_catalog_prior_year_row_before_and_after_the_notice_month(bundle):
    row = _row(bundle, "JEJU-FARMER-ALLOW@2026")               # 작년 공고 기준, 다음 신청 달 3월
    assert row.status == "prior_year_reference" and row.expected_notice_month == 3
    late = window_of(row, date(2026, 11, 13))
    assert late.text == "올해 신청은 끝났어요 · 내년 3월쯤 다시 받아요" and late.month == 3
    early = window_of(row, date(2026, 1, 20))
    assert early.text == "올해 공고 전이에요 · 3월쯤 받아요" and early.month == 3       # 올해 안이라 '올해 N월쯤 다시 받아요'가 아니라 '올해 공고 전'으로 보인다
    same = window_of(row, date(2026, 3, 15))
    assert same.text.startswith("올해 공고 전이에요") and same.month == 3


@pytest.mark.parametrize("today", [date(2026, 11, 13), date(2027, 1, 20), date(2026, 12, 31)])
def test_list_orders_ended_rows_by_the_structured_month_for_any_as_of(today):
    """목록 정렬은 글('내년 3월쯤 다시 받아요')을 되읽지 않고 Window.month 로 한다: 기준일이 바뀌어도 다음 철이 가까운 순이다."""
    from app.catalog import build_catalog
    from app.catalog.layout import groups_of
    cat = build_catalog(load_tables(Path(__file__).resolve().parents[2] / "data" / "tables", today), today)
    groups = {g.id: g for g in groups_of(cat.entries, None, cat.as_of)}
    ended = groups.get("ended")
    if ended is None:
        pytest.skip("이 기준일에는 끝난 묶음이 없다")
    gaps = [((r.entry.window_month or 0) - today.month) % 12 for r in ended.rows if r.entry.window_month is not None]
    assert gaps == sorted(gaps) and gaps
    for r in ended.rows:
        if r.entry.window_month is not None:
            assert r.show_main.endswith("월쯤 다시 받아요") and f"{r.entry.window_month}월쯤" in r.show_main
            assert r.show_main.split()[0] in ("올해", "내년")


def test_result_screen_next_season_days_use_the_month_not_the_text():
    from app.catalog.texts import Window
    from app.ui.result_view import _days_to_next
    w = Window("올해 신청은 끝났어요 · 내년 3월쯤 다시 받아요", RANK_LATER, None, False, 3)
    assert _days_to_next(w, date(2026, 11, 13)) == 4 * 30 and _days_to_next(w, date(2027, 1, 20)) == 2 * 30
    assert _days_to_next(Window("언제 받는지는 창구에 물어보세요", 4, None, False), date(2026, 11, 13)) is None


def test_ended_season_in_the_same_month_says_next_year():
    from app.catalog.texts import next_season
    assert next_season(1, date(2026, 1, 17)) == "내년 1월쯤 다시 받아요"            # 마감(1월 16일)이 이미 지난 철: 달이 같아도 내년
    assert next_season(12, date(2026, 11, 13)) == "올해 12월쯤 다시 받아요"
