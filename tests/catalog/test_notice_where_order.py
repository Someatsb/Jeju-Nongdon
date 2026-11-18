"""새 공고의 '어디서 신청해요': 접수처 칸(apply_where)이 있으면 그것이 첫 줄이고 기관은 뒤. 없을 때만 기관이 앞."""
import dataclasses
from pathlib import Path

from app.catalog import load_notices
from app.catalog.build import _notice_texts
from app.catalog.layout import list_where

ROOT = Path(__file__).resolve().parents[2]
NOTICES = {n.name: n for n in load_notices(ROOT / "tests" / "fixtures" / "catalog_notices_polish")}
BASE = NOTICES["유기농업자재 지원사업"]
LINE = "나. 신청장소: 농지 소재지 읍면동사무소"


def test_apply_where_comes_before_agency():
    n = dataclasses.replace(BASE, agency="농업정책과", apply_where=LINE)
    assert _notice_texts(n)["where"] == ("신청장소: 농지 소재지 읍면동사무소", "농업정책과")


def test_agency_first_when_there_is_no_apply_where():
    n = dataclasses.replace(NOTICES["출산 농가도우미 지원사업"], agency="농업정책과", apply_where="")
    where = _notice_texts(n)["where"]
    assert where[0] == "공고 낸 곳: 농업정책과"


def test_list_shows_the_place_not_the_department(tmp_path):
    from datetime import date

    from app.catalog import build_catalog
    from app.data_layer.tables import load_tables
    import json
    d = tmp_path / "n"
    d.mkdir()
    for p in (ROOT / "tests" / "fixtures" / "catalog_notices_polish").glob("*.json"):
        if p.stem == BASE.key.removeprefix("new-"):
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["agency"], raw["apply_where"] = "농업정책과", LINE
            (d / p.name).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    today = date(2026, 11, 14)
    cat = build_catalog(load_tables(ROOT / "data" / "tables", today), today, notices=load_notices(d))
    e = next(x for x in cat.entries if x.kind == "notice")
    assert list_where(e) == ("농지 소재지 읍면동사무소",)


# --- 접수처가 없고 부서만 있을 때는 '공고 낸 곳:' 머리말 -------------------------------------------

def _plain(**over):
    over.setdefault("tags", BASE.tags[:1])
    return dataclasses.replace(BASE, **over)


def test_department_only_gets_the_issuer_label():
    n = _plain(agency="대륜동", apply_where="", tags=(dataclasses.replace(BASE.tags[0], quote="지원 대상 농가"),))
    assert _notice_texts(n)["where"] == ("공고 낸 곳: 대륜동",)


def test_apply_where_keeps_coming_first_without_a_label():
    n = _plain(agency="대륜동", apply_where=LINE, tags=(dataclasses.replace(BASE.tags[0], quote="지원 대상 농가"),))
    where = _notice_texts(n)["where"]
    assert where[0] == "신청장소: 농지 소재지 읍면동사무소" and not any(w.startswith("공고 낸 곳") for w in where[:1])


def test_neither_apply_where_nor_department_shows_nothing():
    n = _plain(agency="", apply_where="", tags=(dataclasses.replace(BASE.tags[0], quote="지원 대상 농가"),))
    assert _notice_texts(n)["where"] == ()


def test_the_list_cell_keeps_the_issuer_label_and_still_strips_the_others(tmp_path):
    from datetime import date

    from app.catalog import build_catalog
    from app.data_layer.tables import load_tables
    today = date(2026, 11, 14)
    tables = load_tables(ROOT / "data" / "tables", today)
    only_dept = _plain(agency="대륜동", apply_where="", tags=(dataclasses.replace(BASE.tags[0], quote="지원 대상 농가"),))
    with_where = dataclasses.replace(only_dept, key="new-b", name="다른 공고", apply_where=LINE)
    cat = build_catalog(tables, today, notices=[only_dept, with_where])
    assert list_where(cat.by_key[only_dept.key]) == ("공고 낸 곳: 대륜동",)
    assert list_where(cat.by_key["new-b"]) == ("농지 소재지 읍면동사무소",)
    from app.catalog.layout import where_line
    assert where_line("공고 낸 곳: 대륜동") == "공고 낸 곳: 대륜동"                       # 지원 안내의 '어디로'도 머리말을 떼지 않는다
