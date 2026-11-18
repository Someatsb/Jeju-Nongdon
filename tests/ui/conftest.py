"""화면 시험 공용 픽스처: 오늘 기준 앱(client)과 시연 기준일 앱(client_demo).

입력 폼 도우미(Task 7): `P4_FORM`(P4 양 씨를 화면 입력으로 옮긴 폼), `session_profile(client)`,
`session_reminder(client)`. 다른 시험 파일은 `from .conftest import P4_FORM, session_profile`로 쓴다.
결과 확인 화면(Task 16): `P2_FORM`, `client_p2`(시연 기준일 앱에 P2 입력을 낸 상태).
"""
import asyncio
import gc
import time

import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.ui.app import create_app

WSAEFAULT = 10014
ENTER_DEADLINE_S = 6.0   # 실측(2026-11-08, 화면 시험 12회): 실패가 몰리면 2.3초까지 이어졌다
RETRY_PAUSE_S = (0.05, 0.25)  # 다시 할 때마다 0.05초씩 더 쉬되 0.25초를 넘기지 않는다


def _open_loops() -> set[int]:
    return {id(o) for o in gc.get_objects() if isinstance(o, asyncio.BaseEventLoop) and not o.is_closed()}


def _drop_half_built_loop(before: set[int]) -> None:
    """실패한 TestClient 진입이 남긴, 반쯤 만들어진 이벤트 루프를 닫힌 것으로 표시한다.

    소켓 쌍을 못 만들어 중간에 멈춘 루프는 close()도 실패해(`_ssock` 없음) 닫히지 않은 채 버려지고, 나중에
    아무 시험 중에나 가비지 수거되며 BaseEventLoop.__del__이 ResourceWarning을 낸다(-W error에서는 엉뚱한
    시험의 teardown 오류가 된다). 진입 전(before)에 없던, 돌고 있지 않은 열린 루프만 닫는다.
    close()가 실패하면 닫힘 표시만 한다.
    """
    for obj in gc.get_objects():
        if (isinstance(obj, asyncio.BaseEventLoop) and id(obj) not in before
                and not obj.is_closed() and not obj.is_running()):
            try:
                obj.close()
            except Exception:
                obj._closed = True


def _started_client(argv: list[str], **app_kw) -> TestClient:
    """TestClient를 열어 돌려준다.

    Windows asyncio는 이벤트 루프를 만들 때 127.0.0.1 소켓 쌍을 만든다. 소켓 호출을 가로채는 보안
    프로그램이 깔린 PC(개발 PC 실측)에서는 이것이 가끔 WinError 10014로 실패하므로 그 오류만 다시 해 본다.
    실패는 몇 초씩 몰려서 오므로 횟수가 아니라 시간(ENTER_DEADLINE_S)으로 다시 하는 한도를 둔다.
    """
    cfg = load_config(argv)
    deadline = time.monotonic() + ENTER_DEADLINE_S
    attempt = 0
    while True:
        # TestClient 기본 주소 testserver는 TrustedHost에서 막히므로 실제와 같은 주소를 쓴다.
        # 303 이동은 따라가지 않는다: 시험이 이동 응답(상태·Location)을 직접 본다.
        client = TestClient(create_app(cfg, **app_kw), base_url=f"http://127.0.0.1:{cfg.port}", follow_redirects=False)
        before = _open_loops()
        try:
            client.__enter__()
            return client
        except OSError as e:
            if getattr(e, "winerror", None) != WSAEFAULT or time.monotonic() >= deadline:
                raise
            _drop_half_built_loop(before)   # 오류가 아직 루프를 붙들고 있는 동안 닫는다(놓으면 바로 수거되며 경고가 난다)
        attempt += 1
        time.sleep(min(RETRY_PAUSE_S[0] * attempt, RETRY_PAUSE_S[1]))


@pytest.fixture
def client():
    c = _started_client([])
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def client_demo():
    c = _started_client(["--asof", "2026-11-13"])
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def client_replay():
    """재생 모드 앱(--replay --asof 2026-11-13): 열쇠 없이 data/replay의 녹화 답으로 설명 문장을 만든다(Task 32)."""
    c = _started_client(["--asof", "2026-11-13", "--replay"])
    yield c
    c.__exit__(None, None, None)


# --- 입력 폼(Task 7) ---------------------------------------------------------------------------
# tests/conftest.py의 P4_KWARGS를 화면 입력으로 옮긴 것(round2-A-service.md §4-4 입력 줄).
# 면적은 평: 양배추 3,600평 = 11,901㎡. 8번 "따로 일함" → spouse="none". 7번(등록 연도)은 해당 없음이라 비움.
# 공유 dict이므로 고치지 말고 {**P4_FORM, "키": 값}으로 복사해 쓴다.
P4_FORM = {
    "visitor": "self", "owner_sex": "M", "emd_code": "애월읍", "birth_year": "1961",
    "crop1_crop_code": "양배추", "crop1_area_py": "3600",
    "crop1_sales_channel": "field_contract_done", "crop1_selfpay_fund": "not_paid",
    "total_area_py": "3600", "land_tenure": "rent_all", "mgmt_status": "none", "spouse": "separate",
    "farming_years": "3", "residence_3y": "on", "health_ins": "unknown",
    "disaster_damage": "no", "direct_payment_education": "NA",
}


# P2 강 씨(tests/conftest.py P2_KWARGS) 화면 입력: 당근 3,000평 = 9,917㎡. 5a는 302~2,890평 밖이라 비움.
# R1·R2(already_receiving·ins_*)는 결과 확인 화면(Task 16)에서 넣으므로 여기 없다.
P2_FORM = {
    "visitor": "self", "owner_sex": "M", "emd_code": "구좌읍", "birth_year": "1958",
    "crop1_crop_code": "당근", "crop1_area_py": "3000", "crop1_sales_channel": "coop", "crop1_selfpay_fund": "paid",
    "total_area_py": "3000", "land_tenure": "own_part", "land_held_2y": "yes", "mgmt_status": "over_2y",
    "mgmt_last_reg_year": "2025", "spouse": "cofarming_unregistered", "farming_years": "40", "residence_3y": "on",
    "health_ins": "regional", "disaster_damage": "no", "direct_payment_education": "Y",
}


@pytest.fixture
def client_p2(client_demo):
    """시연 기준일(2026-11-13) 앱에 P2 입력 폼을 낸 상태. 다음 화면은 /counsel/confirm."""
    assert client_demo.post("/counsel/input", data=P2_FORM).status_code == 303
    return client_demo


def _session(client) -> dict:
    from app.ui.session import COOKIE  # 지연 import: 이 파일은 화면 시험 전체가 읽는다
    data = client.app.state.sessions.get(client.cookies.get(COOKIE))
    assert data is not None, "세션이 없습니다(입력 폼을 먼저 제출하세요)"
    return data


def session_profile(client):
    """마지막으로 제출한 FarmProfile(서버 세션의 profile 키)."""
    return _session(client)["profile"]


def session_reminder(client):
    """마지막으로 제출한 문자 안내 요청(ReminderRequest) 또는 None(서버 세션의 reminder 키)."""
    return _session(client)["reminder"]
