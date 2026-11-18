"""샘플 종이 만들기(Task 27): samples/P1~P5/{input.json, print.html, print.pdf}.

골든 P1~P5의 프로필로 실제 계산 → 종이(설명 문장 없음, narrative=None)를 만들고, Edge를 화면 없이 돌려 PDF로 저장한다.
Edge가 없으면 HTML만 쓰고 NO_PDF.txt 에 이유를 적는다. 키·인터넷은 쓰지 않는다.
실행: python -X utf8 scripts/make_samples.py [--asof 2026-11-13] [--only P1,P2] [--no-pdf]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests" / "golden")]

from golden_adapter import build_paper, load_case, to_profile  # noqa: E402

from app.config import load_config  # noqa: E402
from app.data_layer.snapshot import load_snapshot  # noqa: E402
from app.data_layer.tables import load_tables  # noqa: E402
from app.ui.preflight import preflight  # noqa: E402

SAMPLES = ROOT / "samples"
CASES = ("P1", "P2", "P3", "P4", "P5")
# 시연 농가(재생 모드) P5 는 확인 화면에서 "이미 받고 계신 지원"에 제주 농민수당만 눌렀다(data/replay/demo_inputs.json). 골든 P5 는 농민수당·면적직불금 둘이라 표가 길어 종이가 2쪽이 된다.
# 샘플 P5 는 시연 농가와 같게 받고 있는 지원을 농민수당만으로 한다(input.json 에 이 값이 그대로 적힌다). 계산 규칙은 건드리지 않는다.
DEMO_PROFILE = {"P5": {"already_receiving": frozenset({"JEJU-FARMER-ALLOW"})}}
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
NO_PDF_NOTE = ("PDF를 만들지 못했습니다: 이 PC에서 Edge(msedge.exe)를 찾지 못했습니다.\n"
               "print.html 을 Edge나 크롬으로 열어 Ctrl+P → 'PDF로 저장'(용지 A4, 머리글·바닥글 끔)으로 저장하세요.\n")


def find_edge() -> str | None:
    return shutil.which("msedge") or next((p for p in EDGE_PATHS if Path(p).exists()), None)


def html_to_pdf(edge: str, html: Path, pdf: Path, wait_s: float = 25) -> bool:
    """Edge 화면 없는 모드로 PDF 저장. 성공하면 True."""
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="edge_profile_", ignore_cleanup_errors=True) as profile:
        cmd = [edge, "--headless", "--disable-gpu", f"--user-data-dir={profile}", "--no-first-run",
               f"--print-to-pdf={pdf}", "--no-pdf-header-footer", html.resolve().as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, timeout=wait_s)
        except subprocess.TimeoutExpired:
            pass
        end = time.time() + 5
        while time.time() < end and not (pdf.exists() and pdf.stat().st_size > 0):
            time.sleep(0.2)
    return pdf.exists() and pdf.stat().st_size > 0


def main(argv: list[str]) -> int:
    asof = argv[argv.index("--asof") + 1] if "--asof" in argv else "2026-11-13"
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else list(CASES)
    want_pdf = "--no-pdf" not in argv
    cfg = load_config(["--asof", asof])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    edge = find_edge() if want_pdf else None
    failures = 0
    for case_id in only:
        t0 = time.perf_counter()
        profile = to_profile(load_case(case_id)["profile"]).model_copy(update=DEMO_PROFILE.get(case_id, {}))
        fs, _sheet, html = build_paper(profile, bundle, snap, cfg)
        problems = preflight(html, fs, cfg)
        out = SAMPLES / case_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "input.json").write_text(json.dumps({"case_id": case_id, "as_of": asof, "profile": profile.model_dump(mode="json")},
                                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        (out / "print.html").write_text(html, encoding="utf-8", newline="\n")
        note = out / "NO_PDF.txt"
        status = "PDF 건너뜀"
        if want_pdf and edge:
            ok = html_to_pdf(edge, out / "print.html", out / "print.pdf")
            status = "PDF 저장" if ok else "PDF 실패(Edge가 파일을 만들지 못함)"
            failures += not ok
            note.unlink(missing_ok=True)
        elif want_pdf:
            note.write_text(NO_PDF_NOTE, encoding="utf-8", newline="\n")
            status = "Edge 없음, NO_PDF.txt 작성"
        print(f"{case_id}: 종이 {len(html):,}자 · 사전 점검 {'통과' if not problems else problems} · {status} · {time.perf_counter() - t0:.1f}초",
              flush=True)
        failures += bool(problems)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
