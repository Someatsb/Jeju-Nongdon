"""결과 확인 화면(Task 16, U16): 시트를 만들기 전에 직원이 R1·R2를 표시한다.

GET  /counsel/confirm  세션 프로필을 1차 매칭(받는 것을 비운 채)해 LIKELY·CHECK·BLOCKED_PREREQ만 program_key마다 카드 하나로 보인다
                       ("이미 받고 계신 지원이 있으면 눌러 주세요": already 체크박스). 직불을 받는다고 누르면 "올해 직불 교육을 들으셨어요?"
                       (direct_payment_education Y/N). 아래에 작물별 보험·안전보험 누름 단추(value="yes").
POST /counsel/confirm  표시를 담은 새 FarmProfile(model_validate, 원본은 안 고친다)을 세션에 두고
                       다시 매칭해 본 뒤 /counsel/working으로 303. 소농·면적직불을 받고 있다고 했는데 교육 값이 "NA"면 "N"으로(교육 안내가 나가게).
                       first_heard(처음 들음) 칸은 화면에서 없앴지만 오면 그대로 받는다(시험·옛 입력 호환).
POST /counsel/new      세션 전체(프로필·문자 번호·대신 입력 표시)를 지우고 입력 화면으로(?to=home이면 첫 화면으로).
세션이 없으면 입력 화면으로 303. 표는 app.state.tables(앱을 만들 때 한 번 읽음). 폼 값은 로그에 쓰지 않는다.
"""
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.match import match_supports
from app.core.models import FarmProfile, MatchResult
from app.ui.session import COOKIE, profile_session, set_session_cookie

router = APIRouter(prefix="/counsel")

CANDIDATE_RANK = {"LIKELY": 0, "CHECK": 1, "BLOCKED_PREREQ": 2}   # 한 제도의 변형들 중 가장 앞선 상태를 보인다
DIRECT_PAY_KEYS = frozenset({"NAT-DIRECT-SMALL", "NAT-DIRECT-AREA"})   # 직불 교육 질문이 붙는 제도(받고 있다고 누르면 질문이 나온다)
EDUCATION_VALUES = ("Y", "N")
CUE_SAY = {      # 확인 화면 작은 글(표의 recognition_cue)을 보일 때만 해요체로 푼다(표는 그대로). 차액 보전·운송비 글은 뜻이 달라질까 봐 풀지 않는다
    "3월 신청, 탐나는전(지역화폐)으로 50만 원": "3월에 신청해서 탐나는전(지역화폐)으로 받는 50만 원",
    "11~12월 통장으로 130만 원": "11~12월에 통장으로 들어오는 130만 원",
    "2월 신청, 농협 농자재 15만 원": "2월에 신청해서 농협 농자재로 받는 15만 원",
    "신청 없이 경영체 정보로 정산": "신청 안 해도 농업경영체 정보로 정산돼요",
    "태풍·우박 뒤 읍면에 내는 피해 신고": "태풍·우박 뒤 읍·면에 내는 피해 신고",
}


def cue_say(cue: str | None) -> str | None:
    return CUE_SAY.get(cue or "", cue)


@dataclass(frozen=True)
class Line:
    key: str
    status: str
    names: tuple[str, ...]
    cue: str | None
    question: str | None      # CHECK 줄만: manual_check 첫 항목(화면에는 안 보인다)


def _session(request: Request) -> dict | None:
    return profile_session(request)


def _lines(request: Request, profile: FarmProfile) -> list[Line]:
    """받는 것·처음 들음을 비운 1차 매칭 결과를 program_key마다 한 줄로(표 순서). 이미 받는 줄도 남는다."""
    state = request.app.state
    bundle = state.tables
    blank = FarmProfile.model_validate({**profile.model_dump(), "already_receiving": (), "first_heard": ()})
    grouped: dict[str, list[MatchResult]] = {}
    for m in match_supports(blank, bundle.programs, state.cfg.as_of, crops=bundle.crops):
        if m.status in CANDIDATE_RANK:
            grouped.setdefault(m.program_key, []).append(m)
    by_id = {p.id: p for p in bundle.programs}
    lines = []
    for key, ms in grouped.items():
        best = min(ms, key=lambda m: CANDIDATE_RANK[m.status])
        names = tuple(dict.fromkeys(n for n in (by_id[m.program_id].name for m in ms) if n))
        question = None
        if best.status == "CHECK" and best.manual_check:
            question = best.manual_check.split("/")[0].strip() or None
        lines.append(Line(key, best.status, names or (key,), cue_say(by_id[best.program_id].recognition_cue), question))
    return lines


def _answers(profile: FarmProfile) -> dict[str, str]:
    """보험 누름 단추의 현재 값: 이미 가입했다고 표시된 칸만 "yes"(안 누르면 모름)."""
    ans = {}
    for i, crop in enumerate(profile.crops, 1):
        ans[f"crop{i}_ins_disaster"] = "yes" if crop.ins_disaster else ""
        ans[f"crop{i}_ins_income"] = "yes" if crop.ins_income else ""
    ans["safety_owner"] = "yes" if "owner" in profile.ins_safety else ""
    ans["safety_spouse"] = "yes" if "spouse" in profile.ins_safety else ""
    return ans


def _to_input() -> Response:
    return RedirectResponse("/counsel/input", status_code=303)


@router.get("/confirm", response_class=HTMLResponse)
def confirm_form(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return _to_input()
    profile: FarmProfile = session["profile"]
    labels = {c.crop_code: c.label for c in request.app.state.tables.crops}
    return request.app.state.templates.TemplateResponse(request, "confirm.html", {
        "proxy": bool(session.get("proxy")), "lines": _lines(request, profile), "direct_keys": sorted(DIRECT_PAY_KEYS),
        "already": profile.already_receiving, "crops": [(i, labels.get(c.crop_code, c.crop_code)) for i, c in enumerate(profile.crops, 1)],
        "education": profile.flags.direct_payment_education if profile.flags.direct_payment_education in EDUCATION_VALUES else "",
        "has_spouse": profile.spouse != "none", "answers": _answers(profile)})


@router.post("/confirm")
async def submit_confirm(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return _to_input()
    profile: FarmProfile = session["profile"]
    form = await request.form()
    shown = {line.key for line in _lines(request, profile)}      # 화면에 없던 제도 key는 받지 않는다
    already = {v for v in form.getlist("already") if isinstance(v, str)} & shown
    heard = {v for v in form.getlist("first_heard") if isinstance(v, str)} & shown - already  # 둘 다 오면 [받고 있음]만
    crops = [{**c.model_dump(), "ins_disaster": True if form.get(f"crop{i}_ins_disaster") == "yes" else None,
              "ins_income": True if form.get(f"crop{i}_ins_income") == "yes" else None}   # 누른 것만 가입, 안 누르면 모름(None)
             for i, c in enumerate(profile.crops, 1)]
    safety = {who for who, name in (("owner", "safety_owner"), ("spouse", "safety_spouse")) if form.get(name) == "yes"}
    if profile.spouse == "none":
        safety.discard("spouse")
    dump = profile.model_dump()
    flags = dict(dump["flags"])
    edu = form.get("direct_payment_education")
    if already & DIRECT_PAY_KEYS:          # 직불을 받는 분에게는 교육 안내가 나가야 한다: 답이 없으면 아직 안 들은 것(N)
        if edu in EDUCATION_VALUES:
            flags["direct_payment_education"] = edu
        elif flags["direct_payment_education"] == "NA":
            flags["direct_payment_education"] = "N"
    updated = FarmProfile.model_validate({**dump, "flags": flags, "crops": crops, "already_receiving": already,
                                          "first_heard": heard, "ins_safety": safety})
    state = request.app.state
    match_supports(updated, state.tables.programs, state.cfg.as_of, crops=state.tables.crops)  # 돌아가는지 확인
    sid = state.sessions.put(request.cookies.get(COOKIE), profile=updated, printed=False)
    response = RedirectResponse("/counsel/working", status_code=303)
    set_session_cookie(response, sid)
    return response


@router.post("/new")
def new_counsel(request: Request, to: str | None = None) -> Response:
    """앞 사람 답을 지운다. to=home이면 첫 화면으로("처음으로"), 아니면 입력 화면으로("처음부터 다시")."""
    request.app.state.sessions.drop(request.cookies.get(COOKIE))
    response = RedirectResponse("/", status_code=303) if to == "home" else _to_input()
    response.delete_cookie(COOKIE, path="/")
    return response
