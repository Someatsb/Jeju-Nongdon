"""종이 2차 손질(2026-11-16 부장 결정) 가운데 지금도 맞는 것: 앞으로 줄이 앞면 표에 그대로 · 표 아래 줄들 · 때 칸 · 곳 이름 · 오늘까지(날짜) · 빈 종이 결과(뒷면은 2026-11-18 에 없앴다) 화면 두 구역.
골든 22건 + 시험용 P1~P5(재생과 같은 입력 모양)를 모두 돈다."""
import re
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "golden"))
from golden_adapter import CASES_DIR, build_paper, case_env, load_case, to_profile  # noqa: E402

from app.config import load_config
from app.core.sheet import EmptyFront, build_sheet
from app.data_layer.tables import load_tables
from app.ui import render
from app.ui.render import check_overflow, paper_urgent_date, render_sheet, split_when
from app.ui.result_view import build_view, empty_later_rows
from conftest import AS_OF, P1_KWARGS, P2_KWARGS, P3_KWARGS, P4_KWARGS, P5_KWARGS, T1_KWARGS, T2_KWARGS
from factsheet_fixtures import amount, make_fs

CFG = load_config(["--asof", "2026-11-13"])
ALL_GOLDEN = tuple(sorted(p.stem for p in CASES_DIR.glob("*.json")))
TABLES = Path(__file__).resolve().parents[2] / "data" / "tables"
P4_AMOUNTS = (amount("NAT-DIRECT-AREA@2026", 1_800_000, 2_580_000, check=True),)
NARR = {"action": ["경영체 등록부터 하시면 아래 직불을 받으실 길이 열립니다."], "support": ["농협을 거치는 돈은 올해 해당되지 않을 수 있습니다."],
        "insurance": ["보험은 둘 중 하나만 들 수 있습니다."]}


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


@pytest.fixture(scope="module")
def bundle():
    return load_tables(TABLES, AS_OF)


@pytest.fixture(scope="module")
def papers(bundle):
    """{이름: (html, screen view 또는 None)}: 골든 22건 + 시험용 P1~P5(설명 문장 있음)."""
    out = {}
    for cid in ALL_GOLDEN:
        case = load_case(cid)
        env = case_env(case)
        fs, sheet, html = build_paper(to_profile(case["profile"]), env.bundle, env.snap, env.cfg)
        out["G:" + cid] = (html, None if isinstance(sheet.front, EmptyFront) else build_view(sheet, fs, env.bundle, env.cfg.as_of, None, screen=True))
    for name, kw, amts in (("P1", P1_KWARGS, ()), ("P2", P2_KWARGS, ()), ("P3", P3_KWARGS, ()), ("P4", P4_KWARGS, P4_AMOUNTS), ("P5", P5_KWARGS, ())):
        fs = make_fs(kw, bundle, AS_OF, amounts=amts)
        sheet = build_sheet(fs, bundle, AS_OF)
        out["R:" + name] = (render_sheet(sheet, fs, NARR, CFG, crop_labels={}, programs=bundle.programs), build_view(sheet, fs, bundle, AS_OF, None, screen=True))
    return out


# ---------------- 1. 앞으로 신청할 것(넉 달 안 + 때 모르는 줄)은 앞면 표에 화면과 같이 그대로 ----------------
def front_of(html: str):
    """앞면 쪽들(표가 이어지면 둘 이상)의 안쪽을 한 덩어리로 합친 것."""
    pages = parse(html).select(".sheet.front")
    return BeautifulSoup('<div class="front">' + "".join(p.decode_contents() for p in pages) + "</div>", "html.parser").select_one(".front")


def test_every_later_month_and_row_is_on_the_front_and_nothing_is_folded(papers):
    """2026-11-17 사장 지시: 종이 앞면 = 화면 표 그대로. 달마다 한 줄로 접지 않는다. 화면의 앞으로 줄(2026-11-18: 넉 달 안 + 때 모르는 줄)은 모두 앞면 표에 같은 순서로 있다."""
    checked = 0
    for name, (html, view) in papers.items():
        if view is None or not view["later_rows"]:
            continue
        checked += 1
        front = front_of(html)
        for w in front.select(".pz-later .lg-where"):          # 때 아래 작은 글(신청할 곳)은 때가 아니다
            w.decompose()
        months = [squash(w.get_text()) for w in front.select(".pz-later .lg-when")]
        want = [squash(split_when(g["when"])[0]) for g in view["later_groups"]]
        assert months == want, (name, months, want)                                    # 달이 전부, 가까운 달부터, 순서 그대로
        assert not front.select(".lr-more, .lm, .lm-i, .pb-more"), name
        shown_titles = [squash(x.get_text()) for x in front.select(".pz-later .lr-t")]
        assert shown_titles == [squash(r["title"]) for r in view["later_rows"]], name   # 줄도 전부(이름은 줄이지 않는다)
    assert checked >= 20


def test_paper_table_rows_equal_screen_table_rows_for_every_replay_and_golden_case(papers):
    """화면 표의 줄과 종이 표의 줄이 같다(재생 5건 + 골든): 지금 구역은 곳 묶음마다 곳 이름 · 줄 이름이, 앞으로 구역은 달 · 줄 이름이 같은 순서로 하나도 빠짐없이 있다."""
    checked = 0
    for name, (html, view) in papers.items():
        if view is None:
            continue
        checked += 1
        front = front_of(html)
        groups = front.select(".pz-now .pg.rrw")
        assert len(groups) == len(view["now_cards"]), name
        for g, card in zip(groups, view["now_cards"]):
            assert [squash(x.get_text()) for x in g.select(".pr-t")] == [squash(it["title"]) for it in card["rows"]], name
        assert [squash(x.get_text()) for x in front.select(".pz-later .lr-t")] == [squash(r["title"]) for r in view["later_rows"]], name
    assert checked >= 20


def test_the_front_table_keeps_the_notes_the_screen_has(papers):
    """화면 줄의 덧말(회색 작은 글)은 종이 표에도 있다(예전에는 자리가 모자라면 앞으로 줄의 덧말부터 뺐다)."""
    seen = 0
    for name, (html, view) in papers.items():
        if view is None:
            continue
        front = squash(front_of(html).get_text())
        for g in view["later_groups"]:
            for note in g["shared_notes"]:
                seen += 1
                assert squash(note) in front, (name, note)
        for r in view["later_rows"]:
            for note in r["notes"]:
                seen += 1
                assert squash(note) in front, (name, note)
    assert seen >= 20


# ---------------- 2. 알아 두세요도 화면과 같이 전부 ----------------
def test_know_lines_have_the_window_line_and_every_keep_line_the_screen_has(papers):
    """표 아래 줄들(상자·제목 없음): '가실 때 …' 는 언제나, 그 농가의 '끊기지 않게 …' 줄은 화면과 같이 전부. 조건 줄·못 실은 항목 줄은 없다."""
    for name, (html, view) in papers.items():
        if view is None:
            continue
        soup = parse(html)
        assert not soup.select(".know, .know-t"), name
        know = soup.select(".front .keepl")
        assert len(know) == 1, name                                                     # 표 아래 줄들은 끝 쪽에 한 번
        text = squash(know[0].get_text())
        assert text.startswith("가실때") and "조건은" not in text, name
        assert not re.search(r"알아두실것이\d+가지더있어요", text), name                  # 못 실은 항목을 세어 알리는 줄은 없다(전부 싣는다)
        for k in view["know"]:
            if k["kind"] == "keep":
                assert squash(k["title"]) in text, (name, k)


def test_paper_know_lines_equal_the_screen_know_lines_without_the_screen_only_ones(papers):
    """표 아래 줄들 = 화면 알아 두세요의 '가실 때'·'끊기지 않게' 줄(항목·글·순서). 화면에만 있는 줄(자세히 보기 안내 · 금액은 올해 기준이에요)은 종이에 없다."""
    from app.ui.checklist import PRIOR_LINE
    seen = 0
    for name, (html, view) in papers.items():
        if view is None:
            continue
        paper = [squash(p.get_text()) for p in parse(html).select(".front .keepl p")]
        want = []
        for k in view["know"]:
            if k["kind"] == "keep":
                want.append(squash("끊기지 않게 " + k["title"] + ": " + k["text"]))
            elif k["kind"] == "bring":
                want.append(squash(k["text"]))
        seen += 1
        assert paper == want, name
        assert squash(PRIOR_LINE) not in " ".join(paper), name
    assert seen >= 20


def test_the_ai_sentence_does_not_change_the_paper(papers, bundle):
    """결과가 있는 종이에는 AI 한 문장이 없다: 문장이 있든 없든 종이가 같다(자리를 미리 비우지도 않는다)."""
    fs = make_fs(P3_KWARGS, bundle, AS_OF)
    sheet = build_sheet(fs, bundle, AS_OF)
    said = render_sheet(sheet, fs, NARR, CFG, crop_labels={}, programs=bundle.programs)
    plain = render_sheet(sheet, fs, None, CFG, crop_labels={}, programs=bundle.programs)
    assert said == plain


# ---------------- 3. 뒷면이 없다: 한 면, 쪽마다 한도 안 ----------------
def test_every_case_has_only_a_front_and_stays_inside_the_limit(papers):
    for name, (html, _) in papers.items():
        soup = parse(html)
        assert soup.select(".sheet.front") and not soup.select(".back, [data-page=back]"), name
        assert "뒷면" not in html, name
        assert check_overflow(html) == [], name


# ---------------- 4. 때 칸 · 곳 이름 · 오늘까지 ----------------
def test_split_when_keeps_only_the_time_in_the_time_column():
    assert split_when("내년 4월 27일부터 가입할 수 있어요") == ("내년 4월 27일부터", "가입할 수 있어요")
    assert split_when("내년 8~10월에 가입해요") == ("내년 8~10월", "가입해요")
    assert split_when("내년 1월쯤") == ("내년 1월쯤", "")
    assert split_when("때는 창구에 물어보세요") == ("때는 창구에 물어보세요", "")


def test_long_when_text_goes_to_the_row_note_not_the_time_column(bundle, monkeypatch):
    """'내년 4월 27일부터 가입할 수 있어요'는 넉 달 밖이라 보통은 한 줄 안내로 줄지만, 기준을 늘리면(LATER_SHOW_MONTHS) 표에 실리고 때 칸에는 때만, 덧말은 줄 아래에 간다."""
    from app.ui import result_view
    monkeypatch.setattr(result_view, "LATER_SHOW_MONTHS", 12)
    fs = make_fs(P1_KWARGS, bundle, AS_OF)
    html = render_sheet(build_sheet(fs, bundle, AS_OF), fs, NARR, CFG, crop_labels={}, programs=bundle.programs)
    front = parse(html).select_one(".front")
    whens = [squash(w.get_text()) for w in front.select(".lg-when")]
    assert "내년4월27일부터" in whens and not any("가입할수있어요" in w for w in whens)
    row = next(g for g in front.select(".lg") if "27일부터" in g.select_one(".lg-when").get_text())
    assert "가입할 수 있어요" in [n.get_text(strip=True) for n in row.select(".lr-note")]


def test_place_name_wraps_as_one_block_not_one_word():
    css = (Path(render.__file__).parent / "static" / "print.css").read_text(encoding="utf-8")
    assert re.search(r"\.v2 \.lr-sub \{[^}]*display: inline-block", css)               # '읍·면사무소, 동 주민센터'가 낱말 하나만 다음 줄로 넘어가지 않는다


def test_urgent_pill_says_today_with_the_date_when_the_deadline_is_the_base_day():
    due_today = {"urgent": "오늘까지", "text": "오늘 11월 13일까지"}
    assert paper_urgent_date(due_today) == "오늘까지(11월 13일)"
    soon = {"urgent": "5일 남음", "text": "11월 18일까지 · 5일 남음"}
    assert paper_urgent_date(soon) == "11월 18일까지"                                      # 아닌 날은 날짜만(○일 남음은 읽는 날이 달라지면 틀리다)
    assert paper_urgent_date({"urgent": "", "text": "오늘 11월 13일까지"}) == ""


# ---------------- 5. 이미 다 받고 있는 농가의 결과 화면도 두 구역 ----------------
@pytest.mark.parametrize("kw", [T1_KWARGS, T2_KWARGS])
def test_empty_result_screen_splits_now_and_later(kw, bundle):
    fs = make_fs(kw, bundle, AS_OF, amounts=())
    sheet = build_sheet(fs, bundle, AS_OF)
    if not isinstance(sheet.front, EmptyFront):
        pytest.skip("이 입력은 빈 종이가 아니다")
    v = build_view(sheet, fs, bundle, AS_OF, None, screen=True)
    assert v["empty"]
    assert all(c["icon_name"] == "cycle" for c in v["now_cards"]) and all(c["pill"] is None and not c["emphasis"] for c in v["now_cards"])
    later = empty_later_rows(sheet.front)
    assert sorted(r["title"] for r in v["later_rows"] + v["far_rows"]) == sorted(l.title for l in sheet.front.insurance_next) == sorted(r["title"] for r in later)      # 넉 달 밖 줄은 far_rows 로(2026-11-18)
    n_lines = sum(len(c["rows"]) for c in v["now_cards"]) + len(v["later_rows"]) + len(v["far_rows"])
    assert n_lines == len(sheet.front.keep_actions) + len(sheet.front.insurance_next)       # 줄은 사라지지 않고 두 구역 중 한 곳에만 있다
    now_text = " ".join(it["text"] or "" for c in v["now_cards"] for it in c["rows"])
    assert "내년" not in now_text and "가입할 수 있어요" not in now_text                       # 나중 일이 지금 하실 일 안에 들어 있지 않다


def test_empty_result_screen_has_the_two_zones_in_html(client_replay):
    import json

    from app.config import APP_ROOT
    demo = json.loads((APP_ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
    client_replay.post("/counsel/input", data=demo["P1"]["form"])
    page = client_replay.get("/counsel/confirm").text
    already = re.findall(r'name="already" value="([^"]+)"', page)
    assert client_replay.post("/counsel/confirm", data={"already": already}).status_code == 303
    html = client_replay.get("/counsel/preview").text
    soup = parse(html)
    now, later = soup.select_one("section#now"), soup.select_one("section#later")
    assert now is not None and later is not None
    assert "내년" not in now.get_text() and "가입할 수 있어요" not in now.get_text()
    assert "내년 4월 27일부터" not in later.get_text() and "그 뒤에도 1가지가 더 있어요 · 내년 4월부터 신청해요" in " ".join(later.get_text().split()).replace("1가지 가", "1가지가")      # 넉 달 밖이라 한 줄로만
    assert "노지감귤(온주) 농작물보험" in " ".join(soup.select_one(".staff-far").get_text().split())
    assert " ".join(later.select_one(".lt-h").get_text().split()).startswith("앞으로 신청할 것") and later.select_one(".lt-btn")        # 문자 알림 받기 단추
