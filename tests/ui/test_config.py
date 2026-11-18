"""Task 6(U06) 설정: --asof 시연 기준일, 기본값, 오늘 날짜는 config에서만."""
import ast
from datetime import date
from pathlib import Path

import pytest

from app.config import PORT_FIRST, load_config
from app.core.models import Header

APP = Path(__file__).resolve().parents[2] / "app"


# --- 계획서 Step 1(그대로) ---

def test_asof_flag_sets_demo():
    c = load_config(["--asof", "2026-11-13"])
    assert c.as_of == date(2026, 11, 13) and c.demo_asof


def test_demo_asof_shows_no_badge_on_screen(client_demo):
    """화면 머리에 "기준일 …(시연)"을 찍지 않는다(날짜는 직원 메뉴로 옮겼다)."""
    r = client_demo.get("/")
    assert "(시연)" not in r.text and "기준일" not in r.text and "2026-11-13" not in r.text


# --- 더한 것 ---

def test_defaults_without_flags():
    c = load_config([])
    assert c.as_of == date.today() and not c.demo_asof and not c.replay
    assert c.port == PORT_FIRST == 8765
    assert (c.tables_dir / "supports.csv").is_file() and (c.snapshot_dir / "hub_1361.csv").is_file()


def test_replay_and_port_flags():
    c = load_config(["--replay", "--port", "8770"])
    assert c.replay and c.port == 8770 and not c.demo_asof


@pytest.mark.parametrize("bad", ["2026-13-01", "20261113", "내일"])
def test_bad_asof_rejected(bad):
    with pytest.raises(SystemExit):
        load_config(["--asof", bad])


def test_health_json(client, client_demo):
    assert client_demo.get("/health").json() == {"ok": True, "as_of": "2026-11-13", "demo": True}
    assert client.get("/health").json() == {"ok": True, "as_of": date.today().isoformat(), "demo": False}


def test_no_demo_badge_without_asof(client):
    r = client.get("/")
    assert r.status_code == 200 and "(시연)" not in r.text
    assert 'class="fresh"' not in r.text and 'class="asof"' not in r.text


def test_header_values_not_shown_on_screen(client):
    """날짜 칩 4개(가격·감귤 가격·지원 표 확인·저장본)는 화면에 없다."""
    client.app.state.header = Header(price_as_of=date(2026, 11, 5), citrus_as_of=None,
                                     tables_verified=date(2026, 11, 4), snapshot_built=date(2026, 11, 7),
                                     refresh_ok=False, demo_asof=False)
    text = client.get("/").text
    for w in ("가격 2026-11-05", "지원 표 확인", "저장본", "외부 갱신", "2026-11-04", "2026-11-07"):
        assert w not in text


def test_only_config_reads_today():
    """오늘 날짜는 app/config.py 한 곳에서만 읽는다(.today() 호출을 AST로 찾는다)."""
    files = sorted(APP.rglob("*.py"))
    assert files
    hits = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "today":
                hits.append(path.relative_to(APP).as_posix())
    assert hits == ["config.py"], hits
