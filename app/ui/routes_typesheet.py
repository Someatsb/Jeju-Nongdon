"""유형별 종이 화면(Task 23): 작물 x 면적 구간 x 연령 구간을 고르면 사람 정보 없는 A4 앞면 1장.

GET  /typesheet                 고르는 화면(선택 3개)
POST /typesheet[?view=screen]   종이. 인쇄 전 검사(preflight_type)에 걸리면 "인쇄 보류" 화면. view=screen은 화면 확대.
이름·번호·읍면동·태어난 해를 받는 칸은 없다. 종이의 숫자는 모두 span.num(data-source·data-asof) 안에 있다.
"""
import logging
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from markupsafe import Markup, escape
from pydantic import ValidationError

from app.core.models import Action, TypeQuery
from app.core.office_say import office_say
from app.core.sheet_rules import CHECK_TAG
from app.core.typesheet import build_typesheet
from app.core.units import fmt_won
from app.ui.preflight import REASONS
from app.ui.preflight_type import preflight_html
from app.ui.render import CIRCLED, ENV, NUMBER, UI_DIR, text_rows
from app.ui.routes_counsel import SCREEN_CSS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/typesheet")
AREA_CHOICES = (("le_0_5ha", "0.5ha 이하"), ("0_5_to_1ha", "0.5~1ha"),
                ("gt_1ha", "1ha 넘는 밭"))
AREA_SUB = {"le_0_5ha": "약 1,500평 이하", "0_5_to_1ha": "약 1,500~3,000평", "gt_1ha": "약 3,000평 넘음"}
AREA_SHORT = {"le_0_5ha": "0.5ha 이하", "0_5_to_1ha": "0.5~1ha", "gt_1ha": "1ha 넘는 밭"}
AGE_CHOICES = (("lt60", "60세 미만"), ("60_64", "60~64세"), ("65_74", "65~74세"), ("75_84", "75~84세"), ("ge85", "85세 이상"))
AGE_SHORT = dict(AGE_CHOICES)
ACTION_TEXT = {
    "PREREQ:mgmt_registration": "농업경영체 등록하기",
    "PREREQ:fund": "작목반 회비(자조금) 내기",
    "PREREQ:spouse_registration": "함께 농사짓는 배우자도 경영체에 올리기",
    "KEEP:direct_pay_education": "올해 직불 교육 듣기(끊기지 않게)",
    "COOP_SWITCH:coop_fund": "물량을 농협에 내는 쪽으로 바꾸기(다음 시즌 조건 확인)",
    "PREREQ:enrollment": "지원사업 참여 신청하기",
}
ACTION_PREFIX_TEXT = (("KEEP:mgmt_renewal:", "경영체 정보 갱신하기(3년마다) · {tail}년까지"),)
KIND_TEXT = {"URGENT": "마감이 가까운 신청", "DISASTER_REPORT": "재해 신고", "PREREQ": "먼저 갖출 것", "KEEP": "끊기지 않게 할 일",
             "APPLY_NOW": "지금 신청", "ASK_COOP": "농협에 물어볼 것", "COOP_SWITCH": "농협 출하로 바꾸기",
             "APPLY_NEXT": "다음 신청", "REVISIT": "다시 확인"}
MAX_AMOUNT_EXAMPLES = 2   # 예시 금액 줄 상한(+ 시장 사실 줄 하나 = 3줄): 앞면 한 장(35줄)에 들어가게. 못 실은 줄 수는 제목에 "외 N건"
RESPONSIBILITY = "개인 판정이 아니에요 · 센터에서 개인 상담을 받으세요"
BAD_CHOICE = "작물, 밭 넓이, 나이대를 하나씩 모두 눌러 주세요."


TEXT_WIDTH_PT = 505   # 쪽 너비 210mm - 좌우 여백 24mm - 안쪽 띠(약 5mm)를 pt로


def est_rows(text: str, pt: int) -> int:
    """글이 차지할 줄 수 어림(넘침 검사용). 한글·한자는 글자 크기 1, 숫자·영문·기호는 0.55로 센다."""
    width = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in text) * pt
    return max(1, -int(-width // TEXT_WIDTH_PT))


def sub_text(line) -> str:
    """줄 둘째 칸 글. '확인' 꼬리표가 이미 "확인할 조건 있음"을 말하므로 같은 말은 덜어 낸다(한 장에 넣으려고)."""
    parts = [x for x in (line.sub or "").split(" · ") if x and not (line.print_tag == "CHECK" and x == CHECK_TAG)]
    return " · ".join(parts)


def _form_page(request: Request, *, error: str | None = None, values: dict | None = None) -> Response:
    crops = [(c.crop_code, c.label) for c in request.app.state.tables.crops]
    return request.app.state.templates.TemplateResponse(
        request, "typesheet.html", {"crops": crops, "areas": AREA_CHOICES, "ages": AGE_CHOICES,
                                    "error": error, "values": values or {}, "sub_area": AREA_SUB}, status_code=422 if error else 200)


@router.get("", response_class=HTMLResponse)
def choose(request: Request) -> Response:
    return _form_page(request)


def static_action_text(action_id: str) -> str | None:
    """이름이 고정된 행동(PREREQ·COOP_SWITCH·KEEP)의 한글. 접두사 id(KEEP:mgmt_renewal:<연도>)는 꼬리를 문구에 넣는다."""
    if action_id in ACTION_TEXT:
        return ACTION_TEXT[action_id]
    for prefix, template in ACTION_PREFIX_TEXT:
        if action_id.startswith(prefix):
            return template.format(tail=action_id[len(prefix):])
    return None


def pick_examples(lines: tuple, max_amounts: int = MAX_AMOUNT_EXAMPLES) -> tuple[tuple, int]:
    """예시 줄을 고른다: 금액 줄은 앞의 max_amounts개, 시장 사실 줄(가격안정관리제 kg당 평균 등)은 하나 남긴다.

    돌려주는 값: (실을 줄들(원래 순서), 못 실은 줄 수).
    """
    def is_fact(e) -> bool:
        return e.amount is None or e.amount.kind == "REFERENCE_LAST_SEASON"

    amounts = [e for e in lines if not is_fact(e)][:max_amounts]
    fact = next((e for e in lines if is_fact(e)), None)
    keep = {id(e) for e in amounts} | ({id(fact)} if fact is not None else set())
    kept = tuple(e for e in lines if id(e) in keep)
    return kept, len(lines) - len(kept)


def action_text(a: Action, offices) -> str:
    """먼저 하실 일 한 줄. 선결 조건이 열어 주는 돈은 하한이라 '최소 약'으로 쓴다."""
    text = static_action_text(a.action_id) or KIND_TEXT.get(a.kind, a.kind)
    if a.kind == "PREREQ" and a.unlock_low_won:
        text += f" → 열리는 돈 최소 약 {fmt_won(a.unlock_low_won, a.unlock_low_won)}"
    office = offices.get(a.office_id)
    name = office_say(office.name) if office else None
    return f"{text} · {'농협' if name == '지역농협' else name}" if office else text       # 곳 이름은 결과 화면과 같은 표기(농협·읍·면·동)


def _stamper(bundle, as_of: date):
    """(nums, stamp): ref가 Line이면 그 제도 행의 출처·확인일, 아니면 인자, 아니면 코드 계산(calc:typesheet)."""
    by_key: dict[str, tuple[str, str]] = {}
    for p in bundle.programs:
        if p.status != "hold" and p.verified_date is not None:
            by_key.setdefault(p.program_key, (f"supports:{p.id}", p.verified_date.isoformat()))
    fallback = ("calc:typesheet", as_of.isoformat())

    def resolve(ref, source, asof) -> tuple[str, str]:
        key = getattr(ref, "program_key", ref)
        if key in by_key:
            return by_key[key]
        if source is not None:
            return source, (asof or as_of).isoformat()
        return fallback

    def nums(text, ref=None, source=None, asof=None) -> Markup:
        if not text:
            return Markup("")
        src, day = resolve(ref, source, asof)
        out, pos = [], 0
        for m in NUMBER.finditer(str(text)):
            out.append(escape(text[pos:m.start()]))
            out.append(Markup('<span class="num" data-source="{}" data-asof="{}">{}</span>').format(src, day, m.group()))
            pos = m.end()
        out.append(escape(text[pos:]))
        return Markup("").join(out)

    def stamp(text, ref=None, source=None, asof=None, cls="") -> Markup:
        if not text:
            return Markup("")
        src, day = resolve(ref, source, asof)
        return Markup('<span class="{} num" data-source="{}" data-asof="{}">{}</span>').format(cls, src, day, text)

    return nums, stamp


def render_typesheet(request: Request, q: TypeQuery) -> str:
    st = request.app.state
    cfg, bundle = st.cfg, st.tables
    sheet = build_typesheet(q, bundle, st.snapshot, cfg.as_of)
    labels = {c.crop_code: c.label for c in bundle.crops}
    nums, stamp = _stamper(bundle, cfg.as_of)
    by_pid = {p.id: p for p in bundle.programs}

    def example_source(e) -> tuple[str, date]:
        if e.amount is not None and e.amount.program_id in by_pid and by_pid[e.amount.program_id].verified_date:
            return f"supports:{e.amount.program_id}", by_pid[e.amount.program_id].verified_date
        return "calc:typesheet", cfg.as_of

    examples, dropped = pick_examples(sheet.example_1000py)
    ctx = {
        "cfg": cfg, "sheet": sheet, "nums": nums, "stamp": stamp,
        "title_place": f"{labels.get(q.crop_code, q.crop_code)} · {AREA_SHORT[q.area_band]} · {AGE_SHORT[q.age_band]} 유형 안내",
        "asof_demo": f"기준일 {cfg.as_of.isoformat()}" if cfg.demo_asof else None,
        "asof_plain": f"{cfg.as_of.year}년 {cfg.as_of.month}월 {cfg.as_of.day}일",
        "circled": lambda i: CIRCLED[i], "est_rows": est_rows, "sub_text": sub_text, "examples": examples, "examples_dropped": dropped,
        # provisional: 상담 종이 줄에만 붙는 잠정 배지(공용 매크로 item이 부른다). 유형별 종이에는 없다.
        "provisional": lambda line: None, "rows": text_rows,
        "action_text": lambda a: action_text(a, bundle.offices), "example_source": example_source,
        "foot": [{"text": RESPONSIBILITY}, {"text": f"유효 30일 · 기준일 {cfg.as_of.isoformat()}"}],
    }
    css = (UI_DIR / "static" / "print.css").read_text(encoding="utf-8")
    return ENV.get_template("typesheet_doc.html").render(ctx | {"css": Markup(css)})


@router.post("", response_class=HTMLResponse)
async def print_typesheet(request: Request, view: str | None = None) -> Response:
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    known = {c.crop_code for c in request.app.state.tables.crops}
    try:
        q = TypeQuery(crop_code=form.get("crop_code", ""), area_band=form.get("area_band", ""), age_band=form.get("age_band", ""))
        if q.crop_code not in known:
            raise ValueError(q.crop_code)
    except (ValidationError, ValueError):
        return _form_page(request, error=BAD_CHOICE, values=form)
    try:
        html = render_typesheet(request, q)
    except Exception:
        log.exception("유형별 종이 만들기 실패")
        return request.app.state.templates.TemplateResponse(
            request, "print_hold.html", {"reasons": [("BUILD_FAILED", "종이를 만들지 못했어요. 담당자에게 알려 주세요.")]})
    codes = preflight_html(html, request.app.state.cfg)
    if codes:
        return request.app.state.templates.TemplateResponse(
            request, "print_hold.html", {"reasons": [(c, REASONS.get(c, c)) for c in codes]})
    if view == "screen":
        html = html.replace("</head>", SCREEN_CSS + "</head>", 1)
    return HTMLResponse(html)
