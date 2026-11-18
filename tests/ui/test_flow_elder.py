"""어르신 기준(docs/design/2026-11-15-elder-design-principles.md)으로 맞춘 질문 여섯 장 · 확인 화면 · 찾는 중 화면.
글·표 모양은 HTML과 CSS 글을 직접 읽어 본다(실제 크기는 scripts/screen_fit.py 가 창 크기별로 잰다)."""
import re
from pathlib import Path

from .conftest import P4_FORM

STATIC = Path(__file__).resolve().parents[2] / "app" / "ui" / "static"
def _css(name: str) -> str:
    """주석을 뺀 CSS 글(주석이 규칙 앞에 붙어 선택자를 흐리지 않게)."""
    return re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)


FLOW = _css("flow.css")
QUESTION = _css("question.css")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def rules(css: str, selector: str) -> list[str]:
    """selector 가 (쉼표로 나눈 선택자 가운데) 그대로 있는 규칙들의 본문."""
    found = []
    for sels, body in RULE.findall(css):
        if selector in [s.strip() for s in sels.split(",")]:
            found.append(body)
    return found


def px(value: str) -> float:
    """clamp(24px, 3vh, 30px)처럼 쓴 값은 가장 작은 쪽(첫 px 값), 그냥 24px 은 그 값."""
    m = re.search(r"(\d+(?:\.\d+)?)px", value)
    assert m, value
    return float(m.group(1))


def prop(body: str, name: str) -> str | None:
    m = re.search(rf"(?:^|[;\s]){re.escape(name)}\s*:\s*([^;]+)", body)
    return m.group(1).strip() if m else None


def all_props(css: str, selector: str, name: str) -> list[str]:
    return [v for body in rules(css, selector) if (v := prop(body, name))]


# ------------------------------------------------------------------ 확인 화면

def test_confirm_top_line_and_boxes(client_p2):
    html = client_p2.get("/counsel/confirm").text
    assert "받고 계신 것만 눌러 주세요. 없거나 모르시면 아래 '결과 보기'를 눌러 주세요." in html
    boxes = re.findall(r'<section class="c-box[^"]*"[^>]*>\s*<h2 class="c-band"[^>]*>(.*?)</h2>', html, re.S)
    assert len(boxes) == len(re.findall(r'<section class="c-box', html)) >= 3          # 상자마다 제목 띠가 첫 요소(직불 교육 상자 포함)
    names = [re.sub(r"<[^>]+>|\s+", " ", b).strip() for b in boxes]
    assert "이미 받고 계신 지원" in names and "가입한 보험" in names


def test_confirm_box_band_and_gap_rules():
    band = " ".join(rules(FLOW, ".c-band"))
    assert px(prop(band, "font-size")) >= 24 and "var(--sea-soft)" in band and "var(--ink)" in band and "#fff" not in band      # 옅은 청록 바탕 + 먹색 글자
    gap = " ".join(rules(FLOW, ".c-box + .c-box"))
    assert px(prop(gap, "margin-top")) >= 32


def test_confirm_cards_are_two_columns_big_text():
    grid = " ".join(rules(FLOW, ".c-cards"))
    assert "repeat(2" in grid and px(prop(grid, "gap")) >= 12
    for sel, floor in ((".c-cards .choice-label", 24), (".c-cards .choice-sub", 20)):
        sizes = all_props(FLOW, sel, "font-size")
        assert sizes and all(px(s) >= floor for s in sizes), (sel, sizes)
    assert all(int(w) >= 700 for w in all_props(FLOW, ".c-cards .choice-label", "font-weight") or ["800"])
    heights = all_props(FLOW, ".c-cards .choice-face", "min-height")
    assert heights and all(px(h) >= 76 for h in heights), heights
    one = [b for sels, b in RULE.findall(FLOW) if ".c-cards" in sels and "grid-template-columns" in b and "repeat(2" not in b]
    assert one, "좁은 창은 한 칸"


def test_confirm_check_box_is_big_left_and_not_color_only(client_p2):
    html = client_p2.get("/counsel/confirm").text
    cards = re.findall(r'<label class="choice[^"]*"><input type="checkbox" name="already".*?</label>', html, re.S)
    assert cards
    for c in cards:
        assert c.index('class="choice-mark"') < c.index('class="choice-label"')            # 선택 칸이 이름 앞(왼쪽)
    mark = " ".join(rules(FLOW, ".page-c .choice-mark"))
    assert px(prop(mark, "width")) >= 40 and px(prop(mark, "height")) >= 40
    on = " ".join(rules(FLOW, ".page-c .choice input:checked + .choice-face"))
    assert re.search(r"border:\s*[5-9]px solid var\(--tang-deep\)", on) and "box-shadow" in on    # 굵은 주황 테두리
    assert "opacity: 1" in " ".join(rules(FLOW, ".page-c .choice input:checked + .choice-face .choice-mark svg"))   # 굵은 체크
    assert "background: var(--tang-deep)" in " ".join(rules(FLOW, ".page-c .choice input:checked + .choice-face .choice-mark"))
    bg = prop(on, "background")
    assert bg is None or bg.lower() in ("#fff", "var(--paper)", "#ffe6bf")                       # 고른 바탕은 흰색 또는 옅은 주황


def test_confirm_count_is_announced(client_p2):
    html = client_p2.get("/counsel/confirm").text
    m = re.search(r"<[^>]*data-count[^>]*>", html)
    assert m and 'aria-live="polite"' in m.group(0)
    js = (STATIC / "confirm.js").read_text(encoding="utf-8")
    assert "가지 골랐어요" in js and "data-count" in js


def test_confirm_keeps_items_and_keys(client_p2):
    html = client_p2.get("/counsel/confirm").text
    assert 'name="already" value="JEJU-FARMER-ALLOW"' in html
    for name in ("crop1_ins_disaster", "crop1_ins_income", "safety_owner", "safety_spouse"):
        assert f'name="{name}" value="yes"' in html


# ------------------------------------------------------------------ 질문 화면

GUIDE_CLASSES = (".pick-city", ".area-q", ".area-q.small", ".sell-name", ".press-q", ".must-tag", ".age", ".x2-text", ".crop-chip", ".fund-q")


def test_question_guide_text_has_no_color():
    for sel in GUIDE_CLASSES:
        for body in rules(QUESTION, sel):
            col = prop(body, "color")
            assert col is None or col in ("var(--ink)", "var(--ink-soft)"), (sel, col)
            bg = prop(body, "background")
            assert bg is None or "var(--sea)" not in bg, (sel, bg)


def test_question_selected_choice_is_bold_border_plus_check():
    on = " ".join(rules(QUESTION, ".page-q .choice input:checked + .choice-face"))
    assert re.search(r"border:\s*[5-9]px solid var\(--tang-deep\)", on)          # 고른 보기는 주황(2026-11-16 사장 지시) + 굵은 테두리
    assert "opacity: 1" in " ".join(rules(QUESTION, ".page-q .choice input:checked + .choice-face .choice-mark svg"))
    assert "background: var(--tang-deep)" in " ".join(rules(QUESTION, ".page-q .choice input:checked + .choice-face .choice-mark"))
    tab = " ".join(rules(QUESTION, ".tab.on"))
    assert "var(--sea)" not in tab and re.search(r"border:\s*[5-9]px", tab)           # 시 탭도 색이 아니라 굵은 테두리로


def test_question_buttons_and_text_never_shrink_below_the_floor():
    """원칙 7: 누르는 곳 56px 이상, 글씨 22px 이상. 창이 낮아도 줄이지 않는다(뒤에 오는 규칙이 이기므로 맨 끝 규칙을 본다)."""
    for sel in (".page-q .choice-sm .choice-face", ".page-q .press6 .choice-sm .choice-face", ".page-q .emd-big .choice-face"):
        assert px(rules(QUESTION, sel)[-1] and prop(rules(QUESTION, sel)[-1], "min-height")) >= 56, sel
    for sel in (".page-q .choice-sm .choice-label", ".page-q .press6 .choice-sm .choice-label", ".page-q .choice-tile .choice-label"):
        assert px(prop(rules(QUESTION, sel)[-1], "font-size")) >= 22, sel
    assert px(prop(rules(QUESTION, ".page-q .step-btn")[-1], "min-height")) >= 56


def test_question_wait_button_says_why(client):
    html = client.get("/counsel/input").text
    m = re.search(r"<[^>]*data-bar-note[^>]*>", html)
    assert m and 'aria-live="polite"' in m.group(0)
    js = (STATIC / "input.js").read_text(encoding="utf-8")
    for line in ("사시는 읍·면·동을 눌러 주세요", "키우시는 것을 눌러 주세요", "성별을 눌러 주세요"):
        assert line in js
    wait = " ".join(rules(QUESTION, ".actionbar .btn-main.is-wait"))
    assert "color: #fff" not in wait                                                    # 흰 글씨를 연한 바탕에 얹지 않는다


def test_question_last_screen_marks_must_rows_always(client):
    html = client.get("/counsel/input").text
    assert html.count('class="must-tag"') == 3
    assert "농사 지은 햇수, 배우자, 제주에 사신 햇수는 꼭 눌러 주세요." in html
    assert "아래 세 가지는" not in html
    hid = [b for sels, b in RULE.findall(QUESTION) if ".must-tag" in re.sub(r":not\(\.must-tag\)", "", sels) and "display: none" in b]
    assert not hid, "꼭 눌러야 하는 줄 표시는 어떤 창 크기에서도 숨기지 않는다"


def test_question_values_unchanged(client):
    r = client.post("/counsel/input", data=P4_FORM)
    assert r.status_code == 303
    html = client.get("/counsel/input").text
    for name in ("emd_code", "crop1_crop_code", "crop1_area_py", "owner_sex", "birth_year", "mgmt_status", "crop1_sales_channel",
                 "farming_years", "spouse", "residence_3y", "health_ins", "disaster_damage", "land_tenure"):
        assert f'name="{name}"' in html


# ------------------------------------------------------------------ 찾는 중 화면

def test_working_screen_says_one_thing(client_demo):
    client_demo.post("/counsel/input", data=P4_FORM)
    full = client_demo.get("/counsel/working").text
    html = re.sub(r'<div class="w-more".*?</ul>.*?</div>', "", full, flags=re.S)      # 오래 걸릴 때만(1.2초 뒤) 보이는 세 줄(hidden)은 따로 시험한다
    text = re.sub(r"<[^>]+>", " ", html)
    assert "받을 수 있는 지원을 찾고 있어요" in text and "곧 보여 드릴게요" in text
    for w in ("쉬운 말로", "풀고", "대조", "검사", "AI가", "하나씩 살펴", "틀린 곳", "확인하고 있어요"):
        assert w not in text, w
    assert "w-step" not in html and "/static/working.js" in html and "/counsel/preview?wait=1" in html


def test_working_screen_waits_for_text_and_notices_and_shows_three_lines_only_when_slow(client_demo):
    """찾는 중 화면(2026-11-16): 설명 글과 공고 맞춰 보기가 다 끝날 때까지 기다린 뒤 결과 화면으로 간다. 세 줄은 처음엔 숨겨져 있다."""
    client_demo.post("/counsel/input", data=P4_FORM)
    html = client_demo.get("/counsel/working").text
    more = re.search(r'<div class="w-more" data-w-more hidden>.*?</ul>.*?</div>', html, flags=re.S)
    assert more, "세 줄은 hidden 으로 시작한다"
    lines = [re.sub(r"<[^>]+>", "", li).strip() for li in re.findall(r'<li class="w-step.*?</li>', more[0], flags=re.S)]
    assert [re.sub(r"\(.*?\)", "", x).strip() for x in lines] == ["지원 조건을 하나씩 맞춰 봤어요", "지금 접수 중인 공고를 AI가 읽고 맞춰 보고 있어요", "쉬운 말로 설명을 쓰고 있어요"]
    assert "20초쯤 걸려요. 잠시만 기다려 주세요." in more[0] and "%" not in more[0]      # 지어낸 진행률은 없다
    assert 'class="w-step is-done" data-w-step="rules"' in more[0] and 'data-w-step="match"' in more[0] and 'data-w-step="text"' in more[0]
    js = (Path(__file__).resolve().parents[2] / "app/ui/static/working.js").read_text(encoding="utf-8")
    assert "/counsel/ai" in js and 'j.state === "run"' in js and 'j.match.state === "run"' in js      # 둘 다 run 이 아닐 때만 넘어간다
    assert "LIMIT_MS = 30000" in js and "MIN_MS = 1400" in js and "SLOW_MS = 8000" in js and ".catch(function () { finish(); })" in js      # 오류가 나도 멈추지 않고 넘어간다
    assert 'static/working.js' in html and "<noscript>" in html and "/counsel/preview?wait=1" in html


def test_question_blank_ok_fields_explain_before_the_click():
    """비워도 되는 칸(평수·태어난 해)은 '한 번 더 누르면 넘어가요'를 누르기 전에 아래 띠에 보인다. 등록한 해는 처음 눌러도 바로 넘어간다."""
    js = (STATIC / "input.js").read_text(encoding="utf-8")
    assert js.count("모르시면 '다음'을 한 번 더 눌러 주세요") >= 3          # 첫째 평수 · 둘째 평수 · 태어난 해: 띠에 미리
    assert "warned.year" not in js
    assert "비워 두세요" in (Path(__file__).resolve().parents[2] / "app/ui/templates/input.html").read_text(encoding="utf-8")


def test_question_blank_year_goes_next_at_once():
    """질문 4: 등록한 해를 비워도 '다음'은 한 번에 넘어간다(서버로 가는 칸 이름은 그대로)."""
    js = (STATIC / "input.js").read_text(encoding="utf-8")
    seg = js[js.index("if (i === 3)"):]
    seg = seg[:seg.index("return true;")]
    assert "hint(" not in seg


def test_confirm_cards_are_never_left_under_the_fixed_bottom_bar():
    """확인 화면: 칸을 화면으로 끌어 올 때(Tab·scrollIntoView) 아래 붙박이 띠 밑에 가려져 눌리지 않는 칸이 없다.
    CSS 는 칸 아래에 띠만큼 여유를 두고(scroll-margin), 스크립트는 Tab 으로 온 칸이 띠에 가리면 띠 위로 올린다."""
    margin = [b for sel in (".page-c .choice", ".page-c .choice input") for b in rules(FLOW, sel) if "scroll-margin-bottom" in b]
    assert len(margin) == 2 and all(px(re.search(r"scroll-margin-bottom:\s*([^;]+)", b)[1]) >= 150 for b in margin)
    js = (STATIC / "confirm.js").read_text(encoding="utf-8")
    assert 'form.addEventListener("focusin"' in js and "window.scrollBy" in js and '".actionbar"' in js
