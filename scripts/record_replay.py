"""재생 녹화 만들기(Task 32). data/replay/<표본>.json 을 쓴다. 형식은 app/agents/llm/recording.py.

  python scripts/record_replay.py --handwritten P1 P2 P3 P4 P5 N1 S1  손으로 쓴 답(data/replay/answers/<표본>.json)으로 만든다
  python scripts/record_replay.py --live P4                          열쇠가 있는 PC에서 실제 LLM 답을 녹화한다(source="recorded")
  python scripts/record_replay.py --live M-P1 M-P2 M-P3 M-P4 M-P5     새 공고 맞춰 보기 녹화(실제 LLM). --handwritten 도 된다(답 파일 answers/M-P1.json 의 "match" 단계)
  옵션: --asof 2026-11-13  --out data/replay  --answers data/replay/answers  --recorded-at "2026-11-08 10:00"
        --today YYYY-MM-DD  --catalog-dir data/catalog   (M-P 표본만: 맞춰 볼 새 공고를 고르는 기준일·자료 폴더)

- 표본 S1은 새 공고 찾기(`notice --scout`)다. data/replay/boards 의 고정본 게시판으로 찾기 에이전트(answers 의 scout 단계)와
  고른 글마다 공고 에이전트(answers 의 notice 단계, 고른 차례대로)를 돌려 녹화한다. 인터넷은 쓰지 않는다. input_hash 는 고정본 폴더의 지문이다.
  찾기 프롬프트나 고정본이 바뀌면 요청이 달라지므로 다시 녹화해야 한다.
- 표본 M-P1~M-P5 는 새 공고 맞춰 보기(app/agents/match.py)다. 시연 다섯 명 각각을 지금 지원 전체 보기에 올라 있는 새 공고(--catalog-dir, 기본 data/catalog)와
  맞춰 본다. 파일 이름은 M-P<번호>.json, input_hash 는 그 농가의 상담 지문(P<번호>.json 과 같다), prompt_ver 는 match-v2.
  요청에는 공고 글이 들어가므로 새 공고 목록(또는 기간 때문에 목록에서 빠지는 공고)이 바뀌면 요청이 달라져 재생이 "없음"으로 떨어진다. 그때 다시 녹화한다.
  끝까지 끝난 맞춰 보기(source="ai")만 저장한다. --today 는 앱이 목록을 만드는 '오늘'과 같게 한다(체험 모드는 상담 기준일 --asof, JEJU_SHOW_TODAY 가 있으면 그 날). 기본은 --asof 와 같다.
- 표본 P1~P5는 data/replay/demo_inputs.json 의 입력(입력 화면 값 + [받고 있음] 표시)으로 상담 근거를 만들어 narrate를 돌리고,
  N1은 tests/fixtures/notices/N1.txt 공고를 run_notice로 돌린다. 요청마다 request_hash가 달라지므로 답은 요청 순서대로 필요하다.
- --handwritten 에 답 파일이 없으면 뼈대 파일을 써 준다(구획별 근거 줄 목록과 빈 문장 칸). 사람이 문장을 채운 뒤 다시 돌린다.
  답 파일의 문장에서 {P:#k}는 그 구획 k번째 근거의 제도 id, cites의 "#k"는 그 근거의 fact_id 로 바뀐다.
  주입(검수가 반려해야 하는 일부러 나쁜 답)은 {"injected": true} 를 단다. 판정(judge) 답은 따로 없으면 통과다.
- 기준일(--asof)이 다르면 상담 지문이 달라 재생이 거절되므로 11-13 시연은 기본값 그대로 쓴다.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.counsel import PROMPT_VER as NARRATE_PROMPT_VER  # noqa: E402
from app.agents.counsel import narrate  # noqa: E402
from app.agents.llm.base import GenRequest, GenResult, LLMClient, LLMUnavailable, ToolCall  # noqa: E402
from app.agents.llm.factory import make_llm_client  # noqa: E402
from app.agents.llm.keystore import KeyStore  # noqa: E402
from app.agents.llm.null import NullClient  # noqa: E402
from app.agents.llm.payload import build_payload, input_hash  # noqa: E402
from app.agents.llm.recording import RecordedCall, Recording, save_recording, write_text_atomic  # noqa: E402
from app.agents.match import PROMPT_VER as MATCH_PROMPT_VER  # noqa: E402
from app.agents.match import run_match  # noqa: E402
from app.agents.notice import PROMPT_VER as NOTICE_PROMPT_VER  # noqa: E402
from app.agents.notice import run_notice  # noqa: E402
from app.agents.reviewer import MemoryReviewLog  # noqa: E402
from app.agents.scout import PROMPT_VER as SCOUT_PROMPT_VER  # noqa: E402
from app.agents.rules import RULES_VERSION  # noqa: E402
from app.config import load_config  # noqa: E402
from app.catalog.pool import load_pool  # noqa: E402
from app.core.models import FarmProfile  # noqa: E402
from app.core.pipeline import build_fact_sheet, fingerprint, narrative_input  # noqa: E402
from app import cli  # noqa: E402
from app.data_layer.docs_in import extract  # noqa: E402
from app.data_layer.notice_board import fixture_hash, fixture_http  # noqa: E402
from app.data_layer.snapshot import load_snapshot  # noqa: E402
from app.data_layer.supports_index import load_program_index  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402
from app.tools.models import ToolLog  # noqa: E402
from app.ui import forms  # noqa: E402

SAMPLES = ("P1", "P2", "P3", "P4", "P5", "M-P1", "M-P2", "M-P3", "M-P4", "M-P5", "N1", "S1")
BOARDS_DIR = ROOT / "data" / "replay" / "boards"       # 새 공고 찾기 시연의 고정본 게시판(tests/fixtures/boards 의 복사본)
NOTICE_FILES = {"N1": ROOT / "tests" / "fixtures" / "notices" / "N1.txt"}
PASS_VERDICT = '{"verdict": "PASS", "reason_code": null}'
PLACEHOLDER_ANSWER = "(여기에 손으로 쓴 문장을 채우세요)"


def _result(text: str | None, calls: tuple[ToolCall, ...] = (), provider="handwritten", model="demo-script") -> GenResult:
    return GenResult(text=text, tool_calls=calls, stop="tool" if calls else "end", tok_in=0, tok_out=0,
                     latency_ms=0, provider=provider, model=model)


class Recorder:
    """안쪽 클라이언트를 감싸 요청마다 (purpose, section, attempt, request_hash, response, injected)를 적는다."""

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model
        self.calls: list[RecordedCall] = []
        self._count: dict[tuple[str, str | None], int] = {}

    def generate(self, req: GenRequest) -> GenResult:
        res = self.inner.generate(req)
        key = (req.purpose, req.section)
        self._count[key] = self._count.get(key, 0) + 1
        self.calls.append(RecordedCall(
            purpose=req.purpose, section=req.section, attempt=self._count[key],
            request_hash=input_hash(build_payload(req)), response=res,
            injected=bool(getattr(self.inner, "last_injected", False))))
        return res


class HandwrittenClient:
    """답 파일(손으로 쓴 문장)을 요청 순서대로 내주는 클라이언트."""

    provider, model = "handwritten", "demo-script"

    def __init__(self, answers: dict):
        self.narrate = {k: list(v) for k, v in answers.get("narrate", {}).items()}
        self.judge = list(answers.get("judge", []))
        self.steps = list(answers.get("notice", []))
        self.scout_steps = list(answers.get("scout", []))
        self.match_steps = list(answers.get("match", []))
        self.last_injected = False

    def generate(self, req: GenRequest) -> GenResult:
        self.last_injected = False
        if req.purpose == "judge":
            return _result(self.judge.pop(0) if self.judge else PASS_VERDICT)
        if req.purpose in ("notice", "scout", "match"):
            steps = {"notice": self.steps, "scout": self.scout_steps, "match": self.match_steps}[req.purpose]
            if not steps:
                raise LLMUnavailable("BAD_OUTPUT", f"손으로 쓴 {req.purpose} 답이 모자랍니다")
            step = steps.pop(0)
            calls = tuple(ToolCall(call_id=f"h{i}", name=c["name"], args=c["args"]) for i, c in enumerate(step["tool_calls"], 1))
            return _result(step.get("text"), calls)
        queue = self.narrate.get(req.section or "", [])
        if not queue:
            raise LLMUnavailable("BAD_OUTPUT", f"{req.section} 구획의 손으로 쓴 답이 모자랍니다")
        entry = queue.pop(0)
        self.last_injected = bool(entry.get("injected"))
        items = json.loads(req.messages[0].text.split("\n\n")[0])["items"]
        return _result(json.dumps(_section_json(req.section, entry["sentences"], items), ensure_ascii=False))


def _section_json(section: str | None, sentences: list[dict], items: list[dict]) -> dict:
    def sub(text: str) -> str:
        for k in range(len(items), 0, -1):
            text = text.replace(f"#{k}", "\0%d\0" % k)
        for k, item in enumerate(items, 1):
            text = text.replace("\0%d\0" % k, item["program_id"])
        return text

    def cite(c: str) -> str:
        return items[int(c[1:]) - 1]["fact_id"] if c.startswith("#") else c

    return {"section": section, "sentences": [
        {"sid": n, "text": sub(s["text"]), "cites": [cite(c) for c in s["cites"]]} for n, s in enumerate(sentences, 1)]}


# --- 표본 만들기 -------------------------------------------------------------------------------------

def demo_fact_sheet(sample: str, asof: str):
    cfg = load_config(["--asof", asof])
    demo = json.loads((ROOT / "data" / "replay" / "demo_inputs.json").read_text(encoding="utf-8"))[sample]
    profile = forms.to_profile(demo["form"], proxy=False)
    if isinstance(profile, dict):
        raise SystemExit(f"{sample}: 시연 입력이 입력 검사를 통과하지 못했습니다: {dict(profile)}")
    profile = FarmProfile.model_validate({**profile.model_dump(), "already_receiving": demo["already"]})
    tables = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=tables.crops)
    version = f"표{tables.verified_date.isoformat()}+저장본{snap.built_at.isoformat()}"
    return build_fact_sheet(profile, tables, snap, cfg.as_of, version, demo_asof=cfg.demo_asof)


def scaffold(sample: str, fs) -> dict:
    ctx = narrative_input(fs)
    sections = {}
    for kind in ("support", "insurance", "action", "empty"):
        items = [i for i in ctx.items if i.section == kind]
        if items:
            sections[kind] = {"근거": [f"#{n} {i.fact_id} {i.official_name} {i.status}" for n, i in enumerate(items, 1)],
                              "문장 예": [{"sentences": [{"text": "{P:#1} …", "cites": ["#1"]}]}]}
    return {"설명": "narrate.<구획> 에 답을 순서대로 적으세요(처음 답, 반려될 때를 위한 다시 쓴 답…). 아래 '근거'를 보고 채웁니다.",
            "참고": sections, "narrate": {}}


def record_counsel(sample: str, client: LLMClient, asof: str) -> tuple[Recorder, str]:
    fs = demo_fact_sheet(sample, asof)
    rec = Recorder(client)
    narrate(fs, rec, MemoryReviewLog())
    return rec, fingerprint(fs)


def record_match(sample: str, client: LLMClient, asof: str, today: date | None = None,
                 catalog_dir: Path | None = None) -> tuple[Recorder, str]:
    """M-P<번호>: 시연 농가를 지금 목록의 새 공고와 맞춰 본다. 끝까지 끝나지 않았으면(없음·건너뜀) 저장할 게 없으므로 LLMUnavailable."""
    cfg = load_config(["--asof", asof])
    fs = demo_fact_sheet(sample[2:], asof)
    tables = load_tables(cfg.tables_dir, cfg.as_of)
    pool = load_pool(catalog_dir if catalog_dir is not None else ROOT / "data" / "catalog", tables, today or cfg.as_of)
    rec = Recorder(client)
    report = run_match(fs.profile, fs, [n for n, _ in pool], tables.crops, rec, ToolLog(), as_of=cfg.as_of)
    if report.source != "ai":
        raise LLMUnavailable("BAD_OUTPUT", f"맞춰 보기를 끝까지 돌리지 못했습니다: {report.note}")
    return rec, fingerprint(fs)


def record_notice(sample: str, client: LLMClient) -> tuple[Recorder, str]:
    path = NOTICE_FILES[sample]
    doc = extract(path)
    rec = Recorder(client)
    run_notice(doc, load_program_index(ROOT / "data" / "tables"), rec, ToolLog())
    return rec, hashlib.sha256(doc.text.encode("utf-8")).hexdigest()[:8]


def record_scout(client: LLMClient, asof: str) -> tuple[Recorder, str]:
    """고정본 게시판으로 `notice --scout --no-catalog` 를 돌린다(인터넷 없음). 임시 폴더에서 돌려 저장소에 아무것도 남기지 않는다."""
    rec = Recorder(client)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(ROOT / "data" / "tables", root / "data" / "tables")
        code = cli.main(["--asof", asof, "notice", "--scout", "--no-catalog"], root=root, llm=rec,
                        http=fixture_http(BOARDS_DIR), sleep=lambda s: None)
    if code != 0:
        raise LLMUnavailable("BAD_OUTPUT", "찾기를 끝까지 돌리지 못했습니다")
    return rec, fixture_hash(BOARDS_DIR)


def build_recording(sample: str, rec: Recorder, source: str, in_hash: str, asof: str, when: datetime) -> Recording:
    prompt = MATCH_PROMPT_VER if sample.startswith("M-") else SCOUT_PROMPT_VER if sample.startswith("S") else NOTICE_PROMPT_VER if sample.startswith("N") else NARRATE_PROMPT_VER
    return Recording(sample_id=sample, recorded_at=when, source=source, provider=rec.provider, model=rec.model,
                     prompt_ver=prompt, rules_ver=RULES_VERSION, as_of=asof, input_hash=in_hash, calls=tuple(rec.calls))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="재생 녹화 만들기")
    p.add_argument("samples", nargs="+", choices=SAMPLES)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--handwritten", action="store_true")
    mode.add_argument("--live", "--real", dest="live", action="store_true")
    p.add_argument("--asof", default="2026-11-13")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "replay")
    p.add_argument("--answers", type=Path, default=ROOT / "data" / "replay" / "answers")
    p.add_argument("--today", type=date.fromisoformat, default=None, help="M-P 표본: 새 공고 목록의 '오늘'(기본: --asof 와 같음. 체험 모드 앱이 세는 오늘과 같다)")
    p.add_argument("--catalog-dir", type=Path, default=None, help="M-P 표본: 지원 전체 보기 자료 폴더(기본 data/catalog)")
    p.add_argument("--recorded-at", default=None, help='예: "2026-11-08 10:00" (기본: 지금)')
    args = p.parse_args(argv)
    when = datetime.strptime(args.recorded_at, "%Y-%m-%d %H:%M") if args.recorded_at else datetime.now().replace(second=0, microsecond=0)

    for sample in args.samples:
        if args.live:
            client = make_llm_client(KeyStore(), today_fn=lambda: load_config(["--asof", args.asof]).as_of)
            if isinstance(client, NullClient):
                print("열쇠가 없어 실제 녹화를 할 수 없습니다. keys.bat 으로 키를 넣은 뒤 다시 하세요.")
                return 1
        else:
            answer_file = args.answers / f"{sample}.json"
            if not answer_file.is_file():
                skeleton = scaffold(sample, demo_fact_sheet(sample, args.asof)) if sample.startswith("P") else \
                    {"설명": "match 에 도구 호출 단계를 적으세요(check_farmer 묶음, submit_matches).", "match": []} if sample.startswith("M-") else \
                    {"설명": "scout(찾기)·notice(고른 글 읽기)에 도구 호출 단계를 적으세요.", "scout": [], "notice": []} if sample.startswith("S") else {"설명": "notice 에 도구 호출 단계를 적으세요.", "notice": []}
                write_text_atomic(answer_file, json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n")
                print(f"{sample}: 답 파일이 없어 뼈대를 만들었습니다 -> {answer_file}. 문장을 채우고 다시 실행하세요.")
                continue
            client = HandwrittenClient(json.loads(answer_file.read_text(encoding="utf-8")))
        try:
            if sample.startswith("S"):
                rec, in_hash = record_scout(client, args.asof)
            elif sample.startswith("M-"):
                rec, in_hash = record_match(sample, client, args.asof, args.today, args.catalog_dir)
            else:
                rec, in_hash = record_notice(sample, client) if sample.startswith("N") else record_counsel(sample, client, args.asof)
        except LLMUnavailable as e:
            print(f"{sample}: LLM을 쓸 수 없어 중단했습니다({e.reason}).")
            return 1
        recording = build_recording(sample, rec, "recorded" if args.live else "handwritten", in_hash, args.asof, when)
        if args.live and not recording.calls:
            print(f"{sample}: LLM 호출이 하나도 없어 녹화하지 않았습니다.")
            return 1
        if recording.source == "recorded":     # 실제 호출 녹화의 제공자·모델은 응답이 알려 준다
            last = recording.calls[-1].response
            recording = recording.model_copy(update={"provider": last.provider, "model": last.model})
        save_recording(recording, args.out / f"{sample}.json")
        print(f"{sample}: 호출 {len(recording.calls)}개 -> {args.out / (sample + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
