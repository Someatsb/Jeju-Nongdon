"""결과 화면(/counsel/preview)에 보이는 값(2026-11-14 설계 2절): 종이(Sheet)와 상담 근거(FactSheet)에서만 만든다. 종이에 없는 말은 지어내지 않는다.

카드는 종이와 같은 묶음(app/core/sheet_cards.build_cards)을 그대로 쓴다. 화면에서 따로 다시 묶지 않는다.
build_view()가 돌려주는 dict: conclusion(결론 한 줄) · conclusion_parts(꺾는 자리) · sub(AI 쉬운 말 한 문장) · who(답 요약 한 줄) ·
cards(가실 곳별 카드 최대 셋) · others_n(그 밖에 ○가지) · detail(자세히 보기 덮개 내용) · place_name(인쇄 뒤 안내용 첫 가실 곳) · speak(소리로 듣기 글).
"""
import re
from collections.abc import Mapping, Sequence
from datetime import date

from markupsafe import Markup, escape

from app.catalog.texts import RANK_LATER, RANK_SOON, window_of
from app.core.office_say import office_say
from app.core.actions import crop_of
from app.core.models import FactSheet
from app.core.sheet import _PREREQ_TITLE, EmptyFront, Sheet
from app.core.sheet_cards import Card, CardLine, CardSet, build_cards
from app.core.sheet_rules import CHECK_TAG, PREREQ_MONEY, first_segment
from app.ui.checklist import OTHER as ASK_OTHER, entries as ask_entries
from app.core.units import PYEONG_M2

M2_PER_PY = float(PYEONG_M2)    # 1평 = 3.3058㎡ (forms.py의 평→㎡ 환산의 거꾸로)
SALES_TAG = {"coop": "농협에 내요", "field_contract_done": "밭째 넘겼어요", "merchant_planned": "상인에게 팔 거예요", "direct": "직접 팔아요"}


def short_office(name: str) -> str:
    """'국립농산물품질관리원 제주지원(농관원)' → '농관원 제주지원'. 형식이 다르면 원문."""
    m = re.fullmatch(r"(.+\s)(\S+)\((\S+)\)", name)
    return f"{m[3]} {m[2]}" if m else name


def _won_py(area_m2: float | None) -> str | None:
    return None if not area_m2 else f"{round(area_m2 / M2_PER_PY):,}평"


def eun(word: str) -> str:
    """'은'/'는'."""
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣":
        return word + ("는" if (ord(last) - 0xAC00) % 28 == 0 else "은")
    return word + "은"


def tags(fs: FactSheet, crop_labels: dict[str, str], as_of: date) -> list[tuple[str, int]]:
    """답한 내용 꼬리표 (글, 고칠 질문 단계): 읍면동(1) · 작물 평수(2) · 나이 성별(3) · 경영체(4) · 파는 곳(5). 누르면 그 질문으로 돌아간다."""
    p = fs.profile
    out = [(p.emd_code, 1)]
    for c in p.crops:
        py = _won_py(c.area_m2)
        out.append((crop_labels.get(c.crop_code, c.crop_code) + (f" {py}" if py else ""), 2))
    if p.birth_year:
        sex = {"F": " 여자", "M": " 남자"}.get(p.owner_sex or "", "")
        out.append((f"{as_of.year - p.birth_year}세{sex}", 3))
    elif p.owner_sex:
        out.append(({"F": "여자", "M": "남자"}[p.owner_sex], 3))
    mgmt = {"over_2y": "경영체에 등록했어요", "under_2y": "경영체에 등록했어요", "none": "경영체에 등록 안 했어요"}.get(p.mgmt_status)
    if mgmt:
        out.append((mgmt, 4))
    if p.crops and p.crops[0].sales_channel in SALES_TAG:
        label = crop_labels.get(p.crops[0].crop_code, p.crops[0].crop_code)
        tag = SALES_TAG[p.crops[0].sales_channel]
        out.append((f"{eun(label)} {tag}" if p.crops[0].sales_channel == "coop" else tag, 5))
    return out


# 어르신이 처음 듣는 낱말 풀이: 카드 글에 그 낱말이 있을 때만 카드 아래에 붙인다(정의만, 새 사실은 없다)
GLOSS = (("자조금", "자조금은 농협에 출하할 때 값에서 매번 얼마씩 떼는 돈이에요"),
         ("농협 출하", "농협 출하는 상인이 아니라 농협에 파는 것이에요"),
         ("면적조절", "면적조절은 밭 넓이를 줄이는 일이에요"),
         ("수입안정보험", "수입안정보험은 값이 떨어져 수입이 줄 때 보상하는 보험이에요"),
         ("경영체", "경영체 등록은 농산물품질관리원에 하는 농업인 등록이에요"))
SALE_NOW = {"field_contract_done": "밭째 넘기셔서", "merchant_planned": "상인에게 파실 예정이라"}


def gloss_for(texts: list[str]) -> list[str]:
    blob = " ".join(texts)
    return [g for word, g in GLOSS if word in blob]


def full_cond(manual_check: str | None) -> str | None:
    """창구에서 확인할 조건 첫 토막. 괄호가 열린 채 끊겼으면 닫는 괄호까지 이어 붙인다(글이 중간에 잘려 보이지 않게)."""
    seg = first_segment(manual_check)
    if not seg or seg.count("(") <= seg.count(")"):
        return seg
    rest = (manual_check or "")[len(seg):]
    end = rest.find(")")
    return seg + rest[:end + 1].replace(" / ", "·") if end >= 0 else seg + ")"


def ro(word: str) -> str:
    """'로'/'으로': 받침이 없거나 ㄹ 받침이면 '로', 아니면 '으로'."""
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣":
        jong = (ord(last) - 0xAC00) % 28
        return word + ("로" if jong in (0, 8) else "으로")
    return word + "으로"


LONG_TEXT = 10      # 금액·시기 글이 이보다 길면 이름 아래 한 줄로 내려 크게 보인다(이름과 나란히 두면 이름이 꺾인다)


MONEY_SENTENCE = re.compile(r"^(.*" + PREREQ_MONEY + r" )(연 .+?)( 받을 수 있어요)$")


def headline_parts(text: str) -> list[tuple[str, bool]]:
    """결론 한 줄을 (글, 노란 강조) 조각으로: '경영체 등록부터 하세요. 조건이 맞으면 ' / '연 약 180만~258만 원'(금액이 낱말 중간에서 꺾이지 않게) / ' 받을 수 있어요' 또는 '○가지'."""
    m = MONEY_SENTENCE.match(text)
    if m:
        return [(m[1], False), (m[2], True), (m[3], False)]
    m = re.search(r"\d+가지", text)
    if m:
        return [(text[:m.start()], False), (m.group(0), True), (text[m.end():], False)]
    return [(text, False)]


RENEW = re.compile(r"경영체\s*(\d{4})년\s*갱신")


def keep_view(title: str, text: str, sub: str | None, as_of: date) -> dict:
    """끊기지 않게 할 일 한 건. 경영체 갱신은 줄에 적힌 해가 이미 지났는지에 따라 지금 할 일로 풀어 쓴다(해는 종이 줄에 있는 값 그대로)."""
    name = title.removeprefix("끊기지 않게 · ").replace("경영체 갱신", "농업경영체 갱신")       # 줄임말('경영체')을 정식 이름으로
    m = RENEW.search(text) if "경영체 갱신" in title else None
    if m:
        yr = int(m.group(1))
        text = (f"갱신할 때가 {yr}년이었는데 이미 지났어요. 가까운 농산물품질관리원에 전화해서 고치세요" if yr < as_of.year
                else f"{'올해(' + str(yr) + '년)' if yr == as_of.year else str(yr) + '년'} 안에 갱신하세요. 전화하면 알려 줘요")
    sub = sub.replace("농관원", "농산물품질관리원") if sub else sub       # 줄임말을 정식 이름으로(전화번호 글은 그대로)
    return {"title": name, "text": f"{text} · {sub}" if sub else text}


SPEAK_ORDER = ("action", "support", "insurance", "empty")


def _sub_sentence(cs: CardSet, front) -> str | None:
    """위 띠 작은 줄: AI 쉬운 말의 첫 문장(할 일 구획 첫 문장, 없으면 지원 구획 첫 문장). 빈 종이는 '지키실 돈' 글이 먼저다. 없으면 비운다."""
    if cs.empty and getattr(front, "money_text", None):
        return front.money_text
    pool = cs.narr.get("action") or cs.narr.get("support") or cs.narr.get("empty")
    return pool[0] if pool else None


WHEN_RE = re.compile(r"내년|올해|\d+월|언제든|지금도|다음|까지|부터")        # 시기를 말하는 토막(달력 그림을 붙인다)
MONEY_LABEL = "받을 수 있는 돈"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
PILL_TODO = "먼저 하실 일"      # 굵은 주황 테두리 줄 딱지: 받을 지원이 있는 결과는 한 가지 말(2026-11-15 점검: 줄에 따라 "먼저 가실 곳"과 갈리면 다른 뜻으로 읽힌다)
PILL_GO = "먼저 가실 곳"         # 빈 종이(새로 받을 돈이 없고 끊기지 않게 할 일만 있는 경우)만: 골든 시험이 이 종이에 "먼저 하실 일"이 찍히지 않아야 한다고 본다


def office_display(name: str | None) -> str | None:
    """가실 곳 이름을 어르신이 읽는 말로: 건보공단 → 건강보험공단, 농관원 → 농산물품질관리원(농관원)(첫 등장이라 괄호로 함께 적는다)."""
    return office_say(name)       # 곳 이름의 다른 표기를 한 가지로(app/core/office_say.py: 지원 전체 보기와 같은 규칙)


_PRICE_STATE = {"열림": "이번 달은 열렸어요", "열림(추정)": "이번 달은 열린 것으로 보여요", "곧 열릴 수 있음": "이번 달은 곧 열릴 수 있어요",
                "아직": "이번 달은 아직 열리지 않았어요", "자료 오래됨": "이번 달 가격 자료가 오래돼서 알 수 없어요"}
_PRICE_RE = re.compile(r"^이번 반월 (열림\(추정\)|열림|곧 열릴 수 있음|아직|자료 오래됨)(\(잠정\))?$")


def price_say(piece: str) -> str:
    """가격안정관리제 줄의 '이번 반월 아직(잠정)'을 어르신이 읽는 말로(반월·잠정은 직원용 글에만). 판정 값은 그대로이고 말만 바뀐다."""
    m = _PRICE_RE.match(piece)
    if not m:
        return piece
    return _PRICE_STATE[m[1]] + (" · 거래 날이 적어 바뀔 수 있어요" if m[2] else "")


def split_small(small: str | None, check: bool) -> tuple[list[str], list[str], bool]:
    """카드 줄의 아래 작은 줄('예년 3월 · 확인할 조건 있음')을 (시기 토막, 그 밖의 안내 토막, 조건 확인 여부)로 가른다. 글은 그대로, 가르기만 한다."""
    whens, notes, chk = [], [], check
    for piece in (small or "").split(" · "):
        piece = price_say(piece.strip())
        if not piece:
            continue
        if piece == CHECK_TAG:
            chk = True
        elif WHEN_RE.search(piece):
            whens.append(piece)
        else:
            notes.append(piece)
    return whens, notes, chk


TEL_RE = re.compile(r"\d{2,4}-\d{3,4}(?:-\d{4})?")


def tel_nb(text) -> Markup:
    """전화번호('1644-8778')가 줄 끝에서 '1644-'/'8778'로 끊기지 않게 한 덩어리로 묶는다(글은 그대로, 템플릿 필터 `tel`)."""
    return Markup(TEL_RE.sub(lambda m: f'<span class="nb">{m[0]}</span>', str(escape(text if text is not None else ""))))


def money_parts(text: str | None) -> tuple[str, str]:
    """받을 금액 글을 (앞 말, 금액 덩어리)로: '하시고 조건 맞으면 연 약 180만~258만 원' → ('하시고 조건 맞으면', '연 약 180만~258만 원'), '130만 원' → ('', '130만 원').
    금액(숫자와 '원')이 없는 글은 ('', '')이다. 주황은 금액 덩어리만 칠한다(앞 말은 검정)."""
    if not text or "원" not in text or not re.search(r"\d", text):
        return "", ""
    m = re.match(r"^(.*?)\s*(연 .*)$", text)
    return (m[1], m[2]) if m else ("", text)


DAYS_LEFT = re.compile(r"(\d+)일 남음")


def urgent_label(text: str | None) -> str:
    """마감이 급한 줄의 글('오늘 11월 13일까지' · '11월 20일까지 · 5일 남음')에서 남은 날을 큰 표시 글로: '오늘까지' · '5일 남음'. 글에 없으면 빈 글."""
    m = DAYS_LEFT.search(text or "")
    return f"{m[1]}일 남음" if m else ("오늘까지" if "오늘" in (text or "") else "")


NOTICE_GO = re.compile(r"(?:접수처|신청장소)\s*[:：]\s*")        # '가실 곳' 줄의 앞머리(떼고 곳 이름만 띠에 보인다)
URGENT_DAYS = 7                                                   # 지원 전체 보기(layout.URGENT_DAYS)와 같은 급한 남은 날


def notice_box(ln: Mapping[str, object]) -> dict:
    """"지금 접수 중인 공고" 상자 하나(맞을 수 있는 공고 한 건, match_job 줄)의 띠·날짜 글. 글은 줄에 있는 값 그대로, 가르기만 한다(템플릿 필터 `nnv`).
    place: 띠의 곳 이름(접수처·신청장소 줄이 있을 때만, 없으면 빈 글 = 띠는 "지금 접수 중인 공고") · other: 가실 곳 줄이 아닌 안내(공고를 낸 부서는 가실 곳처럼 읽혀 뺀다)
    left: 빨간 남은 날 딱지 글("10일 남음"·"오늘 마감", 기간 글에 없으면 빈 글) · urgent: 7일 안(딱지를 빨강으로 채운다) · date: 달력 옆 글("11월 23일까지")."""
    where = str(ln.get("where") or "").strip()
    place = NOTICE_GO.sub("", where).strip() if NOTICE_GO.match(where) else ""
    other = "" if place or where.startswith("공고 낸 곳") else where
    period = str(ln.get("period") or "")
    m = DAYS_LEFT.search(period)
    left = f"{m[1]}일 남음" if m else ("오늘 마감" if "오늘 마감" in period else "")
    days = int(m[1]) if m else (0 if left else None)
    head = period.partition(" · ")[0]
    return {"place": place, "other": other, "left": left, "urgent": days is not None and days <= URGENT_DAYS, "date": head if left else period}


def _mk(role: str, title: str, text: str | None, whens=(), notes=(), check=False, **more) -> dict:
    pre, amt = money_parts(text)
    return {"role": role, "title": title, "text": text, "text_when": bool(text) and "원" not in text and bool(WHEN_RE.search(text)),
            "pre": pre, "amt": amt, "whens": list(whens), "notes": list(notes), "check": check, "unlocks_n": 0, "urgent": "", "counted": False,
            "place_notes": [], **more}


def _line_view(cl, cond: str | None) -> dict:
    return {"title": cl.title, "text": cl.text, "small": cl.small, "check": cl.check, "todo": cl.todo, "cond": cond, "role": cl.role,
            "long": cl.todo or len(cl.text) > LONG_TEXT, "counted": cl.counted, "place_notes": list(cl.place_notes)}


def _sides(c: Card, unlocks: dict) -> tuple[list[dict], list[dict], bool]:
    """카드의 보이는 줄을 왼쪽(하실 일)과 오른쪽(받을 수 있는 것)으로 나눈다. 글은 카드 층의 것 그대로. 셋째 값: 급한 줄을 오른쪽으로 옮겼는가.
    먼저 하실 일 줄은 왼쪽. 그 줄의 글이 '하시고 조건 맞으면 연 약 …'처럼 받을 돈을 말하면 그 글은 오른쪽(받을 수 있는 돈)으로 보낸다.
    마감이 급한 줄(URGENT: '마늘 농작물보험 오늘까지')은 받을 것 자체라서 오른쪽에 둔다(왼쪽에는 '가입하기'): 같은 가실 곳의 다른 보험과 나란히 읽힌다."""
    todo, gets, moved = [], [], False
    for cl in c.lines:
        whens, notes, chk = split_small(cl.small, cl.check)
        pn = list(cl.place_notes)          # 합친 상자에서 이 줄이 원래 어느 곳 이름에서 왔는지(작은 글)
        if cl.todo:
            if cl.line.kind == "URGENT":
                gets.append(_mk("insurance" if "보험" in cl.title else "benefit", cl.title, cl.text, whens, notes, chk, urgent=urgent_label(cl.text), counted=cl.counted, place_notes=pn))
                moved = True
            elif cl.line.kind == "PREREQ" and cl.text.startswith(PREREQ_MONEY):
                todo.append(_mk(cl.role, cl.title, None, place_notes=pn))
                gets.append(_mk("benefit", MONEY_LABEL, cl.text, whens, notes, chk, unlocks_n=len(unlocks.get(cl.title, ())), counted=cl.counted))
            else:
                todo.append(_mk(cl.role, cl.title, cl.text, whens, notes, chk, place_notes=pn))
        else:
            gets.append(_mk(cl.role, cl.title, cl.text, whens, notes, chk, counted=cl.counted, place_notes=pn))
    return todo, gets, moved


SCREEN_MAX_CARDS = len(CIRCLED)     # 화면은 가실 곳을 전부 보인다(종이의 MAX_CARDS=3 한도는 종이만): 번호 글자가 있는 만큼
SCREEN_MAX_LINES = 99               # 한 곳의 줄도 전부(종이의 MAX_CARD_LINES=3 한도는 종이만)
FAR_DAYS = 10 ** 6


def _line_window(cl: CardLine, prog_of: Mapping[str, object], as_of: date):
    """줄 하나의 신청 기간(지원 전체 보기가 쓰는 texts.window_of 의 값 그대로). 줄이 가리키는 표 행이 없으면 None(= 알 수 없음)."""
    p = prog_of.get(cl.line.program_id or "")
    return window_of(p, as_of) if p is not None else None


def _days_to_next(w, as_of: date) -> int | None:
    """아직 안 열린 지원이 다시 열릴 때까지(어림, 일). 곧 열려요는 표의 남은 날, 다음 철은 Window.month 의 달 차이 x 30(지원 전체 보기 layout._next_month_gap 과 같은 달 계산). 모르면 None."""
    if w.rank == RANK_SOON and w.days is not None:
        return w.days
    if w.rank == RANK_LATER:
        if w.month is not None:
            return ((w.month - as_of.month) % 12) * 30
    return None


def _sort_lines(c: Card, prog_of: Mapping[str, object], as_of: date) -> Card:
    """상자 안 줄 순서(2026-11-15): 먼저 하실 일 줄 → 지금 신청할 수 있는 줄(마감이 가까운 순) → 다음 신청 달이 가까운 순 → 표 행을 몰라 알 수 없는 줄. 같은 값끼리는 지금 순서 그대로."""
    def key(cl: CardLine) -> tuple[int, int]:
        if cl.todo:
            return 0, 0
        w = _line_window(cl, prog_of, as_of)
        if w is None:
            return 3, 0
        if w.open_now:
            return 1, w.days if w.days is not None else FAR_DAYS
        d = _days_to_next(w, as_of)
        return 2, d if d is not None else FAR_DAYS
    allv = sorted(c.all_lines, key=key)
    return c.model_copy(update={"lines": allv[:len(c.lines)], "hidden": allv[len(c.lines):]})


def order_boxes(cs: CardSet, prog_of: Mapping[str, object], as_of: date) -> tuple[CardSet, list[bool]]:
    """화면의 상자 순서(2026-11-15 4차): 먼저 하실 일이 든 상자(지금 순서 그대로) → 지금 신청할 수 있는 줄이 든 상자(마감이 가까운 순) → 나머지(다음 신청 달이 가까운 순).
    '지금 신청할 수 있는가'는 지원 전체 보기와 같은 texts.window_of(표 행, 기준일).open_now(상시 포함), 다음 신청 달은 Window.month·'○일 뒤 열려요'다.
    표 행이 없어 알 수 없는 상자는 값이 있는 상자 뒤에 지금 순서 그대로 둔다. 새 판정을 만들지 않는다.
    번호(①②③)는 새 순서대로 다시 매기고 대조표용 ref·reduced 의 번호도 같이 옮긴다(AI 에 보내는 입력·FactSheet 은 이 묶음을 쓰지 않으므로 바뀌지 않는다).
    돌려주는 값: (새 CardSet, 상자마다 지금 신청할 수 있는 줄이 든 상자인가)."""
    cards = [_sort_lines(c, prog_of, as_of) for c in cs.cards]
    keys, now = [], []
    for i, c in enumerate(cards):
        ws = [w for cl in c.all_lines if (w := _line_window(cl, prog_of, as_of)) is not None]
        open_ws = [w for w in ws if w.open_now]
        nexts = [d for w in ws if not w.open_now and (d := _days_to_next(w, as_of)) is not None]
        now.append(bool(open_ws))
        if c.first:
            keys.append((0, 0, i))
        elif open_ws:
            keys.append((1, min((w.days for w in open_ws if w.days is not None), default=FAR_DAYS), i))
        else:
            keys.append((2, min(nexts, default=FAR_DAYS), i))
    order = sorted(range(len(cards)), key=lambda i: keys[i])
    remap = {cards[i].no: CIRCLED[pos] for pos, i in enumerate(order)}
    new = tuple(cards[i].model_copy(update={"no": CIRCLED[pos], "emphasis": cards[i].first}) for pos, i in enumerate(order))
    out = cs.model_copy(update={"cards": new, "ref": {k: remap.get(v, v) for k, v in cs.ref.items()},
                                "reduced": tuple(r.model_copy(update={"where": remap.get(r.where, r.where)}) for r in cs.reduced)})
    return out, [now[i] for i in order]


def _card_view(c: Card, cond_of, unlocks: dict | None = None) -> dict:
    todo, gets, moved = _sides(c, unlocks or {})
    gets = sorted(gets, key=lambda g: not g["urgent"])     # 마감이 급한 줄(빨간 딱지)이 상자 맨 위에(같은 급함끼리는 지금 순서 그대로)
    head = office_display(c.place)
    note = None
    if head and "(집에서는" in head:                 # '농지가 있는 읍·면·동 (집에서는 농업e지나 전화 1334)' → 이름과 전화 쪽 글을 가른다
        head, _, rest = head.partition("(집에서는")
        head, note = head.strip(), "(집에서는" + rest
    act = None if (todo and not moved) or not gets else ("가입하기" if all(g["role"] == "insurance" for g in gets) else "신청하기")
    return {"no": c.no, "no_n": str(CIRCLED.index(c.no) + 1) if c.no in CIRCLED else "", "head": head, "phone": c.phone, "tel_note": note,
            "first": c.first, "emphasis": c.emphasis, "pill": PILL_TODO if c.emphasis else None, "hidden_names": [cl.title for cl in c.hidden],
            "icon": c.office or c.place or "", "icon_name": None, "todo": todo, "gets": gets, "act": act,
            "wide": not gets, "lines": [_line_view(cl, None) for cl in c.lines], "hidden_n": len(c.hidden), "where": None, "now": False,
            "conds": [(cl.title, cond_of(cl)) for cl in c.all_lines if cl.check],
            "rows": [{**r, "kind": "do"} for r in todo] + [{**r, "kind": "get"} for r in gets]}


# ---------- 결과 화면 두 구역(2026-11-15 사장 지시): 지금 하실 일(위) · 앞으로 신청할 것(아래). 줄 하나는 두 구역 가운데 한 곳에만 나온다. 새 판정은 없고 있는 값(TODO_KINDS·window_of.open_now)만 쓴다 ----------
UNLOCK_NOTE = re.compile(r"^이것을 하시면 알아볼 수 있는 지원 \d+가지$")
FUND_TITLE, COOP_TITLE = "자조금 가입 확인", "농협에 물어볼 것"          # core/sheet._section_b 가 ASK_COOP 줄에 붙이는 이름
_WHEN_SPLIT = re.compile(r"(.+?(?:월|일부터))(?:에)?\s*(가입.*)")


def split_when(when: str) -> tuple[str, str]:
    """때 글을 (때, 줄 덧말)로: '내년 4월 27일부터 가입할 수 있어요' → ('내년 4월 27일부터', '가입할 수 있어요'), '내년 8~10월에 가입해요' → ('내년 8~10월', '가입해요').
    때 칸은 좁아 긴 글이 네다섯 줄로 꺾이므로 때만 남기고 하는 일은 줄의 덧말 자리로 보낸다. 그 모양이 아니면 (글, '')."""
    m = _WHEN_SPLIT.fullmatch(when or "")
    return (m[1], m[2]) if m else (when, "")


def later_show_days() -> int:
    """표에 싣는 가장 먼 때(일). LATER_SHOW_MONTHS x 30 (gap 은 달 차이 x 30 으로 어림한 일 수라서)."""
    return LATER_SHOW_MONTHS * 30


def is_far(gap: int | None) -> bool:
    """때를 아는 줄의 gap(일)이 기준보다 크면 먼 줄. 때를 모르는 줄(None)은 먼 줄이 아니다(표 맨 끝 묶음에 그대로 둔다)."""
    return gap is not None and gap > later_show_days()


def far_summary(far_rows: Sequence[dict]) -> dict | None:
    """먼 줄 한 줄 안내의 값. n: 먼 줄 수 · from: 첫 먼 줄의 때 글에서 뽑은 '내년 5월'('내년 8~10월'은 '내년 8월', 못 뽑으면 빈 글) ·
    text: 화면 글 '그 뒤에도 N가지가 더 있어요 · 내년 5월부터 신청해요' · paper_text: 종이 글(뒤에 문자 알림 안내가 붙는다). 먼 줄이 없으면 None."""
    if not far_rows:
        return None
    m = FAR_FROM_RE.match(far_rows[0].get("when") or "")
    frm = ((m[1] + " " if m[1] else "") + f"{int(m[2])}월") if m else ""
    base = f"그 뒤에도 {len(far_rows)}가지가 더 있어요"
    text = base + (f" · {frm}부터 신청해요" if frm else "")
    return {"n": len(far_rows), "counted": sum(1 for r in far_rows if r.get("counted")), "from": frm, "text": text,
            "paper_text": text + (" · 문자 알림을 받으시면 그 달에 알려 드려요" if frm else "")}


def month_gap(text: str, as_of: date) -> int | None:
    """때 글('내년 5월쯤')의 첫 달까지 어림 일 수(달 차이 x 30). 같은 달이면 한 해 뒤(LATER_GAP_MIN)로 본다. 달이 없으면 None."""
    mm = MONTH_RE.search(text or "")
    return (((int(mm[1]) - as_of.month) % 12) * 30 or LATER_GAP_MIN) if mm else None


def empty_later_rows(front: EmptyFront) -> list[dict]:
    """빈 종이(새로 받을 돈이 없는 농가)의 '다시 가입할 보험'(내년에 가입)은 앞으로 신청할 것 구역의 줄이다(종이와 같은 나누기). 줄 모양은 split_screen 의 앞으로 줄과 같다.
    때 글('내년 4월 27일부터 가입할 수 있어요')은 때('내년 4월 27일부터')와 덧말('가입할 수 있어요')로 가른다."""
    rows = []
    for l in front.insurance_next:
        when, tail = split_when(l.text)
        known = bool(MONTH_RE.search(when))
        rows.append({"title": l.title, "when": when if known else "", "pre": "", "amt": "", "text": "" if known else l.text, "counted": False,
                     "notes": ([tail] if tail else []) + ([p.strip() for p in l.sub.split(" · ") if p.strip()] if l.sub else []),
                     "place": short_office(l.office) if l.office else None, "phone": None, "tel_note": None, "known": known})
    return rows


LATER_NONE = "때는 창구에 물어보세요"
LATER_GAP_MIN = 360
LATER_SHOW_MONTHS = 4          # 앞으로 신청할 것은 이 달 수 안의 것만 표에 싣는다(사장 결정 2026-11-18). 이 상수 하나만 바꾸면 화면·종이의 기준이 같이 바뀐다
MONTH_RE = re.compile(r"(\d{1,2})월")
FAR_FROM_RE = re.compile(r"^(?:(내년|올해)\s*)?(\d{1,2})\s*(?:~\s*\d{1,2}\s*)?월")        # 때 글 앞머리의 '내년 5월' 꼴('내년 8~10월'은 첫 달 8월)
TODAY_DATE = re.compile(r"^오늘 \d{1,2}월 \d{1,2}일까지$")
TRAIL_PAREN = re.compile(r"\s*\(([^)]+)\)$")
MONEY_LABEL_SCREEN = "이것을 하시면 받을 수 있는 돈"


def reul(word: str) -> str:
    """'을'/'를'. 끝의 괄호는 읽지 않고 그 앞 글자로 본다."""
    last = re.sub(r"\s*\([^)]*\)\s*$", "", word).rstrip()[-1:]
    if "가" <= last <= "힣":
        return word + ("를" if (ord(last) - 0xAC00) % 28 == 0 else "을")
    return word + "을"


def unlock_sentence(names: Sequence[str]) -> str:
    """'이것을 해야 ○○을(를) 받을 수 있어요': 이름은 둘까지, 더 있으면 '… 외 N가지'."""
    head = ", ".join(names[:2])
    if len(names) > 2:
        head += f" 외 {len(names) - 2}가지"
    return f"이것을 해야 {reul(head)} 받을 수 있어요"


def unlock_names(cs: CardSet, fs: FactSheet) -> dict[str, list[str]]:
    """먼저 하실 일·농협에 물어볼 것 줄의 이름 → 그것을 해야 받을 수 있는 지원의 화면 이름(그 지원의 줄 이름, 없으면 조건표 이름). 하나라도 이름을 못 찾으면 그 줄은 빠진다(지금 글을 유지)."""
    title_of: dict[str, str] = {}
    for cl in cs.card_lines:
        if cl.line.program_key:
            title_of.setdefault(cl.line.program_key, cl.title)
    for it in cs.later:
        if it.line.program_key:
            title_of.setdefault(it.line.program_key, it.title)
    key_of = {m.program_id: m.program_key for m in fs.matches}
    out: dict[str, list[str]] = {}
    for a in fs.actions:
        if a.kind not in ("PREREQ", "ASK_COOP") or ":" not in a.action_id:
            continue
        group = a.action_id.split(":", 1)[1]
        title = _PREREQ_TITLE.get(group) if a.kind == "PREREQ" else (FUND_TITLE if group == "fund" else COOP_TITLE)
        names: list[str] = []
        for pid in a.unlocks:
            k = key_of.get(pid)
            nm = (title_of.get(k) or cs.names.get(k)) if k else None
            if not nm:
                names = []
                break
            if nm not in names:
                names.append(nm)
        if title and names:
            out[title] = names
    return out


def _line_days(cl: CardLine, w) -> int | None:
    """지금 구역 줄의 마감까지 남은 날: 급한 줄('오늘까지'·'5일 남음')은 줄 글, 그 밖에 지금 신청할 수 있는 줄은 표의 남은 날(상시는 None)."""
    if cl.line.kind == "URGENT":
        lab = urgent_label(cl.text)
        m = DAYS_LEFT.search(lab)
        if m:
            return int(m[1])
        if lab:
            return 0
    if w is not None and w.open_now and w.days is not None:
        return w.days
    return None


def _split_head(c: Card) -> tuple[str | None, str | None]:
    head = office_display(c.place)
    if head and "(집에서는" in head:
        head, _, rest = head.partition("(집에서는")
        return head.strip(), "(집에서는" + rest
    return head, None


def _line_rows(c: Card, cl: CardLine, unlocks: dict, names: Mapping[str, list[str]], paper: bool = False) -> list[dict]:
    """줄 하나의 화면 줄(하실 일 줄·받을 것 줄). 이름을 아는 '이것을 하시면 알아볼 수 있는 지원 N가지'는 '이것을 해야 ○○을(를) 받을 수 있어요'로 바꾼다.
    paper: 종이가 같은 줄을 쓸 때(2026-11-15) 빨간 '오늘까지' 알약이 없으니 날짜 글을 지우지 않는다(나머지는 화면과 같은 줄)."""
    todo, gets, _ = _sides(c.model_copy(update={"lines": (cl,), "hidden": ()}), unlocks)
    rows = [{**r, "kind": "do"} for r in todo] + [{**r, "kind": "get"} for r in gets]
    head = _split_head(c)[0] or ""
    for r in rows:
        if not paper and r.get("urgent") == "오늘까지" and r["text"] and TODAY_DATE.match(r["text"]):      # 빨간 '오늘까지' 옆에 같은 말(날짜)을 또 적지 않는다
            r["text"], r["text_when"] = "", False
        if r["kind"] == "do" and (m := TRAIL_PAREN.search(r["title"])) and m[1] in head:       # '농업경영체 등록 (농관원)' 위 띠에 이미 농관원이 있으면 괄호는 뺀다
            r["title"] = r["title"][:m.start()].rstrip()
        if r["kind"] == "get" and r["title"] == MONEY_LABEL:                                    # 위 하실 일 줄과 이어 읽히게(종이도 같은 줄)
            r["title"] = MONEY_LABEL_SCREEN
    nm = names.get(cl.title)
    if nm:
        for r in rows:
            had = [n for n in r["notes"] if UNLOCK_NOTE.match(n)]
            if r["unlocks_n"] or had:
                r["unlocks_n"] = 0
                r["notes"] = [n for n in r["notes"] if n not in had]
                r["unlock_text"] = unlock_sentence(nm)
    return rows


def screen_card(c: Card, lines: Sequence[CardLine], pos: int, always: bool, cond_of, unlocks: dict, names: Mapping[str, list[str]],
                hidden: Sequence[CardLine] = (), paper: bool = False) -> dict:
    """지금 구역 상자 하나(번호 pos+1). lines 가 상자에 보이는 줄, hidden 은 종이가 자리가 모자라 접는 뒷줄(화면은 늘 비어 있다).
    row_refs: rows 의 줄마다 그 줄이 나온 원래 줄(Line) — 종이가 숫자 출처를 붙일 때 쓴다(화면은 안 쓴다)."""
    sub = c.model_copy(update={"no": CIRCLED[pos], "lines": tuple(lines), "hidden": tuple(hidden)})
    card = _card_view(sub, cond_of, unlocks)
    rows: list[dict] = []
    refs: list = []
    for cl in lines:
        rr = _line_rows(c, cl, unlocks, names, paper)
        rows += rr
        refs += [cl.line] * len(rr)
    card.update({"first": False, "emphasis": False, "pill": None, "now": False, "no": CIRCLED[pos], "no_n": str(pos + 1), "always": always,      # always: 언제든 신청할 수 있는 줄만 든 상자(지금 접수 중인 공고 상자는 이 앞에 둔다)
                 "rows": rows, "row_refs": refs})
    return card


def group_later(rows: Sequence[dict]) -> list[dict]:
    """앞으로 구역 줄들(달 순서)을 같은 때끼리 묶는다. 때를 모르는 줄은 맨 끝 한 묶음. 같은 달 줄들이 곳이 같으면 곳을 묶음에 한 번만, 모든 줄에 있는 덧말도 한 번만 적는다(줄 값은 그대로, 화면·종이가 가린다)."""
    groups: list[dict] = []
    for r in rows:
        if groups and groups[-1]["known"] == r["known"] and (not r["known"] or groups[-1]["when"] == r["when"]):
            groups[-1]["rows"].append(r)
        else:
            groups.append({"when": r["when"] if r["known"] else LATER_NONE, "known": r["known"], "rows": [r]})
    for g in groups:
        rs = g["rows"]
        g["shared_place"], g["shared_notes"] = None, []
        if len(rs) > 1:
            if rs[0]["place"] and len({(r["place"], r["phone"], r["tel_note"]) for r in rs}) == 1:
                g["shared_place"] = {k: rs[0][k] for k in ("place", "phone", "tel_note")}
            g["shared_notes"] = [n for n in rs[0]["notes"] if all(n in r["notes"] for r in rs[1:])]
    return groups


def split_screen(cs: CardSet, prog_of: Mapping[str, object], as_of: date, cond_of, names: Mapping[str, list[str]]) -> dict:
    """order_boxes 를 거친 묶음(cs)을 화면의 두 구역으로 가른다. now_cards: 지금 하실 일 상자(번호 1부터) · later_rows·later_groups: 앞으로 신청할 것 · ask_groups: 같이 확인해요 표용 (상자 번호, 줄들).
    지금 구역 = 하실 일 줄(TODO_KINDS) + 지금 신청할 수 있는 줄(window_of.open_now, 상시 포함). 나머지는 앞으로 구역. 줄은 두 곳 가운데 한 곳에만 간다.
    앞으로 구역의 표(later_rows·later_groups·later_src)에는 LATER_SHOW_MONTHS 달 안의 줄과 때 모르는 줄만 싣는다. 더 먼 줄은 later_far(한 줄 안내 값: n·from·text·paper_text, 없으면 None)와
    far_rows(줄 값, later_rows 와 같은 모양)·far_src(줄의 (원래 상자, 줄), far_rows 와 같은 차례)로 따로 낸다. ask_groups 의 마지막 묶음에는 먼 줄도 든다.
    상자 순서: 날짜 마감이 있는 줄이 든 상자(마감이 가까운 순) → 하실 일·물어볼 것이 든 상자 → 언제든 신청할 수 있는 것만 든 상자(같은 값은 지금 순서). 상자 안 줄도 같은 순서."""
    boxes: list[tuple[tuple[int, int, int], Card, list[CardLine]]] = []
    later: list[tuple[tuple[int, int, int], dict, Card, CardLine]] = []
    seq = 0
    for i, c in enumerate(cs.cards):
        items: list[tuple[tuple[int, int], int, CardLine]] = []
        for j, cl in enumerate(c.all_lines):
            w = _line_window(cl, prog_of, as_of)
            if cl.todo or (w is not None and w.open_now):
                d = _line_days(cl, w)
                items.append(((0, d) if d is not None else (1, 0) if cl.todo else (2, 0), j, cl))
                continue
            gap = _days_to_next(w, as_of) if w is not None else None
            if gap == 0 and w is not None and w.rank == RANK_LATER:
                gap = LATER_GAP_MIN
            r = _sides(c.model_copy(update={"lines": (cl,), "hidden": ()}), cs.unlocks)[1][0]
            pieces = ([r["text"]] if r["text_when"] and not r["amt"] else []) + r["whens"]
            flat = [p.strip() for x in pieces for p in x.split(" · ") if p.strip()]
            if gap is None and flat:      # 표에서 철을 몰라도 줄 글에 달이 있으면 그 달 자리에 둔다(순서만, 새 판정 없음)
                gap = month_gap(flat[0], as_of)
            if not flat:
                gap = None          # 때 글이 없으면 때를 모르는 줄(맨 끝 묶음)
            head, note = _split_head(c)
            seq += 1
            later.append(((0 if gap is not None else 1, gap if gap is not None else 0, seq),
                          {"title": cl.title, "when": flat[0] if flat else "", "pre": r["pre"], "amt": r["amt"],
                           "text": r["text"] if r["text"] and not r["amt"] and not r["text_when"] else "",
                           "notes": flat[1:] + list(r["notes"]) + list(r["place_notes"]), "counted": r["counted"], "place": head, "phone": c.phone, "tel_note": note, "known": gap is not None}, c, cl))
        if items:
            items.sort(key=lambda x: (x[0], x[1]))
            first = min(items, key=lambda x: x[0])[0]
            days = min((k[1] for k, _, _ in items if k[0] == 0), default=0)
            boxes.append(((first[0], days if first[0] == 0 else 0, i), c, [cl for _, _, cl in items]))
    boxes.sort(key=lambda b: b[0])
    now_cards, ask_groups, now_subs = [], [], []
    for pos, (bkey, c, lines) in enumerate(boxes):
        now_cards.append(screen_card(c, lines, pos, bkey[0] == 2, cond_of, cs.unlocks, names))
        now_subs.append((c, tuple(lines), bkey[0] == 2))
        ask_groups.append((CIRCLED[pos], tuple(lines)))
    later.sort(key=lambda x: x[0])
    ask_groups.append(("", tuple(cl for _, _, _, cl in later)))         # 같이 확인해요 표는 먼 줄까지 전부(줄여도 직원이 볼 조건은 그대로)
    near = [x for x in later if not (x[0][0] == 0 and is_far(x[0][1]))]      # 때를 아는 줄 가운데 먼 줄만 뺀다. 때 모르는 줄(x[0][0] == 1)은 남는다
    far = [x for x in later if x[0][0] == 0 and is_far(x[0][1])]
    rows = [r for _, r, _, _ in near]
    far_rows = [r for _, r, _, _ in far]
    return {"now_cards": now_cards, "later_rows": rows, "later_groups": group_later(rows), "ask_groups": ask_groups,
            "later_far": far_summary(far_rows), "far_rows": far_rows, "far_src": [(c, cl) for _, _, c, cl in far],
            "now_boxes": now_subs, "later_src": [(c, cl) for _, _, c, cl in near]}      # now_boxes·later_src: 종이가 같은 나누기를 그대로 쓰는 값(상자 원본·지금 줄, 앞으로 줄의 (원래 상자, 줄)은 later_rows 와 같은 차례, 먼 줄은 far_rows·far_src 에 따로)


def _speak_number(text: str) -> str:
    return text.replace("~", "에서 ").replace("  ", " ")


KNOW_MAX = 3            # "알아 두세요" 상자에 보이는 항목 수(나머지는 자세히 보기)


def know_items(bring: str | None, keeps: list[dict], others_n: int) -> list[dict]:
    """줄 아래 흩어져 있던 덧말(가실 때 · 끊기지 않게 · 그 밖에 ○가지)을 "알아 두세요" 상자 항목으로(글은 그대로). 세 줄까지 보이고, 넘치면 앞의 둘 + 자세히 보기로 안내하는 마지막 한 줄.
    넘친 항목(가실 때·끊기지 않게)은 자세히 보기 덮개에 그대로 있다. (조건을 직원과 같이 확인하라는 줄은 없다: 확인 조건은 직원용 창에 있다.)"""
    head: list[dict] = []
    cap = KNOW_MAX
    items: list[dict] = [{"kind": "bring", "text": bring}] if bring else []
    items += [{"kind": "keep", "title": k["title"], "text": k["text"]} for k in keeps]
    more = {"kind": "more", "text": f"그 밖에 {others_n}가지 · 자세히 보기에서 볼 수 있어요"} if others_n else None
    if len(items) + (1 if more else 0) > cap:
        hidden = items[cap - 1:]
        last = ({"kind": "more", "text": f"그 밖에 {others_n}가지, 알아 두실 것 {len(hidden)}가지 · 자세히 보기에서 볼 수 있어요"} if more      # 넘친 가실 때·끊기지 않게 항목도 자세히 보기에 있다고 알린다
                else {"kind": "more", "text": f"알아 두실 것이 {len(hidden)}가지 더 있어요 · 자세히 보기에서 볼 수 있어요"})
        items = items[:cap - 1] + [last]
    elif more:
        items.append(more)
    return head + items


INSURANCE_NAME = {"NAT-CROP-INS": "농작물재해보험", "NAT-INCOME-INS": "수입안정보험"}      # 보험 줄('○○ 농작물보험')이 말하는 두 보험(제도 표의 이름 그대로)


def insurance_supports(cs: CardSet, fs: FactSheet, prog_of: Mapping[str, object], crop_labels: Mapping[str, str]) -> list[tuple[str, str]]:
    """보험 줄은 제도 열쇠가 없다. 줄의 작물에 대한 보험 판정(fs.insurance)이 근거로 든 제도 행에서 (이름, 제도 열쇠)를 찾는다. 계산은 건드리지 않고 이름·열쇠 짝만 잇는다."""
    codes: dict[str, list[str]] = {}
    for code, label in crop_labels.items():
        codes.setdefault(label, []).append(code)
    out: list[tuple[str, str]] = []
    for cl in cs.card_lines:
        if cl.line.program_key or not cl.title.endswith(" 농작물보험"):
            continue
        crop = cl.title.removesuffix(" 농작물보험")
        for r in fs.insurance:
            if r.product_id.startswith("nh_safety") or r.status in ("NOT_COVERED", "NOT_ELIGIBLE") or crop_of(r.product_id) not in (codes.get(crop) or [crop]):
                continue
            sid = r.source.source_id.removeprefix("supports:")
            key = getattr(prog_of.get(sid), "program_key", None) or sid.partition("@")[0]
            if key in INSURANCE_NAME and (f"{crop} {INSURANCE_NAME[key]}", key) not in out:
                out.append((f"{crop} {INSURANCE_NAME[key]}", key))
    return out


def detail_links(cs: CardSet, links: Mapping[str, object] | None, extra: list[tuple[str, str]] = ()) -> list[dict]:
    """자세히 보기의 "공고 원문" 줄: 결과에 나온 지원(카드 줄·보험 줄·올해는 어려운 것) 중 공식 원문 주소(links.csv)가 있는 것만.
    같은 주소를 쓰는 지원은 한 줄로 묶어 이름을 이어 쓴다(같은 곳으로 가는 단추가 여럿이면 헷갈린다). key 는 묶음의 첫 제도 열쇠, keys 는 묶음의 열쇠 모두."""
    out: list[dict] = []
    pairs = [*((cl.title, cl.line.program_key) for cl in cs.card_lines), *extra, *((it.title, it.line.program_key) for it in cs.later)]
    for title, key in pairs:
        if not (links and key and key in links):
            continue
        url = links[key].url
        hit = next((x for x in out if x["url"] == url), None)
        if hit is None:
            out.append({"key": key, "keys": [key], "title": title, "titles": [title], "url": url, "kind": links[key].kind})
        else:
            if key not in hit["keys"]:
                hit["keys"].append(key)
            if title not in hit["titles"]:
                hit["titles"].append(title)
                hit["title"] = " · ".join(hit["titles"])
    return out


def build_view(sheet: Sheet, fs: FactSheet, bundle, as_of: date, narr: dict | None = None, cs: CardSet | None = None, links: Mapping[str, object] | None = None,
               screen: bool = False) -> dict:
    """narr: render._narrative_slots가 거른 {'action'|'support'|'insurance'|'empty': 문장들}(없으면 AI 문장 없이).
    cs: 종이가 카드 수·줄 수를 줄여 미리 묶은 카드 묶음(없으면 기본 묶음). links: data/catalog/links.csv 를 읽은 {제도 열쇠: Link}(없으면 공고 보기·링크 복사하기 줄이 없다).
    screen: 결과 화면용(2026-11-15 4차). 가실 곳·줄 수 한도 없이 전부 묶고, 상자 순서를 order_boxes 로 바꾼다(종이는 screen=False 로 지금처럼)."""
    crop_labels = {c.crop_code: c.label for c in bundle.crops}
    prog_of = {p.id: p for p in bundle.programs}
    now_flags: list[bool] = []
    scr = screen and cs is None          # 화면이 직접 묶는 경우만 두 구역으로 가른다(종이는 미리 묶은 cs 를 넘기므로 지금 그대로)
    if screen and cs is None:
        cs = build_cards(sheet, fs, narr, max_cards=SCREEN_MAX_CARDS, max_lines=SCREEN_MAX_LINES)
        if not cs.empty:
            cs, now_flags = order_boxes(cs, prog_of, as_of)
    cs = cs or build_cards(sheet, fs, narr)
    front = sheet.front
    tg = tags(fs, crop_labels, as_of)

    def cond_of(cl) -> str | None:
        p = prog_of.get(cl.line.program_id or "")
        return full_cond(p.manual_check) if p is not None and cl.check else None

    sp = None
    view: dict = {"empty": cs.empty, "tags": [t for t, _ in tg], "who": " · ".join(t for t, _ in tg), "count": cs.count, "todo_n": cs.todo_n,
                  "conclusion": cs.conclusion, "conclusion_parts": headline_parts(cs.conclusion), "sub": _sub_sentence(cs, front),
                  "cards": [], "others_n": cs.others_count, "prior_note": bool(cs.basis)}
    if isinstance(front, EmptyFront):
        offices = lambda ls: " · ".join(dict.fromkeys(short_office(l.office) for l in ls if l.office)) or None      # noqa: E731
        for head, ls, icon, role in (("끊기지 않게 할 일", front.keep_actions, "cycle", "do"), ("다시 가입할 보험", front.insurance_next, "umbrella", "insurance")):
            if ls:
                items = [_mk(role, l.title, l.text, notes=[l.sub] if l.sub else ()) for l in ls]
                view["cards"].append({"no": "", "no_n": "", "head": head, "phone": None, "tel_note": None, "first": False, "emphasis": not view["cards"],
                                      "pill": PILL_GO if not view["cards"] else None, "hidden_names": [],
                                      "icon": "", "icon_name": icon, "todo": items if role == "do" else [], "gets": items if role != "do" else [],
                                      "act": None, "wide": role == "do", "hidden_n": 0, "where": offices(ls), "conds": [], "now": False,
                                      "lines": [{"title": l.title, "text": l.text, "small": l.sub, "check": False, "todo": False, "cond": None, "role": role,
                                                 "long": len(l.text) > LONG_TEXT} for l in ls],
                                      "rows": [{**r, "kind": "do" if role == "do" else "get"} for r in items]})      # 상자 안 줄(_result_boxes.html 이 c.rows 를 돈다)
        view["place_name"] = next((short_office(l.office) for l in (*front.keep_actions, *front.insurance_next) if l.office), None)
        if scr:         # 빈 종이도 두 구역(종이와 같은 나누기): 끊기지 않게 할 일 상자 = 지금 하실 일, 다시 가입할 보험(내년 가입) = 앞으로 신청할 것(달 목록)
            sp = None
            now = [c for c in view["cards"] if c["icon_name"] == "cycle"]
            for c in now:
                c["pill"], c["emphasis"] = None, False         # 딱지·굵은 테두리는 없다(구역 제목이 그 뜻이다)
            all_rows = empty_later_rows(front)
            far_rows = [r for r in all_rows if r["known"] and is_far(month_gap(r["when"], as_of))]      # 내년 가입 보험도 앞으로 구역과 같은 기준(때를 아는 줄만 멀면 뺀다)
            rows = [r for r in all_rows if not any(r is f for f in far_rows)]
            view.update({"now_cards": now, "later_rows": rows, "later_groups": group_later(rows), "later_far": far_summary(far_rows), "far_rows": far_rows})
    else:
        view["cards"] = [_card_view(c, cond_of, cs.unlocks) for c in cs.cards]
        for card, now in zip(view["cards"], now_flags):
            card["now"] = now
        if scr:
            sp = split_screen(cs, prog_of, as_of, cond_of, unlock_names(cs, fs))
            view.update({"now_cards": sp["now_cards"], "later_rows": sp["later_rows"], "later_groups": sp["later_groups"], "later_far": sp["later_far"], "far_rows": sp["far_rows"]})
        pn = next((c.place for c in cs.cards if c.place), None)
        view["place_name"] = office_display(pn).split("(집에서는")[0].strip() if pn else None       # 안내 글에는 이름만(집에서 하는 길은 줄에 있다)
    view["place_ro"] = ro(view["place_name"]) if view["place_name"] else "창구로"

    # ---- 자세히 보기 덮개 ----
    sale = fs.profile.crops[0].sales_channel if fs.profile.crops else None
    note = SALE_NOW[sale] + " 올해는 어려워요. 내년에 농협에 파시면 맞을 수 있어요" if sale in SALE_NOW and any("농협 출하" in it.need for it in cs.later) else None
    asks = ask_entries(sp["ask_groups"] if sp else [*((c.no, c.all_lines) for c in cs.cards), *((g.no, g.all_lines) for g in cs.others)], prog_of)         # 같이 확인해요 표(지원마다 ask 쉬운 말 · 직원용 창에서 보는 모음)
    if sp:          # 화면의 번호는 지금 구역 상자 번호다: 앞으로 구역 줄에는 번호가 없다
        for e in asks:
            if e["no"] == ASK_OTHER:
                e["no"] = ""
    checks = [{"title": cl.title, "text": cl.text} for cl in cs.card_lines if not cl.counted and not cl.todo and not cl.check]
    staff_conds = [{"title": cl.title, "text": prog_of[cl.line.program_id].manual_check} for cl in cs.card_lines
                   if cl.line.program_id in prog_of and prog_of[cl.line.program_id].manual_check]       # 직원이 볼 내용: 표의 확인 글 원문 그대로
    ai_all = [s for k in SPEAK_ORDER for s in cs.narr.get(k, ())]
    blob = [it.title + " " + it.need for it in cs.later] + [cl.title + " " + cl.text + " " + (cond_of(cl) or "") for cl in cs.card_lines]
    fh = fs.header
    day = lambda d: d.isoformat() if d else "확인일 미상"      # noqa: E731
    view["detail"] = {
        "far": [{"title": r["title"], "when": r["when"], "place": " ".join(x for x in (r["place"], r["phone"]) if x)} for r in view.get("far_rows", ())],      # 표에서 줄인 먼 줄(때 · 지원 이름 · 가실 곳)
        "data_basis": f"데이터 기준일 지원 표 확인 {day(fh.tables_verified)} · 가격 {day(fh.price_as_of)} · 감귤 가격 {day(fh.citrus_as_of)} · 저장본 {day(fh.snapshot_built)} · 계산 지문 {fs.fingerprint}",
        "later": [{"title": it.title, "need": it.need, "sub": it.sub, "place": office_display(it.place)} for it in cs.later], "later_note": note,
        "asks": [{k: e[k] for k in ("no", "title", "asks")} for e in asks], "checks": checks, "staff_conds": staff_conds, "ai": ai_all, "ai_screen": [s for s in ai_all if s != view["sub"]], "gloss": gloss_for(blob),
        "notes": [l.text for l in cs.notes],
        "bring": cs.bring.text if cs.bring else None, "docs": cs.docs.text if cs.docs else None,
        "others": [(office_display(g.place), [cl.title for cl in g.all_lines]) for g in cs.others]}
    view["bring"] = cs.bring.text if cs.bring else None
    view["keeps"] = [keep_view(l.title, l.text, l.sub, as_of) for l in (cs.keeps if not cs.empty else ())]
    view["detail"]["keeps"] = [(k["title"], k["text"]) for k in view["keeps"]]
    view["detail"]["links"] = detail_links(cs, links, insurance_supports(cs, fs, prog_of, crop_labels))
    view["know"] = know_items(view["bring"], view["keeps"], view["others_n"])
    view["speak"] = _speak(view, cs)
    return view


def ieyo(word: str) -> str:
    """'예요'/'이에요'(받침이 있으면 이에요). 끝의 괄호('농관원')는 읽지 않고 그 앞 글자로 본다."""
    last = re.sub(r"\s*\([^)]*\)\s*$", "", word).rstrip()[-1:]
    return word + ("이에요" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "예요")


def _speak_note(note: str) -> str:
    """합친 상자 줄의 곳 안내 작은 글을 말로: '구좌농협' → '구좌농협이에요', '집에서는 농업e지나 전화 1334' → '… 1334로도 신청할 수 있어요'. '…해요'로 끝나는 글은 그대로."""
    if note.endswith("요"):
        return note
    return note + "로도 신청할 수 있어요" if note.startswith("집에서는") else ieyo(note)


def _speak(v: dict, cs: CardSet) -> str:
    """소리로 듣기 글(설계 2절): 결론 한 줄 + AI 설명 문장 + 상자마다 '곳 이름에서는.' 뒤에 '지원 이름, 금액'(합친 상자의 줄은 곳 안내 글까지)."""
    parts = [_speak_number(v["conclusion"]) + "."]
    parts += list(cs.lead)
    two = "now_cards" in v          # 화면: 지금 하실 일 → 앞으로 신청할 것 순서(빈 종이도 같다)
    if two:
        parts.append("지금 하실 일이에요." if v["now_cards"] else "지금 바로 하실 일은 없어요.")
    for c in (v["now_cards"] if two else v["cards"]):
        bits = [f"{c['head']}에서는." if c["head"] and c["no_n"] else (c["head"] + "." if c["head"] else "")]
        for ln in c["lines"]:
            bits.append(f"{ln['title']}, {_speak_number(ln['text'])}." + "".join(f" {_speak_note(n)}." for n in ln.get("place_notes", ())))
        if c["hidden_n"]:
            bits.append(f"그 밖에 {c['hidden_n']}가지가 더 있어요.")
        parts.append(" ".join(b for b in bits if b))
    if two and (v["later_groups"] or v.get("later_far")):
        parts.append("앞으로 신청할 것이에요.")
        for g in v["later_groups"]:
            items = " ".join(f"{r['title']}{', ' + _speak_number(r['amt']) if r['amt'] else ''}." for r in g["rows"])
            parts.append(f"{g['when']}. {items}" if g["known"] else items)
        if v.get("later_far"):
            parts.append(v["later_far"]["text"].replace(" · ", ", ") + ".")      # 화면 글과 같은 말(가운뎃점만 쉼표로 읽는다)
    if v["others_n"]:
        parts.append(f"그 밖에 {v['others_n']}가지는 종이에 있어요.")
    return " ".join(parts)
