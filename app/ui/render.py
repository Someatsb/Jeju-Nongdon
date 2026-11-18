"""종이 그리기(Task 17, U17): Sheet(배치 모델) + FactSheet → A4 앞면 HTML. 배치 결정은 Task 15 모델이 하고 여기는 조립만 한다. 종이는 앞면 한 면뿐이다(2026-11-18 사장 결정).

- 템플릿: sheet_front.html / sheet_front_empty.html(+ _paper_boxes.html 가실 곳 칸). 쪽 틀은 sheet_doc.html. CSS는 static/print.css를 그대로
  <style>에 넣어 한 파일로 만든다(미리보기와 인쇄가 같은 HTML, Edge 헤드리스 PDF도 같은 파일).
- 숫자는 모두 span.num(data-source·data-asof)에 담긴다. 줄 글자 속 숫자는 `nums()`가 줄의 출처로 감싼다.
- narrative(설명 문장)는 None이면 비운다. 결과가 있는 종이에는 AI 한 문장이 없다(화면 맨 위 띠에만 있다). 빈 종이만 설명 문장을 첫 하나 싣는다(숫자가 든 문장은 버린다).
- check_overflow: 앞면의 `.line` 요소를 글자 크기(pt/16)로 환산해 줄 수를 세고, 구획별 상한도 본다. 가실 곳 묶음(.rrw)은 paper_group_lines·paper_row_lines 가 어림한 높이(data-n)를 쓴다.
- 앞면은 결과 화면의 표 그대로다(2026-11-17 사장 지시: 인쇄 = 화면): 머리 → 표 위 한 줄 → 표(대분류 지금 하실 일·앞으로 신청할 것 | 소분류 가실 곳·때 | 지원 이름·금액·설명) → 표 아래 줄들(가실 때 · 끊기지 않게) → 바닥글.
  나누기는 result_view.split_screen 을 그대로 쓰고(앞으로 신청할 것은 넉 달 안의 줄과 때 모르는 줄, 먼 줄은 맨 끝 한 줄), 값은 result_view.screen_card 의 상자(paper_cards 가 숫자를 출처 칸으로 감싼 것)다. 줄이거나 접지 않는다. 번호 동그라미는 없다.
  지금 접수 중인 공고(AI가 읽은 공고)는 화면과 같은 자리(언제든 신청하는 줄만 든 첫 상자 앞, 없으면 끝)에 둔다.
  한 쪽에 안 들어가면 plan_pages 가 글자 단계를 올리고(TIER_K: 지원 이름·설명 18·15pt → 16·14 → 15·13 → 14·12. 들어가는 가장 큰 단계), 그래도 안 들면 표가 다음 쪽으로 이어진다(paper_pages: 곳·달 묶음은 쪽 가운데서 자르지 않는다. 이어진 쪽 맨 위에 머리 한 줄).
  어느 단계로 그릴지는 줄 높이 어림(paper_group_lines · paper_later · notice_lines, 글자 폭은 단계 몫 _PT_K)을 check_overflow 로 쪽마다 한 쪽 한도(CARD_LINE_LIMIT)에 견주어 정한다.
"""
import logging
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from app.core.models import CalendarSlot, FactSheet
from app.core.sheet import ITEM_SECTIONS, EmptyFront, Line, Sheet
from app.core.sheet_cards import CardLine, CardSet, build_cards
from app.core.sheet_rules import FIELD_LABEL, notice_badge
from app.core.snapshot_models import AGED_MAX_DAYS, freshness
from app.core.when_text import ASK_WHEN, month_when, year_word_of
from app.ui.result_view import (notice_box, split_when, SCREEN_MAX_CARDS, SCREEN_MAX_LINES, build_view, MONEY_SENTENCE, group_later, headline_parts, keep_view, money_parts,
                                office_display, order_boxes, screen_card, split_screen, unlock_names)

log = logging.getLogger(__name__)
UI_DIR = Path(__file__).resolve().parent
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
FRONT_LINE_LIMIT = 41.0                                  # 16pt 한 줄(줄 간격 1.3)을 1로 센 앞면 줄 수 상한. 2026-11-13 재보정(재생 서버 미리보기 실측, Chromium 96dpi, 16pt 한 줄 = 27.6px): 달력 이름표를 없애 세 칸을 넓히고 달력·상자 꺾임(REAL_WIDTH)·설명 문장 줄 간격(NARR_EXTRA)을 추정에 넣은 뒤, 다섯 사례의 '추정 + 남는 px/27.6'(= 담을 수 있는 줄 수)이 41.5(P4, 설명 문장 3줄)~43.9. 가장 작은 41.5에서 0.5줄(14px) 여유를 둔 41.0(이전 41.5는 P4가 실제로 70px 넘쳐 고정 줄 둘이 잘렸다). 이력: 2026-11-08 39.9줄 실측, 2026-11-11 '가실 때' 고정 줄 추가로 41.5
LAST_PLAN: dict[str, Any] = {}                           # 마지막으로 그린 종이의 앞면 모양(측정 도구가 읽는다): shape · caps · know_extra · know_total. 시험·측정용 plan 인자로 모양을 정해 그릴 수도 있다
ITEM_CAP = 7
CARD_CAP = 5                                             # 앞면 상자 수 상한(들어가는 만큼 싣는다: 상자 하나는 가장 작아야 125px 쯤이라 다섯이면 한 장이 찬다)
CARD_MM = 156.0                                          # 카드 안 글자 폭(mm): 글자 폭 183 − 카드 테두리·여백 − 체크 칸·번호
LEAD_LINE = 14 / 16 + 0.05                               # 설명 문장의 꺾인 줄 하나가 차지할 줄 수(실측 한 줄 문장 = 26px = 0.94줄). 문장을 실을지는 이 값에 실제 줄 수를 곱해 본다
LEAD_FIT_SLACK = 0.0                                     # 문장을 얹을 때 어림이 상자를 실측보다 크게 잡은 몫을 돌려받는 값. 2026-11-17 표 구조에서는 묶음 어림이 실측과 ±3px 로 맞아 돌려받을 몫이 없다(옛 0.25)
FX_MM = 176.0                                            # 카드 밖 덧말 줄(가실 때·그 밖에 …)의 글자 폭
KNOW_MM = 158.0                                          # "알아 두세요" 상자 안 항목 글자 폭(상자 테두리·여백·점 몫을 뺀 값에 굵은 글자·낱말 줄바꿈 보정 0.85를 곱함. 종이에서는 제목이 위 한 줄, 항목은 상자 폭 전체를 쓴다)
KNOW_MAX = 3                                             # 상자에 실리는 항목 수(화면과 같다: result_view.KNOW_MAX)
SECTION_CAP = {"A": 2, "B": 7, "C": 7, "D": 7, "E": 7, "E2": 7, "F": 5, "G": 3, "KEEP": 7, "INS": 7}
SECTION_NAME = {"A": "급한 것", "B": "먼저 하실 일", "C": "농협 창구에서 신청하는 돈", "D": "직접 신청하셔야 받는 돈",
                "E": "보험 — 가입 시기 안내", "E2": "작년처럼 다시 신청", "F": "가실 곳", "G": "책임 표기",
                "KEEP": "끊기지 않게 할 일", "INS": "다시 가입할 보험"}
DETAIL_CHARS_PER_ROW = 40
NARR_PER_SLOT = 1                                        # 칸마다 첫 문장만: 템플릿 문장 구획당 둘이면 P4 앞면이 35줄을 넘는다(Task 21 e2e)
NARR_SLOTS = ("action", "support", "insurance", "empty")
_DIGIT = re.compile(r"[\d①-⑳]")
_NUMBER = re.compile(r"\d+(?:[,.]\d+)*|[①-⑳]")
_env = Environment(loader=FileSystemLoader(UI_DIR / "templates"), autoescape=select_autoescape(["html"]),
                   trim_blocks=True, lstrip_blocks=True)
_RESULT_LABEL = {"PASS": "충족", "UNKNOWN": "확인 필요", "FAIL": "안 됨"}   # 글자 이름표(색·기호만으로 뜻을 나누지 않음)
_SLOT_SUB = {"integrated": "통합신청 다시 확인", "allowance_direct": "수당·직불 신청", "insurance": "작물 보험"}


FOOT_SAY = {      # 종이 맨 아래 고정 문장 세 줄(core 의 DISCLAIMER). 둘째·셋째는 core 가 이미 해요체라 첫째만 해요체로 바꿔 보인다(뜻·숫자는 그대로)
    "이 종이를 뽑아 준 곳: 제주빅데이터센터 창구 · 궁금한 점도 그곳에": "이 종이를 뽑아 준 곳: 제주빅데이터센터 창구 · 궁금하면 그곳에 물어보세요",
}


def _other_amount(cl) -> str:
    """그 밖에 줄에 붙일 금액 덩어리('130만 원'): 앞면에서 줄여도 받을 금액은 이름 옆에 남긴다(없으면 빈 글)."""
    pre, amt = money_parts(cl.text)
    return amt


def _other_name(cl) -> str:
    amt = _other_amount(cl)
    return f"{cl.title} {amt}" if amt else cl.title


def _other_markup(cl, nums) -> Markup:
    amt = _other_amount(cl)
    return nums(cl.title, cl.line) + (Markup(" <b>") + nums(amt, cl.line) + Markup("</b>") if amt else Markup(""))


def _say(html: str) -> str:
    """종이 글의 줄임말을 정식 이름으로(화면과 같게): 건보공단 → 건강보험공단, 읍면동 → 읍·면·동."""
    return html.replace("건보공단", "건강보험공단").replace("읍면동", "읍·면·동")


MATCH_SRC = "AI가 읽은 공고 맞춰 보기"                          # 지금 접수 중인 공고 줄 숫자의 출처 이름(공고 글에 있는 숫자와 센 개수뿐이다)


def render_sheet(sheet: Sheet, fs: FactSheet, narrative: Any | None, cfg, *,
                 crop_labels: Mapping[str, str] | None = None, replay_line: str | None = None, match: Mapping[str, Any] | None = None,
                 programs: Sequence[Any] = (), plan: Mapping[str, Any] | None = None) -> str:
    """종이 HTML. 한 면뿐이다(2026-11-18 사장 결정. 직원이 볼 내용은 결과 화면의 '직원용 · 자세한 내용 보기' 창에 있다).
    결과가 있는 종이는 앞면 표가 한 쪽에 들도록 글자 단계를 정하고, 그래도 안 들면 표가 다음 쪽으로 이어진다. AI 한 문장은 종이에 싣지 않는다(화면 맨 위 띠에만 있다).

    crop_labels: 작물 코드 → 한글 이름(bundle.crops의 label). 없으면 코드를 그대로 찍는다.
    replay_line: 재생 모드(Task 32)의 숫자 없는 표시 줄. 있으면 종이 맨 위에 작게 찍는다(없으면 종이는 그대로).
    programs: 지원 표의 행(bundle.programs). 가실 곳 상자 순서(화면과 같은 규칙, result_view.order_boxes)에서 '지금 신청할 수 있는가'를 가르는 데 쓴다(없으면 먹을 값이 없어 먼저 하실 일 상자 뒤는 지금 순서).
    plan: 시험·측정용. {"tier": 글자 단계}면 그 단계로 쪽 넘김 없이 그린다(넘치면 넘친 채로).
    match: 지금 접수 중인 공고 맞춰 보기 결과 {lines: [{name, why, period, where, ask}], more_names: [이름]}(MatchJob.view 의 어르신 칸). 없거나 비면 종이에 그 줄이 없다.
      있으면 표의 「지금 하실 일」 구역에 공고 줄로 실린다(화면과 같은 자리: 언제든 신청할 수 있는 줄만 든 첫 상자 앞, 없으면 끝).
    """
    front = sheet.front
    LAST_PLAN.clear()
    narr = _narrative_slots(narrative)
    stamper = _stamper_for(fs)
    nums, stamp = stamper
    labels = crop_labels or {}
    match_ctx = {"lines": [dict(ln) for ln in match.get("lines", ())][:3]} if match and match.get("lines") else None

    def tail_blocks(cs: CardSet) -> dict[str, Any]:
        """카드 밖 덧말: 그 밖에(빈 종이의 앞면 카드에 못 든 곳. 결과가 있는 종이는 「앞으로 신청할 것」 구역이 대신한다)."""
        out: dict[str, Any] = {"others_text": None, "others_n": 0}
        if empty and cs.others:
            parts, n = [], 0
            for i, g in enumerate(cs.others):
                ref = g.all_lines[0].line
                names = " · ".join(_other_name(cl) for cl in g.all_lines)
                where = office_display(g.place)
                where_all = " · ".join(x for x in (where, g.phone) if x)                # 그 밖에 줄에도 전화를 남긴다(지금 신청하는 곳은 전화로 되는 곳이 많다)
                parts.append(Markup(" · ").join(_other_markup(cl, nums) for cl in g.all_lines) + (Markup(" (") + nums(where_all, ref) + Markup(")") if where_all else Markup("")))
                n += wrap_lines(("그 밖에: " if i == 0 else "") + names + (f" ({where_all})" if where_all else ""), 14, KNOW_MM)
            out |= {"others_text": Markup("<br>").join(parts), "others_n": n}
        return out

    def paper_blocks(cs: CardSet, nums) -> dict[str, Any]:
        """결과 화면과 같은 값(result_view.build_view)에서 종이 앞면이 쓰는 조각: 가실 곳 상자·끊기지 않게 줄."""
        crops = SimpleNamespace(crops=[SimpleNamespace(crop_code=k, label=v) for k, v in labels.items()], programs=())
        view = build_view(sheet, fs, crops, cfg.as_of, None, cs)
        if not empty:
            view["cards"] = zone["views"]          # 화면의 「지금 하실 일」 상자(같은 줄·같은 번호·같은 차례)
        else:                                      # 빈 종이도 「먼저 가실 곳」 딱지와 굵은 주황(흑백은 회색) 테두리를 쓰지 않는다: 구역 제목이 그 뜻이다
            for c in view["cards"]:
                c["pill"], c["emphasis"] = None, False
        cards = paper_cards(cs, front, view["cards"], nums)
        keeps = []
        for l in (cs.keeps if not cs.empty else ()):
            k = keep_view(l.title, l.text, l.sub, cfg.as_of)
            keeps.append({"title": nums(k["title"], l), "text": nums(k["text"], l), "plain": f"{k['title']}: {k['text']}", "n": wrap_lines(f"끊기지 않게 {k['title']}: {k['text']}", 14, KNOW_MM) or 1})
        return {"vcards": cards, "row_ns": [round((paper_row_lines if empty else paper_group_lines)(c), 2) for c in view["cards"]], "view": view, "keeps_v": keeps,
                "band_parts": [(nums(txt, cs.conclusion_line, source="sheet"), hi, txt.startswith("연 ")) for txt, hi in headline_parts(cs.conclusion)]}

    def notice_lines(nums) -> list[dict[str, Any]]:
        """화면의 '지금 접수 중인 공고' 상자와 같은 공고(match_ctx.lines, 화면 순서)를 한 줄씩: 공고 이름 · 마감 날짜(화면 상자 띠의 '11월 23일까지'). n = 줄 높이 어림(16pt 한 줄 = 1)."""
        out = []
        for ln in (match_ctx["lines"] if match_ctx else ()):
            nb = notice_box(ln)
            date_, place = nb["date"], nb["place"]
            plain = f"{ln['name']} {date_}".strip()
            right = word_flow(plain, 16, TB_ROW_MM - FIT_SAFETY)[0] * H_GT + 1.6 + (0.6 if date_ else 0.0)
            why, other = _clip(str(ln.get("why") or ""), NOTICE_WHY_MAX), _clip(nb["other"], NOTICE_WHY_MAX)
            ask = [_clip(str(a), NOTICE_ASK_MAX) for a in list(ln.get("ask") or ())[:2]]
            bits = [(why, False), (other, False), *((a, True) for a in ask), (NOTICE_ASK, True)]          # 화면 공고 줄과 같은 글: 왜 맞는지 · 가실 곳 아닌 안내 · 물어볼 것(둘까지) · 조건은 창구에서 확인하세요
            right += sum(word_flow(t, 14, TB_ROW_MM - FIT_SAFETY, bold)[0] * H_NOTE for t, bold in bits if t) + 0.8
            wide = pc_wide(place or NOTICE_LABEL)
            inner = TB_C2_MM - 2 * TB_PAD_MM - FIT_SAFETY
            left = ((PC_ROW_MM + word_flow(place or NOTICE_LABEL, 16, inner)[0] * H_GT) if wide else max(PC_MARK_MM, word_flow(place or NOTICE_LABEL, 16, inner - PC_MARK_W_MM)[0] * H_GT)) + H_NOTE + 1.6        # [그림 · 체크 칸 | 접수처(없으면 '지금 접수 중인 공고')] + 꼬리표 한 줄
            out.append({"name": nums(str(ln["name"]), source=MATCH_SRC), "date": nums(date_, source=MATCH_SRC) if date_ else "",
                        "why": nums(why, source=MATCH_SRC) if why else "", "other": nums(other, source=MATCH_SRC) if other else "", "ask": [nums(a, source=MATCH_SRC) for a in ask], "check": NOTICE_ASK,
                        "place": nums(place, source=MATCH_SRC) if place else "", "icon": place or "", "wide": wide, "n": round((max(left, right) + PG_LINE_MM) / LINE_MM, 2)})
        return out

    def paper_know(cs: CardSet, pb: dict[str, Any], tails: dict[str, Any]) -> list[dict[str, Any]]:
        """표 아래 줄들(결과 화면 알아 두세요의 '가실 때'·'끊기지 않게' 줄과 같은 글, 상자·제목은 없다): 가실 때 → 끊기지 않게 줄 전부 → (빈 종이만) 그 밖에.
        '금액은 올해 기준이에요' 줄과 조건·공고 개수 안내 줄은 종이에 싣지 않는다. 각 항목: lab(굵은 이름표) · html(숫자 칸으로 감싼 글) · n(14pt 줄 수 어림)."""
        bring = None
        if cs.bring:
            lab, txt = label_split(cs.bring.text)
            bring = {"lab": lab + ":" if lab else "", "html": nums(txt, source="sheet"), "n": wrap_lines(cs.bring.text, 14, KNOW_MM) or 1}
        keeps = [{"lab": "끊기지 않게", "html": Markup("{}: {}").format(k["title"], k["text"]), "n": wrap_lines("끊기지 않게: " + k["plain"], 14, KNOW_MM) or 1} for k in pb["keeps_v"]]
        more = [{"lab": "그 밖에:", "html": tails["others_text"], "n": tails["others_n"]}] if tails["others_text"] else []
        return [x for x in (bring, *keeps, *more) if x]

    layout: dict[str, Any] = {"tier": 0, "cuts": ()}       # 결과가 있는 종이의 앞면 모양: 글자 단계(0·1·2·3)와 표를 이어 가는 자리(units 의 몇 번째 앞에서 쪽을 넘기는가)

    def with_layout(ctx: dict[str, Any], tier: int | None = None, cuts: Sequence[int] | None = None,
                    only: tuple[int, int, bool, bool] | None = None) -> dict[str, Any]:
        """앞면 표의 줄(units)을 글자 단계 tier 의 높이로 쪽마다 나눈 pages 를 ctx 에 더한다. only = (시작, 끝, 첫 쪽인가, 끝 쪽인가): 쪽 하나만(배치 시험용). 빈 종이는 그대로."""
        if empty:
            return ctx
        tier = layout["tier"] if tier is None else tier
        cuts = layout["cuts"] if cuts is None else cuts
        return ctx | {"tier": tier, **paper_pages(ctx, cuts, only)}

    def make_ctx(cs: CardSet, tier: int | None = None) -> dict[str, Any]:
        """tier: 표 줄 높이를 어림할 글자 단계(없으면 지금 정해 둔 단계)."""
        tier = layout["tier"] if tier is None else tier
        _PT_K[0] = TIER_K[tier] if not empty else 1.0
        try:
            return make_ctx_(cs, tier)
        finally:
            _PT_K[0] = 1.0

    def make_ctx_(cs: CardSet, tier: int) -> dict[str, Any]:
        if isinstance(front, EmptyFront):
            offices = tuple(dict.fromkeys(l.office for l in (*front.keep_actions, *front.insurance_next) if l.office))[:3]
        else:
            offices = tuple(dict.fromkeys(office_display(c.place or c.office) for c in cs.cards if c.place or c.office))[:3]       # 앞면 상자 띠와 같은 이름(농관원·건강보험공단·읍·면·동 표기)
        first = bool(cs.cards and cs.cards[0].first)
        title = ("먼저 하실 일" if all(c.first for c in cs.cards) else "먼저 하실 일과 받을 수 있는 돈") if first else "받을 수 있는 돈"
        pblocks, tails = paper_blocks(cs, nums), tail_blocks(cs)
        now_date = nums(f"{cfg.as_of.month}월 {cfg.as_of.day}일 기준", source="config", asof=cfg.as_of)
        zctx = ({"two": False, "later_groups": [], "later_far": None, "zt_n": round(ZT_MM / LINE_MM, 2), "now_date": now_date} if empty else
                {"two": True, "now_date": now_date, "no_now": NO_NOW, "zt_n": round(ZT_MM / LINE_MM, 2), "note_n": round(NOTE_MM / LINE_MM, 2),
                 "zempty_n": round((ZEMPTY_MM + 2.0) / LINE_MM, 2), "notices": notice_lines(nums),
                 **paper_later(zone["rows"], zone["srcs"], nums, zone["far"])})
        know = paper_know(cs, pblocks, tails)
        return with_layout({
            "tier_k": TIER_K[tier],
            "sheet": sheet, "front": front, "fs": fs, "cfg": cfg, "cs": cs, "cards": cs.cards,
            "cards_title": title, "offices": offices,
            "offices_text": Markup(" · ").join(nums(o, source="sheet") for o in offices),
            "facts": {f.fact_id: f for f in fs.facts},
            "narr": narr,
            "nums": nums, "stamp": stamp,
            "provisional": _provisional_badge(fs),
            "tel": _nowrap_tel,
            "slot_text": lambda slot: _slot_text(slot, fs.as_of),
            "circled": lambda line: "",
            "circled_by_key": lambda key: cs.ref.get(key, "-"),
            "res_label": _RESULT_LABEL,
            "field_label": lambda f: FIELD_LABEL.get(f, f),
            "replay_line": replay_line, "asof_demo": f"기준일 {cfg.as_of.isoformat()}" if cfg.demo_asof else None,
            "asof_plain": f"{cfg.as_of.year}년 {cfg.as_of.month}월 {cfg.as_of.day}일",
            "rows": _rows,
            "prior_badge": lambda status: notice_badge(status, None, fs.as_of),
            "title_place": _title(fs, labels), "section_name": SECTION_NAME,
            "stale_notes": _stale_notes(fs, labels), "foot_say": lambda t: FOOT_SAY.get(t, t), "office_say": office_display,
            "cwrap": lambda text, pt, mm=CARD_MM: wrap_lines(text, pt, mm) or 1,
            "text_pt": card_text_pt, "am_pt": card_am_pt, "row_n": card_row_n,
            "erow_n": lambda line: card_row_n(line, FX_MM - 6), "eam_pt": lambda line: card_am_pt(line, FX_MM - 6),
            "conclusion_parts": conclusion_parts(cs.conclusion),
            "conclusion_n": sum(wrap_lines(part, 22, 172) or 1 for part in conclusion_parts(cs.conclusion)),
            "know_mm": KNOW_MM, **pblocks, **tails, **zctx, "know": know, "know_n": round(sum(i["n"] for i in know), 2),
        }, tier)

    def plan_pages(ctx: dict[str, Any], bare_cs: CardSet) -> tuple[int, tuple[int, ...]]:
        """글자 단계와 쪽 넘김을 정한다(2026-11-17, 2026-11-18 가장 큰 단계 하나를 앞에 더했다). 한 쪽에 들면 가장 큰 글자 단계(0)부터. 가장 작은 단계로도 안 들면 표를 다음 쪽으로 잇는다:
        한 쪽에 가장 많이 담고(줄 하나 = 곳 하나·달 하나는 쪽 가운데서 자르지 않는다) 남은 줄과 표 아래 줄들을 다음 쪽에."""
        n = len(ctx["units"])

        def fits(tier: int, a: int, b: int, first: bool, last: bool) -> bool:
            html = front_tpl.render(with_layout(by_tier[tier], tier, (), (a, b, first, last)))
            return not check_overflow(html)

        by_tier = {t: make_ctx(bare_cs, t) for t in range(len(TIER_K))}
        for tier in range(len(TIER_K)):
            if fits(tier, 0, n, True, True):
                return tier, ()
        tier, cuts, a = len(TIER_K) - 1, [], 0
        while a < n and not fits(tier, a, n, a == 0, True):      # a == n: 표 아래 줄들만 든 쪽(더 쪼갤 것이 없다)
            b = a + 1
            while b < n and fits(tier, a, b + 1, a == 0, False):
                b += 1
            cuts.append(b)
            a = b
        return tier, tuple(cuts)

    prog_of = {p.id: p for p in programs}
    zone: dict[str, Any] = {"views": [], "rows": [], "srcs": [], "names": {}, "far": None}       # paper_cs 가 채우는 두 구역의 값(상자 화면 값 · 앞으로 줄과 그 원래 줄 · 먼 줄 한 줄 안내)

    def paper_cs(narr_: Any, caps: tuple[Any, ...]) -> CardSet:
        """종이에 그릴 카드 묶음. 빈 종이는 caps = (카드 수, 카드별 줄 수)대로. 결과가 있는 종이는 화면과 같은 나누기(result_view.order_boxes → split_screen)를 그대로 쓰고
        하나도 줄이지 않는다(2026-11-17): cards = 「지금 하실 일」 가실 곳 묶음 전부, later_cards = 「앞으로 신청할 것」 줄(넉 달 안과 때 모르는 줄. 먼 줄은 한 줄 안내) 전부, others 는 없다. 카드의 no 는 번호가 아니라 짧은 곳 이름."""
        if empty:
            return build_cards(sheet, fs, narr_, max_cards=caps[0], max_lines=caps[1])
        base = build_cards(sheet, fs, narr_, max_cards=SCREEN_MAX_CARDS, max_lines=SCREEN_MAX_LINES)
        ordered, _ = order_boxes(base, prog_of, cfg.as_of)
        names = unlock_names(ordered, fs)
        sp = split_screen(ordered, prog_of, cfg.as_of, lambda cl: None, names)
        views, cards = [], []
        for k, (c, lines, always) in enumerate(sp["now_boxes"]):
            views.append(screen_card(c, lines, k, always, lambda cl: None, ordered.unlocks, names, hidden=[], paper=True))
            cards.append(c.model_copy(update={"no": place_tag(office_display(c.place or c.office)), "lines": tuple(lines), "hidden": (), "first": False, "emphasis": False}))
        srcs = sp["later_src"]
        solo = lambda c, cl: c.model_copy(update={"no": "", "lines": (cl,), "hidden": (), "first": False, "emphasis": False})        # noqa: E731
        later_cards = tuple(solo(c, cl) for c, cl in srcs)
        zone.update(views=views, rows=sp["later_rows"], srcs=srcs, names=names, far=sp["later_far"])
        return ordered.model_copy(update={"cards": tuple(cards), "later_cards": later_cards, "others": ()})

    # 결과가 있는 종이는 줄을 하나도 줄이지 않고, 글자 단계와 쪽 넘김(plan_pages)만 정한다. AI 한 문장은 싣지 않는다(문장이 있든 없든 종이는 같다).
    empty = isinstance(front, EmptyFront)
    template = "sheet_front_empty.html" if empty else "sheet_front.html"
    front_tpl = _env.get_template(template)
    caps: tuple[Any, ...] = (CARD_CAP, 5) if empty else ()      # 빈 종이: 카드·줄을 줄이지 않는다(한 쪽에 안 들면 인쇄 전 검사가 막는다). 결과가 있는 종이는 줄이지 않는다
    full = paper_cs(narr, caps)
    if not empty:
        full = full.model_copy(update={"lead": (), "narr": {}})        # 결론 칸이 없으니 설명 문장은 종이에 없다
        tier, cuts = (plan["tier"], ()) if plan and "tier" in plan else plan_pages(make_ctx(full), full)
        layout.update(tier=tier, cuts=cuts)
        LAST_PLAN.update(tier=tier, cuts=cuts)
        cs = full
    else:
        # 빈 종이: 모양은 설명 문장 유무와 무관하게 정한다. 남는 자리에 문장이 실제 꺾이는 줄 수만큼 들어가면 싣는다(첫 문장부터, 아래 여백은 한도에 이미 들어 있다).
        bare_cs = full.model_copy(update={"lead": (), "narr": {}})
        bare = front_tpl.render(make_ctx(bare_cs))
        lead_rows = [LEAD_LINE * (wrap_lines(s, 14, FRONT_TEXT_MM) or 1) for s in full.lead]
        keep = len(full.lead)
        while keep and check_overflow(bare, extra=sum(lead_rows[:keep]) - LEAD_FIT_SLACK):
            keep -= 1
        cs = full.model_copy(update={"lead": full.lead[:keep]}) if keep < len(full.lead) else full
    ctx = make_ctx(cs)
    front_html = _say(front_tpl.render(ctx))
    css = (UI_DIR / "static" / "print.css").read_text(encoding="utf-8")
    html = _env.get_template("sheet_doc.html").render(ctx | {"css": Markup(css), "front_html": Markup(front_html)})
    for message in check_overflow(html):
        log.warning("종이 넘침(상담 %s): %s", fs.data_version, message)
    return html


# --- 템플릿 도우미 --------------------------------------------------------------------------------

_TEL = re.compile(r'(<span class="num"[^>]*>\d+</span>(?:-<span class="num"[^>]*>\d+</span>)+)')


def _nowrap_tel(html: Markup) -> Markup:
    """전화번호('1644-8778')가 좁은 상자에서 '1644-'/'8778'로 끊기지 않게 한 덩어리(span.tel, 줄바꿈 금지)로 묶는다."""
    return Markup(_TEL.sub(r'<span class="tel">\1</span>', str(html)))


def _item_lines(front) -> list[Line]:
    if isinstance(front, EmptyFront):
        return [*front.keep_actions, *front.insurance_next]
    return [l for s in ITEM_SECTIONS for l in front.sections[s]]


def _rows(text: str | None) -> int:
    """작은 글씨 원문(detail)이 차지할 줄 수(한 줄 약 40자)."""
    return math.ceil(len(text) / DETAIL_CHARS_PER_ROW) if text else 0


def _title(fs: FactSheet, labels: Mapping[str, str]) -> str:
    """제목 줄: 작물 이름 · 읍면동. 작물 이름은 표의 label, 없으면 코드."""
    crops = " · ".join(dict.fromkeys(labels.get(c.crop_code, c.crop_code) for c in fs.profile.crops))
    return f"{crops} · {fs.profile.emd_code}" if crops else fs.profile.emd_code


STALE_DAYS = AGED_MAX_DAYS + 1                           # 설계 §6-3: 15일 이상이면 "현재 값 아님"(snapshot_models.freshness와 같은 문턱)


def _stale_notes(fs: FactSheet, labels: Mapping[str, str]) -> tuple[str, ...]:
    """머리의 '현재 값 아님' 띠 문장들(조용한 대체 금지). 농가가 짓는 작물의 자료만 본다: 감귤은 수급센터 저장본의 마지막 날,
    나머지는 시세 판정이 STALE로 나온 작물의 자료 마지막 날."""
    def day(d: date) -> str:
        return f"{d.year}년 {d.month}월 {d.day}일"

    out: list[str] = []
    grows_citrus = any(c.crop_code.startswith("감귤") for c in fs.profile.crops)
    c_day = fs.header.citrus_as_of
    if grows_citrus and c_day is not None and freshness(fs.as_of, c_day) == "stale":
        out.append(f"감귤 가격은 {day(c_day)} 값이에요 · 현재 값 아님")
    for t in fs.triggers:
        if t.status == "STALE" and t.data_as_of is not None and t.crop_code:
            note = f"{labels.get(t.crop_code, t.crop_code)} 시세는 {day(t.data_as_of)} 값이에요 · 현재 값 아님"
            if note not in out:
                out.append(note)
    return tuple(out)


def _narrative_slots(narrative: Any | None) -> dict[str, tuple[str, ...]]:
    """{'action'|'support'|'insurance'|'empty': 문장들}. 숫자가 든 문장은 버린다."""
    if narrative is None:
        return {}
    raw = narrative if isinstance(narrative, Mapping) else getattr(narrative, "sections", {})
    out: dict[str, tuple[str, ...]] = {}
    for key in NARR_SLOTS:
        value = raw.get(key) if isinstance(raw, Mapping) else None
        sentences = [value] if isinstance(value, str) else list(value or ())
        kept = tuple(s for s in sentences if isinstance(s, str) and s.strip() and not _DIGIT.search(s))
        kept = kept[:NARR_PER_SLOT]
        if kept:
            out[key] = kept
    return out


def _stamper_for(fs: FactSheet):
    """(nums, stamp). 숫자는 모두 span.num[data-source][data-asof] 안에 둔다.

    nums(text, ref=None, source=None, asof=None): 숫자 덩어리마다 감싼다.
    stamp(text, ...): 글 전체를 한 칸으로 감싼다(배지·머리 날짜처럼 문장째 읽혀야 하는 것).
    출처: ref가 Line이면 그 줄의 제도 판정, 문자열이면 그 program_key의 판정, 아니면 source·asof 인자, 아니면 코드 계산.
    source를 주고 asof를 안 주면 기준일은 판정일(fs.as_of).
    """
    by_key = {m.program_key: m.source for m in fs.matches}
    by_id = {m.program_id: m.source for m in fs.matches}      # 같은 program_key가 작물별로 여럿이면 줄의 program_id로 제 행을 찾는다
    fallback = (f"calc:{fs.data_version}", fs.as_of.isoformat())

    def resolve(ref, source, asof) -> tuple[str, str]:
        key = ref.program_key if isinstance(ref, Line) else ref
        src = (by_id.get(ref.program_id) if isinstance(ref, Line) and ref.program_id else None) or (by_key.get(key) if key else None)
        if src is not None:
            return src.source_id, src.as_of.isoformat() if src.as_of else "확인일 미상"
        if source is not None:
            return source, (asof or fs.as_of).isoformat()
        return fallback

    def nums(text: str | None, ref=None, source: str | None = None, asof: date | None = None) -> Markup:
        if not text:
            return Markup("")
        src, day = resolve(ref, source, asof)
        out, pos = [], 0
        for m in _NUMBER.finditer(str(text)):
            out.append(escape(text[pos:m.start()]))
            out.append(Markup('<span class="num" data-source="{}" data-asof="{}">{}</span>').format(src, day, m.group()))
            pos = m.end()
        out.append(escape(text[pos:]))
        return Markup("").join(out)

    def stamp(text: str | None, ref=None, source: str | None = None, asof: date | None = None, cls: str = "") -> Markup:
        if not text:
            return Markup("")
        src, day = resolve(ref, source, asof)
        return Markup('<span class="{} num" data-source="{}" data-asof="{}">{}</span>').format(cls, src, day, text)

    return nums, stamp


def _provisional_badge(fs: FactSheet):
    """줄 글자에 '(잠정)'이 있으면 잠정 트리거의 '잠정 · 거래 n일'."""
    provisional = next((t for t in fs.triggers if t.provisional), None)

    def badge(line: Line) -> str | None:
        if provisional is None or "(잠정)" not in f"{line.text} {line.sub or ''}":
            return None
        return f"잠정 · 거래 {provisional.n_days_with_data}일"

    return badge


def _slot_text(slot: CalendarSlot, as_of: date) -> dict[str, str | None]:
    if slot.start and slot.end:
        # 달력 칸은 좁아 "1월 2일~1월 16일"이 두 줄로 꺾인다. 같은 달이면 뒤의 달을 생략한다.
        tail = f"{slot.end.day}일" if slot.end.month == slot.start.month else f"{slot.end.month}월 {slot.end.day}일"
        about = "쯤" if slot.row_status == "prior_year_reference" else ""        # 작년 공고 기준 날짜는 단정하지 않는다
        head = f"{year_word_of(slot.start, as_of)} {slot.start.month}월 {slot.start.day}일~{tail}{about}"
    elif slot.month:
        head = month_when(slot.month, as_of)
    else:
        head = ASK_WHEN
    # 달력 칸은 좁아(약 50mm) 긴 배지가 3줄로 꺾여 앞면 바닥글과 겹쳤다. 항목 줄에 이미 전체 배지가 있으므로 여기는 기준 연도만 적는다.
    badge = f"{as_of.year}년 기준" if slot.row_status == "prior_year_reference" else None
    return {"head": head, "sub": slot.label or _SLOT_SUB[slot.kind], "badge": badge}


# --- 줄바꿈 추정(넘침 검사용) --------------------------------------------------------------------
# 맑은 고딕 기준 한글 한 자 폭 ≈ pt × 0.353mm(전각), 숫자·영문·기호 ≈ 그 0.55배. 넉넉히(올림) 센다.
FRONT_TEXT_MM = 183.0                 # 앞면 글자 폭: 210 − 좌우 12mm − 테두리 여유
_KO = re.compile(r"[가-힣]")


ROW_MM = 165.0                        # 항목 한 줄에서 이름+오른쪽 글자가 쓸 수 있는 폭(상자·번호·점선 최소 폭을 뺀 값)


def text_mm(text: str, pt: int) -> float:
    """글자 폭 어림(mm). 맑은 고딕: 한글 ≈ 0.92em, 숫자·영문·기호·공백 ≈ 0.5em. 1pt = 0.353mm."""
    ko = len(_KO.findall(text))
    return pt * 0.353 * (0.92 * ko + 0.5 * (len(text) - ko))


def fits_row(title: str, text: str, pt: int) -> bool:
    """항목 1줄째(이름 16pt + 오른쪽 글자 pt)가 한 줄에 들어가는가."""
    return text_mm(title or "", 16) + text_mm(text or "", pt) <= ROW_MM


def wrap_lines(text: str | None, pt: int, width_mm: float) -> int:
    """width_mm 안에 pt 크기로 적을 때 꺾이는 줄 수(최소 1). 단어 단위 줄바꿈은 1줄 더 들 수 있다."""
    if not text:
        return 0
    return max(1, math.ceil(text_mm(text, pt) / width_mm))


def r2_rows(line) -> int:
    """항목 2줄째(14pt 작은 글씨 + 배지)가 차지하는 줄 수. 배지가 같은 줄의 오른쪽을 차지하므로 그만큼 좁게 본다."""
    width = FRONT_TEXT_MM - 14.0 - ((text_mm(line.badge, 13) + 6.0) if line.badge else 0.0)
    return max(1, wrap_lines(line.sub, 14, max(width, 40.0)))


def f_rows(lines) -> int:
    """'가실 곳' 상자 줄(.pls)이 차지하는 16pt 줄 수. 상자 중 가장 긴 것: 제목 1줄 + 본문(14pt) 꺾임 + 상세(13pt) 줄."""
    n = max(1, len(lines))
    inner = (186.0 / n - 6.0) * REAL_WIDTH        # 상자 안쪽 폭: 가로 186mm를 n등분, 테두리·안쪽 여백·칸 사이 약 6mm
    best = 0.0
    for l in lines:
        units = 1.0 + 0.875 * wrap_lines(l.text, 14, inner) + (0.8125 * wrap_lines(l.detail, 13, inner) if l.detail else 0)
        best = max(best, units)
    return max(1, math.ceil(best))


REAL_WIDTH = 0.82      # 실측(2026-11-13, Chromium 96dpi): 좁은 칸(달력·가실 곳 상자)은 맑은 고딕 굵은 글자·낱말 단위 줄바꿈 때문에 어림 폭의 약 82%에서 꺾인다


def cal_rows(texts: list[dict]) -> int:
    """달력 세 칸 중 가장 긴 칸의 16pt 줄 수: 머리(16pt) + 설명(14pt) 꺾임 + 배지(13pt, 설명 끝에 안 들어가면 새 줄)."""
    inner = ((186.0 - 4.0) / 3 - 4.0) * REAL_WIDTH
    best = 0.0
    for t in texts:
        sub_mm = text_mm(t.get("sub") or "", 14)
        sub_rows = math.ceil(sub_mm / inner) if sub_mm else 0
        badge_mm = text_mm(t["badge"], 13) if t.get("badge") else 0.0
        room = sub_rows * inner - sub_mm                      # 설명 마지막 줄에 남는 폭
        badge_rows = 0 if not badge_mm or (sub_rows and badge_mm <= room) else math.ceil(badge_mm / inner)
        best = max(best, wrap_lines(t["head"], 16, inner) + 0.875 * (sub_rows + badge_rows))
    return max(1, math.ceil(best))


# --- 카드 줄 도우미(템플릿이 부른다) ---------------------------------------------------------------

def _line_of(item) -> Line:
    return item.line if isinstance(item, CardLine) else item


def card_text_pt(cl) -> int:
    """카드 한가운데 큰 글(금액·시기·한 줄 결론)의 글자 크기: 줄 크기를 따르되 20pt 넘게는 안 키운다."""
    return min(_line_of(cl).pt, 20)


def card_am_pt(cl, width: float = CARD_MM) -> int:
    """여러 줄 카드 속 한 줄의 오른쪽 금액 글자 크기. 이름(16pt)과 한 줄에 안 들어가면 14pt로 줄여 꺾임을 막는다(18pt 넘게는 안 키운다)."""
    line = _line_of(cl)
    pt = min(line.pt, 18)
    return pt if pt <= 14 or text_mm(line.title or "", 16) + text_mm(line.text or "", pt) <= width - 6 else 14


def card_row_n(cl, width: float = CARD_MM) -> int:
    """이름 ····· 금액 줄이 차지하는 16pt 줄 수: 한 줄에 들면 1, 아니면 금액이 다음 줄로 내려가 그만큼 더."""
    line, pt = _line_of(cl), card_am_pt(cl, width)
    if text_mm(line.title or "", 16) + text_mm(line.text or "", pt) <= width - 6:
        return 1
    return 1 + wrap_lines(line.text, pt, width)


# --- 종이 앞면 상자(결과 화면 4차와 같은 모양, templates/_paper_boxes.html) ---------------------------------------
# 상자 하나의 높이를 mm로 어림해 16pt 줄 수로 바꾼다(check_overflow가 .rrw 의 data-n 으로 센다). print.css 의 .pbox 칸 크기와 같은 값: 바꾸면 어림도 같이 맞출 것.
BOX_MM = 178.0                        # 상자 바깥 폭: 글자 폭 186 − 체크 칸 6 − 사이 2
BOX_BORDER_MM = 0.7                   # 테두리 위아래(2.2pt x 2 ≈ 1.6, 굵은 테두리는 pill 에서 더함). 실측 2026-11-16: 상자 어림이 모든 사례에서 실측보다 4~5px 컸다(1.0mm 를 덜어 냄)
BAND_PAD_MM = 3.2                     # 제목 띠 위아래 안쪽 여백
BAND_X_MM = 4.8 + 1.4                 # 제목 띠 좌우 안쪽 여백 + 테두리
NO_MM = 9.0 + 2.4                     # 번호 동그라미 + 사이
PIC_MM = 12.0 + 2.4                   # 가실 곳 그림 + 사이
PIC_H_MM = 12.0                       # 가실 곳 그림 높이
ROW_PAD_MM = 2.0 + 0.4                # 줄 안쪽 위아래 여백 + 줄 사이 선
ROW_X_MM = 6.0 + 1.4                  # 줄 안쪽 좌우 여백 + 테두리
ICON_MM = 6.0 + 2.0                   # 줄 앞 그림 + 사이
TEL_MAX_MM = 64.0                     # 띠 오른쪽 전화 칸의 가장 넓은 폭
# 한 줄 높이(mm): 기관 이름 18pt·1.18 / 하실 일·받을 것 이름 16pt·1.22 / 금액 20pt·1.18 / 전화 17pt·1.15 / 언제 15pt·1.25 / 덧말·딱지·더 있음 14pt·1.25
H_NAME, H_GT, H_AMT, H_TEL, H_WHEN, H_NOTE = 7.49, 6.9, 8.33, 6.9, 6.6, 6.17
LINE_MM = 7.34                        # 16pt 한 줄(줄 간격 1.3) = 1로 세는 높이
AMT_FIT = 1.10                        # 이름 ··· 금액이 한 줄에 드는지 볼 때 글자 폭에 곱하는 값(실측 2026-11-15: 굵은 글자가 어림의 1.04~1.09배, 가장 긴 줄은 금액 앞 점선이 10mm 남았다)
AMT_GAP = 4.0                         # 이름과 금액 사이에 남겨야 하는 가장 작은 틈(mm)
MORE_MM = 168.0                       # "외 ○가지: …" 줄이 한 줄에 드는 어림 글자 폭(실측 2026-11-15: 어림 164mm는 한 줄, 183mm는 두 줄)
UNLOCK_WRAP = 0.97                    # 상자 폭을 다 쓰는 '이것을 해야 ○○을 받을 수 있어요' 줄의 어림 폭 보정(실측 2026-11-16: 어림 157mm는 한 줄, 205mm는 두 줄)
FIT_SAFETY = -0.3                      # 한 줄에 드는지 볼 때 더 남겨 두는 폭(mm). 음수 = 실측 글자 폭이 낱말 사이 자간 때문에 0.3mm 쯤 작게 나오는 것을 받아들인다(2026-11-16 골든 22건: 어림 66.7mm 줄이 66.6mm 칸에 한 줄로 들었다)
LR_COL_GAP = 3.0                       # 앞으로 줄의 이름 칸과 금액 칸 사이
PAPER_WRAP = 0.9                      # 좁은 칸 굵은 글자의 어림 폭 보정(실측으로 맞춤)
BOX_GAP_MM = 1.6                      # 상자 위 간격(print.css .rrw margin-top)
PILL_EXTRA_MM = 1.8                   # 먼저 하실 일 상자의 굵은 테두리가 더 먹는 높이
TAG_H_MM = 7.4                        # 띠 안 딱지 한 줄(14pt 글 + 테두리)
H_PILL = 7.6                          # 줄 안 마감 날짜 알약 한 줄(14pt 글 + 굵은 테두리 + 줄 사이)


_PT_K = [1.0]                          # 표 줄 높이를 어림하는 동안만 글자 단계 몫(TIER_K)이 들어간다(paper_tier). 글자 폭(glyph_mm·_n)이 그만큼 줄어 한 줄에 더 든다


def _n(text: str | None, pt: int, width: float) -> int:
    return wrap_lines(text, pt * _PT_K[0], width * PAPER_WRAP) if text else 0


def _rest_mm(it: dict, w: float) -> float:
    """줄의 아래 덩어리(언제 · 덧말)."""
    h = 0.0
    pill = paper_urgent_date(it)
    when = ([it["text"]] if it.get("text") and it.get("text_when") and not it.get("amt") and not pill else []) + list(it.get("whens") or ())
    if pill:
        h += H_PILL          # 마감 날짜 알약(빨강 테두리 + 빨강 굵은 글: 흑백으로 뽑아도 굵은 글 + 테두리로 읽힌다)
    if when:
        h += _n(" · ".join(when), 15, w - 7.0) * H_WHEN
    h += sum(_n(n, 14, w) * H_NOTE for n in (*(it.get("notes") or ()), *(it.get("place_notes") or ())))
    if it.get("unlock_text"):
        h += wrap_lines(it["unlock_text"], 15, w * UNLOCK_WRAP) * H_WHEN          # '이것을 해야 ○○을 받을 수 있어요'(하실 일 줄·받을 것 줄 모두). 상자 폭 전체를 쓰는 한 줄 글이라 좁은 칸 보정(PAPER_WRAP)을 덜 건다
    return h


def _get_mm(it: dict, w: float, amt_pt: int = 20, h_amt: float = H_AMT) -> float:
    """받을 것 한 줄: 이름 ··· 금액(안 들어가면 금액이 아래로) → 언제 → 덧말 → 하시면 알아볼 수 있는 지원."""
    amt = ((it.get("pre") or "") + " " + it["amt"]).strip() if it.get("amt") else (it["text"] if it.get("text") and not it.get("text_when") else "")
    fit_mm = (text_mm(it["title"] or "", 16) + text_mm(amt, amt_pt if it.get("amt") else 16)) * AMT_FIT + AMT_GAP
    if not amt:
        top = _n(it["title"], 16, w) * H_GT
    elif fit_mm <= w and not it.get("pre"):
        top = h_amt if it.get("amt") else H_GT
    else:
        top = _n(it["title"], 16, w) * H_GT + _n(amt, amt_pt if it.get("amt") else 16, w) * (h_amt if it.get("amt") else H_GT)
    h = top + _rest_mm(it, w)
    if it.get("unlocks_n"):
        h += _n("이것을 하시면 알아볼 수 있는 지원 4가지", 15, w) * H_WHEN
    return h + ROW_PAD_MM


def _do_mm(it: dict, w: float) -> float:
    """하실 일 한 줄: 연필 + 굵은 이름, 아래에 안내 글·언제·덧말."""
    h = _n(it["title"], 16, w - ICON_MM) * H_GT
    if it.get("text"):
        h += _n(it["text"], 14, w - (7.0 if it.get("text_when") else 0.0)) * H_NOTE
    return h + _rest_mm({**it, "text": None}, w) + ROW_PAD_MM


# --- 종이 앞면 두 구역(2026-11-15 사장 지시): 「지금 하실 일」(가실 곳 상자) · 「앞으로 신청할 것」(달 순서 목록). 나누기는 화면과 같다(result_view.split_screen) ---
def place_tag(name: str | None) -> str:
    """가실 곳을 가리키는 짧은 이름표(번호를 대신한다): 이름에 괄호 줄임말이 있으면 그것('농산물품질관리원(농관원) 제주지원' → 농관원), 없으면 첫 낱말."""
    text = (name or "").strip()
    if not text:
        return "창구"
    m = re.search(r"\(([^)]{2,6})\)", text)
    return m[1] if m else text.split()[0]


# 종이 앞면 표(2026-11-17 사장 지시): 대분류(지금 하실 일 · 앞으로 신청할 것) | 소분류(가실 곳 · 때) | 지원(이름 + 오른쪽 끝 금액, 아래 설명). print.css .ptb 칸 폭과 같은 값: 바꾸면 어림도 같이 맞출 것.
TB_C1_MM, TB_C2_MM = 26.0, 52.0        # 대분류 칸 · 소분류 칸 폭
TB_C3_MM = 186.0 - 1.0 - TB_C1_MM - TB_C2_MM        # 지원 칸 폭(바깥 테두리와 칸 선 몫 1mm 를 뺀다)
TB_PAD_MM = 2.0                        # 소분류 칸 좌우 안쪽 여백
TB_RPAD_MM = 2.5                       # 지원 칸 좌우 안쪽 여백
LG_WHEN_MM = TB_C2_MM - 2 * TB_PAD_MM  # 앞으로 목록 소분류(때) 칸 글자 폭
LG_FAR_MM = TB_C2_MM + TB_C3_MM - 2 * TB_RPAD_MM       # 앞으로 구역 끝 조용한 한 줄이 쓰는 글자 폭(때 칸 + 지원 칸 전체)
LG_FAR_PAD_MM = 3.2                    # 그 한 줄의 위아래 안쪽 여백
LR_BOX_MM = 5.0 + 2.4                  # 줄 앞 체크 칸 + 사이
LG_BODY_MM = TB_C3_MM - 2 * TB_RPAD_MM - LR_BOX_MM       # 앞으로 줄 글이 쓰는 폭
TB_ROW_MM = TB_C3_MM - 2 * TB_RPAD_MM  # 지금 구역 줄 글이 쓰는 폭
H_AMT18 = 7.49                         # 금액 18pt·1.18 한 줄(표 안 금액은 18pt)
PC_ICON_MM = 10.0                      # 소분류 칸 왼쪽 가실 곳 그림(2026-11-18: 이름 두 줄 높이쯤)
PC_MARK_MM = PC_ICON_MM + 1.2 + 5.4    # 소분류 칸 왼쪽의 그림 + 체크 칸(세로) 높이
PC_MARK_W_MM = PC_ICON_MM + 1.6        # 그 칸 폭 + 이름과의 사이
PC_ROW_MM = PC_ICON_MM + 1.2           # 긴 이름: 그림·체크 칸을 가로로 한 줄 위에 둔 높이(그림 + 이름과의 사이)
PC_PAD_MM = 3.2                        # 소분류 칸 위아래 안쪽 여백
PG_LINE_MM = 0.6                       # 곳(묶음) 사이 줄
LR_PAD_MM = 1.2 + 0.2                  # 줄 안쪽 위아래 여백 + 줄 사이 선
LG_PAD_MM = 2.0 + 0.3 + 0.5            # 묶음 위아래 여백 + 아래 선 + 실측 보정(2026-11-15 골든 22건·재생 5건: 묶음 어림이 실측보다 1~5px 작았다)
ZT_MM = 11.0                           # 구역 제목 줄(글 + 아래 굵은 선 + 위 간격)
ZEMPTY_MM = 9.0                        # "지금 바로 하실 일은 없어요" 한 줄
NOTE_MM = 10.0                         # 표 바로 위 한 줄(지금 = ○월 ○일 기준 · 다녀오면 □에 ✓) + 표 바깥 테두리
NOTICE_LABEL = "지금 접수 중인 공고"
NOTICE_WHY_MAX, NOTICE_ASK_MAX = 140, 80          # 공고 줄의 왜 맞는지·물어볼 것 한 건이 한 쪽을 넘지 않게(실제 글은 이보다 훨씬 짧다. 넘으면 뒤를 줄임표로, 전문은 화면에 있다)


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


NOTICE_ASK = "조건은 창구에서 확인하세요"          # 화면 공고 줄(_new_notices.html nn-ai)과 같은 글
NO_NOW = "지금 바로 하실 일은 없어요. 아래 달에 신청하시면 돼요."
_MONTH = re.compile(r"(\d{1,2})(?:~(\d{1,2}))?월")


def word_lines(text: str, pt: int, width_mm: float) -> int:
    """낱말 단위로 줄을 바꿀 때(word-break: keep-all) 꺾이는 줄 수(최소 1). 좁은 칸(때 칸)에서 낱말이 줄 끝에 안 들어가 한 줄 더 드는 것까지 센다."""
    lines, cur, gap = 1, 0.0, text_mm(" ", pt)
    for word in text.split():
        w = text_mm(word, pt)
        if cur == 0.0:
            cur = w
        elif cur + gap + w <= width_mm:
            cur += gap + w
        else:
            lines, cur = lines + 1, w
        if cur > width_mm:                  # 낱말 하나가 한 줄보다 길면 글자 단위로 꺾인다
            lines, cur = lines + math.ceil(cur / width_mm) - 1, cur % width_mm
    return lines


# 글자 폭 실측(2026-11-16, Chromium 96dpi, 맑은 고딕): 1em 에 대한 폭. (보통, 굵게) — 한글·원·㎡ 1.00 / 공백 0.352 / 괄호 0.305·0.358 / 숫자 0.551·0.580 / ·,.: 0.219·0.262 / ~ 0.701·0.719 / 영문 소문자 0.504·0.537 / 대문자 0.625·0.661
_GLYPH_EM = {" ": (0.352, 0.352), "[": (0.305, 0.358), "]": (0.305, 0.358), "(": (0.305, 0.358), ")": (0.305, 0.358), "·": (0.219, 0.262), ",": (0.219, 0.262), ".": (0.219, 0.262),
             ":": (0.219, 0.262), "~": (0.701, 0.719), "-": (0.41, 0.414)}


def glyph_mm(text: str, pt: float, bold: bool = True) -> float:
    """글자 폭(mm)을 실측한 글자별 폭으로 센다(text_mm 는 한글 0.92em·그 밖 0.5em 로 거칠게 센 값이라 굵은 글자는 5~9% 작게, 공백·괄호가 많은 글은 크게 나온다). 새로 만든 앞으로 구역 어림이 쓴다."""
    em = 0.0
    for ch in text:
        if ch in _GLYPH_EM:
            em += _GLYPH_EM[ch][bold]
        elif ch.isdigit():
            em += 0.580 if bold else 0.551
        elif ch.isascii() and ch.isalpha():
            em += (0.661 if bold else 0.625) if ch.isupper() else (0.537 if bold else 0.504)
        else:
            em += 1.0
    return em * pt * _PT_K[0] * 0.3528


def word_flow(text: str, pt: int, width_mm: float, bold: bool = True) -> tuple[int, float]:
    """낱말 단위로 줄을 바꿀 때(word-break: keep-all) (줄 수, 마지막 줄에 찬 폭 mm). 글자 폭은 glyph_mm. 뒤에 이어 붙는 글이 같은 줄에 들어갈지 볼 때도 쓴다."""
    return token_flow([(w, bold) for w in text.split()], pt, width_mm)


def token_flow(tokens: Sequence[tuple[str, bool]], pt: int, width_mm: float) -> tuple[int, float]:
    """word_flow 의 바닥: 줄 중간에서 꺾이지 않는 덩어리(글, 굵은가) 목록을 공백 한 칸씩 띄워 폭 안에 쌓는다."""
    lines, cur, gap = 1, 0.0, glyph_mm(" ", pt, True)
    for word, bold in tokens:
        for k, piece in enumerate(p for p in re.split(r"(?=\()", word) if p):          # 여는 괄호 앞에서도 줄이 바뀔 수 있다(앞 글과 붙어 있어 사이 공백은 없다)
            w = glyph_mm(piece, pt, bold)
            g = 0.0 if k else gap
            if cur == 0.0:
                cur = w
            elif cur + g + w <= width_mm:
                cur += g + w
            else:
                lines, cur = lines + 1, w
            if cur > width_mm:              # 낱말 하나가 한 줄보다 길면 글자 단위로 꺾인다
                lines, cur = lines + math.ceil(cur / width_mm) - 1, cur % width_mm
    return lines, cur


def _lr_sub(r: Mapping[str, Any], shared: bool) -> str:
    """앞으로 줄 아래 한 줄의 곳: '농협 1644-8778' (묶음에서 곳을 한 번만 적을 때는 빈 글)."""
    if shared:
        return ""
    return " ".join(x for x in (r.get("place"), r.get("phone"), r.get("tel_note")) if x)


def _lr_stack(title: str, amt: str, w: float) -> bool:
    """앞으로 줄: 이름 오른쪽에 금액을 두면 이름의 어떤 낱말이 남은 폭보다 넓어 낱말 가운데서 꺾이는가. 그러면 금액을 이름 아래 줄 오른쪽 끝에 둔다('토양생태환경보 / 전' 같은 꺾임을 막는다)."""
    if not amt:
        return False
    left = max(w - (glyph_mm(amt, 16) + LR_COL_GAP), 30.0)
    return any(glyph_mm(x, 16) > left for x in re.split(r"\s+|(?=\()", title) if x)


def _lr_mm(v: Mapping[str, Any], w: float) -> float:
    """앞으로 줄 하나의 높이(mm). 첫 줄은 [이름 + 곳(작은 글, 같은 줄에 이어 쓴다)] ··· 금액이다. 금액을 뺀 폭에 이름과 곳이 다 들면 한 줄,
    아니면 곳이 다음 줄로 내려간다. 금액에 앞 말이 붙으면(pre) 금액이 이름 아래 줄로. 덧말(notes)은 그 아래 줄들."""
    amt = (((v["pre"] + " ") if v["pre"] else "") + v["amt"]) if v["amt"] else ""
    amt_w = glyph_mm(amt, 16) + LR_COL_GAP if amt else 0.0
    h = word_flow(v["text"], 14, w - FIT_SAFETY)[0] * H_NOTE if (v["text"] and not v["amt"]) else 0.0          # 금액 없는 글은 이름 아래 줄(14pt 굵게)
    if v["pre"] and v["amt"]:
        h += _n(amt, 16, w) * H_GT
        amt_w = 0.0
    elif amt and _lr_stack(v["title"], amt, w):          # 금액이 이름 아래 줄 오른쪽 끝으로
        h += H_GT
        amt_w = 0.0
    left = max(w - amt_w, 30.0)
    sub = v["sub"]
    n_lines, last_w = word_flow(v["title"], 16, left - FIT_SAFETY)             # 이름이 꺾이는 줄 수와 마지막 줄에 찬 폭
    if not sub or last_w + glyph_mm(" ", 16) + glyph_mm(sub, 14, False) + FIT_SAFETY <= left:
        h += n_lines * H_GT                                                 # 곳(작은 글)은 이름 끝 줄에 이어 붙는다
    else:
        h += n_lines * H_GT + word_flow(sub, 14, left - FIT_SAFETY, False)[0] * H_NOTE     # 곳은 한 덩어리(inline-block)로 다음 줄에 내려간다
    h += sum(_n(n, 14, w) * H_NOTE for n in v["notes"])
    return h + LR_PAD_MM


def month_label(when: str) -> str:
    """'내년 8~10월에 가입해요' → '8~10월', '내년 1월쯤' → '1월'. 달이 없으면 빈 글."""
    m = _MONTH.search(when or "")
    return (f"{m[1]}~{m[2]}월" if m[2] else f"{m[1]}월") if m else ""


def g_where(g: Mapping[str, Any]) -> str:
    """앞으로 묶음(같은 때)의 신청할 곳: 곳이 같으면 한 번, 다르면 가운뎃점으로 이은 글(곳 이름 + 전화. 덧말은 뺀다). 소분류 칸 때 아래에 작은 글로 쓴다."""
    if g.get("shared_place"):
        sp = g["shared_place"]
        return " ".join(x for x in (sp.get("place"), sp.get("phone")) if x)
    seen: list[str] = []
    for r in g["rows"]:
        w = " ".join(x for x in (r.get("place"), r.get("phone")) if x)
        if w and w not in seen:
            seen.append(w)
    return " · ".join(seen)


def paper_later(rows: Sequence[dict], srcs: Sequence[tuple[Any, CardLine]], nums, far: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """종이 앞면 「앞으로 신청할 것」(2026-11-17: 화면과 같은 줄, 접거나 줄이지 않는다): 화면의 앞으로 구역 줄(rows, 달 순서)을 달 묶음으로.
    묶음마다 때(소분류 칸)와 지원 줄들(□ 이름 · 금액 · 곳, 덧말 전부). 글은 모두 숫자 칸(nums)으로 감싼다. n 은 묶음이 차지하는 줄 수 어림(16pt 한 줄 = 1).
    far: split_screen 의 later_far(먼 줄 한 줄 안내 값). 있으면 묶음들 뒤에 조용한 한 줄(far.paper_text: '그 뒤에도 N가지가 더 있어요 · 내년 5월부터 신청해요 · 문자 알림을 받으시면 그 달에 알려 드려요')을 더한다."""
    ref = {id(r): cl.line for r, (_, cl) in zip(rows, srcs)}
    out: list[dict[str, Any]] = []
    for g in group_later(list(rows)):
        ref0 = ref[id(g["rows"][0])]
        when, tail = split_when(g["when"]) if g["known"] else (g["when"], "")
        when_mm = word_flow(when, 16, LG_WHEN_MM - FIT_SAFETY)[0] * H_GT
        shared = g["shared_place"]
        shared_bits = [x for x in (_lr_sub(shared, False) if shared else "", *g["shared_notes"]) if x]
        rs, body_mm = [], (_n(" · ".join(shared_bits), 14, LG_BODY_MM) * H_NOTE if shared_bits else 0.0)
        for r in g["rows"]:
            rref = ref[id(r)]
            sub = _lr_sub(r, bool(shared))
            notes = ([tail] if tail else []) + [n for n in r["notes"] if n not in g["shared_notes"]]
            body_mm += _lr_mm({"title": r["title"], "pre": r["pre"], "amt": r["amt"], "text": r["text"], "sub": sub, "notes": notes}, LG_BODY_MM)
            rs.append({"title": nums(r["title"], rref), "stack": bool(not r["pre"] and r["amt"] and _lr_stack(r["title"], r["amt"], LG_BODY_MM)),
                       "pre": nums(r["pre"], rref) if r["pre"] else "", "amt": nums(r["amt"], rref) if r["amt"] else "",
                       "text": nums(r["text"], rref) if r["text"] else "", "sub": nums(sub, rref) if sub else "", "notes": [nums(n, rref) for n in notes]})
        out.append({"when": nums(when, ref0), "where": "", "rows": rs, "shared": Markup(" · ").join(nums(x, ref0) for x in shared_bits),
                    "n": round((max(when_mm, body_mm) + LG_PAD_MM) / LINE_MM, 2)})
    far_line = None
    if far:
        m_ = re.match(r"^(그 뒤에도 )(\d+가지)(.*)$", far["paper_text"])
        html = (nums(m_[1], source="sheet") + Markup("<b>") + nums(m_[2], source="sheet") + Markup("</b>") + nums(m_[3], source="sheet")) if m_ else nums(far["paper_text"], source="sheet")
        far_line = {"text": html, "n": round((word_flow(far["paper_text"], 15, LG_FAR_MM - FIT_SAFETY)[0] * H_WHEN + LG_FAR_PAD_MM + PG_LINE_MM) / LINE_MM, 2)}
    return {"later_groups": out, "later_far": far_line}


TIER_K = (1.1, 1.0, 0.93, 0.85)        # 글자 단계(0: 지원 이름 18pt·설명 15pt, 1: 16·14, 2: 15·13, 3: 14·12)별로 표 줄 높이 어림에 곱하는 값(0 은 2026-11-18 줄이 적은 농가를 위해 앞에 더한 가장 큰 단계. 18/16 과 15/14 사이로 잡고 실제 그려 잰다). print.css [data-tier] 와 같은 단계. 골든 22건 + 재생 5건을 실제 그려 잰 값(어림이 실측보다 늘 8mm 넘게 컸다). 더는 줄이지 않는다
CONT_MM = 11.0                         # 이어진 쪽 맨 위 한 줄("제주 농돈 · (이어서)")


def paper_units(ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    """앞면 표의 줄을 위에서 아래로 한 줄씩(화면 표와 같은 순서): 지금 하실 일(곳 묶음 · 지금 접수 중인 공고 · 없으면 안내 한 줄) → 앞으로 신청할 것(달 묶음). n = 글자 단계 0 의 높이 어림."""
    boxes = [{"zone": "now", "kind": "g", "c": c, "n": n} for c, n in zip(ctx["vcards"], ctx["row_ns"])]
    at = next((i for i, c in enumerate(ctx["vcards"]) if c.get("always")), len(boxes))      # 화면(_result_boxes.html boxes)과 같은 자리: 지금 접수 중인 공고(AI가 읽은 공고)는 언제든 신청하는 줄만 든 첫 상자 바로 앞(없으면 끝)
    out: list[dict[str, Any]] = [*boxes[:at], *({"zone": "now", "kind": "n", "t": t, "n": t["n"]} for t in ctx["notices"]), *boxes[at:]]
    if not out:
        out = [{"zone": "now", "kind": "e", "n": ctx["zempty_n"]}]
    out += [{"zone": "later", "kind": "l", "g": g, "n": g["n"]} for g in ctx["later_groups"]]
    if ctx.get("later_far"):
        out.append({"zone": "later", "kind": "far", "far": ctx["later_far"], "n": ctx["later_far"]["n"]})
    return out


def paper_pages(ctx: Mapping[str, Any], cuts: Sequence[int], only: tuple[int, int, bool, bool] | None = None) -> dict[str, Any]:
    """표의 줄(units)을 cuts 에서 끊어 쪽마다 {now, later, first, last} 로 나눈다. 줄 높이 n 은 이미 글자 단계의 폭으로 센 값(_PT_K)이고 여기서 줄 높이 몫(tier_k)을 곱한다. only 가 있으면 그 범위의 쪽 하나만."""
    units = paper_units(ctx)
    k = ctx["tier_k"]
    scaled = [u | {"n": round(u["n"] * k, 2)} for u in units]
    edges = [0, *cuts, len(units)]
    specs = [(a, b, i == 0, i == len(edges) - 2) for i, (a, b) in enumerate(zip(edges, edges[1:]))]
    if only:
        specs = [only]
    pages = [{"now": [u for u in scaled[a:b] if u["zone"] == "now"], "later": [u for u in scaled[a:b] if u["zone"] == "later"], "first": first, "last": last}
             for a, b, first, last in specs]
    return {"pages": pages, "units": units, "cont_n": round(CONT_MM / LINE_MM, 2)}


def paper_row_lines(c: dict) -> float:
    """상자 하나가 차지하는 높이를 16pt 줄 수로. c 는 result_view 카드(글 그대로, 아직 숫자 칸으로 안 감싼 것)."""
    name = c["head"] or "가실 곳은 창구에 물어보세요"
    tel = bool(c.get("phone") or c.get("tel_note"))
    tel_w = 0.0
    tel_h = 0.0
    if tel:
        tel_w = min(TEL_MAX_MM, 8.1 + text_mm(c.get("phone") or "", 17) + (0.0 if c.get("phone") else text_mm(c.get("tel_note") or "", 14))) + 3.0
        tel_h = H_TEL if c.get("phone") else 0.0
        if c.get("tel_note"):
            tel_h += _n(c["tel_note"], 14, TEL_MAX_MM - (8.1 if not c.get("phone") else 0.0)) * H_NOTE if c.get("phone") else max(H_TEL, _n(c["tel_note"], 14, TEL_MAX_MM - 8.1) * H_NOTE)
    tag_w = (8.0 + text_mm("먼저 하실 일", 14) if c.get("pill") else 0.0) + (8.0 + text_mm(c["now"] if isinstance(c["now"], str) else "지금 신청할 수 있어요", 14) if c.get("now") else 0.0) if (c.get("pill") or c.get("now")) else 0.0
    side_w = max(tel_w - 3.0, min(TEL_MAX_MM, tag_w))
    side_h = tel_h + (TAG_H_MM * (2 if tag_w > TEL_MAX_MM else 1) if tag_w else 0.0)
    name_w = BOX_MM - BAND_X_MM - (NO_MM if c.get("no_n") else 0.0) - PIC_MM - (side_w + 3.0 if side_w else 0.0)
    name_h = word_flow(name, 18, name_w - FIT_SAFETY)[0] * H_NAME + (_n(c["where"], 14, name_w) * H_NOTE if c.get("where") else 0.0)
    band = max(PIC_H_MM, name_h, side_h) + BAND_PAD_MM
    w = BOX_MM - ROW_X_MM
    rows_ = c.get("rows")          # 화면이 다시 쓴 줄(이것을 해야 ○○을 받을 수 있어요 · 받을 돈 이름표)이 todo·gets 에는 아직 옛 글이라, 실제로 그려지는 rows 로 센다
    todo, gets = ([r for r in rows_ if r["kind"] == "do"], [r for r in rows_ if r["kind"] == "get"]) if rows_ is not None else (c["todo"], c["gets"])
    rows = sum(_do_mm(it, w) for it in todo) + sum(_get_mm(it, w) for it in gets)
    if c.get("hidden_n"):
        more = f"외 {c['hidden_n']}가지: " + " · ".join(c.get("hidden_names") or ())
        rows += wrap_lines(more, 14, MORE_MM) * H_NOTE + 1.0
    return (band + rows + BOX_BORDER_MM + BOX_GAP_MM + (PILL_EXTRA_MM if c.get("pill") else 0.0)) / LINE_MM


def _tb_rest_mm(it: Mapping[str, Any], w: float) -> float:
    """표 지원 칸 줄의 아래 덩어리(마감 알약 · 언제 · 덧말 · 이것을 해야 …). 글자 폭은 글자별 실측 폭(glyph_mm)으로 센다."""
    h = H_PILL if paper_urgent_date(it) else 0.0
    when = ([it["text"]] if it.get("text") and it.get("text_when") and not it.get("amt") and not paper_urgent_date(it) else []) + list(it.get("whens") or ())
    if when:
        h += word_flow(" · ".join(when), 15, w - 7.0 - FIT_SAFETY)[0] * H_WHEN
    h += sum(word_flow(n, 14, w - FIT_SAFETY, False)[0] * H_NOTE for n in (*(it.get("notes") or ()), *(it.get("place_notes") or ())))
    if it.get("unlock_text"):
        h += word_flow(it["unlock_text"], 15, w - FIT_SAFETY)[0] * H_WHEN
    return h


def _tb_do_mm(it: Mapping[str, Any], w: float) -> float:
    """표 지원 칸의 하실 일 한 줄: 연필 + 굵은 이름, 아래에 안내 글·언제·덧말."""
    h = word_flow(it["title"], 16, w - ICON_MM - FIT_SAFETY)[0] * H_GT
    if it.get("text"):
        h += word_flow(it["text"], 14, w - (7.0 if it.get("text_when") else 0.0) - FIT_SAFETY)[0] * H_NOTE
    return h + _tb_rest_mm({**it, "text": None}, w) + ROW_PAD_MM


def _tb_get_mm(it: Mapping[str, Any], w: float) -> float:
    """표 지원 칸의 받을 것 한 줄: 이름 ··· 금액(안 들어가면 금액이 이름 아래 줄 오른쪽 끝) → 언제 → 덧말 → 이것을 해야 …. 금액 없는 글은 이름 아래 줄(14pt 굵게)."""
    n_title, last_w = word_flow(it["title"], 16, w - FIT_SAFETY)
    top = n_title * H_GT
    if it.get("amt"):
        pre = (it.get("pre") or "").strip()
        amt_w = glyph_mm(it["amt"], 18) + (glyph_mm(pre, 16, False) + glyph_mm(" ", 16) if pre else 0.0)
        if not pre and last_w + AMT_GAP + amt_w <= w - FIT_SAFETY:
            top = (n_title - 1) * H_GT + H_AMT18
        else:                                   # 앞 말(16pt 보통)과 금액(18pt 굵게)은 이름 아래 한 줄 오른쪽 끝, 한 줄에 안 들면 두 줄
            top += (1 if amt_w <= w - FIT_SAFETY else math.ceil(amt_w * 1.05 / w)) * H_AMT18
    elif it.get("text") and not it.get("text_when"):
        top += word_flow(it["text"], 14, w - FIT_SAFETY)[0] * H_NOTE
    h = top + _tb_rest_mm(it, w) + ROW_PAD_MM
    if it.get("unlocks_n"):
        h += word_flow("이것을 하시면 알아볼 수 있는 지원 4가지", 15, w - FIT_SAFETY)[0] * H_WHEN
    return h


def pc_wide(name: str | None) -> bool:
    """곳 이름에 소분류 칸의 이름 자리(번호·체크 칸 옆)보다 넓은 낱말이 있으면 True: 그때는 번호·체크 칸을 가로로 한 줄 위에 두고 이름이 칸 폭 전체를 쓴다('농산물품질관리원(농관원)' 같은 긴 이름이 낱말 가운데서 꺾이지 않게)."""
    col = TB_C2_MM - 2 * TB_PAD_MM - PC_MARK_W_MM
    return any(glyph_mm(w, 16) > col - 0.6 for w in (name or "").replace("(", " (").split())


def paper_cell_mm(c: Mapping[str, Any]) -> float:
    """표의 소분류 칸(가실 곳) 높이(mm): [번호 · 체크 칸 | 곳 이름] + 어디서 + 전화 + 딱지. 칸 폭은 TB_C2_MM − 양쪽 여백."""
    inner = TB_C2_MM - 2 * TB_PAD_MM
    name = c.get("head") or "가실 곳은 창구에 물어보세요"
    flow = name.replace("(", " (")
    if pc_wide(name):
        h = PC_ROW_MM + word_flow(flow, 16, inner - FIT_SAFETY)[0] * H_GT
    else:
        h = max(PC_MARK_MM, word_flow(flow, 16, inner - PC_MARK_W_MM - FIT_SAFETY)[0] * H_GT)
    if c.get("where"):
        h += _n(c["where"], 14, inner) * H_NOTE
    if c.get("phone"):
        h += math.ceil((6.0 + 1.6 + text_mm(c["phone"], 16)) / inner) * H_TEL
    if c.get("tel_note"):
        h += _n(c["tel_note"], 14, inner - (0.0 if c.get("phone") else 7.6)) * H_NOTE
    h += TAG_H_MM * ((1 if c.get("pill") else 0) + (1 if c.get("now") else 0))
    return h + PC_PAD_MM


def paper_group_lines(c: dict) -> float:
    """표 한 칸 묶음(가실 곳 하나 = 소분류 칸 + 그 곳의 지원 줄들)이 차지하는 높이를 16pt 줄 수로. c 는 result_view 카드(글 그대로)."""
    rows_ = c.get("rows")
    todo, gets = ([r for r in rows_ if r["kind"] == "do"], [r for r in rows_ if r["kind"] == "get"]) if rows_ is not None else (c["todo"], c["gets"])
    rows = sum(_tb_do_mm(it, TB_ROW_MM) for it in todo) + sum(_tb_get_mm(it, TB_ROW_MM) for it in gets)
    if c.get("hidden_n"):
        more = f"외 {c['hidden_n']}가지: " + " · ".join(c.get("hidden_names") or ())
        rows += wrap_lines(more, 14, TB_ROW_MM - 4.0) * H_NOTE + 1.0
    return (max(paper_cell_mm(c), rows) + PG_LINE_MM) / LINE_MM


TODAY = re.compile(r"^오늘\s+")         # 종이는 집에 가져가 다음 날 읽는다: '오늘 11월 13일까지'는 '11월 13일까지'로(날짜는 그대로)
DAYS_LEFT_TAIL = re.compile(r"\s*·\s*\d+일 남음$")      # '○일 남음'은 읽는 날이 달라지면 틀리므로 종이에는 싣지 않는다(날짜만)


def paper_urgent_date(it: Mapping[str, Any]) -> str:
    """급한 줄(화면의 빨간 '오늘까지'·'○일 남음' 알약이 있는 줄)의 마감 날짜 글('11월 13일까지'). 종이는 다음 날 읽으므로 '오늘'·'○일 남음'은 뺀다. 날짜 글이 아니면 빈 글."""
    text = DAYS_LEFT_TAIL.sub("", TODAY.sub("", it["text"])) if it.get("text") else ""
    if not (it.get("urgent") and text.endswith("까지")):
        return ""
    return f"오늘까지({text.removesuffix('까지')})" if it["text"].startswith("오늘") else text        # 마감이 기준일 당일이면 '오늘까지(11월 13일)': 오늘이 마감임이 보이고, 며칠 뒤에 읽어도 날짜가 남는다


def paper_cards(cs: CardSet, front, cards: list[dict], nums) -> list[dict]:
    """result_view 카드를 종이에 그릴 값으로: 숫자가 든 글은 모두 nums()로 감싸 출처·기준일 칸에 담는다(검사 NO_SOURCE·NARR_DIGIT).
    줄마다 숫자의 출처는 그 줄(Line)의 제도 판정이다. 카드의 rows(화면과 같은 줄·같은 차례)를 그대로 쓰고, 빈 종이만 하실 일 → 받을 것 차례다.
    급한 줄(빨간 알약이 있던 줄)은 종이에서 마감 날짜를 빨강 테두리 알약 글로 싣는다."""
    if cs.empty:
        lines = [list(ls) for ls in (front.keep_actions, front.insurance_next) if ls]
        refs = [list(ls) for ls in lines]
    else:
        refs = [list(c["row_refs"]) for c in cards]
    out = []
    for k, (c, rrefs) in enumerate(zip(cards, refs)):
        first = (rrefs or [None])[0]
        d = dict(c)
        d["no"] = nums(c["no"], source="sheet") if c["no"] else ""
        d["no_n"] = nums(c["no_n"], source="sheet") if c["no_n"] else ""
        d["wide"] = pc_wide(c["head"])
        d["hidden_names"] = [nums(cl.title, cl.line) for cl in cs.cards[k].hidden] if not cs.empty else []
        for key in ("head", "phone", "tel_note", "where"):
            d[key] = nums(c[key], first, source="sheet") if c[key] else c[key]
        d["hidden_n"] = nums(str(c["hidden_n"]), source="sheet") if c["hidden_n"] else 0
        assert len(rrefs) == len(c["rows"]), "상자 줄 수가 카드 층과 다릅니다"
        rows = []
        for it, ref in zip(c["rows"], rrefs):
            x = dict(it)
            text = DAYS_LEFT_TAIL.sub("", TODAY.sub("", it["text"])) if it["text"] else it["text"]
            date = paper_urgent_date(it)
            x["urgent"] = nums(date, ref) if date else ""       # 종이는 다음 날 읽는다: '오늘까지'·'○일 남음' 대신 마감 날짜를 굵은 알약으로(설계 8절 6)
            x["text"] = "" if date else (nums(text, ref) if text else text)
            x["text_when"] = False if date else it["text_when"]
            x["title"] = nums(it["title"], ref)
            x["pre"], x["amt"] = (nums(it["pre"], ref) if it["pre"] else ""), (nums(it["amt"], ref) if it["amt"] else "")
            x["whens"] = [nums(DAYS_LEFT_TAIL.sub("", TODAY.sub("", w)), ref) for w in it["whens"]]
            x["notes"] = [nums(n, ref) for n in it["notes"]]
            x["place_notes"] = [nums(n, ref, source="sheet") for n in it["place_notes"]]      # 곳 안내 글('전화 1334')은 접수처 표의 글이다
            x["unlocks_n"] = nums(str(it["unlocks_n"]), source="sheet") if it["unlocks_n"] else 0
            x["unlock_text"] = nums(it["unlock_text"], ref) if it.get("unlock_text") else ""
            rows.append(x)
        d["rows"] = rows
        d["todo"], d["gets"] = [x for x in rows if x["kind"] == "do"], [x for x in rows if x["kind"] == "get"]
        out.append(d)
    return out


def conclusion_parts(text: str) -> tuple[str, ...]:
    """결론 한 줄을 줄바꿈 자리에서 둘로: '경영체 등록부터 하세요. 조건이 맞으면' / '연 약 180만~258만 원 받을 수 있어요'(금액이 낱말 중간에서 꺾이지 않게)."""
    m = MONEY_SENTENCE.match(text)
    return (m[1].rstrip(), m[2] + m[3]) if m else (text,)


def label_split(text: str) -> tuple[str, str]:
    """'가실 때: 이 종이와 신분증' → ('가실 때', '이 종이와 신분증'). 이름표가 없는 글은 ('', 글)."""
    head, sep, rest = text.partition(": ")
    return (head, rest) if sep and len(head) <= 12 else ("", text)


# --- 넘침 검사 -----------------------------------------------------------------------------------

_TAG = re.compile(r"<([a-zA-Z0-9]+)\b[^>]*>")
_TAGS = re.compile(r"<[^>]+>")
_CLASS = re.compile(r"\bclass=\"([^\"]*)\"")
_ATTR = re.compile(r"\b(data-sec|data-par|data-n)=\"([^\"]*)\"")
# 글자 줄 말고 테두리·안쪽 여백이 먹는 높이(16pt 줄 = 1 기준). print.css의 padding·border를 줄 수로 환산한 값.
BOX_EXTRA = {"it": 0.2, "pl": 0.25, "c": 0.25, "cd": 0.35, "sh": 0.7, "know": 1.65}      # cd: 가실 곳 카드, sh: 한마디로 칸(카드 배치)
CARD_LINE_LIMIT = 36.95          # 좌우 줄 앞면(v2)의 줄 수 상한(16pt 한 줄 = 1). 2026-11-17 표 구조(대분류 | 소분류 | 지원)로 바꾼 뒤 재측정: 골든 22건 + 긴 문장 22건의 가능한 모든 모양(paper_caps_seq, 어림 35.8~38.5줄인 것)에서 '어림 + 남는 px/27.74' 가 가장 작은 값은 38.37(B07)이고 여유 40px(1.44줄)을 두면 36.93 → 36.95(어림이 36.9x 인 사례가 아래 여백 47px 로 실린다). 어림이 실측과 맞아(묶음 하나 ±3px) 문장 몫의 여유(LEAD_FIT_SLACK)는 0으로 했다. 이전: 37.2(2026-11-16), 37.0, 37.1, 37.9, 36.5, 35.5, 33.5
TIER_LIMIT = (38.7, 37.3, 36.0, 37.4)      # 글자 단계(data-tier)별 줄 수 상한(결과가 있는 종이). 2026-11-18 재측정(뒷면·결론 상자·알아 두세요 상자가 없어지고 가실 곳 그림이 생긴 표):
                                 # 골든 22건 + 시연 5건을 단계마다 그려 '어림 + 남는 px/27.74' 를 구하고, 한 쪽이 거의 찬 사례(어림 33줄 이상)에서 가장 작은 값(단계 0·1·2·3 에서 39.44·37.99·36.67·38.12)에서
                                 # 여유 0.7줄(약 19px)을 뺐다. 단계마다 어림의 기울기가 조금 달라(TIER_K 가 거친 값이라) 한 값으로 묶지 않았다. data-tier 가 없는 종이(빈 종이)는 CARD_LINE_LIMIT
H2_EXTRA = 0.3
NARR_EXTRA = 0.05               # 설명 문장 한 줄은 실측 0.85줄(14pt, 줄 간격 1.26 = 추정 0.875)이라 줄 사이 여백 몫만 조금 더한다(옛 종이는 0.32). 2026-11-14 실측: 두 줄 문장 하나 = 47px = 1.7줄
PAGE_PAD_LINES = 1.0            # 위 12mm + 아래 10mm 여백과 바닥글 윗선·안쪽 간격(약 7mm 줄 1개)


def _front_total(front: str, extra: float = 0.0) -> tuple[float, int, dict[str, int]]:
    """앞면 HTML 의 줄 수 어림(16pt 한 줄 = 1) · 카드 수 · 구획별 항목 수."""
    total = PAGE_PAD_LINES + extra
    per_section: dict[str, int] = {}
    cards = 0
    has_narr = False
    for tag in _TAG.finditer(front):
        cm = _CLASS.search(tag.group())
        classes = cm.group(1).split() if cm else []
        pt = next((int(c[2:]) for c in classes if re.fullmatch(r"pt\d+", c)), None)
        if "line" not in classes or pt is None:
            continue
        attrs = dict(_ATTR.findall(tag.group()))
        cards += "cd" in classes or "rrw" in classes
        if ("it" in classes or "pl" in classes) and attrs.get("data-sec"):
            per_section[attrs["data-sec"]] = per_section.get(attrs["data-sec"], 0) + 1
        if attrs.get("data-par") == "1":
            continue
        n = float(attrs.get("data-n", "1"))
        if "narr" in classes:                                   # 설명 문장: 글자 수로 꺾임을 센다(속성으로 두면 AI/템플릿 HTML 동일성이 깨진다)
            has_narr = True
            end = front.find("</p>", tag.end())
            n = wrap_lines(_TAGS.sub("", front[tag.end():end if end > 0 else tag.end()]), 14, FRONT_TEXT_MM)
            total += NARR_EXTRA * n
        total += pt / 16 * n
        total += sum(v for k, v in BOX_EXTRA.items() if k in classes)
        total += H2_EXTRA if tag.group(1) == "h2" else 0
    if has_narr:
        total -= LEAD_FIT_SLACK                                 # 설명 문장이 얹힌 종이는 문장 몫으로 상자 어림의 여유를 돌려받는다(한 번만). 문장을 실을지 정하는 render_sheet 의 계산과 같은 값
    return total, cards, per_section


def check_overflow(html: str, extra: float = 0.0) -> list[str]:
    """앞면이 한 쪽에 안 들어갈 것 같으면 한국어 메시지 목록(괜찮으면 빈 목록).

    앞면의 `.line` 요소마다 pt 클래스(ptNN)로 줄 수를 환산(NN/16)하고, data-n="k"가 있으면 k줄로 센다(긴 원문; 좌우 줄은 render.paper_row_lines 가 어림한 값).
    항목·상자·묶음 제목의 테두리·여백과 쪽 여백을 더해 한도를 넘는지, 구획별 항목 수가 상한을 넘는지 본다.
    같은 줄에 나란히 놓이는 칸은 data-par="1"로 표시해 한 번만 센다. extra: 아직 안 들어간 글(설명 문장 자리)을 위해 미리 더하는 줄 수.
    """
    front = html
    mark = '<section class="sheet front'
    parts = front.split(mark)
    sheets = [parts[0] + mark + parts[1], *(mark + x for x in parts[2:])] if len(parts) > 1 else [front]        # 앞면이 여러 쪽(표가 이어질 때)이면 쪽마다 한 쪽 한도로 본다
    out: list[str] = []
    per_section: dict[str, int] = {}
    for i, page in enumerate(sheets):
        head = page.split('class="sheet front', 1)[1][:120] if 'class="sheet front' in page else ""
        card_sheet = 'cardsheet' in head
        tier = re.search(r'data-tier="(\d)"', head)
        limit = (TIER_LIMIT[int(tier[1])] if tier and int(tier[1]) < len(TIER_LIMIT) else CARD_LINE_LIMIT) if card_sheet else FRONT_LINE_LIMIT
        total, cards, per_sec = _front_total(page, extra if i == 0 else 0.0)
        for k, v in per_sec.items():
            per_section[k] = per_section.get(k, 0) + v
        label = f" {i + 1}쪽" if len(sheets) > 1 else ""
        if total > limit:
            out.append(f"종이{label}{'이' if label else '가'} 너무 길어요: 약 {total:.1f}줄 (최대 {limit:g}줄). 항목을 줄여 주세요.")
        if cards > CARD_CAP and (not card_sheet or "empty" in head):         # 결과가 있는 종이의 표는 곳 수 한도가 없다(쪽이 이어진다)
            out.append(f"가실 곳 카드가 {cards}개로 상한 {CARD_CAP}개를 넘어요.")
    for sec, n in per_section.items():
        cap = SECTION_CAP.get(sec)
        if cap is not None and n > cap:
            out.append(f"'{SECTION_NAME.get(sec, sec)}' 칸이 {n}개로 상한 {cap}개를 넘어요.")
    items = sum(n for s, n in per_section.items() if s not in ("F", "G"))
    if items > ITEM_CAP and not any("상한" in m for m in out):
        out.append(f"종이 항목이 {items}개로 상한 {ITEM_CAP}개를 넘어요.")
    return out


def front_lines(html: str, extra: float = 0.0) -> float:
    """앞면 줄 수 어림(한도와 비교하지 않는다). 측정 스크립트가 실측과 맞춰 한도를 정할 때 쓴다."""
    return _front_total(html, extra)[0]


# 다른 화면 모듈(유형별 종이 등)이 쓰는 공개 이름. 위 밑줄 이름을 바꿔도 여기만 맞추면 된다.
ENV = _env
NUMBER = _NUMBER
text_rows = _rows
