"""검수 규칙 R1~R6(Task 8). 합격 기준은 round2-C-agent.md §6-2.

좋은 40은 오탐 0, 나쁜 40의 R1~R6 기대 코드는 미탐 0, B31의 R5는 알려진 미탐(xfail),
R7만 걸리는 문장은 규칙 단계를 통과해야 한다(판정 몫). 변이 6종은 기대 코드가 걸려야 한다.
"""
import ast
import re
from pathlib import Path

import pytest
from review_fixtures import BAD, BY_ID, CONTEXTS, GOOD, mutate, sheet_ids

from app.agents.rules import (RULE_CODES, RULE_MESSAGES, RULES_VERSION, Section, Sentence, check_rules, ko_count,
                              parse_section)

RULES_PY = Path(__file__).resolve().parents[2] / "app" / "agents" / "rules.py"


def run(section: Section, context: str):
    ctx = CONTEXTS[context]
    return check_rules(section, ctx, sheet_ids(ctx))


def codes(section: Section, context: str) -> set[str]:
    return {h.rule for h in run(section, context)}


def one(text: str, cites=("M:jeju_farmer_allowance",), kind="support") -> Section:
    return Section(section=kind, sentences=(Sentence(sid=1, text=text, cites=cites),))


# --- 픽스처 자체 -----------------------------------------------------------------------------

def test_fixture_ids_and_counts():
    # 앞 40건씩은 §6-2 그대로, 뒤는 검토 1차 추가(G41~G46, B41~B55)
    assert [c.id for c in GOOD] == [f"G{i:02d}" for i in range(1, 47)]
    assert [c.id for c in BAD] == [f"B{i:02d}" for i in range(1, 56)]
    assert all(c.expect == () for c in GOOD)
    assert all(c.expect for c in BAD)


def test_r7_only_marks_are_consistent():
    for c in BAD:
        if c.expect_r7_only:
            assert not c.rule_expect and not c.known_miss, c.id
    assert sorted(c.id for c in BAD if c.expect_r7_only) == ["B27", "B36", "B37", "B39", "B40"]


def test_contexts_are_numberless():
    for name, ctx in CONTEXTS.items():
        assert not re.search(r"[0-9０-９]", ctx.model_dump_json()), name


# --- 합격 기준 -------------------------------------------------------------------------------

def test_good_40_no_false_positive():
    false_positives = {c.id: run(c.section, c.context) for c in GOOD}
    assert {k: v for k, v in false_positives.items() if v} == {}


BAD_R1_R6 = [c for c in BAD if c.rule_expect]


def test_bad_r1_r6_case_count():
    # §6-2 40 - R7만 5건(B27·B36·B37·B39·B40) - 알려진 미탐 B31 = 34건, 검토 1차 추가 15건
    assert len(BAD_R1_R6) == 34 + 15


@pytest.mark.parametrize("b", BAD_R1_R6, ids=lambda b: b.id)
def test_bad_expected_rules_hit(b):
    # 기대 코드가 걸리고, 그 밖의 코드는 걸리지 않아야 한다(정확히 같음)
    assert codes(b.section, b.context) == set(b.rule_expect)


@pytest.mark.xfail(strict=True, reason="R5 known miss: spaced fabricated program name")
def test_b31_spaced_program():
    b31 = BY_ID["B31"]
    assert "RAW_PROGRAM" in codes(b31.section, b31.context)


@pytest.mark.parametrize("b", [c for c in BAD if c.expect_r7_only], ids=lambda b: b.id)
def test_r7_only_cases_pass_rules(b):
    assert run(b.section, b.context) == []


def test_mutations():
    mutations = [(c.id, m, sec, expected) for c in GOOD for m, sec, expected in mutate(c, CONTEXTS[c.context])]
    with_placeholder = sum("{P:" in c.section.sentences[0].text for c in GOOD)
    assert len(mutations) == 5 * len(GOOD) + with_placeholder
    misses = [(cid, m, sec.sentences[0].text, expected, codes(sec, BY_ID[cid].context))
              for cid, m, sec, expected in mutations if expected not in codes(sec, BY_ID[cid].context)]
    assert misses == []


# --- 경계와 세부 -----------------------------------------------------------------------------

def test_length_boundary_70_chars():
    assert run(one("가" * 69 + "."), "ctx_P4") == []
    assert codes(one("가" * 70 + "."), "ctx_P4") == {"LENGTH"}


def test_length_counts_official_name_not_placeholder():
    # 자리표시자 12자는 정식 이름 "토양생태환경보전(월동채소 면적조절)" 21자로 바뀌어 인쇄된다
    text = "{P:soil_eco}은 " + "가" * (70 - len("{P:soil_eco}은 ") - 1) + "."
    assert len(text) == 70
    assert codes(one(text, cites=("M:soil_eco",)), "ctx_P2") == {"LENGTH"}


def test_three_sentences_ok_four_not():
    s = [Sentence(sid=i, text="창구에서 이 종이를 보여 주시면 됩니다.", cites=("A:prereq_mgmt",)) for i in range(1, 5)]
    assert run(Section(section="action", sentences=tuple(s[:3])), "ctx_P4") == []
    hits = run(Section(section="action", sentences=tuple(s)), "ctx_P4")
    assert [(h.rule, h.sid) for h in hits] == [("LENGTH", 0)]


def test_empty_section_and_duplicate_sid_are_schema():
    assert codes(Section(section="support", sentences=()), "ctx_P4") == {"SCHEMA"}
    s = Sentence(sid=1, text="창구에서 이 종이를 보여 주시면 됩니다.", cites=("M:logistics",))
    assert codes(Section(section="support", sentences=(s, s)), "ctx_P4") == {"SCHEMA"}


def test_broken_placeholder_is_schema():
    assert "SCHEMA" in codes(one("{P:Jeju Allowance}을 알아보세요."), "ctx_P4")
    assert "SCHEMA" in codes(one("{jeju_farmer_allowance}을 알아보세요."), "ctx_P4")


def test_parse_section():
    sec, hits = parse_section('{"section":"support","sentences":[{"sid":1,"text":"창구에서 물어보세요.","cites":["M:logistics"]}]}')
    assert hits == [] and sec.sentences[0].cites == ("M:logistics",)
    sec, hits = parse_section('{"section":"support","sentences":[{"sid":1,"text":"창구에서 물어보세요."}]}')
    assert hits == [] and sec.sentences[0].cites is None  # cites 없음은 check_rules가 문장 단위로 잡는다
    for bad in ("{not json", '{"section":"support"}', '{"section":"other","sentences":[]}',
                '{"section":"support","sentences":[{"sid":1,"text":"가","cites":"M:logistics"}]}'):
        sec, hits = parse_section(bad)
        assert sec is None and [h.rule for h in hits] == ["SCHEMA"], bad


def test_hit_span_is_cut_from_original_text():
    hits = run(one("{P:jeju_farmer_allowance}은 삼월에 신청하시면 지급됩니다."), "ctx_P4")
    assert [(h.rule, h.sid, h.span) for h in hits] == [("NUM_SINO_UNIT", 1, "삼월"), ("RIGHTS", 1, "지급됩니다")]


def test_compare_needs_a_comparison_not_just_channel_words():
    assert "COMPARE" not in codes(BY_ID["G04"].section, "ctx_P4")
    assert "COMPARE" in codes(one("상인보다 농협 쪽이 유리합니다.", cites=("M:logistics",)), "ctx_P4")
    assert "COMPARE" in codes(one("밭떼기로 넘기시면 농협에 내실 때보다 손해입니다.", cites=("M:logistics",)), "ctx_P4")


def test_forecast_past_tense_and_mechanism_allowed():
    assert run(one("작년에는 값이 기준 아래로 떨어졌습니다.", cites=("M:price_stab_cabbage",)), "ctx_P4") == []
    assert "FORECAST" in codes(one("값이 내려갈 것 같습니다.", cites=("M:price_stab_cabbage",)), "ctx_P4")


def test_certainty_negated_hedge_allowed():
    assert run(one("올해 공고가 아직 확정되지 않아 작년 기준으로 적었습니다."), "ctx_P4") == []
    assert run(one("올해 공고가 확정되면 다시 확인해 보세요."), "ctx_P4") == []
    assert run(one("보장 내용은 농협 창구에서 확인해 보세요.", cites=("I:crop_ins_cabbage",), kind="insurance"), "ctx_P4") == []
    assert "CERTAINTY" in codes(one("올해 공고로 확정된 금액입니다."), "ctx_P4")
    assert "CERTAINTY" in codes(one("태풍 피해는 모두 보장됩니다.", cites=("I:crop_ins_cabbage",), kind="insurance"), "ctx_P4")


def test_bare_sino_amount_exceptions():
    assert run(one("이만 줄이고 나머지는 창구에서 여쭤보세요."), "ctx_P4") == []
    assert run(one("천만에요, 언제든 다시 오세요."), "ctx_P4") == []
    assert run(one("만사 제쳐 두고 오실 필요는 없습니다."), "ctx_P4") == []
    assert codes(one("이만오천 정도 됩니다."), "ctx_P4") == {"NUM_SINO_UNIT"}
    assert codes(one("만사천 정도 됩니다."), "ctx_P4") == {"NUM_SINO_UNIT"}


def test_native_day_count_words_are_numbers():
    assert codes(one("피해가 나면 열흘 안에 읍면에 신고하세요."), "ctx_P4") == {"NUM_NATIVE_UNIT"}
    assert run(one("보름달이 뜨기 전에 다녀오시면 좋습니다."), "ctx_P4") == []


def test_insurance_category_words_allowed_only_standalone():
    assert run(one("재해보험은 농협에서 알아보시면 됩니다.", cites=("I:crop_ins_cabbage",), kind="insurance"), "ctx_P4") == []
    assert "RAW_PROGRAM" in codes(one("농작물재해보험은 농협에서 알아보시면 됩니다.", cites=("I:crop_ins_cabbage",),
                                      kind="insurance"), "ctx_P4")


# 픽스처 밖 일상어 함정(오탐 방지). 맥락은 ctx_P4, 인용은 M:jeju_farmer_allowance.
EVERYDAY = [
    "농협 창구로 오세요.",
    "사시는 곳 읍면사무소에 가시면 됩니다.",
    "이분께 이 종이를 보여 드리세요.",
    "오일장에 가시는 길에 들르셔도 됩니다.",
    "삼춘, 이 일은 읍면사무소에서 맡습니다.",
    "구좌읍 사무소에서 서류를 일일이 봐 드립니다.",
    "만일 피해가 나면 바로 읍면에 알리세요.",
    "표시해 두시면 나중에 찾기 쉽습니다.",
    "확실하지 않은 줄은 창구에서 물어보세요.",
    "한림 농협에서도 알아보실 만합니다.",
    "판단은 접수기관이 내립니다.",
    "가족분과 함께 오셔도 됩니다.",
]


@pytest.mark.parametrize("text", EVERYDAY)
def test_everyday_words_no_false_positive(text):
    assert run(one(text), "ctx_P4") == []


def test_rules_version_and_codes():
    assert re.fullmatch(r"rules-v1\.0#[0-9a-f]{8}", RULES_VERSION)
    assert len(RULE_CODES) == 14


LLM_DIGIT = re.compile(r"[0-9０-９①-⑳]")  # app/agents/llm/payload.py 거름망의 digit 규칙과 같은 글자


def test_rule_messages_are_digit_free():
    # 재생성 지시문은 LLM으로 나가므로 숫자가 있으면 전송 거름망에 막힌다(Task 9 판정)
    assert set(RULE_MESSAGES) == RULE_CODES
    assert {k: v for k, v in RULE_MESSAGES.items() if LLM_DIGIT.search(v)} == {}
    assert "세 개" in RULE_MESSAGES["LENGTH"] and "일흔 자" in RULE_MESSAGES["LENGTH"]


def test_ko_count():
    assert [ko_count(n) for n in (1, 3, 10, 20, 21, 70, 99)] == ["한", "세", "열", "스무", "스물한", "일흔", "아흔아홉"]
    with pytest.raises(ValueError):
        ko_count(100)


def test_made_up_spans_are_digit_free():
    # 원문을 그대로 자르지 않는 span(문장 수·글자 수·cites 없음 등)도 지시문에 실릴 수 있다
    sections = [(c.section, c.context) for c in GOOD + BAD]
    sections += [(sec, c.context) for c in GOOD for _, sec, _ in mutate(c, CONTEXTS[c.context])]
    spans = {h.span for sec, ctx in sections for h in run(sec, ctx) if h.rule != "NUM_DIGIT"}
    assert spans and not [s for s in spans if LLM_DIGIT.search(s)]


def test_rules_imports_core_only():
    tree = ast.parse(RULES_PY.read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    app_mods = {m for m in mods if m.split(".")[0] == "app"}
    assert app_mods and all(m.startswith("app.core") for m in app_mods), app_mods
