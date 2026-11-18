"""지원 전체 보기(/supports)와 지원 안내(/supports/{제도}), 첫 화면 연결, 직원 메뉴 한 줄(설계서 B-5)."""
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
from bs4 import BeautifulSoup

from app.catalog import build_catalog
from app.config import APP_ROOT, today_fn
from app.core.office_say import office_say
from app.ui.routes_supports import check_say

from .conftest import _started_client

FIXTURE_NOTICES = Path(__file__).resolve().parents[1] / "fixtures" / "catalog_notices"
CODE_WORDS = re.compile(r"program_key|CHECK|None|True|False|null|undefined|\bhold\b|\bkey\b|[A-Z]{2,}-[A-Z0-9]{2,}")


def soup_of(r):
    return BeautifulSoup(r.text, "html.parser")


def main_text(r) -> str:
    return soup_of(r).select_one("main").get_text(" ", strip=True)


def catalog_of(client):
    from app.ui.routes_supports import load_catalog_for

    class Req:
        app = client.app
    return load_catalog_for(Req())


@pytest.fixture
def client_demo(tmp_path):
    """표 28가지만 있는 목록 자료 폴더로 띄운 앱. 실제 새 공고 폴더는 공고가 올라올 때마다 바뀌므로 쓰지 않는다."""
    cdir = tmp_path / "catalog-table-only"
    (cdir / "notices").mkdir(parents=True)
    shutil.copy(APP_ROOT / "data" / "catalog" / "links.csv", cdir / "links.csv")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def client_new(tmp_path):
    """새 공고 두 건(둘째는 표의 물류비 지원과 같아 카드가 안 생긴다)이 올라 있는 목록 자료 폴더로 띄운 앱."""
    cdir = tmp_path / "catalog"
    (cdir / "notices").mkdir(parents=True)
    for f in FIXTURE_NOTICES.glob("*.json"):
        shutil.copy(f, cdir / "notices" / f.name)
    shutil.copy(APP_ROOT / "data" / "catalog" / "links.csv", cdir / "links.csv")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def client_five(tmp_path, monkeypatch):
    """실제로 읽은 새 공고 다섯 건을 굳혀 둔 폴더(tests/fixtures/catalog_notices_polish)로 띄운 앱.
    실제 data/catalog/notices 는 공고를 다시 읽힐 때마다 바뀌므로 시험이 기대지 않는다."""
    from datetime import date as _date
    monkeypatch.setattr("app.config._today", lambda: _date(2026, 11, 14))
    cdir = tmp_path / "catalog-five"
    (cdir / "notices").mkdir(parents=True)
    for f in (FIXTURE_NOTICES.parent / "catalog_notices_polish").glob("*.json"):
        shutil.copy(f, cdir / "notices" / f.name)
    shutil.copy(APP_ROOT / "data" / "catalog" / "links.csv", cdir / "links.csv")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    yield c
    c.__exit__(None, None, None)


# ---------- 목록 ----------

def test_list_shows_real_counts_and_today(client_demo):
    cat = catalog_of(client_demo)
    r = client_demo.get("/supports")
    assert r.status_code == 200
    s = soup_of(r)
    today = today_fn()
    assert f"오늘은 {today.month}월 {today.day}일이에요" in s.select_one(".sp-count").text
    assert f"모두 {cat.count}가지" in s.select_one(".sp-count").text and cat.count == 28
    assert len(s.select("a.sp-card")) == cat.count
    chips = {c.select_one("small").text: c.get_text(" ", strip=True) for c in s.select("a.sp-chip")}
    assert s.select_one("a.sp-chip.is-on")["aria-current"] == "page"
    assert s.select("a.sp-chip")[0].get_text(" ", strip=True).startswith("전체 ") and chips


GROUP_TITLES = ["지금 신청할 수 있어요", "곧 열려요", "언제든 신청할 수 있어요", "올해 신청은 끝났어요", "언제 받는지는 창구에 물어보세요"]


def row_of(s, href):
    return s.select_one(f'tr.sp-row:has(a.sp-card[href="{href}"])')


def test_list_is_one_box_per_group_each_with_three_columns_and_its_own_column_head(client_demo):
    s = soup_of(client_demo.get("/supports"))
    boxes = s.select("section.sp-bx")
    assert len(boxes) == len(s.select("table.sp-tab")) == 4                       # 묶음 수만큼 상자(표 28가지: 곧 열려요는 비어 있어 없다)
    for bx in boxes:
        first = bx.find_all(recursive=False)[0]
        assert first.name == "h2" and "sp-gh" in first["class"]                    # 제목 띠가 상자의 첫 요소
        t = bx.select_one("table.sp-tab")
        assert [th.text.strip() for th in t.select("thead th[scope=col]")] == ["지원", "어디서 신청해요", "언제 신청해요"]     # 칸 머리 줄은 상자마다 되풀이
        assert t.select_one("caption").text.strip() and len(t.select("colgroup col")) == 3
        assert all(len(r.select("th[scope=row], td")) == 3 for r in t.select("tr.sp-row"))
        assert bx["aria-labelledby"] == bx.select_one("h2")["id"]
    assert sum(len(bx.select("tr.sp-row")) for bx in boxes) == 28
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8")
    assert "table-layout: fixed" in css and css.split("/* ---------- 지원 안내")[0].count("sticky") == 2   # 제목 띠와 칸 머리 줄만 붙박이


def test_every_row_is_one_link_with_who_and_period_and_no_amount(client_demo):
    from app.catalog.layout import groups_of
    cat = catalog_of(client_demo)
    s = soup_of(client_demo.get("/supports"))
    hrefs = set()
    rows = s.select("tr.sp-row")
    assert len(rows) == cat.count == len(s.select("a.sp-card"))
    for tr in rows:
        assert len(tr.select("a")) == 1                 # 줄 하나가 링크 하나(줄 안에 또 링크를 넣지 않는다)
        card = tr.select_one("a.sp-card")
        assert card["href"].startswith("/supports/") and not card.select("a")
        hrefs.add(card["href"])
        assert card.select_one(".sp-name").text.strip()
        assert not tr.select(".sp-agency, .sp-badge, .sp-tags, .sp-line, .sp-lead")     # 기관 줄·'조건을 따져 드려요'·이름표 알약·금액 줄은 목록에 없다
        assert "조건을 따져 드려요" not in tr.text
        e = cat.get(card["href"].rsplit("/", 1)[1])
        assert tr.select_one(".sp-when").text.strip()
        assert e.amount not in tr.text or e.amount in e.tags                              # 금액은 안내 화면에서 본다
    assert len(hrefs) == 28
    expected = {r.entry.href: r for g in groups_of(cat.entries, None, cat.as_of) for r in g.rows}
    for href, r in expected.items():
        tr = row_of(s, href)
        assert not tr.select(".sp-pill, .sp-pills, .sp-c-who")                           # 누가 이름표는 목록에 없다
        lines = [x.text.strip() for x in tr.select(".sp-c-where .sp-where")]
        assert lines == (list(r.where) or ["안내에서 확인"])
        assert (not r.where) == bool(tr.select(".sp-c-where .sp-nowhere"))
        assert tr.select_one(".sp-when").text.strip() == r.show_main


GROUP_ROW = "section.sp-bx"


def test_list_is_split_into_ordered_boxes_with_counts(client_demo):
    from app.catalog.layout import groups_of
    cat = catalog_of(client_demo)
    for url in ("/supports", "/supports?f=open", "/supports?f=citrus", "/supports?f=field"):
        s = soup_of(client_demo.get(url))
        heads = [(h.contents[0].strip(), h.select_one("small").text.strip()) for h in s.select("h2.sp-gh")]
        titles = [t for t, _ in heads]
        assert titles == [t for t in GROUP_TITLES if t in titles]      # 정해진 순서(걸러 보기를 눌러도 같다), 빈 묶음은 안 보인다
        shown = cat.select(url.partition("f=")[2] or "all")
        groups = groups_of(shown, "citrus" if url.endswith("citrus") else None, cat.as_of)
        assert titles == [g.title for g in groups] and [c for _, c in heads] == [f"{g.count}가지" for g in groups]
        assert len(s.select(GROUP_ROW)) == len(groups)                 # 묶음 수만큼 상자
        names = [a.select_one(".sp-name").text.strip() for a in s.select("a.sp-card")]
        assert names == [r.entry.title for g in groups for r in g.rows]          # 차례도 같다(남은 날 순)
        assert sum(len(sec.select("tr.sp-row")) for sec in s.select(GROUP_ROW)) == len(shown)        # 상자 안 줄 수의 합 = 보이는 지원 수
        for sec in s.select(GROUP_ROW):
            assert len(sec.select("a.sp-card")) == int(sec.select_one("small").text.replace("가지", ""))
            assert sec.find_all(recursive=False)[0] is sec.select_one("h2.sp-gh") and sec["aria-labelledby"] == sec.select_one("h2")["id"]
    s = soup_of(client_demo.get("/supports"))
    assert [h.contents[0].strip() for h in s.select("h2.sp-gh")] == [t for t in GROUP_TITLES if t != "곧 열려요"]       # 표 28가지에는 곧 열리는 것이 없다: 빈 묶음은 안 보인다
    open_group = s.select_one(GROUP_ROW)
    assert all(r.select_one(".sp-when") and r.select_one(".sp-c-when .left-pill") for r in open_group.select("tr.sp-row"))    # 기간 + 남은 날 표시
    assert not s.select(".sp-newnote")                  # 새 공고가 없으면 안내 한 줄도 없다


def test_open_rows_show_days_left_as_a_big_flag_and_only_those(client_demo):
    from app.catalog.layout import groups_of, split_window
    cat = catalog_of(client_demo)
    s = soup_of(client_demo.get("/supports"))
    groups = groups_of(cat.entries, None, cat.as_of)
    assert groups[0].id == "open"
    for g, sec in zip(groups, s.select(GROUP_ROW)):
        for r, tr in zip(g.rows, sec.select("tr.sp-row")):
            flags = tr.select(".sp-c-when .left-pill")
            if g.id == "open":
                assert len(flags) == 1
                assert flags[0].text.strip() == split_window(r.entry.window)[1].split(" · ")[0]     # 자료가 만든 글 그대로("8일 남음")
                assert re.fullmatch(r"(\d+일 남음|오늘 마감)", flags[0].text.strip())
                assert ("is-urgent" in flags[0]["class"]) == r.urgent
                kids = [c.get("class")[0] for c in tr.select_one(".sp-c-when").find_all(recursive=False)]
                assert kids.index("left-pill") < kids.index("sp-when")                          # 날짜 글은 남은 날 표시 뒤에 온다
                assert all(flags[0].text.strip() not in x.text for x in tr.select(".sp-c-when .sp-left"))      # 같은 말을 두 번 적지 않는다
            else:
                assert not flags and not tr.select(".left-pill")                              # 마감이 없는 줄에는 남은 날 표시가 없다
    days = [int(re.match(r"(\d+)", x.text).group(1)) for x in s.select_one(GROUP_ROW).select(".left-pill") if x.text[0].isdigit()]
    assert days == sorted(days)


def test_ended_and_unknown_rows_are_dimmed_with_only_the_next_time(client_demo):
    s = soup_of(client_demo.get("/supports"))
    low = [sec for sec in s.select(GROUP_ROW) if sec.select_one("h2").contents[0].strip() in GROUP_TITLES[3:]]
    assert len(low) == 2
    rows = [r for sec in low for r in sec.select("tr.sp-row")]
    assert rows and all("is-low" in r["class"] for r in rows)
    assert not [r for sec in s.select(GROUP_ROW) if sec not in low for r in sec.select("tr.sp-row") if "is-low" in r["class"]]
    ended = [r.select_one(".sp-when").text.strip() for r in low[0].select("tr.sp-row")]
    assert all(t.startswith(("올해 ", "내년 ")) and t.endswith("월쯤 다시 받아요") for t in ended)      # 묶음 제목이 '올해 신청은 끝났어요'를 말하고, 날짜 칸 첫 줄에는 다음 철(같은 글자 15줄이 벽이 되지 않게)
    assert not any("올해 끝났어요" in r.text for r in low[0].select("tr.sp-row"))
    assert all(r.select_one(".sp-when").text.strip().startswith("언제 받는지는 창구에 물어보세요") for r in low[1].select("tr.sp-row"))


def test_filter_chips_work_without_script_through_the_address(client_demo):
    cat = catalog_of(client_demo)
    s = soup_of(client_demo.get("/supports"))
    chips = {c.text.split()[0] if False else c["href"]: c for c in s.select("a.sp-chip")}
    assert "/supports" in chips and any(h.startswith("/supports?f=") for h in chips)
    for fd in cat.filters():
        if fd.id == "all":
            continue
        r = client_demo.get(f"/supports?f={fd.id}")
        page = soup_of(r)
        assert len(page.select("a.sp-card")) == fd.count == len(cat.select(fd.id))
        on = page.select("a.sp-chip.is-on")
        assert len(on) == 1 and on[0]["href"] == f"/supports?f={fd.id}"
        assert f"{fd.count}가지만 보고 있어요" in page.select_one(".sp-shown").text


def test_unknown_filter_falls_back_to_all(client_demo):
    s = soup_of(client_demo.get("/supports?f=zzz"))
    assert len(s.select("a.sp-card")) == 28 and s.select_one("a.sp-chip.is-on")["href"] == "/supports"


def test_citrus_filter_only_keeps_citrus_cards(client_demo):
    cat = catalog_of(client_demo)
    s = soup_of(client_demo.get("/supports?f=citrus"))
    shown = {c.select_one(".sp-name").text.strip() for c in s.select("a.sp-card")}
    assert shown == {e.title for e in cat.entries if "citrus" in e.filters} and "농지연금" not in shown


def test_list_bottom_bar_buttons(client_demo):
    s = soup_of(client_demo.get("/supports"))
    prev, main = s.select_one(".actionbar .btn-prev"), s.select_one(".actionbar .btn-main")
    assert prev["href"] == "/" and prev.text.strip() == "처음으로"
    assert main["href"] == "/counsel" and main.text.strip() == "내가 받을 수 있는지 찾기"
    assert len(s.select("main a.btn-primary")) == 1


# ---------- 안내 ----------

def test_every_support_page_opens_and_matches_the_catalog(client_demo):
    cat = catalog_of(client_demo)
    for e in cat.entries:
        r = client_demo.get(e.href)
        assert r.status_code == 200, e.key
        s = soup_of(r)
        assert s.select_one("h1").text.strip() == e.title
        text = main_text(r)
        assert e.window.split(" · ")[0] in text or e.variants, e.key
        assert e.verified_text in text, e.key
        for c in e.contacts:
            assert office_say(c.office) in text and (c.phone is None or c.phone in text), e.key
        for d in e.documents:
            assert d in text, e.key
        for c in e.checks:
            assert check_say(c) in text, e.key                       # 접어 둔 글도 HTML 에 있다(네/아니요로 답할 조건은 같이 확인해요 표의 쉬운 말, 그 밖은 표의 글 그대로)
        for c in e.conditions:
            assert c in text, e.key
        assert s.select_one(".actionbar .btn-prev")["href"] == "/supports"
        assert s.select_one(".actionbar .btn-main")["href"] == "/counsel"


def test_values_on_the_page_are_the_table_values(client_demo):
    t = main_text(client_demo.get("/supports/JEJU-SMALLFARM"))
    assert "1년에 15만 원" in t and "0.5ha 이하" in t
    pension = main_text(client_demo.get("/supports/NAT-PENSION-SUPPORT"))
    assert "보험료 50%, 월 최대 50,350원" in pension and "언제든 신청할 수 있어요" in pension
    assert "59세 이하" in pension


def test_multi_crop_page_lists_each_crop_window(client_demo):
    cat = catalog_of(client_demo)
    e = cat.get("NAT-CROP-INS")
    t = main_text(client_demo.get(e.href))
    for v in e.variants:
        assert v.label in t and v.window in t
    assert "지난 공고 기준이에요. 올해 공고가 나오면 달라질 수 있어요" in t


def test_link_opens_in_new_window_with_the_notice(client_demo):
    cat = catalog_of(client_demo)
    e = cat.get("NAT-PENSION-SUPPORT")
    s = soup_of(client_demo.get(e.href))
    a = s.select_one("a.sp-ext")
    assert a["href"] == e.link.url and a["target"] == "_blank" and "noopener" in a["rel"]
    assert "새 창이 열려요. 다 보시면 그 창을 닫으세요" in s.select_one(".sp-link-note").text
    assert len(s.select('a[target="_blank"]')) == 1


def test_support_without_link_has_no_external_anchor(client_demo):
    cat = catalog_of(client_demo)
    no_link = [e for e in cat.entries if e.link is None]
    assert no_link, "링크 없는 지원이 하나는 있어야 이 시험이 뜻이 있다"
    for e in no_link:
        s = soup_of(client_demo.get(e.href))
        assert not s.select('a[target="_blank"]') and not s.select("a.sp-ext"), e.key
        assert "인터넷 안내가 없어요. 위에 적힌 곳에 물어보세요" in s.select_one("main").text
        hrefs = {a["href"] for a in s.select("main a")}
        assert hrefs <= {"/supports", "/counsel"}, e.key       # 아래 띠 단추 두 개뿐


def test_hold_support_says_it_is_being_checked(client_demo):
    cat = catalog_of(client_demo)
    holds = [e for e in cat.entries if e.hold]
    assert holds
    for e in holds:
        assert "아직 확인 중인 내용이에요" in main_text(client_demo.get(e.href))
    card_text = row_of(soup_of(client_demo.get("/supports")), holds[0].href).text
    assert "언제 받는지는 창구에 물어보세요" in card_text


def test_unknown_support_goes_to_the_easy_error_screen(client_demo):
    r = client_demo.get("/supports/NO-SUCH-THING")
    assert r.status_code == 404 and "찾으시는 화면이 없어요" in r.text
    assert client_demo.get("/supports/new-%EC%97%86%EC%9D%8C").status_code == 404


def test_no_english_or_code_words_on_the_screens(client_demo):
    cat = catalog_of(client_demo)
    pages = [client_demo.get("/supports")] + [client_demo.get(f"/supports?f={f.id}") for f in cat.filters()]
    pages += [client_demo.get(e.href) for e in cat.entries]
    for r in pages:
        t = soup_of(r).select_one("main").get_text(" ", strip=True)
        assert not CODE_WORDS.search(t), CODE_WORDS.search(t).group(0)
        assert not re.search(r"\b[a-z_]{6,}\b", t.replace("noopener", "")), re.search(r"\b[a-z_]{6,}\b", t).group(0)


# ---------- 새 공고 ----------

def test_new_notices_join_the_list_and_filter(client_new):
    cat = catalog_of(client_new)
    assert cat.count == 29 and cat.hidden_notices == 1
    s = soup_of(client_new.get("/supports"))
    assert "모두 29가지" in s.select_one(".sp-count").text and len(s.select("a.sp-card")) == 29
    first = s.select("tr.sp-row.is-new")[0]
    assert first.select_one(".sp-new").text.strip() == "AI가 읽은 공고" and first.select_one(".sp-c-where").text.strip()
    assert "'AI가 읽은 공고'는 AI가 도·시 공고를 읽어 올린 것이에요. 조건은 창구에서 확인하세요" in s.select_one(".sp-newnote").text
    assert not first.select(".sp-agency, .sp-badge")
    only = soup_of(client_new.get("/supports?f=new"))
    assert len(only.select("a.sp-card")) == 1 and "AI가 읽은 공고" in only.select_one("a.sp-chip.is-on").text


def test_new_notice_page_shows_original_quotes_and_the_ai_warning(client_new):
    cat = catalog_of(client_new)
    e = next(x for x in cat.entries if x.kind == "notice")
    r = client_new.get(e.href)
    assert r.status_code == 200
    t = main_text(r)
    assert "AI가 공고에서 읽은 내용이에요. 금액과 자격은 따지지 않았으니 자세한 조건은 창구에 물어보세요" in t
    from app.catalog.texts import plain_line
    for _, quote in e.new_quotes:
        if quote != e.title.removeprefix("2027년 ") and e.title.removeprefix("2027년 ") not in quote:     # 공고 이름을 되풀이한 인용은 따로 안 보인다
            from app.catalog.layout import where_line
            assert where_line(plain_line(quote)) in t              # 앞머리 기호('나. ')와 '접수처:' 이름만 떼고 그대로 보인다
    assert e.new_period_line in t and all(x in t for x in e.new_content_lines)
    assert "가. 신청기간" not in t
    a = soup_of(r).select_one("a.sp-ext")
    assert a["href"] == e.link.url and a["target"] == "_blank" and "공고문 보기" in a.text
    assert e.verified_text in t and not CODE_WORDS.search(t)


def test_staff_line_counts_tables_and_new_notices(client_demo, client_new):
    t = client_demo.get("/staff").text
    assert "지원 목록" in t and "표 28가지 · AI가 읽은 공고 0건" in t and 'href="/supports"' in t
    t2 = client_new.get("/staff").text
    assert re.search(r"표 28가지 · AI가 읽은 공고 1건\((마지막으로 읽은 날 \d+월 \d+일|시연 자료)\)", t2)
    assert "새 공고" not in t and "새 공고" not in t2


def test_staff_menu_hold_count_matches_the_list(client_demo):
    """'준비 중인 지원제도 N건' 숫자와 아래 '준비 중인 지원제도 N건 보기'·목록 길이가 같다(이름이 같은 두 건은 한 가지)."""
    s = BeautifulSoup(client_demo.get("/staff").text, "html.parser")
    n = int(re.search(r"준비 중인 지원제도\s*(\d+)건", s.select_one(".s-status").get_text(" ")).group(1))
    summary = s.select_one(".s-holds summary").get_text()
    assert f"{n}건" in summary and len(s.select(".s-holds li")) == n
    assert "없습니다" not in s.get_text()


def test_broken_link_table_does_not_break_the_screens(tmp_path):
    cdir = tmp_path / "catalog"
    cdir.mkdir()
    (cdir / "links.csv").write_text("틀린,머리\n1,2\n", encoding="utf-8")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    try:
        assert c.get("/supports").status_code == 200 and c.get("/supports/NAT-PENSION-SUPPORT").status_code == 200
        assert not soup_of(c.get("/supports/NAT-PENSION-SUPPORT")).select("a.sp-ext")
    finally:
        c.__exit__(None, None, None)


# ---------- 첫 화면 ----------

def test_home_due_cards_link_to_their_support_page(client_demo):
    s = soup_of(client_demo.get("/"))
    cards = s.select("a.dl-link")
    assert 1 <= len(cards) == len(s.select(".dl"))
    for a in cards:
        assert a["href"].startswith("/supports/") and a.select_one(".dl-go")
        assert client_demo.get(a["href"]).status_code == 200


def test_home_all_supports_button_has_no_count(client_demo):
    s = soup_of(client_demo.get("/"))
    b = s.select_one("a.btn-all")
    # 사장 지시(11-14 밤): 단추에 개수("33가지")를 적지 않는다. 개수는 들어가서 보면 된다.
    assert b["href"] == "/supports" and b.text.strip() == "지원 전체 보기" and "가지" not in b.text
    # 사장 지시(11-14 저녁): 단추는 "곧 마감되는 지원" 제목 줄 오른쪽(.sec-head)에 있다. 마감 카드가 없을 때만 .all-row 에 홀로 놓인다.
    assert b.find_parent(class_="deadlines") is not None and b.find_parent(class_="sec-head") is not None
    assert b.find_parent(class_="sec-head").select_one("h2.sec-title") is not None


def test_home_all_supports_button_stays_without_due_cards(client_demo, monkeypatch):
    from app.core.home import HomeLines
    monkeypatch.setattr("app.ui.routes_home.home_lines", lambda *a: HomeLines(due30=(), data_line="", hold_count=0))
    s = soup_of(client_demo.get("/"))
    assert not s.select(".dl") and s.select_one("a.btn-all")["href"] == "/supports"


def test_home_link_keys_are_quoted_addresses(client_demo):
    from app.catalog import support_href
    assert support_href("new-감귤 공고").startswith("/supports/new-") and " " not in support_href("new-감귤 공고")
    assert quote("NAT-CROP-INS", safe="") == "NAT-CROP-INS"
    assert build_catalog  # 목록 자료는 app.catalog 가 만든다(이 시험은 화면 쪽만 본다)


# ---------- 안내: 한눈에 띠, 누가 받나요 표, 접어 둔 칸 ----------

def test_every_support_page_has_the_three_cell_glance_band_in_order(client_demo):
    cat = catalog_of(client_demo)
    for e in cat.entries:
        s = soup_of(client_demo.get(e.href))
        cells = s.select(".sp-glance > section.sp-cell")
        assert [c.select_one("h2").text.strip() for c in cells] == ["얼마나", "언제 신청해요", "어디서 신청해요"], e.key
        assert all(c.select_one(".sp-v").text.strip() for c in cells), e.key
        assert not s.select(".sp-tagline, .sp-tags, .sp-badge"), e.key               # 이름표 알약은 머리에 없다
        assert s.select_one("h1").find_next("div", class_="sp-glance") is not None
        assert s.select_one("h1").text.strip() == e.title


def test_glance_band_shows_big_value_with_small_notes(client_demo):
    s = soup_of(client_demo.get("/supports/NAT-PENSION-SUPPORT"))
    amount, when, where = s.select(".sp-glance .sp-cell")
    assert amount.select_one(".sp-v").text.strip() == "보험료 50%, 월 최대 50,350원(2026)" and when.select_one(".sp-v").text.strip() == "언제든 신청할 수 있어요"
    assert where.select_one(".sp-v-phone").text.strip() == "1355" and "국민연금공단 지사" in where.select_one(".sp-small").text
    s = soup_of(client_demo.get("/supports/JEJU-FARMER-ALLOW"))
    when = s.select(".sp-glance .sp-cell")[1]
    assert when.select_one(".sp-v").text.strip() == "올해 신청은 끝났어요"
    notes = [x.text.strip() for x in when.select(".sp-small")]
    assert notes[0].endswith("월쯤 다시 받아요") and "지난 공고 기준이에요. 올해 공고가 나오면 달라질 수 있어요" in notes       # 넓은 '작년 기준' 띠 대신 덧말
    assert not s.select("p.sp-note")


def test_crop_table_has_one_row_per_crop(client_demo):
    cat = catalog_of(client_demo)
    e = cat.get("NAT-CROP-INS")
    s = soup_of(client_demo.get(e.href))
    table = s.select_one('section[aria-label="누가 받나요"] table.sp-table')
    tables = s.select('section[aria-label="누가 받나요"] table.sp-table')
    assert len(tables) == 2                              # 조건(넓이)이 같은 작물끼리 한 표: 조건은 표 위에 한 번만 적는다
    assert all([th.text.strip() for th in t.select("thead th")] == ["작물", "언제 신청해요"] and t.select_one("caption") for t in tables)
    rows = [tr for t in tables for tr in t.select("tbody tr")]
    assert len(rows) <= len(e.variants) == 7             # 같은 시기인 작물은 한 줄로 묶는다
    for v in e.variants:                                 # 작물도 시기도 하나 빠지지 않는다
        tr = next(tr for tr in rows if v.label in tr.select_one("th").text.replace("보고 계신 줄", "").split(" · "))
        assert v.window in tr.select("td")[-1].text
    assert sum("월동무 · 브로콜리" in tr.select_one("th").text for tr in rows) == 1
    table = tables[0]
    assert "농업경영체에 등록해야 해요" in s.select_one('section[aria-label="누가 받나요"]').select_one(".sp-lines").text    # 모든 줄에 같은 조건은 한 번만
    one = soup_of(client_demo.get("/supports/JEJU-FARMER-ALLOW"))
    assert not one.select("table")                      # 조건이 한 가지뿐이면 표 없이 줄로
    assert len(one.select('section[aria-label="누가 받나요"] .sp-lines li')) == len(cat.get("JEJU-FARMER-ALLOW").conditions)
    taxi = soup_of(client_demo.get("/supports/JEJU-HAPPY-TAXI")).select_one("table.sp-table")
    assert [th.text.strip() for th in taxi.select("thead th")] == ["지역", "조건"] and len(taxi.select("tbody tr")) == 2


def test_checks_are_folded_but_in_the_html_and_documents_stay_open(client_demo):
    cat = catalog_of(client_demo)
    e = cat.get("JEJU-FARMER-ALLOW")
    s = soup_of(client_demo.get(e.href))
    fold = s.select_one("details.sp-fold")
    assert fold is not None and not fold.has_attr("open")
    summary = fold.select_one("summary")
    assert summary.contents[0].strip() == f"창구에서 확인하실 것 {len(e.checks)}가지" and summary.select_one(".sp-when-closed").text == "보기" and summary.select_one(".sp-when-open").text == "접기"
    assert [li.text.strip() for li in fold.select("li")] == [check_say(c) for c in e.checks]               # 펼친 글: 쉬운 말 조각은 쉬운 말, 나머지는 표의 글 그대로
    docs = s.select_one('section[aria-label="준비물"]')
    assert [li.text.strip() for li in docs.select("li")] == list(e.documents) and not docs.find_parent("details")
    nothing = soup_of(client_demo.get("/supports/NAT-PENSION-SUPPORT"))
    assert not nothing.select('section[aria-label="준비물"]')                           # 준비물이 없으면 칸도 없다


def test_link_button_is_below_the_body_and_verified_date_is_last(client_demo):
    s = soup_of(client_demo.get("/supports/NAT-PENSION-SUPPORT"))
    body = s.select_one(".sp-body")
    kids = [c for c in body.find_all(recursive=False)]
    names = [(" ".join(c.get("class", [])) or c.name) for c in kids]
    assert names.index("sp-link") > names.index("sp-two") > names.index("sp-glance") and names[-1] == "sp-verified"


def test_list_says_where_to_apply_in_each_row(client_five):
    s = soup_of(client_five.get("/supports"))
    def where(prefix):
        tr = next(r for r in s.select("tr.sp-row") if r.select_one(".sp-name").text.strip().startswith(prefix))
        return [x.text.strip() for x in tr.select(".sp-c-where > *") if "sp-phone" not in (x.get("class") or [])]       # 전화 줄은 따로 시험한다(test_list_shows_phone...)
    assert where("농작물재해보험") == ["지역농협"]
    assert where("농어업인 건강보험료 지원") == ["건강보험공단 지사"]
    assert where("FTA기금 과수(감귤) 고품질시설현대화 지원사업") == ["지역 농·감협"]
    assert where("유기농업자재") == ["농지가 있는 읍·면·동"]
    assert where("농촌융복합산업") == ["서귀포시 감귤유통과 직접 방문 접수(문의: 064-760-2883)"]
    assert where("유기질비료 지원사업") == ["안내에서 확인하세요"] and where("출산 농가도우미 지원사업") == ["안내에서 확인하세요"]
    assert not s.select(".sp-pill, .sp-pills, .sp-c-who")
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8")
    narrow = css[css.index("@media (max-width: 760px)"):]
    assert 'content: "어디서"' in narrow and 'content: "언제까지"' in narrow                 # 좁은 창: 머리 줄이 숨으므로 칸마다 작은 머리 글


def test_list_phone_number_is_one_unbreakable_piece(client_five):
    s = soup_of(client_five.get("/supports"))
    tr = next(r for r in s.select("tr.sp-row") if r.select_one(".sp-name").text.strip().startswith("농촌융복합산업"))
    assert [x.text for x in tr.select(".sp-c-where .sp-tel")] == ["064-760-2883"]
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8")
    assert "white-space: nowrap" in css[css.index(".sp-tel"):].split("}")[0]


# ---------- 어디서 신청해요 칸의 전화번호(2026-11-15) · 남은 날 딱지 빨강 ----------

def _row_by_title(client, title):
    from app.catalog.layout import groups_of
    from app.ui.routes_supports import today_of

    class Req:
        app = client.app
    cat = catalog_of(client)
    return next(r for g in groups_of(cat.entries, None, today_of(Req())) for r in g.rows if r.entry.title == title)


def test_list_where_phone_is_only_the_number_in_the_data(client_demo):
    """자료(Entry.contacts)에 전화가 있는 곳만 이름 아래에 번호가 붙는다. 번호를 새로 만들지 않는다."""
    from app.catalog.layout import groups_of
    from app.ui.routes_supports import today_of

    class Req:
        app = client_demo.app
    cat = catalog_of(client_demo)
    rows = [r for g in groups_of(cat.entries, None, today_of(Req())) for r in g.rows]
    assert all(len(r.where_phones) == len(r.where) for r in rows)
    for r in rows:
        data = {c.phone for c in r.entry.contacts if c.phone}
        assert {p for p in r.where_phones if p} <= data
    assert _row_by_title(client_demo, "농어업인 건강보험료 지원").where_phones == ("1577-1000",)
    assert _row_by_title(client_demo, "농업인 국민연금보험료 지원").where_phones == ("1355",)
    assert _row_by_title(client_demo, "농작물재해보험").where_phones == ("",)               # 지역농협: 자료에 전화 없음
    assert _row_by_title(client_demo, "농지연금").where_phones == ("",)                    # 이름에 이미 1577-7770
    assert _row_by_title(client_demo, "소농직불금").where_phones == ("",)                  # 이름에 이미 ARS 1334


def test_list_ask_phone_is_the_data_number_shown_with_a_label(client_demo):
    """한 곳이 아닌 곳(읍·면·동, 지역농협)에 자료가 적어 둔 번호는 담당 부서 번호다. 지어내지 않고 자료 번호만, 화면에는 "문의"를 달아 보인다."""
    from app.catalog.layout import groups_of
    from app.ui.routes_supports import today_of

    class Req:
        app = client_demo.app
    cat = catalog_of(client_demo)
    rows = [r for g in groups_of(cat.entries, None, today_of(Req())) for r in g.rows]
    assert all(len(r.where_asks) == len(r.where) for r in rows)
    for r in rows:
        data = {c.phone for c in r.entry.contacts if c.phone}
        assert {p for p in r.where_asks if p} <= data
        assert not any(a and b for a, b in zip(r.where_phones, r.where_asks))       # 한 곳에 번호 줄은 하나뿐
    assert _row_by_title(client_demo, "제주 농민수당").where_asks == ("064-710-4092",)
    assert _row_by_title(client_demo, "농어업인 건강보험료 지원").where_asks == ("",)       # 한 곳(건보공단)은 문의가 아니라 그 곳 번호
    assert _row_by_title(client_demo, "농작물재해보험").where_asks == ("",)               # 지역농협: 자료에 전화 없음
    s = soup_of(client_demo.get("/supports"))
    asks = s.select(".sp-phone.sp-ask")
    assert asks and all(a.select_one(".sp-ask-lab").get_text(strip=True) == "문의" for a in asks)
    assert any("064-710-4092" in a.get_text() for a in asks)


def test_list_shows_phone_line_under_where_without_repeating_number(client_demo):
    s = soup_of(client_demo.get("/supports"))
    rows = {r.select_one(".sp-name").get_text(strip=True): r for r in s.select("tr.sp-row")}
    ph = rows["농어업인 건강보험료 지원"].select_one(".sp-c-where .sp-phone")
    assert ph and ph.select_one("svg") and ph.get_text(strip=True) == "1577-1000"
    assert not rows["농작물재해보험"].select(".sp-phone")
    assert rows["농지연금"].select_one(".sp-c-where").get_text(" ", strip=True).count("1577-7770") == 1
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8")
    block = re.search(r"\.sp-phone \{([^}]*)\}", css).group(1)
    assert "white-space: nowrap" in block and int(re.search(r"font-size: (\d+)px", block).group(1)) >= 22


def test_left_pill_is_red_with_enough_contrast():
    css = (APP_ROOT / "app" / "ui" / "static" / "app.css").read_text(encoding="utf-8")
    red = re.search(r"--urgent:\s*(#[0-9A-Fa-f]{6})", css).group(1)

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)
    for bg in ("#FFFFFF", "#FFF6E3", "#FFFDF5"):
        assert ratio(red, bg) >= 4.5
    assert re.search(r"\.left-pill \{[^}]*color: var\(--urgent\)[^}]*border: 2px solid var\(--urgent\)", css)
    assert re.search(r"\.left-pill\.is-urgent \{[^}]*background: var\(--urgent\)[^}]*color: #fff", css)
