"""체험(재생) 모드의 '오늘': 첫 화면·지원 전체 보기·맞춰 보기 공고 고르기는 상담 기준일(--asof)로 센다.
실제 모드(체험이 아님)는 진짜 오늘이고, 환경 변수 JEJU_SHOW_TODAY 가 있으면 그 값이 먼저다."""
import sys
from datetime import date
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app.config import APP_ROOT, load_config
from app.ui.routes_supports import today_of

from .conftest import _started_client

sys.path.insert(0, str(APP_ROOT / "scripts"))
import record_replay as rr  # noqa: E402

REAL = date(2026, 11, 20)          # 심사위원이 며칠 뒤 열었을 때의 진짜 오늘
ASOF = "2026-11-13"


@pytest.fixture(autouse=True)
def _real_today(monkeypatch):
    monkeypatch.setattr("app.config._today", lambda: REAL)
    monkeypatch.delenv("JEJU_SHOW_TODAY", raising=False)


def req(argv):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cfg=load_config(argv))))


def soup(r):
    return BeautifulSoup(r.text, "html.parser")


def test_replay_mode_counts_from_the_counsel_day():
    assert today_of(req(["--asof", ASOF, "--replay"])) == date(2026, 11, 13)


def test_real_mode_and_plain_demo_mode_keep_the_real_today():
    assert today_of(req([])) == REAL
    assert today_of(req(["--asof", ASOF])) == REAL                 # 체험(--replay)이 아닌 시연 기준일은 지금처럼 진짜 오늘


def test_show_today_variable_comes_first_in_replay_mode(monkeypatch):
    monkeypatch.setenv("JEJU_SHOW_TODAY", "2026-11-16")
    assert today_of(req(["--asof", ASOF, "--replay"])) == date(2026, 11, 16)
    monkeypatch.setenv("JEJU_SHOW_TODAY", "엉뚱한 글")
    assert today_of(req(["--asof", ASOF, "--replay"])) == date(2026, 11, 13)       # 읽을 수 없는 값은 무시
    assert today_of(req([])) == REAL                                                # 실제 모드는 환경 변수도 듣지 않는다


def test_home_list_and_staff_banner_use_the_counsel_day_in_replay_mode():
    c = _started_client(["--asof", ASOF, "--replay"])
    try:
        assert "11월 13일" in soup(c.get("/")).select_one(".due-base").text
        assert "오늘은 11월 13일이에요" in soup(c.get("/supports")).select_one(".sp-count").text
        staff = c.get("/staff").text
        assert "체험 모드 · 미리 저장해 둔 AI 답변을 써요 · 오늘을 2026년 11월 13일로 보고 보여 드려요" in staff
        assert "2026년 11월 20일" not in staff
    finally:
        c.__exit__(None, None, None)


def test_real_mode_home_and_list_use_the_real_today():
    c = _started_client([])
    try:
        assert "11월 20일" in soup(c.get("/")).select_one(".due-base").text
        assert "오늘은 11월 20일이에요" in soup(c.get("/supports")).select_one(".sp-count").text
        assert "오늘을" not in c.get("/staff").text                                    # 체험 모드 줄 자체가 없다
    finally:
        c.__exit__(None, None, None)


def test_match_pool_uses_the_same_day_as_the_list(monkeypatch):
    from app.ui import match_job

    seen = []
    monkeypatch.setattr(match_job, "load_pool", lambda cdir, tables, today: seen.append(today) or [])
    for argv, want in ((["--asof", ASOF, "--replay"], date(2026, 11, 13)), ([], REAL)):
        c = _started_client(argv)
        try:
            match_job.pool_for(SimpleNamespace(app=c.app))
        finally:
            c.__exit__(None, None, None)
        assert seen[-1] == want


def test_recording_script_defaults_to_the_counsel_day(monkeypatch):
    seen = []
    monkeypatch.setattr(rr, "load_pool", lambda cdir, tables, today: seen.append(today) or [])
    with pytest.raises(Exception):
        rr.record_match("M-P1", rr.HandwrittenClient({"match": []}), ASOF)
    assert seen == [date(2026, 11, 13)]
