"""3단계 화면: 찾는 중 · 결과(위 띠 결론 한 줄 · 가실 곳별 카드 · 아래 띠 · 자세히 보기) · 인쇄 뒤 안내 · 인쇄 보류 · 답 고치기."""
import re

from app.ui.result_view import build_view, office_display, ro

from .conftest import P4_FORM, session_profile, _session


def go_result(client, form=None, already=()):
    assert client.post("/counsel/input", data=form or P4_FORM).status_code == 303
    assert client.post("/counsel/confirm", data={"already": list(already)}).status_code == 303
    r = client.get("/counsel/preview")
    assert r.status_code == 200
    return r.text


def test_working_page_and_no_session(client_demo):
    assert client_demo.get("/counsel/working").headers["location"] == "/counsel/input"
    client_demo.post("/counsel/input", data=P4_FORM)
    r = client_demo.get("/counsel/working")
    assert r.status_code == 200
    assert "받을 수 있는 지원을 찾고 있어요" in r.text                       # 속사정(단계 설명)은 적지 않고 한 가지 뜻만
    assert "곧 보여 드릴게요" in r.text and 'data-w-more hidden' in r.text                  # 설명 글·공고 맞춰 보기가 끝날 때까지 기다린다. "20초쯤" 안내는 오래 걸릴 때만 보인다(hidden)
    assert "/static/working.js" in r.text and "/counsel/preview?wait=1" in r.text    # 스크립트가 꺼져 있으면 다 된 화면을 받는 길(meta)로 넘어간다


def test_result_page_order_and_server_values(client_demo):
    html = go_result(client_demo)
    text = re.sub(r"<[^>]+>", " ", html)
    assert html.index('id="summary"') < html.index('id="cards"') < html.index('class="rbar"') < html.index('id="detail"')
    assert "받을 수 있는 지원" in text or "조건이 맞으면" in text or "하세요" in text      # 위 띠는 결론 한 줄
    assert "애월읍" in text and "양배추 3,600평" in text and re.search(r"\d+세 남", text)
    assert "지금 하실 일" in text and "농업경영체 등록" in text and "1644-8778" in text
    assert "종이로 뽑기" in text and "답 고치기" in text and "처음으로" in text and "자세히 보기" in text and "문자 알림 받기" in text
    assert 'href="/counsel/print?auto=1"' in html and 'data-pv-open="front"' in html
    assert 'class="res-right"' not in html and "pv-frame" not in html and "big-num" not in html and "who-chips" not in html      # 옛 오른쪽 종이 칸·숫자 둘·답 칩은 없다
    assert "reminder-line" in html and "직원이 볼 내용" in html and "이 종이는 공문서가 아니에요" in html
    for gone in ("시연", "데모", "재생", "NUM_DIGIT", "(주입)"):
        assert gone not in text


def _view(client):
    from app.ui.routes_counsel import _paper
    st = client.app.state
    paper = _paper(type("R", (), {"app": client.app, "cookies": client.cookies})(), _session(client))
    return build_view(paper["sheet"], paper["fs"], st.tables, st.cfg.as_of, paper["narr"]), paper


def test_result_view_count_matches_paper_lines(client_demo):
    go_result(client_demo)
    v, paper = _view(client_demo)
    from app.core.sheet_cards import build_cards
    cs = build_cards(paper["sheet"], paper["fs"], paper["narr"])
    # 카드는 종이와 같은 묶음 그대로다(화면에서 따로 다시 묶지 않는다)
    assert [c["head"] for c in v["cards"]] == [office_display(c.place).partition(" (비대면:")[0] for c in cs.cards] and [c["no"] for c in v["cards"]] == [c.no for c in cs.cards]
    assert [[l["title"] for l in c["lines"]] for c in v["cards"]] == [[cl.title for cl in c.lines] for c in cs.cards]
    assert v["conclusion"] == cs.conclusion and v["count"] == cs.count and v["others_n"] == cs.others_count
    assert v["cards"][0]["first"] and v["cards"][0]["emphasis"] and v["cards"][0]["phone"] == "1644-8778" and v["place_name"]
    # 올해는 어려운 것(농협 출하·자조금이 먼저인 셋)은 카드가 아니라 자세히 보기 안으로 간다
    assert len(v["detail"]["later"]) == 3 and all(it["need"] for it in v["detail"]["later"])
    assert not any("가격안정관리제" in l["title"] for c in v["cards"] for l in c["lines"])
    assert [t for t in v["tags"]][0] == "애월읍" and v["who"].startswith("애월읍 · ")


def test_ai_steps_three_lines_default_sentences(client_demo):
    html = go_result(client_demo)
    assert "가지의 조건과 하나씩 맞춰 봤어요" in html
    assert "설명 문장은 미리 써 둔 기본 문장을 썼어요" in html or "AI가 쉬운 말로 설명 문장을 썼어요" in html
    assert "숫자와 지원 이름이 틀리지 않았는지 검사했고 통과했어요" in html


def test_ai_steps_when_preflight_fails(client_demo, monkeypatch):
    monkeypatch.setattr("app.ui.routes_counsel.preflight", lambda html, fs, cfg: ["OVERFLOW"])
    assert "종이 검사에서 걸린 곳이 있어요" in go_result(client_demo)


def test_print_marks_printed_and_status(client_demo):
    html = go_result(client_demo)
    assert 'id="after-print" role="status" hidden' in html and "printed" not in re.search(r"<body[^>]*>", html).group(0)
    assert client_demo.get("/counsel/print-status").text == "0"
    r = client_demo.get("/counsel/print?auto=1")
    assert r.status_code == 200 and "window.print()" in r.text
    assert "window.print" not in client_demo.get("/counsel/print").text      # auto 없이는 인쇄 창을 띄우지 않는다
    assert client_demo.get("/counsel/print-status").text == "1"
    again = client_demo.get("/counsel/preview").text
    assert "종이를 뽑고 있어요" in again and "처음으로" in again
    assert "printed" in re.search(r"<body[^>]*>", again).group(0) and 'role="status" hidden' not in again.split("종이가 나왔습니다")[0][-80:]
    place = _view(client_demo)[0]["place_name"]
    assert place in again


def test_held_print_is_not_printed(client_demo, monkeypatch):
    go_result(client_demo)
    monkeypatch.setattr("app.ui.routes_counsel.preflight", lambda html, fs, cfg: ["HOLD_ROW"])
    r = client_demo.get("/counsel/print?auto=1")
    assert "종이를 뽑지 못했어요" in r.text and "처음부터 다시" in r.text and "window.print" not in r.text
    assert client_demo.get("/counsel/print-status").text == "0"
    folded = r.text.split("직원에게 전달할 코드")[0]
    assert "HOLD_ROW" not in folded and "HOLD_ROW" in r.text      # 영문 코드는 접힌 칸에만


def test_new_answers_reset_printed(client_demo):
    go_result(client_demo)
    client_demo.get("/counsel/print")
    assert client_demo.get("/counsel/print-status").text == "1"
    client_demo.post("/counsel/confirm", data={})
    assert client_demo.get("/counsel/print-status").text == "0"


def test_edit_answers_prefills_input(client_demo):
    go_result(client_demo)
    html = client_demo.get("/counsel/input?edit=1").text
    assert re.search(r'name="emd_code" value="애월읍" checked', html) and 'value="3600"' in html
    assert 'value="010' not in html and 'name="reminder_phone"' not in html
    assert 'value="3600"' not in client_demo.get("/counsel/input").text         # edit 없이는 빈 화면


def test_edit_without_session_is_empty_form(client_demo):
    assert client_demo.get("/counsel/input?edit=1").status_code == 200


def test_ro_josa():
    assert ro("농관원 제주지원") == "농관원 제주지원으로" and ro("지역농협") == "지역농협으로" and ro("제주시청") == "제주시청으로"
    assert ro("농관원 서울") == "농관원 서울로" and ro("읍사무소") == "읍사무소로"


def test_edit_with_step_opens_that_question(client_demo):
    go_result(client_demo)
    html = client_demo.get("/counsel/input?edit=1&step=4").text
    assert 'data-start="4"' in html and "6개 중 <b>4번째</b>" in html
    assert 'data-start="1"' in client_demo.get("/counsel/input?edit=1&step=99").text


def test_result_edit_link_goes_back_to_questions(client_demo):
    html = go_result(client_demo)
    assert 'class="rb-edit" href="/counsel/input?edit=1"' in html and "답 고치기" in html
    assert 'class="rb-ans"' in html and "애월읍 · 양배추 3,600평" in html      # 답 요약은 한 줄(칩 여섯 개가 아니다)


def test_result_later_items_are_inside_the_detail_overlay_and_cards_carry_paper_numbers(client_demo):
    html = go_result(client_demo)
    detail = html[html.index('id="detail"'):]
    cards = html[html.index('id="cards"'):html.index('class="rbar"')]
    text = re.sub(r"<[^>]+>", " ", detail)
    assert "올해는 어려워요" in text and "내년에 하려면 먼저 이것부터" in text and "먼저 필요한 것: 자조금" in text
    assert "올해는 어려워요" not in cards and "먼저 필요한 것" not in cards      # 카드에는 올해 못 받는 것이 없다
    assert 'class="bx-no"' not in cards      # 번호 동그라미는 없다(2026-11-17)


def test_footer_has_no_staff_link_or_replay_note_on_elder_screens(client_replay):
    go_result(client_replay)
    for url in ("/", "/counsel/input", "/counsel/confirm", "/counsel/preview"):
        t = client_replay.get(url).text
        assert "직원 메뉴" not in t and "체험 모드" not in t and "제주빅데이터센터 제공" not in t, url


def test_press_screen_defaults_send_same_profile_as_before(client_demo):
    """마지막 화면을 안 눌렀을 때(10년 넘음·혼자 하거나 배우자는 안 지어요 기본)가 옛 기본과 같은 프로필이 된다."""
    client_demo.post("/counsel/input", data=P4_FORM)
    base = session_profile(client_demo)
    client_demo.post("/counsel/input", data={**P4_FORM, "farming_years": "", "spouse": "none"})
    again = session_profile(client_demo)
    assert again.farming_years is None and again.spouse == base.spouse and again.farming_10y_plus == base.farming_10y_plus


def test_farming_years_buttons_follow_the_thresholds(client_demo):
    for value, expect in (("1", 1), ("3", 3), ("5", 5)):
        client_demo.post("/counsel/input", data={**P4_FORM, "farming_years": value})
        assert session_profile(client_demo).farming_years == expect


def test_rent_all_is_accepted_for_any_area(client_demo):
    client_demo.post("/counsel/input", data={**P4_FORM, "land_tenure": "rent_all"})      # P4는 3,600평(땅 질문 범위 밖)
    assert session_profile(client_demo).land_tenure == "rent_all"
    assert 'name="land_tenure" value="rent_all"' in client_demo.get("/counsel/input").text


def test_home_due_cards_show_days_left(client_demo):
    html = client_demo.get("/").text
    assert re.search(r"오늘 마감|내일 마감|\d+일 남음|\d+일 뒤 열려요", html) and "지금 신청 받아요" not in html


def test_staff_page_has_title_badge_and_stale_warning(client_demo):
    t = client_demo.get("/staff").text
    assert "직원 메뉴" in t and "직원용" in t and "다시 확인 필요" in t


def test_overdue_renewal_year_is_said_as_a_thing_to_do_now(client_demo):
    """경영체 갱신 해가 올해보다 지났으면 "이미 지났어요. 농관원에 전화하세요"로 풀어 쓴다(카드 밑 '끊기지 않게' 한 줄과 자세히 보기 안)."""
    html = go_result(client_demo, {**P4_FORM, "mgmt_status": "over_2y", "mgmt_last_reg_year": "2020"})
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "농산물품질관리원 1644-8778" in text and "경영체 2023년 갱신" not in text and "이미 지났어요" in text and "농산물품질관리원에 전화" in text
    assert 'class="rn-keep"' in html and html.index('class="rn-keep"') < html.index('class="rbar"')      # 끊기지 않게 할 일은 카드 밑 한 줄로 화면에 남는다


def test_edit_screen_goes_back_to_the_result_and_confirm_goes_back_to_last_step(client_demo):
    go_result(client_demo)
    page = client_demo.get("/counsel/input?edit=1").text
    assert 'href="/counsel/preview"' in page and "결과 보기" in page
    assert "/counsel/input?edit=1&amp;step=6" in client_demo.get("/counsel/confirm").text.replace("&step", "&amp;step")


def test_last_press_screen_starts_with_nothing_pressed_and_ask_once_hint(client):
    html = client.get("/counsel/input").text
    assert not re.search(r'name="(farming_years|spouse|residence_3y)"[^>]*checked', html)
    assert 'data-must="farming"' in html and 'id="hint-must"' in html and 'id="hint-sex"' in html and 'id="hint-year"' in html
