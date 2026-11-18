"""새 공고 맞춰 보기 시험 실행(설계서 2026-11-14 1절).

  python scripts/try_match.py P4                     AI 를 부르지 않고 첫 요청(시스템 글·첫 메시지·도구 정의)을 화면에 찍는다
  python scripts/try_match.py P4 --notices 폴더        공고 폴더를 바꾼다(기본 data/catalog/notices)
  python scripts/try_match.py P4 --live              실제 AI 로 돌려 결과(MatchReport)를 찍는다(열쇠가 있는 PC에서 부장만 쓴다)
  옵션: --asof 2026-11-13

표본 P1~P5 는 data/replay/demo_inputs.json 의 입력이다(scripts/record_replay.py 의 demo_fact_sheet).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from record_replay import demo_fact_sheet  # noqa: E402

from app.agents.match import PROMPT_PATH, _tool_defs, opening_text, run_match, screen_notices  # noqa: E402
from app.catalog.notices import load_notices  # noqa: E402
from app.config import load_config  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402
from app.tools.match_tools import MatchTools  # noqa: E402
from app.tools.models import ToolLog  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="새 공고 맞춰 보기 시험 실행")
    p.add_argument("sample", choices=("P1", "P2", "P3", "P4", "P5"))
    p.add_argument("--notices", type=Path, default=ROOT / "data" / "catalog" / "notices")
    p.add_argument("--asof", default="2026-11-13")
    p.add_argument("--live", action="store_true", help="실제 AI 로 돌린다(부장만 쓴다)")
    args = p.parse_args(argv)

    cfg = load_config(["--asof", args.asof])
    fs = demo_fact_sheet(args.sample, args.asof)
    crops = load_tables(cfg.tables_dir, cfg.as_of).crops
    notices = load_notices(args.notices)
    print(f"표본 {args.sample} · 기준일 {cfg.as_of.isoformat()} · 공고 폴더의 공고 {len(notices)}건")

    if not args.live:
        seen = screen_notices(notices, fs, cfg.as_of)[:8]
        if not seen:
            print("프로그램이 거른 뒤 볼 공고가 없어 AI 를 부르지 않습니다(source=skipped).")
            return 0
        tools = MatchTools(fs.profile, seen, crops, cfg.as_of)
        print("\n===== 시스템 글 =====")
        print(PROMPT_PATH.read_text(encoding="utf-8"))
        print("===== 첫 메시지 =====")
        print(opening_text(seen, crops))
        print("\n===== 도구 정의 =====")
        for d in _tool_defs(tools):
            print(f"- {d.name}: {d.description}")
            print(json.dumps(d.input_schema, ensure_ascii=False, indent=2))
        return 0

    from app.agents.llm.factory import make_llm_client
    from app.agents.llm.keystore import KeyStore
    from app.agents.llm.null import NullClient

    client = make_llm_client(KeyStore(), today_fn=lambda: cfg.as_of)
    if isinstance(client, NullClient):
        print("열쇠가 없어 실제 AI 로 돌릴 수 없습니다. keys.bat 으로 키를 넣은 뒤 다시 하세요.")
        return 1
    log = ToolLog()
    report = run_match(fs.profile, fs, notices, crops, client, log, as_of=cfg.as_of)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\n도구를 쓴 횟수 {log.tool_calls}번")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
