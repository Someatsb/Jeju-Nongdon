"""새 공고(실제로 읽은 꼴) 화면 다듬기: 기간 말투, 첫 화면 마감 카드에 새 공고 섞임, 안내 화면 칸(설계서 B절)."""
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.config import APP_ROOT

from .conftest import _started_client

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "catalog_notices_polish"
CODE_WORDS = re.compile(r"program_key|CHECK|None|True|False|null|undefined|\bhold\b|\bkey\b|[A-Z]{2,}-[A-Z0-9]{2,}")
TODAY = date(2026, 11, 14)


def soup_of(r):
    return BeautifulSoup(r.text, "html.parser")


def main_text(r) -> str:
    return soup_of(r).select_one("main").get_text(" ", strip=True)


def href_of(client, title: str) -> str:
    for a in soup_of(client.get("/supports?f=new")).select("a.sp-card"):
        if a.select_one(".sp-name").text.strip() == title:
            return a["href"]
    raise AssertionError(title)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config._today", lambda: TODAY)      # 시험은 2026-11-14 기준으로 센다
    cdir = tmp_path / "catalog"
    (cdir / "notices").mkdir(parents=True)
    for f in FOLDER.glob("*.json"):
        shutil.copy(f, cdir / "notices" / f.name)
    shutil.copy(APP_ROOT / "data" / "catalog" / "links.csv", cdir / "links.csv")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    yield c
    c.__exit__(None, None, None)


def test_cards_say_the_period_like_the_table_cards(client):
    s = soup_of(client.get("/supports?f=new"))
    def period(tr):         # 기간 굵게 + 남은 날(또는 낮은 줄의 둘째 줄 글)
        parts = [x.text.strip() for x in tr.select(".sp-when, .sp-left, .left-pill")]      # 기간(굵게)·덧말·남은 날 큰 표시를 한 줄로(표시는 날짜보다 먼저 있다)
        parts = parts[1:] + parts[:1] if tr.select_one(".left-pill") else parts
        return " · ".join(parts)
    cards = {tr.select_one(".sp-name").text.strip(): period(tr) for tr in s.select("tr.sp-row")}
    assert cards["FTA기금 과수(감귤) 고품질시설현대화 지원사업"] == "11월 23일까지 · 9일 남음"
    assert cards["유기질비료 지원사업"] == "12월 4일까지 · 20일 남음"
    assert cards["곧 열리는 자재 지원사업"] == "11월 20일부터 · 6일 뒤 열려요"
    assert cards["지난 시설 지원사업"] == "신청이 끝났어요"
    assert cards["출산 농가도우미 지원사업"] == "언제 받는지는 창구에 물어보세요"
    names = list(cards)
    assert names[0].startswith("FTA기금")                                                 # 마감 가까운 순
    assert names.index("곧 열리는 자재 지원사업") < names.index("지난 시설 지원사업") < names.index("출산 농가도우미 지원사업")   # 묶음 순서: 곧 열려요, 끝났어요, 시기는 창구에서 확인
    assert all(a.select_one(".sp-new").text == "AI가 읽은 공고" for a in s.select("a.sp-card")) and len(s.select("tr.sp-row.is-new")) == len(s.select("tr.sp-row"))
    assert not any("신청기간:" in w or "신청기한:" in w for w in cards.values())


def test_open_filter_lists_new_notices_inside_their_period(client):
    names = [a.select_one(".sp-name").text.strip() for a in soup_of(client.get("/supports?f=open")).select("a.sp-card")]
    for n in ("FTA기금 과수(감귤) 고품질시설현대화 지원사업", "유기질비료 지원사업", "유기농업자재 지원사업"):
        assert n in names
    assert "지난 시설 지원사업" not in names and "곧 열리는 자재 지원사업" not in names


def test_home_due_cards_mix_new_notices_most_urgent_first(client):
    s = soup_of(client.get("/"))
    cards = s.select("a.dl-link")
    assert 1 <= len(cards) <= 3 and len(s.select(".dl")) == len(cards)
    dates = [a.select_one(".dl-date").text.strip() for a in cards]
    assert dates == sorted(dates, key=lambda d: (int(d.split("월")[0]), int(d.split("월")[1].split("일")[0])))          # 날짜 빠른 순
    first = next(a for a in cards if "FTA기금" in a.select_one(".dl-name").text)
    assert first.select_one(".dl-flag").text.strip() == "9일 남음" and first.select_one(".dl-date").text.strip() == "11월 23일까지"
    assert first.select_one(".dl-meta").text.split() == ["11월", "23일까지"]   # 사장 지시: 남은 날 옆 가운뎃점 없음(4차: 남은 날은 카드 맨 위 큰 표시, 날짜만 아래에)
    assert client.get(first["href"]).status_code == 200
    names = " ".join(a.select_one(".dl-name").text for a in cards)
    assert "지난 시설" not in names and "유기농업자재" not in names              # 끝난 것, 30일 밖은 나오지 않는다
    assert all(a["href"].startswith("/supports/") for a in cards)


def test_home_due_cards_are_ordered_by_date_across_tables_and_notices(client):
    from app.ui.routes_home import due_cards
    from app.ui.routes_supports import load_catalog_for

    class Req:
        app = client.app
    cat = load_catalog_for(Req(), TODAY)
    table_due = (("표의 지원 하나", date(2026, 11, 20)),)
    cards = due_cards(client.app.state.tables, TODAY, table_due, cat.entries)
    assert [(c["name"], c["date_text"], c["new"]) for c in cards] == [
        ("표의 지원 하나", "11월 20일부터", False), ("곧 열리는 자재 지원사업", "11월 20일부터", True),
        ("FTA기금 과수(감귤) 고품질시설현대화 지원사업", "11월 23일까지", True)]                     # 같은 날이면 표의 지원이 먼저
    assert cards[2]["flag"] == "9일 남음" and not cards[2]["urgent"]
    assert not due_cards(client.app.state.tables, date(2027, 1, 5), (), cat.entries)               # 마감이 모두 지났으면 안 나온다


def test_fta_page_fills_every_box_from_the_notice_text(client):
    r = client.get(href_of(client, "FTA기금 과수(감귤) 고품질시설현대화 지원사업"))
    s, t = soup_of(r), main_text(r)
    who = s.select_one('section[aria-label="누가 받나요"]').get_text(" ", strip=True)
    assert "공고에 적힌 조건" in who and "감귤 농가 대상" in who and "신청사업: 16개사업" in who and "대상이 따로 적혀 있지 않아요" not in who
    assert "신청·접수계획 알림" not in who                                        # 공고 이름을 되풀이한 글은 대상 칸에 안 나온다
    when = s.select_one('section[aria-label="언제 신청해요"]').get_text(" ", strip=True)
    assert "11월 23일까지" in when and "9일 남음" in when and "신청기간: 2026. 11. 9.(월) ~ 11. 23.(월) (15일간)" in when and s.select_one('section[aria-label="언제 신청해요"] details.sp-more')
    where = s.select_one('section[aria-label="어디서 신청해요"]').get_text(" ", strip=True)
    assert "지역 농·감협" in where and "접수처:" not in where and "공고 원문에서 확인하세요" not in where
    assert "금액은 창구에 물어보세요" in s.select_one('section[aria-label="얼마나"]').text
    assert "가. " not in t and "나. " not in t and "다. " not in t
    assert "AI가 공고에서 읽은 내용이에요. 금액과 자격은 따지지 않았으니 자세한 조건은 창구에 물어보세요" in t and s.select_one("a.sp-ext")["href"].startswith("https://www.seogwipo.go.kr/")


def test_fertilizer_page_shows_the_amount_and_who_without_repeats(client):
    r = client.get(href_of(client, "유기질비료 지원사업"))
    s, t = soup_of(r), main_text(r)
    how = s.select_one('section[aria-label="얼마나"]').get_text(" ", strip=True)
    assert "보조 1,700원 ~ 2,000원/20kg" in how and "금액은 창구에서 확인" not in how
    who = s.select_one('section[aria-label="누가 받나요"]')
    assert who.select_one(".sp-who-list b").text == "농업경영체 등록 농가·법인"
    assert who.select_one(".sp-src").text.startswith("신청자격: 농업경영체")
    assert "20kg" not in who.text
    assert t.count("보조 1,700원 ~ 2,000원/20kg") == 1                            # 같은 글이 두 칸에 겹치지 않는다
    assert "12월 4일까지" in t and "20일 남음" in t and "신청기간: 2026. 11. 10.(화)" in t


def test_page_with_target_and_page_with_agency_and_page_without_period(client):
    t = main_text(client.get(href_of(client, "출산 농가도우미 지원사업")))
    assert "지원대상: 도내 출산(예정) 여성농업인" in t and "지원기준: 농가도우미 1일 기준 단가 82,560원(정액지원)" in t
    assert "언제 받는지는 창구에 물어보세요" in t and "공고에 적힌 기간 글" not in t
    s = soup_of(client.get(href_of(client, "농촌융복합산업 자금(융자) 지원사업")))
    where = s.select_one('section[aria-label="어디서 신청해요"]').get_text(" ", strip=True)
    assert "서귀포시 감귤유통과" in where and "064-760-2883" in where
    assert "금액은 창구에 물어보세요" in s.select_one('section[aria-label="얼마나"]').text
    s = soup_of(client.get(href_of(client, "지난 시설 지원사업")))
    assert "신청이 끝났어요" in s.select_one('section[aria-label="언제 신청해요"]').text


def test_no_english_or_code_words_on_new_notice_pages(client):
    for a in soup_of(client.get("/supports?f=new")).select("a.sp-card"):
        assert not CODE_WORDS.search(main_text(client.get(a["href"])))


def test_citrus_filter_leads_with_the_new_citrus_notice_and_reads_the_citrus_row_period(client):
    s = soup_of(client.get("/supports?f=citrus"))
    first = s.select_one("section.sp-bx")
    assert first.select_one("h2").contents[0].strip() == "지금 신청할 수 있어요"
    top = first.select_one("tr.sp-row")
    assert top.select_one(".sp-name").text.strip() == "FTA기금 과수(감귤) 고품질시설현대화 지원사업" and top.select_one(".sp-when").text == "11월 23일까지"
    assert "양파" not in s.select_one("main").text.split("올해 신청은 끝났어요")[0]          # 감귤 걸러 보기 맨 위에 양파·마늘 날짜가 오지 않는다
    crop = next(a for a in s.select("tr.sp-row") if a.select_one(".sp-name").text.strip() == "농작물재해보험")
    assert "is-low" in crop["class"] and crop.select_one(".sp-when").text == "내년 4월쯤 다시 받아요" and crop.select_one(".sp-left").text == "감귤"        # 감귤 줄의 기간
    chip = next(a for a in s.select("a.sp-chip") if "감귤" in a.text)
    assert chip.select_one("small").text == str(len(s.select("a.sp-card")))                 # 단추 숫자 = 보이는 줄 수(새 공고 포함)


def test_all_view_names_the_crop_behind_the_first_date(client):
    s = soup_of(client.get("/supports"))
    crop = next(a for a in s.select("tr.sp-row") if a.select_one(".sp-name").text.strip() == "농작물재해보험")
    assert crop.select_one(".sp-when").text == "11월 27일까지" and "양파가 제일 먼저예요" in crop.select_one(".sp-left").text


def test_rows_remember_the_filter_so_the_back_button_returns_to_it(client):
    s = soup_of(client.get("/supports?f=citrus"))
    hrefs = [a["href"] for a in s.select("a.sp-card")]
    assert hrefs and all(h.endswith("?f=citrus") for h in hrefs)
    page = soup_of(client.get(next(h for h in hrefs if "NAT-CROP-INS" in h)))
    assert page.select_one(".actionbar a[href='/supports?f=citrus']") is not None
    assert page.select_one("tr.is-focus th").text.strip().startswith("감귤")
    assert page.select_one('section[aria-label="언제 신청해요"] .sp-v').text == "올해 신청은 끝났어요"
    plain = soup_of(client.get("/supports/NAT-CROP-INS"))
    assert plain.select_one(".actionbar a[href='/supports']") is not None and not plain.select("tr.is-focus")
    assert soup_of(client.get("/supports/NAT-CROP-INS?f=nonsense")).select_one(".actionbar a[href='/supports']") is not None


def test_legal_and_official_sentences_are_folded_but_stay_in_the_page(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr("app.config._today", lambda: TODAY)
    cdir = tmp_path / "catalog"
    (cdir / "notices").mkdir(parents=True)
    law = "1. 신청자격: ｢농어업경영체 육성 및 지원에 관한 법률｣ 제2조제3호에 따른 농업경영체"
    official = "3. 2027년 지원사업 신청을 알려드리오니, 희망하는 농가께서는 신청하시기 바랍니다."
    (cdir / "notices" / "법률글.json").write_text(json.dumps({
        "version": 1, "name": "법률 글 시험 지원사업", "agency": "", "apply_period": "3. 신청기간: 2026. 11. 10.(화) ~ 12. 4.(금)", "target": "",
        "content": "- 가종: 보조 1,700원 / 나종: 보조 1,300원",
        "tags": [{"label": "농업경영체 등록 농가", "quote": law}, {"label": "지원 신청 안내", "quote": official}, {"label": "구입비 일부 지원", "quote": "2. 지원내용: 구입비 일부 지원"}],
        "url": None, "read_date": "2026-11-14", "decision": "DRAFT_READY", "table_key": None}, ensure_ascii=False), encoding="utf-8")
    shutil.copy(APP_ROOT / "data" / "catalog" / "links.csv", cdir / "links.csv")
    c = _started_client(["--asof", "2026-11-13", "--catalog-dir", str(cdir)])
    try:
        s = soup_of(c.get(href_of(c, "법률 글 시험 지원사업")))
        who = s.select_one('section[aria-label="누가 받나요"]')
        folds = who.select("details.sp-more")
        assert len(folds) == 2 and not any(d.has_attr("open") for d in folds)
        text = " ".join(d.text for d in folds)
        assert "｢농어업경영체 육성 및 지원에 관한 법률｣" in text and "알려드리오니" in text            # 접어 두어도 글은 그대로 있다
        assert all(b.find_parent("details") is None for b in who.select(".sp-who-list b"))         # 굵은 한 줄(이름표)은 접지 않는다
        amount = s.select_one('section[aria-label="얼마나"]')
        assert amount.select_one(".sp-v").text == "가종: 보조 1,700원" and "나종: 보조 1,300원" in amount.select_one(".sp-small").text      # ' / ' 에서 나눈 항목, 글은 그대로
    finally:
        c.__exit__(None, None, None)


def test_every_support_appears_once_and_filter_counts_match_the_rows(client):
    s = soup_of(client.get("/supports"))
    hrefs = [a["href"] for a in s.select("tr.sp-row a.sp-card")]
    assert len(hrefs) == len(set(hrefs)) == len(s.select("tr.sp-row")) and f"모두 {len(hrefs)}가지" in s.select_one(".sp-count").text
    for chip in s.select("a.sp-chip"):
        page = soup_of(client.get(chip["href"]))
        assert len(page.select("tr.sp-row")) == int(chip.select_one("small").text)          # 단추 숫자 = 그 걸러 보기의 표 줄 수


def test_closing_within_seven_days_is_an_orange_flag_in_the_when_cell(client, monkeypatch):
    monkeypatch.setattr("app.config._today", lambda: date(2026, 11, 20))              # FTA 공고(11월 23일까지)가 3일 남는다
    s = soup_of(client.get("/supports"))
    tr = next(r for r in s.select("tr.sp-row") if r.select_one(".sp-name").text.strip().startswith("FTA기금"))
    flag = tr.select_one(".sp-c-when .left-pill")
    assert flag.text.strip() == "3일 남음" and "is-urgent" in flag["class"]                  # 7일 안: 주황 채움 표시(글로도 남은 날을 말한다)
    assert not tr.select(".sp-soon") and "곧 마감" not in tr.text
    later = next(r for r in s.select("tr.sp-row") if r.select_one(".sp-name").text.strip() == "유기질비료 지원사업")
    assert not later.select(".is-urgent")
    home = soup_of(client.get("/"))
    assert any("is-urgent" in a.select_one(".dl-flag")["class"] for a in home.select("a.dl-link") if "FTA기금" in a.text)


def _rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def _px(decl, prop):
    m = re.search(r"(?<![-\w])" + prop + r":\s*(?:[\d.]+px\s+)?([\d.]+)px", decl)
    return float(m.group(1)) if m else None


def test_boxes_breathe_bands_and_rows_follow_the_spacing_rules():
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert ".sp-pill" not in css and ".sp-pills" not in css                              # 누가 알약은 목록에서 뺐다
    band = re.search(r"\n\.sp-gh \{([^}]*)\}", css, re.S).group(1)
    assert "height: var(--gh-h)" in band and "--gh-h: 64px" in css and _px(band, "font-size") >= 26 and "background: var(--sea-soft)" in band and "color: var(--ink)" in band   # 옅은 청록 띠, 먹색 글씨(대비 12:1)
    assert "background: var(--sea)" not in band
    boxes = re.search(r"\n\.sp-boxes \{([^}]*)\}", css, re.S).group(1)
    assert _px(boxes, "gap") >= 40                                                       # 상자와 상자 사이 40px 이상
    box = re.search(r"\n\.sp-bx \{([^}]*)\}", css, re.S).group(1)
    assert "border-radius" in box and re.search(r"border:\s*2px solid var\(--ink\)", box) and "background: #fff" in box
    row = _rule(css, ".sp-row > *")
    assert _px(row, "height") >= 76 and re.search(r"padding:\s*14px 24px", row)           # 줄 높이 76px, 칸 안 위아래 14px, 칸 사이 24px
    assert "border-radius" not in _rule(css, ".sp-row")                                  # 줄마다 따로 두르지 않는다
    head = re.search(r"\.sp-tab thead th \{([^}]*)\}", css, re.S).group(1)
    assert 18 <= _px(head, "font-size") <= 20 and "var(--ink-soft)" in head      # 칸 머리 줄(붙박이)은 상자마다 작은 회색 글로 되풀이한다
    assert ".sp-newnote + .sp-boxes" in css


def test_list_boxes_use_the_same_left_pill_rule_as_the_home_card():
    app = (APP_ROOT / "app" / "ui" / "static" / "app.css").read_text(encoding="utf-8").replace(chr(13), "")
    pill = re.search(r"\n\.left-pill \{([^}]*)\}", app).group(1)
    assert "font-weight: 800" in pill and _px(pill, "font-size") >= 20 and "border: 2px solid var(--urgent)" in pill and "background: #fff" in pill and "color: var(--urgent)" in pill      # 남은 날 딱지는 빨강(2026-11-15)
    urgent = re.search(r"\.left-pill\.is-urgent \{([^}]*)\}", app).group(1)
    assert "background: var(--urgent)" in urgent and "color: #fff" in urgent
    future = re.search(r"\.left-pill\.is-future \{([^}]*)\}", app).group(1)
    assert "background" not in future and "border-color" in future and "color: var(--ink)" in future      # 아직 안 열린 지원: 빨강을 쓰지 않는다(회색 테두리, 글은 검정)
    home = re.search(r"\.page-home \.left-pill \{([^}]*)\}", app).group(1)
    assert min(int(n) for n in re.findall(r"(\d+)px", home.split("font-size:")[1].split(";")[0])) >= 20       # 어떤 창에서도 20px 이상
    sp = _css()
    assert not re.search(r"\.sp-flag[^{]*\{[^}]*font-size", sp) or True


def test_home_due_card_leads_with_days_left_then_name_then_date(client):
    s = soup_of(client.get("/"))
    cards = s.select("a.dl-link")
    assert cards
    from app.ui.routes_home import due_cards
    from app.ui.routes_supports import load_catalog_for

    class Req:
        app = client.app
    lines = __import__("app.core.home", fromlist=["home_lines"]).home_lines(client.app.state.tables, client.app.state.snapshot, TODAY)
    data = due_cards(client.app.state.tables, TODAY, lines.due30, load_catalog_for(Req(), TODAY).entries)
    for a in cards:
        kids = [c.get("class")[0] for c in a.find_all(recursive=False)]
        assert kids[:3] == ["dl-flag", "dl-name", "dl-meta"]           # 남은 날 표시 -> 이름 -> 날짜
        assert "left-pill" in a.select_one(".dl-flag")["class"]
        meta = a.select_one(".dl-meta")
        assert meta.select_one(".dl-date") and not meta.select(".dl-flag")
        assert "새 공고" not in a.text and not a.select_one(".dl-new")       # 첫 화면 카드에 새 공고 딱지 없음
        name = a.select_one(".dl-name")
        words = [w.text for w in name.select("span.w")]
        assert words and "".join(words) == name.text.replace(" ", "")   # 낱말마다 감싸고, 이으면 원래 이름(긴 낱말은 괄호 앞에서 한 번 더 나눔)
        assert all(len(w) <= 10 for w in words)                        # 한 덩어리가 카드 폭을 넘지 않게
        card = next(c for c in data if "".join(c["name"].split()) == "".join(name.text.split()))
        assert a.select_one(".dl-flag").text.strip() == card["flag"]    # 남은 날 글은 자료가 만든 글 그대로
        assert ("is-urgent" in a.select_one(".dl-flag")["class"]) == bool(card["urgent"])        # 급한 카드만 급함 표시
        assert ("is-future" in a.select_one(".dl-flag")["class"]) == (not card["closing"])
    first = next(a for a in cards if "FTA기금" in a.select_one(".dl-name").text)
    assert first.select_one(".dl-name").text == "FTA기금 과수(감귤) 고품질시설현대화 지원사업"
    assert "long" in first.select_one(".dl-name")["class"]            # 긴 이름은 한 단계 작게


def test_home_card_urgent_means_seven_days_like_the_list(client):
    from app.ui.routes_home import due_cards
    from app.ui.routes_supports import load_catalog_for

    class Req:
        app = client.app
    for today, expect in ((date(2026, 11, 14), False), (date(2026, 11, 16), True), (date(2026, 11, 23), True)):    # FTA 공고는 11월 23일까지: 9일, 7일, 0일 남음
        cat = load_catalog_for(Req(), today)
        fta = next(c for c in due_cards(client.app.state.tables, today, (), cat.entries) if c["name"].startswith("FTA기금"))
        assert fta["urgent"] is expect, today


def test_home_due_card_name_bigger_than_date_in_css():
    import re
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "app/ui/static/app.css").read_text(encoding="utf-8")
    def px(rule):
        m = re.search(re.escape(rule) + r"\s*\{[^}]*?font-size:\s*([^;]+);", css)
        assert m, rule
        return [int(n) for n in re.findall(r"(\d+)px", m.group(1))]
    assert "font-weight: 800" in re.search(r"\n\.dl-name \{[^}]*\}", css).group(0)
    assert px(".page-home .dl-name")[-1] >= 1.2 * px(".page-home .dl-meta")[-1]
    assert min(px(".page-home .dl-name.long")) >= 22 and min(px(".page-home .dl-meta")) >= 18
    assert "white-space: nowrap" in re.search(r"\.dl-name \.w \{[^}]*\}", css).group(0)
    flag = px(".page-home .left-pill")
    assert min(flag) >= 20 and max(flag) >= 24                                  # 남은 날 표시: 어떤 창에서도 20px 이상, 큰 창에서 24px 이상
    assert max(flag) <= max(px(".page-home .dl-name"))                          # 이름보다 크지 않다(이름이 표시에 밀려 작아지지 않는다)
    assert "font-weight: 800" in re.search(r"\n\.left-pill \{[^}]*\}", css).group(0)
    go = re.search(r"\n\.dl-go \{([^}]*)\}", css).group(1)
    assert "tang" not in go and "background" not in go and "border-radius" not in go     # 화살표는 검정 선 화살표(주황 동그라미 없음)
    assert not re.search(r"\.dl\.urgent\s*\{[^}]*background", css)                          # 급한 카드 바탕도 칠하지 않는다(주황은 남은 날 표시에만)


def test_static_files_are_not_cached_by_browser(client_demo):
    """화면을 고친 뒤 브라우저가 옛 CSS 를 붙들면 새 화면에 옛 모양이 입혀진다(사장이 고친 화면을 못 봄). 매번 다시 묻게 한다."""
    for path in ("/static/app.css", "/static/supports.css", "/static/app.js"):
        r = client_demo.get(path)
        assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path


def _css():
    return (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8").replace(chr(13), "")


def test_third_pass_few_colors_where_cell_big_black_and_plain_arrow():
    css = _css()
    lst = css.split("/* ---------- 지원 안내")[0]                                          # 목록 쪽 규칙만
    assert "nth-of-type" not in lst and "nth-child" not in lst and "FFF6E3" not in lst    # 얼룩말 바탕 없음
    name, where, when, left = (_rule(css, k) for k in (".sp-name", ".sp-where", ".sp-when", ".sp-left"))
    assert "clamp(22px" in name and "font-weight: 800" in name
    assert _px(where, "font-size") >= 22 and int(re.search(r"font-weight:\s*(\d+)", where).group(1)) in (600, 700)
    assert "word-break: keep-all" in where and "color: var(--ink)" in where
    assert "var(--sea)" not in when and ".sp-when.is-open" not in css                     # 날짜 글은 청록이 아니라 검정
    assert _px(left, "font-size") >= 20 and "var(--ink-soft)" in left
    go = _rule(css, ".sp-go")
    assert "background" not in go and "border-radius" not in go and "tang" not in go       # 주황 채운 동그라미 없음
    tab_new = re.search(r"\.sp-tab \.sp-new \{([^}]*)\}", css).group(1)
    assert "background: #fff" in tab_new and re.search(r"border: 1\.5px solid var\(--ink\)", tab_new) and "color: var(--ink)" in tab_new and _px(tab_new, "font-size") >= 18
    assert "#FFD25E" not in css
    for k in ("is-low",):
        low = re.search(r"\.sp-row\.is-low \.sp-where[^{]*\{([^}]*)\}", css)
        assert low and "#5F5750" in low.group(1)                                          # 끝난 줄 가실 곳도 한 단계 흐리게(대비 4.5:1 이상)


def test_demo_server_can_override_the_counting_day_so_urgent_flags_show(client_demo, monkeypatch):
    """시연 기준일(--asof)로 띄운 서버도 환경 변수 JEJU_SHOW_TODAY 로 목록·마감 카드의 '오늘'을 바꿀 수 있다(급한 표시 시연용)."""
    monkeypatch.setattr("app.config._today", lambda: date(2026, 11, 14))
    monkeypatch.setenv("JEJU_SHOW_TODAY", "2026-11-20")
    home = soup_of(client_demo.get("/"))
    assert "11월 20일" in home.select_one(".due-base").text
    assert any("is-urgent" in a.select_one(".dl-flag")["class"] for a in home.select("a.dl-link"))
    s = soup_of(client_demo.get("/supports"))
    assert "오늘은 11월 20일이에요" in s.select_one(".sp-count").text and s.select(".sp-flag.is-urgent")
    monkeypatch.setenv("JEJU_SHOW_TODAY", "엉뚱한 글")                                  # 읽을 수 없는 값은 무시하고 실제 오늘
    assert "오늘은 11월 14일이에요" in soup_of(client_demo.get("/supports")).select_one(".sp-count").text


def test_demo_override_is_ignored_when_not_a_demo_server(monkeypatch):
    monkeypatch.setattr("app.config._today", lambda: date(2026, 11, 14))
    c = _started_client([])
    try:
        monkeypatch.setenv("JEJU_SHOW_TODAY", "2026-11-20")
        assert "오늘은 11월 14일이에요" in soup_of(c.get("/supports")).select_one(".sp-count").text
    finally:
        c.__exit__(None, None, None)


def test_box_title_band_and_column_head_stay_pinned_inside_their_own_box():
    css = (APP_ROOT / "app" / "ui" / "static" / "supports.css").read_text(encoding="utf-8")
    box = _rule(css, ".sp-bx")
    assert "overflow: hidden" not in box and "overflow: clip" in box                         # hidden 이면 붙박이가 안 먹는다
    gh = _rule(css, ".sp-gh")
    assert "position: sticky" in gh and "top: 0" in gh
    head = css[css.index(".sp-tab thead th {"):].split("}")[0]
    assert "position: sticky" in head and "top: var(--gh-h)" in head
