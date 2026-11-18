"""전송 거름망(Task 9, U09). 외부 LLM으로 나가는 바이트는 전부 build_payload()를 지난다.

거부 패턴(플랜 Task 9 그대로). 먼저 걸린 하나를 PayloadRejected(field, pattern)로 알린다.
  rrn    주민번호 \\d{6}-\\d{7}
  phone  전화 \\d{2,3}-\\d{3,4}-\\d{4}
  digit  숫자 [0-9０-９①-⑳]
  emd    읍면동 이름(그대로 부분 일치. 예: "연동"은 '연동되다'에도 걸린다 — 프롬프트에서 피한다)
  health 건강 낱말 입원·질병·진단·수술·치매와 암 합성어 목록(위암·항암·암환자 …)은 부분 일치.
         홑 '암'은 앞에 한글이 없고 뒤가 끝·한글 아님·조사(이·가·까지·하고·보다·만 …)일 때만
         → '암에', '암 진단', '암만'은 걸리고 '암반', '현무암', '암석', '암술', '암소'는 통과.
전화·주민번호를 숫자보다 먼저 보는 것은 걸린 이유를 정확히 남기기 위해서다(숫자 규칙이 먼저 걸리므로).
purpose="notice"(공개 공고문, 날짜·금액·기관 전화가 본래 있음)는 rrn 규칙만 건다(컨트롤러 결정).
purpose="match"(새 공고 맞춰 보기)·"scout"(새 공고 찾아오기)도 공개 공고 글을 싣기 때문에 같다(base.PUBLIC_TEXT_PURPOSES).
  match 는 어르신 값이 나가지 않게 구조로 막는다: 요청에 FarmProfile 값을 넣는 길이 없고 도구 결과는 예/아니오/답에 없음뿐이다.

검사 대상: system, 메시지 글(text), 도구 결과(content), 도구 호출 이름과 인자,
도구 정의(name·description·input_schema), response_schema — 문자열 값과 dict 키 전부.
dict 안의 문자열 아닌 값은 JSON 꼴(날짜는 문자열)로 바꿔 본다. 숫자 값은 글자로 바꿔 같은 규칙에 건다
(→ digit). 예외는 스키마(input_schema·response_schema)의 제약 키(SCHEMA_NUMBER_KEYS) 아래 숫자뿐이다.
default·enum·const·examples의 숫자, 도구 호출 인자의 숫자(sid 등)는 digit 위반이다. 참·거짓·null은 보지 않는다.
뺀 것: ToolCall·ToolResult의 call_id(제공자가 붙인 불투명 ID).
오류에는 필드 경로와 규칙 이름만 담고 걸린 글자는 담지 않는다(로그로 새지 않게).

Payload는 build_payload()만 만든다(직접 만들면 ValidationError). 어댑터는 Payload만 받아 요청을 조립한다.
input_hash(payload)는 녹화 재생(scripted)의 열쇠: 정렬 키·ensure_ascii=False JSON의 sha256.
기본 거름망은 처음 쓸 때 한 번 만든다. data/tables/emd.csv가 잘못됐으면 한국어 오류를 한 번 로그에 남기고,
그 뒤 build_payload()는 모두 PayloadRejected("data/tables/emd.csv", "emd_table")로 막는다(닫힌 쪽 실패).
"""
import csv
import functools
import hashlib
import json
import logging
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationInfo, model_validator
from pydantic_core import to_jsonable_python

from app.agents.llm.base import PUBLIC_TEXT_PURPOSES, GenRequest, LLMUnavailable

EMD_CSV = Path(__file__).resolve().parents[3] / "data" / "tables" / "emd.csv"

# 제주 43개 읍면동(제주시 4읍 3면 19동, 서귀포시 3읍 2면 12동). data/tables/emd.csv가 아직 없어
# 내장 목록으로 둔다. 표가 생기면 그 name 칸을 더한다(내장 목록은 빼지 않는다: 거름망은 닫힌 쪽으로 실패).
JEJU_EMD: tuple[str, ...] = (
    "한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "추자면", "우도면",
    "일도1동", "일도2동", "이도1동", "이도2동", "삼도1동", "삼도2동", "용담1동", "용담2동", "건입동",
    "화북동", "삼양동", "봉개동", "아라동", "오라동", "연동", "노형동", "외도동", "이호동", "도두동",
    "대정읍", "남원읍", "성산읍", "안덕면", "표선면",
    "송산동", "정방동", "중앙동", "천지동", "효돈동", "영천동", "동홍동", "서홍동", "대륜동", "대천동",
    "중문동", "예래동",
)

CANCER_WORDS: tuple[str, ...] = ("위암", "폐암", "간암", "대장암", "유방암", "갑상선암", "췌장암", "자궁암", "전립선암",
                                 "혈액암", "피부암", "말기암", "항암", "암환자", "암투병", "암치료")
_AM_NEXT = r"[이가은는을를에의도과와만랑으입인일뿐]|까지|하고|보다|부터|처럼|조차|마저|밖에"

RRN = r"\d{6}-\d{7}"
PHONE = r"\d{2,3}-\d{3,4}-\d{4}"
DIGIT = r"[0-9０-９①-⑳]"
HEALTH = "|".join(("입원", "질병", "진단", "수술", "치매", *CANCER_WORDS)) + rf"|(?<![가-힣])암(?=$|[^가-힣]|{_AM_NEXT})"

SCHEMA_NUMBER_KEYS = frozenset({"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
                                "multipleOf", "exclusiveMinimum", "exclusiveMaximum"})

_log = logging.getLogger(__name__)


class PayloadRejected(LLMUnavailable):
    """거름망이 전송을 막음(reason "PAYLOAD_REJECTED"). 필드 경로와 규칙 이름만 담는다."""

    def __init__(self, field: str, pattern: str):
        super().__init__("PAYLOAD_REJECTED", f"{field}에 {pattern} 패턴이 있어 보내지 않습니다")
        self.field = field
        self.pattern = pattern


_GATE = object()


class Payload(GenRequest):
    """거름망을 지난 GenRequest 사본. build_payload()가 아니면 만들 수 없다."""

    @model_validator(mode="before")
    @classmethod
    def _only_from_gate(cls, data: Any, info: ValidationInfo) -> Any:
        if not (info.context and info.context.get("gate") is _GATE):
            raise ValueError("Payload는 build_payload()로만 만듭니다.")
        return data


class PayloadGuard:
    """읍면동 이름 목록이 정해지면 build()는 순수 함수다(파일·시계 없음)."""

    def __init__(self, emd_names: frozenset[str]):
        names = sorted(n for n in emd_names if n)
        if not names:
            raise ValueError("읍면동 이름 목록이 비었습니다.")
        emd = "|".join(map(re.escape, names))
        self._rules = tuple((label, re.compile(rx)) for label, rx in (
            ("rrn", RRN), ("phone", PHONE), ("digit", DIGIT), ("emd", emd), ("health", HEALTH)))
        self._notice_rules = self._rules[:1]   # rrn만

    def build(self, req: GenRequest) -> Payload:
        rules = self._notice_rules if req.purpose in PUBLIC_TEXT_PURPOSES else self._rules
        for field, text in _texts(req):
            for label, rx in rules:
                if rx.search(text):
                    raise PayloadRejected(field, label)
        return Payload.model_validate(req.model_dump(), context={"gate": _GATE})  # model_dump = 깊은 사본


def load_emd_names(path: Path = EMD_CSV) -> frozenset[str]:
    """내장 43개 + emd.csv의 name 칸(있으면) + 숫자 뺀 이름('일도1동' → '일도동', 흔히 부르는 이름)."""
    names = set(JEJU_EMD)
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "name" not in (reader.fieldnames or ()):
                raise ValueError(f"읍면동 표 {path}에 name 칸이 없습니다. 전송 거름망을 만들 수 없어 "
                                 "LLM 호출을 모두 막습니다. 표를 고친 뒤 다시 시작하세요.")
            names.update(row["name"].strip() for row in reader if (row["name"] or "").strip())
    return frozenset(names | {re.sub(r"[0-9]", "", n) for n in names})


@functools.cache
def _default_guard() -> PayloadGuard | ValueError:
    """기본 거름망을 한 번만 만든다. 표가 잘못됐으면 오류를 한 번 로그에 남기고 그 오류를 기억한다."""
    try:
        return PayloadGuard(load_emd_names(EMD_CSV))
    except ValueError as e:
        _log.error("%s", e)
        return e


def default_guard() -> PayloadGuard:
    """기본 거름망. 앱 시작·설치 점검(Task 27)에서 불러 표 오류를 한국어로 크게 드러낸다."""
    guard = _default_guard()
    if isinstance(guard, ValueError):
        raise ValueError(str(guard))
    return guard


def build_payload(req: GenRequest, guard: PayloadGuard | None = None) -> Payload:
    """PayloadRejected 말고는 내지 않는다(기본 거름망을 못 만들면 그것도 PayloadRejected)."""
    if guard is None:
        default = _default_guard()
        if isinstance(default, ValueError):
            raise PayloadRejected("data/tables/emd.csv", "emd_table") from default
        guard = default
    return guard.build(req)


def input_hash(payload: Payload) -> str:
    data = payload.model_dump(mode="json")
    if data.get("purpose") == "match":
        # 새 공고 맞춰 보기는 남은 시간에 맞춰 요청마다 제한 시간(timeout_s)이 달라진다. 제한 시간은 보내는 글이 아니라 전송 설정이므로
        # 해시는 고정값으로 센다. 그러지 않으면 실제 AI 로 녹화한 것(둘째 요청부터 남은 시간이 줄어 있음)이 재생에서 맞지 않는다.
        data["timeout_s"] = 20.0
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _texts(req: GenRequest) -> Iterator[tuple[str, str]]:
    """(필드 경로, 검사할 글자)를 보내는 순서대로. call_id는 내지 않는다."""
    yield "system", req.system
    for i, m in enumerate(req.messages):
        at = f"messages[{i}]"
        if m.text is not None:
            yield f"{at}.text", m.text
        for j, call in enumerate(m.tool_calls):
            yield f"{at}.tool_calls[{j}].name", call.name
            yield from _walk(to_jsonable_python(call.args), f"{at}.tool_calls[{j}].args", schema=False)
        for j, res in enumerate(m.tool_results):
            yield f"{at}.tool_results[{j}].content", res.content
    for i, tool in enumerate(req.tools):
        yield f"tools[{i}].name", tool.name
        yield f"tools[{i}].description", tool.description
        yield from _walk(to_jsonable_python(tool.input_schema), f"tools[{i}].input_schema", schema=True)
    if req.response_schema is not None:
        yield from _walk(to_jsonable_python(req.response_schema), "response_schema", schema=True)


def _walk(obj: Any, at: str, *, schema: bool, key: str | None = None) -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        yield at, obj
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if not (schema and key in SCHEMA_NUMBER_KEYS):
            yield at, str(obj)                     # 숫자 값 → 글자로 바꿔 digit 규칙에 건다
    elif isinstance(obj, Mapping):
        for k, v in obj.items():
            yield f"{at}.<key>", str(k)            # 키가 통과한 뒤에야 경로에 키 이름을 쓴다
            yield from _walk(v, f"{at}.{k}", schema=schema, key=str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{at}[{i}]", schema=schema)
