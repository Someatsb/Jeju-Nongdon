"""공고를 읽은 뒤 목록에 올리기(app/catalog/publish.py)와 notice 명령의 --url·출처 줄·--no-catalog(설계서 B-3)."""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

import pytest  # noqa: E402
from notice_fixtures import BUNDLE, DOC_N1, N1_APPLICANT, N1_CROPS, N1_PERIOD, N1_TAGS, NOTICES, ROOT, program  # noqa: E402
from notice_loop_fixtures import SCRIPT_N1, call, record, result  # noqa: E402

from app.agents.llm.scripted import ScriptedClient  # noqa: E402
from app.agents.notice import NoticeResult  # noqa: E402
from app.catalog import build_catalog, load_notices  # noqa: E402
from app.catalog.publish import publish_notice  # noqa: E402
from app.cli import main  # noqa: E402
from app.data_layer.docs_in import extract  # noqa: E402
from app.data_layer.notice_url import UrlNotice, parse_notice_page  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402
from app.tools.models import NoticeDraft  # noqa: E402

READ = date(2026, 11, 14)
SGP_URL = "https://www.seogwipo.go.kr/info/news/notice.htm?act=view&seq=155891572"
NAME_QUOTE = "제주산 주요 농산물 물류비 지원사업"


def res(*programs, decision="DRAFT_READY") -> NoticeResult:
    return NoticeResult(programs=tuple(programs), decision=decision)


def publish(tmp_path, r, doc=DOC_N1, url=None):
    return publish_notice(r, doc, url=url, read_date=READ, root=tmp_path, bundle=BUNDLE)


def written(tmp_path):
    return sorted((tmp_path / "data" / "catalog" / "notices").glob("*.json"))


def new_program(**over):
    kw = dict(action="NEW", match_id=None, program_key="X-NEW-LOGI", name=("제주산 물류비 지원", NAME_QUOTE),
              apply_start=("2026-07-22", N1_PERIOD), apply_end=("2026-08-04", N1_PERIOD), crop_in=(["월동무", "양배추", "당근", "양파"], N1_CROPS),
              applicant=("농협경유", N1_APPLICANT), tags=N1_TAGS)
    kw.update(over)
    return program(**kw)


NO_WHEN = dict(apply_start=(None, ""), apply_end=(None, ""))          # 기간 칸이 비어 있는 초안


# --- 올리는 조건 -----------------------------------------------------------------------------

def test_published_file_has_verbatim_quotes_url_and_date(tmp_path):
    rep = publish(tmp_path, res(new_program()), url=SGP_URL)
    assert [p.name for p in rep.written] == ["제주산_물류비_지원.json"] and rep.skipped == []
    rec = json.loads(rep.written[0].read_text(encoding="utf-8"))
    assert rec["version"] == 1 and rec["name"] == "제주산 물류비 지원" and rec["url"] == SGP_URL and rec["read_date"] == "2026-11-14"
    assert rec["decision"] == "DRAFT_READY" and rec["table_key"] is None
    assert rec["apply_period"] == N1_PERIOD                                            # 원문 그대로(같은 인용은 한 번만)
    assert rec["target"].splitlines() == [N1_APPLICANT, N1_CROPS]
    assert [t["label"] for t in rec["tags"]] == [t[0] for t in N1_TAGS] and all(t["quote"] for t in rec["tags"])
    assert (tmp_path / "data" / "tables").exists() is False                            # 표는 건드리지 않는다


def test_same_scheme_as_table_is_marked_and_not_shown_twice(tmp_path):
    rep = publish(tmp_path, res(program(tags=N1_TAGS, match_id="JEJU-LOGI@2026-27")), url=SGP_URL)
    rec = json.loads(rep.written[0].read_text(encoding="utf-8"))
    assert rec["name"] == "제주산 농산물 물류비 지원" and rec["table_key"] == "JEJU-LOGI"      # 이름이 없으면 표의 같은 제도 이름
    tables = load_tables(ROOT / "data" / "tables", READ)
    cat = build_catalog(tables, READ, notices=load_notices(tmp_path / "data" / "catalog" / "notices"))
    assert cat.count == 28 and cat.hidden_notices == 1


def test_unreadable_blocked_and_not_relevant_are_not_published(tmp_path):
    for decision, word in (("UNREADABLE", "읽을 수 없는"), ("BLOCKED_PII", "개인정보"), ("NOT_RELEVANT", "농가에 닿는")):
        rep = publish(tmp_path, res(new_program(), decision=decision))
        assert rep.written == [] and word in rep.skipped[0]
    assert publish(tmp_path, res(new_program()), doc=None).skipped == ["문서를 읽지 못해 목록에 올리지 않았습니다"]
    assert "사업이 없어" in publish(tmp_path, res()).skipped[0]
    assert written(tmp_path) == []


def test_needs_staff_draft_is_published_when_the_conditions_hold(tmp_path):
    assert publish(tmp_path, res(new_program(), decision="NEEDS_STAFF")).written                # 읽을 수 있고 농가 대상이면 직원 확정 없이


def test_needs_a_name_checked_against_the_text_or_the_table(tmp_path):
    rep = publish(tmp_path, res(new_program(name=("지어낸 사업 이름", "원문에 없는 문장"))))
    assert rep.written == [] and "이름을 원문에서 확인하지 못해" in rep.skipped[0]
    assert publish(tmp_path, res(program(action="NEW", match_id=None, program_key="X", tags=N1_TAGS))).written == []


def test_needs_two_verified_tags_and_wrong_ones_are_left_out(tmp_path):
    bad = ("지어낸 조건", "원문에 없는 문장입니다")
    rep = publish(tmp_path, res(new_program(tags=(N1_TAGS[0], bad), **NO_WHEN)))          # 이름표 하나뿐, 기간·접수처도 없음
    assert rep.written == [] and "이름표가 하나뿐이고 원문과 맞는 기간·접수처가 없어" in rep.skipped[0]
    rep = publish(tmp_path, res(new_program(tags=(*N1_TAGS[:2], bad))))
    assert [t["label"] for t in json.loads(rep.written[0].read_text(encoding="utf-8"))["tags"]] == [t[0] for t in N1_TAGS[:2]]


def test_tags_are_capped_at_four_and_deduplicated(tmp_path):
    many = (*N1_TAGS, ("월동무·양배추·당근·양파", N1_CROPS), ("해상운송비 일부 지원", "출하한 생산자에 대해 해상운송비 일부 지원"),
            ("자조금 가입 증명서", "자조금 가입 증명서 농협은 명단 제출"))
    rec = json.loads(publish(tmp_path, res(new_program(tags=many))).written[0].read_text(encoding="utf-8"))
    labels = [t["label"] for t in rec["tags"]]
    assert len(labels) == 4 == len(set(labels))


def test_fields_whose_quote_is_not_in_the_text_are_left_out(tmp_path):
    prog = new_program(applicant=("농협경유", "원문에 없는 인용문"), apply_end=("2026-08-04", "역시 원문에 없는 인용문"))
    rec = json.loads(publish(tmp_path, res(prog)).written[0].read_text(encoding="utf-8"))
    assert rec["apply_period"] == N1_PERIOD and rec["target"] == N1_CROPS             # 대조에 실패한 칸의 글은 싣지 않는다


def test_personal_info_in_a_quote_never_gets_written(tmp_path):
    from app.data_layer.docs_in import extract as ex

    doc = ex(DOC_N1.text + "\n담당자 문의 010-1234-5678 에 전화하세요")
    prog = new_program(applicant=("농협경유", "담당자 문의 010-1234-5678 에 전화하세요"))
    rec = json.loads(publish(tmp_path, res(prog), doc=doc).written[0].read_text(encoding="utf-8"))
    assert "010-1234-5678" not in json.dumps(rec, ensure_ascii=False)


def test_link_only_for_official_addresses(tmp_path):
    ok = json.loads(publish(tmp_path, res(new_program()), url="https://www.jejusi.go.kr/x").written[0].read_text(encoding="utf-8"))
    assert ok["url"] == "https://www.jejusi.go.kr/x"
    shutil.rmtree(tmp_path / "data")
    bad = json.loads(publish(tmp_path, res(new_program()), url="https://newsseoul.co.kr/news/1").written[0].read_text(encoding="utf-8"))
    assert bad["url"] is None


def test_rerun_of_same_notice_overwrites_but_same_name_from_another_notice_gets_a_suffix(tmp_path):
    first = publish(tmp_path, res(new_program()), url=SGP_URL).written[0]
    again = publish(tmp_path, res(new_program()), url=SGP_URL).written[0]
    long_a, long_b = "가" * 40 + "하나", "가" * 40 + "둘"                 # 앞 40자가 같은 서로 다른 사업 이름은 파일 이름이 겹쳐 꼬리표가 붙는다
    a = publish(tmp_path, res(new_program(name=(long_a, NAME_QUOTE))), url="https://www.jejusi.go.kr/a2").written[0]
    b = publish(tmp_path, res(new_program(name=(long_b, NAME_QUOTE))), url="https://www.jejusi.go.kr/other").written[0]
    assert first == again and a != b and b.name.startswith("가" * 40 + "-") and len(written(tmp_path)) == 3
    same = publish(tmp_path, res(new_program()), url="https://www.jejusi.go.kr/other")     # 같은 사업의 다른 주소 글은 올리지 않는다
    assert same.written == [] and len(written(tmp_path)) == 3
    assert not list((tmp_path / "data" / "catalog" / "notices").glob("*.tmp"))


# --- notice 명령 -----------------------------------------------------------------------------

def _root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "data" / "tables", tmp_path / "data" / "tables")
    return tmp_path


def _client(doc, script):
    return ScriptedClient(record(doc, script))


def test_cli_publishes_after_a_run_and_says_so(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["notice", str(NOTICES / "N1.txt")], root=root, llm=_client(DOC_N1, SCRIPT_N1)) == 0
    out = capsys.readouterr().out
    assert "지원 전체 보기에 올렸습니다" in out
    (rec,) = written(root)
    assert json.loads(rec.read_text(encoding="utf-8"))["table_key"] == "JEJU-LOGI" and len(json.loads(rec.read_text(encoding="utf-8"))["tags"]) == 4


def test_cli_no_catalog_flag_writes_nothing(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["notice", str(NOTICES / "N1.txt"), "--no-catalog"], root=root, llm=_client(DOC_N1, SCRIPT_N1)) == 0
    assert not (root / "data" / "catalog").exists() and "지원 전체 보기" not in capsys.readouterr().out


def test_replay_never_writes_to_the_catalog(tmp_path):
    from app import replay_cli

    root = _root(tmp_path)
    for name in ("N1.json", "N1.txt"):
        (root / "data" / "replay").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "data" / "replay" / name, root / "data" / "replay" / name)
    assert replay_cli.main(["N1"], root=root) == 0
    assert not (root / "data" / "catalog").exists()


def test_cli_uses_the_source_line_of_a_text_file_as_the_link(tmp_path):
    root = _root(tmp_path)
    src = tmp_path / "공고.txt"
    src.write_text(f"출처: {SGP_URL}\n" + (NOTICES / "N1.txt").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["notice", str(src)], root=root, llm=_client(extract(src), SCRIPT_N1)) == 0
    (rec,) = written(root)
    assert json.loads(rec.read_text(encoding="utf-8"))["url"] == SGP_URL


PAGE = (ROOT / "tests" / "fixtures" / "notice_pages" / "sgp_fta_citrus_facility_2027.html").read_text(encoding="utf-8")


def _url_script(doc):
    period = "가. 신청기간: 2026. 11. 9.(월) ~ 11. 23.(월) (15일간)"
    prog = program(action="NEW", match_id=None, program_key="SGP-FTA-CITRUS",
                   name=("FTA기금 감귤 고품질시설현대화 지원사업", "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"),
                   apply_start=("2026-11-09", period), apply_end=("2026-11-23", period),
                   tags=(("감귤 과수 농가", "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"), ("지역 농·감협 소속", "나. 접수처: 지역 농·감협"),
                         ("감귤 시설 16개 사업", "다. 신청사업: 16개사업")))
    draft = NoticeDraft(programs=(prog,)).model_dump(mode="json")
    return [result((call(1, "validate_draft", draft=draft),)), result((call(2, "finish", decision="DRAFT_READY", reason="신청 계획 공고"),))]


def test_cli_reads_a_url_and_publishes_with_that_address(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    fetched = parse_notice_page(SGP_URL, PAGE)
    monkeypatch.setattr("app.cli.fetch_notice", lambda url: UrlNotice(fetched.doc, url, fetched.title, 0))
    assert main(["notice", "--url", SGP_URL], root=root, llm=_client(fetched.doc, _url_script(fetched.doc))) == 0
    out = capsys.readouterr().out
    assert "DRAFT_READY" in out and "올렸습니다" in out
    (inbox,) = [p for p in (root / "data" / "inbox").iterdir() if p.is_dir()]
    assert inbox.name.startswith("url-") and "FTA기금" in (inbox / "report.html").read_text(encoding="utf-8")
    (rec,) = written(root)
    data = json.loads(rec.read_text(encoding="utf-8"))
    assert data["url"] == SGP_URL and data["apply_period"] == "가. 신청기간: 2026. 11. 9.(월) ~ 11. 23.(월) (15일간)"
    assert data["table_key"] is None and len(data["tags"]) == 3
    from app.catalog import load_catalog

    cat = load_catalog(root, load_tables(root / "data" / "tables", READ), READ)
    assert cat.entries[0].title == "FTA기금 감귤 고품질시설현대화 지원사업" and cat.entries[0].link.url == SGP_URL


@pytest.mark.parametrize("argv,word", [(["notice", "--url", "https://www.naver.com/x"], "받을 수 있는 곳"),
                                       (["notice", "--url", "http://www.seogwipo.go.kr/x"], "https://"),
                                       (["notice"], "사용법"), (["notice", "a.txt", "--url", SGP_URL], "하나만")])
def test_cli_url_errors_are_korean_and_exit_two(tmp_path, capsys, argv, word):
    assert main(argv, root=_root(tmp_path), llm=ScriptedClient(record(DOC_N1, SCRIPT_N1))) == 2
    assert word in capsys.readouterr().out


# --- 이름표 규칙(v4): 조건 이름표 1개 + 원문과 맞는 기간·접수처 ----------------------------------

def _tags_of(rep):
    return json.loads(rep.written[0].read_text(encoding="utf-8"))["tags"]


def test_one_tag_with_a_verified_period_is_published(tmp_path):
    rep = publish(tmp_path, res(new_program(tags=N1_TAGS[:1])))
    assert len(rep.written) == 1 and rep.skipped == [] and len(_tags_of(rep)) == 1


def test_one_tag_with_a_verified_office_only_is_published(tmp_path):
    rep = publish(tmp_path, res(new_program(tags=N1_TAGS[:1], office=("지역 농협", N1_APPLICANT), **NO_WHEN)))
    assert len(rep.written) == 1


def test_one_tag_with_no_period_or_office_is_not_published(tmp_path):
    rep = publish(tmp_path, res(new_program(tags=N1_TAGS[:1], **NO_WHEN)))
    assert rep.written == [] and "이름표가 하나뿐이고 원문과 맞는 기간·접수처가 없어" in rep.skipped[0]


def test_one_tag_whose_period_or_office_does_not_match_the_text_is_not_published(tmp_path):
    prog = new_program(tags=N1_TAGS[:1], apply_start=("2026-11-09", "원문에 없는 기간"), apply_end=("2026-11-23", "역시 없는 기간"),
                       office=("지역 농협", "원문에 없는 접수처"))
    assert publish(tmp_path, res(prog)).written == []
    none_office = new_program(tags=N1_TAGS[:1], office=("없음", N1_APPLICANT), **NO_WHEN)       # 접수처가 '없음'이라고 읽은 것은 접수처가 아니다
    assert publish(tmp_path, res(none_office)).written == []


def test_zero_verified_tags_is_never_published_even_with_a_period(tmp_path):
    bad = ("지어낸 조건", "원문에 없는 문장입니다")
    rep = publish(tmp_path, res(new_program(tags=(bad,))))
    assert rep.written == [] and "원문과 맞는 조건 이름표가 없어" in rep.skipped[0]
    rep = publish(tmp_path, res(new_program(tags=())))
    assert rep.written == [] and "원문과 맞는 조건 이름표가 없어" in rep.skipped[0]


def test_two_tags_are_enough_without_a_period_or_office(tmp_path):
    rep = publish(tmp_path, res(new_program(tags=N1_TAGS[:2], **NO_WHEN)))
    assert len(rep.written) == 1


# --- 저장된 파일을 읽을 때의 같은 규칙 ----------------------------------------------------------

def _stored(tmp_path, tags, **over):
    d = tmp_path / "notices"
    d.mkdir(exist_ok=True)
    raw = {"version": 1, "name": "시험 공고", "agency": "", "apply_where": "", "apply_period": "", "target": "", "content": "",
           "tags": [{"label": f"조건{i}", "quote": f"근거{i}", "anchor": None} for i in range(tags)], "url": None,
           "read_date": "2026-11-14", "decision": "DRAFT_READY", "table_key": None}
    raw.update(over)
    (d / "a.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return load_notices(d)


def test_stored_file_rule_matches_the_publish_rule(tmp_path):
    assert len(_stored(tmp_path, 2)) == 1                                               # 이름표 둘이면 기간·접수처 없이도
    assert len(_stored(tmp_path, 1, apply_period="신청기간 11. 9.~11. 23.")) == 1
    assert len(_stored(tmp_path, 1, apply_where="지역 농협")) == 1
    assert _stored(tmp_path, 1) == []
    assert _stored(tmp_path, 0, apply_period="신청기간 11. 9.~11. 23.") == []


def test_every_stored_notice_in_the_repo_still_loads():
    assert len(load_notices(ROOT / "data" / "catalog" / "notices")) == 5


# --- 같은 주소의 공고는 바꾼다 ----------------------------------------------------------------

RENAMED = ("제주산 주요 농산물 물류비 지원사업", NAME_QUOTE)


def test_same_address_with_a_new_name_replaces_the_old_file(tmp_path):
    old = publish(tmp_path, res(new_program()), url=SGP_URL).written[0]
    rep = publish(tmp_path, res(new_program(name=RENAMED)), url=SGP_URL)
    assert [p.name for p in written(tmp_path)] == [rep.written[0].name] and rep.written[0] != old
    assert rep.replaced == [old.name] and not old.exists()
    assert json.loads(rep.written[0].read_text(encoding="utf-8"))["name"] == RENAMED[0]
    assert [n.name for n in load_notices(tmp_path / "data" / "catalog" / "notices")] == [RENAMED[0]]


def test_same_name_same_address_is_a_plain_overwrite_and_says_nothing_about_replacing(tmp_path):
    publish(tmp_path, res(new_program()), url=SGP_URL)
    rep = publish(tmp_path, res(new_program()), url=SGP_URL)
    assert rep.replaced == [] and len(written(tmp_path)) == 1


def test_other_addresses_and_missing_addresses_are_never_replaced(tmp_path):
    publish(tmp_path, res(new_program()), url=SGP_URL)
    publish(tmp_path, res(new_program(name=RENAMED)), url="https://www.jejusi.go.kr/other")
    rep = publish(tmp_path, res(new_program(name=("제주산 물류비 지원 안내", NAME_QUOTE))), url=None)             # 주소 없는 입력은 이름으로만
    assert rep.replaced == [] and len(written(tmp_path)) == 3
    rep = publish(tmp_path, res(new_program(name=("제주산 물류비 지원 안내 둘째", NAME_QUOTE))), url=None)
    assert rep.replaced == [] and len(written(tmp_path)) == 4


def test_two_programs_of_one_notice_do_not_replace_each_other(tmp_path):
    first = new_program()
    second = new_program(name=RENAMED, program_key="X-NEW-LOGI-2")
    rep = publish(tmp_path, res(first, second), url=SGP_URL)
    assert len(rep.written) == 2 and rep.replaced == [] and len(written(tmp_path)) == 2


def test_nothing_is_deleted_when_the_new_reading_is_not_published(tmp_path):
    old = publish(tmp_path, res(new_program()), url=SGP_URL).written[0]
    rep = publish(tmp_path, res(new_program(tags=N1_TAGS[:1], **NO_WHEN)), url=SGP_URL)
    assert rep.written == [] and old.exists() and rep.replaced == []


def test_cli_says_when_it_replaced_an_old_notice(tmp_path, capsys):
    root = _root(tmp_path)
    old = publish(root, res(new_program()), url=SGP_URL).written[0]
    src = tmp_path / "공고.txt"
    src.write_text(f"출처: {SGP_URL}\n" + (NOTICES / "N1.txt").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["notice", str(src)], root=root, llm=_client(extract(src), SCRIPT_N1)) == 0
    out = capsys.readouterr().out
    assert "같은 주소의 옛 공고를 바꿨습니다" in out and old.name in out and not old.exists()


def test_scout_report_cell_mentions_the_replacement():
    from app.ui.report_scout import _upload_cell

    assert "같은 주소의 옛 공고를 바꿨어요" in _upload_cell({"published": ["a.json"], "replaced": ["b.json"]})
    assert "바꿨습니다" not in _upload_cell({"published": ["a.json"], "replaced": []})
