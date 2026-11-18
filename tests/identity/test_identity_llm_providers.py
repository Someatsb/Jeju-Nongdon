"""Task 35 (E3-E5, E18): 제공자가 무엇을 말해도 종이의 숫자는 그대로다.

골든 케이스 x 네 제공자 {Null, Scripted-정상, Scripted-1회 오염, Scripted-전부 오염}.
각 케이스에서 계산 지문, 종이의 span.num 목록((data-source, data-asof, 글) 순서대로), 설명 문장 밖의 HTML이 같고,
검수 기록이 기대한 시도 수·출처(템플릿 / 1 / 2 / 템플릿)를 보인다. 네트워크는 건드리지 않는다.
오염 답은 검수 규칙 시험 자료(tests/fixtures/review/bad.jsonl)의 B13(상인-농협 비교)·B21(권리형) 글이다.
골든 14 중 G13·G14는 Task 34가 아직 이 트리에 넣지 않아 12건이다(생기면 자동으로 포함한다).
"""
import html as htmllib
import json
import socket
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "golden"))
from golden_adapter import CASES_DIR, build_paper, load_case, to_profile  # noqa: E402

from app.agents.counsel import narrate  # noqa: E402
from app.agents.llm import anthropic_adapter  # noqa: E402
from app.agents.llm.base import GenRequest, GenResult  # noqa: E402
from app.agents.llm.null import NullClient  # noqa: E402
from app.agents.llm.payload import build_payload, input_hash  # noqa: E402
from app.agents.llm.scripted import RecordedCall, Recording, ScriptedClient  # noqa: E402
from app.agents.reviewer import MemoryReviewLog  # noqa: E402
from app.config import load_config  # noqa: E402
from app.core.pipeline import fingerprint  # noqa: E402
from app.data_layer.snapshot import load_snapshot  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402
from app.ui.preflight import _nums, _parse  # noqa: E402
from app.ui.render import render_sheet  # noqa: E402

GOLDEN = ["P1", "P2", "P3", "P4", "P5", "T1", "T2", "B02", "B04", "B05", "B06", "B12"] + \
    [c for c in ("G13", "G14") if (CASES_DIR / f"{c}.json").is_file()]
PROVIDERS = ("null", "scripted_good", "scripted_one_bad", "scripted_all_bad")
EXPECT_SOURCE = {"null": "template", "scripted_good": "ai_pass", "scripted_one_bad": "ai_pass", "scripted_all_bad": "template"}
EXPECT_ATTEMPTS = {"null": 0, "scripted_good": 1, "scripted_one_bad": 2, "scripted_all_bad": 3}
PASS = '{"verdict": "PASS", "reason_code": null}'
# 오염 답(검수 시험 자료 B13, B21의 글). 첫 구획은 B13, 둘째는 B21 ...
BAD_B13 = "상인에게 넘기시는 것보다 농협에 내시는 게 낫습니다."
BAD_B21 = "{P:%s}을 받으실 수 있습니다."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """실제 호출 길은 막는다: 소켓 연결과 AnthropicClient 생성이 일어나면 시험이 실패한다."""
    def boom(*a, **k):
        raise AssertionError("시험이 네트워크를 건드렸습니다")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(anthropic_adapter.AnthropicClient, "__init__", boom)


def _result(text: str) -> GenResult:
    return GenResult(text=text, tool_calls=(), stop="end", tok_in=0, tok_out=0, latency_ms=0,
                     provider="scripted-test", model="identity")


class Composer:
    """정책에 따라 답을 짓고 (요청 해시 -> 답)을 모은다. 모은 것이 ScriptedClient의 녹화가 된다."""
    provider, model = "scripted-test", "identity"

    def __init__(self, policy: str):
        self.policy = policy
        self.calls: list[RecordedCall] = []
        self._tries: dict[str, int] = {}
        self._order: list[str] = []

    def generate(self, req: GenRequest) -> GenResult:
        if req.purpose == "judge":
            res = _result(PASS)
        else:
            kind = req.section or ""
            if kind not in self._order:
                self._order.append(kind)
            n = self._tries[kind] = self._tries.get(kind, 0) + 1
            items = json.loads(req.messages[0].text.split("\n\n")[0])["items"]
            bad = self.policy == "all_bad" or (self.policy == "one_bad" and n == 1)
            res = _result(json.dumps(self._answer(kind, items, bad), ensure_ascii=False))
        self.calls.append(RecordedCall(input_hash=input_hash(build_payload(req)), response=res))
        return res

    def _answer(self, kind: str, items: list[dict], bad: bool) -> dict:
        first = items[0]
        if bad:
            text = BAD_B13 if self._order.index(kind) % 2 == 0 else BAD_B21 % first["program_id"]
            sentences = [{"sid": 1, "text": text, "cites": [first["fact_id"]]}]
        else:
            sentences = [{"sid": k, "text": "{P:%s}은 창구에서 알아보세요." % i["program_id"], "cites": [i["fact_id"]]}
                         for k, i in enumerate(items[:3], 1)]
        return {"section": kind, "sentences": sentences}


def make_client(provider: str, fs):
    if provider == "null":
        return NullClient()
    composer = Composer({"scripted_good": "good", "scripted_one_bad": "one_bad", "scripted_all_bad": "all_bad"}[provider])
    narrate(fs, composer, MemoryReviewLog())          # 요청 해시별 답을 모은다
    rec = Recording(provider=composer.provider, model=composer.model, recorded_at=datetime(2026, 11, 8, 9, 0),
                    calls=tuple(composer.calls))
    return ScriptedClient(rec)                        # 이후에는 이 녹화만 쓴다(해시로 찾음)


@pytest.fixture(scope="module")
def env():
    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    return cfg, bundle, load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)


@pytest.fixture(scope="module")
def runs(env):
    """케이스 x 제공자의 결과를 한 번씩만 만든다."""
    cfg, bundle, snap = env
    cache: dict = {}

    def get(case: str, provider: str) -> dict:
        key = (case, provider)
        if key not in cache:
            fs, sheet, _ = build_paper(to_profile(load_case(case)["profile"]), bundle, snap, cfg)
            log = MemoryReviewLog()
            narrative = narrate(fs, make_client(provider, fs), log)
            html = render_sheet(sheet, fs, narrative.texts(), cfg, crop_labels={c.crop_code: c.label for c in bundle.crops})
            cache[key] = {"fs": fs, "narrative": narrative, "log": log, "html": html}
        return cache[key]
    return get


def num_spans(html: str) -> list[tuple[str, str, str]]:
    return [(n.attrs.get("data-source", ""), n.attrs.get("data-asof", ""), n.text()) for n in _nums([_parse(html)])]


def without_narrative(html: str, narrative) -> str:
    out = html
    for sentences in narrative.texts().values():
        for s in sentences:
            out = out.replace(htmllib.escape(s), "@@")
    return out


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", GOLDEN)
def test_fingerprint_and_numbers_identical(case, provider, runs):
    base, run = runs(case, "null"), runs(case, provider)
    assert fingerprint(run["fs"]) == fingerprint(base["fs"]), f"{case}/{provider}: 계산 지문이 다릅니다"
    assert num_spans(run["html"]) == num_spans(base["html"]), f"{case}/{provider}: span.num 목록이 다릅니다"
    assert num_spans(base["html"]), f"{case}: 종이에 숫자 칸이 하나도 없습니다(시험이 비어 있음)"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", GOLDEN)
def test_html_differs_only_in_narrative(case, provider, runs):
    base, run = runs(case, "null"), runs(case, provider)
    assert without_narrative(run["html"], run["narrative"]) == without_narrative(base["html"], base["narrative"]), \
        f"{case}/{provider}: 설명 문장 밖의 HTML이 다릅니다"
    for sentences in run["narrative"].texts().values():
        assert not any(ch.isdigit() for s in sentences for ch in s), f"{case}/{provider}: 설명 문장에 숫자"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", GOLDEN)
def test_review_log_shows_expected_attempts_and_source(case, provider, runs):
    run = runs(case, provider)
    outcomes = run["narrative"].sections
    assert outcomes, f"{case}: 설명 구획이 없습니다"
    for kind, o in outcomes.items():
        assert o.source == EXPECT_SOURCE[provider], f"{case}/{provider}/{kind}: 출처 {o.source}"
        assert o.attempts == EXPECT_ATTEMPTS[provider], f"{case}/{provider}/{kind}: 시도 {o.attempts}"
    entries = run["log"].entries
    if provider == "scripted_one_bad":
        first = {e["section"]: [c["rule"] for c in e["checks"]] for e in entries if e.get("attempt") == 1}
        assert all(r and r[0] in ("COMPARE", "RIGHTS") for r in first.values()), f"{case}: 오염 답이 반려되지 않음 {first}"
    if provider == "scripted_all_bad":
        assert [e["verdict"] for e in entries].count("TEMPLATE") == len(outcomes)
    if provider == "null":
        assert all(e["verdict"] == "SKIPPED" for e in entries)


@pytest.mark.parametrize("case", GOLDEN)
def test_good_provider_actually_writes_sentences(case, runs):
    """시험이 허공을 치지 않게: 정상 제공자의 설명 문장은 템플릿과 다르다. 결과가 있는 종이에는 AI 문장이 없으므로(2026-11-18 결론 상자 없앰) 종이는 같고, 문장은 화면 맨 위 띠에만 간다."""
    good, null = runs(case, "scripted_good"), runs(case, "null")
    assert good["narrative"].mode == "ai" and null["narrative"].mode == "template"
    assert good["narrative"].texts() != null["narrative"].texts()
    empty = 'class="sheet front empty' in good["html"]
    assert (good["html"] != null["html"]) if empty else (good["html"] == null["html"])      # 빈 종이(T1·T2)만 설명 문장이 찍힌다
