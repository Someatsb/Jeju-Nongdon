"""키 없음(Task 9, U09). 늘 LLMUnavailable("NO_KEY") → 부르는 쪽은 처음부터 템플릿 문장을 쓴다."""
from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable


class NullClient:
    provider = "none"
    model = "none"

    def generate(self, req: GenRequest) -> GenResult:
        raise LLMUnavailable("NO_KEY")
