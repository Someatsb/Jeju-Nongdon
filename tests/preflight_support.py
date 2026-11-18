"""Task 21 시험 보조: P4 양 씨 종이(시연 기준일)와 인쇄 전 검사 HTML 픽스처 9개를 만든다.

`python tests/preflight_support.py`를 돌리면 tests/fixtures/preflight/*.html을 다시 쓴다(표·코어가 바뀌어 종이가 달라졌을 때).
시험(test_preflight.py)은 파일을 읽어 쓰고, 파일이 지금 종이와 같은지도 본다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "preflight"


def build_p4():
    """(cfg, fs, html): 시연 기준일(2026-11-13) P4 종이. 인쇄 경로와 같은 순서."""
    from app.config import load_config
    from app.core.models import FarmProfile
    from app.core.pipeline import build_fact_sheet
    from app.core.sheet import build_sheet
    from app.data_layer.snapshot import load_snapshot
    from app.data_layer.tables import load_tables
    from app.ui.render import render_sheet
    from conftest import P4_KWARGS

    cfg = load_config(["--asof", "2026-11-13"])
    bundle = load_tables(cfg.tables_dir, cfg.as_of)
    snap = load_snapshot(cfg.snapshot_dir, cfg.as_of, crops=bundle.crops)
    fs = build_fact_sheet(FarmProfile(**P4_KWARGS), bundle, snap, cfg.as_of, "test", demo_asof=True)
    sheet = build_sheet(fs, bundle, cfg.as_of)
    return cfg, fs, render_sheet(sheet, fs, None, cfg, crop_labels={c.crop_code: c.label for c in bundle.crops}, programs=bundle.programs)


def _sub_once(pattern: str, repl: str, text: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1)
    assert n == 1, pattern
    return out


def _span(source: str) -> str:
    return f'<p class="x"><span class="num" data-source="{source}" data-asof="2026-11-07">확인</span></p>'


def _no_source(html, fs):
    return _sub_once(r'(<span class="[^"]*\bnum\b[^"]*") data-source="[^"]*"', r"\1", html)


def _no_asof(html, fs):
    return _sub_once(r'(<span class="[^"]*\bnum\b[^"]*" data-source="[^"]*") data-asof="[^"]*"', r"\1", html)


def _narr_digit(html, fs):
    return _sub_once(r"(</h1>)", r'<p class="x">올해 3번</p>', html)


def _overflow(html, fs):
    return html.replace('<div class="foot">', '<p class="fixed line pt14" data-sec="F">가</p>' * 30 + '<div class="foot">', 1)


def _expired(html, fs):
    return html.replace('<div class="foot">', _span("supports:KRC-FARMLAND-PENSION@2026") + '<div class="foot">', 1)


def _hold(html, fs):
    return html.replace('<div class="foot">', _span("supports:NAT-SAFETY-INS@2026") + '<div class="foot">', 1)


PRIOR_NUM = '<p class="fixed" data-sec="F"><span class="num" data-source="supports:JEJU-FARMER-ALLOW@2026" data-asof="2026-11-07">50</span></p>'


def _prior_no_badge(html, fs):
    """작년 공고 기준 제도의 숫자가 있는데 머리의 '○년 기준 · ○년 공고 전' 배지가 없는 종이(종이 단순화 뒤: 배지는 머리에 한 번)."""
    html = _sub_once(r'<span class="badge prior hd num"[^>]*>[^<]*</span>', "", html)
    return html.replace('<div class="foot">', PRIOR_NUM + '<div class="foot">', 1)


def _asof_no_badge(html, fs):
    return html.replace("기준일 2026-11-13", "")   # 머리 기준일 날짜가 안 찍힌 종이


# 파일 이름 → (고치는 함수, 기대 코드). 11번은 고치지 않은 정상 종이. (2026-11-18 뒷면이 없어져 03_header3·08_no_fingerprint·12_back_overflow 는 없다)
CASES = {
    "01_no_source": (_no_source, "NO_SOURCE"), "02_no_asof": (_no_asof, "NO_ASOF"),
    "04_narr_digit": (_narr_digit, "NARR_DIGIT"), "05_overflow": (_overflow, "OVERFLOW"),
    "06_expired_row": (_expired, "EXPIRED_ROW"), "07_hold_row": (_hold, "HOLD_ROW"),
    "09_prior_no_badge": (_prior_no_badge, "PRIOR_NO_BADGE"),
    "10_asof_no_badge": (_asof_no_badge, "ASOF_NO_BADGE"), "11_clean": (lambda html, fs: html, None),
}


def make_all(p4=None) -> dict[str, str]:
    _, fs, html = p4 or build_p4()
    return {name: fix(html, fs) for name, (fix, _) in CASES.items()}


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in make_all().items():
        (FIXTURE_DIR / f"{name}.html").write_text(text, encoding="utf-8", newline="\n")
    print("wrote", len(CASES))
