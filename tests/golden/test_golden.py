"""골든 케이스(Task 27 → 34, 관문 G1): 프로필 → 사실표 → 종이 → 사전 점검(빈 목록) → 기대값 비교.

골든 12 = P1~P5, T1, T2, B02, B04, B05, B06, B12 (tests/golden/README.md). 나머지 B 케이스와 시즌 중간 G13·G14도 같이 돌린다.
기대값을 바꾸면 사유를 tests/golden/CHANGELOG.md에 적는다(사례 번호, 이전·이후 값, 근거). 못 맞춘 것은 XFAIL_TASK34에 올리고
tests/golden/FAILURES.md "미해결"에 정확한 이유를 적는다.
비교 범위: 종이 모드, 머리, 고정 줄, 줄·보험·첫 행동의 must_include(종이 글. 종이에 없는 담당자용 내용은 결과 화면 직원용 창 글(staff_text)로 갈음: 2026-11-18 뒷면을 없앴다),
배지 글, must_not_print·must_not_print_front(종이 글만).
기준일·가격 fixture는 사례마다 golden_adapter.case_env가 입힌다.
"""
import re
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden_adapter import CASES_DIR, build_paper, case_env, load_case, to_profile  # noqa: E402

from app.core.sheet import EmptyFront, flatten  # noqa: E402
from app.ui.preflight import preflight  # noqa: E402

GOLDEN_12 = ("P1", "P2", "P3", "P4", "P5", "T1", "T2", "B02", "B04", "B05", "B06", "B12")
ALL_CASES = tuple(sorted(p.stem for p in CASES_DIR.glob("*.json")))
XFAIL_TASK34: frozenset[str] = frozenset()    # 못 맞춘 케이스. 이유는 FAILURES.md "미해결"


def _text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "script"]):
        tag.decompose()
    return re.sub(r"\s+", "", soup.get_text(" "))   # 숫자 칸이 span으로 쪼개져 사이에 공백이 생기므로 공백을 모두 뺀다


def _line_text(line) -> str:
    return re.sub(r"\s+", "", "".join(x for x in (line.title, line.text, line.sub, line.detail, line.badge) if x))


def _scoped(lines, item: dict) -> str | None:
    key = item.get("program_key")
    if not key:
        return None
    found = [_line_text(l) for l in lines if l.program_key == key]
    return " ".join(found) if found else None


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strings(obj) -> list[str]:
    """객체 안의 글(문자열)을 모두 모은다(사전·목록·모델·튜플 속까지)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [s for v in obj for s in _strings(v)]
    if hasattr(obj, "model_dump"):
        return _strings(obj.model_dump())
    return [str(obj)] if isinstance(obj, (int, float)) else []


def staff_text(sheet, fs, bundle, as_of) -> str:
    """2026-11-18 종이에서 뒷면이 없어졌다. 뒷면에 있던 담당자용 내용(조건 확인·뺀 것·가격 근거·숫자 근거)은 결과 화면 '직원용 · 자세한 내용 보기' 창과 그 바탕 자료(Sheet.back · FactSheet.facts)에 있다:
    골든이 '종이 뒷면 글'로 보던 기대는 이 글(+ 종이에 싣지 않는 줄을 담은 Sheet.front)에서 본다(종이 글과 따로)."""
    from app.ui.result_view import build_view

    view = build_view(sheet, fs, bundle, as_of, None, screen=True)
    from app.ui.render import _slot_text
    slots = [" ".join(str(v) for v in _slot_text(s, fs.as_of).values() if v) for s in getattr(sheet.front, "calendar3", ())]      # 빈 종이의 '다음에 오실 때' 달력 칸(옛 뒷면 표)
    return _norm(" ".join([*_strings(view["detail"]), *_strings(sheet.front), *_strings(sheet.back), *_strings(fs.facts), *_strings(fs.triggers), *slots]))


def check_case(case: dict, sheet, html: str, staff: str = "") -> list[str]:
    """기대값과 어긋난 점 목록(없으면 빈 목록).

    key_lines·first_actions·insurance는 앞면 글에서만 찾는다. `program_key`가 있는 항목은 그 줄(제목·글·작은 글씨·원문·배지)이 앞면에
    있어야 하고 must_include는 그 줄 안에서만 찾는다. 담당자용 글로 맞추려면 항목에 `"section": "back"` 또는 `"where": "back"`을 적는다(2026-11-18 뒷면이 없어져 종이 글 + 직원용 창 글 staff 에서 찾는다).
    also는 종이 글 + staff 에서 찾는다."""
    exp, paper = case["expect"], _text(html)
    page, front_page = paper + staff, paper
    lines = list(flatten(sheet.front))
    bad: list[str] = []

    def need(where: str, words, haystack: str = page, back_detail: bool = False) -> None:
        for w in words or ():
            if _norm(w) not in haystack:
                bad.append(f"{where}: 종이에 '{w}' 없음" if haystack is page else f"{where}: 앞면(줄)에 '{w}' 없음")

    mode = "all_set" if isinstance(sheet.front, EmptyFront) else "normal"
    if mode != exp["paper_mode"]:
        bad.append(f"paper_mode: 기대 {exp['paper_mode']} / 실제 {mode}")
    need("header", exp["header"].get("must_include"))
    for group in ("key_lines", "first_actions", "insurance", "also"):
        for item in exp.get(group, ()):
            name = item.get("id") or f"{group}:{item.get('program_key') or item.get('product_id') or item.get('target') or item.get('kind')}"
            back = group == "also" or item.get("section") == "back" or item.get("where") == "back"
            scope = _scoped(lines, item)
            if back:
                hay = page
            elif item.get("program_key"):
                if scope is None:
                    if item.get("must_include") or item.get("badge"):
                        bad.append(f"{name}: 앞면에 {item['program_key']} 줄이 없음")
                    continue
                hay = scope
            else:
                hay = front_page + staff      # 줄에 매이지 않는 항목: 종이 글 또는 직원용 창 글(2026-11-18)
            need(name, item.get("must_include"), hay, back_detail=back)
            need(name + " 배지", item.get("badge_must_include") if item.get("badge") else None, hay, back_detail=back)
            for w in item.get("must_not_include", ()) if scope is not None else ():
                if _norm(w) in scope:
                    bad.append(f"{name}: 줄 안에 금지 글 '{w}'")
    if (allset := exp.get("all_set")):          # 빈 종이 머리: 문구, 지키실 돈 표시, 끊기지 않게, 달력 세 칸의 달
        need("all_set", allset.get("front_top_must_include"))
        need("all_set 끊기지 않게", allset.get("keep_actions_must_include"))
        need("all_set 달력", allset.get("calendar_3"))
        shown = (allset.get("kept_money") or {}).get("display")
        if shown and isinstance(sheet.front, EmptyFront) and _norm(shown).removeprefix("연") != _norm(sheet.front.money_text or "").removeprefix("지키실돈").removeprefix("연"):
            bad.append(f"all_set 지키실 돈: 기대 '{shown}' / 실제 '{sheet.front.money_text}'")
    for item in exp.get("fixed_lines", ()):
        need(item["id"], item.get("must_include"))
        for w in item.get("must_not_include", ()):
            if re.sub(r"\s+", "", w) in paper:
                bad.append(f"{item['id']}: 금지 글 '{w}'")
    for w in exp.get("must_not_print", ()):
        if re.sub(r"\s+", "", w) in paper:
            bad.append(f"must_not_print: 종이에 '{w}' 있음")
    for w in exp.get("must_not_print_front", ()):
        if re.sub(r"\s+", "", w) in front_page:
            bad.append(f"must_not_print_front: 앞면에 '{w}' 있음")
    return bad


@pytest.fixture(scope="module")
def envs():
    cache: dict[str, object] = {}

    def get(case_id: str):
        if case_id not in cache:
            case = load_case(case_id)
            env = case_env(case)
            cache[case_id] = (case, env, *build_paper(to_profile(case["profile"]), env.bundle, env.snap, env.cfg))
        return cache[case_id]
    return get


@pytest.mark.parametrize("case_id", ALL_CASES)
def test_golden_preflight(case_id, envs):
    """인쇄 전 검사는 xfail과 상관없이 모든 사례에서 통과해야 한다."""
    _, env, fs, _, html = envs(case_id)
    assert preflight(html, fs, env.cfg) == []


@pytest.mark.parametrize("case_id", [pytest.param(c, marks=pytest.mark.xfail(reason="Task 34 미해결: FAILURES.md", strict=False))
                                     if c in XFAIL_TASK34 else c for c in ALL_CASES])
def test_golden(case_id, envs):
    case, env, fs, sheet, html = envs(case_id)
    assert check_case(case, sheet, html, staff_text(sheet, fs, env.bundle, env.cfg.as_of)) == []


def _sensitivity():
    """scripts/sensitivity_prices.py(표준 라이브러리만, 파일을 쓰지 않는다)를 모듈로 읽어 온다."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "sensitivity_prices.py"
    spec = importlib.util.spec_from_file_location("sensitivity_prices", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("case_id,rule,base,flipped", [
    ("G13", "PRICE_STAB", "NEAR", {0.8: "MET", 1.1: "NOT_MET", 1.2: "NOT_MET"}),
    ("G14", "PRICE_STAB", "MET", {1.1: "NEAR", 1.2: "NEAR"}),
    ("G14", "LOGISTICS", "NEAR", {0.8: "BELOW", 0.9: "BELOW"})])
def test_mid_season_cases_flip_under_price_error_and_agree_with_the_engine(case_id, rule, base, flipped, envs):
    """시즌 중간 사례는 허브 가격 ±10·20% 오차에서 판정이 뒤집힌다. 엔진의 배수 1.0 판정이 스크립트(별개 구현)와 같다."""
    from datetime import date
    mod = _sensitivity()
    case, _, fs, _, _ = envs(case_id)
    crop = case["profile"]["crop_key"]
    crops, params = mod.load_tables()
    _, flips = mod.run_case(mod.load_1361(), crops, params, crop, date.fromisoformat(case["as_of"]))
    assert flips[rule] == flipped
    engine = next(t.status for t in fs.triggers if t.rule_id == rule)
    assert {"MET": "MET", "NEAR": "NEAR", "MET_ESTIMATED": "BELOW"}.get(engine, engine) == base
