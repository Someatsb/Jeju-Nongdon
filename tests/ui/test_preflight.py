"""인쇄 전 검사(Task 21): HTML 픽스처 8개는 코드 하나씩, 정상 1개는 빈 목록. 모든 시험 페르소나의 실제 종이도 통과해야 한다."""
import pytest

import preflight_support as sup
from app.ui.preflight import REASONS, preflight

CODED = [(name, code) for name, (_, code) in sup.CASES.items() if code]


def load(name: str) -> str:
    return (sup.FIXTURE_DIR / f"{name}.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def p4():
    """(cfg, fs, 지금 종이): 시연 기준일 P4를 세션에 한 번만 만든다."""
    return sup.build_p4()


def fs_for(fs, code: str):
    """EXPIRED_ROW는 종이 글자만으론 안 보이고 표 행의 유효기간이 끝났다는 판정이 있어야 한다."""
    if code != "EXPIRED_ROW":
        return fs
    matches = tuple(m.model_copy(update={"status": "OUT_OF_VALIDITY"}) if m.program_id == "KRC-FARMLAND-PENSION@2026" else m
                    for m in fs.matches)
    return fs.model_copy(update={"matches": matches})


@pytest.mark.parametrize("fx,code", CODED)
def test_preflight_single_code(p4, fx, code):
    cfg, fs, _ = p4
    assert preflight(load(fx), fs_for(fs, code), cfg) == [code]


def test_clean_fixture_passes(p4):
    cfg, fs, _ = p4
    assert preflight(load("11_clean"), fs, cfg) == []


def test_fixtures_match_current_render(p4):
    drifted = [name for name, text in sup.make_all(p4).items() if load(name) != text]
    assert not drifted, f"{', '.join(drifted)}: python tests/preflight_support.py 로 픽스처를 다시 만드세요"


def test_provisional_badge_does_not_count_as_prior_badge(p4):
    """잠정 배지처럼 같은 출처의 다른 배지가 있어도 '작년 기준' 배지가 없으면 막는다."""
    cfg, fs, html = p4
    with_prior = html.replace('<div class="foot">', sup.PRIOR_NUM + '<div class="foot">', 1)
    assert preflight(with_prior, fs, cfg) == []              # 머리에 '작년 기준' 배지가 있으면 앞면의 작년 기준 숫자는 통과
    broken = with_prior.replace('<span class="badge prior hd num"', '<span class="badge hd num"', 1)
    assert broken != with_prior and preflight(broken, fs, cfg) == ["PRIOR_NO_BADGE"]


def test_digit_in_text_attribute_counts_but_class_and_data_do_not(p4):
    cfg, fs, html = p4
    assert preflight(html.replace("<h1", '<h1 title="3곳"', 1), fs, cfg) == ["NARR_DIGIT"]
    assert preflight(html.replace("<h1", '<h1 id="h1" data-x="9"', 1), fs, cfg) == []


def test_hold_source_on_fact_span_counts(p4):
    """숫자 근거(data-fact) 칸이라도 출처가 hold 행이면 막는다. 보험 쪽 창구 번호(source_hold)는 숫자가 아니라 허용.
    (종이에는 숫자 근거 표가 없으므로 그 표가 있는 모양을 직접 넣어 본다.)"""
    cfg, fs, html = p4
    hold_id = "supports:NAT-SAFETY-INS@2026"
    assert preflight(html, fs, cfg) == []
    held = tuple(m.model_copy(update={"row_status": "hold"}) if m.program_id == "KRC-FARMLAND-PENSION@2026" else m for m in fs.matches)
    fs_hold = fs.model_copy(update={"matches": held})
    row = ('<table class="facts"><tr><td><span class="num" data-fact="office:nh_safety:owner" data-source="%s" data-asof="2026-11-07">농협 창구</span></td></tr></table>')
    with_fact = html.replace('<div class="foot">', row % hold_id + '<div class="foot">', 1)
    assert preflight(with_fact, fs, cfg) == []                       # 보험 창구 번호는 source_hold 라도 허용
    swapped = with_fact.replace('data-source="%s"' % hold_id, 'data-source="supports:KRC-FARMLAND-PENSION@2026"', 1)
    assert preflight(swapped, fs_hold, cfg) == ["HOLD_ROW"]


def test_every_code_has_korean_reason():
    assert {c for _, c in CODED} <= set(REASONS)
    assert all(any("가" <= ch <= "힣" for ch in text) for text in REASONS.values())


def test_non_demo_needs_no_demo_marker(p4):
    from app.config import load_config
    cfg = load_config([])
    assert "ASOF_NO_BADGE" not in preflight(load("11_clean"), p4[1], cfg)


def test_real_sheets_for_all_personas_pass(p4):
    """검사가 너무 빡빡하면 정상 종이가 막힌다: P1~P5·T1·T2 실제 종이가 전부 통과해야 한다."""
    from app.core.models import FarmProfile
    from app.core.pipeline import build_fact_sheet
    from app.core.sheet import build_sheet
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    from app.ui.render import render_sheet
    import conftest as c
    CFG = p4[0]
    bundle = load_tables(CFG.tables_dir, CFG.as_of)
    snap = load_snapshot(CFG.snapshot_dir, CFG.as_of, crops=bundle.crops)
    for name in ("P1", "P2", "P3", "P4", "P5", "T1", "T2"):
        fs = build_fact_sheet(FarmProfile(**getattr(c, f"{name}_KWARGS")), bundle, snap, CFG.as_of, "test", demo_asof=True)
        sheet = build_sheet(fs, bundle, CFG.as_of)
        html = render_sheet(sheet, fs, None, CFG, crop_labels={x.crop_code: x.label for x in bundle.crops})
        assert preflight(html, fs, CFG) == [], name
