"""새 공고 맞춰 보기: 어르신 값이 AI로 나가는 요청 어디에도 없다. 표식 값을 넣은 프로필로 돌려 나간 요청 전체를 글로 바꿔 본다."""
import json

from conftest import AS_OF
from counsel_fixtures import BUNDLE, SNAP
from match_fixtures import CROPS, ScriptClient, StepClock, call, custom_notice, profile, result

from app.agents.match import run_match
from app.core.pipeline import build_fact_sheet
from app.tools.models import ToolLog

MARKERS = {"태어난 해": "1931", "넓이": "12345", "읍면동": "노형동", "햇수": "47", "경영체 마지막 등록 해": "2013", "나이": "95"}
TARGET = ("지원대상: 제주시에 사는 만 65세 이상 여성 농업인으로 농사 10년 이상, 농사짓는 땅 1,000㎡ 이상, 직장가입자, "
          "감귤 재배, 농업경영체 등록, 농협 출하, 내 땅, 재해 피해, 배우자 공동 영농")
NOTICE = custom_notice("new-probe", name="시험용 지원사업", target=TARGET, content="", apply_period="2026. 11. 9.(월) ~ 11. 23.(월)")


def marker_profile():
    return profile(
        birth_year=1931, total_area_m2=12345, emd_code="노형동", farming_years=47, mgmt_last_reg_year=2013,
        crops=({"crop_code": "감귤_노지", "area_m2": 12345, "sales_channel": "coop", "selfpay_fund": "paid"},))


def asks():
    q = TARGET
    return result(
        call(1, "check_farmer", notice_key="new-probe", kind="작물", quote=q, crops=["감귤"]),
        call(2, "check_farmer", notice_key="new-probe", kind="행정시", quote=q, choice="제주시"),
        call(3, "check_farmer", notice_key="new-probe", kind="나이 이상", quote=q, number=65),
        call(4, "check_farmer", notice_key="new-probe", kind="성별", quote=q, choice="여성"),
        call(5, "check_farmer", notice_key="new-probe", kind="넓이 이상", quote=q, number=1000, unit="㎡"),
        call(6, "check_farmer", notice_key="new-probe", kind="농사 햇수 이상", quote=q, number=10),
    )


def test_markers_are_not_in_the_public_notice_text():
    from app.agents.match import opening_text
    text = opening_text([NOTICE], CROPS)
    for name, value in MARKERS.items():
        assert value not in text, f"표식 값({name})이 공고 글에 우연히 들어 있어요. 다른 값으로 바꾸세요"


def test_no_farmer_value_goes_out_in_any_request():
    p = marker_profile()
    client = ScriptClient(
        asks(), result(call(10, "submit_matches", items=[{"notice_key": "new-probe", "why": "감귤 농가 조건이 어울려 맞을 수 있어요", "ask": ["배우자 조건"]}])))
    rep = run_match(p, build_fact_sheet(p, BUNDLE, SNAP, AS_OF, "test"), [NOTICE], CROPS, client, ToolLog(), as_of=AS_OF, clock=StepClock())
    assert rep.source == "ai" and rep.items[0].verdict == "알 수 없음"   # 새 규칙: 예가 있어도 답에 없음이 하나 끼면 알 수 없음
    assert len(client.requests) == 2
    everything = json.dumps([r.model_dump(mode="json") for r in client.requests], ensure_ascii=False)
    for name, value in MARKERS.items():
        assert value not in everything, f"{name}({value})이 AI로 나가는 요청에 있어요"
    results = [r for req in client.requests for m in req.messages for r in m.tool_results]
    assert len(results) == 6
    assert {r.content for r in results} <= {'{"answer": "예"}', '{"answer": "아니오"}', '{"answer": "답에 없음"}'}


def test_error_replies_do_not_carry_farmer_values_either():
    p = marker_profile()
    bad_calls = result(
        call(1, "check_farmer", notice_key="new-probe", kind="나이 이상", quote=TARGET, number=70),       # 인용에 없는 숫자
        call(2, "check_farmer", notice_key="new-probe", kind="행정시", quote=TARGET, choice="서귀포시"),   # 인용에 없는 값
        call(3, "check_farmer", notice_key="new-probe", kind="나이 이상", quote="어르신이 몇 년생인지", number=65),
        call(6, "check_farmer", notice_key="new-probe", kind="그 밖", quote=TARGET))                       # 이것만 받아들여진다
    client = ScriptClient(bad_calls, result(call(4, "submit_matches", items=[{"notice_key": "new-probe", "why": "받습니다"}])),
                          result(call(5, "submit_matches", items=[{"notice_key": "new-probe", "why": "맞는지 알 수 없어요"}])))
    rep = run_match(p, build_fact_sheet(p, BUNDLE, SNAP, AS_OF, "test"), [NOTICE], CROPS, client, ToolLog(), as_of=AS_OF, clock=StepClock())
    assert rep.source == "ai"
    everything = json.dumps([r.model_dump(mode="json") for r in client.requests], ensure_ascii=False)
    for value in MARKERS.values():
        assert value not in everything


def test_narrowing_down_the_age_is_refused():
    """기준값을 바꿔 가며 나이를 좁혀 알아내려는 시도는 셋째에서 막힌다(어르신 값은 한 번도 안 나가지만 답의 모양도 새지 않게)."""
    p = marker_profile()
    q = "지원대상: 만 60세, 70세, 80세, 90세 이상"
    n = custom_notice("new-probe", target=q)
    rounds = result(*[call(i, "check_farmer", notice_key="new-probe", kind="나이 이상", quote=q, number=x)
                      for i, x in enumerate((60, 70, 80, 90), 1)])
    client = ScriptClient(rounds, result(call(9, "submit_matches", items=[{"notice_key": "new-probe", "why": "맞는지 알 수 없어요"}])))
    log = ToolLog()
    run_match(p, build_fact_sheet(p, BUNDLE, SNAP, AS_OF, "test"), [n], CROPS, client, log, as_of=AS_OF, clock=StepClock())
    oks = [c.ok for c in log.calls if c.name == "check_farmer"]
    assert oks == [True, True, False, False]
