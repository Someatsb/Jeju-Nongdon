"""결과 화면과 종이의 "새로 나온 공고" 묶음(설계 result-v2 10절, AI가 읽은 공고 맞춰 보기 에이전트의 결과를 그린다).

실제 AI·인터넷은 쓰지 않는다. 맞춰 보기 보고서를 손으로 만들어 matcher 자리에 끼운다(공고는 tests/fixtures/catalog_notices/match 의 고정본).
- 어르신 화면: 맞을 수 있음 3건까지 줄, 그 밖은 이름만 한 줄, 안 맞음은 어디에도 없음, 공고 글의 꺾쇠는 글자로.
- 직원 칸·공고 원문 상자·지원 안내에서 결과로 돌아가기·종이(앞면 한 면).
"""
import re
import threading
import time

import pytest
from bs4 import BeautifulSoup
from match_fixtures import BIRTH, FTA, LOAN, NOTICES, ORG_FERT, ORG_MAT

from app.agents.match import MatchCheck, MatchItem, MatchReport
from app.ui import routes_counsel
from app.ui.preflight import preflight
from app.ui.session import COOKIE

from .conftest import P4_FORM
from .test_match_async import CITRUS_FORM, SHOW_TODAY, answer, app_client, catalog_dir, start  # noqa: F401

DEADLINE_S = 5.0
FIT_, UNK_, NOT_ = "맞을 수 있음", "알 수 없음", "안 맞음"
NOTE = "조건은 창구에서 확인하세요"
AI_LINE = "조건은 창구에서 확인하세요"
AI_TAG = "AI가 읽은 공고"
HEAD_LINE = "지금 접수 중인 공고 가운데 맞을 수 있는 것"


def item(key, verdict, why="", ask=(), checks=()):
    return MatchItem(key=key, name=NOTICES[key].name, verdict=verdict, why=why or f"{NOTICES[key].name[:8]} 조건에 맞아요",
                     ask=tuple(ask), period=NOTICES[key].apply_period, checks=tuple(MatchCheck(kind=k, quote=q, answer=a) for k, q, a in checks))


def report(*items, source="ai"):
    return MatchReport(items=tuple(items), source=source, candidates=len(items), note="확인 3번")


FTA_CHECKS = (("작물", "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업", "예"),)
BASIC = report(item(FTA, FIT_, "감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요", ("농협에서 받는지", "조합원이어야 하는지"), FTA_CHECKS),
               item(ORG_MAT, UNK_), item(LOAN, UNK_),
               item(BIRTH, NOT_, "여성농업인이 신청하는 사업이 아니에요", (), (("성별", "가. 대상: 출산 예정인 여성 농업인", "아니오"),)))


def boot(app_client, rep, *, gate=None):
    """맞춰 보기 보고서를 정해 둔 서버. gate 가 있으면 풀릴 때까지 맞춰 보기가 돈다."""
    from .test_match_async import MatchLLM
    client = app_client(MatchLLM())

    def matcher(profile, fs, notices):
        if gate is not None:
            gate.wait(10)
        return rep(notices) if callable(rep) else rep
    client.app.state.matcher = matcher
    return client


def go(client, form=CITRUS_FORM, until=("done", "none")):
    answer(client, form)
    client.get("/counsel/preview")
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end:
        j = client.get("/counsel/ai").json()
        if j["match"]["state"] in until:
            return j
        time.sleep(0.02)
    raise AssertionError("맞춰 보기가 끝나지 않음")


def page(client) -> BeautifulSoup:
    r = client.get("/counsel/preview")
    assert r.status_code == 200
    return BeautifulSoup(r.text, "html.parser")


def text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).replace(" · ", " · ")


# ---------------- 화면: 묶음 상자 ----------------
def test_box_with_one_fit_and_two_more(app_client):
    """어르신 화면(2026-11-15 4차): "지금 접수 중인 공고" 상자 = 가실 곳 상자와 같은 모양. 그 밖의 새 공고 이름 나열은 없다(직원이 볼 내용에만)."""
    client = boot(app_client, BASIC)
    go(client)
    s = page(client)
    box = s.select_one('[data-ai-slot="new_notices"]')
    assert box is not None and not box.select(".nn-h") and HEAD_LINE not in text(box)       # 따로 뜬 제목은 없다(꼬리표가 그 뜻이다)
    boxes = box.select("article.bx")
    assert len(boxes) == 1 and boxes[0].get("id") == "new-notices"                       # 첫 묶음이 "아래를 보세요"의 도착 자리
    b = boxes[0]
    assert text(b.select_one(".bx-name .nn-tag")) == AI_TAG                              # 소분류 칸의 작은 꼬리표
    assert not b.select_one(".bx-no")                                                  # 번호는 없다
    assert text(b.select_one(".bx-t")) == "지역 농·감협"                       # 띠: 가실 곳(접수처) 이름만("에 가세요"는 붙이지 않는다)
    r = b.select_one("li.nn-row")
    pill = r.select_one(".bxr-d .left-pill")
    assert text(pill) == "9일 남음" and "is-urgent" not in pill["class"]      # 설명 칸의 빨간 남은 날 알약(7일 안이면 빨강 바탕)
    assert text(r.select_one(".nn-name")) == NOTICES[FTA].name
    assert text(r.select_one(".nn-why")) == "감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요"
    assert text(r.select_one(".bxr-when")) == "11월 23일까지"                         # 달력 + 날짜(남은 날은 띠 딱지에)
    assert not r.select(".nn-where")                                                   # 가실 곳은 띠로 올라갔다
    asks = [text(li) for li in r.select(".nn-ask li")]
    assert asks == ["농협에서 받는지 · 창구에 물어보세요", "조합원이어야 하는지 · 창구에 물어보세요"]
    assert text(r.select_one(".nn-ai")) == AI_LINE
    go_btn = r.select_one("a.nn-go")
    assert text(go_btn) == "공고 자세히 보기" and go_btn["href"] == f"/supports/{FTA}?from=result"
    assert [x["class"][0] for x in r.find_all(recursive=False)] == ["bxr-top", "bxr-d"] and r.select_one(".bxr-top .nn-name")      # 이름 칸 | 설명 칸
    kids = [next(c for c in x["class"] if c in ("bxr-when", "bxr-left", "nn-why", "nn-ask", "nn-ai", "nn-go")) for x in r.select_one(".bxr-d").find_all(recursive=False)]
    assert kids == ["bxr-when", "bxr-left", "nn-why", "nn-ask", "nn-ai", "nn-go"]       # 설명 칸: 언제·남은 날 → 왜 → 물어볼 것 → 작은 글 → 단추
    assert not box.select(".nn-more") and "그 밖의 새 공고" not in text(box) and "새로 나온 공고" not in text(s.select_one("#cards").parent)
    assert s.select_one("a.nn-alert") is not None
    assert text(s.select_one("a.nn-alert")) == "마감이 가까운 공고 1개가 맞을 수 있어요 · 아래를 보세요"
    assert s.select_one("a.nn-alert")["href"] == "#new-notices"


def test_box_sits_below_boxes_and_above_know_box(app_client):
    client = boot(app_client, BASIC)
    go(client)
    html = client.get("/counsel/preview").text
    i_rows, i_know, i_new = html.find('class="rbx"'), html.find('class="know"'), html.find('id="new-notices"')
    assert 0 < i_rows < i_new < i_know < html.find('class="rbar"')                    # 번호 상자들 아래, 알아 두세요 위


def test_four_fits_show_three_boxes_and_no_name_list(app_client):
    rep = report(item(FTA, FIT_), item(ORG_MAT, FIT_), item(ORG_FERT, FIT_), item(LOAN, FIT_))
    client = boot(app_client, rep)
    go(client)
    box = page(client).select_one('[data-ai-slot="new_notices"]')
    assert len(box.select("article.bx")) == 3 and not box.select(".nn-more")
    assert "마감이 가까운 공고 3개가 맞을 수 있어요" in text(page(client).select_one("a.nn-alert"))


def test_only_unknown_items_show_nothing_on_the_elder_screen(app_client):
    client = boot(app_client, report(item(ORG_MAT, UNK_), item(LOAN, UNK_)))
    go(client)
    s = page(client)
    assert s.select_one("#new-notices") is None                      # 맞을 수 있는 것이 없으면 그 자리는 사라진다(이름 나열도 없다)
    assert s.select_one("a.nn-alert") is None
    assert s.select_one('[data-ai-slot="new_notices"]').has_attr("hidden")


def test_done_but_empty_shows_no_box(app_client):
    client = boot(app_client, report(item(BIRTH, NOT_, "아니에요", (), (("성별", "가. 대상: 출산 예정인 여성 농업인", "아니오"),))))
    j = go(client)
    s = page(client)
    assert j["match"]["state"] == "done" and j["match"]["lines"] == [] and j["match"]["more_names"] == []
    assert s.select_one("#new-notices") is None and s.select_one(".nn-run") is None and s.select_one("a.nn-alert") is None
    assert j["match_html"]["new_notices"] == "" and j["match_html"]["match_alert"] == ""


def test_none_shows_nothing(app_client):
    client = boot(app_client, report(source="none"))
    j = go(client)
    s = page(client)
    assert j["match"]["state"] == "none"
    assert s.select_one("#new-notices") is None and s.select_one(".nn-run") is None and s.select_one("a.nn-alert") is None
    assert j["match_html"] == {"new_notices": "", "match_alert": "", "match_links": ""}


def test_run_shows_a_small_waiting_line_with_reserved_slot(app_client):
    gate = threading.Event()
    client = boot(app_client, BASIC, gate=gate)
    try:
        answer(client, CITRUS_FORM)
        s = BeautifulSoup(client.get("/counsel/preview").text, "html.parser")
        slot = s.select_one('[data-ai-slot="new_notices"]')
        run = slot.select_one(".nn-run")
        assert text(run) == "지금 접수 중인 공고도 찾아보고 있어요…" and run["aria-live"] == "polite"
        assert s.select_one("#ai-state")["data-match"] == "run" and s.select_one("#new-notices") is None
        j = client.get("/counsel/ai").json()
        assert j["match"]["state"] == "run" and j["match_html"] == {}
    finally:
        gate.set()
    j = client.get("/counsel/ai").json()
    end = time.monotonic() + DEADLINE_S
    while j["match"]["state"] == "run" and time.monotonic() < end:
        time.sleep(0.02)
        j = client.get("/counsel/ai").json()
    html = j["match_html"]
    assert 'id="new-notices"' in html["new_notices"] and "nn-alert" in html["match_alert"] and NOTICES[FTA].name in html["match_links"]
    assert page(client).select_one("#ai-state")["data-match"] == "done"


# ---------------- 안 맞음은 어르신 화면·응답 어디에도 없다 ----------------
def test_not_fit_name_is_nowhere_on_the_elder_screen_or_response(app_client):
    client = boot(app_client, BASIC)
    j = go(client)
    name = NOTICES[BIRTH].name
    assert name not in str(j)                                    # /counsel/ai 응답 전체(match·match_html·fragments)
    s = page(client)
    s.select_one("details.staff").decompose()                    # 직원이 볼 내용 칸은 직원 몫
    assert name not in str(s)


# ---------------- 공고 글(외부 글)은 글자로 보인다 ----------------
def test_angle_brackets_in_notice_text_stay_text(app_client):
    evil = MatchItem(key=FTA, name="<img src=x onerror=alert(1)>감귤 공고", verdict=FIT_, why="<script>alert(2)</script>맞을 수 있어요",
                     ask=("<b>농협</b>에 물어요",), period="가. 기간", checks=(MatchCheck(kind="작물", quote="<i>인용</i>", answer="예"),))
    client = boot(app_client, report(evil))
    j = go(client)
    html = client.get("/counsel/preview").text
    for raw in ("<img src=x", "<script>alert(2)", "<b>농협</b>", "<i>인용</i>"):
        assert raw not in html and raw not in j["match_html"]["new_notices"] and raw not in j["match_html"]["match_links"]
    s = BeautifulSoup(html, "html.parser")
    assert "<img src=x onerror=alert(1)>감귤 공고" in text(s.select_one("#new-notices .nn-name"))      # 글자로 보인다
    assert s.select_one("#new-notices img") is None and s.select_one("#new-notices .nn-ask b") is None
    staff = client.get("/counsel/match-staff").json()["html"]
    assert "<i>인용</i>" not in staff and "&lt;i&gt;인용&lt;/i&gt;" in staff


# ---------------- 직원이 볼 내용 ----------------
def test_staff_panel_has_verdict_names_and_check_records(app_client):
    client = boot(app_client, BASIC)
    go(client)
    r = client.get("/counsel/match-staff")
    assert r.headers["cache-control"] == "no-store" and r.json()["state"] == "done"
    s = BeautifulSoup(r.json()["html"], "html.parser")
    t = text(s)
    assert "AI가 읽은 공고 맞춰 보기" in t
    assert "맞을 수 있음 1건" in t and "알 수 없음 2건" in t and "안 맞음 1건" in t
    for key in (FTA, ORG_MAT, LOAN, BIRTH):
        assert NOTICES[key].name in t
    assert "작물" in t and "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업" in t and "예" in t
    assert "성별" in t and "아니오" in t
    # 화면을 다시 열면 직원 칸 안에 처음부터 있다
    d = page(client).select_one("details.staff")
    assert "안 맞음 1건" in text(d) and d.select_one("#match-staff") is not None


def test_staff_panel_while_running_and_without_session(app_client):
    gate = threading.Event()
    client = boot(app_client, BASIC, gate=gate)
    try:
        answer(client, CITRUS_FORM)
        client.get("/counsel/preview")
        j = client.get("/counsel/match-staff").json()
        assert j["state"] == "run" and j["html"] == ""
    finally:
        gate.set()
    client.cookies.clear()
    assert client.get("/counsel/match-staff").status_code == 409


# ---------------- 자세히 보기: 공고 원문 상자 ----------------
def test_detail_source_box_has_the_new_notice_with_buttons(app_client):
    client = boot(app_client, BASIC)
    go(client)
    s = page(client)
    lis = [li for li in s.select("#detail .lk-box li.lk") if FTA in li["data-keys"].split()]
    assert len(lis) == 1
    li = lis[0]
    assert NOTICES[FTA].name in text(li.select_one(".lk-name"))
    assert li.select_one("a.lk-open")["href"] == NOTICES[FTA].url == li.select_one("button.lk-copy")["data-copy-url"]
    assert text(li.select_one("a.lk-open")) == "공고문 보기" and text(li.select_one("button.lk-copy")) == "링크 복사하기"
    assert not [x for x in s.select("#detail .lk-box li.lk") if LOAN in x["data-keys"]]         # 맞을 수 있는 것만


def test_detail_source_box_skips_notice_without_url(app_client, catalog_dir):
    import json
    f = catalog_dir / "notices" / "fta_citrus.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["url"] = None
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    client = boot(app_client, BASIC)
    go(client)
    assert not [li for li in page(client).select("#detail .lk-box li.lk") if FTA in li["data-keys"].split()]


# ---------------- 공고 안내 보기 → 지원 안내 → 결과로 돌아가기 ----------------
def test_support_page_from_result_returns_to_the_same_result(app_client):
    client = boot(app_client, BASIC)
    go(client)
    before = page(client)
    href = before.select_one("a.nn-go")["href"]
    r = client.get(href)
    assert r.status_code == 200
    s = BeautifulSoup(r.text, "html.parser")
    back = s.select_one("a.btn-prev")
    assert text(back) == "결과로 돌아가기" and back["href"] == "/counsel/preview#new-notices" and "목록으로" not in r.text
    again = client.get("/counsel/preview")                       # 돌아간 결과 화면: 상담이 그대로
    assert again.status_code == 200
    a = BeautifulSoup(again.text, "html.parser")
    assert text(a.select_one(".rb-h")) == text(before.select_one(".rb-h")) and text(a.select_one(".rb-who")) == text(before.select_one(".rb-who"))
    assert a.select_one("#new-notices") is not None and client.get("/counsel/input?edit=1").text.count("애월") >= 1


def test_support_page_without_mark_keeps_list_back_link(app_client):
    client = boot(app_client, BASIC)
    plain = BeautifulSoup(client.get(f"/supports/{FTA}").text, "html.parser").select_one("a.btn-prev")
    assert text(plain) == "목록으로" and plain["href"] == "/supports"
    other = BeautifulSoup(client.get(f"/supports/{FTA}?from=elsewhere").text, "html.parser").select_one("a.btn-prev")
    assert text(other) == "목록으로" and other["href"] == "/supports"


# ---------------- 종이 ----------------
def paper_of(client) -> str:
    r = client.get("/counsel/print")
    assert r.status_code == 200 and "인쇄 보류" not in r.text, r.text[:300]
    return r.text


def plain(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text("")).strip()


def test_paper_has_the_notice_line_in_the_now_zone_and_no_back_group(app_client):
    client = boot(app_client, BASIC)
    go(client)
    html = paper_of(client)
    soup = BeautifulSoup(html, "html.parser")
    now_zone = plain(soup.select_one(".pz-now").decode())
    assert NOTICES[FTA].name in now_zone and "11월 23일까지" in now_zone          # 「지금 하실 일」 구역에 공고 이름 · 마감 날짜(화면과 같은 글)
    assert "조건은 창구에서 확인하세요" in now_zone and "지역 농·감협" in now_zone
    assert not soup.select(".back, .bk-new, .know") and "뒷면" not in html and "지금 접수 중인 공고 1개가" not in plain(html)
    assert "그 밖의 새 공고" not in plain(html) and "새로 나온 공고" not in plain(html)      # 이름 나열 줄은 종이에 없다(직원이 볼 내용 칸에만)
    assert NOTICES[BIRTH].name not in plain(html)               # 안 맞음 이름은 종이에도 없다
    state = client.app.state
    job = state.sessions.get(client.cookies[COOKIE])["job"]
    assert preflight(html, job.fs, state.cfg) == []


def test_paper_notice_line_is_always_in_the_now_zone():
    """공고 줄은 자리가 남을 때만이 아니라 언제나 「지금 하실 일」 구역에 있다(자리는 글자 단계·쪽 넘김이 맞춘다)."""
    from .test_new_notices import _paper_with
    html, over = _paper_with({"lines": [_line(0, 20, 10, 10)], "more_names": []})
    assert not over
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select(".pz-now .rnt")) == 1 and not soup.select(".know")


def test_paper_without_match_is_the_same_as_before(app_client):
    """맞춰 보기가 없거나 결과가 없으면(none, 0건, 맞춰 볼 것이 없음) 종이는 글자 하나 다르지 않다."""
    from .test_match_async import MatchLLM
    base = app_client(MatchLLM())
    base.app.state.matcher = None
    answer(base, CITRUS_FORM)
    plain_paper = base.get("/counsel/print").text
    for rep in (report(source="none"), report(), report(item(BIRTH, NOT_, "아니에요"))):
        c = boot(app_client, rep)
        go(c)
        assert c.get("/counsel/print").text == plain_paper


def test_paper_overflow_three_long_notices(app_client):
    """아주 긴 공고 셋이어도 종이가 막히지 않는다: 한 쪽(또는 이어진 쪽)에 다 싣거나, 검사에 걸리면 그 줄들 없이 뽑는다(새 공고 때문에 종이가 막히면 안 된다)."""
    long = "가" * 60
    items = [MatchItem(key=k, name=NOTICES[k].name + " " + "공고이름" * 8, verdict=FIT_, why=long + " 조건에 맞아요", ask=(long, long),
                       period=NOTICES[k].apply_period) for k in (FTA, ORG_MAT, ORG_FERT)]
    client = boot(app_client, report(*items, item(LOAN, UNK_), item(BIRTH, UNK_)))
    go(client)
    html = paper_of(client)                                      # 인쇄 보류(넘침)가 아니다
    state = client.app.state
    job = state.sessions.get(client.cookies[COOKIE])["job"]
    assert preflight(html, job.fs, state.cfg) == []
    rows = BeautifulSoup(html, "html.parser").select(".pz-now .rnt")
    assert len(rows) in (0, 3)                                   # 셋 다 있거나(검사 통과) 하나도 없다(묶음 없이 뽑음)
    if rows:
        t = plain(" ".join(r.decode() for r in rows))
        for k in (FTA, ORG_MAT, ORG_FERT):                       # 이름·기간은 줄여도 남는다
            assert NOTICES[k].name in t
        assert t.count("11월 23일까지") >= 1


def test_print_waits_for_running_match_within_the_budget(app_client, monkeypatch):
    monkeypatch.setattr(routes_counsel, "PRINT_BUDGET_S", 3.0)
    gate = threading.Event()
    client = boot(app_client, BASIC, gate=gate)
    answer(client, CITRUS_FORM)
    client.get("/counsel/preview")
    threading.Timer(0.4, gate.set).start()
    t0 = time.monotonic()
    html = paper_of(client)
    assert time.monotonic() - t0 < 3.0 and 'class="pg rnt' in html


def test_print_gives_up_waiting_and_prints_without_the_group(app_client, monkeypatch):
    monkeypatch.setattr(routes_counsel, "PRINT_BUDGET_S", 0.4)
    gate = threading.Event()
    client = boot(app_client, BASIC, gate=gate)
    try:
        answer(client, CITRUS_FORM)
        client.get("/counsel/preview")
        t0 = time.monotonic()
        html = paper_of(client)
        assert time.monotonic() - t0 < 2.0 and 'class="pg rnt' not in html and "새로 나온 공고" not in html
    finally:
        gate.set()


# ---------------- 화면 글자·자리 규칙(CSS) ----------------
def test_css_sizes_and_colors():
    from .test_result_list import RESULT_CSS, css_rules
    rules = css_rules(RESULT_CSS)

    def decl(sel):
        return " ".join(body for cond, s, body in rules if cond is None and s.strip() == sel)

    def px(sel, prop):
        m = re.search(rf"(?:^|[;\s]){prop}:\s*(\d+)px", decl(sel))
        return int(m[1]) if m else None
    assert px(".nn-tag", "font-size") >= 20 and px(".nn-ai", "font-size") >= 20
    assert px(".nn-name", "font-size") >= 24 and px(".nn-why", "font-size") == 22 and px(".bxr-when", "font-size") == 22
    assert px(".nn-where", "font-size") == 22 and px(".nn-ask", "font-size") >= 20
    assert px(".nn-go", "min-height") >= 56
    assert px(".nn-alert", "font-size") >= 20 and px(".nn-run", "min-height") >= 56
    assert "var(--tang" not in "".join(body for _, s, body in rules if s.strip().startswith((".nn", ".ms")))


# ---------------- 종이 공고 줄: 아주 긴 글은 줄임표로 자른다(전문은 화면에 있다) ----------------
def _paper_with(match, crop=None, kwargs=None):
    from conftest import P4_KWARGS

    from app.config import load_config
    from app.core.models import FarmProfile
    from app.core.pipeline import build_fact_sheet
    from app.core.sheet import build_sheet
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    from app.ui.render import check_overflow, render_sheet
    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    fs = build_fact_sheet(FarmProfile(**(kwargs or P4_KWARGS)), bundle, snap, cfg.as_of, "test", demo_asof=True)
    sheet = build_sheet(fs, bundle, cfg.as_of)
    html = render_sheet(sheet, fs, None, cfg, crop_labels={c.crop_code: c.label for c in bundle.crops}, match=match)
    return html, check_overflow(html)


def _line(n, why_len, ask_len, where_len):
    return {"key": f"k{n}", "name": f"새 공고 {n} " + "이름" * 6, "why": "왜" * why_len, "period": "11월 23일까지 · 10일 남음",
            "where": "접수처: " + "곳" * where_len, "ask": ["묻" * ask_len + " · 창구에서 확인", "물" * ask_len + " · 창구에서 확인"]}


def test_paper_notice_row_clips_very_long_text_and_keeps_name_and_period():
    plain_html, _ = _paper_with(None)
    assert "새로 나온 공고" not in plain_html and "rnt" not in plain_html.split("</style>")[1]
    html, over = _paper_with({"lines": [_line(0, 400, 400, 30)], "more_names": ["가", "나"]})
    assert not over
    t = plain(BeautifulSoup(html, "html.parser").select_one(".pz-now .rnt").decode())
    assert "새 공고 0 " in t and "11월 23일까지" in t and "…" in t              # 이름·기간은 남고 긴 글은 줄임표로 끝난다
    assert "그 밖의 새 공고" not in t
