"""가실 곳별 카드 묶음 층(core/sheet_cards.py, 종이 단순화 설계 1·2절): 골든 22건 + 재생 입력 P1~P5 전부에서 줄이 하나도 안 빠지고,
카드는 셋 이하이며, 먼저 하실 일이 첫 카드이고, 결론 한 줄이 설계 2절 규칙대로인지 본다."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests" / "golden")]

from golden_adapter import CASES_DIR, build_paper, case_env, load_case, to_profile  # noqa: E402

from app.core.sheet import EmptyFront  # noqa: E402
from app.core.sheet_cards import MAX_CARDS, MAX_CARD_LINES, TODO_KINDS, build_cards, short_title  # noqa: E402

GOLDEN = tuple(sorted(p.stem for p in CASES_DIR.glob("*.json")))
DEMO = ("P1", "P2", "P3", "P4", "P5")


@pytest.fixture(scope="module")
def papers():
    """이름 → (FactSheet, Sheet). golden_<ID>는 골든 사례, demo_<ID>는 재생 입력(data/replay/demo_inputs.json)."""
    from app.config import load_config
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    from app.ui import forms
    out = {}
    for cid in GOLDEN:
        case = load_case(cid)
        env = case_env(case)
        fs, sheet, _ = build_paper(to_profile(case["profile"]), env.bundle, env.snap, env.cfg)
        out[f"golden_{cid}"] = (fs, sheet)
    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    demo = json.loads((ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))
    for pid in DEMO:
        prof = forms.to_profile(demo[pid]["form"])
        prof = prof.model_copy(update={"already_receiving": frozenset(demo[pid].get("already") or ())})
        fs, sheet, _ = build_paper(prof, bundle, snap, cfg)
        out[f"demo_{pid}"] = (fs, sheet)
    return out


NAMES = [f"golden_{c}" for c in GOLDEN] + [f"demo_{p}" for p in DEMO]


def front_lines(sheet):
    """지금 앞면의 줄 가운데 지원·먼저 할 일 줄(구획 A~E2) + 앞면 한도에 걸려 뒷면으로 갔던 줄."""
    if isinstance(sheet.front, EmptyFront):
        return list(sheet.front.keep_actions)           # 빈 종이: 끊기지 않게 할 일만 카드 층이 받는다(보험 줄은 템플릿이 그대로 그린다)
    return [l for s in ("A", "B", "C", "D", "E", "E2") for l in sheet.front.sections[s]] + list(sheet.overflow)


@pytest.mark.parametrize("name", NAMES)
def test_every_front_line_lands_in_a_card_the_others_the_hard_ones_or_the_keeps(papers, name):
    """(가) 하나도 안 빠진다."""
    fs, sheet = papers[name]
    cs = build_cards(sheet, fs)
    placed = [cl.line for cl in cs.card_lines] + [it.line for it in cs.later] + list(cs.keeps)
    assert sorted(map(repr, placed)) == sorted(map(repr, front_lines(sheet)))


@pytest.mark.parametrize("name", NAMES)
def test_at_most_three_cards_and_at_most_three_lines_each(papers, name):
    """(나) 카드는 셋 이하, 카드 속 보이는 줄은 셋 이하(넘치면 외 ○가지)."""
    fs, sheet = papers[name]
    cs = build_cards(sheet, fs)
    assert len(cs.cards) <= MAX_CARDS
    assert all(len(c.lines) <= MAX_CARD_LINES and c.no for c in cs.cards)
    assert all(c.no == "" and not c.emphasis for c in cs.others)
    assert [c.no for c in cs.cards] == list("①②③")[:len(cs.cards)]


@pytest.mark.parametrize("name", NAMES)
def test_todo_card_comes_first(papers, name):
    """(다) 먼저 하실 일이 있으면 첫 카드이고, 먼저 하실 일 카드는 그렇지 않은 카드보다 앞에 온다. 먼저 하실 일 줄은 카드 안 맨 위."""
    fs, sheet = papers[name]
    cs = build_cards(sheet, fs)
    pool = front_lines(sheet)
    has_todo = any(l.kind in TODO_KINDS for l in pool)
    if has_todo:
        assert cs.cards[0].first and cs.cards[0].emphasis
    flags = [c.first for c in (*cs.cards, *cs.others)]
    assert flags == sorted(flags, reverse=True)
    for c in (*cs.cards, *cs.others):
        todos = [cl.todo for cl in c.all_lines]
        assert todos == sorted(todos, reverse=True)


def expected_conclusion(sheet, cs):
    """(라) 설계 2절 규칙을 줄에서 다시 읽어 낸 기대값."""
    if isinstance(sheet.front, EmptyFront):
        return sheet.front.title
    todo = next((l for l in front_lines(sheet) if l.kind in TODO_KINDS), None)
    if todo is not None:
        money = re.search(r"연 .*$", todo.text)
        short = short_title(todo.title)
        if todo.kind == "PREREQ" and todo.text.startswith("조건이 맞으면") and money:
            return f"{short}부터 하세요. 조건이 맞으면 {money.group(0)} 받을 수 있어요"
        return f"먼저 {short}부터 하세요"
    if cs.count:
        return f"받을 수 있는 지원 {cs.count}가지를 찾았어요"
    return cs.conclusion


@pytest.mark.parametrize("name", NAMES)
def test_conclusion_line_follows_the_design_rules(papers, name):
    fs, sheet = papers[name]
    cs = build_cards(sheet, fs)
    assert cs.conclusion == expected_conclusion(sheet, cs)


def test_conclusion_examples_from_the_design(papers):
    """설계 2절의 예(2026-11-15 표현 정리로 두 문장): 경영체 등록부터 하세요. 조건이 맞으면 연 약 180만~258만 원 받을 수 있어요."""
    fs, sheet = papers["demo_P4"]
    cs = build_cards(sheet, fs)
    assert cs.conclusion == "경영체 등록부터 하세요. 조건이 맞으면 연 약 180만~258만 원 받을 수 있어요"
    assert cs.cards[0].place == "농관원 제주지원" and cs.cards[0].phone == "1644-8778"
    fs, sheet = papers["demo_P1"]
    assert build_cards(sheet, fs).conclusion == "받을 수 있는 지원 6가지를 찾았어요"


@pytest.mark.parametrize("name", NAMES)
def test_card_text_is_the_line_text_unchanged(papers, name):
    """카드 속 글은 Sheet 줄의 글 그대로다(금액·시기·꼬리표를 새로 만들지 않는다). 작은 줄은 줄의 sub·detail에서만 온다."""
    fs, sheet = papers[name]
    for cl in build_cards(sheet, fs).card_lines:
        l = cl.line
        assert cl.title == l.title and cl.text == l.text
        if l.kind == "PREREQ":              # 먼저 하실 일: 작은 줄 = 신청 시기 부연(detail) + 확인 꼬리표
            assert cl.small in (None, "확인할 조건 있음") or cl.small.startswith(l.detail or "확인할 조건 있음")
        else:
            assert cl.small == l.sub
        assert cl.extra in (None, l.detail)


@pytest.mark.parametrize("name", NAMES)
def test_narrative_does_not_change_the_cards_only_the_lead(papers, name):
    fs, sheet = papers[name]
    plain = build_cards(sheet, fs)
    said = build_cards(sheet, fs, {"action": ("할 일 문장입니다.",), "support": ("지원 문장입니다.", "둘째 문장"), "insurance": ("보험 문장입니다.",)})
    assert plain.cards == said.cards and plain.conclusion == said.conclusion
    if not isinstance(sheet.front, EmptyFront):
        assert said.lead == ("할 일 문장입니다.", "지원 문장입니다.") and plain.lead == ()
        assert "보험 문장입니다." in said.back_sentences


@pytest.mark.parametrize("name", NAMES)
def test_basis_is_stated_once_without_the_month(papers, name):
    fs, sheet = papers[name]
    cs = build_cards(sheet, fs)
    if cs.basis:
        assert re.fullmatch(r"\d{4}년 기준 · \d{4}년 공고 전(?: / \d{4}년 기준 · \d{4}년 공고 전)*", cs.basis)


def test_smaller_caps_move_cards_to_the_others_and_hide_lines(papers):
    fs, sheet = papers["golden_B09"]
    big = build_cards(sheet, fs)
    small = build_cards(sheet, fs, max_cards=2, max_lines=1)
    assert len(small.cards) == 2 and all(len(c.lines) == 1 for c in small.cards)
    assert len(small.card_lines) == len(big.card_lines)           # 줄여도 줄은 안 사라진다(그 밖에·외 ○가지로)
    assert small.others and small.cards[1].no == "②"


def test_every_program_with_a_condition_row_gets_a_number_for_the_back(papers):
    fs, sheet = papers["demo_P4"]
    cs = build_cards(sheet, fs)
    for lc in sheet.back.line_conds:
        assert cs.ref.get(lc.program_key), lc.program_key
