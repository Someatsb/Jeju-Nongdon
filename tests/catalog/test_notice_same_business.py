"""같은 사업의 다른 글이 겹쳐 올라가지 않게 한다: 이름 견주기(business_key), 올릴 때의 막기·바꾸기, 읽을 때의 안전 장치."""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

import pytest  # noqa: E402
from notice_fixtures import BUNDLE, DOC_N1, N1_APPLICANT, N1_CROPS, N1_PERIOD, N1_TAGS, ROOT, program  # noqa: E402

from app.agents.notice import NoticeResult  # noqa: E402
from app.catalog import build_catalog, load_notices  # noqa: E402
from app.catalog.notices import business_key  # noqa: E402
from app.catalog.publish import publish_notice  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402

READ = date(2026, 11, 14)
LIVE = Path(__file__).resolve().parents[1] / "fixtures" / "scout_live"
QUOTE = "제주산 주요 농산물 물류비 지원사업"
URL_A, URL_B = "https://www.jejusi.go.kr/a", "https://www.seogwipo.go.kr/b"

SAME = [
    ("FTA기금 과수(감귤) 고품질시설현대화 지원사업", "FTA기금 과수(감귤) 고품질시설 현대화사업"),
    ("유기농업자재 지원사업", "유기농업자재지원사업"),
    ("2027년 유기질비료 지원사업(추가 신청)", "유기질비료 지원사업"),
    ("2027년도 유기질비료 지원사업", "유기질비료 지원사업 (추가 접수)"),
    ("제주 감귤·만감류 지원사업", "제주 감귤 만감류 지원사업"),
]
DIFFERENT = [
    ("농촌융복합산업 자금(융자) 지원사업", "농촌융복합산업 자금 지원사업"),      # (융자)는 사업 구분이라 덧말이 아니다
    ("유기질비료 지원사업", "유기질비료 운송비 지원사업"),                       # 한쪽이 다른 쪽을 품는 것만으로는 같지 않다
    ("FTA기금 과수(감귤) 고품질시설현대화 지원사업", "FTA기금 과수 고품질시설현대화 지원사업"),
    ("유기농업자재 지원사업", "유기질비료 지원사업"),
    ("청년농업인 정책자금 이자보전 지원사업", "청년농업인 정책자금 지원사업"),
]


@pytest.mark.parametrize("a,b", SAME)
def test_same_business_names(a, b):
    assert business_key(a) and business_key(a) == business_key(b)


@pytest.mark.parametrize("a,b", DIFFERENT)
def test_different_business_names(a, b):
    assert business_key(a) != business_key(b)


def test_empty_after_stripping_has_no_key():
    assert business_key("2027년 지원사업") is None and business_key("") is None and business_key("(추가 신청)") is None


def _prog(name, **over):
    kw = dict(action="NEW", match_id=None, program_key="X-NEW-LOGI", name=(name, QUOTE),
              apply_start=("2026-07-22", N1_PERIOD), apply_end=("2026-08-04", N1_PERIOD), crop_in=(["월동무"], N1_CROPS),
              applicant=("농협경유", N1_APPLICANT), tags=N1_TAGS)
    kw.update(over)
    return program(**kw)


def _pub(tmp_path, name, url, **over):
    return publish_notice(NoticeResult(programs=(_prog(name, **over),), decision="DRAFT_READY"), DOC_N1, url=url,
                          read_date=READ, root=tmp_path, bundle=BUNDLE)


def _files(tmp_path):
    return sorted((tmp_path / "data" / "catalog" / "notices").glob("*.json"))


WHERE = dict(office=("지역 농협", N1_APPLICANT))


def test_same_business_is_not_published_again(tmp_path):
    first = _pub(tmp_path, "유기농업자재 지원사업", URL_A)
    rep = _pub(tmp_path, "유기농업자재지원사업", URL_B)
    assert rep.written == [] and len(_files(tmp_path)) == 1 and _files(tmp_path)[0] == first.written[0]
    assert rep.skipped == ["이미 목록에 있는 사업이라 올리지 않았습니다: 유기농업자재 지원사업"]
    assert rep.upgraded == []


def test_newer_text_with_apply_where_replaces_the_old_one(tmp_path):
    old = _pub(tmp_path, "FTA기금 과수(감귤) 고품질시설현대화 지원사업", URL_A).written[0]
    rep = _pub(tmp_path, "FTA기금 과수(감귤) 고품질시설 현대화사업", URL_B, **WHERE)
    (only,) = _files(tmp_path)
    assert not old.exists() and rep.written == [only] and rep.skipped == []
    rec = json.loads(only.read_text(encoding="utf-8"))
    assert rec["url"] == URL_B and rec["apply_where"] and rec["name"] == "FTA기금 과수(감귤) 고품질시설 현대화사업"
    assert rep.upgraded == ["같은 사업의 더 온전한 글로 바꿨습니다: FTA기금 과수(감귤) 고품질시설현대화 지원사업"]


def test_old_with_apply_where_is_kept_even_if_new_has_one(tmp_path):
    old = _pub(tmp_path, "유기질비료 지원사업", URL_A, **WHERE).written[0]
    rep = _pub(tmp_path, "2027년 유기질비료 지원사업(추가 신청)", URL_B, **WHERE)
    assert rep.written == [] and _files(tmp_path) == [old] and "이미 목록에 있는 사업" in rep.skipped[0]


def test_different_business_is_still_published(tmp_path):
    _pub(tmp_path, "유기질비료 지원사업", URL_A)
    rep = _pub(tmp_path, "유기질비료 운송비 지원사업", URL_B)
    assert len(rep.written) == 1 and len(_files(tmp_path)) == 2 and rep.skipped == []


def test_same_address_overwrite_is_not_treated_as_duplicate(tmp_path):
    _pub(tmp_path, "유기농업자재 지원사업", URL_A)
    rep = _pub(tmp_path, "유기농업자재지원사업", URL_A)           # 같은 주소는 지금처럼 바꾼다
    assert len(rep.written) == 1 and len(_files(tmp_path)) == 1 and rep.skipped == []


def _copy_live(dst: Path, *names):
    dst.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy(LIVE / n, dst / n)


def test_real_scout_files_collapse_when_stored_by_hand(tmp_path):
    notices = tmp_path / "notices"
    _copy_live(notices, *[p.name for p in LIVE.glob("*.json")])
    for src in (ROOT / "data" / "catalog" / "notices").glob("*.json"):
        shutil.copy(src, notices / src.name)
    names = [n.name for n in load_notices(notices)]
    assert len(names) == 5 + 1, names                                           # 저장소의 다섯 개 + 청년농업인(겹치지 않음)
    assert sum("유기농업자재" in n for n in names) == 1 and sum("유기질비료" in n for n in names) == 1
    assert sum("FTA기금" in n for n in names) == 1


def test_load_prefers_the_one_with_apply_where_then_the_later_read(tmp_path):
    notices = tmp_path / "notices"
    _copy_live(notices)

    def put(fn, name, where, day):
        rec = json.loads((LIVE / "유기농업자재지원사업.json").read_text(encoding="utf-8"))
        rec.update(name=name, apply_where=where, read_date=day)
        (notices / fn).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    put("a.json", "유기농업자재 지원사업", "", "2026-11-15")
    put("b.json", "유기농업자재지원사업", "읍면동", "2026-11-01")
    assert [n.key for n in load_notices(notices)] == ["new-b"]                  # 접수처가 있는 쪽
    put("b.json", "유기농업자재지원사업", "", "2026-11-01")
    assert [n.key for n in load_notices(notices)] == ["new-a"]                  # 같으면 나중에 읽은 쪽


def test_catalog_shows_one_card_for_the_same_business(tmp_path):
    notices = tmp_path / "notices"
    _copy_live(notices, "유기농업자재지원사업.json")
    rec = json.loads((notices / "유기농업자재지원사업.json").read_text(encoding="utf-8"))
    rec["name"] = "2027년 유기농업자재 지원사업"
    (notices / "x.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    tables = load_tables(ROOT / "data" / "tables", READ)
    cat = build_catalog(tables, READ, notices=load_notices(notices))
    assert len([e for e in cat.entries if e.kind == "notice"]) == 1


def test_scout_report_cell_mentions_upgrade_and_skip():
    from app.ui.report_scout import _upload_cell

    assert "더 온전한 글로 바꿨습니다" in _upload_cell({"published": ["a.json"], "upgraded": ["같은 사업의 더 온전한 글로 바꿨습니다: 옛 이름"]})
    assert "이미 목록에 있는 사업이라 올리지 않았습니다" in _upload_cell({"published": [], "not_published": ["이미 목록에 있는 사업이라 올리지 않았습니다: 옛 이름"]})
