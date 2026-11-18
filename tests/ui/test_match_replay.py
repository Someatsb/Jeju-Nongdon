"""새 공고 맞춰 보기의 재생(설계서 1-5): 녹화 M-P1~M-P5(data/replay) 형식, 녹화 스크립트, 재생 모드.

실제 AI 는 부르지 않는다. 손으로 쓴 답(가짜 LLM)으로 녹화 -> 재생이 같은 결과를 내는지 본다.
공고는 tests/fixtures/catalog_notices/match 의 고정본, 기준일은 JEJU_SHOW_TODAY 로 고정한다.
"""
import json
import shutil
import sys
import time
from datetime import date

import pytest
from conftest import ROOT
from match_fixtures import BIRTH, CROPS, FTA, LOAN, NOTICES, ORG_MAT

from app.agents.llm.recording import load_recording, save_recording
from app.catalog.pool import load_pool
from app.config import APP_ROOT
from app.core.pipeline import fingerprint
from app.data_layer.tables import load_tables
from app.ui import match_job
from app.ui.replay import install_replay

from .conftest import _started_client
from .test_replay import DEMO

sys.path.insert(0, str(APP_ROOT / "scripts"))
import record_replay as rr  # noqa: E402

TODAY = date(2026, 11, 14)
ASOF = "2026-11-13"
FTA_Q = "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"
BIRTH_LINES = NOTICES[BIRTH].target.split("\n")


def step(*calls):
    return {"text": None, "tool_calls": [{"name": n, "args": a} for n, a in calls]}


ANSWERS = {"match": [
    step(("check_farmer", {"notice_key": FTA, "kind": "작물", "quote": FTA_Q, "crops": ["감귤"]}),
         ("check_farmer", {"notice_key": BIRTH, "kind": "성별", "quote": BIRTH_LINES[0], "choice": "여성"}),
         ("check_farmer", {"notice_key": BIRTH, "kind": "그 밖", "quote": BIRTH_LINES[1]}),
         ("check_farmer", {"notice_key": ORG_MAT, "kind": "그 밖", "quote": "나. 신청장소: 농지 소재지 읍면동사무소"}),
         ("check_farmer", {"notice_key": LOAN, "kind": "그 밖", "quote": NOTICES[LOAN].target})),
    step(("submit_matches", {"items": [
        {"notice_key": FTA, "why": "감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요", "ask": ["농협에서 받는지"]},
        {"notice_key": BIRTH, "why": "여성농업인이 신청하는 사업이라 알아봐야 해요", "ask": ["출산 예정인지"]}]})),
]}


@pytest.fixture
def catalog_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JEJU_SHOW_TODAY", TODAY.isoformat())
    d = tmp_path / "catalog"
    shutil.copytree(ROOT / "tests" / "fixtures" / "catalog_notices" / "match", d / "notices")
    shutil.copy(ROOT / "data" / "catalog" / "links.csv", d / "links.csv")
    return d


def record(catalog_dir, replay_dir, sample="M-P1", answers=ANSWERS):
    rec, in_hash = rr.record_match(sample, rr.HandwrittenClient(json.loads(json.dumps(answers))), ASOF, today=TODAY, catalog_dir=catalog_dir)
    recording = rr.build_recording(sample, rec, "handwritten", in_hash, ASOF, rr.datetime(2026, 11, 15, 10, 0))
    save_recording(recording, replay_dir / f"{sample}.json")
    return recording


@pytest.fixture
def replay_dir(tmp_path):
    d = tmp_path / "replay"
    d.mkdir()
    for p in (APP_ROOT / "data" / "replay").glob("P[0-9].json"):
        shutil.copy(p, d / p.name)
    return d


@pytest.fixture
def replay_client(catalog_dir):
    c = _started_client(["--asof", ASOF, "--replay", "--catalog-dir", str(catalog_dir)])
    yield c
    c.__exit__(None, None, None)


def run_sample(client, replay_dir, sample):
    install_replay(client.app, replay_dir)      # 시험용 녹화 폴더로 바꿔 끼운다(녹화를 만든 뒤에 읽는다)
    assert client.post("/counsel/input", data=DEMO[sample]["form"]).status_code == 303
    assert client.post("/counsel/confirm", data={"already": DEMO[sample]["already"]}).status_code == 303
    assert client.get("/counsel/preview").status_code == 200
    end = time.monotonic() + 5
    while time.monotonic() < end:
        j = client.get("/counsel/ai").json()
        if j["match"]["state"] != "run":
            return j
        time.sleep(0.02)
    raise AssertionError("재생이 끝나지 않음")


def test_recording_has_the_replay_file_shape(catalog_dir, replay_dir):
    recording = record(catalog_dir, replay_dir)
    saved = load_recording(replay_dir / "M-P1.json")
    assert saved.sample_id == "M-P1" and saved.source == "handwritten" and saved.prompt_ver == "match-v2" and saved.as_of == ASOF
    assert [c.purpose for c in saved.calls] == ["match", "match"] and [c.attempt for c in saved.calls] == [1, 2]
    fs = rr.demo_fact_sheet("P1", ASOF)
    assert saved.input_hash == fingerprint(fs) == recording.input_hash


def test_replay_gives_the_same_match_as_the_handwritten_run(replay_client, catalog_dir, replay_dir):
    record(catalog_dir, replay_dir)
    j = run_sample(replay_client, replay_dir, "P1")
    replayed = j["match"]
    assert replayed["state"] == "done" and [ln["key"] for ln in replayed["lines"]] == [FTA]
    # 같은 손글씨 답을 가짜 LLM 으로 직접 돌린 결과와 같다
    tables = load_tables(ROOT / "data" / "tables", date.fromisoformat(ASOF))
    fs = rr.demo_fact_sheet("P1", ASOF)
    pool = load_pool(catalog_dir, tables, TODAY)
    mj = match_job.MatchJob()
    match_job.launch(mj, match_job.make_matcher(rr.HandwrittenClient(json.loads(json.dumps(ANSWERS))), tables.crops, date.fromisoformat(ASOF)),
                     fs.profile, fs, pool)
    assert mj.done.wait(5)
    assert mj.view() == replayed
    assert "names" not in replayed["staff"] and "items" not in replayed["staff"]
    assert sorted(mj.staff_view()["names"]["알 수 없음"]) == sorted(n.name for n in NOTICES.values() if n.key != FTA)      # 출산 도우미는 성별만 예, 출산은 답에 없음
    assert j["state"] == "done"                                             # 설명 글(녹화)도 그대로 채워진다


def test_replay_without_a_match_recording_is_none(replay_client, replay_dir):
    j = run_sample(replay_client, replay_dir, "P4")
    assert j["match"]["state"] == "none" and j["match"]["lines"] == [] and "녹화" in j["match"]["staff"]["note"]
    assert j["state"] == "done"


def test_replay_with_a_changed_notice_list_falls_back_to_none(replay_client, catalog_dir, replay_dir):
    record(catalog_dir, replay_dir)
    (catalog_dir / "notices" / "organic_materials.json").unlink()          # 공고 목록이 바뀌어 녹화와 요청이 어긋난다
    j = run_sample(replay_client, replay_dir, "P1")
    assert j["match"]["state"] == "none" and "녹화" in j["match"]["staff"]["note"]


def test_recording_one_sample_does_not_serve_another_farmer(replay_client, catalog_dir, replay_dir):
    record(catalog_dir, replay_dir)
    j = run_sample(replay_client, replay_dir, "P2")                                      # 다른 농가: 지문이 달라 맞는 녹화가 없다
    assert j["match"]["state"] == "none"


def test_recorder_refuses_to_save_a_run_that_did_not_finish(catalog_dir, replay_dir):
    with pytest.raises(rr.LLMUnavailable):
        rr.record_match("M-P1", rr.HandwrittenClient({"match": []}), ASOF, today=TODAY, catalog_dir=catalog_dir)


def test_main_writes_the_file_with_handwritten_answers(catalog_dir, tmp_path):
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / "M-P1.json").write_text(json.dumps(ANSWERS, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    code = rr.main(["M-P1", "--handwritten", "--asof", ASOF, "--out", str(out), "--answers", str(answers),
                    "--today", TODAY.isoformat(), "--catalog-dir", str(catalog_dir), "--recorded-at", "2026-11-15 10:00"])
    assert code == 0 and (out / "M-P1.json").is_file() and load_recording(out / "M-P1.json").prompt_ver == "match-v2"


def test_match_recordings_do_not_join_the_counsel_deck(replay_dir, catalog_dir):
    record(catalog_dir, replay_dir)
    from app.ui.replay import ReplayDeck
    deck = ReplayDeck(replay_dir)
    assert {r.sample_id for r in deck.recordings} == {"P1", "P2", "P3", "P4", "P5"} and deck.unreadable == 0


def test_crops_fixture_is_the_one_the_app_uses():
    assert CROPS == load_tables(ROOT / "data" / "tables", date.fromisoformat(ASOF)).crops
