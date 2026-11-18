"""지원 전체 보기의 자료(설계서 B-1, B-5). 화면은 이 모듈이 돌려주는 Catalog·Entry 의 글만 그대로 보여 준다.

- 표의 지원: supports.csv 의 행을 제도(program_key)로 묶는다(작물별·읍면별 행은 한 카드, 안에서 variants 로 나뉜다).
- 새 공고: data/catalog/notices 의 공고. 표의 같은 제도로 확인된 것(table_key 가 표에 있음)은 카드를 만들지 않는다(already).
- 기준일(as_of)은 부르는 쪽이 정한다. 이 모듈은 시계를 읽지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote

from app.catalog.links import Link
from app.catalog.notices import NoticeRecord
from app.catalog.tags import KIND_TAG, crop_labels, crop_names, group_tags
from app.catalog.texts import (
    ASK_AMOUNT,
    ASK_OFFICE,
    HOLD_NOTE,
    PRIOR_NOTE,
    RANK_UNKNOWN,
    amount_of,
    check_items,
    condition_lines,
    md,
    notice_window,
    plain_line,
    plain_lines,
    window_of,
)
from app.core.models import Program
from app.core.tables_models import TableBundle

BADGE_TABLE = "조건을 따져 드려요"
BADGE_NEW = "AI가 읽은 공고 · 조건은 창구에서 확인"
NEW_NOTICE_NOTE = "AI가 읽어 올린 공고예요. 금액과 자격은 따지지 않고 공고에 적힌 글만 보여 드려요"
MULTI_AMOUNT = "작물·지역마다 달라요. 아래에서 확인하세요"
FILTER_ALL, FILTER_OPEN, FILTER_NEW = "all", "open", "new"
CITRUS_CODES = ("감귤_노지", "감귤_만감")
FIELD_CROP_CODES = ("당근", "월동무", "양배추", "브로콜리", "마늘", "양파", "감자", "밭작물", "월동채소")
SENIOR_AGE = 60
FAR = 10**6
_VARIANT_LABEL = {"읍면": "읍·면 지역", "동": "동 지역"}
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


@dataclass(frozen=True)
class Contact:
    office: str
    phone: str | None


@dataclass(frozen=True)
class Variant:
    """제도 안의 한 행(작물별·읍면별). 행이 하나뿐이면 label 이 None 이다."""
    label: str | None
    window: str
    amount: str
    conditions: tuple[str, ...]       # 다른 행에는 없는 이 행만의 조건
    prior_year: bool
    open_now: bool
    rank: int = RANK_UNKNOWN          # 이 행의 신청 기간 순서(texts.RANK_*)와 남은 날. 걸러 보기에서 그 작물 줄만 볼 때 쓴다
    days: int | None = None
    month: int | None = None          # 끝난 행의 다음 신청 철 달(글을 되읽지 않고 정렬한다)


@dataclass(frozen=True)
class Entry:
    key: str                          # 주소에 쓰는 열쇠. 표의 제도는 program_key, 새 공고는 'new-...'
    kind: str                         # 'table' | 'notice'
    title: str
    crops: str                        # '당근 · 양배추' 처럼 작물 목록. 없으면 빈 글
    agency: str
    support_kind: str                 # '현금 지원', '보험료 지원' ... 새 공고는 빈 글
    tags: tuple[str, ...]
    badge: str                        # BADGE_TABLE | BADGE_NEW
    window: str                       # 카드의 신청 기간 한 줄
    window_rank: int
    window_days: int | None
    open_now: bool                    # 지금 신청을 받는다(확정된 행, 상시 포함)
    amount: str                       # '얼마나' 한 줄. 표에 없으면 '창구에서 확인'
    conditions: tuple[str, ...]       # '누가 받나요': 모든 행에 공통인 조건
    checks: tuple[str, ...]           # 창구에서 확인하는 것(표의 확인 항목 그대로)
    variants: tuple[Variant, ...]
    contacts: tuple[Contact, ...]
    documents: tuple[str, ...]
    link: Link | None
    verified_text: str                # '2026년 11월 7일에 확인했어요'. 새 공고는 '○일에 읽은 공고예요'
    verified_date: date
    prior_year: bool
    hold: bool
    notes: tuple[str, ...]            # 화면에 꼭 적을 안내(작년 기준, 확인 중, 새 공고)
    filters: frozenset[str]
    new_period: str = ""              # 새 공고: 공고 원문 그대로
    new_target: str = ""
    new_content: str = ""
    new_quotes: tuple[tuple[str, str], ...] = ()    # 새 공고 이름표와 그 근거 문장(저장된 그대로)
    window_start: date | None = None  # 새 공고: 신청 기간 글에서 읽은 시작일·마감일(못 읽으면 None)
    window_end: date | None = None
    # 새 공고 안내 화면에 보여 줄 글(앞머리 기호를 뗀 것). 같은 글이 두 칸에 겹치지 않게 칸마다 나눠 담는다.
    new_period_line: str = ""
    new_target_lines: tuple[str, ...] = ()
    new_content_lines: tuple[str, ...] = ()
    new_who: tuple[tuple[str, str], ...] = ()        # (이름표, 근거 인용). 인용이 따로 보일 필요가 없으면 빈 글
    new_where: tuple[str, ...] = ()                  # 접수처·신청장소·신청방법 줄
    new_rest: tuple[tuple[str, str], ...] = ()       # 다른 칸에 나오지 않은 이름표와 근거 인용
    window_month: int | None = None                  # 끝난 지원의 다음 신청 철 달(texts.Window.month). 목록 정렬이 쓴다

    @property
    def href(self) -> str:
        return support_href(self.key)

    @property
    def phone(self) -> str | None:
        """첫 번째 전화번호(없으면 None). 접수처가 여럿이면 contacts 를 쓴다."""
        return next((c.phone for c in self.contacts if c.phone), None)


@dataclass(frozen=True)
class FilterDef:
    id: str
    label: str
    count: int


FILTER_LABELS = ((FILTER_OPEN, "지금·언제든 신청"), ("citrus", "감귤"), ("field", "밭작물"), ("senior", "어르신"),
                 ("women", "여성"), ("insurance", "보험"), (FILTER_NEW, "AI가 읽은 공고"))


@dataclass(frozen=True)
class Catalog:
    as_of: date
    entries: tuple[Entry, ...]
    hidden_notices: int = 0                                           # 표의 제도와 같아서 카드를 만들지 않은 새 공고 수
    by_key: Mapping[str, Entry] = field(default_factory=dict, repr=False, compare=False)
    names: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)   # 표 행 이름 → 제도 열쇠

    @property
    def count(self) -> int:
        return len(self.entries)

    def get(self, key: str) -> Entry | None:
        return self.by_key.get(key)

    def filters(self) -> tuple[FilterDef, ...]:
        """걸러 보기 단추. 맨 앞은 '전체', 해당하는 것이 없는 묶음은 뺀다."""
        out = [FilterDef(FILTER_ALL, "전체", self.count)]
        for fid, label in FILTER_LABELS:
            n = sum(fid in e.filters for e in self.entries)
            if n:
                out.append(FilterDef(fid, label, n))
        return tuple(out)

    def select(self, filter_id: str | None) -> tuple[Entry, ...]:
        """걸러 본 카드(모르는 걸러 보기 이름이면 전체)."""
        known = {f.id for f in self.filters()}
        if not filter_id or filter_id == FILTER_ALL or filter_id not in known:
            return self.entries
        return tuple(e for e in self.entries if filter_id in e.filters)

    def key_for_name(self, name: str) -> str | None:
        """첫 화면 마감 카드의 이름(표 행의 이름)에서 제도 열쇠를 찾는다. 없으면 None."""
        return self.names.get(name)


def support_href(key: str) -> str:
    """지원 안내 화면 주소. 열쇠는 주소 조각으로 안전하게 바꾼다(새 공고 열쇠에는 한글이 든다)."""
    return f"/supports/{quote(key, safe='')}"


def key_for_name(programs: Sequence[Program], name: str) -> str | None:
    """Catalog 없이 표만으로 같은 일을 한다(첫 화면 마감 카드용)."""
    for p in programs:
        if (p.name or p.program_key) == name:
            return base_key(p)
    return None


def base_key(p: Program) -> str:
    """제도 열쇠: program_key 에서 @회차와 #변형을 뗀 것."""
    return p.program_key.split("@")[0].split("#")[0]


def _group_name(rows: Sequence[Program]) -> str:
    names = [r.name or r.program_key for r in rows]
    if len(names) > 1:
        stripped = {_TRAILING_PAREN.sub("", n) for n in names}
        if len(stripped) == 1:
            return stripped.pop()
    return names[0]


def _variant_label(p: Program) -> str | None:
    v = p.id.partition("#")[2]
    return _VARIANT_LABEL.get(v, v) or None


def _distinct(items) -> list:
    out: list = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def _filters(rows: Sequence[Program], open_now: bool) -> frozenset[str]:
    ids = set()
    codes = {c for r in rows for c in r.crop_in}
    if open_now:
        ids.add(FILTER_OPEN)
    if codes & set(CITRUS_CODES):
        ids.add("citrus")
    if codes & set(FIELD_CROP_CODES):
        ids.add("field")
    if any((r.min_age or 0) >= SENIOR_AGE for r in rows):
        ids.add("senior")
    if any(r.sex for r in rows):
        ids.add("women")
    if any(r.kind == "보험료지원" or "보험" in (r.name or "") for r in rows):
        ids.add("insurance")
    return frozenset(ids)


def _table_entry(rows: Sequence[Program], bundle: TableBundle, as_of: date, labels: Mapping[str, str],
                 links: Mapping[str, Link]) -> Entry:
    first = rows[0]
    key = base_key(first)
    multi = len(rows) > 1
    wins = [window_of(r, as_of) for r in rows]
    amounts = [amount_of(r) or ASK_AMOUNT for r in rows]
    cond_per_row = [condition_lines(r, labels) for r in rows]
    common = [c for c in cond_per_row[0] if all(c in other for other in cond_per_row[1:])]
    variants = tuple(Variant(
        label=_variant_label(r) if multi else None, window=w.text, amount=a,
        conditions=tuple(c for c in cl if c not in common), prior_year=r.status == "prior_year_reference",
        open_now=w.open_now, rank=w.rank, days=w.days, month=w.month) for r, w, a, cl in zip(rows, wins, amounts, cond_per_row, strict=True))
    head = min(wins, key=lambda w: (w.rank, w.days if w.days is not None else FAR))
    head_row = rows[wins.index(head)]
    head_text = head.text
    if multi and len({w.text for w in wins}) > 1 and (lab := _variant_label(head_row)):
        head_text = f"{lab} {head.text}"
    distinct_amounts = _distinct(amounts)
    contacts: list[Contact] = []
    for r in rows:
        office = r.office or ASK_OFFICE
        phone = r.phone or (o.phone if (o := bundle.office_named(r.office)) else None)
        if (c := Contact(office, phone)) not in contacts:
            contacts.append(c)
    crop_codes = [c for r in rows for c in r.crop_in]
    verified = min(r.verified_date for r in rows)
    prior = any(r.status == "prior_year_reference" for r in rows)
    hold = all(r.status == "hold" for r in rows)
    open_now = any(w.open_now for w in wins)
    return Entry(
        key=key, kind="table", title=_group_name(rows), crops=" · ".join(crop_names(crop_codes, labels)),
        agency=" · ".join(_distinct(r.agency for r in rows if r.agency)),
        support_kind=" · ".join(_distinct(KIND_TAG[r.kind] for r in rows)),
        tags=group_tags(rows, labels), badge=BADGE_TABLE, window=head_text, window_rank=head.rank, window_days=head.days,
        window_month=head.month, open_now=open_now, amount=distinct_amounts[0] if len(distinct_amounts) == 1 else MULTI_AMOUNT,
        conditions=tuple(common), checks=tuple(_distinct(i for r in rows for i in check_items(r))), variants=variants,
        contacts=tuple(contacts), documents=tuple(_distinct(r.documents for r in rows if r.documents)),
        link=links.get(key), verified_text=f"{verified.year}년 {md(verified)}에 확인했어요", verified_date=verified,
        prior_year=prior, hold=hold,
        notes=tuple(n for n, on in ((PRIOR_NOTE, prior), (HOLD_NOTE, hold)) if on), filters=_filters(rows, open_now))


_WHERE_WORDS = ("접수처", "신청장소", "신청방법")
ISSUER_LABEL = "공고 낸 곳: "
_TITLE_TAIL = 14
_TITLE_YEAR = re.compile(r"^\s*\d{4}\s*년\s*")


def _restates_title(line: str, title: str) -> bool:
    """줄이 공고 이름을 그대로 되풀이할 뿐인가(예: '2027년 ○○사업 신청·접수계획 알림'). 대상·조건 글이 아니다."""
    core = _TITLE_YEAR.sub("", title).strip()
    if not core or core not in line:
        return False
    left = re.sub(r"\d{4}\s*년", "", line.replace(core, ""))
    return len(left.strip()) <= _TITLE_TAIL           # 이름 말고 남는 말이 짧다('신청·접수계획 알림' 정도)


def _notice_texts(n: NoticeRecord) -> dict:
    """새 공고 안내 화면의 칸별 글. 가진 글(대상, 금액 줄, 이름표 근거)을 빠짐없이 쓰되 한 번씩만 나눠 담는다."""
    period = plain_line(n.apply_period)
    content = plain_lines(n.content)
    target = tuple(x for x in plain_lines(n.target) if not _restates_title(x, n.name))
    where = tuple(dict.fromkeys(x for x in (*plain_lines(n.apply_where), *(plain_line(t.quote) for t in n.tags)) if x and (
        x in plain_lines(n.apply_where) or any(w in x for w in _WHERE_WORDS))))      # 접수처 칸(v4)이 먼저, 이름표 근거 중 접수처 줄(v3)은 뒤에
    if n.agency and any(n.agency in w for w in where):
        shown_where = where
    elif n.agency and plain_lines(n.apply_where):
        shown_where = (*where, n.agency)          # 가실 곳(접수처 칸)이 먼저, 담당 부서는 뒤(목록은 첫 줄만 보인다)
    elif n.agency:
        shown_where = (f"{ISSUER_LABEL}{n.agency}", *where)      # 접수처가 없을 때 부서 이름만 쓰면 그 부서로 가야 하는 것처럼 읽힌다
    else:
        shown_where = where
    used = {x for x in (period, *content, *target, *where) if x}
    who: list[tuple[str, str]] = []
    rest: list[tuple[str, str]] = []
    for t in n.tags:
        q = plain_line(t.quote)
        if q in used:
            continue                                  # 같은 글이 이미 다른 칸에 있다
        if not target and _restates_title(q, n.name):
            who.append((t.label, ""))                 # 이름표만(근거 인용은 공고 이름을 되풀이할 뿐)
        elif not target:
            who.append((t.label, q))
        else:
            rest.append((t.label, "" if _restates_title(q, n.name) else q))
    return {"period": period, "target": target, "content": content, "where": shown_where, "who": tuple(who), "rest": tuple(rest)}


def _about_citrus(n: NoticeRecord) -> bool:
    """감귤 농가가 대상인 새 공고인가: 이름이나 대상 글, 이름표 말에 '감귤'이 있다. 근거 문장 속 부서 이름('감귤유통과')은 세지 않는다."""
    return any("감귤" in x for x in (n.name, n.target, *(t.label for t in n.tags)))


def _notice_entry(n: NoticeRecord, as_of: date) -> Entry:
    link = Link(n.key, n.url, "공고 원문", n.name, n.read_date) if n.url else None
    w, start, end = notice_window(n.apply_period, n.read_date, as_of)
    x = _notice_texts(n)
    return Entry(
        key=n.key, kind="notice", title=n.name, crops="", agency=n.agency, support_kind="",
        tags=tuple(t.label for t in n.tags[:4]), badge=BADGE_NEW, window=w.text,
        window_rank=w.rank, window_days=w.days, open_now=w.open_now, amount=ASK_AMOUNT, conditions=(), checks=(), variants=(),
        contacts=(), documents=(), link=link, verified_text=f"{n.read_date.year}년 {md(n.read_date)}에 읽은 공고예요",
        verified_date=n.read_date, prior_year=False, hold=False, notes=(NEW_NOTICE_NOTE,),
        filters=frozenset({FILTER_NEW, *((FILTER_OPEN,) if w.open_now else ()), *(("citrus",) if _about_citrus(n) else ())}),
        new_period=n.apply_period, new_target=n.target, new_content=n.content,
        new_quotes=tuple((t.label, t.quote) for t in n.tags), window_start=start, window_end=end,
        new_period_line=x["period"], new_target_lines=x["target"], new_content_lines=x["content"], new_who=x["who"],
        new_where=x["where"], new_rest=x["rest"])


def build_catalog(bundle: TableBundle, as_of: date, links: Mapping[str, Link] | None = None,
                  notices: Sequence[NoticeRecord] = ()) -> Catalog:
    """목록 자료를 만든다. 새 공고가 앞(마감 가까운 순, 끝난 것은 새 공고 맨 뒤), 그다음 신청 기간이 급한 순서(지금 받는 것, 곧 열리는 것, 상시, 다음 철), 같으면 이름순."""
    labels = crop_labels(bundle.crops)
    groups: dict[str, list[Program]] = {}
    for p in bundle.programs:
        groups.setdefault(base_key(p), []).append(p)
    table_entries = [_table_entry(rows, bundle, as_of, labels, links or {}) for rows in groups.values()]
    table_entries.sort(key=lambda e: (e.window_rank, e.window_days if e.window_days is not None else FAR, e.title))
    shown = [n for n in notices if not (n.table_key and n.table_key in groups)]
    new_entries = [_notice_entry(n, as_of) for n in shown]
    new_entries.sort(key=lambda e: (e.window_rank, e.window_days if e.window_days is not None else FAR))   # 마감 가까운 순, 끝난 것은 맨 뒤(같으면 불러온 순서)
    entries = tuple(new_entries + table_entries)
    return Catalog(as_of=as_of, entries=entries, hidden_notices=len(notices) - len(shown),
                   by_key={e.key: e for e in entries},
                   names={(p.name or p.program_key): k for k, rows in groups.items() for p in rows})
