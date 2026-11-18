"""app/core는 순수해야 한다: 시계·난수·파일·네트워크 import와 today()/now()/open() 호출 금지."""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "app" / "core"
FORBIDDEN = {"time", "random", "os", "httpx", "urllib", "requests", "pathlib"}
FORBIDDEN_CALLS = {"today", "now", "open"}


def core_files():
    files = sorted(CORE.rglob("*.py"))
    assert files, f"no .py files under {CORE}"  # 잘못된 위치에서 돌면 빈 통과가 되므로 막는다
    return files


def call_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr  # date.today(), datetime.now(), io.open()
    if isinstance(func, ast.Name):
        return func.id  # open()
    return None


def test_core_has_no_clock_io_or_network():
    for path in core_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {a.name.split(".")[0] for a in node.names} | ({node.module.split(".")[0]} if getattr(node, "module", None) else set())
                assert not (names & FORBIDDEN), f"{path}: {names & FORBIDDEN}"
            if isinstance(node, ast.Call):
                name = call_name(node.func)
                assert name not in FORBIDDEN_CALLS, f"{path}:{node.lineno}: {name}()"
