"""틀린 문장 주입(Task 9, U09) — round1-C-agent.md §4-5. 테스트·녹화 도구 전용, 화면 없음.

다른 LLMClient를 감싸는 장식자. first_attempt_bad.section 구획의 첫 설명 요청(purpose="narrate")에만
미리 정한 나쁜 구획을 돌려주고(구조화 출력처럼 text = 구획 JSON, rules.parse_section으로 읽힌다),
그 뒤 요청과 다른 구획·판정 요청은 모두 inner로 넘긴다. 주입한 결과의 provider는
"fault-inject(<inner 제공자>)", 토큰·지연은 0이라 로그에서 주입이 드러난다.
한 번 주입하면 끝이므로 상담(시연) 한 번마다 새로 만든다.
"""
from app.agents.llm.base import GenRequest, GenResult, LLMClient
from app.agents.rules import Section


class FaultInjectClient:
    def __init__(self, inner: LLMClient, first_attempt_bad: Section):
        self.inner = inner
        self.first_attempt_bad = first_attempt_bad
        self.provider = f"fault-inject({inner.provider})"
        self.model = inner.model
        self._injected = False

    def generate(self, req: GenRequest) -> GenResult:
        if not self._injected and req.purpose == "narrate" and req.section == self.first_attempt_bad.section:
            self._injected = True
            return GenResult(text=self.first_attempt_bad.model_dump_json(), tool_calls=(), stop="end",
                             tok_in=0, tok_out=0, latency_ms=0, provider=self.provider, model=self.model)
        return self.inner.generate(req)
