"""앞으로 신청할 것은 넉 달 안의 것만 표에 싣는다(사장 결정 2026-11-18). 기준 상수 LATER_SHOW_MONTHS 하나로 정해지고,
먼 줄은 이름 없이 한 줄("그 뒤에도 N가지가 더 있어요 · 내년 5월부터 신청해요")로 알리며 직원용 창에 목록으로 남는다. 때 모르는 줄은 줄이지 않는다."""
import re
from datetime import date

import pytest

import app.ui.result_view as rv
from app.core.sheet import EmptyFront
from app.ui.result_view import build_view, empty_later_rows, far_summary, is_far, later_show_days, month_gap

from .test_replay import run_demo
from .test_result_list import soup
from .test_result_rows import later_of
from .test_result_simplify import NAMES, papers  # noqa: F401

DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")


def squash(t: str) -> str:
    return re.sub(r"\s+", "", t)


# ---------------- 기준 ----------------
def test_the_limit_is_one_constant_and_the_boundary_is_inclusive():
    assert rv.LATER_SHOW_MONTHS == 4 and later_show_days() == 120
    assert not is_far(120) and is_far(150) and not is_far(0) and not is_far(None)       # gap 이 딱 120 이면 보임, 150 이면 먼 줄, 때를 모르면 먼 줄이 아니다


def test_changing_the_constant_changes_the_limit(monkeypatch):
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 2)
    assert later_show_days() == 60 and not is_far(60) and is_far(90)
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 13)
    assert not is_far(360) and not is_far(LATER_FAR_ROW_GAP)


LATER_FAR_ROW_GAP = rv.LATER_GAP_MIN


def test_no_other_place_spells_the_limit_in_months_or_days():
    import inspect
    src = inspect.getsource(rv)
    assert len(re.findall(r"\b120\b", src)) == 0                                   # 4달 = 120일 은 어디에도 따로 적지 않는다


@pytest.mark.parametrize("asof,when,gap", [(date(2026, 11, 13), "내년 3월쯤", 120), (date(2026, 11, 13), "내년 4월쯤", 150), (date(2026, 12, 13), "내년 4월쯤", 120),
                                           (date(2026, 12, 13), "내년 1월쯤", 30), (date(2026, 10, 13), "내년 2월쯤", 120), (date(2026, 10, 13), "내년 3월쯤", 150),
                                           (date(2026, 11, 13), "내년 11월쯤", 360)])
def test_month_gap_crosses_the_new_year(asof, when, gap):
    assert month_gap(when, asof) == gap and month_gap("때는 창구에 물어보세요", asof) is None


def test_far_summary_text_and_month_name():
    far = lambda *ws: [{"when": w, "counted": True} for w in ws]       # noqa: E731
    assert far_summary([]) is None
    s = far_summary(far("내년 5월쯤", "내년 7월 1일부터"))
    assert s["n"] == 2 and s["from"] == "내년 5월" and s["text"] == "그 뒤에도 2가지가 더 있어요 · 내년 5월부터 신청해요"
    assert s["paper_text"] == "그 뒤에도 2가지가 더 있어요 · 내년 5월부터 신청해요 · 문자 알림을 받으시면 그 달에 알려 드려요"
    assert far_summary(far("내년 8~10월에 가입해요"))["from"] == "내년 8월"          # 미리 보기는 10월로 잘못 나왔다
    assert far_summary(far("내년 4월 27일부터"))["from"] == "내년 4월"
    s = far_summary(far("올해 12월쯤"))
    assert s["from"] == "올해 12월"
    none = far_summary(far("때를 알 수 없어요"))
    assert none["from"] == "" and none["text"] == none["paper_text"] == "그 뒤에도 1가지가 더 있어요"      # 달을 못 뽑으면 한 줄까지만
    assert "지원 이름" not in s["text"]


# ---------------- 다섯 농가 ----------------
SHOWN = {"P1": ["내년 2월쯤", "내년 3월쯤"], "P2": ["내년 1월쯤", "내년 3월쯤"], "P3": ["내년 1월쯤", "내년 3월쯤"], "P4": [], "P5": ["내년 1월쯤", "내년 3월쯤", "때는 창구에 물어보세요"]}
FAR = {"P1": (1, "내년 4월"), "P2": (3, "내년 5월"), "P3": (2, "내년 5월"), "P4": (1, "내년 8월"), "P5": (2, "내년 5월")}


@pytest.mark.parametrize("pid", DEMO_IDS)
def test_demo_farms_show_only_the_near_months_then_one_quiet_line(client_replay, pid):
    html = run_demo(client_replay, pid).text
    s = soup(html)
    assert [t.get_text(strip=True) for t in s.select("#later .lt-when")] == SHOWN[pid]
    n, frm = FAR[pid]
    more = s.select_one("#later .lt-more")
    assert more and more.get_text(" ", strip=True).replace(" 가지", "가지").replace("가지 가", "가지가") == f"그 뒤에도 {n}가지가 더 있어요 · {frm}부터 신청해요"
    assert more.find_next_sibling("p", class_="lt-remind") is not None             # 바로 아래에 문자 알림 줄
    assert "뒷면" not in html and "양면" not in html


def test_p4_has_only_far_lines_so_the_zone_stays_with_the_one_line_and_no_zero_count(client_replay):
    s = soup(run_demo(client_replay, "P4").text)
    sec = s.select_one("#later")
    assert sec is not None and not sec.select(".lt-g") and sec.select_one(".lt-more") and sec.select_one(".lt-remind")
    head = sec.select_one(".zn-h").get_text(strip=True)
    assert head == "앞으로 신청할 것" and "0가지" not in sec.get_text()


def test_unknown_time_group_is_kept(client_replay):
    s = soup(run_demo(client_replay, "P5").text)
    assert "때는 창구에 물어보세요" in [t.get_text(strip=True) for t in s.select("#later .lt-when")]


def test_header_count_is_the_number_of_shown_rows(client_replay):
    for pid in ("P1", "P2", "P3", "P5"):
        s = soup(run_demo(client_replay, pid).text)
        assert s.select_one("#later .lt-n").get_text(strip=True) == f"{len(s.select('#later .lt-r'))}가지", pid


def test_constant_change_follows_to_the_screen(client_replay, monkeypatch):
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 13)
    s = soup(run_demo(client_replay, "P2").text)
    assert not s.select("#later .lt-more") and len(s.select("#later .lt-r")) == 9 and not s.select(".staff-far")      # 줄인 것이 없으면 한 줄도 직원용 목록도 없다
    monkeypatch.setattr(rv, "LATER_SHOW_MONTHS", 2)
    s = soup(run_demo(client_replay, "P2").text)
    assert [t.get_text(strip=True) for t in s.select("#later .lt-when")] == ["내년 1월쯤"] and s.select_one("#later .lt-more")["data-far"] == "5"


def test_staff_window_lists_every_far_line_with_when_name_and_place(client_replay):
    for pid in DEMO_IDS:
        s = soup(run_demo(client_replay, pid).text)
        staff = s.select_one("details.staff")
        assert staff.select_one(".staff-h") and "그 뒤에 신청할 것 (표에는 줄였어요)" in staff.get_text()
        items = [" ".join(li.get_text(" ", strip=True).split()) for li in staff.select(".staff-far li")]
        assert len(items) == FAR[pid][0] and all(" · " in i for i in items), pid
    s = soup(run_demo(client_replay, "P2").text)
    got = " | ".join(" ".join(li.get_text(" ", strip=True).split()) for li in s.select(".staff-far li"))
    for want in ("토양생태환경보전(월동채소 면적조절)", "당근 농작물보험", "제주형 가격안정관리제(당근)", "내년 7월 1일부터 가입할 수 있어요", "농협"):
        assert want in got


def test_staff_window_ends_with_data_dates_and_the_calc_fingerprint(client_replay):
    s = soup(run_demo(client_replay, "P1").text)
    b = s.select_one("details.staff .staff-basis")
    assert b and b.find_next_siblings() == []                                      # 창 맨 아래
    t = b.get_text(" ", strip=True)
    assert t.startswith("데이터 기준일 지원 표 확인 ") and "가격 " in t and "감귤 가격 " in t and "저장본 " in t and re.search(r"계산 지문 [0-9a-f]{8}$", t)


def test_reminder_button_is_still_there_when_everything_was_cut(client_replay):
    s = soup(run_demo(client_replay, "P4").text)
    assert s.select_one("#later .lt-remind [data-rm-open]") and "신청하는 달에 문자로 알려 드려요" in s.select_one("#later .lt-remind").get_text()


def test_speech_reads_the_same_far_line_as_the_screen(client_replay):
    for pid in DEMO_IDS:
        s = soup(run_demo(client_replay, pid).text)
        speak = s.select_one(".btn-speak[data-speak]")["data-speak"]
        n, frm = FAR[pid]
        assert f"그 뒤에도 {n}가지가 더 있어요, {frm}부터 신청해요." in speak and speak.index("앞으로 신청할 것이에요") < speak.index("그 뒤에도"), pid
        for g in SHOWN[pid]:
            if g != "때는 창구에 물어보세요":
                assert g in speak


def test_know_box_has_no_check_line_and_keeps_the_prior_year_line(client_replay):
    for pid in DEMO_IDS:
        s = soup(run_demo(client_replay, pid).text)
        items = [li.get_text(" ", strip=True) for li in s.select(".know-list li")]
        assert items[0].startswith("가실 때") and items[-1] == "금액은 올해 기준이에요. 내년 공고가 나오면 달라질 수 있어요.", pid
        assert not [i for i in items if i.startswith("조건은")] and len(items) >= 2, pid
    assert [li.get_text(" ", strip=True)[:6] for li in soup(run_demo(client_replay, "P3").text).select(".know-list li")] == ["가실 때: ", "끊기지 않게", "끊기지 않게", "금액은 올해"]


def test_first_and_question_screens_say_nothing_about_a_back_side(client_replay):
    for path in ("/", "/counsel/input"):
        r = client_replay.get(path)
        assert r.status_code == 200 and "뒷면" not in r.text and "양면" not in r.text, path


# ---------------- 쪼갠 값(종이가 쓰는 값) ----------------
@pytest.mark.parametrize("name", NAMES)
def test_split_screen_values_stay_in_the_same_order_and_cover_every_line(papers, name):
    from app.catalog.texts import window_of  # noqa: F401
    from app.core.sheet_cards import build_cards
    from app.ui.result_view import SCREEN_MAX_CARDS, SCREEN_MAX_LINES, order_boxes, split_screen, unlock_names
    fs, sheet, bundle, as_of = papers[name]
    if isinstance(sheet.front, EmptyFront):
        pytest.skip("빈 종이는 따로(test_empty_front_far_lines)")
    prog_of = {p.id: p for p in bundle.programs}
    cs = build_cards(sheet, fs, None, max_cards=SCREEN_MAX_CARDS, max_lines=SCREEN_MAX_LINES)
    cs, _ = order_boxes(cs, prog_of, as_of)
    sp = split_screen(cs, prog_of, as_of, lambda cl: None, unlock_names(cs, fs))
    assert [cl.title for _, cl in sp["later_src"]] == [r["title"] for r in sp["later_rows"]]            # later_src 는 later_rows 와 같은 차례(먼 줄은 빠진 채로)
    assert [cl.title for _, cl in sp["far_src"]] == [r["title"] for r in sp["far_rows"]]
    assert sum(len(g["rows"]) for g in sp["later_groups"]) == len(sp["later_rows"])
    assert (sp["later_far"] or {"n": 0})["n"] == len(sp["far_rows"])
    assert all(r["known"] for r in sp["far_rows"])
    last = sp["ask_groups"][-1]
    assert last[0] == "" and len(last[1]) == len(sp["later_rows"]) + len(sp["far_rows"])                 # 같이 확인해요 표는 먼 줄까지 전부


def test_year_turn_months_count_across_december(papers, monkeypatch):
    """기준일이 12월이면 내년 1~4월이 넉 달 안(30~120일), 10월이면 2월까지가 안이다(달 차이는 해를 넘겨 센다)."""
    fs, sheet, bundle, _ = papers["demo_P2"]
    dec = build_view(sheet, fs, bundle, date(2026, 12, 13), screen=True)
    for r in dec["later_rows"]:
        if r["known"] and (g := month_gap(r["when"], date(2026, 12, 13))) is not None:
            assert g <= 120, r
    for r in dec["far_rows"]:
        assert (g := month_gap(r["when"], date(2026, 12, 13))) is None or g > 120, r
    octo = build_view(sheet, fs, bundle, date(2026, 10, 13), screen=True)
    for r in octo["later_rows"]:
        if r["known"] and (g := month_gap(r["when"], date(2026, 10, 13))) is not None:
            assert g <= 120, r
    for r in octo["far_rows"]:
        assert (g := month_gap(r["when"], date(2026, 10, 13))) is None or g > 120, r


@pytest.mark.parametrize("name", NAMES)
def test_empty_front_far_lines(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    if not isinstance(sheet.front, EmptyFront):
        pytest.skip("결과가 있는 종이")
    v = build_view(sheet, fs, bundle, as_of, screen=True)
    allr = empty_later_rows(sheet.front)
    assert sorted(r["title"] for r in v["later_rows"] + v["far_rows"]) == sorted(r["title"] for r in allr)
    assert len(v["later_rows"]) + len(v["far_rows"]) == len(allr)
    assert (v["later_far"] or {"n": 0})["n"] == len(v["far_rows"]) == len(v["detail"]["far"])
    for r in v["far_rows"]:
        assert is_far(month_gap(r["when"], as_of))
    for r in v["later_rows"]:
        assert not r["known"] or not is_far(month_gap(r["when"], as_of))
