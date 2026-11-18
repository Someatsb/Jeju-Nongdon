"""공고 초안 검사 8종(Task 18) — research/dept/round1-B-data.md §3-4, round2-C-agent.md §6-1. LLM 없이 결정적.

 1 인용        칸마다 인용이 있고 원문의 부분 문자열인가(공백·전각·물결·가운뎃점 정규화 후)   QUOTE_MISSING·QUOTE_NOT_IN_DOC (빨강)
 2 값·단위     숫자·날짜 값이 인용 속 숫자와 단위 환산 후 같은가(평은 0.5% 오차)             VALUE_NOT_IN_QUOTE (빨강)
 3 칸 규칙     알려진 칸이고 허용값·범위·형식에 맞는가, 법인·단체 신청 주체                 UNKNOWN_FIELD·BAD_ENUM·OUT_OF_RANGE·BAD_VALUE (빨강), NOT_INDIVIDUAL (노랑)
 4 순서        시작 ≤ 끝(날짜, 나이, 면적, 보조율, 금액)                                     OUT_OF_ORDER (빨강)
 5 기존 행     match_id·program_key가 표에 있는가, NEW의 키가 이미 쓰이지 않는가              UNKNOWN_PROGRAM (빨강), NEW_KEY_EXISTS (노랑)
 6 개인정보    칸 값·인용·질문·넣지 않은 사업에 휴대전화·주민번호·메일이 없는가               PII_IN_DRAFT (빨강)
 7 필수 칸     새 사업의 필수 칸, 작년 기준 행의 확인 예정 월                                MISSING_REQUIRED (노랑)
 8 가점 혼동   자격 칸(needs_·min_·max_)의 인용이 가점·심사·평가 항목인가                    BONUS_AS_ELIGIBILITY (노랑)
 9 태그        이름표(tags)마다 이름이 있고 너무 길지 않고 개인정보가 없고, 누가 받을 수 있는지에 관한 조건이고(날짜·장소·금액 모양이 아니고),
               근거 문장이 원문의 부분 문자열인가
               TAG_EMPTY·TAG_TOO_LONG·TAG_NOT_CONDITION·TAG_QUOTE_MISSING·TAG_QUOTE_NOT_IN_DOC·PII_IN_DRAFT (빨강). 칸 이름은 "tags.순번"(0부터)

값이 비어 있는 칸(None·빈 글·빈 목록)은 "없음"으로 보고 검사하지 않는다. 접수처 칸(office)에 "없음"이라고 적은 것도 같다(공고에 접수처가 없다는 뜻). 사업 순번은 0부터.
"""
import difflib
import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Annotated, Any, Literal, Protocol, get_args, get_origin

from pydantic import TypeAdapter, ValidationError

from app.core.models import Program
from app.data_layer.docs_in import Doc
from app.tools.models import DraftField, DraftIssue, DraftProgram, DraftTag, Level, NoticeDraft


class ProgramLike(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def program_key(self) -> str: ...
    @property
    def name(self) -> str | None: ...


class ProgramBundle(Protocol):
    """표 묶음. TableBundle이나 supports_index.ProgramIndex가 맞는다."""

    @property
    def programs(self) -> Sequence[ProgramLike]: ...


# --- 글 정규화·개인정보 -----------------------------------------------------------------------

_TILDES = str.maketrans({"∼": "~", "～": "~", "〜": "~"})
_DOTS = str.maketrans({c: "·" for c in "‧ㆍ・•∙"})
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def squash(text: str) -> str:
    """인용 비교용 정규화: 전각→반각, 물결·가운뎃점·따옴표 통일, 공백 제거."""
    t = unicodedata.normalize("NFKC", text).translate(_TILDES).translate(_DOTS).translate(_QUOTES)
    return "".join(ch for ch in t if not ch.isspace()).casefold()


_PII = (
    ("phone", re.compile(r"(?<!\d)01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")),   # 휴대전화. 기관 대표 전화는 해당 없음
    ("rrn", re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
)


def pii_labels(text: str) -> tuple[str, ...]:
    return tuple(label for label, rx in _PII if rx.search(text))


# --- 칸 규칙 ---------------------------------------------------------------------------------

@cache
def _adapter(name: str) -> TypeAdapter:
    info = Program.model_fields[name]
    return TypeAdapter(Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation)


def _literals(annotation: Any) -> list[str]:
    if get_origin(annotation) is Literal:
        return [str(v) for v in get_args(annotation)]
    return [c for arg in get_args(annotation) for c in _literals(arg)]


_RANGE_ERRORS = {"greater_than", "greater_than_equal", "less_than", "less_than_equal", "string_too_long", "too_long"}


def _absent(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == ()


# --- 값·단위 환산 ----------------------------------------------------------------------------

_MONEY = {"원": 1, "천원": 1_000, "만원": 10_000, "백만원": 1_000_000, "천만원": 10_000_000, "억원": 100_000_000}
_AREA_HA = {"ha": 1.0, "㏊": 1.0, "㎡": 1e-4, "m2": 1e-4, "m²": 1e-4, "a": 1e-2, "평": 400 / 121 * 1e-4}
_NUM = re.compile(r"(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)[ ]?"
                  r"(?P<u>백만원|천만원|억원|만원|천원|원|㎡|m2|m²|ha|㏊|평|a(?![A-Za-z])|%)?")
_MONEY_FIELDS = {"cap_won", "amount_value", "amount_min", "amount_max", "amount_2plus_each"}
_MANWON_FIELDS = {"income_max_manwon"}
_HA_FIELDS = {"min_ha", "max_ha", "max_owned_ha"}
_PCT_FIELDS = {"rate_pct_min", "rate_pct_max"}
_UNIT_FIELDS = _MONEY_FIELDS | _MANWON_FIELDS | _HA_FIELDS | _PCT_FIELDS
AREA_TOL = 0.005   # 평 환산은 정확하지 않아서


def _candidates(name: str, quote: str) -> list[tuple[float, float]]:
    """(값, 허용 상대 오차). 단위가 붙은 숫자는 그 칸의 단위로 환산한 값만, 단위가 없거나 모르는 단위(kg·포·대)는 그대로."""
    out: list[tuple[float, float]] = []
    for m in _NUM.finditer(unicodedata.normalize("NFKC", quote)):
        n, unit = float(m["n"].replace(",", "")), m["u"]
        if unit is None:
            out.append((n, 0.0))
        elif name in _MONEY_FIELDS and unit in _MONEY:
            out.append((n * _MONEY[unit], 0.0))
        elif name in _MANWON_FIELDS and unit in _MONEY:
            out.append((n * _MONEY[unit] / 10_000, 0.0))
        elif name in _HA_FIELDS and unit in _AREA_HA:
            out.append((n * _AREA_HA[unit], AREA_TOL if unit == "평" else 0.0))
        elif name in _PCT_FIELDS and unit == "%":
            out.append((n, 0.0))
        elif name not in _UNIT_FIELDS and unit not in _MONEY and unit not in _AREA_HA:
            out.append((n, 0.0))
        # 다른 종류의 단위(예: 금액 칸 옆의 70%)는 후보가 아니다
    return out


_DATE = re.compile(r"(?:(?P<y>\d{4}|['’‘]\d{2})\s*[.\-년]\s*)?(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[.일]?")


def _dates(quote: str) -> set[date]:
    """'2026. 1. 2.(금)'·'2026-01-02'·"'26. 1. 2."류를 읽는다. 연도 없는 뒤쪽 날짜('1. 16.')는 앞 날짜의 해를 쓴다."""
    found: set[date] = set()
    year: int | None = None
    for m in _DATE.finditer(unicodedata.normalize("NFKC", quote)):
        if m["y"]:
            year = int(m["y"][-2:]) + 2000 if m["y"][0] in "'’‘" else int(m["y"])
        if year is None:
            continue
        try:
            found.add(date(year, int(m["m"]), int(m["d"])))
        except ValueError:
            continue
    return found


def _value_matches(name: str, parsed: Any, quote: str) -> bool | None:
    """None이면 이 칸은 값-인용 대조 대상이 아니다(글·선택값)."""
    if isinstance(parsed, date):
        return parsed in _dates(quote)
    if isinstance(parsed, bool) or not isinstance(parsed, (int, float, Decimal)):
        return None
    v = float(parsed)
    return any(abs(v - c) <= max(tol * abs(c), 1e-9) for c, tol in _candidates(name, quote))


# --- 검사 ------------------------------------------------------------------------------------

_PAIRS = (("apply_start", "apply_end"), ("valid_from", "valid_to"), ("min_age", "max_age"), ("min_ha", "max_ha"),
          ("rate_pct_min", "rate_pct_max"), ("amount_min", "amount_max"))
_NEW_REQUIRED = ("program_key", "name", "agency", "applicant", "apply_cycle", "amount_type", "valid_from", "valid_to")
_BONUS = re.compile(r"가점|배점|심사|평가|우선순위|\d\s*점")
_ELIGIBILITY_PREFIX = ("needs_", "min_", "max_")


TAG_MAX_LABEL = 20      # 이름표는 열두 글자 안팎의 쉬운 말. 이보다 길면 설명문이므로 돌려보낸다
NONE_WORD = "없음"       # 접수처를 공고에서 못 찾았다는 뜻으로 office 칸에 적는 값

# 이름표는 누가 받을 수 있는지에 관한 조건만이다. 날짜·장소·지원 금액 모양은 조건이 아니므로 코드가 떨어뜨린다.
_TAG_DATE = re.compile(r"\d{4}\s*년|\d{1,2}\s*월|\d{1,2}\s*\.\s*\d{1,2}\s*\.|(?:신청|접수)\s*기간|기한")
_TAG_PLACE = re.compile(r"접수\s*처|접수\s*장소|신청\s*장소|신청\s*처|신청\s*방법|제출\s*처|문의|담당\s*부서|방문\s*접수|우편\s*접수|전화")
_TAG_MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:[억천백만]\s*)*원|/\s*(?:kg|㎏|20kg|포|10a|ha)|\d\s*(?:kg|㎏)\s*당")
_TAG_RULE_WORD = re.compile(r"이상|미만|초과|소득|매출|재산|자산|제한|자격")    # 숫자가 있어도 자격 기준이면 조건이다("농외소득 3,700만원 미만"). '최대 5천만 원'·'1,000만원 이내'·'1억원 이하'는 지원 한도라 조건이 아니다


def not_a_condition(label: str) -> bool:
    """이름표가 조건이 아닌 날짜·장소·금액 모양인가(코드가 떨어뜨리는 것)."""
    if _TAG_DATE.search(label) or _TAG_PLACE.search(label):
        return True
    return bool(_TAG_MONEY.search(label)) and not _TAG_RULE_WORD.search(label)


def tag_problem(tag: DraftTag, doc_squashed: str) -> tuple[str, str] | None:
    """이름표 하나의 문제(코드, 한국어 안내). 문제가 없으면 None. doc_squashed는 squash(doc.text)."""
    label = tag.label.strip()
    if not label:
        return "TAG_EMPTY", "이름표 글이 비어 있습니다"
    if len(label) > TAG_MAX_LABEL:
        return "TAG_TOO_LONG", f"이름표가 너무 깁니다({len(label)}글자). 열두 글자 안팎의 쉬운 말로 줄여 주세요"
    if pii_labels(label) or pii_labels(tag.quote or ""):
        return "PII_IN_DRAFT", "이름표나 근거 문장에 전화번호·주민번호·메일 같은 개인정보가 있습니다. 지우고 다시 만들어 주세요"
    if not_a_condition(label):
        return "TAG_NOT_CONDITION", "이름표는 누가 받을 수 있는지에 관한 조건만 냅니다. 날짜·장소·금액은 이름표로 내지 말고 그 칸에 적어 주세요. 이 이름표는 빼 주세요"
    quote = squash(tag.quote or "")
    if not quote:
        return "TAG_QUOTE_MISSING", "이름표의 근거 문장이 없습니다. 공고 원문의 문장을 그대로 인용해 주세요"
    if quote not in doc_squashed:
        return "TAG_QUOTE_NOT_IN_DOC", "이름표의 근거 문장이 원문에 없습니다. 원문의 문장을 그대로 옮겨 주세요"
    return None


def strip_bad_tags(draft: NoticeDraft, doc: Doc) -> tuple[NoticeDraft, tuple[str, ...]]:
    """근거 대조에 끝까지 못 맞은 이름표를 뺀 초안과, 뺀 이름표의 글을 돌려준다."""
    doc_squashed = squash(doc.text)
    dropped: list[str] = []
    programs = []
    for p in draft.programs:
        keep = tuple(t for t in p.tags if tag_problem(t, doc_squashed) is None)
        dropped += [t.label for t in p.tags if t not in keep]
        programs.append(p.model_copy(update={"tags": keep}) if len(keep) != len(p.tags) else p)
    return (draft.model_copy(update={"programs": tuple(programs)}) if dropped else draft), tuple(dropped)


class _Issues:
    def __init__(self) -> None:
        self.items: list[DraftIssue] = []

    def add(self, program: int | None, field: str, level: Level, code: str, message: str) -> None:
        self.items.append(DraftIssue(program=program, field=field, level=level, code=code, message=message))


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _check_field(out: _Issues, i: int, name: str, f: DraftField, doc_squashed: str) -> Any:
    """칸 하나의 검사 1·2·3·8. 형식에 맞게 읽은 값을 돌려준다(못 읽으면 None)."""
    if name not in Program.model_fields:
        out.add(i, name, "RED", "UNKNOWN_FIELD", f"표에 없는 칸 이름입니다: {name}")
        return None
    parsed: Any = None
    try:
        parsed = _adapter(name).validate_python(f.value)
    except ValidationError as exc:
        err = exc.errors()[0]
        if err["type"] == "literal_error":
            near = difflib.get_close_matches(str(f.value), _literals(Program.model_fields[name].annotation), n=1, cutoff=0.5)
            hint = f" 가까운 값: {near[0]}" if near else ""
            out.add(i, name, "RED", "BAD_ENUM", f"허용된 값이 아닙니다: {f.value}.{hint}")
        elif err["type"] in _RANGE_ERRORS:
            out.add(i, name, "RED", "OUT_OF_RANGE", f"허용 범위를 벗어났습니다: {f.value}")
        else:
            out.add(i, name, "RED", "BAD_VALUE", f"값의 형식이 맞지 않습니다: {f.value}. 날짜는 연-월-일 형식으로 적어 주세요")
    if name == "applicant" and parsed == "법인·단체":
        out.add(i, name, "YELLOW", "NOT_INDIVIDUAL", "개인 대상 사업이 아닙니다. 표에 넣지 않는 것을 권합니다")

    quote = f.quote or ""
    if not squash(quote):
        out.add(i, name, "RED", "QUOTE_MISSING", "근거 문장이 없습니다. 공고 원문의 문장을 그대로 인용해 주세요")
        return parsed
    if squash(quote) not in doc_squashed:
        out.add(i, name, "RED", "QUOTE_NOT_IN_DOC", "근거 문장이 원문에 없습니다. 원문의 문장을 그대로 옮겨 주세요")
    elif _value_matches(name, parsed if parsed is not None else f.value, quote) is False:   # 범위 밖이어도 값-인용 대조는 한다
        out.add(i, name, "RED", "VALUE_NOT_IN_QUOTE", f"값 {f.value}이(가) 근거 문장의 숫자와 단위를 환산해도 맞지 않습니다")
    if name.startswith(_ELIGIBILITY_PREFIX) and _BONUS.search(quote):
        out.add(i, name, "YELLOW", "BONUS_AS_ELIGIBILITY", "가점·심사 항목을 자격 조건으로 넣은 것 아닌가요? 직원이 확인해 주세요")
    return parsed


def _check_program(out: _Issues, i: int, p: DraftProgram, doc_squashed: str, bundle: ProgramBundle) -> None:
    present = {k: f for k, f in p.fields.items() if not _absent(f.value) and not (k == "office" and str(f.value).strip() == NONE_WORD)}
    parsed = {k: _check_field(out, i, k, f, doc_squashed) for k, f in present.items()}

    for lo, hi in _PAIRS:                                                            # 4 순서
        if parsed.get(lo) is not None and parsed.get(hi) is not None and parsed[lo] > parsed[hi]:
            out.add(i, hi, "RED", "OUT_OF_ORDER", f"{hi}이(가) {lo}보다 앞섭니다")
    for k, v in parsed.items():
        if isinstance(v, date) and not 2000 <= v.year <= 2100:
            out.add(i, k, "RED", "OUT_OF_RANGE", f"연도가 이상합니다: {v.year}")

    rows = {r.id: r for r in bundle.programs}                                        # 5 기존 행
    keys = {r.program_key for r in bundle.programs}
    if p.action == "NEW":
        if p.program_key in keys:
            out.add(i, "program_key", "YELLOW", "NEW_KEY_EXISTS", "새 사업이라고 했지만 같은 사업 키가 이미 표에 있습니다. 갱신이 아닌가요?")
        for req in _NEW_REQUIRED:                                                    # 7 필수 칸
            if not (p.program_key if req == "program_key" else req in present):
                out.add(i, req, "YELLOW", "MISSING_REQUIRED", f"새 사업에 필요한 칸이 비어 있습니다: {req}. 직원 입력이 필요합니다")
    else:
        row = rows.get(p.match_id or "")
        if row is None:
            out.add(i, "match_id", "RED", "UNKNOWN_PROGRAM", f"표에 없는 사업입니다: {p.match_id}. find_existing_program으로 찾아 주세요")
        elif p.program_key and p.program_key != row.program_key:
            out.add(i, "program_key", "RED", "UNKNOWN_PROGRAM", f"program_key가 match_id 행의 키({row.program_key})와 다릅니다")
    if parsed.get("status") == "prior_year_reference" and "expected_notice_month" not in present:
        out.add(i, "expected_notice_month", "YELLOW", "MISSING_REQUIRED", "올해 공고가 아닌 작년 기준 행은 다음 공고 예정 월이 필요합니다")

    texts = [(k, t) for k, f in present.items() for t in _strings(f.value) + [f.quote or ""]]   # 6 개인정보
    texts += [("questions", q) for q in p.questions]
    for k in dict.fromkeys(k for k, t in texts if pii_labels(t)):
        out.add(i, k, "RED", "PII_IN_DRAFT", "초안에 전화번호·주민번호·메일 같은 개인정보가 있습니다. 지우고 다시 만들어 주세요")


def _check_tags(out: _Issues, i: int, p: DraftProgram, doc_squashed: str) -> None:
    for j, tag in enumerate(p.tags):                                                 # 9 태그
        if (bad := tag_problem(tag, doc_squashed)) is not None:
            out.add(i, f"tags.{j}", "RED", *bad)


def run(draft: NoticeDraft, doc: Doc, bundle: ProgramBundle) -> list[DraftIssue]:
    out = _Issues()
    doc_squashed = squash(doc.text)
    for i, p in enumerate(draft.programs):
        _check_program(out, i, p, doc_squashed, bundle)
        _check_tags(out, i, p, doc_squashed)
    if any(pii_labels(f"{s.title} {s.reason}") for s in draft.skipped):
        out.add(None, "skipped", "RED", "PII_IN_DRAFT", "넣지 않은 사업 설명에 개인정보가 있습니다. 지워 주세요")
    return out.items
