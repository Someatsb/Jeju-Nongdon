"""하루 상한·설명 예산(Task 9, U09) — round1-C-agent.md §6-3의 DAILY_CAP, §4-3의 설명 예산 45초.

Guard는 LLMClient 장식자다(generate(req), provider·model은 안쪽 클라이언트 것을 그대로 보인다).
- 하루 상한: 날짜는 today_fn()으로 묻는다(구성 지점이 config.as_of를 넘긴다, 기본값 없음). 안에서 시계를
  읽지 않는다. 상한에 닿으면 LLMUnavailable("DAILY_CAP") — 그날은 템플릿. 상한으로 거절한 호출은 세지 않는다.
- 설명 예산: `with guard.budget():`가 상담 한 번의 설명 단계 동안 budget_s초 창을 열고 끝나면 닫는다.
  창이 열린 채 budget_s초가 지나면 새 호출을 LLMUnavailable("TIMEOUT")으로 거절한다 → 남은 구획은 템플릿.
  이미 나간 호출은 끊지 않는다(그 호출의 timeout_s가 상한). 창 밖에서는 예산이 없다.
  start_budget()은 창을 열기만 하는 얇은 별칭이다. 경과 시간은 넘겨받은 clock(기본 time.monotonic)으로 잰다.
- 연속 실패 차단(CIRCUIT_OPEN)·재시도·오류 분류는 이 Task 범위 밖이다(재시도는 SDK max_retries=1, Task 31).
"""
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date

from app.agents.llm.base import GenRequest, GenResult, LLMClient, LLMUnavailable


class Guard:
    def __init__(self, client: LLMClient, daily_cap: int = 200, budget_s: float = 45, *,
                 today_fn: Callable[[], date], clock: Callable[[], float] = time.monotonic):
        self.client = client
        self.daily_cap = daily_cap
        self.budget_s = budget_s
        self._today_fn = today_fn
        self._clock = clock
        self._day: date | None = None
        self._calls = 0
        self._budget_start: float | None = None
        self._lock = threading.Lock()   # 구획을 동시에 돌릴 때(counsel.narrate parallel=True) 하루 호출 수를 안전하게 센다

    @property
    def provider(self) -> str:
        return self.client.provider

    @property
    def model(self) -> str:
        return self.client.model

    @contextmanager
    def budget(self) -> Iterator[None]:
        self.start_budget()
        try:
            yield
        finally:
            self._budget_start = None

    def start_budget(self) -> None:
        self._budget_start = self._clock()

    def exhausted(self) -> bool:
        """오늘 이미 하루 상한에 닿았나(인터넷 판 직원 화면이 미리 묻는다). 세지는 않는다."""
        with self._lock:
            today = self._today_fn()
            if today != self._day:
                self._day, self._calls = today, 0
            return self._calls >= self.daily_cap

    def generate(self, req: GenRequest) -> GenResult:
        with self._lock:
            today = self._today_fn()
            if today != self._day:
                self._day, self._calls = today, 0
            if self._calls >= self.daily_cap:
                raise LLMUnavailable("DAILY_CAP")
            if self._budget_start is not None and self._clock() - self._budget_start >= self.budget_s:
                raise LLMUnavailable("TIMEOUT", "설명 예산을 다 썼습니다")
            self._calls += 1
        return self.client.generate(req)  # 잠금 밖: 호출이 오래 걸려도 다른 구획이 기다리지 않는다


class SideCap:
    """맞춰 보기·새 공고 찾아보기가 함께 쓰는 하루 호출 한도(LLMClient 장식자). 설명 글이 쓰는 Guard 의 하루 한도 안쪽에서 이 몫만 쓰게 해,
    되풀이해 누르거나 찾아보기를 자주 눌러도 어르신 설명 글 몫이 닳지 않게 한다. 한도에 닿으면 LLMUnavailable("DAILY_CAP")이고
    거절한 호출은 세지 않는다. 날짜는 today_fn() 으로 묻는다(안에서 시계를 읽지 않는다)."""

    def __init__(self, client: LLMClient, cap: int, *, today_fn: Callable[[], date]):
        self.client, self.cap, self._today_fn = client, cap, today_fn
        self._day: date | None = None
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def provider(self) -> str:
        return self.client.provider

    @property
    def model(self) -> str:
        return self.client.model

    def exhausted(self) -> bool:
        with self._lock:
            today = self._today_fn()
            if today != self._day:
                self._day, self._calls = today, 0
            return self._calls >= self.cap

    def generate(self, req: GenRequest) -> GenResult:
        with self._lock:
            today = self._today_fn()
            if today != self._day:
                self._day, self._calls = today, 0
            if self._calls >= self.cap:
                raise LLMUnavailable("DAILY_CAP")
            self._calls += 1
        return self.client.generate(req)
