"""지원의 manual_check 조각마다 종류(ask/basis/info)와 쉬운 말을 붙인 자료(check_items.csv)를 읽는다.

- ask: 어르신이 "네/아니요"로 답할 수 있는 사람·땅 조건(쉬운 말 한 문장). basis: 자료의 단서. info: 방법·참고·계산 설명.
- 이 파일은 app/ui 에 있어 표 묶음(data/tables 의 지정 CSV만 읽음)·AI 입력·FactSheet 지문에 들어가지 않는다.
- 표에는 있는데 파일에 없는 조각은 원문 그대로 info 로 다룬다. 어긋남은 시험이 알려 준다.
"""
import csv
from functools import lru_cache
from pathlib import Path

KINDS = ("ask", "basis", "info")
SEP = " / "
_FILE = Path(__file__).with_name("check_items.csv")


def split_pieces(manual_check: str | None) -> list[str]:
    """manual_check 를 " / " 로 나눈 조각(앞뒤 공백 제거, 빈 것 제외)."""
    return [p.strip() for p in (manual_check or "").split(SEP) if p.strip()]


@lru_cache(maxsize=1)
def load_items() -> dict[str, tuple[str, str]]:
    """원문 조각 → (종류, 쉬운 말). 쉬운 말은 ask 에만 있고 나머지는 빈 글."""
    with _FILE.open(encoding="utf-8", newline="") as f:
        return {r["text"]: (r["kind"], r["easy"]) for r in csv.DictReader(f)}


def classify(piece: str) -> tuple[str, str]:
    """조각 하나의 (종류, 쉬운 말). 파일에 없으면 ("info", "")."""
    return load_items().get(piece, ("info", ""))


def split_check(manual_check: str | None) -> tuple[list[str], list[str]]:
    """manual_check → ([ask 쉬운 말], [info 원문]). basis 는 어디에도 싣지 않는다(기준 연도 표시로 갈음)."""
    asks: list[str] = []
    infos: list[str] = []
    for p in split_pieces(manual_check):
        kind, easy = classify(p)
        if kind == "ask" and easy:
            asks.append(easy)
        elif kind != "basis":
            infos.append(p)
    return asks, infos


def check_for(program, programs=None) -> tuple[list[str], list[str]]:
    """지원(표 행 객체, 또는 program_key 글 + 표 행들)의 ([ask 쉬운 말], [info 원문]). 같은 program_key 의 여러 판은 조각을 합쳐 중복을 뺀다."""
    if isinstance(program, str):
        rows = [p for p in (programs or ()) if p.program_key == program]
    else:
        rows = [program]
    asks: list[str] = []
    infos: list[str] = []
    for r in rows:
        a, i = split_check(getattr(r, "manual_check", None))
        asks += [x for x in a if x not in asks]
        infos += [x for x in i if x not in infos]
    return asks, infos
