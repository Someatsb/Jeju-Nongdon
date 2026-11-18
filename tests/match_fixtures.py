"""새 공고 맞춰 보기 시험 공용 틀. 공고 고정본은 tests/fixtures/catalog_notices/match/ (실제 공고 글을 그대로 옮긴 것)."""
from dataclasses import replace

from conftest import AS_OF, P1_KWARGS, P4_KWARGS, ROOT

from app.agents.llm.base import GenRequest, GenResult, LLMUnavailable, ToolCall
from app.catalog.notices import NoticeRecord, load_notices
from app.core.models import FarmProfile
from app.data_layer.tables import load_tables

NOTICE_DIR = ROOT / "tests" / "fixtures" / "catalog_notices" / "match"
NOTICES = {n.key: n for n in load_notices(NOTICE_DIR)}
FTA, ORG_MAT, ORG_FERT, LOAN, BIRTH = (f"new-{s}" for s in ("fta_citrus", "organic_materials", "organic_fertilizer_extra", "agri_loan", "birth_helper"))
CROPS = load_tables(ROOT / "data" / "tables", AS_OF).crops
CARROT = ({"crop_code": "당근", "area_m2": 4959, "sales_channel": "coop", "selfpay_fund": "paid"},)


def profile(**over) -> FarmProfile:
    """P1(남원 노지감귤, 1952년생 여성)을 바탕으로 한 농가."""
    return FarmProfile(**{**P1_KWARGS, **over})


def profile_p4() -> FarmProfile:
    return FarmProfile(**P4_KWARGS)


def custom_notice(key: str = "new-x", **over) -> NoticeRecord:
    """출산 농가도우미 공고를 바탕으로 글 칸만 바꾼 시험용 공고."""
    return replace(NOTICES[BIRTH], key=key, **over)


def result(*calls: ToolCall, text: str | None = None) -> GenResult:
    return GenResult(text=text, tool_calls=tuple(calls), stop="tool" if calls else "end", tok_in=0, tok_out=0,
                     latency_ms=0, provider="script", model="script")


def call(n: int, tool: str, /, **args) -> ToolCall:
    return ToolCall(call_id=f"c{n}", name=tool, args=args)


class ScriptClient:
    """정해 둔 답(GenResult 또는 예외)을 차례로 내고, 받은 요청을 모두 적어 둔다."""
    provider = model = "script"

    def __init__(self, *script):
        self.script, self.requests = list(script), []

    def generate(self, req: GenRequest) -> GenResult:
        self.requests.append(req)
        if not self.script:
            raise AssertionError("준비한 답이 모자랍니다")
        nxt = self.script.pop(0)
        if isinstance(nxt, LLMUnavailable):
            raise nxt
        return nxt


class StepClock:
    def __init__(self, step: float = 0.0):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now
