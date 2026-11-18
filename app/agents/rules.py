"""검수 규칙 R1~R6(Task 8, U08). 규칙 코드·허용 목록은 research/dept/round2-C-agent.md §6-2.

설명 문장 한 구획(Section)을 코드 규칙으로 검사해 걸린 곳(Hit)을 돌려준다.
R7(근거 일치, LLM 판정)은 reviewer(Task 19), R8(인쇄 직전 HTML)은 ui/preflight(Task 21)가 맡는다.

- 제도 이름은 {P:id} 자리표시자로만 쓴다. 검사할 때 자리표시자는 같은 길이의 "가"로 가린다.
  자리표시자는 명사 자리이므로 조사·낱말 경계가 실제 이름과 똑같이 작동한다.
- 허용 목록 낱말("한 번 더", "두 분", 보험 범주어 3개 …)은 같은 길이의 "_"로 가린다.
  가린 문자열은 원문과 길이가 같아서, 걸린 곳(span)은 원문 위치 그대로 잘라 낸다.
- 문장 길이는 자리표시자를 정식 이름으로 바꾼 뒤(인쇄되는 모양) 잰다.
- Hit.sid=0은 구획 전체(문장 수·빈 구획·JSON 형식)를 뜻한다.
- 띄어쓰기로 지어낸 제도명("어업인 지원금", B31)은 규칙으로 못 잡는다(알려진 미탐, R7 몫).
"""
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, ValidationError

from app.core.models import CoreModel, NarrativeInput

SectionKind = Literal["support", "insurance", "action", "empty"]


class Sentence(CoreModel):
    sid: int = Field(ge=1)
    text: str
    cites: tuple[str, ...] | None = None       # None = cites 키 없음(SCHEMA), () = 인용 없음(NO_CITE)


class Section(CoreModel):
    section: SectionKind
    sentences: tuple[Sentence, ...]


class Hit(CoreModel):
    rule: str
    sid: int                                    # 0 = 구획 전체
    span: str                                   # 걸린 부분(원문에서 잘라 냄) 또는 짧은 설명


RULE_GROUPS: dict[str, tuple[str, ...]] = {
    "R1": ("SCHEMA", "LENGTH"),
    "R2": ("NUM_DIGIT", "NUM_SINO_UNIT", "NUM_NATIVE_UNIT", "NUM_WORD"),
    "R3": ("FORECAST", "CERTAINTY", "COMPARE"),
    "R4": ("RIGHTS",),
    "R5": ("RAW_PROGRAM", "NOT_IN_SHEET"),
    "R6": ("NO_CITE", "BAD_CITE"),
}
RULE_ORDER: tuple[str, ...] = tuple(code for codes in RULE_GROUPS.values() for code in codes)
RULE_CODES = frozenset(RULE_ORDER)
R7_CODES = frozenset({"UNSUPPORTED", "WRONG_STATUS", "OVERPROMISE"})  # LLM 판정(Task 19). 여기서는 안 냄

MAX_SENTENCES = 3
MAX_CHARS = 70

_KO_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
_KO_TENS = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")


def ko_count(n: int) -> str:
    """1~99를 단위 앞에 쓰는 고유어 수사로(3 → "세", 20 → "스무", 70 → "일흔"). 지시문에 숫자를 안 쓰려고."""
    if not 1 <= n <= 99:
        raise ValueError(f"고유어 수사는 1~99만 바꿉니다: {n}")
    tens, ones = divmod(n, 10)
    return "스무" if n == 20 else _KO_TENS[tens] + _KO_ONES[ones]


def _count_words(n: int, unit: str) -> str:
    """Hit.span용 숫자 없는 수량("아흔두 자"). span도 재생성 지시문에 실릴 수 있어 숫자를 쓰지 않는다."""
    return f"{ko_count(n)} {unit}" if n <= 99 else f"{ko_count(99)} {unit} 넘음"


# 재생성 지시문(Task 19)이 쓰는 사유 설명. LLM으로 나가므로 숫자를 쓰지 않는다(전송 거름망이 막음).
# 규칙 표가 아니므로 RULES_VERSION에 넣지 않는다.
RULE_MESSAGES: dict[str, str] = {
    "SCHEMA": "형식 오류입니다. 문장마다 sid·text·cites를 갖추고 자리표시자는 {P:id} 모양으로 쓰세요.",
    "LENGTH": f"구획당 문장은 {ko_count(MAX_SENTENCES)} 개까지, 한 문장은 {ko_count(MAX_CHARS)} 자까지입니다.",
    "NUM_DIGIT": "숫자(아라비아·전각·원문자)를 쓰지 마세요. 숫자는 표 칸이 보여 줍니다.",
    "NUM_SINO_UNIT": "한자어 수사와 단위(삼월, 오십만 원 등)를 쓰지 마세요.",
    "NUM_NATIVE_UNIT": "고유어 수사와 단위(세 가지, 두 번 등)를 쓰지 마세요.",
    "NUM_WORD": "수량어(절반, 몇십만, 전액 등)를 쓰지 마세요.",
    "FORECAST": "가격 전망(오를, 떨어질, 전망 등)을 쓰지 마세요. 지난 사실은 써도 됩니다.",
    "CERTAINTY": "단정(확정, 반드시, 틀림없이 등)을 쓰지 마세요.",
    "COMPARE": "상인과 농협을 견주지 마세요.",
    "RIGHTS": "권리처럼 말하지 마세요(받으실 수 있습니다, 지급됩니다 등). '해당될 수 있습니다'로 쓰세요.",
    "RAW_PROGRAM": "제도 이름은 {P:id} 자리표시자로만 쓰세요.",
    "NOT_IN_SHEET": "이 종이에 없는 제도를 쓰지 마세요.",
    "NO_CITE": "문장마다 근거(cites)를 하나 이상 다세요.",
    "BAD_CITE": "이 상담의 근거 ID 중 이 구획 것을 인용하세요.",
}

# --- 규칙 표(정규식 원문). 이 표가 바뀌면 RULES_VERSION이 바뀐다 ---------------------------------

_START = r"(?<![가-힣])"                                    # 수사 앞: 낱말 첫머리
_JOSA = (r"[을를이가은는에의도만씩째로과와께뿐밖쯤당여간초말경중달]|까지|부터|마다|짜리|정도|동안|미만"
         r"|어치")                                          # 조사, 때·양 접미사(삼월말·유월경·오십만원어치)
_END = rf"(?=$|[^가-힣]|{_JOSA})"                           # 단위 뒤: 낱말 끝이거나 조사·접미사

_DIGITS = (r"\d²³¹¼-¾⁰⁴-⁹₀-₉⅐-↋"
           r"①-⒛⓪-⓿❶-➓㉑-㉟㊱-㊿")  # 아라비아·전각·원문자·분수

_SD, _SM = "일이삼사오육칠팔구", "십백천만억"                   # 한자어 수사: 숫자·자릿수
_SINO_UNITS = (r"만\s?원|천\s?원|억\s?원|원|퍼센트|프로|%|킬로그램|킬로|키로|kg|평|헥타르|ha|톤|개월|년|월|일"
               r"|세|살|배|가지|개|명|차|주일|시간|분")
# 한 글자 숫자는 일상어와 겹친다(이분·사회·오차·이건·일원). 붙여 쓴 단위를 줄이고 "이"는 띄어 쓰면 안 본다(이 일).
_SINO_UNITS_ONE = r"만\s?원|천\s?원|억\s?원|퍼센트|프로|%|킬로그램|킬로|kg|평|헥타르|톤|개월|년|월|일|세|살|배|개|명|주일|시간"
_SINO_UNITS_MULT = r"원|년|명|개|평|톤|배|일|세|살|퍼센트|프로|%|개월|킬로|kg"

_NATIVE_TENS = "열|스물|서른|마흔|쉰|예순|일흔|여든|아흔"
_NATIVE_ONES = "한|두|세|네|다섯|여섯|일곱|여덟|아홉"
_NATIVE = rf"(?:(?:{_NATIVE_TENS})\s?)?(?:{_NATIVE_ONES})|스무|{_NATIVE_TENS}"
_NATIVE_UNITS = ("가지|번째|번|개|명|분|해|달|살|배|마리|군데|곳|차례|주일|주|가마|상자|포대|평|장|권|시간|날"
                 "|그루|송이|단|줌")

_PRICE = "값|가격|시세|단가|경락가|시장가|도매가"
_CHANNEL = "상인|밭떼기|중간상|수집상|산지유통인|포전|농협|계통출하|계통|조합"

PATTERNS: dict[str, tuple[str, ...]] = {
    "NUM_DIGIT": (rf"[{_DIGITS}]+(?:[.,:][{_DIGITS}]+)*",),
    "NUM_SINO_UNIT": (
        rf"{_START}[{_SD}{_SM}]{{2,}}\s?(?:{_SINO_UNITS}){_END}",               # 오십만 원, 삼십 년, 칠십세
        rf"{_START}(?:[{_SD}]|[일삼사오육칠팔구]\s)(?:{_SINO_UNITS_ONE}){_END}",  # 삼월, 일 년
        rf"{_START}[{_SM}]\s?(?:{_SINO_UNITS_MULT}){_END}",                      # 만 원, 십 년
        rf"{_START}(?:유월|시월){_END}",
        rf"{_START}[{_SD}십]+\s?분의\s?[{_SD}십]+{_END}",                        # 삼분의 일
        # 단위 없는 금액(오십만 넘게, 삼십만이): 두 음절 이상이고 자릿수가 든 수사.
        # 일상어 이만(이만 줄이고)·천만(천만에요)·만사(만사 제쳐 두고)·천사는 뺀다(뒤에 수사가 이어지면 금액)
        rf"{_START}(?!(?:이만|천만|만사|천사)(?![{_SD}{_SM}]))(?:[{_SD}][{_SM}]|[{_SM}][{_SD}{_SM}])[{_SD}{_SM}]*{_END}",
    ),
    "NUM_NATIVE_UNIT": (
        rf"{_START}(?:{_NATIVE})\s?(?:{_NATIVE_UNITS}){_END}",
        rf"{_START}(?:이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름)(?!달){_END}",  # 수사+날이 한 낱말(하루는 관용어가 많아 뺌, 보름달은 통과)
    ),
    "NUM_WORD": (
        r"절반|반값|반액|전액|갑절|곱절|대부분",
        rf"{_START}(?:몇|수)\s?(?:십|백|천)|{_START}몇\s?(?:만|억)|{_START}수만\s?원|{_START}수억",
        r"(?:몇|여러)\s?배",
    ),
    # 미래·추측형 가격 전망. 낱말 자체가 전망인 것과 추측 어미(것·겁·거)가 붙은 동사형은 늘,
    # 그 밖의 동사형은 같은 문장에 값 낱말이 있을 때만("비가 내릴 때"는 통과).
    "FORECAST": (
        r"전망|오름세|내림세|상승세|하락세|반등|폭락|폭등|급등|급락",
        r"(?:오를|올라갈|내릴|내려갈|떨어질|하락할|상승할|뛸|좋아질|나빠질|회복될|회복할|안정될)(?=\s?(?:것|겁|거))",
    ),
    "FORECAST_PRICE": (_PRICE,),
    "FORECAST_VERB": (
        r"오를|오르겠|오르기\s?전|올라갈|올라가겠|내릴|내리겠|내리기\s?전|내려갈|내려가겠"
        r"|떨어질|떨어지겠|떨어지기\s?전|하락할|하락하겠|상승할|상승하겠|뛸|뛰겠|좋아질|좋아지겠|나빠질|나빠지겠"
        r"|회복될|회복되겠|회복할|안정될|예상됩니다|예상돼",
    ),
    # 단정. 부정·조건·단서는 단정이 아니다: 확정되지 않아·확정되면·확정 전·미확정·불확실·확실하지 않은.
    # prior 행에 시스템이 직접 찍는 단서(확정 전, 미확정)가 걸리면 안 된다. "보장"은 보험의 보장 내용(명사)과
    # 겹쳐 동사형만 본다.
    "CERTAINTY": (
        r"(?<![미불])(?:확정|확실)(?!(?:되|하)지\s?않|치\s?않|[이은]\s?아니|되기\s?전|되면|\s?전)"
        r"|반드시|틀림없|무조건|분명히|당연히|보장(?:됩니다|돼요|합니다|해\s?드립니다|해\s?드려요)",
    ),
    # 상인·농협 비교(§12-A (2)). 판로 낱말과 견주는 말이 함께 있어야 한다(G04는 판로 낱말만 있음).
    "COMPARE_CHANNEL": (_CHANNEL,),
    "COMPARE": (
        r"(?<=[가-힣])(?<![아어해])보다(?=[\s는도.,!?]|$)|비해|비하면|비교|낫|나은|나아요|유리|불리|이득|손해|이익"
        r"|더\s?(?:받|남|벌|많|좋|나|비싸|높|후하)|비싸게|후하게",
    ),
    # 받을 수 있·받게 되·지급되는 문장 어디서든(있으니·있는 돈·지급되니), 해당…은 문장 끝 모양만(해당되니는 통과).
    # 긴 끝 모양을 앞에 두어 span이 "받으실 수 있습니다"처럼 잘린다.
    "RIGHTS": (
        r"받(?:으실|을)\s?수\s?있(?:습니다|어요|으세요|으십니다)?"
        r"|받게\s?(?:됩니다|되십니다|돼요|될|되)|받으실\s?(?:겁니다|거예요|것입니다|것이)|받으십니다"
        r"|지급(?:됩니다|돼요|해\s?드립니다|해\s?드려요|되|돼)|대상(?:자)?(?:이십니다|이세요|입니다|이에요)"
        r"|자격이\s?(?:됩니다|되십니다|있으십니다|있습니다|돼요)|해당(?:되십니다|됩니다|돼요|하십니다)|권리",
    ),
    # 자리표시자 밖 제도명 합성어. 띄어 쓴 이름(어업인 지원금)은 못 잡는다(B31).
    "RAW_PROGRAM": (
        r"[가-힣A-Za-z]+(?:수당|연금|보험|지원사업|지원금|보조금|장려금|이용권|바우처|관리제|안정제|복구비)(?!료)",
        r"직불|자조금|바우처|이용권",
    ),
}

# 허용 목록: 검사 전에 "_"로 가린다. 앞 셋은 §6-2 그대로, 뒤는 한자어 수사 일상어(구현 보조).
# 모두 낱말 첫머리에서만 가린다. "열두 분"의 "두 분"은 허용이 아니다.
ALLOW: tuple[str, ...] = (
    rf"{_START}한\s?번(?=에|\s?더|\s?들르|\s?확인)",              # 한 번(에·더·들르·확인)
    rf"{_START}하나만",
    rf"{_START}두\s?분",
    r"(?<![가-힣A-Za-z])(?:재해보험|수입안정보험|안전보험)",        # 보험 범주어 3개(이름 앞에 붙으면 제도명)
    rf"{_START}직불\s?교육",
    rf"{_START}만일",
    rf"{_START}일일이",
)

PLACEHOLDER = r"\{P:([a-z][a-z0-9_]*)\}"
CITE = r"[A-Z]:[a-z][a-z0-9_]*"
PROGRAM_FACT_PREFIXES = ("M:", "I:")  # 정식 이름이 제도명인 근거(지원·보험). 행동(A:) 이름은 설명문이라 뺀다

_TABLES = {"max_sentences": MAX_SENTENCES, "max_chars": MAX_CHARS, "patterns": PATTERNS, "allow": ALLOW,
           "placeholder": PLACEHOLDER, "cite": CITE, "program_fact_prefixes": PROGRAM_FACT_PREFIXES}
RULES_VERSION = "rules-v1.0#" + hashlib.sha256(
    json.dumps(_TABLES, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]

_RX = {code: re.compile("|".join(f"(?:{p})" for p in pats)) for code, pats in PATTERNS.items()}
_ALLOW = re.compile("|".join(f"(?:{p})" for p in ALLOW))
_PLACEHOLDER = re.compile(PLACEHOLDER)
_CITE = re.compile(CITE)
_BAD_BRACE = re.compile(r"\{[^{}\s]*\}?|\}")
_SIMPLE_TEXT_RULES = ("NUM_DIGIT", "NUM_SINO_UNIT", "NUM_NATIVE_UNIT", "NUM_WORD")


# --- 검사 ------------------------------------------------------------------------------------

def parse_section(raw: str | bytes | Mapping[str, Any]) -> tuple[Section | None, list[Hit]]:
    """LLM이 낸 JSON 한 구획을 Section으로 읽는다. 읽을 수 없으면 (None, [SCHEMA 1건]).

    cites 키가 빠진 문장은 cites=None으로 통과시켜 check_rules가 문장 단위 SCHEMA로 잡게 한다.
    """
    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        return None, [Hit(rule="SCHEMA", sid=0, span="JSON을 읽을 수 없음")]
    try:
        return Section.model_validate(obj), []
    except ValidationError as e:
        where = ".".join(p for p in e.errors()[0]["loc"] if isinstance(p, str)) or "구획"  # 목록 번호(숫자)는 뺌
        return None, [Hit(rule="SCHEMA", sid=0, span=f"구조 오류: {where}")]


def check_rules(section: Section, context: NarrativeInput, sheet_program_ids: frozenset[str]) -> list[Hit]:
    """구획 하나에 R1~R6을 건다. 걸린 것이 없으면 []. 순서: sid → 규칙 순서(R1~R6) → 문장 안 위치."""
    fact_sections = {item.fact_id: item.section for item in context.items}
    names: dict[str, str] = {}
    for item in context.items:
        names.setdefault(item.program_id, item.official_name)
    program_names = tuple(dict.fromkeys(
        item.official_name for item in context.items if item.fact_id.startswith(PROGRAM_FACT_PREFIXES)))

    hits: list[Hit] = []
    n = len(section.sentences)
    if n == 0:
        hits.append(Hit(rule="SCHEMA", sid=0, span="문장 없음"))
    if n > MAX_SENTENCES:
        hits.append(Hit(rule="LENGTH", sid=0, span="문장 " + _count_words(n, "개")))
    seen: set[int] = set()
    for s in section.sentences:
        if s.sid in seen:
            hits.append(Hit(rule="SCHEMA", sid=s.sid, span="sid 중복"))
        seen.add(s.sid)
        hits += _check_text(s, names, program_names, sheet_program_ids)
        hits += _check_cites(s, section.section, fact_sections)

    unique = list(dict.fromkeys(hits))
    return sorted(unique, key=lambda h: (h.sid, RULE_ORDER.index(h.rule)))  # 안정 정렬: 같은 규칙은 위치 순


def _check_text(s: Sentence, names: dict[str, str], program_names: tuple[str, ...],
                sheet_program_ids: frozenset[str]) -> list[Hit]:
    out: list[Hit] = []

    def hit(rule: str, m: re.Match[str]) -> None:
        out.append(Hit(rule=rule, sid=s.sid, span=text[m.start():m.end()]))

    text = s.text
    if s.cites is None:
        out.append(Hit(rule="SCHEMA", sid=s.sid, span="cites 없음"))
    if not text.strip():
        out.append(Hit(rule="SCHEMA", sid=s.sid, span="빈 문장"))
        return out

    # R1: 자리표시자 형식, 인쇄 길이
    no_ph = _PLACEHOLDER.sub(lambda m: "가" * len(m[0]), text)
    for m in _BAD_BRACE.finditer(no_ph):
        hit("SCHEMA", m)
    printed = _PLACEHOLDER.sub(lambda m: names.get(m[1], m[0]), text).strip()
    if len(printed) > MAX_CHARS:
        out.append(Hit(rule="LENGTH", sid=s.sid, span=_count_words(len(printed), "자")))

    masked = _ALLOW.sub(lambda m: "_" * len(m[0]), no_ph)
    # R2
    for rule in _SIMPLE_TEXT_RULES:
        for m in _RX[rule].finditer(masked):
            hit(rule, m)
    # R3
    for m in _RX["FORECAST"].finditer(masked):
        hit("FORECAST", m)
    if _RX["FORECAST_PRICE"].search(masked):
        for m in _RX["FORECAST_VERB"].finditer(masked):
            hit("FORECAST", m)
    for m in _RX["CERTAINTY"].finditer(masked):
        hit("CERTAINTY", m)
    if _RX["COMPARE_CHANNEL"].search(masked):
        for m in _RX["COMPARE"].finditer(masked):
            hit("COMPARE", m)
    # R4
    for m in _RX["RIGHTS"].finditer(masked):
        hit("RIGHTS", m)
    # R5: 합성어 + 이 상담의 정식 이름(띄어쓰기 무시)이 자리표시자 밖에 나오면
    for m in _RX["RAW_PROGRAM"].finditer(masked):
        hit("RAW_PROGRAM", m)
    for name in program_names:
        core = re.sub(r"\s+", "", re.sub(r"\(.*?\)|\[.*?\]", "", name))
        if len(core) >= 3 and (m := re.search(r"\s*".join(map(re.escape, core)), no_ph)):
            hit("RAW_PROGRAM", m)
    for m in _PLACEHOLDER.finditer(text):
        if m[1] not in sheet_program_ids:
            hit("NOT_IN_SHEET", m)
    return out


def _check_cites(s: Sentence, kind: str, fact_sections: dict[str, str]) -> list[Hit]:
    """R6: 인용이 있고, 형식이 맞고, 이 상담의 근거이고, 적어도 하나는 이 구획 근거여야 한다."""
    if s.cites is None:
        return []                               # cites 키 없음은 SCHEMA로 이미 잡음
    if not s.cites:
        return [Hit(rule="NO_CITE", sid=s.sid, span="인용 없음")]
    out, valid = [], []
    for c in s.cites:
        if _CITE.fullmatch(c) and c in fact_sections:
            valid.append(c)
        else:
            out.append(Hit(rule="BAD_CITE", sid=s.sid, span=c))
    if valid and all(fact_sections[c] != kind for c in valid):
        out.append(Hit(rule="BAD_CITE", sid=s.sid, span="다른 구획 근거만 인용: " + ", ".join(valid)))
    return out
