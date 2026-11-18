"""가실 곳별 카드 묶음 층(2026-11-14 결과 화면·종이 단순화 설계 1·2·3절).

Sheet(종이 배치 모델)의 줄을 가실 곳(접수처)별 카드로 다시 묶어 결과 화면과 종이 앞면·뒷면이 같이 쓴다.
판정·금액·글은 하나도 새로 만들지 않는다: 카드 속 글은 모두 Sheet 줄(Line)의 title·text·sub·detail·badge 그대로이고,
묶는 순서와 접는 규칙만 여기서 정한다. 줄은 program_key당 하나(Sheet 규칙)라 같은 지원이 두 번 나오지 않는다.

build_cards(sheet, fs, narr) → CardSet
  conclusion     맨 위 결론 한 줄(설계 2절 규칙) · conclusion_line: 그 글의 숫자 출처가 될 줄
  lead           한마디로 칸의 AI 쉬운 말 문장(검수를 통과한 것, 최대 둘: 할 일 첫 문장, 지원 첫 문장)
  cards          가실 곳 카드 최대 셋(MAX_CARDS). 먼저 하실 일이 있으면 그 카드가 첫 카드. 카드마다 보이는 줄 최대 셋과 hidden(외 ○가지)
  others         그 밖에: 넷째 카드부터(번호 없는 카드)
  later          올해는 어려운 것(이름 + 먼저 필요한 것). 자세한 조건은 뒷면(reduced)
  keeps          끊기지 않게 할 일(경영체 갱신·직불 교육) · notes 알아 두세요(영농도우미·재해 피해) · bring 가실 때 · docs 서류
  basis          기준 연도 표시 한 번("2026년 기준 · 2027년 공고 전") · basis_line 출처 줄
  count          받을 수 있는 지원 가짓수(화면 결론 줄의 ○가지)
  reduced        앞면에서 줄인 내용(뒷면 맨 위 구획용): 지원마다 한 줄
  ref            program_key → 뒷면 대조표에 찍을 앞면 번호(①~③, 그 밖에, 올해는 어려운 것)
"""
import re
from collections.abc import Mapping

from app.core.models import CoreModel, FactSheet
from app.core.sheet import _PREREQ_TITLE, CIRCLED, EmptyFront, Line, Sheet, _own_emd_office, _short_office
from app.core.sheet_rules import CHECK_TAG, PREREQ_MONEY, join

MAX_CARDS = 3                  # 카드는 많아야 셋(설계 1절)
MAX_CARD_LINES = 3             # 한 카드에 넷 이상이면 셋만 보이고 "외 ○가지"
MAX_LEAD = 2                   # 한마디로 칸의 AI 문장 수
SMALL_DETAIL_CHARS = 40        # 먼저 하실 일 줄의 부연(detail)이 이보다 길면 앞면에 안 올리고 뒷면으로
TODO_KINDS = frozenset({"URGENT", "DISASTER_REPORT", "INSURANCE_CLAIM", "PREREQ", "ASK_COOP"})   # 먼저 하실 일 줄
NOT_SUPPORT = frozenset({"PREREQ", "ASK_COOP", "KEEP", "DISASTER_REPORT", "INSURANCE_CLAIM", "OFFICE", "FIXED", "NOTICE"})
MGMT_OFFICE = "국립농산물품질관리원 제주지원(농관원)"        # 경영체 등록 창구(sheet._prereq_line과 같은 접수처 이름)
MGMT_PHONE_MARK = "농관원 1644-8778"
LATER_LABEL, OTHER_LABEL = "올해는 어려운 것", "그 밖에"


class CardLine(CoreModel):
    line: Line                  # 원래 줄(숫자 출처 표시용)
    title: str
    text: str                   # 금액·시기(오른쪽 굵은 글). 먼저 하실 일은 한 줄 결론("조건이 맞으면 연 약 …")
    small: str | None           # 아래 작은 줄: "언제 · 확인할 조건 있음"
    extra: str | None           # 앞면에 남기는 단서("작년 kg당 … · 예측 아님")
    todo: bool                  # 먼저 하실 일 줄
    check: bool                 # 확인할 조건 있음
    counted: bool               # 받을 수 있는 지원 가짓수에 센다
    role: str                   # 화면의 좌우 나누기용(2026-11-14 2차): "do" 하실 일(연필) · "confirm" 확인하실 일(체크) · "insurance" 보험(우산) · "benefit" 받을 수 있는 것(동전)
    place_notes: tuple[str, ...] = ()   # 합친 상자 안에서 이 줄이 원래 어느 곳 이름에서 왔는지(line_notes): "밭(과수원)이 있는 곳의 읍·면사무소에서 신청해요", "대정농협" …


class Card(CoreModel):
    no: str                     # ① ② ③ (그 밖에 묶음은 "")
    office: str | None          # 접수처 표(offices.csv)의 이름 그대로
    place: str | None           # 가실 곳 이름(짧게)
    phone: str | None
    place_full: str | None      # 접수처 표의 전체 이름(읍면 이름으로 줄였을 때)
    lines: tuple[CardLine, ...]     # 보이는 줄(최대 셋)
    hidden: tuple[CardLine, ...]    # 접힌 줄("외 ○가지")
    first: bool                 # 먼저 하실 일이 든 카드
    emphasis: bool              # 첫 카드(감귤색 테두리)

    @property
    def all_lines(self) -> tuple[CardLine, ...]:
        return self.lines + self.hidden


class LaterItem(CoreModel):
    line: Line
    title: str
    need: str                   # 먼저 필요한 것("자조금 + 농협 출하")
    sub: str | None
    place: str | None


class ReducedRow(CoreModel):
    where: str                  # ① ② ③ · 그 밖에 · 올해는 어려운 것 · 끊기지 않게
    title: str
    pieces: tuple[str, ...]     # 금액·시기, 조건 줄, 부연, 확인 달 … (줄에 있던 글 그대로)
    place: str | None
    line: Line


class CardSet(CoreModel):
    empty: bool
    conclusion: str
    conclusion_line: Line | None
    narr: dict[str, tuple[str, ...]]
    lead: tuple[str, ...]
    back_sentences: tuple[str, ...]
    cards: tuple[Card, ...]
    others: tuple[Card, ...]
    later_cards: tuple[Card, ...] = ()      # 종이 앞면 「앞으로 신청할 것」에 실린 줄(줄 하나가 카드 하나, 번호 없음). 화면과 기본 묶음에서는 비어 있다
    later: tuple[LaterItem, ...]
    keeps: tuple[Line, ...]
    notes: tuple[Line, ...]
    bring: Line | None
    docs: Line | None
    footer: tuple[Line, ...]
    basis: str | None
    basis_line: Line | None
    count: int
    todo_n: int
    reduced: tuple[ReducedRow, ...]
    ref: dict[str, str]
    unlocks: dict[str, tuple[str, ...]]     # 먼저 하실 일 줄 제목 → 그것을 하면 열리는 제도의 program_key
    names: dict[str, str]                   # program_key → 제도 이름(뒷면 조건표의 이름)

    @property
    def card_lines(self) -> tuple[CardLine, ...]:
        return tuple(cl for c in (*self.cards, *self.later_cards, *self.others) for cl in c.all_lines)

    @property
    def others_count(self) -> int:
        return sum(len(c.all_lines) for c in self.others)


def short_title(title: str) -> str:
    """결론 한 줄에 쓰는 먼저 하실 일의 짧은 이름: '농업경영체 등록 (농관원)' → '경영체 등록'. 끊기지 않게 줄 앞 말머리는 뗀다."""
    t = re.sub(r"\s*\([^)]*\)\s*$", "", title).replace("농업경영체", "경영체")
    return t.removeprefix("끊기지 않게 · ").strip()


EMD_KEY, COOP_KEY = "@읍면동", "@농협"
# 합치는 두 무리의 상자 이름(2026-11-15 사장 지시: 최대한 합친다). 자료(supports.csv)가 지원마다 다르게 적은 같은 창구를 한 상자로 둔다.
# 읍·면·동 무리: 주소지·거주지·농지 소재(지)·농지가 있는·과원 소재지·피해 농지 또는 주소지·교통복지카드의 읍·면·동(사무소·주민센터). 농협 무리: 지역농협류와 읍·면에 맞춰 뽑은 농협.
MERGED_OFFICE = {EMD_KEY: "읍·면사무소, 동 주민센터", COOP_KEY: "농협"}
FARMLAND_NOTE = "밭(과수원)이 있는 곳의 읍·면사무소에서 신청해요"      # 집과 밭이 다른 읍·면에 있으면 가실 곳이 다르다: 농지·과원 쪽 곳에서 온 줄에만 단다
DISASTER_NOTE = "피해를 입은 농지나 주소지의 읍·면사무소에서 신청해요"
_ONLINE_NOTE = re.compile(r"\(비대면:\s*([^)]*)\)")
_EMD = r"읍[·ㆍ]?면[·ㆍ]?동"
_HOME_NAME = re.compile(rf"(?:(?:주소지|거주지)\s*(?:{_EMD}|읍[·ㆍ]?면\s*사무소(?:\s*,\s*동\s*주민센터)?|읍\s*\(면\)\s*사무소|주민센터|동\s*주민센터)|{_EMD})")
_FARMLAND_NAME = re.compile(rf"(?:농지(?:\s*소재지?|가\s*있는)|과원\s*소재지)\s*{_EMD}(?:\s*사무소)?")
_DISASTER_NAME = re.compile(rf"피해\s*농지\s*또는\s*주소지\s*{_EMD}")
_COOP_NAME = re.compile(r"(?:(?:거주지|농지\s*소재지?|서귀포시\s*관내)\s*)?지역\s*농(?:협|[·ㆍ][감축]협)|(?:[가-힣]+[·ㆍ])*[가-힣]+농협,\s*수급관리센터")


def _bare(office: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", office).strip()        # 끝의 괄호 덧말('(비대면: …)', '(집에서는 …)', '(교통복지카드)', '(신청 주체)')은 이름이 아니다


def _kind(office: str) -> tuple[str | None, str]:
    """(무리 열쇠, 무리 안의 종류). 종류: home · farm · disaster · coop. 이름 전체가 꼭 맞아야 한다(그 밖의 곳·'별도 신청 없음 … 지역농협·농관원 확인'은 안 합친다)."""
    for name in (office.strip(), _bare(office)):
        if _HOME_NAME.fullmatch(name):
            return EMD_KEY, "home"
        if _FARMLAND_NAME.fullmatch(name):
            return EMD_KEY, "farm"
        if _DISASTER_NAME.fullmatch(name):
            return EMD_KEY, "disaster"
        if _COOP_NAME.fullmatch(name):
            return COOP_KEY, "coop"
    return None, ""


def merge_group(office: str) -> str | None:
    """두 무리(EMD_KEY 읍·면·동 · COOP_KEY 농협) 가운데 어디 드는 접수처 이름인가. 어느 쪽도 아니면 None."""
    return _kind(office)[0]


def _office_key(office: str) -> str:
    """상자 묶는 열쇠: 괄호 앞 이름. 같은 창구를 다르게 적은 두 무리는 한 열쇠로 모은다."""
    return merge_group(office) or office.split("(")[0].strip()


_COOP_SAY = {"거주지 지역농협": "사시는 곳의 지역농협", "농지 소재지 지역농협": "농지가 있는 곳의 지역농협", "농지 소재 지역농협": "농지가 있는 곳의 지역농협",
             "서귀포시 관내 지역 농·감협": "서귀포시 안의 지역 농·감협"}


def _online_text(office: str) -> str | None:
    m = _ONLINE_NOTE.search(office)
    return "집에서는 " + m[1].strip().replace("·", "나 ").replace("ARS ", "전화 ") if m else None


def line_notes(office: str | None, emd: str) -> tuple[str, ...]:
    """합친 상자 안의 줄에 다는 작은 글(그 줄이 원래 어느 곳 이름에서 왔는지). 합치지 않는 곳·읍·면사무소 주소지 쪽 줄·그냥 '지역농협'은 없다.
    농지·과원 쪽 → 밭이 있는 곳의 읍·면사무소 안내(+ 집에서 하는 길), 피해 농지 → 피해 농지 안내, 농협은 이름이 그냥 '지역농협'이 아니면 그 이름(읍·면에 맞는 농협은 그 이름)."""
    if not office:
        return ()
    key, kind = _kind(office)
    if key == EMD_KEY:
        return tuple(n for n in ({"farm": FARMLAND_NOTE, "disaster": DISASTER_NOTE}.get(kind), _online_text(office)) if n)
    if key == COOP_KEY:
        name, full = _own_emd_office(office, emd)
        bare = _bare(office)
        if full:
            return (name,)
        if office.strip() == "지역농협":
            return ()
        if bare == "지역농협":
            return (office.strip(),)        # '지역농협(신청 주체)': 이름 그대로
        return (_COOP_SAY.get(bare, bare),)
    return ()


def _role(l: Line, todo: bool, check: bool) -> str:
    """줄의 종류(화면 좌우 나누기): 먼저 하실 일 줄은 왼쪽(확인하는 일이면 체크, 아니면 연필), 나머지는 오른쪽(보험은 우산, 그 밖은 동전)."""
    if todo:
        return "confirm" if check or l.kind == "ASK_COOP" else "do"
    return "insurance" if l.kind == "INSURANCE" else "benefit"


def _card_line(l: Line, counted: bool, place_notes: tuple[str, ...] = ()) -> CardLine:
    todo = l.kind in TODO_KINDS
    check = l.print_tag == "CHECK"
    if l.kind == "PREREQ":      # 먼저 하실 일: 아래 작은 줄은 신청 시기 부연(전화·참여 신청 메모는 가실 곳·뒷면으로)
        small = join(l.detail if l.detail and len(l.detail) <= SMALL_DETAIL_CHARS else None, CHECK_TAG if check else None)
    else:
        small = l.sub
    extra = l.detail if not todo and l.detail and "예측 아님" in l.detail else None
    return CardLine(line=l, title=l.title, text=l.text, small=small, extra=extra, todo=todo, check=check, counted=counted, role=_role(l, todo, check), place_notes=place_notes)


def _pieces(l: Line) -> tuple[str, ...]:
    """뒷면 '앞면에서 줄인 내용'에 줄 글을 그대로. 배지는 앞면 머리로 올라간 '○년 기준 · ○년 공고 전'을 빼고 확인 달만 남긴다."""
    month = " · ".join(l.badge.split(" · ")[2:]) if l.badge else None
    return tuple(p for p in (l.text, l.sub, l.detail, month) if p)


def build_cards(sheet: Sheet, fs: FactSheet, narr: Mapping[str, tuple[str, ...]] | None = None, *,
                max_cards: int = MAX_CARDS, max_lines: int = MAX_CARD_LINES) -> CardSet:
    """Sheet + FactSheet → 카드 묶음. narr는 검수·숫자 걸러내기를 거친 {'action'|'support'|'insurance'|'empty': 문장들}.
    max_cards·max_lines는 종이가 한 장에 안 들어갈 때 렌더러가 줄여 다시 부르는 상한이다(기본은 설계의 셋·셋)."""
    narr = {k: tuple(v) for k, v in (narr or {}).items() if v}
    front, back = sheet.front, sheet.back
    names, phones = back.office_names, back.office_phones
    phone_of = {names[i]: p for i, p in phones.items() if i in names}
    coop = names.get("coop")
    emd = fs.profile.emd_code

    def place_of(office: str | None) -> tuple[str | None, str | None, str | None]:
        if not office:
            return None, None, None
        name, full = _own_emd_office(office, emd)
        short = _short_office(name)
        phone = phone_of.get(office)
        if phone and phone in short:        # '(비대면: … ARS 1334)'처럼 이름에 전화가 이미 있으면 다시 적지 않는다
            phone = None
        return short, phone, (full or (office if short != office else None))

    docs = None
    if isinstance(front, EmptyFront):
        fixed, footer = front.fixed, front.footer
    else:
        fixed, footer = front.fixed, front.sections["G"]
        docs = next((l for l in front.sections["F"] if l.title == "가져오실 서류"), None)
    bring = next((l for l in fixed if l.title == "가실 때"), None)
    notes = tuple(l for l in fixed if l.title in ("영농도우미", "재해 피해"))
    lead_pool = tuple(s for slot in ("action", "support") for s in narr.get(slot, ())[:1])
    lead = tuple(narr.get("empty", ())[:1]) if isinstance(front, EmptyFront) else lead_pool[:MAX_LEAD]
    back_sentences = tuple(s for v in narr.values() for s in v if s not in lead)

    if isinstance(front, EmptyFront):
        lines = (*front.keep_actions, *front.insurance_next)
        reduced = tuple(ReducedRow(where="끊기지 않게" if l.kind == "KEEP" else "보험", title=l.title, pieces=_pieces(l), place=None, line=l)
                        for l in lines)
        return CardSet(empty=True, conclusion=front.title, conclusion_line=None, narr=narr, lead=lead,
                       back_sentences=back_sentences, cards=(), others=(), later=(), keeps=front.keep_actions, notes=notes,
                       bring=bring, docs=None, footer=footer, basis=_basis([front.badge] if front.badge else [l.badge for l in lines if l.badge]),
                       basis_line=next((l for l in lines if l.badge), None), count=0, todo_n=0, reduced=reduced, ref={}, unlocks={}, names={})

    status_of = {m.program_id: m.status for m in fs.matches}
    key_of = {m.program_id: m.program_key for m in fs.matches}
    name_of = {lc.program_key: lc.name for lc in back.line_conds}
    health_unknown = fs.profile.health_ins in (None, "unknown")
    pool = [l for s in ("A", "B", "C", "D", "E", "E2") for l in front.sections[s]] + list(sheet.overflow)
    keeps = tuple(l for l in pool if l.kind == "KEEP")

    def blocked(l: Line) -> bool:
        return l.kind == "COOP_SWITCH" or status_of.get(l.program_id or "") == "BLOCKED_PREREQ"

    def maybe(l: Line) -> bool:       # 건강보험 종류를 모르면 받을 수 있는지 아직 모른다: 지원 가짓수에서 뺀다
        return health_unknown and (l.program_id or "").startswith("NHIS-") and l.kind not in NOT_SUPPORT

    def office_of(l: Line) -> str | None:
        if l.office:
            return l.office
        if l.kind == "ASK_COOP":
            return coop
        if l.kind == "PREREQ" and (MGMT_PHONE_MARK in (l.sub or "") or "(농관원)" in l.title):
            return MGMT_OFFICE
        return None

    later_lines = [l for l in pool if blocked(l)]
    body = [l for l in pool if l.kind != "KEEP" and not blocked(l)]
    groups: dict[str, list[Line]] = {}
    for l in body:
        o = office_of(l)
        groups.setdefault(_office_key(o) if o else "", []).append(l)

    def rank(item: tuple[str, list[Line]]) -> tuple[int, int]:
        todo_idx = [i for i, l in enumerate(body) if l in item[1] and l.kind in TODO_KINDS]
        return (0, todo_idx[0]) if todo_idx else (1, body.index(item[1][0]))

    built: list[Card] = []
    for i, (key, lines) in enumerate(sorted(groups.items(), key=rank)):
        lines = sorted(lines, key=lambda l: l.kind not in TODO_KINDS)      # 먼저 하실 일 줄이 카드 안 맨 위(나머지는 줄 순서 그대로)
        merged = key in MERGED_OFFICE
        cls = [_card_line(l, l.kind not in NOT_SUPPORT and not maybe(l), line_notes(office_of(l), emd) if merged else ()) for l in lines]
        offices = [o for l in lines if (o := office_of(l))]
        office = MERGED_OFFICE[key] if merged else (offices[0] if offices else None)      # 합친 상자는 이름만 한 가지로(전화·덧말은 그 지원의 줄로 내려간다)
        place, phone, full = place_of(office)
        built.append(Card(no=CIRCLED[i] if i < max_cards else "", office=office, place=place, phone=phone, place_full=full,
                          lines=tuple(cls[:max_lines]), hidden=tuple(cls[max_lines:]),
                          first=any(c.todo for c in cls), emphasis=(i == 0)))
    cards, others = tuple(built[:max_cards]), tuple(built[max_cards:])

    ref: dict[str, str] = {}
    for c in cards:
        for cl in c.all_lines:
            if cl.line.program_key:
                ref.setdefault(cl.line.program_key, c.no)
    for c in others:
        for cl in c.all_lines:
            if cl.line.program_key:
                ref.setdefault(cl.line.program_key, OTHER_LABEL)
    later = tuple(LaterItem(line=l, title=l.title, need=re.sub(r"^먼저:\s*", "", l.text), sub=l.sub, place=place_of(office_of(l))[0])
                  for l in later_lines)
    for l in later_lines:
        if l.program_key:
            ref.setdefault(l.program_key, LATER_LABEL)

    # 먼저 하실 일을 하면 열리는 제도(이름은 뒷면 조건표의 이름): 뒷면 대조표에서 그 먼저 하실 일 카드 번호로 찾게 한다
    unlocks: dict[str, tuple[str, ...]] = {}
    for a in fs.actions:
        if a.kind != "PREREQ":
            continue
        title = _PREREQ_TITLE.get(a.action_id.split(":", 1)[1])
        keys = [key_of[i] for i in a.unlocks if i in key_of]
        if title:
            unlocks[title] = tuple(dict.fromkeys(keys))
        card = next((c for c in cards for cl in c.all_lines if cl.line.kind == "PREREQ" and cl.line.title == title), None)
        for k in keys:
            ref.setdefault(k, card.no if card else "-")

    count = sum(1 for cl in (*(x for c in cards for x in c.all_lines), *(x for c in others for x in c.all_lines)) if cl.counted)
    todo_lines = [l for l in body if l.kind in TODO_KINDS]
    conclusion_line = None
    if todo_lines and cards and cards[0].first:
        first = cards[0].lines[0].line
        conclusion_line = first
        money = re.search(r"연 .*$", first.text)
        short = short_title(first.title)
        if first.kind == "PREREQ" and first.text.startswith(PREREQ_MONEY) and money:
            conclusion = f"{short}부터 하세요. {PREREQ_MONEY} {money.group(0)} 받을 수 있어요"
        else:
            conclusion = f"먼저 {short}부터 하세요"
    elif count:
        conclusion = f"받을 수 있는 지원 {count}가지를 찾았어요"
    elif cards:
        conclusion = "받을 수 있는지 창구에서 확인하실 지원이 있어요"
    else:
        conclusion = "올해는 받기 어려워요. 내년에 하려면 먼저 할 일이 있어요"

    prior = [l for l in pool if l.badge]
    reduced: list[ReducedRow] = []
    for c in (*cards, *others):
        for cl in c.all_lines:
            reduced.append(ReducedRow(where=c.no or OTHER_LABEL, title=cl.title, pieces=_pieces(cl.line), place=c.place, line=cl.line))
    reduced += [ReducedRow(where=LATER_LABEL, title=it.title, pieces=_pieces(it.line), place=it.place, line=it.line) for it in later]
    reduced += [ReducedRow(where="끊기지 않게", title=l.title, pieces=_pieces(l), place=None, line=l) for l in keeps]
    return CardSet(empty=False, conclusion=conclusion, conclusion_line=conclusion_line, narr=narr, lead=lead,
                   back_sentences=back_sentences, cards=cards, others=others, later=later, keeps=keeps, notes=notes,
                   bring=bring, docs=docs, footer=footer, basis=_basis([l.badge for l in prior]),
                   basis_line=next((l for l in prior if l.program_id), prior[0] if prior else None), count=count,
                   todo_n=len(todo_lines) + sum(1 for l in later_lines if l.kind == "COOP_SWITCH"),
                   reduced=tuple(reduced), ref=ref, unlocks=unlocks, names=name_of)


def _basis(badges: list[str | None]) -> str | None:
    """줄마다 붙던 '2026년 기준 · 2027년 공고 전 · N월 확인'에서 앞의 둘만 모아 한 번만 적는다(N월 확인은 뒷면). 다르면 ' / '로 이어 둘 다."""
    heads = list(dict.fromkeys(" · ".join(b.split(" · ")[:2]) for b in badges if b))
    return " / ".join(heads) or None
