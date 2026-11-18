"""결과 화면 단순화(2026-11-14 설계 2절): 결론 한 줄 규칙 · 카드 최대 셋(종이와 같은 묶음) · 세는 숫자는 결론의 것 하나뿐 · 큰 감귤색 단추는 "종이로 뽑기" 하나 ·
올해 어려운 것은 자세히 보기 안 · 영어·코드 낱말 없음 · 골든 22건과 재생 P1~P5 전부에서 화면 값이 종이 카드와 같다."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests" / "golden")]

from golden_adapter import CASES_DIR, build_paper, case_env, load_case, to_profile  # noqa: E402

from app.core.sheet import EmptyFront  # noqa: E402
from app.core.sheet_cards import MAX_CARDS, build_cards  # noqa: E402
from app.ui.render import _narrative_slots  # noqa: E402
from app.ui.result_view import build_view, headline_parts  # noqa: E402

from .test_replay import run_demo  # noqa: E402

GOLDEN = tuple(sorted(p.stem for p in CASES_DIR.glob("*.json")))
DEMO_IDS = ("P1", "P2", "P3", "P4", "P5")
NAMES = [f"golden_{c}" for c in GOLDEN] + [f"demo_{p}" for p in DEMO_IDS]
ENGLISH = re.compile(r"[A-Za-z]{3,}")
ENGLISH_OK = {"ARS", "kg", "NH", "ha", "SMS", "FTA"}        # 쓰는 말 그대로인 약어·단위(농업e지의 e는 한 글자)
CODE_WORDS = ("emd_", "supports:", "NOT_APPLICABLE", "BLOCKED", "PREREQ", "ASK_COOP", "COOP_SWITCH", "program_key", "None", "null", "undefined")


@pytest.fixture(scope="module")
def papers():
    from app.config import load_config
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    from app.ui import forms
    out = {}
    for cid in GOLDEN:
        case = load_case(cid)
        env = case_env(case)
        fs, sheet, _ = build_paper(to_profile(case["profile"]), env.bundle, env.snap, env.cfg)
        out[f"golden_{cid}"] = (fs, sheet, env.bundle, env.cfg.as_of)
    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    demo = json.loads((ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
    for pid in DEMO_IDS:
        prof = forms.to_profile(demo[pid]["form"])
        prof = prof.model_copy(update={"already_receiving": frozenset(demo[pid].get("already") or ())})
        fs, sheet, _ = build_paper(prof, bundle, snap, cfg)
        out[f"demo_{pid}"] = (fs, sheet, bundle, cfg.as_of)
    return out


def visible_text(html: str) -> str:
    """화면에 보이는 글: 스크립트·스타일·직원이 볼 내용(확인 번호·검수 표)은 뺀다."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    html = re.sub(r'<details class="staff">.*?</details>', " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---------------- 화면 값(build_view): 모든 사례 ----------------
@pytest.mark.parametrize("name", NAMES)
def test_view_cards_are_the_paper_cards_and_at_most_three(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    cs = build_cards(sheet, fs)
    v = build_view(sheet, fs, bundle, as_of)
    assert v["conclusion"] == cs.conclusion and v["count"] == cs.count and v["others_n"] == cs.others_count
    assert len(v["cards"]) <= MAX_CARDS
    if not isinstance(sheet.front, EmptyFront):
        assert [c["no"] for c in v["cards"]] == [c.no for c in cs.cards]
        assert [[l["title"] for l in c["lines"]] for c in v["cards"]] == [[cl.title for cl in c.lines] for c in cs.cards]
        assert [c["hidden_n"] for c in v["cards"]] == [len(c.hidden) for c in cs.cards]
        assert not v["cards"] or v["cards"][0]["emphasis"]
        # 올해 어려운 것은 카드 줄에 없고 자세히 보기 안에 있다
        later_titles = {it["title"] for it in v["detail"]["later"]}
        assert later_titles == {it.title for it in cs.later}
        assert not later_titles & {l["title"] for c in v["cards"] for l in c["lines"]}
    else:
        assert v["empty"] and v["cards"] and v["conclusion"] == sheet.front.title


@pytest.mark.parametrize("name", NAMES)
def test_headline_parts_rejoin_to_the_conclusion_and_highlight_the_money_or_count(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    v = build_view(sheet, fs, bundle, as_of)
    joined = "".join(t for t, _ in v["conclusion_parts"])
    assert joined == v["conclusion"]
    marked = [t for t, hi in v["conclusion_parts"] if hi]
    if "연 약" in v["conclusion"]:
        assert marked == [re.search(r"연 약 .+?(?= 받을 수 있어요$)", v["conclusion"]).group(0)]
    elif re.search(r"지원 \d+가지", v["conclusion"]):
        assert marked == [re.search(r"\d+가지", v["conclusion"]).group(0)]


def test_headline_parts_examples():
    assert headline_parts("경영체 등록부터 하세요. 조건이 맞으면 연 약 180만~258만 원 받을 수 있어요") == [
        ("경영체 등록부터 하세요. 조건이 맞으면 ", False), ("연 약 180만~258만 원", True), (" 받을 수 있어요", False)]
    assert headline_parts("받을 수 있는 지원 6가지를 찾았어요") == [("받을 수 있는 지원 ", False), ("6가지", True), ("를 찾았어요", False)]
    assert headline_parts("먼저 마늘 농작물보험부터 하세요") == [("먼저 마늘 농작물보험부터 하세요", False)]


@pytest.mark.parametrize("name", NAMES)
def test_only_the_conclusion_counts_supports(papers, name):
    """세는 숫자는 결론 한 줄의 ○가지 하나뿐: 결론에 ○가지가 나오는 것은 '받을 수 있는 지원 ○가지' 규칙일 때만이고, 카드 머리·위 띠에 따로 세지 않는다."""
    fs, sheet, bundle, as_of = papers[name]
    v = build_view(sheet, fs, bundle, as_of)
    assert len(re.findall(r"\d+가지", v["conclusion"])) <= 1
    assert not re.search(r"\d+가지", v["sub"] or "") and not re.search(r"\d+가지", v["who"])


@pytest.mark.parametrize("name", NAMES)
def test_speak_text_is_conclusion_sentences_and_cards(papers, name):
    fs, sheet, bundle, as_of = papers[name]
    v = build_view(sheet, fs, bundle, as_of)
    assert v["speak"].startswith(v["conclusion"].replace("~", "에서 ").replace("  ", " "))
    for c in v["cards"]:
        for l in c["lines"]:
            assert l["title"] in v["speak"]
        if c["head"]:
            assert c["head"] in v["speak"]
    assert "~" not in v["speak"]
    assert not re.search(r"(첫|둘|셋|넷|다섯|여섯|일곱|여덟)째,", v["speak"])       # 화면에 번호가 없으니 소리 글도 순서말 대신 곳 이름으로 읽는다
    for c in v["cards"]:
        if c["head"] and c["no_n"]:
            assert c["head"] + "에서는." in v["speak"]


# ---------------- 그려진 화면: 재생 P1~P5 ----------------
@pytest.fixture(params=DEMO_IDS)
def page(request, client_replay):
    r = run_demo(client_replay, request.param)
    assert r.status_code == 200
    return request.param, r.text


def test_one_big_orange_button_and_no_old_pieces(page):
    pid, html = page
    bar = html[html.index('class="rbar"'):html.index('id="detail"')]
    assert bar.count("btn-primary") == 1 and 'id="print-btn"' in bar and "종이로 뽑기" in bar       # 큰 감귤색 단추는 "종이로 뽑기" 하나
    main = html[html.index('id="summary"'):html.index('id="detail"')]
    assert "btn-primary" not in main.replace(bar, "")
    for gone in ("big-num", "summary-big", "who-chips", "first-task", 'class="places"', 'class="groups"', "res-right", "pv-frame", "paper-wrap"):
        assert gone not in html


def test_cards_at_most_three_and_conclusion_is_the_band_text(page):
    pid, html = page
    cards = re.findall(r'<article class="bx"', html)
    assert len(cards) >= 1                                           # 화면에는 가실 곳 한도가 없다(종이만 셋까지)
    assert html.count('class="bx is-first"') == html.count('class="bx-tag is-first"')
    band = html[html.index('id="summary"'):html.index('id="cards"')]
    heading = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", band[band.index("<h1"):band.index("</h1>")])).strip()
    assert heading.endswith(("하세요", "원", "찾았어요", "있어요", "어려워요. 내년에 하려면 먼저 할 일이 있어요"))      # 결론 한 줄 규칙의 끝맺음
    assert band.count("<h1") == 1


def test_detail_overlay_has_the_hard_this_year_and_the_staff_fold(page):
    pid, html = page
    detail = html[html.index('id="detail"'):]
    assert "같이 확인해요" in detail and "어려운 말 풀이" in detail
    assert "올해 못 받는 것은 없어요" not in detail                                                      # 올해 못 받는 것이 없으면 그 상자는 없다(제목과 반대되는 빈 상자를 두지 않는다)
    assert ("올해는 어려워요 · 내년에 하려면 먼저 이것부터" in detail) == ("먼저 필요한 것" in detail)
    assert "이 종이는 공문서가 아니에요" in detail and 'data-pv-open="front"' in detail and "닫고 돌아가기" in detail
    assert '<details class="staff">' in detail and "직원이 볼 내용" in detail
    assert 'data-dt-close' in detail and 'id="dt-open"' in html and 'href="#detail"' in html      # 스크립트가 꺼져도 맨 아래로 가는 링크


def test_no_english_or_code_words_on_the_elder_screen(page):
    pid, html = page
    text = visible_text(html)
    for w in CODE_WORDS:
        assert w not in text, w
    words = {w for w in ENGLISH.findall(text) if w not in ENGLISH_OK}
    assert not words, words


def test_replay_p4_exact_headline(client_replay):
    html = run_demo(client_replay, "P4").text
    assert "경영체 등록부터 하세요. 조건이 맞으면" in html and "연 약 180만~258만 원" in html and "받을 수 있어요" in html
    assert '<span class="rb-hi">연 약 180만~258만 원</span>' in html
    assert "농산물품질관리원(농관원) 제주지원" in html and "1644-8778" in html and "지금 하실 일" in html and "먼저 하실 일" not in html


def test_replay_p1_headline_counts_supports_once(client_replay):
    html = run_demo(client_replay, "P1").text
    assert '<span class="rb-hi">6가지</span>' in html
    assert len(re.findall(r"\d+가지", visible_text(html[html.index('id="summary"'):html.index('id="cards"')]))) == 1


def test_sub_line_is_the_first_sentence_of_the_action_section(client_replay):
    """위 띠 작은 줄 = AI 쉬운 말의 할 일(action) 첫 문장(없으면 지원 문장). 문장은 종이 한마디로 칸과 같은 것."""
    run_demo(client_replay, "P4")
    from .conftest import _session
    from app.ui.routes_counsel import _paper
    paper = _paper(type("R", (), {"app": client_replay.app, "cookies": client_replay.cookies})(), _session(client_replay))
    narr = paper["narr"]
    v = build_view(paper["sheet"], paper["fs"], client_replay.app.state.tables, client_replay.app.state.cfg.as_of, narr)
    first = (narr.get("action") or narr.get("support") or (None,))[0]
    assert v["sub"] == first
    assert first is None or f'<span class="rb-ai" data-ai-slot="sub">{first}</span>' in client_replay.get("/counsel/preview").text


def test_empty_paper_screen_has_keep_cards(client_demo):
    """받을 것이 없는 빈 종이: 결론은 빈 종이 문구, 카드는 끊기지 않게 할 일과 다시 가입할 보험."""
    from tests.golden.golden_adapter import build_paper as bp, case_env as ce, load_case as lc, to_profile as tp
    case = lc("T2")
    env = ce(case)
    fs, sheet, _ = bp(tp(case["profile"]), env.bundle, env.snap, env.cfg)
    if not isinstance(sheet.front, EmptyFront):
        pytest.skip("T2가 빈 종이가 아님")
    v = build_view(sheet, fs, env.bundle, env.cfg.as_of)
    assert v["empty"] and v["conclusion"] == sheet.front.title and v["cards"] and v["others_n"] == 0
    assert all(c["head"] for c in v["cards"])


def test_narrative_slots_feed_the_view_without_digit_sentences():
    slots = _narrative_slots({"action": ["경영체 등록부터 하세요.", "연 180만 원"], "support": ["지원은 창구에서 알려 줘요."]})
    assert slots["action"] == ("경영체 등록부터 하세요.",) and "support" in slots
