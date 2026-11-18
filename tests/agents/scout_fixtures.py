"""찾기 에이전트 시험 공용 준비물: 고정본 게시판 위치, 대본 LLM(Script), 서귀포 게시판을 도는 한 판의 대본(HAPPY)."""
from datetime import date
from pathlib import Path

from app.agents.llm.base import GenResult, ToolCall

FX = Path(__file__).resolve().parents[1] / "fixtures" / "boards"
AS_OF = date(2026, 11, 14)
SGP, JSI, FARM, DOCHE = "서귀포시 알림마당", "제주시 공지사항", "제주시 농수축산국 부서소식", "제주도청 농축산 소식"


class Script:
    """정해 둔 답을 차례로 낸다. step 은 [(도구, 인자), ...] 이거나 던질 예외, 또는 문자열(도구 없이 말만)."""
    provider = model = "script"

    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    def generate(self, req):
        self.requests.append(req)
        if not self.steps:
            raise AssertionError("대본이 모자랍니다")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        text = step if isinstance(step, str) else None
        calls = () if text else tuple(ToolCall(call_id=f"c{len(self.requests)}-{i}", name=n, args=a)
                                      for i, (n, a) in enumerate(step))
        return GenResult(text=text, tool_calls=calls, stop="tool" if calls else "end", tok_in=0, tok_out=0,
                         latency_ms=0, provider="script", model="script")


HAPPY = [
    [("list_board", {"board": SGP})],
    [("skip", {"row": [1, 2, 3, 4, 5, 9, 10], "reason": "농가 지원사업 공고가 아닌 안내·모집"}),
     ("pick", {"row": 6, "reason": "유기농업자재 지원 신청 공고"}),
     ("pick", {"row": 7, "reason": "유기질비료 추가 신청 공고"})],
    [("list_board", {"board": SGP, "query": "FTA"})],
    [("skip", {"row": [8, 13, 14, 15], "reason": "같은 사업의 읍면동 글(과 글을 고름)"}),
     ("pick", {"row": 16, "reason": "감귤유통과가 올린 원문 공고"})],
    [("finish", {"summary": "서귀포시에서 세 건을 골랐습니다"})],
]
