"""공고 읽기 지시문 v4: 이름표는 '누가 받을 수 있는지' 조건만(날짜·장소·금액 모양은 코드가 떨어뜨림), 접수처는 따로 낸다.

저장된 v3 공고 파일과 옛 녹화(notice-v3)는 그대로 읽히고 재생된다.
"""
import json
from datetime import date

import pytest
from notice_fixtures import BUNDLE, DOC_N1, N1_CROPS, N1_TAGS, ROOT, draft, program
from notice_loop_fixtures import call, result

from app.agents.notice import PROMPT_PATH, PROMPT_VER, NoticeResult, run_notice
from app.catalog import build_catalog, load_notices
from app.catalog.publish import publish_notice
from app.data_layer.tables import load_tables
from app.tools.draft_checks import run, squash, strip_bad_tags, tag_problem
from app.tools.models import DraftTag, ToolLog

SQ = squash(DOC_N1.text)
WHERE_LINE = next(line for page in DOC_N1.pages for line in page.lines if "접수장소" in line)
READ = date(2026, 11, 14)
NAME_QUOTE = "사 업 명 제주산 주요 농산물 물류비 지원사업"


def _tag(label: str, quote: str = N1_CROPS) -> DraftTag:
    return DraftTag(label=label, quote=quote)


# --- 이름표는 조건만 -------------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "20kg당 1,300~2,000원",            # 두 범위를 하나로 합친 금액
    "하루 8만원대 최대 70일",
    "신청 11. 10.~12. 4.",              # 날짜
    "11월 10일부터",
    "2026년 신청",
    "접수처 감귤유통과",                # 장소
    "신청방법 방문·우편",
    "문의 감귤유통과",
    "최대 5천만 원",                     # 지원 한도 금액
    "1,000만원 이내",
    "1억원 이하",
])
def test_labels_that_are_not_conditions_are_dropped_by_code(label):
    got = tag_problem(_tag(label), SQ)
    assert got is not None and got[0] == "TAG_NOT_CONDITION" and "누가 받을 수 있는지" in got[1]


@pytest.mark.parametrize("label", [
    "농업경영체 등록 농가·법인", "65세 이상", "농외소득 3,700만원 미만", "1,000㎡ 이상 재배",
    "연 소득 4천만원 이하", "연매출 1억원 이하", "출산 전90일~후120일 신청", "감귤 농가", "상반기 못 냈거나 변경 희망", "월동무·양배추·당근·양파",
])
def test_real_conditions_pass_even_with_numbers(label):
    assert tag_problem(_tag(label), SQ) is None


def test_the_cheap_checks_keep_their_old_codes():
    assert tag_problem(_tag("", N1_CROPS), SQ)[0] == "TAG_EMPTY"
    assert tag_problem(_tag("가" * 30), SQ)[0] == "TAG_TOO_LONG"
    assert tag_problem(_tag("20kg당 1,300~2,000원", "원문에 없는 문장입니다"), SQ)[0] == "TAG_NOT_CONDITION"


def test_validate_draft_gives_the_model_a_red_error_for_each_such_tag():
    d = draft(program(tags=(*N1_TAGS[:2], ("20kg당 1,300~2,000원", N1_CROPS), ("신청 7월 22일~8월 4일", N1_CROPS))))
    got = [(i.code, i.field, i.level) for i in run(d, DOC_N1, BUNDLE)]
    assert got == [("TAG_NOT_CONDITION", "tags.2", "RED"), ("TAG_NOT_CONDITION", "tags.3", "RED")]


def test_strip_bad_tags_drops_them_and_reports_the_labels():
    d = draft(program(tags=(*N1_TAGS[:2], ("20kg당 1,300~2,000원", N1_CROPS))))
    kept, dropped = strip_bad_tags(d, DOC_N1)
    assert [t.label for t in kept.programs[0].tags] == [t[0] for t in N1_TAGS[:2]] and dropped == ("20kg당 1,300~2,000원",)


class Script:
    provider = model = "x"

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def generate(self, req):
        self.seen.append(req)
        return self.steps.pop(0)


def test_loop_with_a_fake_model_returns_the_error_then_drops_a_tag_it_never_fixes():
    bad = draft(program(tags=(*N1_TAGS[:3], ("20kg당 1,300~2,000원", N1_CROPS)))).model_dump(mode="json")
    client = Script(result((call(1, "validate_draft", draft=bad),)),
                    result((call(2, "finish", decision="NEEDS_STAFF", reason="이름표를 못 고쳤습니다"),)))
    res = run_notice(DOC_N1, BUNDLE, client, ToolLog())
    assert "TAG_NOT_CONDITION" in client.seen[1].messages[-1].tool_results[0].content
    assert res.dropped_tags == ("20kg당 1,300~2,000원",) and len(res.programs[0].tags) == 3


# --- 접수처 ----------------------------------------------------------------------------------

def _published(tmp_path, **fields):
    res = NoticeResult(programs=(program(action="NEW", match_id=None, program_key="X-NEW", name=("제주산 물류비 지원", NAME_QUOTE),
                                         tags=N1_TAGS, **fields),), decision="DRAFT_READY")
    rep = publish_notice(res, DOC_N1, url=None, read_date=READ, root=tmp_path, bundle=BUNDLE)
    assert rep.written, rep.skipped
    return json.loads(rep.written[0].read_text(encoding="utf-8"))


def test_office_field_with_a_verified_quote_becomes_apply_where(tmp_path):
    rec = _published(tmp_path, office=("제주특별자치도 감귤유통과", WHERE_LINE))
    assert rec["apply_where"] == WHERE_LINE.strip()


@pytest.mark.parametrize("office", [("없음", ""), ("없음", "공고에 없습니다"), ("어딘가", "원문에 없는 문장입니다")])
def test_no_office_or_an_unverified_one_is_left_empty_never_invented(tmp_path, office):
    assert _published(tmp_path, office=office)["apply_where"] == ""


def test_the_word_none_in_the_office_field_is_not_a_red_error():
    d = draft(program(office=("없음", "")))
    assert [i for i in run(d, DOC_N1, BUNDLE) if i.field == "office"] == []


def test_a_notice_without_the_field_still_reads_and_the_where_box_shows_the_new_line(tmp_path):
    out = tmp_path / "notices"
    out.mkdir()
    base = {"version": 1, "name": "시험 사업", "agency": "", "apply_period": "", "target": "", "content": "",
            "tags": [{"label": "감귤 농가", "quote": "감귤 농가"}, {"label": "경영체 등록", "quote": "경영체 등록 농가"}],
            "url": None, "read_date": "2026-11-14", "decision": "DRAFT_READY", "table_key": None}
    (out / "old.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    (out / "new.json").write_text(json.dumps({**base, "name": "새 사업", "apply_where": "접수장소: 감귤유통과"}, ensure_ascii=False),
                                  encoding="utf-8")
    notes = {n.name: n for n in load_notices(out)}
    assert notes["시험 사업"].apply_where == "" and notes["새 사업"].apply_where == "접수장소: 감귤유통과"
    cat = build_catalog(load_tables(ROOT / "data" / "tables", READ), READ, notices=list(notes.values()))
    shown = {e.title: e for e in cat.entries if e.kind == "notice"}
    assert shown["시험 사업"].new_where == () and shown["새 사업"].new_where == ("접수장소: 감귤유통과",)


def test_agency_stays_as_written_in_the_notice(tmp_path):
    rec = _published(tmp_path, agency=("제주특별자치도 감귤유통과", WHERE_LINE))
    assert rec["agency"] == "제주특별자치도 감귤유통과"


def test_agency_that_is_not_in_its_own_quote_is_left_empty(tmp_path):
    assert _published(tmp_path, agency=("농정과", WHERE_LINE))["agency"] == ""      # 인용에 없는 부서 이름은 싣지 않는다


# --- 지시문 v4와 옛 녹화 ----------------------------------------------------------------------

def test_prompt_v4_text():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert PROMPT_VER == "notice-v4" and PROMPT_PATH.name == "notice-v4.txt" and (PROMPT_PATH.parent / "notice-v3.txt").is_file()
    for must in ("3~4개", "12자 안팎", "쉬운 말", "누가 받을 수 있는지", "날짜·장소·금액은 이름표로 내지 않", "office", "없음",
                 "지어내지", "부서 이름 그대로", "합치거나 고쳐 쓰지"):
        assert must in text, must


def test_a_replayed_recording_keeps_its_own_prompt_version():
    class Replayed(Script):
        def __init__(self, ver):
            super().__init__()
            self.recording = type("R", (), {"prompt_ver": ver})()

        def generate(self, req):
            self.seen.append(req)
            return result()                     # 도구 없이 끝나 루프가 멈춘다

    old, new, unknown = Replayed("notice-v3"), Replayed("notice-v4"), Replayed("notice-v0")
    for c in (old, new, unknown):
        run_notice(DOC_N1, BUNDLE, c, ToolLog())
    assert old.seen[0].system == (PROMPT_PATH.parent / "notice-v3.txt").read_text(encoding="utf-8")
    assert new.seen[0].system == PROMPT_PATH.read_text(encoding="utf-8")
    assert unknown.seen[0].system == PROMPT_PATH.read_text(encoding="utf-8")       # 모르는 판 이름은 따르지 않는다
