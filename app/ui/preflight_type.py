"""유형별 종이의 인쇄 전 검사(Task 23): FactSheet 없이 HTML만 보는 검사.

preflight.py(상담 종이용, FactSheet 필요)의 파서·규칙을 그대로 빌려 쓰되 아래 코드만 본다.
NO_SOURCE / NO_ASOF / NARR_DIGIT / OVERFLOW / ASOF_NO_BADGE(시연 기준일인데 머리에 기준일 날짜가 안 찍혔다).
뜻은 preflight.py의 표와 같다. 사람 정보가 없는 종이라 제도 판정(EXPIRED_ROW 등)은 없다.
"""
from app.ui.preflight import front_pages, has_digits_outside_nums, num_spans, parse_html
from app.ui.render import check_overflow

CODES = ("NO_SOURCE", "NO_ASOF", "NARR_DIGIT", "OVERFLOW", "ASOF_NO_BADGE")


def preflight_html(html: str, cfg) -> list[str]:
    root = parse_html(html)
    front = front_pages(root)
    spans = num_spans([root])
    found: set[str] = set()
    if any(not s.attrs.get("data-source", "").strip() for s in spans):
        found.add("NO_SOURCE")
    if any(not s.attrs.get("data-asof", "").strip() for s in spans):
        found.add("NO_ASOF")
    if has_digits_outside_nums(root):
        found.add("NARR_DIGIT")
    if check_overflow(html):
        found.add("OVERFLOW")
    if cfg.demo_asof and not (front and any("asof" in n.classes() and cfg.as_of.isoformat() in n.text() for n in front[0].walk())):
        found.add("ASOF_NO_BADGE")
    return [c for c in CODES if c in found]
