"""Task 16(U16) 결과 확인 화면(R1·R2): 해당될 수 있는 줄의 [받고 있음]/[처음 들음], 작물별·사람별 보험, 새 상담."""
import re
from datetime import date

from app.core.match import match_supports
from app.core.models import FarmProfile
from app.ui.session import COOKIE
from conftest import P2_KWARGS, P3_KWARGS

from .conftest import P2_FORM, P4_FORM, session_profile, session_reminder

AS_OF = date(2026, 11, 13)
CANDIDATE = ("LIKELY", "CHECK", "BLOCKED_PREREQ")
CARD = re.compile(r'<label class="choice[^"]*"><input type="checkbox" name="already" value="([^"]+)"( checked)?[^>]*>(.*?)</label>', re.S)


def lines(html: str) -> dict[str, tuple[bool, str]]:
    """확인 화면의 카드: program_key → (눌려 있나, 카드 글). 같은 key가 두 장이면 시험이 실패한다."""
    found = CARD.findall(html)
    assert len(found) == len({key for key, _, _ in found}), "같은 제도가 두 장입니다"
    return {key: (bool(on), re.sub(r"<[^>]+>", " ", body)) for key, on, body in found}


def put_profile(client, profile: FarmProfile, **extra) -> None:
    """입력 화면을 거치지 않고 세션에 프로필을 둔다(작물 둘인 P3처럼 공용 폼이 없는 경우)."""
    client.cookies.set(COOKIE, client.app.state.sessions.put(None, profile=profile, reminder=None, **extra))


def radio(html: str, name: str, value: str) -> str | None:
    """name·value가 맞는 누름 단추(체크박스·라디오) 태그(없으면 None)."""
    m = re.search(rf'<input type="(?:radio|checkbox)" name="{name}" value="{value}"[^>]*>', html)
    return m.group(0) if m else None


# --- 계획서 Step 1(감독 판정: hold 행은 없고 후보 행은 있다) ---

def test_confirm_lists_only_candidate_rows(client_p2):
    html = client_p2.get("/counsel/confirm").text
    assert "농민수당" in html and "행복택시" not in html


def test_confirm_sets_already(client_p2):
    client_p2.post("/counsel/confirm", data={"already": ["JEJU-FARMER-ALLOW"]})
    assert "JEJU-FARMER-ALLOW" in session_profile(client_p2).already_receiving


# --- 더한 것: 줄 고르기 ---

def test_lines_are_first_pass_candidates_one_per_key(client_p2):
    """줄 = 받는 것 표시 전 1차 매칭의 LIKELY·CHECK·BLOCKED_PREREQ, program_key마다 한 줄(표 순서)."""
    bundle = client_p2.app.state.tables
    results = match_supports(session_profile(client_p2), bundle.programs, AS_OF, crops=bundle.crops)
    expected = list(dict.fromkeys(m.program_key for m in results if m.status in CANDIDATE))
    shown = lines(client_p2.get("/counsel/confirm").text)
    assert list(shown) == expected and len(expected) >= 5
    others = {m.program_key for m in results} - set(expected)   # NOT_ELIGIBLE 등만 나온 제도
    assert "NAT-DIRECT-SMALL" in others and not others & set(shown)


def test_cards_show_name_cue_and_no_status_words(client_p2):
    html = client_p2.get("/counsel/confirm").text
    shown = lines(html)
    on, body = shown["JEJU-FARMER-ALLOW"]
    assert "제주 농민수당" in body and "3월에 신청해서 탐나는전(지역화폐)으로 받는 50만 원" in body        # recognition_cue
    assert "매달 통장으로 들어오는 농지연금" in shown["KRC-FARMLAND-PENSION"][1]
    for gone in ("해당될 수 있음", "확인 필요", "먼저 할 일 있음", "처음 들음", "확인할 것", "first_heard", "감귤_노지"):
        assert gone not in html
    assert "받고 계신 것만 눌러 주세요" in html and "이미 받고 계신 지원" in html and "받은 것 없어요, 결과 보기" in html


def test_blocked_prereq_card_still_listed_p4(client_demo):
    client_demo.post("/counsel/input", data=P4_FORM)         # 경영체 미등록
    assert "JEJU-FARMER-ALLOW" in lines(client_demo.get("/counsel/confirm").text)


def test_crop_variants_share_one_card_p3(client_demo):
    """P3 마늘·월동무: 농작물재해보험 두 행이 한 장으로, 두 이름을 함께 보인다."""
    put_profile(client_demo, FarmProfile(**P3_KWARGS))
    on, body = lines(client_demo.get("/counsel/confirm").text)["NAT-CROP-INS"]
    assert "농작물재해보험(월동무)" in body and "농작물재해보험(마늘)" in body


def test_already_marked_lines_stay_and_stay_checked(client_demo):
    """P3 페르소나는 농민수당을 이미 받음으로 들고 있다. 카드는 그대로 나오고 눌려 있다."""
    put_profile(client_demo, FarmProfile(**P3_KWARGS))
    assert lines(client_demo.get("/counsel/confirm").text)["JEJU-FARMER-ALLOW"][0] is True


def test_direct_pay_card_brings_education_question(client_demo):
    """소농·면적직불 카드가 있으면 교육 질문(Y/N)이 붙는다. 직불을 받는 농가는 처음부터 보인다."""
    put_profile(client_demo, FarmProfile(**P3_KWARGS))       # 면적직불을 받는 농가, 교육 N
    html = client_demo.get("/counsel/confirm").text
    assert "올해 직불 교육을 들으셨어요?" in html and "들었어요" in html and "아직이에요" in html
    assert "checked" in radio(html, "direct_payment_education", "N") and "is-on" in html


def test_education_rules_on_confirm_post(client_demo):
    """직불을 받는다고 눌렀는데 교육 값이 NA면 N, 직불을 안 눌렀으면 값을 건드리지 않는다, 눌렀으면 답을 쓴다."""
    client_demo.post("/counsel/input", data=P4_FORM)         # 교육 NA
    assert session_profile(client_demo).flags.direct_payment_education == "NA"
    client_demo.post("/counsel/confirm", data={"direct_payment_education": "Y"})
    assert session_profile(client_demo).flags.direct_payment_education == "NA"
    client_demo.post("/counsel/confirm", data={"already": ["NAT-DIRECT-AREA"]})
    assert session_profile(client_demo).flags.direct_payment_education == "N"
    client_demo.post("/counsel/confirm", data={"already": ["NAT-DIRECT-AREA"], "direct_payment_education": "Y"})
    assert session_profile(client_demo).flags.direct_payment_education == "Y"


# --- 더한 것: 보험 단추 ---

def test_insurance_buttons_per_crop_and_person(client_p2):
    html = client_p2.get("/counsel/confirm").text
    for name in ("crop1_ins_disaster", "crop1_ins_income", "safety_owner", "safety_spouse"):
        tag = radio(html, name, "yes")
        assert tag and 'type="checkbox"' in tag and "checked" not in tag, name        # 안 눌렀으면 눌리지 않은 상태(안 가면 모름)
        assert radio(html, name, "no") is None and radio(html, name, "unknown") is None
    assert "당근 재해보험" in html and "당근 수입안정보험" in html
    assert "안전보험 (농사짓는 분)" in html and "안전보험 (배우자)" in html
    assert radio(html, "crop2_ins_disaster", "yes") is None


def test_no_spouse_no_spouse_safety(client_demo):
    client_demo.post("/counsel/input", data=P4_FORM)         # 8번 "따로 일함" → spouse="none"
    html = client_demo.get("/counsel/confirm").text
    assert radio(html, "safety_owner", "yes") and radio(html, "safety_spouse", "yes") is None


def test_two_crops_two_insurance_rows_p3(client_demo):
    put_profile(client_demo, FarmProfile(**P3_KWARGS))
    html = client_demo.get("/counsel/confirm").text
    assert radio(html, "crop2_ins_income", "yes") and "마늘 재해보험" in html and "월동무 재해보험" in html


# --- 더한 것: 제출 ---

def test_post_redirects_to_working(client_p2):
    r = client_p2.post("/counsel/confirm", data={"already": ["JEJU-FARMER-ALLOW"]})
    assert r.status_code == 303 and r.headers["location"] == "/counsel/working"


def test_post_fills_r1_r2_and_keeps_intake(client_p2):
    before = session_profile(client_p2)
    client_p2.post("/counsel/confirm", data={
        "already": ["JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA"], "first_heard": ["DO-CALCIUM-SULFUR"],
        "crop1_ins_disaster": "yes", "safety_owner": "yes"})
    p = session_profile(client_p2)
    assert p.already_receiving == {"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA"}
    assert p.first_heard == {"DO-CALCIUM-SULFUR"}
    assert (p.crops[0].ins_disaster, p.crops[0].ins_income) == (True, None)
    assert p.ins_safety == {"owner"}
    rest = {"already_receiving", "first_heard", "ins_safety", "crops", "flags"}
    assert p.model_dump(exclude=rest) == before.model_dump(exclude=rest)
    assert p.crops[0].model_dump(exclude={"ins_disaster", "ins_income"}) == before.crops[0].model_dump(
        exclude={"ins_disaster", "ins_income"})


def test_post_unanswered_toggles_are_unknown(client_p2):
    client_p2.post("/counsel/confirm", data={"crop1_ins_disaster": "unknown", "crop1_ins_income": "아무거나"})
    p = session_profile(client_p2)
    assert (p.crops[0].ins_disaster, p.crops[0].ins_income) == (None, None)
    assert p.already_receiving == p.first_heard == p.ins_safety == frozenset()


def test_post_receiving_wins_and_foreign_keys_dropped(client_p2):
    """같은 줄에 둘 다 오면 [받고 있음]만 남긴다. 화면에 없던 제도(소농직불·hold 행·모르는 값)는 버린다."""
    client_p2.post("/counsel/confirm", data={
        "already": ["JEJU-FARMER-ALLOW", "NAT-DIRECT-SMALL", "JEJU-HAPPY-TAXI"],
        "first_heard": ["JEJU-FARMER-ALLOW", "NO-SUCH-KEY", "JEJU-LOGI"]})
    p = session_profile(client_p2)
    assert p.already_receiving == {"JEJU-FARMER-ALLOW"} and p.first_heard == {"JEJU-LOGI"}


def test_spouse_safety_ignored_without_spouse(client_demo):
    client_demo.post("/counsel/input", data=P4_FORM)
    client_demo.post("/counsel/confirm", data={"safety_owner": "yes", "safety_spouse": "yes"})
    assert session_profile(client_demo).ins_safety == {"owner"}


def test_back_to_confirm_shows_saved_answers(client_p2):
    client_p2.post("/counsel/confirm", data={"already": ["JEJU-FARMER-ALLOW"], "first_heard": ["JEJU-LOGI"],
                                             "crop1_ins_income": "yes", "safety_spouse": "yes"})
    html = client_p2.get("/counsel/confirm").text
    shown = lines(html)
    assert shown["JEJU-FARMER-ALLOW"][0] is True and shown["JEJU-LOGI"][0] is False      # 처음 들음 칸은 없다
    assert "checked" in radio(html, "crop1_ins_income", "yes") and "checked" in radio(html, "safety_spouse", "yes")


def test_profile_from_confirm_matches_persona_r1(client_p2):
    """P2 페르소나가 들고 있는 받는 것 5개를 눌러 내면 페르소나 프로필과 같아진다."""
    client_p2.post("/counsel/confirm", data={"already": sorted(P2_KWARGS["already_receiving"])})
    assert session_profile(client_p2) == FarmProfile(**P2_KWARGS)


# --- 더한 것: 세션 없음·대신 입력·새 상담 ---

def test_confirm_without_intake_goes_to_input(client_demo):
    for r in (client_demo.get("/counsel/confirm"), client_demo.post("/counsel/confirm", data={})):
        assert r.status_code == 303 and r.headers["location"] == "/counsel/input"


def test_proxy_mode_carries_to_confirm(client_demo):
    client_demo.post("/counsel/input", data=P2_FORM)
    assert "어르신을 대신해 답해 주세요" not in client_demo.get("/counsel/confirm").text
    client_demo.post("/counsel/input?mode=proxy", data={**P2_FORM, "visitor": "family_proxy"})
    assert "어르신 대신 답하고 있어요" in client_demo.get("/counsel/confirm").text


def test_proxy_input_ignores_reminder_consent(client_demo):
    """대신 입력(mode=proxy)은 문자 안내 동의를 받지 않는다: 번호·동의가 와도 저장하지 않고, 화면에는 안내 한 줄만."""
    r = client_demo.post("/counsel/input?mode=proxy", data={**P2_FORM, "visitor": "family_proxy",
                                                            "reminder_phone": "010-1234-5678", "reminder_consent": "on"})
    assert r.status_code == 303
    assert session_reminder(client_demo) is None
    page = client_demo.get("/counsel/input?mode=proxy").text
    assert "reminder_phone" not in page and "reminder_consent" not in page   # 질문 화면에는 문자 안내 칸이 없다(결과 화면에서 따로 받는다)


def test_new_counsel_clears_session(client_demo):
    client_demo.post("/counsel/input", data={**P2_FORM, "visitor": "family_proxy",
                                                        "reminder_phone": "010-1234-5678", "reminder_consent": "on"})
    assert session_reminder(client_demo) is None
    sid = client_demo.cookies.get(COOKIE)
    r = client_demo.post("/counsel/new")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/input"
    assert client_demo.app.state.sessions.get(sid) is None        # 프로필·문자 번호·대신 입력 표시가 모두 사라짐
    assert client_demo.get("/counsel/confirm").headers["location"] == "/counsel/input"


def test_new_counsel_to_home(client_demo):
    """결과 화면의 "처음으로": 앞사람 답을 지우고 첫 화면으로."""
    client_demo.post("/counsel/input", data=P2_FORM)
    sid = client_demo.cookies.get(COOKIE)
    r = client_demo.post("/counsel/new?to=home")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client_demo.app.state.sessions.get(sid) is None


def test_tables_loaded_once_at_app_creation(client_p2):
    bundle = client_p2.app.state.tables
    client_p2.get("/counsel/confirm")
    client_p2.post("/counsel/confirm", data={})
    assert client_p2.app.state.tables is bundle and bundle.programs
