"""인쇄 전 검사(Task 21, U21; 규칙 R8): 인쇄 직전 종이 HTML 전체를 보고 막을 이유를 코드 목록으로 돌려준다.

코드는 순서대로 한 번씩만 나온다. 하나라도 있으면 /counsel/print는 종이 대신 "인쇄 보류" 화면과 사유(REASONS)를 보인다.

| 코드 | 걸리는 때 |
|---|---|
| NO_SOURCE / NO_ASOF | span.num에 data-source / data-asof가 없거나 비었다(렌더러가 쓰는 "sheet"·"config"·"calendar"·"header"·"상담 입력" 등은 출처로 인정) |
| NARR_DIGIT | span.num·style·script 밖의 글에 숫자(아라비아·원문자)가 있다(설명 문장에 숫자가 새는 것). 읽히는 속성(TEXT_ATTRS: title·alt·aria-label 등)의 값도 글로 센다. class·id·style·data-*·meta의 설정값은 글이 아니라 세지 않는다 |
| OVERFLOW | render.check_overflow가 종이 한 쪽에 글이 다 안 들어간다고 알렸다 |
| EXPIRED_ROW | 찍힌 숫자의 출처가 유효기간이 끝난 행(MatchResult.status == OUT_OF_VALIDITY)이다 |
| HOLD_ROW | 찍힌 숫자의 출처가 hold 행이다. 보험 줄은 숫자 없이 찍는 줄(no_numbers = source_hold)이라 앞면에 숫자 칸이 있으면 걸린다. data-fact 가 붙은 숫자는 그 사실 자체의 행 상태와 출처 행(제도 판정)이 hold인지 둘 다 본다(보험 창구 번호는 숫자가 아니라 source_hold여도 허용) |
| PRIOR_NO_BADGE | 작년 공고 기준 행(prior_year_reference)에서 온 숫자가 있는데 머리에 '○년 기준 · ○년 공고 전' 배지(class "badge prior")가 없다(2026-11-14 종이 단순화: 줄마다 붙이던 배지를 머리에 한 번만 적는다). 잠정 배지 등 다른 배지는 인정하지 않는다 |
| ASOF_NO_BADGE | 시연 기준일(cfg.demo_asof)인데 종이 머리에 기준일 날짜("기준일 2026-11-13" 모양)가 안 찍혔다 |

HTML은 표준 라이브러리 파서로 읽는다(시험용 부품 bs4에 기대지 않는다).
"""
import re
from html.parser import HTMLParser

from app.core.insurance import SOURCE_HOLD
from app.core.models import FactSheet
from app.ui.render import check_overflow

CODES = ("NO_SOURCE", "NO_ASOF", "NARR_DIGIT", "OVERFLOW", "EXPIRED_ROW", "HOLD_ROW", "PRIOR_NO_BADGE", "ASOF_NO_BADGE")
REASONS = {
    "NO_SOURCE": "출처가 없는 숫자가 있어요.",
    "NO_ASOF": "날짜 표시가 없는 숫자가 있어요.",
    "NARR_DIGIT": "근거 표시 없이 쓰인 숫자가 있어요(설명 문장에 숫자가 섞였을 수 있어요).",
    "OVERFLOW": "종이 한 쪽에 글이 다 안 들어갈 수 있어요.",
    "EXPIRED_ROW": "유효기간이 끝난 지원의 숫자가 찍혔어요.",
    "HOLD_ROW": "근거를 확인 중인 지원의 숫자가 찍혔어요.",
    "PRIOR_NO_BADGE": "작년 공고 기준인 항목에 '작년 기준' 표시가 빠졌어요.",
    "ASOF_NO_BADGE": "종이 머리에 기준일 날짜가 안 찍혔어요.",
}
_VOID = frozenset({"br", "hr", "img", "input", "link", "meta", "col", "wbr"})
_DIGIT = re.compile(r"[\d①-⑳]")
TEXT_ATTRS = ("title", "alt", "aria-label", "aria-description", "placeholder", "value", "label")


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None") -> None:
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, _Node):
                yield from c.walk()

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, {k: v or "" for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _parse(html: str) -> _Node:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


def _pages(root: _Node) -> list[_Node]:
    return [n for n in root.walk() if n.attrs.get("data-page") == "front"]


def _nums(nodes) -> list[_Node]:
    return [n for top in nodes for n in top.walk() if n.tag == "span" and "num" in n.classes()]


def _digits_outside_nums(node: _Node) -> bool:
    if node.tag in ("style", "script") or (node.tag == "span" and "num" in node.classes()):
        return False
    if any(_DIGIT.search(node.attrs.get(a, "")) for a in TEXT_ATTRS):
        return True
    return any(_DIGIT.search(c) if isinstance(c, str) else _digits_outside_nums(c) for c in node.children)


def _program_id(source: str) -> str | None:
    return source.removeprefix("supports:") if source.startswith("supports:") else None


def preflight(html: str, fs: FactSheet, cfg) -> list[str]:
    """종이 HTML을 검사해 막을 이유 코드 목록(CODES 순서, 없으면 빈 목록)을 돌려준다."""
    root = _parse(html)
    front = _pages(root)
    spans = _nums([root])
    found: set[str] = set()

    if any(not s.attrs.get("data-source", "").strip() for s in spans):
        found.add("NO_SOURCE")
    if any(not s.attrs.get("data-asof", "").strip() for s in spans):
        found.add("NO_ASOF")

    if _digits_outside_nums(root):
        found.add("NARR_DIGIT")
    if check_overflow(html):
        found.add("OVERFLOW")

    status = {m.program_id: m.status for m in fs.matches}
    prior = {m.program_id for m in fs.matches if m.row_status == "prior_year_reference"}
    match_hold = {m.source.source_id for m in fs.matches if m.row_status == "hold"}
    hold = match_hold | {r.source.source_id for r in fs.insurance if SOURCE_HOLD in r.reasons}
    facts = {f.fact_id: f for f in fs.facts}
    for s in spans:
        src, fact = s.attrs.get("data-source", ""), facts.get(s.attrs.get("data-fact", ""))
        if status.get(_program_id(src)) == "OUT_OF_VALIDITY":
            found.add("EXPIRED_ROW")
        if (fact.row_status == "hold" or src in match_hold) if fact is not None else (src in hold):
            found.add("HOLD_ROW")

    def is_prior(span: _Node) -> bool:
        fact = facts.get(span.attrs.get("data-fact", ""))
        if fact is not None:
            return fact.row_status == "prior_year_reference"
        return _program_id(span.attrs.get("data-source", "")) in prior

    front_prior = any(is_prior(s) for s in _nums(front))
    head_badge = any({"badge", "prior"} <= n.classes() for top in front for n in top.walk())    # 머리의 배지 한 번(항목마다 붙이지 않는다)
    if front_prior and not head_badge:
        found.add("PRIOR_NO_BADGE")

    if cfg.demo_asof and not all(any("asof" in n.classes() and cfg.as_of.isoformat() in n.text() for n in page.walk())
                                 for page in front[:1]):
        found.add("ASOF_NO_BADGE")
    return [c for c in CODES if c in found]

# 다른 검사 모듈(preflight_type)이 쓰는 공개 이름.
parse_html = _parse
front_pages = _pages
num_spans = _nums
has_digits_outside_nums = _digits_outside_nums
