"""새 공고 맞춰 보기 도구 둘(설계서 2026-11-14 1-2) — check_farmer, submit_matches.

MatchTools(profile, notices, crops, as_of) 한 개가 상담 한 건을 맡는다(전역 상태 없음. 여러 상담이 동시에 돌아도 서로 모른다).

- check_farmer: AI 가 공고가 따지는 조건을 하나씩 묻는다. 돌려주는 것은 "예" / "아니오" / "답에 없음" 셋뿐이다.
  어르신 값(나이·넓이·읍면동 …)은 이 모듈 밖으로 나가는 길이 없다. 읍면동은 묻지 못한다(종류 "그 밖"은 항상 "답에 없음").
  인용(quote)은 그 공고 글에 글자 그대로 있어야 하고, 숫자 기준은 그 숫자가 인용에 있어야 한다.
  한 공고 6번, 전체 24번까지. 같은 공고에 같은 종류를 기준값만 바꿔 3번째 물으면 거절한다(값을 좁혀 알아내는 것을 막는다).
  숫자 기준은 인용 안에서 그 종류의 낱말 바로 앞에 있어야 한다(나이는 '세' 앞, 넓이는 쓴 단위 앞, 햇수는 '년' 앞. 날짜 숫자를 나이로 쓸 수 없다).
  같은 종류 묶음(나이 이상·이하 등)의 숫자 질문은 공고를 합쳐 10가지까지. 인용은 그 종류를 실제로 말하는 글이어야 한다(경영체·소유 등).
- submit_matches: 공고마다 왜 맞을 수 있는지 한 문장(why)과 창구에서 물어볼 것(ask). 프로그램이 글을 검사한다
  (숫자는 그 공고 인용의 숫자만, 단정 낱말 금지, 금액 새로 쓰기 금지, 영어·코드 금지, 길이). 걸리면 이유를 돌려 한 번 다시 쓰게 하고,
  또 걸리면 그 공고만 프로그램의 기본 문장을 쓴다. 첫 제출에서 통과한 공고의 글은 보관해 둘째 제출과 합친다(둘째 우선).
  확인이 하나도 없으면 받지 않는다. 판정이 알 수 없음인 공고의 이유 글은 늘 프로그램의 기본 문장이다(ask 만 AI 글).
  맞을 수 있음인 공고의 이유 글이 '예'로 확인하지 않은 조건을 말하면 걸린다.
- 판정은 확인 기록에서 프로그램이 계산한다(verdict_of). AI 가 쓴 글은 판정을 바꾸지 못한다.
도구 입력 모델의 설명에는 숫자를 쓰지 않는다(registry.register 가 막는다).
"""
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import Field

from app.catalog.notices import NoticeRecord
from app.core.match import _CITY_OF_EUPMYEON
from app.core.models import CoreModel, FarmProfile
from app.core.tables_models import Crop
from app.tools.draft_checks import squash
from app.tools.registry import ToolError, ToolRegistry

YES, NO, UNKNOWN = "예", "아니오", "답에 없음"
FIT, MAYBE_UNKNOWN, NOT_FIT = "맞을 수 있음", "알 수 없음", "안 맞음"
MAX_PER_NOTICE = 6
MAX_TOTAL = 24
MAX_VALUES_PER_KIND = 2          # 같은 공고·같은 종류에서 서로 다른 기준값은 둘까지(셋째는 거절)
MAX_NUMERIC_PER_FAMILY = 10      # 같은 종류 묶음(나이 이상·이하 등)의 서로 다른 숫자 질문은 공고를 합쳐 열 가지까지
MIN_QUOTE = 4
MAX_WHY = 80
MAX_ASK = 50
MAX_ASKS = 2
PYEONG_M2 = 3.3058

KindName = Literal["작물", "행정시", "나이 이상", "나이 이하", "성별", "넓이 이상", "넓이 이하", "농사 햇수 이상",
                   "제주 거주 햇수 이상", "경영체 등록", "농협 출하", "배우자 공동 영농", "건강보험 종류",
                   "최근 재해 피해", "땅 소유", "그 밖"]
SHORT_KIND = {"작물": "작물", "행정시": "지역", "나이 이상": "나이", "나이 이하": "나이", "성별": "성별", "넓이 이상": "농사짓는 땅 넓이",
              "넓이 이하": "농사짓는 땅 넓이", "농사 햇수 이상": "농사 햇수", "제주 거주 햇수 이상": "제주 거주", "경영체 등록": "경영체 등록",
              "농협 출하": "농협 출하", "배우자 공동 영농": "배우자", "건강보험 종류": "건강보험", "최근 재해 피해": "재해 피해",
              "땅 소유": "땅 소유", "그 밖": "그 밖"}
_NUMERIC = frozenset({"나이 이상", "나이 이하", "넓이 이상", "넓이 이하", "농사 햇수 이상", "제주 거주 햇수 이상"})
_CHOICES = {"행정시": ("제주시", "서귀포시"), "성별": ("여성", "남성"), "건강보험 종류": ("지역", "직장", "피부양자")}
_CHOICE_STEM = {"제주시": "제주", "서귀포시": "서귀포", "여성": "여", "남성": "남", "지역": "지역", "직장": "직장", "피부양자": "피부양자"}
_CROP_STOP = frozenset({"기타", "작물", "농작물", "농산물", "일반", "전체", "모든"})

# 단정으로 읽히는 낱말. 이 앱은 맞을 수 있다고만 말하고 받는다고 하지 않는다.
ASSERT_WORDS = ("받으실수있습니다", "받을수있습니다", "받습니다", "받게됩니다", "받으십니다", "대상입니다", "대상이에요", "대상이세요",
                "확정", "틀림없", "반드시", "무조건", "보장", "지급됩니다", "지원됩니다", "해당됩니다", "전액", "무료", "공짜",
                # 해요체 단정(글자 사이 공백은 지우고 비교한다)
                "꼭", "받을수있", "받으실수있", "받아요", "받으세요", "받으십", "받게돼", "받게되", "받을거", "받으실거", "받는다",
                "나와요", "나옵니다", "나올거", "지원해요", "지원돼요", "지원되요", "지원합니다", "지원해드", "지원해줘", "지원해주",
                "지급돼요", "지급되요", "지급해요", "지급합니다", "해당돼요", "해당되요", "해당합니다", "해당해요", "드려요", "드립니다",
                "줘요", "줍니다")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MONEY = re.compile(r"(?:\d[\d,]*(?:\.\d+)?|(?<![가-힣])[일이삼사오육칠팔구십백천만억]+)\s*(?:만\s*)?원|\d[\d,]*(?:\.\d+)?\s*%|(?<![가-힣])억"
                    r"|[일이삼사오육칠팔구십백천]*[십백천]\s*만\s*원|[일이삼사오육칠팔구]\s*만\s*원|수[십백천]?[만억]\s*원?|수천만")
_HANGUL_NUM = re.compile(r"(?:스물|서른|마흔|쉰|예순|일흔|여든|아흔)(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?"
                         r"|(?<![가-힣])(?:열(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?|한|두|세|네|다섯|여섯|일곱|여덟|아홉)\s*살"
                         r"|(?<![가-힣])[일이삼사오육칠팔구십백천]{1,4}\s*(?:세|살|평|년|헥타르)(?![가-힣])")
# 숫자 기준이 그 종류의 낱말 바로 앞에 있는지 보는 글꼴(NFKC 로 바꾼 인용에서 찾는다)
_NEAR_SUFFIX = {"나이": r"(?:세(?!대)|살)", "농사 햇수": r"년(?!도)", "제주 거주": r"년(?!도)"}
_UNIT_SUFFIX = {"평": r"평", "㎡": r"(?:m2|제곱미터)", "ha": r"(?:ha|헥타르)(?![a-z])"}
_NUM_AT = r"(?<![\d,.])(\d[\d,]*(?:\.\d+)?)\s*"
# 인용이 그 종류를 실제로 말하는 글인지 보는 낱말(공백을 지운 인용에서 하나라도 있어야 한다)
KIND_WORDS = {"경영체 등록": ("경영체",), "농협 출하": ("농협", "조합", "출하"), "배우자 공동 영농": ("배우자", "부부"),
              "땅 소유": ("소유", "자가", "내땅", "자기땅", "임차", "임대"), "제주 거주 햇수 이상": ("거주", "주소", "도민"),
              "농사 햇수 이상": ("농", "경력", "재배"), "최근 재해 피해": ("재해", "피해")}
# 맞을 수 있음 글이 '예'로 확인하지 않고 말하면 안 되는 조건 이름
CLAIM_WORDS = {"지역": ("제주시", "서귀포시"), "나이": ("나이", "세이상", "세이하"), "성별": ("여성", "남성", "성별"),
               "농사짓는 땅 넓이": ("넓이", "평수", "면적"), "농사 햇수": ("햇수", "농사경력", "영농경력"), "제주 거주": ("거주",),
               "경영체 등록": ("경영체",), "농협 출하": ("출하",), "배우자": ("배우자",), "건강보험": ("건강보험",),
               "재해 피해": ("재해",), "땅 소유": ("땅소유", "자기땅", "내땅", "소유")}
_LATIN = re.compile(r"[A-Za-z]+")
_CODEISH = re.compile(r"[_{}<>\[\]\\|]")


# --- 도구 입력·출력 --------------------------------------------------------------------------

class CheckFarmerIn(CoreModel):
    """공고가 내건 조건 하나가 이 어르신 답에 맞는지 묻는다. 돌아오는 것은 예, 아니오, 답에 없음 셋 중 하나뿐이다.
    조건을 그 공고 글에서 그대로 옮긴 인용 한 줄과 함께 묻는다. 공고가 말하지 않은 조건은 묻지 않는다.
    읍면동이나 답으로 받지 않는 조건(인증, 소득, 사업 계획 등)은 종류를 그 밖으로 내면 답에 없음이 돌아온다."""

    notice_key: str = Field(description="공고 열쇠. 공고 목록에 적힌 그대로")
    kind: KindName = Field(description="조건 종류. 작물, 행정시, 나이, 성별, 농사짓는 땅 넓이, 농사 햇수, 제주 거주 햇수, 경영체 등록, 농협 출하, "
                                       "배우자 공동 영농, 건강보험 종류, 최근 재해 피해, 땅 소유 중 하나. 이 밖의 조건은 그 밖")
    quote: str = Field(description="그 조건이 적힌 공고 글을 한 글자도 바꾸지 않고 옮긴 한 줄")
    crops: tuple[str, ...] = Field(default=(), description="종류가 작물일 때만. 공고가 말한 작물 낱말을 인용에 나온 그대로 모두")
    number: float | None = Field(default=None, description="종류가 나이, 넓이, 햇수일 때만. 공고가 적은 기준 숫자(인용에 있는 숫자)")
    unit: Literal["평", "㎡", "ha"] | None = Field(default=None, description="종류가 넓이일 때만. 공고가 쓴 단위")
    choice: str | None = Field(default=None, description="종류가 행정시, 성별, 건강보험 종류일 때만. 행정시는 제주시나 서귀포시, "
                                                        "성별은 여성이나 남성, 건강보험은 지역, 직장, 피부양자 중 공고가 말한 것")


class CheckFarmerOut(CoreModel):
    """확인 결과."""

    answer: Literal["예", "아니오", "답에 없음"]


class SubmitItem(CoreModel):
    """공고 하나의 결과 글."""

    notice_key: str = Field(description="공고 열쇠")
    why: str = Field(description="왜 맞을 수 있는지 쉬운 해요체 한 문장. 단정하지 않는다")
    ask: tuple[str, ...] = Field(default=(), description="창구에서 물어볼 것. 없거나 둘까지. 짧은 해요체")


class SubmitMatchesIn(CoreModel):
    """확인을 마친 뒤 공고마다 결과 글을 한꺼번에 낸다. 한 번만 낸다. 프로그램이 글을 검사해 걸리면 이유를 돌려주니 고쳐서 다시 낸다."""

    items: tuple[SubmitItem, ...] = Field(min_length=1, description="공고마다 한 항목")


class SubmitMatchesOut(CoreModel):
    """접수 결과."""

    accepted: bool
    message: str


@dataclass(frozen=True)
class CheckRecord:
    notice_key: str
    kind: str
    quote: str
    answer: str
    sig: tuple


def verdict_of(checks: Sequence[CheckRecord]) -> str:
    """확인 기록에서 판정을 계산한다. 아니오가 하나라도 있으면 안 맞음.
    맞을 수 있음은 예가 하나 이상이고 아니오도 답에 없음도 없을 때만이다(설계서 4절). 그 밖(답에 없음이 있거나 확인이 없음)은 알 수 없음."""
    answers = {c.answer for c in checks}
    if NO in answers:
        return NOT_FIT
    return FIT if YES in answers and UNKNOWN not in answers else MAYBE_UNKNOWN


# 어르신 값으로 답할 수 없는 핵심 조건 낱말. 공고 이름·대상·이름표에 이 낱말이 있는데 "그 밖"으로 한 번도 묻지 않았으면
# AI 가 그 조건을 빠뜨린 것이니 맞을 수 있음으로 올리지 않는다(내리기만 하고 올리지는 않는다).
CORE_CONDITION_WORDS = ("출산", "임신", "산모", "인증", "창업", "귀농", "귀촌", "후계", "장애", "기초생활", "차상위", "다문화",
                        "소득", "토양검정", "교육이수", "수료")


def verdict_with_notice(n: NoticeRecord, checks: Sequence[CheckRecord]) -> str:
    """verdict_of 에 공고 글을 더해 본 판정. 핵심 조건 낱말이 있는데 그 밖 확인이 없으면 맞을 수 있음을 알 수 없음으로 내린다."""
    verdict = verdict_of(checks)
    if verdict == FIT and not any(c.kind == "그 밖" for c in checks):
        text = unicodedata.normalize("NFKC", "\n".join([n.name, n.target, *(t.quote for t in n.tags)]))
        if any(w in text for w in CORE_CONDITION_WORDS):
            return MAYBE_UNKNOWN
    return verdict


def default_why(verdict: str, checks: Sequence[CheckRecord]) -> str:
    """AI 글이 검사에 끝까지 걸렸을 때의 프로그램 문장. 숫자·금액이 없다."""
    if verdict == FIT:
        labels: list[str] = []
        for c in checks:
            if c.answer == YES and SHORT_KIND[c.kind] not in labels:
                labels.append(SHORT_KIND[c.kind])
        return f"{'·'.join(labels[:3])} 조건에 맞아요. 나머지는 창구에서 확인하세요"
    if verdict == NOT_FIT:
        return "조건이 맞지 않아요"
    return "맞는지 아직 알 수 없어요. 조건은 창구에서 확인하세요"


# --- 글 다루기 -------------------------------------------------------------------------------

def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUM.findall(unicodedata.normalize("NFKC", text)):
        try:
            out.add(float(m.rstrip(",").replace(",", "")))
        except ValueError:
            continue
    return out


def number_is_beside_word(kind: str, number: float, unit: str | None, quote: str) -> bool:
    """숫자 기준이 인용 안에서 그 종류의 낱말(세·년·쓴 단위) 바로 앞에 있는가. 날짜 숫자를 나이나 넓이로 쓰는 것을 막는다."""
    text = unicodedata.normalize("NFKC", quote).casefold()
    family = SHORT_KIND[kind]
    suffix = _UNIT_SUFFIX[unit] if family == "농사짓는 땅 넓이" else _NEAR_SUFFIX[family]
    for m in re.finditer(_NUM_AT + suffix, text):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if value == number and (family == "농사짓는 땅 넓이" or value <= 130):
            return True
    return False


def notice_corpus(n: NoticeRecord) -> str:
    """quote 를 찾을 공고 글: 이름, 이름표 인용, 대상, 내용, 기간."""
    return "\n".join([n.name, *(t.quote for t in n.tags), n.target, n.content, n.apply_period])


def _crop_tokens(c: Crop) -> frozenset[str]:
    raw = {c.crop_code, c.label, *c.aliases, *c.groups}
    raw |= {re.sub(r"\(.*?\)", "", t) for t in raw}
    return frozenset(squash(t) for t in raw if t.strip())


def _word_hits(word: str, tokens: frozenset[str]) -> bool:
    w = squash(word)
    if not w or w in _CROP_STOP:
        return False
    return any(w == t or (len(w) >= 2 and len(t) >= 2 and (w in t or t in w)) for t in tokens)


class MatchTools:
    def __init__(self, profile: FarmProfile, notices: Sequence[NoticeRecord], crops: Sequence[Crop], as_of: date,
                 max_per_notice: int = MAX_PER_NOTICE, max_total: int = MAX_TOTAL) -> None:
        self._p = profile
        self._as_of = as_of
        self._notices = {n.key: n for n in notices}
        self._corpus = {n.key: squash(notice_corpus(n)) for n in notices}
        self._crop_tokens = [_crop_tokens(c) for c in crops]
        self._my_crops = [_crop_tokens(c) for c in crops if c.crop_code in {pl.crop_code for pl in profile.crops}]
        self._max_per, self._max_total = max_per_notice, max_total
        self.checks: list[CheckRecord] = []
        self._cache: dict[tuple, str] = {}
        self.submitted: dict[str, tuple[str, tuple[str, ...]]] = {}
        self.defaulted: set[str] = set()
        self.submit_tries = 0
        self.done = False
        self._kept: dict[str, tuple[str, tuple[str, ...]]] = {}     # 첫 제출에서 통과한 공고의 글
        self._first_failed: set[str] = set()
        self._numeric_seen: dict[str, set[tuple]] = {}

    # -- 조회 --
    def checks_of(self, key: str) -> tuple[CheckRecord, ...]:
        return tuple(c for c in self.checks if c.notice_key == key)

    def verdict_for(self, key: str) -> str:
        return verdict_with_notice(self._notices[key], self.checks_of(key))

    # -- check_farmer --
    def check_farmer(self, a: CheckFarmerIn) -> CheckFarmerOut:
        key = a.notice_key
        if key not in self._notices:
            raise ToolError(f"모르는 공고 열쇠예요. 공고 목록에 적힌 열쇠를 그대로 쓰세요: {', '.join(self._notices)}")
        quote_sq = squash(a.quote)
        if len(quote_sq) < MIN_QUOTE or quote_sq not in self._corpus[key]:
            raise ToolError("인용이 그 공고 글에 그대로 없어요. 공고 글에서 한 줄을 한 글자도 바꾸지 말고 옮겨 다시 물어보세요")
        sig = self._validate(a, quote_sq)
        cache_key = (key, a.kind, sig)
        if cache_key in self._cache:                       # 똑같은 질문은 같은 답을 다시 준다(횟수에 세지 않는다)
            return CheckFarmerOut(answer=self._cache[cache_key])
        mine = self.checks_of(key)
        if len(mine) >= self._max_per:
            raise ToolError("이 공고에 대한 확인 횟수를 다 썼어요. 지금까지의 확인으로 결과를 내세요")
        if len(self.checks) >= self._max_total:
            raise ToolError("확인 횟수를 다 썼어요. 지금까지의 확인으로 결과를 내세요")
        if a.kind != "그 밖":
            seen = {c.sig for c in mine if c.kind == a.kind}
            if len(seen) >= MAX_VALUES_PER_KIND:
                raise ToolError("같은 조건을 기준만 바꿔 여러 번 물을 수 없어요. 공고가 적은 기준 하나로 묻거나 넘어가세요")
        if a.kind in _NUMERIC:
            fam = self._numeric_seen.setdefault(SHORT_KIND[a.kind], set())
            if (key, sig) not in fam and len(fam) >= MAX_NUMERIC_PER_FAMILY:
                raise ToolError(f"{SHORT_KIND[a.kind]} 숫자 질문을 너무 많이 했어요. 지금까지의 확인으로 결과를 내세요")
            fam.add((key, sig))
        answer = self._answer(a)
        self._cache[cache_key] = answer
        self.checks.append(CheckRecord(key, a.kind, a.quote.strip(), answer, sig))
        return CheckFarmerOut(answer=answer)

    def _validate(self, a: CheckFarmerIn, quote_sq: str) -> tuple:
        """종류별 인자를 점검하고 같은 질문인지 가리는 서명을 돌려준다."""
        if a.kind == "작물":
            words = tuple(sorted({w.strip() for w in a.crops if w.strip()}))
            if not words or len(words) > 6:
                raise ToolError("작물 종류는 작물 낱말을 하나 이상 여섯 개까지 적어야 해요")
            for w in words:
                if squash(w) not in quote_sq:
                    raise ToolError("작물 낱말은 인용에 나온 그대로만 쓸 수 있어요. 인용에 없는 작물 낱말을 빼 주세요")
            return words
        if a.kind in _NUMERIC:
            if a.number is None:
                raise ToolError("이 종류는 공고가 적은 기준 숫자가 필요해요")
            if a.number not in _numbers(a.quote):
                raise ToolError("기준 숫자가 인용에 없어요. 공고에 적힌 숫자가 든 줄을 인용하세요")
            if a.kind.startswith("넓이") and a.unit is None:
                raise ToolError("넓이는 공고가 쓴 단위(평, ㎡, ha)가 필요해요")
            if not number_is_beside_word(a.kind, a.number, a.unit, a.quote):
                raise ToolError("기준 숫자가 인용에서 그 낱말 곁에 없어요. 나이는 세 앞, 넓이는 쓴 단위 앞, 햇수는 년 앞에 있는 숫자만 물을 수 있어요")
            self._need_words(a.kind, quote_sq)
            return (a.number, a.unit if a.kind.startswith("넓이") else None)
        if a.kind in _CHOICES:
            if a.choice not in _CHOICES[a.kind]:
                raise ToolError(f"고를 수 있는 값은 {', '.join(_CHOICES[a.kind])} 중 하나예요")
            if squash(_CHOICE_STEM[a.choice]) not in quote_sq:
                raise ToolError("고른 값이 인용에 나오지 않아요. 공고가 말한 값만 물을 수 있어요")
            return (a.choice,)
        if a.kind == "그 밖":
            return (quote_sq,)
        self._need_words(a.kind, quote_sq)
        if a.kind == "최근 재해 피해":                       # 인용에 60일이 있는지에 따라 답이 달라 서명에 넣는다
            return ("60일" in quote_sq,)
        return ()

    @staticmethod
    def _need_words(kind: str, quote_sq: str) -> None:
        words = KIND_WORDS.get(kind)
        if words and not any(squash(w) in quote_sq for w in words):
            raise ToolError("인용이 그 조건을 말하는 글이 아니에요. 그 조건이 적힌 줄을 인용하세요")

    # -- 답 계산(어르신 값은 여기서만 읽고 밖으로 내지 않는다) --
    def _answer(self, a: CheckFarmerIn) -> str:
        p, kind = self._p, a.kind
        if kind == "작물":
            words = [w for w in a.crops if w.strip()]
            if any(_word_hits(w, t) for w in words for t in self._my_crops):
                return YES
            known = all(any(_word_hits(w, t) for t in self._crop_tokens) for w in words)
            return NO if known else UNKNOWN
        if kind == "행정시":
            city = _CITY_OF_EUPMYEON.get(p.emd_code)
            return UNKNOWN if city is None else YES if city == a.choice else NO
        if kind in ("나이 이상", "나이 이하"):
            if p.birth_year is None:
                return UNKNOWN
            hi = self._as_of.year - p.birth_year          # 생일을 몰라 만 나이는 하나 적을 수 있다
            lo = hi - 1
            x = a.number
            if kind == "나이 이상":
                return YES if lo >= x else NO if hi < x else UNKNOWN
            return YES if hi <= x else NO if lo > x else UNKNOWN
        if kind == "성별":
            if p.owner_sex is None:
                return UNKNOWN
            return YES if (p.owner_sex == "F") == (a.choice == "여성") else NO
        if kind in ("넓이 이상", "넓이 이하"):
            area = self._area_m2()
            if area is None:
                return UNKNOWN
            x = a.number * {"평": PYEONG_M2, "㎡": 1.0, "ha": 10_000.0}[a.unit]
            return YES if (area >= x if kind == "넓이 이상" else area <= x) else NO
        if kind == "농사 햇수 이상":
            if p.farming_years is not None:
                return YES if p.farming_years >= a.number else NO
            return YES if p.farming_10y_plus and a.number <= 10 else UNKNOWN
        if kind == "제주 거주 햇수 이상":
            if p.residence_3y:
                return YES if a.number <= 3 else UNKNOWN
            return NO if a.number >= 3 else UNKNOWN
        if kind == "경영체 등록":
            return {"over_2y": YES, "under_2y": YES, "none": NO}.get(p.mgmt_status, UNKNOWN)
        if kind == "농협 출하":
            channels = [pl.sales_channel for pl in p.crops]
            if "coop" in channels:
                return YES
            return UNKNOWN if "unknown" in channels else NO
        if kind == "배우자 공동 영농":
            return NO if p.spouse == "none" else YES
        if kind == "건강보험 종류":
            mine = {"regional": "지역", "employee": "직장", "dependent": "피부양자"}.get(p.health_ins)
            return UNKNOWN if mine is None else YES if mine == a.choice else NO
        if kind == "최근 재해 피해":
            if "60일" not in squash(a.quote):             # 어르신 답은 최근 60일 재해 하나라 다른 기간은 답하지 못한다
                return UNKNOWN
            return YES if p.flags.disaster_damage else NO
        if kind == "땅 소유":
            return {"own_all": YES, "own_part": YES, "rent_all": NO}.get(p.land_tenure, UNKNOWN)
        return UNKNOWN                                     # 그 밖

    def _area_m2(self) -> float | None:
        if self._p.total_area_m2 is not None:
            return float(self._p.total_area_m2)
        areas = [pl.area_m2 for pl in self._p.crops]
        return float(sum(areas)) if all(x is not None for x in areas) else None

    # -- submit_matches --
    def submit_matches(self, a: SubmitMatchesIn) -> SubmitMatchesOut:
        if self.done:
            raise ToolError("결과는 이미 받았어요")
        if not self.checks:
            raise ToolError("확인한 조건이 하나도 없어요. 먼저 check_farmer 로 공고가 내건 조건을 확인한 뒤 결과를 내세요")
        problems: dict[str, list[str]] = {}
        good: dict[str, tuple[str, tuple[str, ...]]] = {}
        for it in a.items:
            if it.notice_key not in self._notices:
                problems.setdefault(it.notice_key, []).append("모르는 공고 열쇠예요")
                continue
            if it.notice_key in good or it.notice_key in problems:
                continue
            checks = self.checks_of(it.notice_key)
            verdict = self.verdict_for(it.notice_key)
            if verdict == NOT_FIT:                         # 안 맞는 공고의 글은 쓰지 않는다
                good[it.notice_key] = ("", ())
                continue
            if verdict == MAYBE_UNKNOWN:                   # 알 수 없는 공고의 이유 글은 늘 프로그램 문장(AI 글은 ask 만)
                it = it.model_copy(update={"why": default_why(verdict, checks)})
            found = self.text_problems(it, checks)
            if found:
                problems[it.notice_key] = found
            else:
                good[it.notice_key] = (it.why.strip(), tuple(s.strip() for s in it.ask))
        self.submit_tries += 1
        if problems and self.submit_tries == 1:
            self._kept.update(good)
            self._first_failed = {k for k in problems if k in self._notices}
            lines = [f"{self._notices[k].name if k in self._notices else k}: {'; '.join(v)}" for k, v in problems.items()]
            raise ToolError("글이 검사에 걸렸어요. 아래 이유를 고쳐 같은 도구로 한 번 더 내세요(걸리지 않은 공고의 글은 보관했어요) - " + " / ".join(lines))
        merged = {**self._kept, **good}                    # 같은 공고가 둘째에 있으면 둘째 글
        self.submitted.update(merged)
        for k in {*problems, *self._first_failed}:
            if k in self._notices and k not in merged:
                self.defaulted.add(k)
        self.done = True
        if self.defaulted:
            return SubmitMatchesOut(accepted=True, message="일부 공고는 기본 문장으로 바꿔 받았어요")
        return SubmitMatchesOut(accepted=True, message="받았어요")

    def text_problems(self, it: SubmitItem, checks: Sequence[CheckRecord]) -> list[str]:
        n = self._notices[it.notice_key]
        allowed = "\n".join([n.apply_period, *(t.quote for t in n.tags), *(c.quote for c in checks)])
        allowed_sq, allowed_nums = squash(allowed), _numbers(allowed)
        out: list[str] = []
        why = it.why.strip()
        asks = [s.strip() for s in it.ask]
        if not why:
            return ["이유 글(why)이 비었어요"]
        if len(why) > MAX_WHY:
            out.append("이유 글(why)이 너무 길어요. 한 문장으로 짧게 쓰세요")
        if len(asks) > MAX_ASKS or any(not s for s in asks):
            out.append("창구에서 물어볼 것(ask)은 비지 않은 것으로 둘까지만 쓰세요")
        if any(len(s) > MAX_ASK for s in asks):
            out.append("창구에서 물어볼 것(ask) 한 줄이 너무 길어요. 짧게 쓰세요")
        for text in [why, *asks]:
            t_sq = squash(text)
            bad_nums = _numbers(text) - allowed_nums
            if bad_nums or any(squash(m.group(0)) not in allowed_sq for m in _HANGUL_NUM.finditer(text)):
                out.append("공고 인용에 없는 숫자를 썼어요. 인용에 있는 숫자만 쓰거나 숫자를 빼세요")
            for m in _MONEY.findall(text):
                if squash(m) not in allowed_sq:
                    out.append("금액이나 비율을 새로 썼어요. 금액은 인용에 있는 그대로가 아니면 쓰지 마세요")
                    break
            hit = [w for w in ASSERT_WORDS if w in t_sq]
            if hit:
                out.append("단정하는 말을 썼어요. 맞을 수 있다는 말투로 쓰세요(받습니다, 대상입니다, 확정, 전액 같은 말은 쓰지 않아요)")
            if _CODEISH.search(text) or any(squash(w) not in allowed_sq and squash(w) not in squash(n.name) for w in _LATIN.findall(text)):
                out.append("영어나 코드 같은 글자를 썼어요. 쉬운 한국어로만 쓰세요")
        if self.verdict_for(it.notice_key) == FIT:
            confirmed = {SHORT_KIND[c.kind] for c in checks if c.answer == YES}
            why_sq = squash(why)
            if any(label not in confirmed and any(squash(w) in why_sq for w in words) for label, words in CLAIM_WORDS.items()):
                out.append("확인하지 않은 조건을 맞는다고 썼어요. '예'로 확인된 조건만 쓰세요")
        return list(dict.fromkeys(out))

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register("check_farmer", CheckFarmerIn, CheckFarmerOut, self.check_farmer)
        reg.register("submit_matches", SubmitMatchesIn, SubmitMatchesOut, self.submit_matches)
        return reg
