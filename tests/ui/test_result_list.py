"""결과 화면 3차(2026-11-15 설계 result-v2 9절): 줄 하나 = 할 일 하나. 왼쪽은 기관 → 하실 일 → 전화 → 확인 줄, 오른쪽은 받을 것마다 이름 → 금액 → 언제 → 덧말(세로),
가실 곳 그림은 크게, "알아 두세요" 상자, 링크 복사하기, 글씨 하한, 종이 앞면이 화면과 같은 줄·순서. 재생 P1~P5와 골든 사례."""
import re
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests" / "golden")]

from app.catalog.links import load_links  # noqa: E402
from app.core.sheet_cards import build_cards  # noqa: E402
from app.ui.result_view import build_view  # noqa: E402

from .test_replay import run_demo  # noqa: E402
from .test_result_rows import rows_of, visible  # noqa: E402
from .test_result_simplify import NAMES, papers  # noqa: E402,F401  (papers: 골든 22건 + 재생 5건 픽스처)

DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")
APP = ROOT / "app" / "ui"
TEMPLATES = APP / "templates"
RESULT_CSS = (APP / "static" / "result.css").read_text(encoding="utf-8")
PRINT_CSS = (APP / "static" / "print.css").read_text(encoding="utf-8")
COPY_CSS = (APP / "static" / "copylink.css").read_text(encoding="utf-8")
LINKS = load_links(ROOT / "data" / "catalog" / "links.csv")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def classes(el) -> list[str]:
    return el.get("class") or []


@pytest.fixture(params=DEMO_IDS)
def page(request, client_replay):
    r = run_demo(client_replay, request.param)
    assert r.status_code == 200
    return request.param, r.text


# ---------------- 작은 CSS 읽개: (조건, 선택자, 본문) ----------------
def css_rules(css: str) -> list[tuple[str | None, str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[str | None, str, str]] = []

    def block(text: str, media):
        j = 0
        while True:
            k = text.find("{", j)
            if k < 0:
                return
            head, depth, m = text[j:k].strip(), 1, k + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[m], 0)
                m += 1
            body = text[k + 1:m - 1]
            if head.startswith("@media"):
                block(body, head[len("@media"):].strip())
            elif not head.startswith("@"):
                out.append((media, head, body))
            j = m
    block(css, None)
    return out


def declared(css: str, selector: str, prop: str) -> list[tuple[str | None, str]]:
    """선택자(쉼표로 나눈 것 중 하나가 정확히 같은)의 prop 값들을 (조건, 값) 순서대로."""
    res = []
    for cond, sel, body in css_rules(css):
        if selector in [s.strip() for s in sel.split(",")]:
            for m in re.finditer(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+)", body):
                res.append((cond, m[1].strip()))
    return res


def px_values(css: str, selector: str, prop: str = "font-size") -> list[tuple[str | None, float]]:
    vals = []
    for cond, v in declared(css, selector, prop):
        m = re.fullmatch(r"([\d.]+)px", v)
        assert m, (selector, prop, v, "글씨·그림 크기는 px 하나로(clamp 로 줄어들지 않게)")
        vals.append((cond, float(m[1])))
    return vals


def assert_floor(css: str, selector: str, floor: float, small_floor: float | None = None, prop: str = "font-size") -> None:
    """기본값은 floor 이상, 좁은 창·낮은 창 조건 아래 값은 small_floor(없으면 floor) 이상."""
    vals = px_values(css, selector, prop)
    assert vals, f"{selector} 에 {prop} 가 없다"
    assert any(c is None for c, _ in vals) and [v for c, v in vals if c is None][-1] >= floor, (selector, vals)
    for cond, v in vals:
        assert v >= (floor if cond is None else (small_floor or floor)), (selector, cond, v)


# ---------------- 왼쪽: 기관 이름 → 하실 일 → 전화 → 확인 줄 ----------------
LEFT_ORDER = ["rr-name", "rr-todo", "rr-tel", "rr-checks"]


def left_parts(row) -> list[str]:
    return [next(c for c in classes(e) if c in LEFT_ORDER) for e in row.select_one(".rr-l").select(".rr-name, .rr-todo, .rr-tel, .rr-checks")]


def test_box_band_reads_number_picture_place_phone_tags_and_rows_follow(page):
    """상자 띠: 번호 → 그림 → 가실 곳 → (전화) → (딱지). 그 아래에 줄이 세로로만 쌓인다(2026-11-15 4차)."""
    pid, html = page
    order = ["bx-pic", "bx-name", "bx-tel", "bx-tags"]
    for r in rows_of(html):
        box = soup(r).select_one(".bx")
        band = [next(c for c in classes(e) if c in order) for e in box.select_one(".bx-band").find_all(recursive=False)]
        assert band[0] == "bx-pic" and band[1] == "bx-name", (pid, band)      # 번호 동그라미는 없다(2026-11-17)
        assert [order.index(b) for b in band] == sorted(order.index(b) for b in band), (pid, band)
        assert not box.select_one(".bx-go") and "에 가세요" not in box.select_one(".bx-t").get_text()
        assert all(set(classes(li)) & {"bxr-do", "bxr-get"} for li in box.select(".bx-rows > li")), pid
        assert [classes(e)[0] for e in box.find_all(recursive=False)] == ["bx-band", "bx-rows"], pid      # 띠 아래 줄들, 옆에 칸이 없다


def test_p4_first_box_has_the_task_row_then_phone_in_the_band(client_replay):
    box = soup(rows_of(run_demo(client_replay, "P4").text)[0]).select_one(".bx")
    band = box.select_one(".bx-band")
    assert "에 가세요" not in band.select_one(".bx-t").get_text()
    assert band.select_one(".bx-tel b").get_text(strip=True) == "1644-8778" and band.select_one(".bx-tel svg")
    assert not band.select(".bx-tag") and "is-first" not in classes(box)
    first = box.select_one(".bx-rows > li")
    assert "bxr-do" in classes(first) and first.select_one(".bxr-t").get_text(strip=True).startswith("농업경영체 등록") and first.select_one("svg")      # 연필 그림 + 이름


def test_confirm_line_is_one_row_with_title_and_message(client_replay):
    box = soup(rows_of(run_demo(client_replay, "P3").text)[0]).select_one(".bx")
    li = box.select_one(".bx-rows > li.is-confirm")
    text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
    assert "자조금 가입 확인" in text and "가입했는지 농협에 물어보세요" in text


# 종이 앞면(옛 좌우 줄 모양, print.css)의 오른쪽 받을 것 안 순서: 종이 시험이 쓴다
RIGHT_ORDER = {"rg-t": 0, "rg-m": 1, "rx-urgent": 2, "rx-when": 2, "rx-note": 3, "rx-unlock": 4}


def right_kids(li) -> list[str]:
    return [next(c for c in classes(e) if c in RIGHT_ORDER) for e in li.select(".rg-body > *")]


# ---------------- 줄: 표의 한 줄 = 이름 칸(.bxr-top) | 설명 칸(.bxr-d: 금액 → 글 → 언제·남은 날 → 덧말) ----------------
ROW_ORDER = {"bxr-m": 0, "bxr-text": 1, "bxr-when": 2, "bxr-left": 3, "bxr-note": 4, "bxr-opens": 5, "bxr-unlock": 5}


def row_kids(li) -> list[str]:
    """설명 칸 안 조각들의 차례(이름 칸은 따로 하나)."""
    return [next(c for c in classes(e) if c in ROW_ORDER) for e in li.select_one(".bxr-d").find_all(recursive=False) if set(classes(e)) & set(ROW_ORDER)]


def test_each_row_is_one_vertical_bundle_name_money_when_note(page):
    pid, html = page
    n = 0
    for r in rows_of(html):
        for li in soup(r).select(".bx-rows > li:not(.bxr-foot)"):
            assert [classes(e)[0] for e in li.find_all(recursive=False)] == ["bxr-top", "bxr-d"], pid      # 이름 칸 | 설명 칸
            kids = row_kids(li)
            ranks = [ROW_ORDER[k] for k in kids]
            assert ranks == sorted(ranks), (pid, kids)
            assert kids.count("bxr-when") <= 1 and kids.count("bxr-m") <= 1, (pid, kids)
            assert len(li.select(".bxr-top > .bxr-t")) == 1 and len(li.select(".bxr-m")) <= 1
            n += 1
    assert n >= 1


def test_amount_is_first_in_the_description_cell_in_its_own_span_and_none_without_money(client_replay):
    box = soup(rows_of(run_demo(client_replay, "P4").text)[0]).select_one(".bx")
    m = box.select_one(".bx-rows .bxr-m")
    assert m.select_one(".bxr-pre").get_text(strip=True) == "조건이 맞으면"
    assert m.select_one(".bxr-amt").get_text(strip=True) == "연 약 180만~258만 원"
    assert "bxr-d" in classes(m.parent) and m.parent.find_all(recursive=False)[0] is m      # 설명 칸의 맨 앞
    p3 = soup(rows_of(run_demo(client_replay, "P3").text)[0]).select_one(".bx")
    for li in [x for x in p3.select(".bx-rows > li.bxr-get") if not x.select_one(".bxr-amt") and not x.select_one(".left-pill")]:
        assert not li.select_one(".bxr-m"), "금액이 없는 받을 것(시기만 있는 보험)은 금액 줄이 없다"
        assert li.select_one(".bxr-when svg")                               # 언제: 달력 그림 + 글
    # 빨간 딱지('오늘까지')가 있으면 날짜 줄은 '오늘'을 되풀이하지 않는다(2026-11-15 검수)
    urgent = p3.select_one(".bxr-get:has(.left-pill)")
    assert urgent.select_one(".left-pill").get_text() == "오늘까지"
    assert urgent.select_one(".bxr-when") is None and "11월 13일까지" not in urgent.get_text()      # 같은 뜻의 날짜 줄은 없다(2026-11-16 검증)
    # 마감이 급한 줄(딱지)은 받을 것 줄의 맨 위
    assert p3.select(".bxr-get")[0] is urgent


def test_rows_are_split_by_a_thin_rule(client_replay):
    box = soup(rows_of(run_demo(client_replay, "P3").text)[0]).select_one(".bx")
    assert len(box.select(".bx-rows > li")) == 2          # 마늘 보험(오늘까지) · 자조금 확인(토양생태·월동무 보험은 내년이라 앞으로 구역)
    assert "solid" in declared(RESULT_CSS, ".bxr + .bxr", "border-top")[0][1] and "var(--line)" in declared(RESULT_CSS, ".bxr + .bxr", "border-top")[0][1]      # 같은 곳 안의 지원 사이: 가는 옅은 줄


def test_a_row_is_name_cell_then_description_cell_and_stacks_when_narrow():
    assert declared(RESULT_CSS, ".bxr", "display")[-1][1] == "grid" and declared(RESULT_CSS, ".bxr", "grid-template-columns")[0][1] == "var(--c3) minmax(0, 1fr)"
    assert declared(RESULT_CSS, ".bxr", "grid-template-columns")[-1][1] == "minmax(0, 1fr)"      # 폭이 좁으면 이름 칸 아래 설명 칸
    assert declared(RESULT_CSS, ".bx-rows", "flex-direction")[-1][1] == "column"
    assert not declared(RESULT_CSS, ".bx-rows", "display") or declared(RESULT_CSS, ".bx-rows", "display")[-1][1] == "flex"


# ---------------- 가실 곳 그림: 줄마다 있고 크다 ----------------
def test_every_box_has_a_big_place_picture_beside_the_number(page):
    pid, html = page
    for r in rows_of(html):
        band = soup(r).select_one(".bx-band")
        assert not band.select_one(".bx-no") and band.select_one(".bx-pic svg.ic-p")
        kids = [classes(e)[0] for e in band.find_all(recursive=False)]
        assert kids.index("bx-pic") == 0 and kids.index("bx-name") == 1          # 그림 바로 옆에 곳 이름
        assert len(band.select_one(".bx-pic svg").find_all()) >= 2             # 비어 있지 않다


def test_place_picture_css_is_64px_or_more_and_56px_in_small_windows():
    vals = px_values(RESULT_CSS, ".ic-p", "width")
    base = [v for c, v in vals if c is None]
    assert base and base[-1] >= 64
    assert px_values(RESULT_CSS, ".ic-p", "height")[0][1] == base[-1]
    small = [v for c, v in vals if c is not None]
    assert small and min(small) >= 56, vals


def render_rows(cards) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    return env.from_string('{% import "_result_rows.html" as rr %}{{ rr.rows(cards) }}').render(cards=cards)


PLACES = {"지역농협": "M24 40 V27", "농산물품질관리원(농관원) 제주지원": "M8 4 h20 l9 9", "건강보험공단 지사": "M24 4 L40 9", "국민연금공단 제주지사": "M13 19 l2 -6",
          "농지은행·농어촌공사 제주지역본부": "M6 24 L21 8", "주소지 읍·면·동": "M5 22 L24 12", "행정시 민원실": "M5 22 L24 12", "어딘가 이름 모를 곳": "M9 43 V9",
          "": "M9 43 V9", "감협": "M24 40 V27"}


@pytest.mark.parametrize("place,mark", sorted(PLACES.items()))
def test_every_kind_of_place_gets_its_own_or_the_default_picture(place, mark):
    card = {"no": "①", "no_n": "1", "head": place or None, "head_go": bool(place), "icon": place, "icon_name": None, "phone": None, "tel_note": None, "todo": [], "gets": [],
            "act": None, "wide": True, "emphasis": False, "pill": None, "hidden_n": 0, "hidden_names": [], "where": None, "conds": [], "lines": [], "first": False}
    pic = soup(render_rows([card])).select_one(".rr-pic svg")
    assert pic is not None and mark in str(pic), place


@pytest.mark.parametrize("name", NAMES)
def test_no_place_in_any_case_is_left_without_a_picture(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    v = build_view(sheet, fs, bundle, as_of)
    for row in soup(render_rows(v["cards"])).select(".rr"):
        assert row.select_one(".rr-pic svg") and len(row.select_one(".rr-pic svg").find_all()) >= 2, name


def test_pictures_are_drawn_in_the_same_line_style_as_the_others():
    art = (TEMPLATES / "_art.html").read_text(encoding="utf-8")
    for macro in ("pi_pension", "pi_farmland", "pi_building", "pi_gov", "pi_coop", "pi_qa", "pi_health"):
        body = art[art.index("macro " + macro):].split("endmacro")[0]
        assert 'stroke="#2B2724"' in body and 'stroke-width="3' in body, macro
    assert "('국민연금', 'pi_pension')" in art and "('농지은행', 'pi_farmland')" in art and "('농어촌공사', 'pi_farmland')" in art


# ---------------- 알아 두세요 상자 ----------------


def know_items(html: str) -> list[str]:
    box = soup(html).select_one(".know")
    items = [re.sub(r"\s+", " ", li.get_text(" ", strip=True)) for li in box.select("li")] if box else []
    return items


def old_wording(v: dict) -> list[list[str]]:
    """예전 작은 덧말 줄의 항목마다 그 글 조각들(한 항목의 조각이 모두 있어야 같은 글)."""
    out = []
    if v["bring"]:
        out.append([v["bring"]])
    out += [["끊기지 않게", k["title"], k["text"]] for k in v["keeps"]]
    if v["others_n"]:
        out.append([f"그 밖에 {v['others_n']}가지", "자세히 보기에서 볼 수 있어요"])
    return out


def squash(t: str) -> str:
    return re.sub(r"\s+", "", t)


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_know_box_is_one_titled_box_with_the_same_words_as_before(client_replay, papers, pid):
    html = run_demo(client_replay, pid).text
    s = soup(html)
    fs, sheet, bundle, as_of = papers[f"demo_{pid}"]
    wanted = old_wording(build_view(sheet, fs, bundle, as_of, screen=True))      # 화면은 가실 곳·줄을 전부 보이므로 "그 밖에 ○가지"는 없다
    shown = know_items(html)
    assert not s.select(".rnote"), "흩어진 작은 덧말 줄은 없고 상자 하나뿐"
    if not wanted:
        assert not shown
        return
    box = s.select_one(".know")
    assert box and box.select_one(".know-t").get_text(strip=True) == "알아 두세요"
    assert 1 <= len(shown) <= 4                                                    # 세 줄 + 작은 창에서만 보이는 '금액은 올해 기준이에요' 줄
    for item in [i for i in shown if not i.startswith("금액은 올해 기준이에요")]:
        assert any(all(squash(p) in squash(item) for p in w) for w in wanted) or "자세히 보기에서 볼 수 있어요" in item, (pid, item)
    detail = squash(s.select_one("#detail").get_text())
    for w in wanted:                                                               # 상자에 못 실은 항목은 자세히 보기에 있다
        shown_here = any(all(squash(p) in squash(item) for p in w) for item in shown)
        assert shown_here or all(squash(p) in detail for p in w if p != "끊기지 않게"), (pid, w)


def test_p3_know_box_shows_all_three_pieces_since_the_screen_has_no_others_line(client_replay):
    html = run_demo(client_replay, "P3").text
    shown = [i for i in know_items(html) if not i.startswith("금액은 올해 기준이에요")]
    assert len(shown) == 3 and "이 종이와 신분증" in shown[0] and not any("그 밖에" in i for i in shown)
    detail = soup(html).select_one("#detail").get_text()
    assert "농업경영체 갱신" in detail and "이 종이와 신분증" in detail and "직불 교육" in detail


def test_know_css_sizes():
    assert_floor(RESULT_CSS, ".know-t", 22)
    assert_floor(RESULT_CSS, ".know li", 20)


# ---------------- 링크 복사하기 ----------------
@pytest.mark.parametrize("name", NAMES)
def test_detail_links_are_exactly_the_results_supports_that_have_an_official_address(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    cs = build_cards(sheet, fs)
    keys = {cl.line.program_key for cl in cs.card_lines if cl.line.program_key} | {it.line.program_key for it in cs.later if it.line.program_key}
    v = build_view(sheet, fs, bundle, as_of, links=LINKS)
    got = {k: x for x in v["detail"]["links"] for k in x["keys"]}                  # 같은 주소를 쓰는 지원은 한 줄로 묶인다(keys)
    assert {k for k in got if k in keys} == {k for k in keys if k in LINKS}, name   # (보험 줄의 열쇠는 이 표에 더 붙는다: test_result_review3)
    assert all(x["url"] == LINKS[k].url and x["title"] for k, x in got.items()), name
    assert len({x["url"] for x in v["detail"]["links"]}) == len(v["detail"]["links"])      # 주소마다 한 줄
    assert build_view(sheet, fs, bundle, as_of)["detail"]["links"] == []            # 주소 표를 안 넘기면 단추도 없다


def test_detail_shows_two_buttons_per_supported_link_and_none_without(client_replay):
    found = 0
    for pid in DEMO_IDS:
        s = soup(run_demo(client_replay, pid).text)
        for li in s.select("#detail .lk-box li.lk"):
            key = li["data-key"]
            if key.startswith("new-"):                                                 # 맞을 수 있는 새 공고(재생 녹화 M-P*가 있으면 나온다): 주소는 공고 파일의 것, 공식 누리집뿐
                a = li.select_one("a.lk-open")
                assert re.match(r"https://www\.(seogwipo\.go\.kr|jejusi\.go\.kr|jeju\.go\.kr)/", a["href"]) and a["href"] == li.select_one("button.lk-copy")["data-copy-url"]
                continue
            assert key in LINKS and set(li["data-keys"].split()) <= set(LINKS)
            a, b = li.select_one("a.lk-open"), li.select_one("button.lk-copy")
            assert a["href"] == LINKS[key].url == b["data-copy-url"]
            assert a["target"] == "_blank" and "noopener" in a["rel"] and a.get_text(strip=True) == "공고문 보기"
            assert "링크 복사하기" in b.get_text() and b.select_one("svg")           # 그림 + 글
            assert LINKS[key].url not in li.get_text(), "긴 주소 글자를 늘어놓지 않는다"
            found += 1
    assert found >= 3


def test_every_other_result_has_no_link_box_when_no_support_has_an_address(client_replay):
    s = soup(run_demo(client_replay, "P1").text)
    keys = {li["data-key"] for li in s.select("#detail li.lk")}
    assert {k for k in keys if not k.startswith("new-")} <= set(LINKS)             # 새 공고 줄(new-…)은 공고 파일의 주소를 쓴다
    assert len(s.select("#detail button.lk-copy")) == len(keys)


def test_result_page_has_the_copy_done_message_slot_and_script(client_replay):
    html = run_demo(client_replay, "P4").text
    done = soup(html).select_one("#detail .lk-done")
    assert done and done.get("aria-live") == "polite" and done.get("data-msg") == "복사했어요. 카카오톡이나 문자에 붙여 넣으세요"
    assert soup(html).select_one("#detail .lk-fallback")                           # 복사가 안 될 때 주소가 든 입력칸(처음에는 숨김)
    js = (APP / "static" / "copylink.js").read_text(encoding="utf-8")
    assert "navigator.clipboard" in js and "writeText" in js and "4000" in js and ".select()" in js
    assert 'src="/static/copylink.js"' in html


def test_support_page_has_copy_button_next_to_the_notice_button(client_demo):
    from .test_supports import catalog_of
    cat = catalog_of(client_demo)
    linked = [e for e in cat.entries if e.link is not None]
    assert linked
    for e in linked[:5]:
        html = client_demo.get(e.href).text
        s = soup(html)
        a, b = s.select_one("a.sp-ext"), s.select_one("button.lk-copy")
        assert b is not None and b["data-copy-url"] == e.link.url == a["href"]
        assert "링크 복사하기" in b.get_text() and b.select_one("svg")
        assert s.select_one(".lk-done[aria-live]") and 'src="/static/copylink.js"' in html
        assert e.link.url not in s.select_one(".sp-link").get_text()
    for e in [e for e in cat.entries if e.link is None][:3]:
        assert not soup(client_demo.get(e.href).text).select("button.lk-copy")


def test_copy_button_css_height():
    assert_floor(COPY_CSS, ".lk-copy", 56, prop="min-height")
    assert_floor(COPY_CSS, ".lk-open", 56, prop="min-height")


# ---------------- 글씨 하한 (px) ----------------
@pytest.mark.parametrize("selector,floor,small", [
    (".bx-t", 28, 26), (".bxr-t", 26, 26), (".bx-tel b", 28, 28), (".bxr-text", 22, 22), (".bxr-m", 28, 28), (".bxr-when", 22, 22),
    (".bxr-note", 20, 20), (".bxr-unlock", 22, 22), (".bxr-opens", 22, 22), (".lt-t", 24, 24), (".lt-where", 22, 22), (".nn-name", 26, 26), (".nn-why", 22, 22)])
def test_font_floors(selector, floor, small):
    assert_floor(RESULT_CSS, selector, floor, small)


def test_group_rule_is_2px_and_sizes_do_not_shrink_with_the_window():
    assert "vh" not in " ".join(v for _, v in declared(RESULT_CSS, ".bx-t", "font-size"))
    gap = px_values(RESULT_CSS, ".rbx", "gap")
    assert gap and all(v == 2 for _, v in gap)      # 표: 묶음 사이는 2px 줄(틈 사이로 바탕이 비친다)


# ---------------- 종이 앞면: 화면과 같은 줄·순서 ----------------
@pytest.fixture(scope="module")
def paper_html():
    from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS
    from factsheet_fixtures import amount, make_fs
    from app.config import load_config
    from app.core.sheet import build_sheet
    from app.data_layer.tables import load_tables
    from app.ui.render import render_sheet
    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(ROOT / "data" / "tables", AS_OF)
    out = {}
    for name, kw, amts in (("P1", P1_KWARGS, ()), ("P2", P2_KWARGS, ()), ("P3", P3_KWARGS, ()),
                           ("P4", P4_KWARGS, (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)), ("P5", P5_KWARGS, ())):
        fs = make_fs(kw, bundle, AS_OF, amounts=amts)
        out[name] = render_sheet(build_sheet(fs, bundle, AS_OF), fs, None, cfg, crop_labels={}, programs=bundle.programs)
    return out


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_paper_boxes_have_the_same_parts_in_the_same_order_as_the_screen(paper_html, pid):
    """종이 표(2026-11-17): 소분류 칸 = [곳 그림 · 체크 칸] → 가실 곳 이름 → (어디서) → 전화 → (딱지), 그 옆 지원 칸에 받는 것이 세로로만. 화면 상자(.bx)와 같은 차례(2026-11-18: 그림이 번호 동그라미 자리에 온다)."""
    rows = soup(paper_html[pid]).select(".front .pg.rrw")
    assert 1 <= len(rows) <= 5
    order = ["pc-top", "pb-t", "pb-where", "pb-tel", "pb-tags"]
    for box in rows:
        cell = [classes(e)[0] for e in box.select_one(".pc").find_all(recursive=False)]
        assert cell[:2] == ["pc-top", "pb-t"], cell
        assert [order.index(c) for c in cell] == sorted(order.index(c) for c in cell), cell
        assert [classes(e)[0] for e in box.select_one(".pc-top").find_all(recursive=False)] == ["pc-pic", "bx"]       # 곳 그림 다음에 체크 칸
        assert box.select_one(".pc-pic svg") and not box.select(".pb-pic, .pb-no")                          # 화면 상자 띠와 같은 곳 그림, 번호 동그라미는 없다
        assert [classes(e)[0] for e in box.find_all(recursive=False)][:2] == ["pc", "pc-r"]               # 소분류 칸 옆에 지원 칸
        for li in box.select(".pb-rows > li"):
            kids = [classes(e)[0] for e in li.find_all(recursive=False)]
            assert kids[0] == "pr-top", kids


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_paper_front_has_the_know_lines_like_the_screen_and_fits(paper_html, pid):
    from app.ui.render import check_overflow
    html = paper_html[pid]
    s = soup(html)
    assert not s.select(".front .know, .front .know-t")                              # 알아 두세요 상자·제목은 종이에 없다(2026-11-18)
    lines = [p.get_text(" ", strip=True) for p in s.select(".front .keepl p")]
    assert lines and lines[0].startswith("가실 때:") and all(l.startswith(("가실 때:", "끊기지 않게")) for l in lines)       # 화면 알아 두세요의 두 가지 줄만
    assert "영농도우미" not in " ".join(lines) and "올해는 어려운 것" not in " ".join(lines)
    assert not s.select(".front p.fx"), "표 아래 줄은 한 덩어리(.keepl) 안에만 있다"
    assert check_overflow(html) == []


def test_paper_css_sizes_in_pt():
    block = PRINT_CSS[PRINT_CSS.index("---------- 종이 v2"):PRINT_CSS.index("---------- 화면 미리보기")]

    def pt(sel):
        m = re.search(rf"{re.escape(sel)} \{{[^}}]*?font-size:\s*(?:var\(--\w+,\s*)?([\d.]+)pt", block)         # 표 안 글자는 글자 단계 변수(var(--tn, 16pt))의 기본값
        assert m, sel
        return float(m[1])
    assert pt(".v2 .pb-t") >= 18 and pt(".v2 .pr-t") >= 16 and pt(".v2 .pb-tel b") >= 16
    assert pt(".v2 .pr-m") >= 18 and pt(".v2 .pr-note") >= 14 and pt(".v2 .pr-when") >= 14 and pt(".v2 .pb-tag") >= 14
    m = re.search(r"\.v2 \.ic-p \{[^}]*width:\s*([\d.]+)mm", block)
    assert m and float(m[1]) >= 15                                                  # 큰 그림(15mm = 약 57px 이상)


# ---------------- 종이 줄 높이 어림(새 모양) ----------------
def _card(**kw):
    base = {"head": "지역농협", "head_go": True, "phone": None, "tel_note": None, "act": None, "where": None, "hidden_n": 0, "wide": False, "no": "①",
            "todo": [], "gets": [], "pill": None}
    return {**base, **kw}


def _get(**kw):
    return {"role": "benefit", "title": "소농직불금", "text": "130만 원", "text_when": False, "pre": "", "amt": "130만 원", "whens": [], "notes": [], "check": False, "unlocks_n": 0, **kw}


def test_row_estimate_stacks_every_piece_of_a_bundle():
    from app.ui.render import paper_row_lines
    one = _card(gets=[_get(whens=[])])
    full = _card(gets=[_get(whens=["예년 3월"], notes=["재해보험·수입안정보험 둘 중 하나만"], check=True)])
    assert paper_row_lines(full) > paper_row_lines(one)                              # 언제·덧말·조건 확인이 세로로 더해진다
    assert paper_row_lines(_card(gets=[_get(), _get(title="소규모 농가 경영안정 지원")])) > paper_row_lines(one) + 0.8      # 받을 것이 둘이면 위아래로 쌓인다


def test_row_estimate_stacks_the_left_column_name_task_phone_check():
    from app.ui.render import paper_row_lines
    task = {"role": "do", "title": "농업경영체 등록 (농관원)", "text": "", "text_when": False, "whens": [], "notes": [], "check": False}
    chk = {"role": "confirm", "title": "배우자 등록 여부와 대상 확인", "text": "농관원에 문의해 보세요", "text_when": False, "whens": [], "notes": [], "check": True}
    name_only = _card(wide=True, head="지역농협")
    with_all = _card(wide=True, head="지역농협", phone="1644-8778", todo=[task, chk])
    assert paper_row_lines(with_all) > paper_row_lines(name_only) + 1.0
    assert paper_row_lines(_card(wide=True, head="지역농협")) >= 16.0 / 7.34 * 0.9      # 가실 곳 그림(16mm)보다 낮게 어림하지 않는다


def test_front_overflow_check_still_flags_too_tall_rows():
    from app.ui.render import check_overflow, front_lines
    html = '<section class="sheet front cardsheet v2">' + '<div class="rrw line pt16" data-sec="Rr" data-n="12.5">줄</div>' * 3 + '</section><section data-page="back"></section>'
    assert front_lines(html) > 37.1 and any("너무 길어요" in m for m in check_overflow(html))
    box = '<div class="know line pt14" data-sec="K" data-n="3">상자</div>'
    assert front_lines(html.replace("</section><section", box + "</section><section", 1)) > front_lines(html)         # 알아 두세요 상자도 높이를 더한다


def test_no_check_line_in_boxes_and_know_line_says_where(page):
    """상자 줄에는 '조건을 확인해야 해요'를 붙이지 않는다. 알아 두세요에도 그 말이 없고(2026-11-18), 화면 어디에도 '뒷면'이 없다."""
    pid, html = page
    s = soup(html)
    assert not s.select(".bxr-check, .bxr-foot") and "조건을 확인해야 해요" not in html
    assert "조건은" not in (s.select_one(".know-list").get_text() if s.select_one(".know-list") else "")          # 2026-11-18: 알아 두세요에 '조건은 … 직원과 같이 확인해요' 줄은 없다
    assert "뒷면" not in html and "양면" not in html


def test_result_css_has_no_font_below_22px():
    import re
    for m in re.finditer(r"font-size:\s*(?:clamp\()?(\d+)px", RESULT_CSS):
        assert int(m.group(1)) >= 22, m.group(0)
