"""유형별 종이 화면(Task 23): 고르기 -> 앞면만 1장, 사람 정보 없음."""
import re
from datetime import date
from typing import get_args

from bs4 import BeautifulSoup

from app.core import actions
from app.core.models import Action, TypeQuery
from app.core.typesheet import build_typesheet
from app.ui import routes_typesheet as rt
from app.ui.preflight_type import preflight_html

FORM = {"crop_code": "당근", "area_band": "le_0_5ha", "age_band": "75_84"}


def test_typesheet_route_prints(client):
    r = client.post("/typesheet", data=FORM)
    assert r.status_code == 200 and "자가 체크" in r.text


def test_get_form_has_three_button_groups_with_korean_labels(client):
    r = client.get("/typesheet")
    soup = BeautifulSoup(r.text, "html.parser")
    assert not soup.find_all("select")
    for name, count in (("crop_code", 11), ("area_band", 3), ("age_band", 5)):
        radios = soup.select(f'input[type="radio"][name="{name}"]')
        assert len(radios) == count and all(x.get("value") for x in radios)
    assert "노지감귤(온주)" in r.text and "0.5ha 이하" in r.text and "약 1,500평 이하" in r.text
    assert soup.select_one("#next-btn") and "종이 만들기" in soup.select_one("#next-btn").get_text()
    assert "/static/typesheet.css" in r.text and "시연" not in r.text and "bigbutton" not in r.text


def test_missing_choice_shows_easy_message_and_keeps_picks(client):
    r = client.post("/typesheet", data={"crop_code": "당근", "area_band": "le_0_5ha"})
    assert r.status_code == 422 and "하나씩 모두 눌러 주세요" in r.text
    assert BeautifulSoup(r.text, "html.parser").select_one('input[name="crop_code"][value="당근"][checked]')


def test_print_page_is_front_only_with_title_and_responsibility(client_demo):
    r = client_demo.post("/typesheet", data=FORM)
    soup = BeautifulSoup(r.text, "html.parser")
    assert len(soup.select('section[data-page="front"]')) == 1 and not soup.select('[data-page="back"]')
    text = re.sub(r"\s+", "", soup.get_text(""))      # 숫자 칸(span)마다 글이 끊기므로 공백 없이 이어 붙여 본다
    assert "당근·0.5ha이하·75~84세유형안내" in text
    assert "개인판정이아니에요·센터에서개인상담을받으세요" in text
    assert "유효30일·기준일2026-11-13" in text and "(시연)" not in text
    assert "최소약" in text and "아니면" not in text
    assert re.search(r"외\d+건", text)


def test_check_tag_and_every_digit_in_span_num(client):
    soup = BeautifulSoup(client.post("/typesheet", data=FORM).text, "html.parser")
    assert soup.select(".tag")
    for s in soup.select("span.num"):
        assert s.get("data-source") and s.get("data-asof")
    assert preflight_html(str(soup), client.app.state.cfg) == []


def test_no_personal_inputs_and_bad_choice_rejected(client):
    assert not BeautifulSoup(client.get("/typesheet").text, "html.parser").select('input[type="text"], input[type="tel"]')
    assert client.post("/typesheet", data={**FORM, "age_band": "x"}).status_code == 422 or \
        "선택" in client.post("/typesheet", data={**FORM, "age_band": "x"}).text


def test_screen_view_zoom(client):
    r = client.post("/typesheet?view=screen", data=FORM)
    assert "data-screen-zoom" in r.text


def test_preflight_html_catches_bare_digit_and_missing_source():
    class Cfg:
        demo_asof = False
    html = '<html><body><section class="sheet front" data-page="front"><p>12</p><span class="num">3</span></section></body></html>'
    assert {"NARR_DIGIT", "NO_SOURCE", "NO_ASOF"} <= set(preflight_html(html, Cfg()))


def test_home_has_start_button_and_no_staff_lines(client_demo):
    r = client_demo.get("/")
    soup = BeautifulSoup(r.text, "html.parser")
    assert not soup.select("main .hl")
    for gone in ("(시연", "보류 ", "기준일", "지원 표 확인", "저장본"):
        assert gone not in r.text, gone
    hrefs = {a["href"] for a in soup.select("main a.btn")}
    assert hrefs == {"/counsel", "/supports"}            # 큰 시작 단추 하나 + 지원 전체 보기 단추 하나
    assert [a["href"] for a in soup.select("main a.btn-primary")] == ["/counsel"]
    assert soup.select_one("a.btn-all").text.strip() == "지원 전체 보기"
    assert "지원금 찾아보기" in r.text and "묻지 않습니다" not in r.text
    assert "제주 농돈" in r.text and soup.select_one('footer a[href="/staff"]') is None and "직원 메뉴" not in r.text
    assert len(soup.select(".step")) == 3


def test_home_due_cards_come_from_due30(client_demo):
    soup = BeautifulSoup(client_demo.get("/").text, "html.parser")
    cards = soup.select(".dl")
    assert 1 <= len(cards) <= 3
    for c in cards:
        assert re.search(r"\d+월 \d+일(까지|부터)", c.select_one(".dl-date").text) and c.select_one(".dl-name").text.strip()


def test_home_hides_due_section_when_none(client_demo, monkeypatch):
    from app.core.home import HomeLines
    monkeypatch.setattr("app.ui.routes_home.home_lines", lambda *a: HomeLines(due30=(), data_line="", hold_count=0))
    monkeypatch.setattr("app.ui.routes_home._notice_cards", lambda *a: [])       # 실제 새 공고 폴더의 마감 카드도 끈다
    text = client_demo.get("/").text
    assert "곧 마감되는 지원" not in text and 'class="dl' not in text


def test_home_has_no_replay_note_but_staff_page_does(client_replay):
    note = "체험 모드 · 미리 저장해 둔 AI 답변을 써요"
    assert note not in client_replay.get("/").text
    assert client_replay.get("/staff").text.count(note) == 1


def test_counsel_start_redirects_to_input(client):
    r = client.get("/counsel")
    assert r.status_code == 303 and r.headers["location"] == "/counsel/input"


def test_every_crop_area_age_combination_prints_without_hold(client_demo):
    """표를 고쳐도 한 장에 들어가고 출처·기준일이 붙는지 지킨다: 작물(표) x 면적 구간 x 연령 구간 전부."""
    crops = [c.crop_code for c in client_demo.app.state.tables.crops]
    areas = get_args(TypeQuery.model_fields["area_band"].annotation)
    ages = get_args(TypeQuery.model_fields["age_band"].annotation)
    assert len(crops) * len(areas) * len(ages) >= 100
    for crop in crops:
        for area in areas:
            for age in ages:
                r = client_demo.post("/typesheet", data={"crop_code": crop, "area_band": area, "age_band": age})
                combo = (crop, area, age)
                assert r.status_code == 200 and "자가 체크" in r.text, combo
                assert preflight_html(r.text, client_demo.app.state.cfg) == [], combo


def _reachable_static_action_ids() -> set[str]:
    """actions.py가 만들 수 있는 id 가운데 이름이 고정된 것(PREREQ·COOP_SWITCH·KEEP). 상수와 만드는 함수에서 뽑는다."""
    groups = {actions._prereq_group(tuple(f)) for f in (actions._MGMT_FIELDS, actions._ENROLL_FIELDS,
                                                          actions._FUND_FIELDS, actions._COOP_FIELDS)}
    ids = {f"COOP_SWITCH:{g}" if g == "coop_fund" else f"PREREQ:{g}" for g in groups}
    from app.core.models import Flags
    from tests.unit.test_typesheet import Q  # noqa: F401  (대표 농가 틀)
    from app.core.typesheet import representative_profile
    prof = representative_profile(Q, date(2026, 11, 13)).model_copy(
        update={"mgmt_last_reg_year": 2020, "flags": Flags(direct_payment_education="N")})
    ids |= {a.action_id for a in actions._keep(prof, date(2026, 11, 13))}
    return ids


def test_every_reachable_prerequisite_keep_and_switch_action_has_korean_text():
    ids = _reachable_static_action_ids()
    assert {"PREREQ:enrollment", "PREREQ:mgmt_registration", "PREREQ:fund", "COOP_SWITCH:coop_fund",
            "KEEP:direct_pay_education"} <= ids and any(i.startswith("KEEP:mgmt_renewal:") for i in ids)
    for action_id in ids:
        assert rt.static_action_text(action_id), action_id


def test_all_action_kinds_have_fallback_text():
    from app.core.models import ActionKind
    assert set(get_args(ActionKind)) <= set(rt.KIND_TEXT)


def _ex(label, amount_kind):
    from app.core.typesheet import ExampleLine
    amount = None if amount_kind is None else type("A", (), {"kind": amount_kind})()
    return ExampleLine.model_construct(label=label, amount=amount)


def test_pick_examples_keeps_two_amounts_and_the_fact_line():
    lines = [_ex("a", "FIXED"), _ex("b", "FIXED"), _ex("c", "PER_AREA"), _ex("d", "FIXED"), _ex("fact", None)]
    kept, dropped = rt.pick_examples(tuple(lines))
    assert [e.label for e in kept] == ["a", "b", "fact"] and dropped == 2
    kept, dropped = rt.pick_examples(tuple(lines[:2]))
    assert len(kept) == 2 and dropped == 0
    kept, dropped = rt.pick_examples((_ex("a", "FIXED"), _ex("r", "REFERENCE_LAST_SEASON")))
    assert [e.label for e in kept] == ["a", "r"] and dropped == 0


def test_cabbage_page_prints_price_fact_and_counts_dropped(client_demo):
    st = client_demo.app.state
    q = TypeQuery(crop_code="양배추", area_band="le_0_5ha", age_band="75_84")
    ex = build_typesheet(q, st.tables, st.snapshot, st.cfg.as_of).example_1000py
    assert any(e.amount is None for e in ex) and len(ex) > 3
    text = re.sub(r"\s+", "", client_demo.post("/typesheet", data={"crop_code": "양배추", "area_band": "le_0_5ha",
                                                                 "age_band": "75_84"}).text)
    assert "작년계통출하농가kg당평균" in re.sub(r"<[^>]+>", "", text)
    assert f"외{len(ex) - 3}건은센터에서" in re.sub(r"<[^>]+>", "", text)
