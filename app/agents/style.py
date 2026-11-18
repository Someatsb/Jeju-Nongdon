"""설명 글의 말투 검사(지시문 narrate-v3부터): 해요체, 행정 말 금지, 먼저 하실 일의 가실 곳 순서.

어르신 시험에서 나온 지적을 코드로 건다. 화면은 해요체인데 설명 글만 "~하시면 좋겠습니다"였고, "농작물보험 건은"·"접수기관" 같은 행정 말이
섞였고, 결론 띠의 먼저 하실 일(첫 가실 곳)과 문장의 순서가 어긋났다.

- 규칙 R1~R6(rules.py)과 따로 둔다: 규칙 표(RULES_VERSION)와 옛 녹화(narrate-v2) 재생은 그대로이고, 이 검사는 새 판에서만 건다.
- STYLE_HAPSYO   문장이 합쇼체로 끝맺거나 안에 합쇼체 끝이 있다(~합니다·~입니다·~겠습니다·~하십시오).
- STYLE_ADMIN    행정 말: 건(의존명사), 접수기관, 해당, 관할, 소정, 상기.
- STYLE_ORDER    먼저 하실 일의 첫 가실 곳이 주어졌는데(first_stop) 행동 구획의 문장이 다른 곳을 먼저 말한다.
가실 곳은 낱말(농관원·농협·주민센터…)로만 본다. 숫자·읍면동 이름은 AI에 보내지 않는다(곳의 종류만 보낸다).
"""
import re
from collections.abc import Callable

from app.agents.rules import PLACEHOLDER, Hit, Section
from app.core.models import NarrativeInput

STYLE_VERSION = "style-v1"
STYLE_CODES = frozenset({"STYLE_HAPSYO", "STYLE_ADMIN", "STYLE_ORDER"})
FIRST_STOP_KEY = "first_stop"

STYLE_MESSAGES: dict[str, str] = {
    "STYLE_HAPSYO": "해요체로 쓰세요. 문장을 '~하세요', '~돼요', '~예요'로 끝내고 '~합니다', '~입니다', '~좋겠습니다'는 쓰지 마세요.",
    "STYLE_ADMIN": "행정 말을 쓰지 마세요. '건', '접수기관', '해당' 대신 쉬운 말('창구', '맞는지', '받을 수 있는지')로 쓰세요.",
    "STYLE_ORDER": "먼저 하실 일로 주어진 가실 곳부터 말하세요. 다른 곳을 먼저 말하지 마세요.",
}
# 해요체 지시문에서 규칙이 권하는 말도 해요체로 바꾼다(RULES의 RIGHTS·R7의 OVERPROMISE 문구는 합쇼체와 '해당'을 쓴다).
STYLE_OVERRIDES: dict[str, str] = {
    "RIGHTS": "권리처럼 말하지 마세요(받으실 수 있어요, 지급돼요 등). '맞을 수 있어요'처럼 조심스럽게 쓰세요.",
    "OVERPROMISE": "받을 것처럼 부풀렸어요. '맞을 수 있어요'처럼 조심스럽게 쓰세요.",
}

_HAPSYO = re.compile(r"(?<!아)[가-힣]니다(?![가-힣])|아닙니다|[가-힣]습니까|십시오")
# 건: 앞이 한글이 아니고(띄어 쓴 의존명사) 뒤에 조사만 붙는 것. 조건·물건·건강처럼 낱말 안의 건은 걸리지 않는다
_ADMIN = re.compile(r"(?<![가-힣])건(?:은|는|이|가|을|를|도|에|만|으로|이라)?(?![가-힣])|접수\s?기관|해당|관할|소정|상기")

# 가실 곳 낱말 → 곳의 종류. 순서는 길게 맞는 것부터
_PLACES: tuple[tuple[str, str], ...] = (
    (r"농관원|농산물품질관리원|품질관리원", "농관원"),
    (r"농지은행|농어촌공사", "농지은행"),
    (r"국민연금", "국민연금공단"),
    (r"건강보험공단|건보공단", "건강보험공단"),
    (r"농협|농·감협|지역농협", "농협"),
    (r"주민센터|행정복지센터|읍·면사무소|읍면사무소|면사무소|읍사무소|동사무소|읍·면·동", "읍면동"),
)
_PLACE_RX = [(re.compile(p), label) for p, label in _PLACES]
# 행동의 접수처 id → 곳의 종류(AI에는 이 종류 이름만 보낸다. 읍면동 이름이 든 접수처 이름은 보내지 않는다)
_OFFICE_LABEL = (("naqs", "농관원"), ("coop", "농협"), ("emd", "읍면동"), ("farmland_bank", "농지은행"), ("krc", "농지은행"),
                 ("nps", "국민연금공단"), ("nhis", "건강보험공단"))
_TODO_KINDS = frozenset({"URGENT", "DISASTER_REPORT", "INSURANCE_CLAIM", "PREREQ", "ASK_COOP"})   # 결론 띠의 먼저 하실 일(sheet_cards.TODO_KINDS와 같다)


def first_stop_label(ctx: NarrativeInput) -> str | None:
    """먼저 하실 일(첫 줄)의 가실 곳 종류. 먼저 하실 일이 없거나 곳의 종류를 모르면 None. 숫자·읍면동 이름은 담지 않는다."""
    for item in ctx.items:
        if item.section == "action" and item.status in _TODO_KINDS:
            oid = item.office_id or ""
            return next((label for prefix, label in _OFFICE_LABEL if oid.startswith(prefix)), None)
    return None


def _mask(text: str) -> str:
    return re.sub(PLACEHOLDER, lambda m: "가" * len(m[0]), text)


def check_style(section: Section, first_stop: str | None = None) -> list[Hit]:
    """구획 하나의 말투 검사. 걸린 것이 없으면 []."""
    hits: list[Hit] = []
    for s in section.sentences:
        text = _mask(s.text)
        for code, rx in (("STYLE_HAPSYO", _HAPSYO), ("STYLE_ADMIN", _ADMIN)):
            for m in rx.finditer(text):
                hits.append(Hit(rule=code, sid=s.sid, span=text[m.start():m.end()]))
    if first_stop and section.section == "action":
        texts = [_mask(s.text) for s in section.sentences]
        for n, (s, text) in enumerate(zip(section.sentences, texts)):    # 처음으로 가실 곳을 말하는 문장 하나만 본다
            found = sorted((m.start(), label) for rx, label in _PLACE_RX if (m := rx.search(text)))
            if found:
                later = any(rx.search(t) for rx, label in _PLACE_RX if label == first_stop for t in texts[n:])
                if found[0][1] != first_stop and (n == 0 or later):   # 첫 줄이 다른 곳 이야기이거나, 먼저 할 곳을 말은 하는데 뒤에 말한다
                    hits.append(Hit(rule="STYLE_ORDER", sid=s.sid, span=found[0][1]))
                break
    return list(dict.fromkeys(hits))


StyleCheck = Callable[[Section], list[Hit]]


def style_check_for(first_stop: str | None) -> StyleCheck:
    return lambda section: check_style(section, first_stop)


def style_message(code: str, overrides: bool = True) -> str | None:
    return STYLE_MESSAGES.get(code) or (STYLE_OVERRIDES.get(code) if overrides else None)


__all__ = ["STYLE_VERSION", "STYLE_CODES", "STYLE_MESSAGES", "STYLE_OVERRIDES", "FIRST_STOP_KEY", "StyleCheck", "check_style",
           "first_stop_label", "style_check_for", "style_message"]
