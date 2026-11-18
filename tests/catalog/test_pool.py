"""맞춰 볼 새 공고 고르기(app.catalog.pool): 지원 전체 보기 목록에 '새 공고'로 올라와 있고 신청이 끝나지 않은 것만."""
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.catalog import build_catalog, load_notices
from app.catalog.pool import match_pool
from app.data_layer.tables import load_tables

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 14)
BUNDLE = load_tables(ROOT / "data" / "tables", TODAY)
NOTICES = load_notices(ROOT / "tests" / "fixtures" / "catalog_notices" / "match")
BIRTH = next(n for n in NOTICES if n.key == "new-birth_helper")
KNOWN_KEY = BUNDLE.programs[0].program_key.split("@")[0].split("#")[0]


def pool(notices, today=TODAY):
    cat = build_catalog(BUNDLE, today, {}, notices)
    return match_pool(cat, notices)


def test_listed_open_notices_come_with_the_text_the_list_shows():
    got = pool(NOTICES)
    assert [r.key for r, _ in got] == [n.key for n in NOTICES]
    cat = build_catalog(BUNDLE, TODAY, {}, NOTICES)
    for rec, entry in got:
        assert entry == cat.get(rec.key) and entry.kind == "notice"


def test_notice_hidden_because_the_table_has_it_is_left_out():
    same = replace(BIRTH, key="new-same", table_key=KNOWN_KEY)
    assert [r.key for r, _ in pool([same, BIRTH])] == ["new-birth_helper"]


def test_ended_notice_is_left_out_but_unreadable_period_stays():
    ended = replace(BIRTH, key="new-ended", apply_period="2026. 10. 1.(목) ~ 11. 2.(월)")
    always = replace(BIRTH, key="new-always", apply_period="연중 상시 모집")
    assert [r.key for r, _ in pool([ended, always])] == ["new-always"]


def test_a_later_today_ends_more_notices():
    one = replace(BIRTH, key="new-one", apply_period="2026. 11. 9.(월) ~ 11. 23.(월)")
    assert len(pool([one], date(2026, 11, 23))) == 1 and pool([one], date(2026, 11, 24)) == []
