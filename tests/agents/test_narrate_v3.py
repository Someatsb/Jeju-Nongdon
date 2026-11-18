"""설명 글 지시문 narrate-v3: 해요체, 행정 말 금지, 먼저 하실 일(첫 가실 곳)과 같은 순서. 옛 녹화(narrate-v2)는 그대로 재생된다."""
import json
import re

import pytest
from counsel_fixtures import CTX_P4, FS_P4
from review_fixtures import CONTEXTS, sheet_ids

from app.agents import counsel
from app.agents.counsel import PROMPT_PATH, PROMPT_VER, build_request, narrate
from app.agents.fallback_ko import KINDS, template_for
from app.agents.llm.base import GenResult
from app.agents.reviewer import MemoryReviewLog, build_feedback, review_section
from app.agents.rules import Section, Sentence, check_rules
from app.agents.style import STYLE_CODES, check_style, first_stop_label, style_check_for

DIGITS = re.compile(r"[0-9０-９①-⑳]")
LEGACY = PROMPT_PATH.parent / "narrate-v2.txt"


def sec(*texts: str, kind="action", cite="A:x") -> Section:
    return Section(section=kind, sentences=tuple(Sentence(sid=i, text=t, cites=(cite,)) for i, t in enumerate(texts, 1)))


def codes(section: Section, first_stop=None) -> list[tuple[str, int]]:
    return [(h.rule, h.sid) for h in check_style(section, first_stop)]


# --- 지시문 ----------------------------------------------------------------------------------

def test_prompt_v3_asks_for_haeyo_and_bans_office_words():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert PROMPT_VER == "narrate-v3" and PROMPT_PATH.name == "narrate-v3.txt" and LEGACY.is_file()
    assert not DIGITS.search(text)
    for must in ("해요체", "~하세요", "~돼요", "합쇼체", "'건'", "'접수기관'", "'해당'", "first_stop", "먼저 하실 일"):
        assert must in text, must
    assert "존댓말" not in text and "해당될 수 있다" not in text


# --- 말투 규칙 -------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["이 제도는 확인해 보시면 좋겠습니다.", "먼저 경영체 등록을 하셔야 합니다.", "창구는 농협입니다.",
                                  "내일 가 보겠습니다", "농협에 가십시오.", "이 제도는 받는 것이 아닙니다.", "신청하셨습니까?", "받으셨습니까"])
def test_hapsyo_endings_are_caught(text):
    assert codes(sec(text)) == [("STYLE_HAPSYO", 1)]


@pytest.mark.parametrize("text", ["이 제도는 확인해 보세요.", "먼저 경영체 등록을 하셔야 돼요.", "창구는 농협이에요.", "아니에요.",
                                  "{P:a_x}은 창구에서 확인해 보세요.", "조건이 맞는지 건강보험 쪽도 물어보세요."])
def test_haeyo_sentences_pass(text):
    assert codes(sec(text)) == []


@pytest.mark.parametrize("text", ["{P:a_x} 건은 창구에서 확인해 보세요.", "접수기관에서 확인해 보세요.", "접수 기관에 물어보세요.",
                                  "맞는 분께 해당돼요.", "관할 창구로 가세요."])
def test_admin_words_are_caught(text):
    assert [c for c, _ in codes(sec(text))] == ["STYLE_ADMIN"]


def test_words_that_only_contain_the_syllable_are_not_admin_words():
    assert codes(sec("조건이 물건처럼 많아도 건강보험 얘기는 창구에서 들어요.")) == []


def test_order_must_follow_the_first_stop():
    wrong = sec("먼저 농협에서 확인하세요.", "그다음 농관원에 가세요.")
    assert codes(wrong, "농관원") == [("STYLE_ORDER", 1)]
    assert codes(sec("농관원에서 경영체 등록부터 하세요.", "그다음 농협에서 확인하세요."), "농관원") == []
    assert codes(sec("먼저 경영체 등록을 하세요.", "그다음 농협에서 확인하세요."), "농관원") == []      # 곳 이름이 없는 문장은 건너뛴다
    assert codes(wrong, None) == []                                                              # 먼저 하실 일이 없으면 순서를 보지 않는다
    assert codes(sec("농협에서 확인하세요.", kind="support"), "농관원") == []                      # 행동 구획만 본다


def test_the_style_codes_are_separate_from_the_old_rules():
    from app.agents.rules import RULE_CODES
    assert STYLE_CODES.isdisjoint(RULE_CODES) and len(RULE_CODES) == 14


# --- 먼저 하실 일의 가실 곳 --------------------------------------------------------------------

def test_first_stop_is_a_kind_of_place_never_a_name_or_a_number():
    got = {name: first_stop_label(ctx) for name, ctx in CONTEXTS.items()}
    assert all(v is None or (v in {"농관원", "농협", "읍면동", "농지은행", "국민연금공단", "건강보험공단"}) for v in got.values())
    assert any(v is not None for v in got.values())


def test_request_for_the_action_section_carries_the_first_stop_and_no_new_numbers():
    label = first_stop_label(CTX_P4)
    for kind in ("support", "insurance", "action"):
        body = json.loads(build_request(kind, CTX_P4).messages[0].text)
        assert (counsel.FIRST_STOP_KEY in body) == (kind == "action" and label is not None)
        assert not DIGITS.search(build_request(kind, CTX_P4).messages[0].text)
    if label:
        assert json.loads(build_request("action", CTX_P4).messages[0].text)[counsel.FIRST_STOP_KEY] == label


def test_old_version_request_is_exactly_the_old_one():
    req = build_request("action", CTX_P4, ver="narrate-v2")
    assert req.system == LEGACY.read_text(encoding="utf-8") and counsel.FIRST_STOP_KEY not in req.messages[0].text


# --- 검수 루프 -------------------------------------------------------------------------------

def _good(kind="support", cite="M:x"):
    return sec("이 제도는 창구에서 확인해 보세요.", kind=kind, cite=cite)


def test_a_hapsyo_candidate_is_sent_back_and_the_rewrite_passes():
    ctx = CONTEXTS["P4"] if "P4" in CONTEXTS else next(iter(CONTEXTS.values()))
    item = next(i for i in ctx.items if i.section == "support")
    bad = sec("{P:%s}은 확인해 보시면 좋겠습니다." % item.program_id, kind="support", cite=item.fact_id)
    good = sec("{P:%s}은 창구에서 확인해 보세요." % item.program_id, kind="support", cite=item.fact_id)
    asked = []

    def regen(fb):
        asked.append(fb)
        return good

    log = MemoryReviewLog()
    out = review_section(bad, ctx, sheet_ids(ctx), None, regen, log, style=style_check_for(None))
    assert out.source == "ai_pass" and out.attempts == 2 and out.final == good
    assert asked[0].codes == ("STYLE_HAPSYO",) and "해요체" in asked[0].text and not DIGITS.search(asked[0].text)
    assert log.entries[0]["checks"] == [{"rule": "STYLE_HAPSYO", "sid": 1}] and log.entries[0]["style_ver"]


def test_a_candidate_that_never_gets_fixed_ends_as_the_default_sentences():
    ctx = next(iter(CONTEXTS.values()))
    kind = ctx.items[0].section
    item = ctx.items[0]
    bad = sec("{P:%s}은 확인해 보시면 좋겠습니다." % item.program_id, kind=kind, cite=item.fact_id)
    out = review_section(bad, ctx, sheet_ids(ctx), None, lambda fb: bad, MemoryReviewLog(), style=style_check_for(None))
    assert out.source == "template" and out.attempts == 3
    assert check_style(out.final) == [] and check_rules(out.final, ctx, sheet_ids(ctx)) == []


def test_feedback_for_the_old_rules_speaks_haeyo_in_style_mode_only():
    old = build_feedback("support", [("RIGHTS", 1)])
    new = build_feedback("support", [("RIGHTS", 1)], style=True)
    assert "해당될 수 있습니다" in old.text and "해당" not in new.text and "맞을 수 있어요" in new.text and not DIGITS.search(new.text)


# --- 기본 문장 -------------------------------------------------------------------------------

def test_default_sentences_are_haeyo_and_pass_every_check_in_every_context():
    checked = 0
    for name, ctx in CONTEXTS.items():
        ids = sheet_ids(ctx)
        for kind in KINDS:
            if not any(i.section == kind for i in ctx.items):
                continue
            s = template_for(kind, ctx)
            assert check_rules(s, ctx, ids) == [] and check_style(s, first_stop_label(ctx)) == [], (name, kind, s)
            checked += 1
    assert checked >= 4


# --- 녹화 재생(옛 판) ------------------------------------------------------------------------

class Fake:
    provider = model = "x"

    def __init__(self, ver=None):
        if ver:
            self.recording = type("R", (), {"prompt_ver": ver})()
        self.systems: list[str] = []

    def generate(self, req):
        self.systems.append(req.system)
        if req.purpose == "judge":
            return GenResult(text='{"verdict": "PASS", "reason_code": null}', tool_calls=(), stop="end", tok_in=0, tok_out=0,
                             latency_ms=0, provider="x", model="x")
        body = json.loads(req.messages[0].text.split("\n\n")[0])           # 재생성 요청은 뒤에 지시문이 붙는다
        item = next(i for i in CTX_P4.items if i.section == body["section"])
        text = "{P:%s}은 확인해 보시면 좋겠습니다." % item.program_id           # 합쇼체: 새 판에서는 걸리고 옛 판에서는 통과한다
        return GenResult(text=json.dumps({"section": body["section"], "sentences": [{"sid": 1, "text": text, "cites": [item.fact_id]}]},
                                         ensure_ascii=False), tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0,
                         provider="x", model="x")


def test_a_recording_of_the_old_version_is_replayed_with_the_old_prompt_and_old_rules():
    old, new = Fake("narrate-v2"), Fake()
    n_old = narrate(FS_P4, old, MemoryReviewLog())
    n_new = narrate(FS_P4, new, MemoryReviewLog())
    assert {s for s in old.systems if "도우미" in s} == {LEGACY.read_text(encoding="utf-8")}
    assert all(o.source == "ai_pass" for o in n_old.sections.values())                       # 옛 판은 합쇼체를 막지 않는다
    assert {s for s in new.systems if "도우미" in s} == {PROMPT_PATH.read_text(encoding="utf-8")}
    assert all(o.source == "template" for o in n_new.sections.values())                      # 새 판은 막고, 끝내 못 고치면 기본 문장
    assert all(check_style(o.final) == [] for o in n_new.sections.values())


def test_an_unknown_version_name_is_not_followed():
    unknown = Fake("narrate-v0")
    narrate(FS_P4, unknown, MemoryReviewLog())
    assert {s for s in unknown.systems if "도우미" in s} == {PROMPT_PATH.read_text(encoding="utf-8")}
