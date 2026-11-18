"""설치 점검(Task 27): 12가지를 보고 [통과]/[주의]/[오류]로 한국어로 알린다. 오류가 하나라도 있으면 종료 코드 1.

주의(경고)는 인쇄·키·Edge처럼 없어도 화면과 HTML 종이는 되는 것들이다. 키 값은 어디에도 찍지 않는다.
실행: check_install.bat  (= python -X utf8 scripts/check_install.py [--asof YYYY-MM-DD])
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, WARN, ERR = "통과", "주의", "오류"
MIN_FREE_WARN_MB, MIN_FREE_ERR_MB = 500, 100
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
LOOPBACK_HINT = "보안 모듈이 localhost를 막을 수 있습니다. 잠시 뒤 다시 해 보거나 보안 프로그램의 예외 목록을 확인하세요."


class Result(NamedTuple):
    name: str
    level: str
    message: str


def check_python() -> Result:
    v = sys.version_info
    text = f"Python {v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 12):
        return Result("파이썬 버전", OK, text)
    return Result("파이썬 버전", ERR, f"{text}: 3.12 이상이 필요합니다. 설치 폴더의 runtime\\python을 쓰세요.")


def check_utf8() -> Result:
    if sys.flags.utf8_mode or os.environ.get("PYTHONUTF8") == "1":
        return Result("UTF-8 모드", OK, "켜져 있음")
    return Result("UTF-8 모드", ERR, "꺼져 있습니다. run.bat으로 실행하거나 python -X utf8 로 실행하세요.")


def _bind_once(port: int) -> OSError | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return None
    except OSError as e:
        return e
    finally:
        s.close()


def check_port(first: int | None = None, last: int | None = None, bind: Callable[[int], OSError | None] = _bind_once,
               pause: float = 0.2) -> Result:
    """127.0.0.1에 묶을 수 있는 포트가 있는지. 이 PC는 보안 모듈 때문에 가끔 실패하므로 3번 다시 해 본다."""
    from app.config import PORT_FIRST, PORT_LAST
    first, last = first or PORT_FIRST, last or PORT_LAST
    last_error: OSError | None = None
    for attempt in range(3):
        for port in range(first, last + 1):
            err = bind(port)
            if err is None:
                note = "" if port == first else f"({first}번은 쓰는 중이라 {port}번으로 대신)"
                return Result("포트(localhost 연결)", OK, f"{port}번 사용 가능 {note}".strip())
            last_error = err
        if attempt < 2:
            time.sleep(pause)
    return Result("포트(localhost 연결)", ERR, f"{first}~{last}번 모두 묶지 못했습니다({last_error}). {LOOPBACK_HINT}")


def check_writable(root: Path = ROOT) -> Result:
    bad = []
    for name in ("data", "logs"):
        d = root / name
        try:
            d.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=d, prefix=".write_test_", delete=True):
                pass
        except OSError as e:
            bad.append(f"{name}\\ ({e.strerror or e})")
    if bad:
        return Result("쓰기 권한", ERR, "쓸 수 없는 폴더: " + ", ".join(bad))
    return Result("쓰기 권한", OK, "data\\ , logs\\ 쓰기 가능")


def check_tables(root: Path = ROOT, as_of: date | None = None) -> Result:
    from app.data_layer.validate import validate_tables
    try:
        issues = validate_tables(root / "data" / "tables", today=as_of)
    except Exception as e:  # 파일이 없거나 깨짐
        return Result("지원제도 표 검사", ERR, f"표를 읽지 못했습니다: {e}")
    errors = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    if errors:
        first = errors[0]
        return Result("지원제도 표 검사", ERR, f"오류 {len(errors)}건. 예: {first.file} {first.row_excel}행 {first.message_ko}")
    if warns:
        return Result("지원제도 표 검사", WARN, f"오류 0건, 경고 {len(warns)}건. 예: {warns[0].file} {warns[0].message_ko}")
    return Result("지원제도 표 검사", OK, "오류 0건")


def check_snapshot(root: Path = ROOT, as_of: date | None = None) -> Result:
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    day = as_of or date.today()
    try:
        crops = load_tables(root / "data" / "tables", day).crops
        snap = load_snapshot(root / "data" / "snapshot", day, crops=crops)
    except Exception as e:
        return Result("저장본 지문(sha256)", ERR, f"저장본을 읽지 못했습니다: {e}")
    if snap.damaged:
        return Result("저장본 지문(sha256)", ERR, "manifest와 다른 파일: " + "; ".join(str(k) for k in snap.damaged))
    return Result("저장본 지문(sha256)", OK, f"manifest와 모두 일치(저장본 {snap.built_at.isoformat()})")


def check_templates() -> Result:
    try:
        from app.ui.render import _env
        from app.ui.result_view import notice_box, tel_nb
        _env.filters.setdefault("tel", tel_nb)      # app.py 가 화면 서식 환경에만 다는 필터라 여기서도 같이 단다
        _env.filters.setdefault("nnv", notice_box)
        names = _env.list_templates(extensions=["html"])
        for n in names:
            _env.get_template(n)
    except Exception as e:
        return Result("화면·종이 서식", ERR, f"서식을 불러오지 못했습니다: {e}")
    return Result("화면·종이 서식", OK, f"{len(names)}개 불러옴")


def find_edge() -> str | None:
    found = shutil.which("msedge")
    if found:
        return found
    return next((p for p in EDGE_PATHS if Path(p).exists()), None)


def check_edge() -> Result:
    edge = find_edge()
    if edge:
        return Result("Edge(PDF 저장)", OK, edge)
    return Result("Edge(PDF 저장)", WARN, "msedge.exe를 못 찾았습니다. 종이 PDF 저장은 안 되고 HTML 인쇄만 됩니다.")


def check_printer() -> Result:
    if sys.platform != "win32":
        return Result("프린터", WARN, "Windows가 아니라 확인하지 않았습니다.")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Printer | Measure-Object).Count"],
                             capture_output=True, text=True, timeout=30)
        count = int(out.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return Result("프린터", WARN, "프린터 목록을 읽지 못했습니다. 인쇄할 때 직접 확인하세요.")
    if count:
        return Result("프린터", OK, f"{count}대 등록됨")
    return Result("프린터", WARN, "등록된 프린터가 없습니다. 화면과 PDF는 되지만 종이 출력은 프린터를 추가해야 합니다.")


def check_keyring() -> Result:
    try:
        from app.agents.llm.keystore import KeyStore
        check = KeyStore().test()
    except Exception as e:
        return Result("자격 증명 저장소", WARN, f"쓸 수 없습니다({type(e).__name__}). 키는 .env 파일로 넣으세요.")
    if check.ok:
        return Result("자격 증명 저장소", OK, check.backend)
    return Result("자격 증명 저장소", WARN, f"{check.backend}: 쓸 수 없습니다. 키는 .env 파일로 넣으세요.")


def check_key() -> Result:
    """키가 있는지만 본다. 값은 읽어도 출력하지 않는다."""
    try:
        from app.agents.llm.keystore import KeyStore
        has = KeyStore().get("llm") is not None
    except Exception:
        has = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has:
        return Result("AI 키", OK, "있음(값은 표시하지 않음)")
    return Result("AI 키", WARN, "없음. 키가 없어도 계산·종이는 됩니다(설명 문장만 기본 문구). keys.bat set llm 으로 넣을 수 있습니다.")


def check_disk(root: Path = ROOT) -> Result:
    free_mb = shutil.disk_usage(root).free // (1024 * 1024)
    if free_mb < MIN_FREE_ERR_MB:
        return Result("디스크 여유", ERR, f"{free_mb}MB: {MIN_FREE_ERR_MB}MB 이상 비워 주세요.")
    if free_mb < MIN_FREE_WARN_MB:
        return Result("디스크 여유", WARN, f"{free_mb}MB: 기록·백업에 모자랄 수 있습니다.")
    return Result("디스크 여유", OK, f"{free_mb}MB")


def run_checks(as_of: date | None = None) -> list[Result]:
    return [check_python(), check_utf8(), check_port(), check_writable(), check_tables(as_of=as_of),
            check_snapshot(as_of=as_of), check_templates(), check_edge(), check_printer(), check_keyring(),
            check_key(), check_disk()]


def main(argv: list[str]) -> int:
    as_of = date.fromisoformat(argv[argv.index("--asof") + 1]) if "--asof" in argv else None
    print("제주 농돈 설치 점검\n")
    results = run_checks(as_of)
    for i, r in enumerate(results, 1):
        print(f"{i:>2}. [{r.level}] {r.name}: {r.message}")
    errors = sum(r.level == ERR for r in results)
    warns = sum(r.level == WARN for r in results)
    print(f"\n오류 {errors}건 · 주의 {warns}건")
    if errors:
        print("오류를 먼저 고쳐 주세요. 도움이 필요하면 이 화면을 찍어 센터 담당자에게 보여 주세요.")
        return 1
    print("바로 쓸 수 있습니다." + (" (주의 항목은 없어도 화면과 종이는 됩니다.)" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
