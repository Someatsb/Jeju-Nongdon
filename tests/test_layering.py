"""층 경계(AST로 읽는다, 글자 찾기가 아니다).

- app/core는 app의 다른 층(config·data_layer·agents·tools·ui)을 import하지 않는다.
- app/data_layer는 app.ui를 import하지 않는다.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def imported_app_modules(path: Path) -> set[str]:
    """파일이 import하는 app.* 모듈 이름(from app import x 는 app.x로 센다)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name == "app" or a.name.startswith("app.")}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "app":
                out |= {f"app.{a.name}" for a in node.names}
            elif node.module.startswith("app."):
                out.add(node.module)
    return out


def violations(layer: str, forbidden: tuple[str, ...]) -> list[str]:
    files = sorted((APP / layer).rglob("*.py"))
    assert files, f"no .py files under {APP / layer}"  # 잘못된 위치에서 돌면 빈 통과가 되므로 막는다
    return [f"{p.relative_to(APP)} -> {m}" for p in files for m in sorted(imported_app_modules(p))
            if any(m == f or m.startswith(f + ".") for f in forbidden)]


def test_core_imports_no_other_layer():
    assert violations("core", ("app.config", "app.data_layer", "app.ui", "app.agents", "app.tools")) == []


def test_core_imports_nothing_outside_core():
    bad = [v for v in violations("core", ("app",)) if " -> app.core" not in v]
    assert bad == []


def test_data_layer_never_imports_ui():
    assert violations("data_layer", ("app.ui",)) == []


def test_checker_catches_from_app_import(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("from app import config\nimport app.ui.forms\n", encoding="utf-8")
    assert imported_app_modules(f) == {"app.config", "app.ui.forms"}
