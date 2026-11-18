"""전송 거름망(Task 9). 외부 LLM으로 나가는 바이트는 전부 build_payload()를 지난다.

거부 패턴: 숫자 [0-9０-９①-⑳] · 읍면동 이름 · 건강 낱말(입원·질병·진단·수술·암·치매) ·
전화 \\d{2,3}-\\d{3,4}-\\d{4} · 주민번호 \\d{6}-\\d{7}. 위반하면 PayloadRejected(field, pattern).
"""
import hashlib
import json
import logging
from datetime import date

import pytest
from pydantic import ValidationError
from review_fixtures import CONTEXTS, GOOD

from app.agents.llm import payload as payload_mod
from app.agents.llm.base import GenRequest, LLMUnavailable, Msg, ToolCall, ToolDef, ToolResult
from app.agents.llm.payload import (
    JEJU_EMD,
    SCHEMA_NUMBER_KEYS,
    Payload,
    PayloadGuard,
    PayloadRejected,
    build_payload,
    default_guard,
    input_hash,
    load_emd_names,
)
from app.agents.rules import RULE_MESSAGES

SYSTEM = "어르신께 드릴 설명 문장을 쓰세요. 숫자는 쓰지 마세요."


def req_with(text: str, **changes) -> GenRequest:
    return GenRequest(**{"purpose": "narrate", "section": "support", "system": SYSTEM,
                         "messages": (Msg(role="user", text=text),), **changes})


def rejected(req: GenRequest, **kw) -> PayloadRejected:
    with pytest.raises(PayloadRejected) as e:
        build_payload(req, **kw)
    return e.value


# --- 거부 -----------------------------------------------------------------------------------

def test_payload_rejects_digits_and_emd():
    with pytest.raises(PayloadRejected):
        build_payload(req_with("애월읍 3,000평"))
    assert rejected(req_with("애월읍에 사십니다")).pattern == "emd"
    assert rejected(req_with("삼천 평 넘게 3")).pattern == "digit"


@pytest.mark.parametrize("text", ["３월", "③번 문항", "0", "용담2동"])
def test_payload_rejects_fullwidth_and_circled_digits(text):
    assert rejected(req_with(text)).pattern == "digit"


def test_payload_rejects_health_words():
    with pytest.raises(PayloadRejected):
        build_payload(req_with("입원하셨다면"))


@pytest.mark.parametrize("text", ["질병이 있으면", "진단서를 가져오세요", "수술 뒤에는", "치매 어르신",
                                  "암에 걸리셨다면", "암 진단", "암으로", "(암)", "병명: 암"])
def test_payload_health_word_variants(text):
    assert rejected(req_with(text)).pattern == "health"


@pytest.mark.parametrize("text", ["위암", "폐암", "간암", "대장암", "유방암", "갑상선암", "췌장암", "자궁암", "전립선암",
                                  "혈액암", "피부암", "말기암", "항암 치료", "암환자", "암투병", "암치료",
                                  "남편분 위암 수발"])
def test_payload_cancer_compounds_rejected(text):
    assert rejected(req_with(text)).pattern == "health"


@pytest.mark.parametrize("text", ["암까지 겹쳐", "암하고 같이", "암보다 먼저", "암만 아니면", "암이라서", "암입니다"])
def test_payload_am_with_more_particles_rejected(text):
    assert rejected(req_with(text)).pattern == "health"


@pytest.mark.parametrize("text", ["암반 지하수", "현무암 돌담", "암소를 키우십니다", "암석이 많은 밭", "암술에 꽃가루", "명암"])
def test_payload_am_inside_other_words_passes(text):
    """'암'은 한 글자라 합성어 목록이 아니면, 앞에 한글이 없고 뒤가 끝·한글 아님·조사일 때만 건강 낱말로 본다."""
    assert isinstance(build_payload(req_with(text)), Payload)


# --- 공고(notice): 주민번호만 막는다 ------------------------------------------------------------

NOTICE_TEXT = ("제주특별자치도 공고: 2026년 11월 13일까지 신청, 1ha당 150만 원 지원. "
               "가축 질병 발생 지역 제외. 문의 애월읍사무소 064-710-4092")


def test_notice_purpose_keeps_only_the_resident_id_rule():
    notice = req_with(NOTICE_TEXT, purpose="notice", section=None,
                      response_schema={"type": "object", "properties": {"amount": {"type": "integer", "default": 0}}})
    assert isinstance(build_payload(notice), Payload)
    with_rrn = req_with(NOTICE_TEXT + " 신청인 900101-1234567", purpose="notice", section=None)
    assert rejected(with_rrn).pattern == "rrn"
    assert rejected(req_with(NOTICE_TEXT)).pattern == "phone"          # narrate: 전화가 숫자보다 먼저 걸린다
    assert rejected(req_with(NOTICE_TEXT.replace(" 064-710-4092", ""))).pattern == "digit"


def test_payload_phone_and_resident_id_are_named():
    assert rejected(req_with("문의 064-710-4092")).pattern == "phone"
    assert rejected(req_with("010-1234-5678로 연락")).pattern == "phone"
    assert rejected(req_with("주민번호 900101-1234567")).pattern == "rrn"


@pytest.mark.parametrize("text", ["노형동", "연동", "이도동", "우도면", "서귀포 예래동에서"])
def test_payload_rejects_emd_names(text):
    assert rejected(req_with(text)).pattern == "emd"


def test_rejection_names_the_field_never_the_text():
    schema = {"type": "object", "properties": {"text": {"type": "string", "description": "노형동 기준"}}}
    e = rejected(req_with("괜찮은 문장", tools=(ToolDef(name="submit", description="구획 제출", input_schema=schema),)))
    assert (e.field, e.pattern) == ("tools[0].input_schema.properties.text.description", "emd")
    assert "노형동" not in str(e)
    assert rejected(req_with("문장", system="두세 문장, 최대 3개")).field == "system"
    assert rejected(req_with("문장", response_schema={"properties": {"애월읍": {}}})).field == "response_schema.properties.<key>"
    two = GenRequest(purpose="judge", system=SYSTEM,
                     messages=(Msg(role="user", text="첫째"), Msg(role="user", text="치매 여부")))
    assert (rejected(two).field, rejected(two).pattern) == ("messages[1].text", "health")


def test_tool_result_content_is_checked():
    req = req_with("구획", messages=(
        Msg(role="user", text="구획을 쓰세요"),
        Msg(role="assistant", tool_calls=(ToolCall(call_id="toolu_a", name="get_program_detail", args={"id": "logistics"}),)),
        Msg(role="user", tool_results=(ToolResult(call_id="toolu_a", content='{"amount": 300000}'),)),
    ))
    assert (rejected(req).field, rejected(req).pattern) == ("messages[2].tool_results[0].content", "digit")


def test_numbers_in_non_string_positions():
    """숫자 값은 JSON Schema 제약 키 아래에서만 허용한다. default·enum·const·examples·도구 인자의 숫자는 digit."""
    constraints = {key: 1 for key in SCHEMA_NUMBER_KEYS}
    assert SCHEMA_NUMBER_KEYS == {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
                                  "multipleOf", "exclusiveMinimum", "exclusiveMaximum"}
    tool = ToolDef(name="submit", description="구획", input_schema={"type": "object", "properties": {"n": constraints}})
    assert isinstance(build_payload(req_with("구획", tools=(tool,), response_schema=constraints)), Payload)
    for schema, field in (({"default": 3}, "response_schema.default"),
                          ({"enum": ["가", 2]}, "response_schema.enum[1]"),
                          ({"const": 0.5}, "response_schema.const"),
                          ({"examples": [7]}, "response_schema.examples[0]"),
                          ({"properties": {"n": {"default": -1}}}, "response_schema.properties.n.default")):
        assert (rejected(req_with("구획", response_schema=schema)).field, "digit") == (field, "digit")
    for args, field in (({"sid": 1}, "messages[1].tool_calls[0].args.sid"),
                        ({"maximum": 9}, "messages[1].tool_calls[0].args.maximum"),   # 인자에는 제약 키 예외 없음
                        ({"when": date(2026, 11, 13)}, "messages[1].tool_calls[0].args.when")):
        call = ToolCall(call_id="toolu_a", name="submit_narrative", args=args)
        e = rejected(req_with("구획", messages=(Msg(role="user", text="구획"), Msg(role="assistant", tool_calls=(call,)))))
        assert (e.field, e.pattern) == (field, "digit")
    assert isinstance(build_payload(req_with("구획", response_schema={"default": True, "const": None})), Payload)


# --- 통과 -----------------------------------------------------------------------------------

def test_provider_ids_and_schema_limits_pass():
    """제공자가 붙인 call_id(숫자 섞인 불투명 ID)와 스키마 제약 숫자는 검사하지 않는다."""
    call = ToolCall(call_id="toolu_01AbC9", name="submit_narrative",
                    args={"text": "{P:logistics}은 농협에 물어보실 수 있습니다."})
    req = req_with("구획", messages=(
        Msg(role="user", text="구획을 쓰세요"),
        Msg(role="assistant", tool_calls=(call,)),
        Msg(role="user", tool_results=(ToolResult(call_id="toolu_01AbC9", content="반려: 근거 없음"),)),
    ), response_schema={"type": "object", "properties": {"text": {"type": "string", "maxLength": 70}}})
    assert isinstance(build_payload(req), Payload)


def test_rule_feedback_messages_pass():
    """재생성 지시문(Task 19)은 RULE_MESSAGES로 조립되므로 거름망을 지나야 한다."""
    for message in RULE_MESSAGES.values():
        build_payload(req_with(message))


def test_real_contexts_and_good_sentences_pass():
    """골든 맥락 7개(NarrativeInput JSON)와 좋은 문장 40개는 거름망에 걸리지 않는다(오탐 0)."""
    for ctx in CONTEXTS.values():
        build_payload(req_with(ctx.model_dump_json()))
    for case in GOOD:
        text = " ".join(s.text for s in case.section.sentences)
        build_payload(req_with("구획", messages=(Msg(role="user", text="구획"), Msg(role="assistant", text=text))))


def test_gate_walks_every_request_field():
    """거름망(_texts)은 필드를 이름으로 훑는다. 필드를 더하면 이 목록과 _texts를 함께 고친다."""
    assert set(GenRequest.model_fields) == {"purpose", "system", "messages", "tools", "response_schema",
                                            "max_output_tokens", "timeout_s", "effort", "section"}
    assert set(Msg.model_fields) == {"role", "text", "tool_calls", "tool_results"}
    assert set(ToolCall.model_fields) == {"call_id", "name", "args"}
    assert set(ToolResult.model_fields) == {"call_id", "content", "is_error"}
    assert set(ToolDef.model_fields) == {"name", "description", "input_schema"}


def test_payload_copies_the_request():
    req = req_with("문장", response_schema={"type": "object"})
    p = build_payload(req)
    assert isinstance(p, Payload) and isinstance(p, GenRequest)
    assert p.model_dump() == req.model_dump()
    req.response_schema["type"] = "array"          # 검사 뒤에 원본 dict를 바꿔도 Payload는 그대로
    assert p.response_schema == {"type": "object"}


def test_payload_only_from_the_gate():
    with pytest.raises(ValidationError):
        Payload(**req_with("애월읍").model_dump())
    with pytest.raises(ValidationError):
        Payload.model_validate(req_with("문장").model_dump())


# --- 해시·이름 목록 ---------------------------------------------------------------------------

def test_input_hash_is_sha256_of_canonical_json():
    p = build_payload(req_with("가", response_schema={"b": "y", "a": "x"}))
    canonical = json.dumps(p.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert input_hash(p) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    same = build_payload(req_with("가", response_schema={"a": "x", "b": "y"}))
    assert input_hash(same) == input_hash(p)
    assert input_hash(build_payload(req_with("나", response_schema={"a": "x", "b": "y"}))) != input_hash(p)


def test_match_hash_ignores_timeout_so_real_recordings_replay():
    """새 공고 맞춰 보기는 남은 시간에 맞춰 요청마다 timeout_s 가 달라진다(실제 AI 로 녹화하면 둘째 요청부터 줄어 있다).
    제한 시간이 해시에 섞이면 녹화가 재생에서 맞지 않으므로(2026-11-15 부장 실측), 맞춰 보기 요청의 해시는 제한 시간을 세지 않는다.
    다른 용도(설명 글 등)는 전과 같이 요청 전체를 센다(이미 있는 녹화의 해시가 바뀌지 않게)."""
    def req(purpose, timeout):
        return GenRequest(purpose=purpose, system="s", messages=(Msg(role="user", text="가"),), timeout_s=timeout)
    assert input_hash(build_payload(req("match", 20.0))) == input_hash(build_payload(req("match", 15.2)))
    assert input_hash(build_payload(req("match", 20.0))) != input_hash(build_payload(req("scout", 20.0)))
    assert input_hash(build_payload(req("narrate", 20.0))) != input_hash(build_payload(req("narrate", 15.2)))
    full = build_payload(req("match", 20.0))
    canonical = json.dumps(full.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert input_hash(full) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()      # 20초일 때는 전과 같은 값


def test_emd_names_builtin_table_and_digitless_variants(tmp_path):
    assert len(JEJU_EMD) == 43
    names = load_emd_names(tmp_path / "missing.csv")
    assert {"애월읍", "한경면", "연동", "일도1동", "일도동", "용담동", "예래동"} <= names
    (tmp_path / "emd.csv").write_text("﻿name,admin_city\n가상2동,제주시\n", encoding="utf-8")
    assert {"가상2동", "가상동", "애월읍"} <= load_emd_names(tmp_path / "emd.csv")
    (tmp_path / "bad.csv").write_text("emd\n가상동\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_emd_names(tmp_path / "bad.csv")


def test_payload_rejected_is_llm_unavailable():
    e = PayloadRejected("system", "digit")
    assert isinstance(e, LLMUnavailable) and e.reason == "PAYLOAD_REJECTED"
    assert (e.field, e.pattern) == ("system", "digit")


@pytest.fixture
def bad_emd_table(tmp_path, monkeypatch):
    bad = tmp_path / "emd.csv"
    bad.write_text("emd\n가상동\n", encoding="utf-8")
    calls = []
    real = payload_mod.load_emd_names
    monkeypatch.setattr(payload_mod, "EMD_CSV", bad)
    monkeypatch.setattr(payload_mod, "load_emd_names", lambda path: calls.append(path) or real(path))
    payload_mod._default_guard.cache_clear()
    yield calls
    payload_mod._default_guard.cache_clear()


def test_bad_emd_table_fails_loudly_once_and_payload_rejects(bad_emd_table, caplog):
    """표가 잘못되면 한 번 크게(한국어 오류 로그) 실패하고, build_payload는 PayloadRejected만 낸다(닫힌 쪽)."""
    with caplog.at_level(logging.ERROR, logger="app.agents.llm.payload"):
        for _ in range(2):
            e = rejected(req_with("괜찮은 문장"))
            assert (e.field, e.pattern) == ("data/tables/emd.csv", "emd_table")
            assert isinstance(e.__cause__, ValueError)
    assert len(bad_emd_table) == 1
    assert [r.levelno for r in caplog.records] == [logging.ERROR] and "name 칸" in caplog.records[0].getMessage()
    with pytest.raises(ValueError, match="name 칸"):
        default_guard()                                # 시작·설치 점검에서 부르면 같은 오류로 멈춘다


def test_guard_is_pure_given_names():
    guard = PayloadGuard(frozenset({"가상동"}))
    assert rejected(req_with("가상동에서"), guard=guard).pattern == "emd"
    assert isinstance(build_payload(req_with("애월읍"), guard=guard), Payload)
    with pytest.raises(ValueError):
        PayloadGuard(frozenset())
