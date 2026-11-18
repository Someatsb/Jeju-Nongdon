"""새 공고 맞춰 보기를 결과 화면 뒤 작업에 붙인 것(에이전트 강화 설계서 1절, 결과 v2 6절).

- 결과 화면은 맞춰 보기를 기다리지 않는다. /counsel/ai 의 match 가 run -> done 으로 바뀐다.
- 실패·시간 초과·키 없음·새 공고 0건이면 조용히 none. 결과 화면과 종이는 그대로 나온다.
- 답을 고치면 옛 결과가 섞이지 않고, 동시에 두 상담도 섞이지 않는다.
- AI 로 나간 글에 농가의 숫자·읍면동이 없다. '안 맞음'은 어르신 칸(lines·more_names)에 안 나온다.
실제 AI·인터넷은 쓰지 않는다(가짜 LLM). 새 공고는 tests/fixtures/catalog_notices/match 의 고정본이다.
"""
import json
import shutil
import threading
import time

import pytest
from conftest import ROOT
from match_fixtures import BIRTH, FTA, LOAN, NOTICES, ORG_FERT, ORG_MAT, call, result

from app.agents.llm.base import LLMUnavailable
from app.agents.llm.payload import build_payload
from app.ui import match_job, routes_counsel
from app.ui.session import COOKIE

from .conftest import P2_FORM, P4_FORM, _started_client

DEADLINE_S = 5.0
FTA_Q = "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"
BIRTH_LINES = NOTICES[BIRTH].target.split("\n")
CITRUS_FORM = {**P4_FORM, "crop1_crop_code": "감귤_노지"}       # 애월읍 1961년생 감귤 3,600평(남성)
SHOW_TODAY = "2026-11-14"


class MatchLLM:
    """맞춰 보기 요청에만 답하는 가짜 AI(그 밖의 요청은 못 쓰는 것으로 한다). 요청 내용만 보고 답하므로 여러 상담이 같이 불러도 된다.
    gate 가 있으면 풀릴 때까지 멈춘다(안전하게 10초 뒤엔 저절로 푼다)."""
    provider = model = "fake"

    def __init__(self, *, gate=None, fail=None):
        self.gate, self.fail = gate, fail
        self.requests, self.started = [], threading.Event()
        self._lock = threading.Lock()

    def generate(self, req):
        if req.purpose != "match":
            raise LLMUnavailable("NO_KEY")
        with self._lock:
            self.requests.append(req)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail:
            raise LLMUnavailable(self.fail)
        if req.messages[-1].tool_results:
            return result(call(10, "submit_matches", items=[
                {"notice_key": FTA, "why": "감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요", "ask": ["농협에서 받는지"]},
                {"notice_key": ORG_MAT, "why": "농사짓는 곳 사무소에서 받는 사업이라 조건을 알아봐야 해요", "ask": ["친환경 인증이 필요한지"]},
                {"notice_key": LOAN, "why": "창업 계획이 있는 분이 대상이라 맞는지 알 수 없어요", "ask": []}]))
        return result(
            call(1, "check_farmer", notice_key=FTA, kind="작물", quote=FTA_Q, crops=["감귤"]),
            call(2, "check_farmer", notice_key=BIRTH, kind="성별", quote=BIRTH_LINES[0], choice="여성"),
            call(4, "check_farmer", notice_key=ORG_MAT, kind="그 밖", quote="나. 신청장소: 농지 소재지 읍면동사무소"),
            call(5, "check_farmer", notice_key=LOAN, kind="그 밖", quote=NOTICES[LOAN].target))


@pytest.fixture
def catalog_dir(tmp_path):
    d = tmp_path / "catalog"
    shutil.copytree(ROOT / "tests" / "fixtures" / "catalog_notices" / "match", d / "notices")
    shutil.copy(ROOT / "data" / "catalog" / "links.csv", d / "links.csv")
    return d


def start(catalog_dir, llm, monkeypatch):
    monkeypatch.setenv("JEJU_SHOW_TODAY", SHOW_TODAY)         # 시연 서버의 '오늘'(목록과 같은 기준일)
    return _started_client(["--asof", "2026-11-13", "--catalog-dir", str(catalog_dir)], llm=llm)


@pytest.fixture
def app_client(catalog_dir, monkeypatch):
    made = []

    def make(llm, catalog=None):
        c = start(catalog or catalog_dir, llm, monkeypatch)
        made.append(c)
        return c
    yield make
    for c in made:
        c.__exit__(None, None, None)


def answer(client, form):
    assert client.post("/counsel/input", data=form).status_code == 303
    assert client.post("/counsel/confirm", data={}).status_code == 303


def ai(client):
    r = client.get("/counsel/ai")
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def wait_match(client, until=("done", "none")):
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end:
        j = ai(client)
        if j["match"]["state"] in until:
            return j
        time.sleep(0.02)
    raise AssertionError(f"맞춰 보기가 끝나지 않음: {ai(client)['match']['state']}")


def staff_of(client) -> dict:
    """직원 칸 자료(서버 쪽): /counsel/ai 응답에는 없고 AiJob.paper()["match_staff"] 에만 있다."""
    from app.ui.session import COOKIE

    job = client.app.state.sessions.get(client.cookies[COOKIE])["job"]
    return job.paper()["match_staff"]


def names(*keys):
    return [NOTICES[k].name for k in keys]


def test_result_page_does_not_wait_for_match_and_match_goes_run_then_done(app_client, monkeypatch):
    gate = threading.Event()
    llm = MatchLLM(gate=gate)
    client = app_client(llm)
    answer(client, CITRUS_FORM)
    t = time.monotonic()
    page = client.get("/counsel/preview")
    assert page.status_code == 200 and time.monotonic() - t < DEADLINE_S and not gate.is_set()
    assert llm.started.wait(DEADLINE_S)
    j = ai(client)
    assert j["state"] == "done" and j["match"]["state"] == "run"          # 설명 글은 맞춰 보기를 기다리지 않고 채워진다
    assert j["match"]["lines"] == [] and j["match"]["more_names"] == []
    monkeypatch.setattr(routes_counsel, "PRINT_BUDGET_S", 0.3)           # 종이는 설명 글과 같은 한도 안에서 함께 기다리고, 끝내 안 끝나면 이 묶음 없이 뽑는다(test_new_notices.py)
    printed = client.get("/counsel/print")
    assert printed.status_code == 200 and 'data-page="front"' in printed.text and "새로 나온 공고" not in printed.text
    gate.set()
    m = wait_match(client)["match"]
    assert m["state"] == "done" and m["note"] == "조건은 창구에서 확인하세요"
    assert [ln["key"] for ln in m["lines"]] == [FTA] and m["lines"][0]["name"] == NOTICES[FTA].name
    line = m["lines"][0]
    assert line["why"].startswith("감귤 농가") and line["ask"] == ["농협에서 받는지 · 창구에 물어보세요"]
    assert line["period"] == "11월 23일까지 · 9일 남음"                    # 지원 전체 보기와 같은 글
    assert "접수처" in line["where"] and "대륜동" not in line["where"]      # 가실 곳 줄만(공고 낸 부서는 뺀다)
    assert m["more_names"] == names(ORG_MAT, ORG_FERT, LOAN)                # 알 수 없음은 이름만


def test_run_state_also_carries_an_empty_match(app_client):
    gate = threading.Event()
    llm = MatchLLM(gate=gate)
    client = app_client(llm)
    try:
        answer(client, CITRUS_FORM)
        client.get("/counsel/preview")
        m = ai(client)["match"]
        assert m["state"] == "run" and m["lines"] == [] and m["more_names"] == [] and m["note"] == "조건은 창구에서 확인하세요"
        assert m["staff"]["counts"] == {"맞을 수 있음": 0, "알 수 없음": 0, "안 맞음": 0}
    finally:
        gate.set()


def test_not_fit_stays_out_of_lines_and_more_names_but_staff_has_it(app_client):
    client = app_client(MatchLLM())
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    m = wait_match(client)["match"]
    shown = [ln["name"] for ln in m["lines"]] + m["more_names"]
    assert NOTICES[BIRTH].name not in shown and BIRTH not in str(m["lines"])
    assert set(m["staff"]) == {"source", "note", "candidates", "left_out", "counts"}      # 어르신 화면 응답에는 개수와 한 줄만(이름·근거 없음)
    assert "items" not in m["staff"] and "names" not in m["staff"] and NOTICES[BIRTH].name not in str(m["staff"])
    assert m["staff"]["counts"] == {"맞을 수 있음": 1, "알 수 없음": 3, "안 맞음": 1}
    staff = staff_of(client)
    assert staff["counts"] == {"맞을 수 있음": 1, "알 수 없음": 3, "안 맞음": 1}
    assert staff["names"]["안 맞음"] == names(BIRTH) and staff["names"]["맞을 수 있음"] == names(FTA)
    assert staff["names"]["알 수 없음"] == names(ORG_MAT, ORG_FERT, LOAN)
    assert staff["source"] == "ai" and staff["candidates"] == 5 and "확인 4번" in staff["note"]
    not_fit = next(i for i in staff["items"] if i["key"] == BIRTH)
    assert not_fit["verdict"] == "안 맞음" and [(c["kind"], c["answer"]) for c in not_fit["checks"]] == [("성별", "아니오")]


@pytest.mark.parametrize("fail", ["NO_KEY", "TIMEOUT", "OVERLOADED"])
def test_ai_failure_ends_quietly_as_none(app_client, fail):
    client = app_client(MatchLLM(fail=fail))
    answer(client, CITRUS_FORM)
    page = client.get("/counsel/preview")
    assert page.status_code == 200 and "지금 하실 일" in page.text
    j = wait_match(client)
    m = j["match"]
    assert m["state"] == "none" and m["lines"] == [] and m["more_names"] == [] and fail not in str(m)
    assert j["state"] == "done" and j["match_html"]["new_notices"] == ""
    assert m["staff"]["source"] == "none" and m["staff"]["note"]                # 직원 칸에는 이유 한 줄
    assert client.get("/counsel/print").status_code == 200


def test_no_key_at_all_gives_none(catalog_dir, monkeypatch):
    client = start(catalog_dir, None, monkeypatch)                               # 열쇠 없음: NullClient
    try:
        answer(client, CITRUS_FORM)
        client.get("/counsel/preview")
        m = wait_match(client)["match"]
        assert m["state"] == "none" and "열쇠가 없어" in m["staff"]["note"] and "NO_KEY" not in str(m)
    finally:
        client.__exit__(None, None, None)


def test_hung_ai_is_cut_at_the_hard_limit(app_client, monkeypatch):
    monkeypatch.setattr(match_job, "MATCH_HARD_S", 0.3)
    gate = threading.Event()
    client = app_client(MatchLLM(gate=gate))
    try:
        answer(client, CITRUS_FORM)
        client.get("/counsel/preview")
        t = time.monotonic()
        m = wait_match(client)["match"]
        assert m["state"] == "none" and time.monotonic() - t < DEADLINE_S and "시간" in m["staff"]["note"]
    finally:
        gate.set()
    time.sleep(0.3)
    assert ai(client)["match"]["state"] == "none"                                # 늦게 돌아온 답이 뒤집지 못한다


def test_no_new_notices_gives_none_without_calling_ai(app_client, tmp_path):
    empty = tmp_path / "empty"
    (empty / "notices").mkdir(parents=True)
    llm = MatchLLM()
    client = app_client(llm, catalog=empty)
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    m = wait_match(client)["match"]
    assert m["state"] == "none" and llm.requests == [] and m["staff"]["candidates"] == 0


def test_notice_hidden_or_ended_in_the_list_is_not_matched(app_client, catalog_dir):
    """목록에서 표와 겹쳐 숨겨진 공고, 신청이 끝난 공고는 AI 에 보내지 않는다."""
    f = catalog_dir / "notices" / "fta_citrus.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["apply_period"] = "가. 신청기간: 2026. 11. 2.(월) ~ 11. 12.(목)"           # 오늘(11-14)보다 앞서 끝남
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    g = catalog_dir / "notices" / "birth_helper.json"
    d = json.loads(g.read_text(encoding="utf-8"))
    d["table_key"] = "JEJU-LOGI"                                                   # 표에 있는 제도와 같다고 본 공고
    g.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    llm = MatchLLM()
    client = app_client(llm)
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    wait_match(client)
    sent = llm.requests[0].messages[0].text
    assert sent.count("[공고 ") == 3 and NOTICES[FTA].name not in sent and NOTICES[BIRTH].name not in sent


def test_editing_answers_does_not_mix_old_match(app_client):
    gate = threading.Event()
    llm = MatchLLM(gate=gate)
    client = app_client(llm)
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    assert llm.started.wait(DEADLINE_S)
    assert client.get("/counsel/input?edit=1").status_code == 200
    answer(client, P2_FORM)                                                       # 감귤 -> 당근으로 고침
    client.get("/counsel/preview")
    assert ai(client)["match"]["state"] == "run"                                  # 옛 상담의 결과가 아니라 새 작업이 도는 중
    gate.set()
    m = wait_match(client)["match"]
    assert m["state"] == "done" and m["lines"] == [] and staff_of(client)["names"]["안 맞음"] == names(FTA, BIRTH)
    assert len(llm.requests) >= 3                                                  # 두 상담이 각자 불렀다


def test_two_counsels_do_not_mix(app_client):
    gate = threading.Event()
    client = app_client(MatchLLM(gate=gate))
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    a = dict(client.cookies)
    client.cookies.clear()
    answer(client, P2_FORM)
    client.get("/counsel/preview")
    gate.set()
    jb = wait_match(client)
    staff_b = staff_of(client)
    client.cookies.clear()
    client.cookies.update(a)
    ja = wait_match(client)
    assert [ln["key"] for ln in ja["match"]["lines"]] == [FTA] and jb["match"]["lines"] == []
    assert staff_b["names"]["안 맞음"] == names(FTA, BIRTH) and staff_of(client)["names"]["안 맞음"] == names(BIRTH)


def test_farm_values_never_reach_the_ai_on_this_path(app_client):
    llm = MatchLLM()
    client = app_client(llm)
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    wait_match(client)
    assert len(llm.requests) == 2
    for req in llm.requests:
        sent = build_payload(req).model_dump_json()
        for value in ("애월", "1961", "11901", "11,901", "3600", "3,600"):
            assert value not in sent, value


def test_match_result_is_kept_in_the_counsel_record_for_the_paper(app_client):
    client = app_client(MatchLLM())
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    wait_match(client)
    job = client.app.state.sessions.get(client.cookies.get(COOKIE))["job"]
    paper = job.paper()
    assert paper["match"]["state"] == "done" and paper["match"]["lines"][0]["key"] == FTA
    assert job.match.report.source == "ai" and paper["match"] == ai(client)["match"]
