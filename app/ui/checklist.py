"""'같이 확인해요' 표(2026-11-15 사장 지시): 지원마다 어르신이 네/아니요로 답할 수 있는 조건(check_items.csv 의 ask 쉬운 말)을 상담 직원과 함께 확인하게 모은다.
결과 화면 '직원용 · 자세한 내용 보기'의 같이 확인해요 표가 쓰는 모음이다. 담당자용 원문(info 조각)은 info_text 로 따로 낸다."""
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.ui.check_items import check_for

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
OTHER = "그 밖에"
PRIOR_LINE = "금액은 올해 기준이에요. 내년 공고가 나오면 달라질 수 있어요."      # 화면 알아 두세요가 쓴다(종이에는 없다)
_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|만)?")


def money_value(amt: str | None) -> float:
    """금액 글('연 약 180만~258만 원')에서 가장 큰 값(원). 금액이 없으면 0(큰 지원부터 싣는 순서에만 쓴다)."""
    best = 0.0
    for num, unit in _MONEY.findall(amt or ""):
        v = float(num.replace(",", "")) * (1e8 if unit == "억" else 1e4 if unit == "만" else 1.0)
        best = max(best, v)
    return best


def _amt_text(text: str | None) -> str:
    """줄의 오른쪽 글에서 금액 덩어리만('연 약 180만~258만 원'). 금액이 아닌 글(시기·안내)은 빈 글."""
    if not text or "원" not in text or not re.search(r"\d", text):
        return ""
    m = re.match(r"^(.*?)\s*(연 .*)$", text)
    return m[2] if m else text


def entries(groups: Iterable[tuple[str, Sequence[Any]]], prog_of: Mapping[str, Any]) -> list[dict]:
    """groups: (상자 번호 글 · 번호가 없으면 ""(그 밖에), CardLine 들) 의 차례. 반환: ask 조각이 있는 지원마다 {no, title, amt, money, asks, line}.
    같은 표 행은 한 번만 낸다. 상자 순서·상자 안 줄 순서는 들어온 그대로."""
    out: list[dict] = []
    seen: set[str] = set()
    for no, lines in groups:
        digit = str(CIRCLED.index(no) + 1) if no and no in CIRCLED else (no or OTHER)        # 이름표(가실 곳 이름 · 앞으로 · 달)가 있으면 그 글, 없는 묶음("")은 '그 밖에'
        for cl in lines:
            pid = cl.line.program_id
            prog = prog_of.get(pid) if pid else None
            if prog is None or pid in seen:
                continue
            seen.add(pid)
            asks, _ = check_for(prog)
            if asks:
                amt = _amt_text(cl.text)
                out.append({"no": digit, "title": cl.title, "amt": amt, "money": money_value(amt), "asks": asks, "line": cl.line})
    return out


def info_text(program) -> str:
    """담당자용 원문: ask·basis 가 아닌 조각(방법·참고·계산 설명)을 ' · ' 로 이은 글."""
    return " · ".join(check_for(program)[1])
