"""결과 화면 두 구역(2026-11-15 사장 지시): 지금 하실 일(위) · 앞으로 신청할 것(아래). 줄 하나는 한 구역에만 · 줄은 하나도 사라지지 않는다 · 상자·줄 순서 · 선행 조건 이름 글 · 빈 구역 글.
골든 22건 + 재생 5건(test_result_simplify.papers 픽스처). 종이(screen=False)는 이 규칙 밖이다."""
import re

import pytest

from app.catalog.texts import window_of
from app.core.sheet import EmptyFront
from app.core.sheet_cards import build_cards
from app.ui.result_view import SCREEN_MAX_CARDS, build_view, reul, unlock_sentence

from .test_replay import run_demo
from .test_result_rows import later_of, rows_of, visible
from .test_result_simplify import NAMES, papers  # noqa: F401


def _full(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    if isinstance(sheet.front, EmptyFront):
        pytest.skip("빈 종이는 두 구역 밖(끊기지 않게 할 일 상자만)")
    cs = build_cards(sheet, fs, None, max_cards=SCREEN_MAX_CARDS, max_lines=99)
    return build_view(sheet, fs, bundle, as_of, screen=True), cs, {p.id: p for p in bundle.programs}, as_of


@pytest.mark.parametrize("name", NAMES)
def test_every_line_is_in_exactly_one_zone_and_none_is_lost(papers, name):
    v, cs, _, _ = _full(papers, name)
    now_titles = [ln["title"] for c in v["now_cards"] for ln in c["lines"]]
    later_titles = [r["title"] for r in v["later_rows"]]
    far_titles = [r["title"] for r in v["far_rows"]]               # 넉 달 밖 줄은 표에서 줄었지만 사라진 것이 아니다(직원용 창 목록에 전부)
    assert far_titles == [x["title"] for x in v["detail"]["far"]]
    assert (v["later_far"] or {}).get("n", 0) == len(far_titles)
    later_titles += far_titles
    all_titles = [cl.title for cl in cs.card_lines]
    assert len(now_titles) + len(later_titles) == len(all_titles) == sum(len(c["lines"]) for c in v["cards"])      # 전 줄 수 = 지금 + 앞으로
    assert sorted(now_titles + later_titles) == sorted(all_titles)
    assert not set(now_titles) & set(later_titles)                                                                 # 한 줄이 두 구역에 같이 나오지 않는다
    assert sum(len(g["rows"]) for g in v["later_groups"]) == len(v["later_rows"])
    assert not set(later_titles[:len(v["later_rows"])]) & set(far_titles)                                          # 표 줄과 먼 줄은 겹치지 않는다


@pytest.mark.parametrize("name", NAMES)
def test_now_zone_lines_are_todo_or_open_now_and_later_lines_are_neither(papers, name):
    v, cs, prog_of, as_of = _full(papers, name)
    now_t = {ln["title"] for c in v["now_cards"] for ln in c["lines"]}
    for cl in cs.card_lines:
        p = prog_of.get(cl.line.program_id or "")
        w = window_of(p, as_of) if p is not None else None
        is_now = cl.todo or (w is not None and w.open_now)
        assert (cl.title in now_t) == is_now, (name, cl.title)
    assert [c["no_n"] for c in v["now_cards"]] == [str(i + 1) for i in range(len(v["now_cards"]))]            # 번호는 지금 구역 상자에만 1부터
    assert all(c["pill"] is None and not c["first"] and not c["now"] for c in v["now_cards"])                  # 딱지·굵은 테두리 없음


@pytest.mark.parametrize("name", NAMES)
def test_now_boxes_order_dated_then_todo_then_always(papers, name):
    v, _, _, _ = _full(papers, name)

    def kind(c):
        rows = c["rows"]
        if any(r.get("urgent") for r in rows):
            return 0
        if any(r["kind"] == "do" for r in rows):
            return 1
        return 2
    ks = [kind(c) for c in v["now_cards"]]
    assert ks == sorted(ks), (name, ks)
    for c in v["now_cards"]:                       # 상자 안: 마감 날짜가 있는 줄이 맨 위
        urgent = [bool(r.get("urgent")) for r in c["rows"]]
        assert urgent == sorted(urgent, reverse=True), (name, urgent)


@pytest.mark.parametrize("name", NAMES)
def test_later_rows_are_by_month_and_unknown_time_is_last(papers, name):
    v, _, _, _ = _full(papers, name)
    known = [r["known"] for r in v["later_rows"]]
    assert known == sorted(known, reverse=True), (name, known)                  # 때를 아는 줄 → 때를 모르는 줄
    for g in v["later_groups"]:
        assert g["rows"] and all(r["known"] == g["known"] for r in g["rows"])
        if g["known"]:
            assert all(r["when"] == g["when"] for r in g["rows"])               # 같은 달은 한 묶음


@pytest.mark.parametrize("name", NAMES)
def test_paper_view_has_no_zone_values(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    assert "now_cards" not in build_view(sheet, fs, bundle, as_of)               # 종이용 값은 두 구역이 아니다(종이 앞면은 이번에 그대로)


def test_reul_and_unlock_sentence_follow_the_last_syllable():
    assert reul("소농직불금") == "소농직불금을" and reul("농민수당") == "농민수당을" and reul("가격안정관리제(브로콜리)") == "가격안정관리제(브로콜리)를"
    assert reul("토양생태환경보전(월동채소 면적조절)") == "토양생태환경보전(월동채소 면적조절)을"          # 끝의 괄호는 읽지 않는다
    assert unlock_sentence(["제주 농민수당"]) == "이것을 해야 제주 농민수당을 받을 수 있어요"
    assert unlock_sentence(["제주 농민수당", "면적직불금"]) == "이것을 해야 제주 농민수당, 면적직불금을 받을 수 있어요"
    assert unlock_sentence(["가", "나", "다"]) == "이것을 해야 가, 나 외 1가지를 받을 수 있어요"
    assert unlock_sentence(["가", "나", "다", "라", "마"]) == "이것을 해야 가, 나 외 3가지를 받을 수 있어요"


def test_prereq_lines_say_which_support_they_open_by_name(client_replay):
    s = run_demo(client_replay, "P4").text
    m = re.search(r'<span class="bxr-opens">(.*?)</span>', s)
    assert m and m[1] == "이것을 해야 제주 농민수당, 면적직불금 외 2가지를 받을 수 있어요"
    assert "알아볼 수 있는 지원" not in visible(s[s.index('id="cards"'):s.index('id="later"')])
    p3 = run_demo(client_replay, "P3").text
    assert "이것을 해야 토양생태환경보전(월동채소 면적조절)을 받을 수 있어요" in visible(p3)


def test_empty_now_zone_says_so_in_one_line(client_replay, monkeypatch):
    import app.ui.routes_counsel as rc
    real = rc.build_view

    def fake(*a, **k):
        v = real(*a, **k)
        v["now_cards"] = []                 # 지금 구역에 줄이 하나도 없는 경우
        return v
    monkeypatch.setattr(rc, "build_view", fake)
    from .test_result_list import soup
    s = soup(run_demo(client_replay, "P4").text)          # 지금 접수 중인 공고가 없는 농가(공고 상자가 있으면 그것도 지금 할 일이다)
    assert s.select_one(".zn-none").get_text(strip=True) == "지금 바로 하실 일은 없어요. 아래 달에 신청하시면 돼요."
    assert s.select_one(".rb-n").get_text(strip=True) == "지금 바로 하실 일은 없어요" and not s.select("#now .zn-n") and not s.select("#cards article")
    assert "지금 가실 곳" not in s.select_one("#summary").get_text()


def test_screen_has_two_zones_in_order_and_later_zone_is_plain(client_replay):
    html = run_demo(client_replay, "P3").text
    assert html.index('id="summary"') < html.index('id="now"') < html.index('id="cards"') < html.index('id="later"') < html.index('class="know"') < html.index('class="rbar"')
    assert re.search(r"지금 하실 일\s*<span class=\"zn-n\"> 3곳", html)
    assert html.index('id="rtab"') < html.index('id="now"') and html.count('id="rtab"') == 1      # 두 구역은 표 하나 안에 있다
    later = html[html.index('id="later"'):html.index('class="know"')]
    assert "<article" not in later and "bx-no" not in later       # 상자·번호 없음
    assert "신청하는 달에 문자로 알려 드려요" in later and 'data-rm-open' in later and "문자 알림 받기" in later
    assert [t.strip() for t in re.findall(r'class="lt-when">(.*?)</h3>', later)] == ["내년 1월쯤", "내년 3월쯤"]          # 넉 달(11월 기준 3월)까지만 표에
    assert later_of(html).count("월동무 농작물보험") == 0 and len(rows_of(html)) == 3
    assert "그뒤에도2가지가더있어요·내년5월부터신청해요" in later_of(html).replace(" ", "")
    assert later.index('class="lt-more"') < later.index('class="lt-remind"')          # 먼 줄 안내 바로 아래에 문자 알림 줄


# ---------------- 표 하나(2026-11-16 사장 지시): 대분류 | 소분류 | 지원 이름 | 설명 ----------------
def _cells(row):
    return [c["class"][0] for c in row.find_all(recursive=False)]


def test_result_is_one_table_with_zone_place_name_and_description_cells(client_replay):
    from .test_result_list import soup
    s = soup(run_demo(client_replay, "P1").text)
    tab = s.select_one("#rtab")
    assert [z["id"] for z in tab.find_all("section", recursive=False)] == ["now", "later"]       # 대분류: 지금 하실 일 · 앞으로 신청할 것
    for z in tab.select("section.zn"):
        assert _cells(z) == ["zn-lab", "zn-body"] and z.select_one(".zn-lab h2.zn-h")             # 대분류 칸은 제목(h2) 한 칸
    for g in tab.select("#cards article.bx"):
        assert _cells(g) == ["bx-band", "bx-rows"] and g.select_one(".bx-band .bx-t")               # 소분류 칸(가실 곳) | 줄들
        for li in g.select(".bx-rows > li"):
            assert _cells(li) == ["bxr-top", "bxr-d"]                                               # 지원 이름 칸 | 설명 칸
    for g in tab.select("#later .lt-g"):
        assert _cells(g) == ["lt-when", "lt-rows"]                                                  # 소분류 칸(때) | 줄들
        for li in g.select(".lt-r"):
            assert _cells(li) == ["lt-t", "lt-d"]
    assert not tab.select("thead, th")                                                              # 머리 줄은 없다


def test_every_amount_title_date_and_phone_of_the_view_is_in_the_table(papers):
    """바꾸기 전과 뒤에 화면에 나오는 지원 이름·금액·날짜·전화·덧말이 같다(표 안에 빠짐없이)."""
    from jinja2 import Environment, FileSystemLoader

    from pathlib import Path

    from .test_result_rows import visible
    env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "app/ui/templates")), autoescape=True)
    for name in NAMES:
        fs, sheet, bundle, as_of = papers[name]
        if isinstance(sheet.front, EmptyFront):
            continue
        v = build_view(sheet, fs, bundle, as_of, screen=True)
        html = env.from_string('{% import "_result_boxes.html" as bx %}{{ bx.boxes(cards) }}').render(cards=v["now_cards"])
        now_text = visible(html)
        for c in v["now_cards"]:
            if c["phone"]:
                assert c["phone"] in now_text, (name, c["phone"])
            for r in c["rows"]:
                assert r["title"] in now_text and (not r["amt"] or r["amt"] in now_text), (name, r["title"])
                for n in r["notes"]:
                    assert n in now_text, (name, n)


def test_later_rows_of_the_table_keep_every_title_amount_place_and_note(client_replay, monkeypatch):
    """표로 바꾸기 전 앞으로 구역에 있던 글(P1·P3)이 표의 설명 칸에 그대로 있다. 같은 곳은 줄마다 되풀이한다."""
    from .test_result_list import soup
    want = {"P1": ["소규모 농가 경영안정 지원", "15만 원", "소농직불금", "130만 원", "여성농업인 행복이용권", "20만 원", "제주 농민수당", "작년처럼 다시 신청하세요",
                   "밭(과수원)이 있는 곳의 읍·면사무소에서 신청해요", "집에서는 농업e지나 전화 1334", "노지감귤(온주) 농작물보험", "재해보험만 들 수 있어요", "수입안정보험은 대상이 아니에요"],
            "P3": ["[친서민] 소형농기계 지원", "[친서민] 밭작물 관수시설 자재", "제주 농민수당", "면적직불금", "약 131만~137만 원", "대정농협", "월동무 농작물보험", "날짜는 농협에 물어보세요"]}
    import app.ui.result_view as rv
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 13)          # 줄이지 않는 기준으로 본다(줄인 모습은 test_later_window.py)
    for name, items in want.items():
        s = soup(run_demo(client_replay, name).text)
        later = " ".join(s.select_one("#later").get_text(" ", strip=True).split())
        for it in items:
            assert it in later, (name, it)
        for li in s.select("#later .lt-r"):
            assert li.select_one(".lt-t").get_text(strip=True)


def test_script_made_zone_count_text_is_the_same_as_the_server_text_and_not_a_typo(client_replay):
    """result.js 의 zoneCount() 가 만드는 글("N곳", "지금 가실 곳은 N곳이에요")이 서버가 그리는 글과 같다('곧' 오타 방지). 스크립트가 만드는 다른 화면 글에도 '곧'이 없다."""
    from pathlib import Path

    from .test_result_list import soup
    static = Path(__file__).resolve().parents[2] / "app/ui/static"
    js = (static / "result.js").read_text(encoding="utf-8")
    fn = js[js.index("function zoneCount"):js.index("function matchFill")]
    assert 't.textContent = " " + n + "곳"' in fn and '"지금 가실 곳은 " + n + "곳이에요"' in fn and '"곧"' not in fn
    s = soup(run_demo(client_replay, "P1").text)
    n = len(s.select("#now article.bx"))
    assert n == 2 and s.select_one("#now .zn-n").get_text() == " 2곳"                       # 서버: 같은 글(앞 공백까지)
    assert s.select_one(".rb-n").get_text(strip=True) == "지금 가실 곳은 2곳이에요"
    for f in static.glob("*.js"):                                                          # 스크립트가 만드는 글 어디에도 숫자 바로 뒤 "곧"(곳 오타)이 없다
        assert not re.search(r"\+\s*\"[^\"]*곧\"", f.read_text(encoding="utf-8")), f.name
