"""check_items.csv: 표의 manual_check 조각 전부가 있고, 쉬운 말이 원문의 숫자·뜻 규칙을 지킨다."""
import csv
import re
from pathlib import Path

import pytest

from app.ui import check_items as ci

ROOT = Path(__file__).resolve().parents[2]
NUM = re.compile(r"\d[\d,]*(?:\.\d+)*")


def _table_pieces() -> list[str]:
    out: list[str] = []
    with (ROOT / "data/tables/supports.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            for p in ci.split_pieces(r["manual_check"]):
                if p not in out:
                    out.append(p)
    return out


def test_every_table_piece_is_in_file():
    missing = [p for p in _table_pieces() if p not in ci.load_items()]
    assert not missing, f"check_items.csv 에 없는 조각 {len(missing)}개: {missing}"


def test_file_has_no_stale_piece():
    stale = [p for p in ci.load_items() if p not in set(_table_pieces())]
    assert not stale, f"표에 없어진 조각: {stale}"


def test_kind_values():
    bad = {p: k for p, (k, _) in ci.load_items().items() if k not in ci.KINDS}
    assert not bad, bad


def test_easy_only_for_ask():
    for p, (k, e) in ci.load_items().items():
        assert bool(e) == (k == "ask"), p


ASKS = [(p, e) for p, (k, e) in ci.load_items().items() if k == "ask"]


@pytest.mark.parametrize("orig,easy", ASKS)
def test_ask_keeps_numbers(orig, easy):
    for n in NUM.findall(orig):
        assert n in easy, f"숫자 {n} 빠짐: {orig} -> {easy}"


@pytest.mark.parametrize("orig,easy", ASKS)
def test_ask_is_one_short_haeyo_sentence(orig, easy):
    assert len(easy) <= 60, easy
    assert easy.endswith(("요", "요.")) and not easy.endswith("."), easy
    assert not re.search(r"[.!?](\s|$)", easy.replace("2021.1.1", "").replace("1.1", "")), easy


def test_split_check_unknown_piece_is_info():
    assert ci.split_check("새로 생긴 조각") == ([], ["새로 생긴 조각"])
    assert ci.split_check("지방세 체납 없음 / 2027 공고 전 - 2026 기준") == (["밀린 지방세가 없어요"], [])


def test_check_for_by_key_merges():
    class P:
        def __init__(self, k, m):
            self.program_key, self.manual_check = k, m
    rows = [P("a", "지방세 체납 없음"), P("a", "지방세 체납 없음 / 제주 거주"), P("b", "도내 주소")]
    assert ci.check_for("a", rows) == (["밀린 지방세가 없어요", "제주에 살고 있어요"], [])
    assert ci.check_for(rows[2]) == (["제주도 안에 주소가 있어요"], [])


def test_file_not_read_by_tables_loader():
    # 표 묶음은 data/tables 의 지정 CSV 만 읽고, 이 파일은 app/ui 에 있다.
    assert Path(ci._FILE).parent.name == "ui"
    assert "check_items" not in (ROOT / "app/data_layer/tables.py").read_text(encoding="utf-8")
