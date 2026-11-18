"""지원 전체 보기 화면이 쓰는 묶음과 한눈에 띠(설계서 2026-11-14-supports-readability-spec).

있는 글을 묶고 나눠 줄 뿐이다. 숫자·날짜·금액·기관·전화는 Entry 에 있는 글 그대로이고, 여기서 새로 쓰는 것은
묶음 제목과 "작물·지역마다 달라요" 같은 화면 안내 말뿐이다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from app.catalog.build import MULTI_AMOUNT, Entry, Variant
from app.catalog.texts import (
    ASK_AMOUNT,
    BEFORE_NOTICE,
    ENDED_THIS_YEAR,
    NO_TIMING,
    PRIOR_NOTE,
    RANK_ALWAYS,
    RANK_ENDED,
    RANK_LATER,
    RANK_OPEN,
    RANK_SOON,
    RANK_UNKNOWN,
)
from app.core.office_say import office_say

FAR = 10**6
SEP = " · "
ENDED_PREFIX = ENDED_THIS_YEAR + SEP
VARIES = "작물·지역마다 달라요"          # MULTI_AMOUNT 의 앞 절
SEE_TABLE = "아래 표에서 확인하세요"
NO_WHERE = "신청하는 곳은 공고에서 확인하세요"
NO_LIST_WHERE = "안내에서 확인하세요"        # 목록의 어디서 신청해요 칸: 가실 곳 자료가 없는 새 공고
MAX_LIST_WHERE = 2                    # 표의 제도는 가실 곳을 2곳까지, 더 있으면 "외 ○곳"
ENDED_MAIN = ENDED_THIS_YEAR
HOLD_NOTE = "아직 확인 중"
URGENT_DAYS = 7
FOCUS_WORDS = {"citrus": ("감귤", "만감")}     # 걸러 보기 이름 → 그 걸러 보기가 가리키는 작물 줄의 이름에 든 말
FOCUS_NOTE = "기간이에요. 다른 작물은 아래 표를 보세요"
NO_EXTRA = "따로 적힌 조건이 없어요"

GROUPS = (("open", "지금 신청할 수 있어요"), ("soon", "곧 열려요"), ("always", "언제든 신청할 수 있어요"),
          ("ended", ENDED_THIS_YEAR), ("unknown", NO_TIMING))
LOW_GROUPS = frozenset({"ended", "unknown"})
_GROUP_OF_RANK = {RANK_OPEN: "open", RANK_SOON: "soon", RANK_ALWAYS: "always", RANK_LATER: "ended", RANK_ENDED: "ended",
                  RANK_UNKNOWN: "unknown"}
assert MULTI_AMOUNT.startswith(VARIES)


def group_of(e: Entry) -> str:
    """묶음 이름. 올해 공고 전인 철 지난 지원(다음 철이 아직 안 온 것)은 곧 열리는 쪽에 둔다."""
    return _group_of_window(e.window_rank, e.window)


def _group_of_window(rank: int, text: str) -> str:
    if rank == RANK_LATER and BEFORE_NOTICE in text:           # 작물 이름이 앞에 붙은 글('감귤 올해 공고 전이에요 · …')도 같다
        return "soon"
    return _GROUP_OF_RANK[rank]


def focus_variants(e: Entry, focus: str | None) -> tuple[Variant, ...]:
    """걸러 보기(감귤 등)가 가리키는 작물 줄들. 줄마다 신청 시기가 다른 제도에서만 있다(아니면 빈 묶음)."""
    words = FOCUS_WORDS.get(focus or "")
    if not words or not varies(e, "window"):
        return ()
    return tuple(v for v in e.variants if v.label and any(w in v.label for w in words))


def best_focus(e: Entry, focus: str | None) -> Variant | None:
    return min(focus_variants(e, focus), key=lambda v: (v.rank, v.days if v.days is not None else FAR), default=None)


def split_window(text: str) -> tuple[str, str]:
    """'11월 27일까지 · 13일 남음' → ('11월 27일까지', '13일 남음'). 점이 없으면 (글 전부, '')."""
    head, _, tail = text.partition(SEP)
    return head, tail


@dataclass(frozen=True)
class Row:
    entry: Entry
    low: bool                    # 끝난 것·시기 모름: 글을 흐리게 보인다
    main: str                    # 언제까지 칸 첫 줄(굵게): 기간 · 끝난 것은 '올해 끝났어요'
    sub: str                     # 언제까지 칸 둘째 줄(작게): 남은 날 · '양파 먼저' · 끝난 것은 '내년 3월쯤 다시 받아요'
    urgent: bool = False         # 지금 받는 중이고 7일 안에 마감('곧 마감' 글자와 색)
    note: str = ""               # 작물마다 기간이 다를 때 어느 작물 기간인지(감귤 걸러 보기)
    left: str = ""               # 마감이 있는 줄(지금 받는 중)의 남은 날 글("8일 남음", "오늘 마감"): 자료의 글 그대로, 큰 표시로 보인다
    where: tuple[str, ...] = ()  # 어디서 신청해요 칸: 가실 곳 글(줄마다 한 곳). 자료가 없으면 빈 묶음(화면에 NO_LIST_WHERE)
    where_phones: tuple[str, ...] = ()   # where 와 같은 길이: 그 곳 이름 아래에 보일 자료의 전화번호(없거나 이름에 이미 번호가 있으면 "")
    where_asks: tuple[str, ...] = ()     # where 와 같은 길이: 한 곳이 아닌 곳(지역농협·읍·면·동)의 자료 전화번호. 접수 창구가 아니라 담당 부서 번호라 화면에 "문의"라고 달아 보인다(없으면 "")

    @property
    def where_parts(self) -> tuple[tuple[tuple[str, bool], ...], ...]:
        """where 의 곳마다 (조각, 전화번호인가) 묶음(템플릿이 그린다)."""
        return tuple(where_parts(w) for w in self.where)

    @property
    def show_main(self) -> str:
        """목록 날짜 칸 첫 줄. 끝난 지원은 15줄이 모두 '올해 신청은 끝났어요'라 글자 벽이 되므로(묶음 제목이 이미 말한다) '내년 1월쯤 다시 받아요'를 첫 줄로 올린다."""
        if self.low and self.main == ENDED_MAIN:
            m = next((p for p in self.sub.split(SEP) if _NEXT_SEASON.search(p)), "")
            if m:
                return m
        return self.main

    @property
    def show_sub(self) -> str:
        return SEP.join(p for p in self.sub.split(SEP) if p and p != self.show_main and p != self.left)

    @property
    def gray(self) -> str:
        """낮은 줄의 둘째 줄 글(다음 철)."""
        return self.sub if self.low else ""


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    rows: tuple[Row, ...]

    @property
    def count(self) -> int:
        return len(self.rows)


_NEXT_SEASON = re.compile(r"월쯤 다시 받아요$")        # 끝난 지원의 다음 철 글(texts.next_season): 첫 줄로 올릴 토막을 알아보는 데만 쓴다. 정렬은 Entry.window_month 로 한다
_LEFT = re.compile(r"\d+일 남음|오늘 마감")
_LIST_WHERE_LABEL = re.compile(r"^(?:접수처|신청장소|신청방법)\s*[:：]\s*")     # 칸 제목("어디서 신청해요")과 겹치는 앞머리


def list_where(e: Entry) -> tuple[str, ...]:
    """목록의 '어디서 신청해요' 칸 글. 글은 자료 그대로이고 앞머리만 뗀다(전화번호 칸은 싣지 않는다).
    표의 제도: 접수처 글에서 겹침을 빼고 원래 순서로 2곳까지, 더 있으면 '외 ○곳'. 새 공고: 접수처 첫 줄에서 '접수처:' 같은 앞머리를 뗀 글. 자료가 없으면 빈 묶음."""
    if e.kind == "notice":
        first = e.new_where[0] if e.new_where else ""
        return ((_LIST_WHERE_LABEL.sub("", first, count=1) or first),) if first else ()
    offices = tuple(dict.fromkeys(c.office for c in e.contacts if c.office))
    if len(offices) <= MAX_LIST_WHERE:
        return offices
    return (*offices[:MAX_LIST_WHERE], f"외 {len(offices) - MAX_LIST_WHERE}곳")


_PHONE_IN_TEXT = re.compile(r"\d{2,4}-\d{3,4}(?:-\d{4})?")
_NUMBER_IN_TEXT = re.compile(r"\d{3,4}-\d{3,4}|\d{4,}")        # ARS 1334 처럼 하이픈 없는 번호도 번호로 본다


_MANY_PLACES = re.compile(r"지역농협|읍[·\s]*면|주민센터|외 \d+곳")     # 한 곳이 아닌 곳: 자료의 번호는 도·시 담당과 번호라 접수 창구로 읽힌다


def list_phones(e: Entry, where: tuple[str, ...]) -> tuple[str, ...]:
    """where 의 곳마다 자료(Entry.contacts)에 있는 그 곳의 첫 전화번호. 자료에 없거나(새 공고) 한 곳이 아닌 곳(지역농협·읍·면·동·'외 ○곳': 그 번호는 담당과 것이라 창구 번호로 읽힌다, 2026-11-15 검수) 이거나 곳 이름에 이미 번호가 든 글이면 ""."""
    by_office: dict[str, str] = {}
    for c in e.contacts:
        if c.phone:
            by_office.setdefault(c.office, c.phone)
    return tuple("" if _NUMBER_IN_TEXT.search(w) or _MANY_PLACES.search(w) else by_office.get(w, "") for w in where)


def list_asks(e: Entry, where: tuple[str, ...]) -> tuple[str, ...]:
    """where 의 곳마다, 한 곳이 아닌 곳(지역농협·읍·면·동)에 자료가 적어 둔 전화번호(담당 부서 번호). 화면은 "문의"를 달아 보인다. 자료에 없거나 곳 이름에 이미 번호가 있으면 ""."""
    by_office: dict[str, str] = {}
    for c in e.contacts:
        if c.phone:
            by_office.setdefault(c.office, c.phone)
    return tuple(by_office.get(w, "") if _MANY_PLACES.search(w) and not _NUMBER_IN_TEXT.search(w) else "" for w in where)


def where_parts(text: str) -> tuple[tuple[str, bool], ...]:
    """가실 곳 글을 (조각, 전화번호인가) 로 나눈다. 글은 그대로이고 이어 붙이면 원문이다. 번호 조각은 화면이 줄바꿈 없이 그려 번호가 하이픈에서 갈라지지 않게 한다."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _PHONE_IN_TEXT.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return tuple(out)


def _row(shown: Entry, gid: str, orig: Entry, crop: str = "") -> Row:
    """shown: 기간을 읽을 쪽(걸러 보기에서 그 작물 줄만 볼 때는 그 줄의 기간으로 바꾼 것), orig: 이름·주소를 읽을 쪽."""
    e = shown
    raw = list_where(orig)                        # 자료의 곳 이름(전화번호를 이 이름으로 찾는다)
    where, phones, asks = tuple(office_say(w) for w in raw), list_phones(orig, raw), list_asks(orig, raw)       # 보일 때만 곳 이름을 한 가지 표기로
    if gid in LOW_GROUPS:
        cut = e.window.find(ENDED_PREFIX)
        rest = e.window[cut + len(ENDED_PREFIX):] if cut >= 0 else e.window
        if gid == "ended" and cut >= 0 and e.window_month is not None:        # 표의 지원: 첫 줄 '올해 신청은 끝났어요', 둘째 줄 다음 철. 새 공고는 공고 글('신청이 끝났어요')이 첫 줄
            label = e.window[:cut].strip()                                    # 작물마다 기간이 달라 이름이 앞에 붙은 글('감귤 올해 신청은 끝났어요 · …')은 이름을 덧말로
            main, sub = ENDED_MAIN, (label + SEP + rest if label else rest)
        else:
            main, sub = rest, ""
        if crop:
            sub = crop + SEP + sub if sub else crop
        if e.hold and main != NO_TIMING:          # 첫 줄이 이미 '창구에 물어보세요'면 '아직 확인 중'을 또 적지 않는다
            sub = sub + SEP + HOLD_NOTE if sub else HOLD_NOTE
        return Row(orig, True, main, sub, where=where, where_phones=phones, where_asks=asks)
    main, sub = split_window(e.window)
    note = crop and f"{crop} 기간이에요"
    if not crop and varies(e, "window"):           # 작물마다 기간이 다르다: 가장 이른 줄의 이름은 덧말로
        lab = next((v.label for v in e.variants if v.label and main.startswith(v.label + " ")), None)
        if lab:
            main, sub = main[len(lab) + 1:], (sub + SEP if sub else "") + f"{_ga(lab)} 제일 먼저예요"
    if e.hold and main != NO_TIMING:
        sub = (sub + SEP if sub else "") + HOLD_NOTE
    urgent = gid == "open" and e.window_days is not None and e.window_days <= URGENT_DAYS
    left = next((p for p in sub.split(SEP) if _LEFT.fullmatch(p)), "") if gid == "open" else ""
    return Row(orig, False, main, sub, urgent=urgent, note=note, where=where, left=left, where_phones=phones, where_asks=asks)


def _ga(word: str) -> str:
    """'마늘' → '마늘이', '양파' → '양파가'."""
    last = word.rstrip()[-1:]
    return word + ("이" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "가")


def _next_month_gap(month: int | None, today: date | None) -> int:
    """다음 신청 철(달)까지 남은 달 수(오늘 달이 1월이면 3월은 2). 오늘을 모르면 달 번호 그대로. 달을 모르면 맨 뒤. 글을 되읽지 않고 Entry.window_month 로 센다."""
    if month is None:
        return FAR
    return (month - today.month) % 12 if today else month


def groups_of(entries: Sequence[Entry], focus: str | None = None, today: date | None = None) -> tuple[Group, ...]:
    """묶음 다섯 개를 정해진 순서로. 빈 묶음은 뺀다. 묶음 안은 마감·시작이 가까운 순(끝난 것은 다음 철이 가까운 순), 같으면 이름순.
    focus(예: 'citrus')가 있으면 기간이 작물마다 다른 제도는 그 작물 줄의 기간으로 묶고 줄 세운다."""
    items = []
    for e in entries:
        v = best_focus(e, focus)
        if v:
            shown = replace(e, window=v.window, window_rank=v.rank, window_days=v.days, open_now=v.open_now, window_month=v.month)
            items.append((shown, e, v.label or ""))
        else:
            items.append((e, e, ""))

    def order(x: tuple[Entry, Entry, str], gid: str) -> tuple[int, str]:
        s = x[0]
        return (_next_month_gap(s.window_month, today) if gid == "ended" else s.window_days if s.window_days is not None else FAR, s.title)

    out = []
    for gid, title in GROUPS:
        mine = sorted((x for x in items if _group_of_window(x[0].window_rank, x[0].window) == gid), key=lambda x: order(x, gid))
        if mine:
            out.append(Group(gid, title, tuple(_row(s, gid, o, c) for s, o, c in mine)))
    return tuple(out)


# ---------- 안내 화면: 한눈에 띠 ----------

LONG_BIG = 22                    # 큰 값이 이보다 길면 글씨를 한 단계 줄여 두 줄 안에 담는다


@dataclass(frozen=True)
class Item:
    big: str                     # 큰 값
    small: tuple[str, ...] = ()  # 작은 덧말
    phone: bool = False          # 전화번호(더 크게)
    open: bool = False           # 지금 받는 중(색 말고 글로도 '까지·남음'이 적혀 있다)
    source: tuple[str, ...] = () # 공고에 적힌 원문 줄(접어서 보여 준다)

    @property
    def long(self) -> bool:
        return len(self.big) > LONG_BIG


@dataclass(frozen=True)
class Cell:
    id: str                      # 'amount' | 'when' | 'where'
    title: str
    items: tuple[Item, ...]


def _first_rest(lines: Sequence[str]) -> Item:
    return Item(lines[0], tuple(lines[1:]))


_WHERE_LABEL = re.compile(r"^(?:접수처|신청장소|신청방법)\s*[:：]\s*")
_SLASH = " / "


def where_line(text: str) -> str:
    """접수처 칸 글에서 '접수처:' 같은 앞 이름만 뗀다(칸 제목이 이미 '어디로'다). 뒤의 글은 그대로."""
    out = _WHERE_LABEL.sub("", text, count=1) or text
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", out))       # 괄호 안쪽 공백('(문의: 064-760-2883 )')만 다듬는다


def amount_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """공고의 금액 줄을 ' / '(공고가 항목을 나눈 자리)에서 나눠 첫 항목만 크게 보이게 한다. 글자는 그대로다."""
    return tuple(p for ln in lines for p in ln.split(_SLASH) if p.strip())


_LEGAL = ("｢", "｣", "「", "」", "알려드리오니", "바랍니다")


def is_legal(line: str) -> bool:
    """법 이름·공문 맺음말이 든 줄(어르신이 읽기 어려워 접어 둔다)."""
    return any(w in line for w in _LEGAL)


def split_legal(lines: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(그대로 보일 줄, 접어 둘 법률·공문 줄). 모두 법률·공문 줄이면 접지 않고 그대로 보인다."""
    plain = tuple(x for x in lines if not is_legal(x))
    return (plain, tuple(x for x in lines if is_legal(x))) if plain else (tuple(lines), ())


def varies(e: Entry, attr: str) -> bool:
    return len(e.variants) > 1 and len({getattr(v, attr) for v in e.variants}) > 1


def _contact_item(c) -> Item:
    """안내 화면 '어디서 신청해요' 한 곳. 한 곳이 아닌 곳(지역농협·읍·면·동)의 자료 전화번호는 접수 창구가 아니라 담당 부서 번호라 목록처럼 '문의'를 달아 작게 보인다. 곳 이름은 보일 때만 한 가지 표기로."""
    name = office_say(c.office)
    if c.phone and _MANY_PLACES.search(c.office) and not _NUMBER_IN_TEXT.search(c.office):
        return Item(name, (f"문의 {c.phone}",))
    return Item(c.phone, (name,), phone=True) if c.phone else Item(name)


def glance(e: Entry, focus: str | None = None) -> tuple[Cell, ...]:
    """얼마나 / 언제 / 어디로. focus(걸러 보기 이름)가 있고 기간이 작물마다 다르면 '언제'는 그 작물 줄의 기간을 보인다."""
    fv = best_focus(e, focus)
    # 얼마나
    if e.kind == "notice":
        amount = _first_rest(amount_lines(e.new_content_lines)) if e.new_content_lines else Item(ASK_AMOUNT)
    elif varies(e, "amount"):
        amount = Item(VARIES, (SEE_TABLE,))
    else:
        amount = Item(e.amount)
    # 언제
    if e.kind == "notice":
        main, sub = split_window(e.window)
        small = [sub] if sub else []
        src = (e.new_period_line,) if e.new_period_line and e.new_period_line != e.window else ()
        when = Item(main, tuple(small), open=e.window_rank == RANK_OPEN, source=src)
    elif fv:
        main, sub = split_window(fv.window)
        when = Item(main, tuple(x for x in (sub, PRIOR_NOTE if fv.prior_year else "", f"{fv.label} {FOCUS_NOTE}") if x), open=fv.open_now)
    elif varies(e, "window"):
        when = Item(VARIES, (SEE_TABLE, *((PRIOR_NOTE,) if e.prior_year else ())))
    else:
        main, sub = split_window(e.window)
        when = Item(main, tuple(x for x in (sub, PRIOR_NOTE if e.prior_year else "") if x), open=e.window_rank == RANK_OPEN)
    # 어디로
    if e.kind == "notice":
        where = (_first_rest([where_line(x) for x in e.new_where]),) if e.new_where else (Item(NO_WHERE),)
    elif e.contacts:
        where = tuple(_contact_item(c) for c in e.contacts)
    else:
        where = (Item(NO_WHERE),)
    return (Cell("amount", "얼마나", (amount,)), Cell("when", "언제 신청해요", (when,)), Cell("where", "어디서 신청해요", where))


# ---------- 안내 화면: 작물별 표 ----------

@dataclass(frozen=True)
class TableRow:
    label: str
    condition: str
    amount: str
    window: str
    prior: bool
    focus: bool = False          # 걸러 보기가 가리키는 작물 줄(굵게, 맨 위)


@dataclass(frozen=True)
class Section:
    caption: str                 # 이 묶음의 조건 글(같은 조건인 작물을 한 번만 적는다)
    rows: tuple[TableRow, ...]   # 값이 같은 작물은 한 줄로 묶은 줄


@dataclass(frozen=True)
class VariantTable:
    label_head: str              # '작물' | '지역'
    show_condition: bool
    show_amount: bool
    show_window: bool
    same_as_above: str           # 조건 칸이 빈 줄에 쓰는 말
    rows: tuple[TableRow, ...]   # 줄 하나가 행 하나
    sections: tuple[Section, ...] = ()   # 금액·시기가 다를 때: 조건이 같은 작물끼리 묶은 표(조건은 묶음 제목으로 한 번만)

    @property
    def by_condition(self) -> bool:
        return bool(self.sections)


_AREA_LABELS = ("읍·면 지역", "동 지역")


def _shown(v: Variant) -> list[str]:
    return [c for c in v.conditions if c != f"작물: {v.label}"]


def _sections(rows: Sequence[TableRow], same_as_above: str) -> tuple[Section, ...]:
    by: dict[str, list[TableRow]] = {}
    for r in rows:
        by.setdefault(r.condition, []).append(r)
    out = []
    for cond, rs in by.items():
        merged: dict[tuple, list[TableRow]] = {}
        for r in rs:
            merged.setdefault((r.amount, r.window, r.prior), []).append(r)
        lines = [TableRow(" · ".join(x.label for x in g), cond, g[0].amount, g[0].window, g[0].prior, any(x.focus for x in g))
                 for g in merged.values()]
        lines.sort(key=lambda r: not r.focus)                  # 걸러 보기 작물 줄이 맨 위(나머지는 원래 순서)
        caption = cond or (same_as_above if len(by) > 1 else "") or (NO_EXTRA if len(by) > 1 else "")
        out.append(Section(caption, tuple(lines)))
    out.sort(key=lambda s: not any(r.focus for r in s.rows))
    return tuple(out)


def variant_table(e: Entry, focus: str | None = None) -> VariantTable | None:
    """작물·읍면마다 다른 것을 표 하나로(작물 | 조건 | 신청 시기). 모든 줄이 같은 값이면 만들지 않는다(한 줄로 충분)."""
    if len(e.variants) < 2:
        return None
    cond = any(_shown(v) for v in e.variants)
    amt, win = varies(e, "amount"), varies(e, "window")
    if not (cond or amt or win):
        return None
    mixed = 0 < sum(v.prior_year for v in e.variants) < len(e.variants)
    foc = {v.label for v in focus_variants(e, focus)}
    rows = tuple(TableRow(v.label or "", SEP.join(_shown(v)), v.amount, v.window, v.prior_year and mixed, v.label in foc) for v in e.variants)
    head = "지역" if all(v.label in _AREA_LABELS for v in e.variants) else "작물"
    same = "위 조건과 같아요" if e.conditions else ""
    return VariantTable(head, cond, amt, win, same, rows, _sections(rows, same) if (amt or win) else ())
