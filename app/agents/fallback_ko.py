"""기본 문장 템플릿(Task 19). 검수에 두 번 재생성하고도 못 통과한 구획을 대신하는 코드 문장.

칸은 NarrativeInput의 숫자 없는 필드(제도 id, 근거 id, 상태)에서만 채운다. 제도 이름은 {P:id}로만 쓴다.
템플릿도 check_rules와 말투 검사(app.agents.style)를 통과해야 한다(tests/agents/test_reviewer_loop.py, test_narrate_v3.py가 모든 맥락에서 확인).
말투는 화면과 같은 해요체다(~하세요·~돼요). '건'·'접수기관'·'해당' 같은 행정 말은 쓰지 않는다.
"""
from app.agents.rules import Section, SectionKind, Sentence
from app.core.models import NarrativeInput, NarrativeItem

KINDS: tuple[SectionKind, ...] = ("support", "insurance", "action", "empty")


def _s(sid: int, text: str, *cites: str) -> Sentence:
    return Sentence(sid=sid, text=text, cites=tuple(cites))


def template_for(kind: SectionKind, ctx: NarrativeInput) -> Section:
    """kind 구획의 기본 문장. 맥락에 그 구획 근거가 없으면 ValueError(그 구획은 종이에 없다)."""
    items = [i for i in ctx.items if i.section == kind]
    if not items:
        raise ValueError(f"맥락에 {kind} 구획 근거가 없습니다.")
    first: NarrativeItem = items[0]
    ph, cite = "{P:" + first.program_id + "}", first.fact_id
    if kind == "support":
        blocked = next((i for i in items if i.status == "BLOCKED_PREREQ"), None)
        if blocked is not None:
            lead = _s(1, "경영체 등록을 먼저 하시면 아래 지원을 신청해 볼 수 있어요.", blocked.fact_id)
        else:
            lead = _s(1, f"{ph}은 맞는지 창구에서 확인해 보세요.", cite)
        sentences = (lead, _s(2, "이 종이는 맞을 수 있는 지원을 정리한 것이고, 마지막 판단은 창구에서 해요.", cite))
    elif kind == "insurance":
        sentences = (_s(1, f"{ph}은 가입 시기와 조건을 농협 창구에서 확인해 보세요.", cite),
                     _s(2, "보험을 권하는 게 아니라, 이런 지원이 있다고 알려 드리는 거예요.", cite))
    elif kind == "action":
        sentences = (_s(1, "이 종이의 아래 줄을 위에서부터 차례로 따라 해 보세요.", cite),
                     _s(2, "막히는 곳은 창구에서 이 종이를 보여 주세요.", cite))
    else:
        sentences = (_s(1, f"이번에는 새로 신청해 볼 지원이 없고, {ph}은 그대로 이어가세요.", cite),)
    return Section(section=kind, sentences=sentences)
