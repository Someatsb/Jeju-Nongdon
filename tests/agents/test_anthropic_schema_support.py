"""실호출에서 드러난 일: 제공자의 구조화 출력은 maxItems 등 일부 JSON 스키마 키워드를 거절한다(400).
어댑터는 그 키워드를 뺀 스키마만 보내고, 길이·개수 검사는 우리 쪽 검사(파싱·검수)가 한다."""
from app.agents.llm.anthropic_adapter import AnthropicClient, provider_schema
from app.agents.llm.base import GenRequest, Msg


def test_provider_schema_drops_unsupported_keywords_everywhere():
    schema = {"type": "object", "properties": {
        "s": {"type": "array", "maxItems": 3, "minItems": 2, "items": {"type": "string", "maxLength": 9, "minLength": 1}},
        "n": {"type": "integer", "minimum": 1, "maximum": 4}},
        "required": ["s"], "additionalProperties": False}
    out = provider_schema(schema)
    flat = repr(out)
    for key in ("maxItems", "minItems", "maxLength", "minLength", "minimum", "maximum"):
        assert key not in flat
    assert out["required"] == ["s"] and out["additionalProperties"] is False
    assert out["properties"]["s"]["items"]["type"] == "string"
    assert "maxItems" in repr(schema)          # 원본은 건드리지 않는다


def test_build_kwargs_sends_provider_schema():
    class Fake:
        class messages:
            @staticmethod
            def create(*, output_config=None, **kw): return None
    c = AnthropicClient("key-test-1", client=Fake())
    schema = {"type": "array", "maxItems": 2, "items": {"type": "string"}}
    from app.agents.llm.payload import build_payload
    req = GenRequest(purpose="narrate", system="s", messages=(Msg(role="user", text="t"),), response_schema=schema)
    kw = c.build_kwargs(build_payload(req))
    assert "maxItems" not in repr(kw["output_config"])
