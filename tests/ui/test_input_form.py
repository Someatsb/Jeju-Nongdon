"""Task 7(U07) 입력 화면: 14항목(조건부 5a·12), 모름, 경계 경고, 대신 입력 모드, 문자 안내 선택 항목."""
import csv
import re
import logging

import pytest

from app.core.models import FarmProfile
from app.ui import forms
from app.ui.forms import FormErrors
from app.ui.session import COOKIE
from conftest import P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, ROOT, T1_KWARGS, T2_KWARGS

from .conftest import P4_FORM, session_profile, session_reminder

PERSONAS = {"P1": P1_KWARGS, "P2": P2_KWARGS, "P3": P3_KWARGS, "P4": P4_KWARGS,
            "P5": P5_KWARGS, "T1": T1_KWARGS, "T2": T2_KWARGS}
CONSENT_LINES = ("모으는 것은 휴대폰 번호뿐이에요.", "보험에 들거나 신청할 때가 되면 문자로 알려 드리는 데만 써요.",
                 "알림을 다 보내면 지우고, 늦어도 13개월 뒤에는 지워요.", "동의하지 않으셔도 상담과 종이에 불이익이 없어요.")


# --- 계획서 Step 1(그대로) ---

def test_old_reminder_fields_are_dropped_by_the_question_form(client):
    """문자 안내는 결과 화면에서 따로 받는다(POST /counsel/reminder). 질문 폼으로 번호가 와도(옛 주소) 받지 않고 버린다."""
    r = client.post("/counsel/input", data={**P4_FORM, "reminder_phone": "010-1234-5678", "reminder_consent": "on"})
    assert r.status_code == 303 and "reminder_phone" not in FarmProfile.model_fields
    assert session_reminder(client) is None
    r = client.post("/counsel/input", data={**P4_FORM, "reminder_phone": "010-1234"})
    assert r.status_code == 303 and session_reminder(client) is None      # 틀린 번호도 질문 화면에서는 막지 않는다(화면에 칸이 없다)


def test_form_roundtrip_p4(client):
    r = client.post("/counsel/input", data=P4_FORM)
    assert r.status_code == 303


def test_proxy_mode_sets_visitor(client):
    client.post("/counsel/input?mode=proxy", data={**P4_FORM, "visitor": "family_proxy"})
    assert session_profile(client).visitor == "family_proxy"


def test_hospital_field_absent(client):
    assert "입원" not in client.get("/counsel/input").text
    assert "입원" not in client.get("/counsel/input?mode=proxy").text


def test_area_warning(client):
    r = client.post("/counsel/input", data={**P4_FORM, "crop1_area_py": "100000"})
    assert "평수가 너무 커요" in r.text and "90,750평" in r.text


# --- 더한 것: 저장·이동 ---

def test_success_stores_p4_profile_and_redirects_to_confirm(client):
    r = client.post("/counsel/input", data=P4_FORM)
    assert r.headers["location"] == "/counsel/confirm"
    assert session_profile(client) == FarmProfile(**P4_KWARGS)
    assert session_reminder(client) is None


def _form(kw: dict) -> dict[str, str]:
    """페르소나 키워드 → 화면 폼(면적은 평). R1·R2(확인 화면) 칸은 넣지 않는다."""
    yn = {True: "yes", False: "no", None: "unknown"}
    f = {"visitor": kw["visitor"], "owner_sex": kw["owner_sex"] or "", "emd_code": kw["emd_code"],
         "birth_year": str(kw["birth_year"]), "total_area_py": str(round(kw["total_area_m2"] / 3.3058)),
         "land_tenure": kw["land_tenure"], "land_held_2y": yn[kw["land_held_2y"]],
         "owned_over_4700py": yn[kw["owned_over_4700py"]], "mgmt_status": kw["mgmt_status"],
         "mgmt_last_reg_year": str(kw["mgmt_last_reg_year"] or ""), "spouse": kw["spouse"],
         "farming_years": str(kw["farming_years"]), "health_ins": kw["health_ins"],
         "disaster_damage": yn[kw["flags"]["disaster_damage"]],
         "direct_payment_education": kw["flags"]["direct_payment_education"]}
    if kw["residence_3y"]:
        f["residence_3y"] = "on"
    for i, c in enumerate(kw["crops"], start=1):
        f |= {f"crop{i}_crop_code": c["crop_code"], f"crop{i}_area_py": str(round(c["area_m2"] / 3.3058)),
              f"crop{i}_sales_channel": c["sales_channel"], f"crop{i}_selfpay_fund": c["selfpay_fund"]}
    return f


def _intake_part(kw: dict) -> FarmProfile:
    """입력 화면이 채우는 부분만 남긴 기대 프로필(already_receiving·ins_* 등 R1·R2 칸은 뺌)."""
    kept = {k: v for k, v in kw.items() if k not in ("already_receiving", "first_heard", "ins_safety", "crops")}
    crops = tuple({k: v for k, v in c.items() if not k.startswith("ins_")} for c in kw["crops"])
    return FarmProfile(**kept, crops=crops)


@pytest.mark.parametrize("name", sorted(PERSONAS))
def test_personas_roundtrip_through_form(name):
    """P1~P5·T1·T2: 5a(302~2,890평 + 내 땅), 땅 2년, 작물 2개, 자조금, 7번 연도가 페르소나 값으로 돌아온다."""
    assert forms.to_profile(_form(PERSONAS[name])) == _intake_part(PERSONAS[name])


# --- 더한 것: 항목·문구 ---

STEP_TITLES = ["어디 사세요?", "무엇을 키우세요?", "농사짓는 분은 어떤 분이세요?", "농업경영체 등록을 하셨나요?",
               "올해 어디에 파세요?", "맞는 것을 눌러 주세요"]


def test_page_has_five_questions_and_a_last_press_screen(client):
    """질문 다섯 + 마지막 "해당되는 것만 눌러 주세요" 화면, 한 폼. 스크립트가 꺼져 있어도 차례로 다 있다."""
    html = client.get("/counsel/input").text
    positions = [html.find(t) for t in STEP_TITLES]
    assert -1 not in positions and positions == sorted(positions), list(zip(STEP_TITLES, positions))
    assert html.count("<form") == 1 and html.count('class="qstep') == 6 and "6개 중 <b>1번째</b>" in html
    for label in ("등록했어요, 2년이 넘었어요", "등록했어요, 2년이 안 됐어요", "안 했어요", "잘 모르겠어요",
                  "농협에 내요", "밭째 넘겼어요(밭떼기)", "상인에게 팔 예정이에요", "직접 팔아요",
                  "자조금을 내고 계세요?", "3년이 안 됐어요", "3~4년 됐어요", "5~9년 됐어요", "10년이 넘었어요", "3년 넘었어요", "3년 안 됐어요",
                  "배우자도 농사를 지어요 · 등록했어요", "배우자도 농사를 지어요 · 등록은 안 했어요",
                  "올해 태풍·폭우 피해를 입었어요", "직장에서 내요", "자녀·배우자 밑에 올라 있어요",
                  "국민건강보험 고지서를 따로 받아요(직장 아님)", "내 땅이에요", "내 땅도 있고 빌린 땅도 있어요", "내 땅이 아니라 빌려서 지어요",
                  "가진 땅이 4,700평을 넘어요", "다른 밭도 있어요", "몇 평이세요?", "다음", "이전"):
        assert label in html, label
    # 읍면동 43곳은 라디오, 작물 11개는 그림 단추(라디오)
    assert all(f'name="emd_code" value="{name}"' in html for name in forms.EMD_NAMES) and len(forms.EMD_NAMES) == 43
    assert all(f'name="crop1_crop_code" value="{code}"' in html for code, _ in forms.CROPS)
    assert all(f'name="crop2_crop_code" value="{code}"' in html for code, _ in forms.CROPS)      # 둘째 작물도 그림 단추
    assert "<select" not in html and "다섯 가지" not in html and "5개 중" not in html
    assert len(re.findall(r'class="seg[ "]', html)) == 6 and "둘째로 키우시는 것은요?" in html and "둘째 작물 지우기" in html
    assert "제주시" in html and "서귀포시" in html and "data-numpad" in html


def test_page_has_no_staff_marks_or_old_field_numbers(client):
    html = client.get("/counsel/input").text
    for gone in ("직원 표시", "묻지 않고 보고 표시", "입원", "3번 합계로 셈하고", "(시연)", 'name="visitor"',
                 'name="land_held_2y"', 'name="birth_year_approx"'):
        assert gone not in html, gone
    assert 'type="hidden" name="farming_10y_plus" value="on"' in html   # 안 누르면 "10년 넘게"(설계서 3-2)


def test_unpressed_residence_default_is_yes_on_the_page(client):
    """제주 거주 3년: 미리 눌러 두지 않는다(눌린 줄 모르고 지나가지 않게). 안 누르면 서버가 "예"로 읽는다."""
    html = client.get("/counsel/input").text
    assert 'name="residence_3y" value="on"' in html and 'name="residence_3y" value=""' in html
    assert not re.search(r'name="(residence_3y|farming_years|spouse)"[^>]*checked', html)
    r = client.post("/counsel/input", data={k: v for k, v in P4_FORM.items() if k != "residence_3y"}, follow_redirects=False)
    assert r.status_code == 303


def test_error_opens_the_step_of_the_first_wrong_field(client):
    html = client.post("/counsel/input", data={**P4_FORM, "birth_year": "1899"}).text
    assert 'data-start="3"' in html and 'class="qstep is-current" data-fit data-step="3"' in html
    assert "1900~2010" in html
    html = client.post("/counsel/input", data={**P4_FORM, "emd_code": ""}).text
    assert 'data-start="1"' in html and "사시는 읍·면·동을 눌러 주세요" in html
    html = client.post("/counsel/input", data={**P4_FORM, "health_ins": "가짜"}).text
    assert 'data-start="6"' in html


def test_second_crop_screen_opens_when_its_field_has_an_error(client):
    html = client.post("/counsel/input", data={**P4_FORM, "crop2_crop_code": "감자", "crop2_area_py": "abc"}).text
    assert 'data-start="2"' in html and "is-sub2" in html and 'name="crop2_crop_code" value="감자" checked' in html
    fresh = client.get("/counsel/input").text
    assert "is-sub2" not in fresh and 'class="x2-line is-on"' not in fresh


def test_edit_shows_the_second_crop_line_on_the_first_crop_screen(client_demo):
    """답 고치기: 둘째 작물이 있으면 첫째 작물 화면에 한 줄로 보이고, 단추는 고른 채로 돌아온다."""
    form = {**P4_FORM, "total_area_py": "", "crop2_crop_code": "감자", "crop2_area_py": "400"}
    assert client_demo.post("/counsel/input", data=form).status_code == 303
    html = client_demo.get("/counsel/input?edit=1&step=2").text
    assert 'class="x2-line is-on"' in html and "<b data-x2-name>감자</b>" in html
    assert 'name="crop2_crop_code" value="감자" checked' in html and 'value="400"' in html
    assert "is-sub2" not in html


def test_crop_examples_come_from_the_crops_table():
    """작물 단추 아래 예시는 crops.csv 의 aliases 에 있는 낱말만, 묶음 이름인 단추 네 개에만 붙는다."""
    with open(ROOT / "data" / "tables" / "crops.csv", encoding="utf-8-sig", newline="") as f:
        aliases = {r["crop_code"]: set(r["aliases"].split(";")) for r in csv.DictReader(f)}
    assert set(forms.CROP_HINTS) == {"감귤_노지", "감귤_만감", "기타과수", "시설과채"}
    for code, text in forms.CROP_HINTS.items():
        for w in text.split("·"):
            assert any(a in w for a in aliases[code]), (code, w)


def test_crop_example_texts_show_under_the_buttons(client):
    html = client.get("/counsel/input").text
    for text in ("극조생·조생 귤", "한라봉·천혜향·레드향", "키위·망고·블루베리", "토마토·딸기·파프리카"):
        assert html.count(text) == 2, text         # 첫째·둘째 작물 화면에 한 번씩


def test_unanswered_items_fall_back_to_service_table_unknowns():
    """모르면 칸(round2-A 입력 표): 읍면동과 첫 작물만 넣고 나머지는 비운 폼."""
    p = forms.to_profile({"emd_code": "한림읍", "crop1_crop_code": "브로콜리"})
    assert isinstance(p, FarmProfile)
    assert (p.visitor, p.owner_sex, p.birth_year, p.total_area_m2, p.land_tenure, p.mgmt_status) == \
        ("self", None, None, None, "unknown", "unknown")
    assert (p.spouse, p.farming_years, p.health_ins, p.flags.disaster_damage, p.flags.direct_payment_education) == \
        ("none", None, "unknown", False, "NA")
    assert p.crops[0].model_dump() == {"crop_code": "브로콜리", "area_m2": None, "sales_channel": "unknown",
                                       "selfpay_fund": "unknown", "ins_disaster": None, "ins_income": None}


def test_residence_3y_defaults_to_yes_when_the_field_is_absent():
    """칸이 아예 없으면 "예"(농민수당 줄이 사라지지 않게). 빈 값(화면의 "3년이 안 됐어요")은 아니오, 체크된 값은 예."""
    base = {"emd_code": "한림읍", "crop1_crop_code": "브로콜리"}
    assert forms.to_profile(base).residence_3y is True
    assert forms.to_profile({**base, "residence_3y": ""}).residence_3y is False
    assert forms.to_profile({**base, "residence_3y": "on"}).residence_3y is True


def test_initial_values_are_empty():
    assert forms.initial_values(proxy=False) == forms.initial_values(proxy=True) == {}


def test_total_blank_uses_crop_sum():
    p = forms.to_profile({**P4_FORM, "total_area_py": "", "crop2_crop_code": "감자", "crop2_area_py": "400"})
    assert p.total_area_m2 == 11901 + 1322 and p.total_area_is_crop_sum


def test_non_selfpay_crop_gets_na():
    p = forms.to_profile({**P4_FORM, "crop1_crop_code": "감자", "crop1_selfpay_fund": "paid"})
    assert p.crops[0].selfpay_fund == "na"


def test_5a_ignored_unless_owned_and_302_to_2890_py():
    p1 = _form(P1_KWARGS) | {"owned_over_4700py": "yes"}
    assert forms.to_profile(p1).owned_over_4700py is True
    assert forms.to_profile(p1 | {"land_tenure": "rent_all"}).owned_over_4700py is None
    assert forms.to_profile(p1 | {"total_area_py": "3000", "crop1_area_py": "3000"}).owned_over_4700py is None


def test_mgmt_year_dropped_when_not_registered():
    assert forms.to_profile({**P4_FORM, "mgmt_last_reg_year": "2020"}).mgmt_last_reg_year is None


def test_crop_choices_match_crops_csv():
    with open(ROOT / "data" / "tables" / "crops.csv", encoding="utf-8-sig", newline="") as f:
        rows = [(r["crop_code"], r["label"]) for r in csv.DictReader(f)]
    assert list(forms.CROPS) == rows


def test_selfpay_crops_match_tables():
    """12번을 묻는 작물 = supports.csv에서 자조금 조건(Y·E)이 붙은 행의 crop_in(그룹은 crops.csv로 풂)."""
    tables = ROOT / "data" / "tables"
    with open(tables / "crops.csv", encoding="utf-8-sig", newline="") as f:
        groups: dict[str, set[str]] = {}
        for r in csv.DictReader(f):
            for g in filter(None, r["groups"].split(";")):
                groups.setdefault(g, set()).add(r["crop_code"])
    with open(tables / "supports.csv", encoding="utf-8-sig", newline="") as f:
        names = {n for r in csv.DictReader(f) if r["needs_selfpay_fund"] in ("Y", "E")
                 for n in r["crop_in"].split(";") if n}
    assert forms.SELFPAY_CROPS == {c for n in names for c in groups.get(n, {n})}


# --- 더한 것: 막는 경우 ---

def test_total_below_crop_sum_blocked(client):
    r = client.post("/counsel/input", data={**P4_FORM, "total_area_py": "3000"})
    assert r.status_code == 200 and "작물 땅을 합친 것보다 작아요" in r.text
    assert client.app.state.sessions.get(client.cookies.get(COOKIE)) is None


@pytest.mark.parametrize("year", ["1899", "2011", "61"])
def test_birth_year_outside_1900_2010_blocked(client, year):
    r = client.post("/counsel/input", data={**P4_FORM, "birth_year": year})
    assert r.status_code == 200 and "1900~2010" in r.text


def test_missing_emd_and_crop_and_foreign_values_blocked():
    errors = forms.to_profile({**P4_FORM, "emd_code": "", "crop1_crop_code": "", "health_ins": "가짜"})
    assert isinstance(errors, FormErrors)
    assert {"emd_code", "crop1_crop_code", "health_ins"} <= set(errors)


def test_errors_keep_entered_values(client):
    html = client.post("/counsel/input", data={**P4_FORM, "birth_year": "1899"}).text
    assert 'name="emd_code" value="애월읍" checked' in html and 'value="3600"' in html
    assert 'name="land_tenure" value="rent_all" checked' in html


# --- 더한 것: 대신 입력 모드 ---

def test_proxy_page_is_the_same_screen_with_a_header_line_and_no_sms_field(client):
    proxy, staff = client.get("/counsel/input?mode=proxy").text, client.get("/counsel/input").text
    assert "/static/bigbutton.css" not in proxy and "/static/bigbutton.css" not in staff
    assert "어르신 대신 답하고 있어요" in proxy and "어르신 대신 답하고 있어요" not in staff
    assert 'action="/counsel/input?mode=proxy"' in proxy and 'action="/counsel/input"' in staff
    assert "reminder_phone" not in proxy and "reminder_consent" not in proxy and "reminder_phone" not in staff
    assert 'name="visitor"' not in proxy
    proxy_titles = ["어르신 댁은 어디예요?", "어르신은 무엇을 키우세요?", *STEP_TITLES[2:4], "올해 어디에 파시나요?", STEP_TITLES[5]]
    pos = [proxy.find(t) for t in proxy_titles]
    assert -1 not in pos and pos == sorted(pos)


def test_proxy_mode_without_visitor_means_family(client):
    """대신 입력 화면은 오신 분을 묻지 않는다: visitor가 없으면 "가족"."""
    form = {k: v for k, v in P4_FORM.items() if k != "visitor"}
    assert client.post("/counsel/input?mode=proxy", data=form).status_code == 303
    assert session_profile(client).visitor == "family_proxy"


def test_proxy_mode_rejects_self_visitor(client):
    r = client.post("/counsel/input?mode=proxy", data={**P4_FORM, "visitor": "self"})
    assert r.status_code == 200 and "목록에서 하나 눌러 주세요" in r.text


def test_proxy_village_head(client):
    client.post("/counsel/input?mode=proxy", data={**P4_FORM, "visitor": "village_head_proxy"})
    assert session_profile(client).visitor == "village_head_proxy"


# --- 문자 안내는 질문 화면에 없다(결과 화면에서 따로 받는다: tests/ui/test_reminder_result.py) ---

def test_question_screen_has_no_sms_block(client):
    html = client.get("/counsel/input").text
    for gone in ("마감 전에 문자로", "reminder_phone", "reminder_consent", "휴대폰 번호", "<details"):
        assert gone not in html, gone
    assert 'class="press-row"' not in html and 'class="press press6"' in html


def test_last_screen_order_and_no_floating_right_column(client):
    """묶음마다 한 줄씩 세로로: 햇수 → 배우자 → 제주 거주 → 건강보험 → 재해 → 농사짓는 땅 → 가진 땅. 묶음을 옆으로 나란히 묶는 줄(press-row)은 없다."""
    html = client.get("/counsel/input").text
    order = [html.find(t) for t in ('name="farming_years" value="1"', 'name="spouse" value="none"', 'name="residence_3y" value="on"',
                                    'name="health_ins" value="employee"', 'name="disaster_damage"', 'name="land_tenure" value="rent_all"',
                                    'name="owned_over_4700py"')]
    assert -1 not in order and order == sorted(order), order
    assert "press-row" not in html and "press-land" not in html
