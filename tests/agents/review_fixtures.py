"""검수 규칙 픽스처 읽기와 변이기(Task 8). 검수 루프(Task 19) 테스트도 이 모듈을 쓴다.

- 문장: tests/fixtures/review/{good,bad}.jsonl (round2-C-agent.md §6-2 G01~G40·B01~B40)
  한 줄 = {"id","section","context","text","cites","expect","why"}. 문장이 여럿이면 text·cites 대신
  "sentences":[{"text","cites"},...]. cites 키가 없으면 cites 없는 JSON(B03)이다.
  R7만 걸리는 문장은 "expect_r7_only": true, 규칙이 알고도 못 잡는 코드는 "known_miss".
- 맥락: tests/fixtures/contexts/ctx_*.json = NarrativeInput. 종이에 실린 제도 ID 집합은
  맥락 항목의 program_id 전부다(sheet_ids).
"""
import json
from dataclasses import dataclass
from pathlib import Path

from app.agents.rules import R7_CODES, RULE_CODES, Section, parse_section
from app.core.models import NarrativeInput

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONTEXT_NAMES = ("ctx_P1", "ctx_P2", "ctx_P3", "ctx_P4", "ctx_P5", "ctx_T1", "ctx_T2")


@dataclass(frozen=True)
class Case:
    id: str
    section: Section
    context: str
    expect: tuple[str, ...]
    why: str
    expect_r7_only: bool = False
    known_miss: tuple[str, ...] = ()

    @property
    def rule_expect(self) -> frozenset[str]:
        """규칙 단계(R1~R6)에서 걸려야 하는 코드. R7 코드와 알려진 미탐은 뺀다."""
        return frozenset(self.expect) & RULE_CODES - frozenset(self.known_miss)


def load_context(name: str) -> NarrativeInput:
    return NarrativeInput.model_validate_json((FIXTURES / "contexts" / f"{name}.json").read_text(encoding="utf-8"))


def sheet_ids(ctx: NarrativeInput) -> frozenset[str]:
    return frozenset(item.program_id for item in ctx.items)


def _sentences(rec: dict) -> list[dict]:
    raw = rec["sentences"] if "sentences" in rec else [{k: rec[k] for k in ("text", "cites") if k in rec}]
    return [{"sid": i, **s} for i, s in enumerate(raw, start=1)]


def load_cases(kind: str) -> list[Case]:
    cases = []
    for line in (FIXTURES / "review" / f"{kind}.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        section, schema_hits = parse_section({"section": rec["section"], "sentences": _sentences(rec)})
        assert section is not None and not schema_hits, (rec["id"], schema_hits)
        unknown = set(rec["expect"]) - RULE_CODES - R7_CODES
        assert not unknown, (rec["id"], unknown)
        cases.append(Case(id=rec["id"], section=section, context=rec["context"], expect=tuple(rec["expect"]),
                          why=rec["why"], expect_r7_only=rec.get("expect_r7_only", False),
                          known_miss=tuple(rec.get("known_miss", ()))))
    return cases


CONTEXTS = {name: load_context(name) for name in CONTEXT_NAMES}
GOOD = load_cases("good")
BAD = load_cases("bad")
BY_ID = {c.id: c for c in GOOD + BAD}


# --- 변이기 6개(§6-2 표): 좋은 문장 하나 → [(변이기, 변이된 구획, 걸려야 할 코드)] ------------------

def _with(section: Section, **changes) -> Section:
    s = section.sentences[0]
    return section.model_copy(update={"sentences": (s.model_copy(update=changes),)})


def _official_name(ctx: NarrativeInput, program_id: str) -> str:
    return next(i.official_name for i in ctx.items if i.program_id == program_id)


def mutate(case: Case, ctx: NarrativeInput) -> list[tuple[str, Section, str]]:
    sec = case.section
    text = sec.sentences[0].text
    head = text.rstrip().rstrip(".").rsplit(" ", 1)[0]
    out = [
        ("M1", _with(sec, text="3월에 " + text), "NUM_DIGIT"),
        ("M2", _with(sec, text="삼월에 " + text), "NUM_SINO_UNIT"),
        ("M3", _with(sec, text=text.rstrip() + " 확정입니다."), "CERTAINTY"),
        ("M4", _with(sec, text=head + " 받으실 수 있습니다."), "RIGHTS"),
    ]
    start = text.find("{P:")
    if start >= 0:  # M5: 첫 자리표시자만 정식 이름으로
        end = text.index("}", start)
        name = _official_name(ctx, text[start + 3:end])
        out.append(("M5", _with(sec, text=text[:start] + name + text[end + 1:]), "RAW_PROGRAM"))
    out.append(("M6", _with(sec, cites=()), "NO_CITE"))
    return out
