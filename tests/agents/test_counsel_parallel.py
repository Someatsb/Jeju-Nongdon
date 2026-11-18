"""설명 단계 구획 동시 실행(narrate parallel=True): 시간은 줄고 결과·로그 순서는 차례대로와 같다."""
import threading
import time

from counsel_fixtures import FS_P4, CTX_P4, good_section, recording

from app.agents.counsel import ORDER, narrate
from app.agents.llm.base import GenResult
from app.agents.llm.scripted import ScriptedClient
from app.agents.reviewer import MemoryReviewLog

PASS_V = '{"verdict": "PASS", "reason_code": null}'
SLEEP_S = 0.2


class SleepyClient:
    """호출마다 SLEEP_S초 잠든다. 설명은 녹화 답, 판정은 통과. boom 구획의 설명 호출은 예외를 낸다."""
    provider, model = "rec", "rec"

    def __init__(self, boom: str | None = None) -> None:
        self.scripted = ScriptedClient(recording(CTX_P4, {k: [good_section(k)] for k in ORDER}))
        self.boom, self.lock, self.threads = boom, threading.Lock(), set()

    def generate(self, req):
        with self.lock:
            self.threads.add(threading.get_ident())
        time.sleep(SLEEP_S)
        if req.section == self.boom and req.purpose == "narrate":
            raise RuntimeError("일부러 낸 오류")
        if req.purpose == "judge":
            return GenResult(text=PASS_V, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0, provider="rec", model="rec")
        return self.scripted.generate(req)


def run(parallel, client=None):
    log, client = MemoryReviewLog(), client or SleepyClient()
    t0 = time.monotonic()
    n = narrate(FS_P4, client, log, parallel=parallel)
    return n, log, time.monotonic() - t0, client


def test_parallel_faster_and_same_result():
    seq, seq_log, seq_t, _ = run(False)
    par, par_log, par_t, c = run(True)
    assert seq_t >= 6 * SLEEP_S * 0.95 and par_t < seq_t * 0.6      # 호출 6번 직렬 / 세 줄 병렬
    assert len(c.threads) >= 2                                      # 실제로 여러 스레드에서 돌았다
    assert par.mode == seq.mode == "ai" and list(par.sections) == list(seq.sections) == list(ORDER)
    for k in ORDER:
        a, b = par.sections[k], seq.sections[k]
        assert (a.source, a.attempts, a.final) == (b.source, b.attempts, b.final)
    assert par.texts() == seq.texts() and par_log.entries == seq_log.entries
    assert [e["section"] for e in par_log.entries] == list(ORDER)    # 로그도 구획 순서


def test_parallel_one_section_error_others_pass():
    n, log, _, _ = run(True, SleepyClient(boom="insurance"))
    assert n.sections["support"].source == "ai_pass" and n.sections["action"].source == "ai_pass"
    assert n.sections["insurance"].source == "template" and n.mode == "mixed"
    assert [e["section"] for e in log.entries][:1] == ["support"]
    assert any(e["section"] == "insurance" and e["verdict"] == "SKIPPED" for e in log.entries)


def test_parallel_budget_shared_all_template():
    log = MemoryReviewLog()
    n = narrate(FS_P4, SleepyClient(), log, parallel=True, budget_s=0.0)   # 시작 즉시 예산 초과
    assert n.mode == "template" and all(o.source == "template" for o in n.sections.values())


def test_guard_counts_threads_safely():
    from datetime import date
    from app.agents.llm.guard import Guard
    g = Guard(SleepyClient(), daily_cap=1000, today_fn=lambda: date(2026, 11, 13))
    req = __import__("counsel_fixtures").build_request("support", CTX_P4)
    ts = [threading.Thread(target=lambda: [g.generate(req) for _ in range(3)]) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert g._calls == 18
