"""run_tests.bat이 부른다(Task 27): 시험 전체를 돌리고 tests/REPORT.txt 에 결과를 적는다.

`--golden`: 골든 1차 12건만 돌려 "골든 N/12 통과"를 한 줄로 보이고 REPORT.txt는 건드리지 않는다(전체 시험 결과를 덮지 않게).
REPORT.txt = 시각 · pytest 마지막 줄 · "golden N/12 passed"(12건 모두 통과일 때만 "golden 12 passed").
XFAIL(Task 34로 넘긴 골든)은 통과로 세지 않는다. 종료 코드는 pytest 그대로.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_12 = ("P1", "P2", "P3", "P4", "P5", "T1", "T2", "B02", "B04", "B05", "B06", "B12")
# Task 34: preflight 기준 HTML을 다시 써서(tests/preflight_support.py) 제외 목록이 비었다.
DESELECT: tuple[str, ...] = ()


def golden_passed(junit: Path) -> int:
    passed = 0
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = case.get("name", "")
        if name.startswith("test_golden[") and name[len("test_golden["):-1] in GOLDEN_12:
            if not any(child.tag in ("failure", "error", "skipped") for child in case):
                passed += 1
    return passed


def main(extra: list[str]) -> int:
    junit = ROOT / "tests" / ".junit.xml"
    cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-W", "error", f"--junitxml={junit}", "-p", "no:cacheprovider"]
    golden_only = "--golden" in extra
    extra = [a for a in extra if a != "--golden"]
    if golden_only:
        extra = ["tests/golden/test_golden.py", *extra]
    for d in ([] if golden_only else DESELECT):
        cmd += ["--deselect", d]
    proc = subprocess.run(cmd + extra, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    summary = lines[-1] if lines else "(출력 없음)"
    n = golden_passed(junit) if junit.exists() else 0
    golden = "golden 12 passed" if n == 12 else f"golden {n}/12 passed"
    if golden_only:
        print(f"\n골든 {n}/12 통과")
        return proc.returncode if n == 12 else (proc.returncode or 1)
    report = ROOT / "tests" / "REPORT.txt"
    note = (f"(알려진 제외 {len(DESELECT)}건: {', '.join(DESELECT)})" if DESELECT else
            "(errors는 tests/ui 이벤트 루프 정리 때의 알려진 플레이크일 수 있다: 다시 돌려 확인)")
    report.write_text(f"{datetime.now():%Y-%m-%d %H:%M} \n{summary}\n{golden}\n{note}\n", encoding="utf-8", newline="\n")
    print(f"\n{golden} · 결과는 tests/REPORT.txt")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
