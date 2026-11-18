"""공고 재생(Task 32): `notice.bat --replay N1` -> python -m app.replay_cli N1.

data/replay/N1.json(녹화한 공고 답)과 data/replay/N1.txt(그 공고 글)를 `app.cli notice`에 그대로 먹인다. 실제 LLM은 만들지 않는다.
공고 글이 녹화 때와 다르면(input_hash 불일치) 호출 없이 "녹화와 입력이 다릅니다"로 멈춘다. 보고서 맨 위에 재생 띠를 단다.

`notice.bat --replay S1` 은 새 공고 찾기(`notice --scout`) 시연이다. data/replay/boards 의 고정본 게시판과 data/replay/S1.json 녹화로 돈다
(인터넷·열쇠 없음, 목록에는 올리지 않는다). 고정본이 녹화 때와 다르면 같은 말로 멈춘다.
"""
import hashlib
import html
import shutil
import sys
import tempfile
from pathlib import Path

from app import cli
from app.agents.llm.recording import ReplayClient, load_recording, write_text_atomic
from app.config import APP_ROOT
from app.data_layer.notice_board import fixture_hash, fixture_http


def _doc_hash(path: Path) -> str:
    from app.data_layer.docs_in import extract
    return hashlib.sha256(extract(path).text.encode("utf-8")).hexdigest()[:8]


def _add_banner(report: Path, banner: str) -> bool:
    text = report.read_text(encoding="utf-8")
    strip = f'<div class="banner warn" role="status">{html.escape(banner)}</div>\n'
    if "<body>" not in text:
        print("보고서에 재생 띠를 달지 못해 중단합니다. 재생 결과임을 표시할 수 없는 보고서는 내지 않습니다.")
        return False
    write_text_atomic(report, text.replace("<body>", "<body>\n" + strip, 1))
    return True


def _scout(sample: str, root: Path) -> int:
    rec_path, boards = root / "data" / "replay" / f"{sample}.json", root / "data" / "replay" / "boards"
    if not rec_path.is_file() or not (boards / "index.json").is_file():
        print("사용법: notice.bat --replay S1  (data/replay 폴더에 S1.json과 boards 폴더가 있어야 합니다)")
        return 2
    rec = load_recording(rec_path)
    client = ReplayClient(rec)
    banner = client.banner_text()
    print(banner)
    if fixture_hash(boards) != rec.input_hash:
        print(f"녹화와 입력이 다릅니다. 시연 게시판 고정본이 바뀌었습니다. 시연 {sample}을 다시 녹화하세요")
        return 1
    # 재생은 임시 폴더에서 돌린다(실제 받은 함에 읽은 글 폴더를 남기면, 나중에 진짜 찾기에서 "이미 읽음"으로 보이므로). 보고서만 가져온다
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(root / "data" / "tables", work / "data" / "tables")
        code = cli.main(["--asof", rec.as_of, "notice", "--scout", "--no-catalog"], root=work, llm=client,
                        http=fixture_http(boards), sleep=lambda s: None)
        fresh = sorted((work / "data" / "inbox").glob("scout-*"))
        if code == 0 and fresh:
            report = fresh[-1] / "report.html"
            if not _add_banner(report, banner):
                return 1
            dest = root / "data" / "inbox" / fresh[-1].name
            dest.mkdir(parents=True, exist_ok=True)
            for name in ("report.json", "report.html"):
                shutil.copyfile(fresh[-1] / name, dest / name)
    return code


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    root = Path(root) if root else APP_ROOT
    sample = argv[0] if argv else ""
    if sample.startswith("S"):
        return _scout(sample, root)
    rec_path, doc_path = (root / "data" / "replay" / f"{sample}.json", root / "data" / "replay" / f"{sample}.txt")
    if not sample.startswith("N") or not rec_path.is_file() or not doc_path.is_file():
        print("사용법: notice.bat --replay N1  (data/replay 폴더에 N1.json과 N1.txt가 있어야 합니다)")
        return 2
    rec = load_recording(rec_path)
    client = ReplayClient(rec)
    banner = client.banner_text()
    print(banner)
    if _doc_hash(doc_path) != rec.input_hash:
        print(f"녹화와 입력이 다릅니다. 시연 공고 {sample}을 고르세요")
        return 1
    code = cli.main(["notice", str(doc_path), "--no-catalog"], root=root, llm=client)
    report = root / "data" / "inbox" / cli._inbox_id(doc_path) / "report.html"
    if code == 0 and report.is_file() and not _add_banner(report, banner):
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
