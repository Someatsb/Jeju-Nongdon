"""상담 화면 경로(Task 7, U07: 입력 부분).

GET  /counsel/input[?mode=proxy]  질문 화면(한 화면에 질문 하나: 2번 안의 둘째 작물 화면까지 6장, 마지막은 "해당되는 것만 눌러 주세요"). mode=proxy면 같은 화면에 머리말 "어르신을 대신해 답해 주세요".
POST /counsel/input[?mode=proxy]  막을 것이 있으면 같은 화면을 오류와 함께 다시 그린다(200).
                                  없으면 세션에 profile·proxy(대신 입력 표시)를 두고 /counsel/confirm으로 303(routes_confirm.py).
                                  문자 안내 칸(reminder_*)은 이 화면에 없다. 옛 주소로 와도 받지 않고 버린다(번호를 세션에 두지 않는다).
POST /counsel/reminder            결과 화면의 "마감 전에 문자로 알려 드릴까요?" 덮개가 보내는 곳. 번호·동의를 검사하고 바로 저장한다(JSON 답).
                                  번호는 로그·세션·AI 입력 어디에도 남기지 않는다(저장은 암호화 파일뿐).
폼 값은 로그에 쓰지 않는다.

종이(Task 21, U21):
GET /counsel/working               찾는 중 화면: 1~2초 넘김 뒤 /counsel/preview로 간다(바탕은 규칙 계산이라 바로 되고, 이 화면을 여는 때 AI 글 쓰기 뒤 작업을 띄운다).
GET /counsel/preview[?wait=1]      결과 화면(한 화면). 바탕(받을 지원·금액·가실 곳)만으로 바로 뜬다. AI 글 자리는 "설명을 쓰고 있어요…"로 두었다가 /counsel/ai 로 채운다.
                                   뒤 작업이 0.3초 안에 끝나면 처음부터 채워서 보낸다. wait=1 이면(스크립트가 꺼진 브라우저) 다 될 때까지(PRINT_BUDGET_S) 기다린 화면을 보낸다.
GET /counsel/ai                    JSON {"state": "run"|"done"|"failed", "fragments": {묶음 이름: HTML 조각 또는 글}, "match": {...}}. 쓰는 중에는 fragments 가 비어 있다.
                                   match = 새 공고 맞춰 보기(match_job.MatchJob.view): {"state": "run"|"done"|"none", "lines": [...], "more_names": [...], "note", "staff": {source, note, candidates, left_out, counts}}.
                                   staff 에는 개수와 한 줄뿐이다. 안 맞음 공고 이름·판정 근거는 서버 쪽 paper["match_staff"] 에만 있다.
                                   설명 글과 따로 끝난다(state 가 done 이어도 match.state 는 run 일 수 있다).
                                   묶음: sub(결론 아래 한 문장) · speak(소리로 듣기 글) · detail_ai(자세히 보기 안 설명) · staff(직원이 볼 내용).
                                   match_html = 맞춰 보기가 끝난 뒤에만 채워지는 조각 {new_notices(새로 나온 공고 상자) · match_alert(결론 띠 아래 알림 한 줄) · match_links(자세히 보기 공고 원문 줄)}.
                                   맞춰 보기가 도는 중이면 빈 {}. 어르신 칸 조각뿐이라 안 맞음 공고 이름은 없다.
GET /counsel/match-staff           직원이 볼 내용 칸의 새 공고 맞춰 보기 요약 JSON {"state", "html"}(판정별 이름·확인 기록). 어르신용 /counsel/ai 응답과 떼어 둔 직원 쪽 조각이다. 상담이 없으면 409.
                                   못 썼으면(failed) 조각은 기본 문장(없음)으로 채워진다. 상담이 없으면 409 {"state": "none"}.
                                   결과 화면 안: 위 띠(결론 한 줄) · 가실 곳별 카드 최대 셋 · 아래 띠(처음으로 · 문자로 알림 받기 · 자세히 보기 · "종이로 뽑기").
                                   "자세히 보기" 덮개 안에 올해는 어려운 것 · 창구 확인 · AI 설명 · 낱말 풀이 · 종이 크게 보기 · 접힌 "직원이 볼 내용"(AI가 한 일 3줄과 검수 표).
                                   인쇄한 뒤에는 "종이가 나왔습니다" 안내와 "처음으로".
GET /counsel/preview?view=screen   인쇄와 같은 종이 HTML에 화면용 확대 CSS(<style data-screen-zoom>) 한 덩이만 더한 것.
GET /counsel/print[?auto=1]        AI 글이 될 때까지 기다리고(PRINT_BUDGET_S 를 넘기면 기본 문장으로) 인쇄 전 검사(preflight)를 통과하면 종이 HTML(auto=1이면 열리자마자 인쇄 창). 걸리면 500이 아니라 200 "인쇄 보류" 화면과 사유.
GET /counsel/print-status          "1"이면 이 상담의 종이가 인쇄 검사를 통과해 나갔다(결과 화면이 돌아왔을 때 안내를 띄우는 근거).
세션이 없으면 입력 화면으로 303. 설명 문장은 app.state.narrator(없으면 비움)로 상담(프로필)마다 뒤 작업 하나가 한 번만 만든다.
"""
import json
import logging
import threading
import time
from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from app.agents.reviewer import ReviewOutcome
from app.catalog.links import LinkTableError, load_links
from app.core.pipeline import build_fact_sheet
from app.core.sheet import build_sheet
from app.data_layer import reminders, store
from app.ui import forms, match_job
from app.ui.preflight import REASONS, preflight
from app.ui.render import _narrative_slots, render_sheet
from app.ui.result_view import build_view
from app.ui.session import COOKIE, profile_session, set_session_cookie

log = logging.getLogger(__name__)
NARRATOR_LOCK = threading.Lock()   # 상담 사이에도 설명 만들기를 한 줄로 세운다(창구 한 자리라 일부러). 그리고 스레드풀에서 상담이 겹쳐도 검수 로그 구간(전·후 길이)이 다른 상담 기록과 섞이지 않게
router = APIRouter(prefix="/counsel")


def _official_links(state) -> Mapping[str, object]:
    """자세히 보기의 공고 보기·링크 복사하기가 쓰는 공식 원문 주소(data/catalog/links.csv). 표를 못 읽으면 단추 없이 보인다."""
    try:
        return load_links(state.cfg.catalog_dir / "links.csv")
    except LinkTableError as e:
        log.warning("원문 링크 표를 읽지 못해 링크 단추 없이 보여 줍니다: %s", e)
        return {}


NOT_SAVED = ("reminder_phone", "reminder_consent")     # 답 고치기로 되돌려 채울 때 문자 번호는 다시 쓰지 않는다(번호는 저장 뒤 지운다)


def _input_page(request: Request, *, proxy: bool, values: Mapping[str, str], errors: forms.FormErrors, start_step: int | None = None, edit: bool = False) -> Response:
    expired = request.app.state.sessions.was_expired(request.cookies.get(COOKIE))
    return request.app.state.templates.TemplateResponse(
        request, "input.html", {"proxy": proxy, "values": values, "errors": errors, "F": forms, "expired": expired,
                                    "start_step": start_step if start_step in (1, 2, 3, 4, 5, 6) else None, "edit": edit})


@router.get("/input", response_class=HTMLResponse)
def input_form(request: Request, mode: str | None = None, edit: str | None = None, step: int | None = None) -> Response:
    """edit=1(답 고치기·이전)이면 방금 낸 답을 채워서 보인다(세션에 없으면 빈 화면)."""
    session = profile_session(request) if edit else None
    if session is not None and session.get("form_values"):
        proxy = bool(session.get("proxy"))
        return _input_page(request, proxy=proxy, values=dict(session["form_values"]), errors=forms.FormErrors(), start_step=step, edit=True)
    proxy = mode == "proxy"
    return _input_page(request, proxy=proxy, values=forms.initial_values(proxy=proxy), errors=forms.FormErrors())


@router.post("/input", response_class=HTMLResponse)
async def submit_input(request: Request, mode: str | None = None) -> Response:
    proxy = mode == "proxy"
    values = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    # 문자 안내는 결과 화면에서 따로 받는다(POST /counsel/reminder). 옛 주소로 번호·동의가 와도 여기서는 버린다
    values = {k: v for k, v in values.items() if k not in NOT_SAVED}
    result = forms.to_profile(values, proxy=proxy)
    errors = forms.FormErrors(result if isinstance(result, forms.FormErrors) else {})
    if errors:
        return _input_page(request, proxy=proxy, values=values, errors=errors)
    sid = request.app.state.sessions.put(request.cookies.get(COOKIE), profile=result,
                                         reminder=None, proxy=proxy,
                                         counsel_id=None, reminder_saved=None,
                                         reminder_count=0, reminder_failed=False, reminder_none=False,   # 새 상담: 상담번호·문자 저장 표시를 비운다
                                         printed=False, form_values=dict(values))
    response = RedirectResponse("/counsel/confirm", status_code=303)
    set_session_cookie(response, sid)
    return response


# --- 종이: 미리보기·인쇄 ----------------------------------------------------------------------------

SCREEN_CSS = ("<style data-screen-zoom>@media screen { body { background: #e5e7eb; } .replay-line { display: none !important; } "
              ".sheet { zoom: 1.4; margin: 12px auto 0; } }"
              # 창이 좁으면 종이가 창 안에 다 들어오게 배율을 낮춘다(종이 폭 794px x 배율 + 여백 24px)
              "@media screen and (max-width: 1096px) { .sheet { zoom: 1.35; } } @media screen and (max-width: 1057px) { .sheet { zoom: 1.3; } } @media screen and (max-width: 1017px) { .sheet { zoom: 1.25; } } @media screen and (max-width: 977px) { .sheet { zoom: 1.2; } } @media screen and (max-width: 938px) { .sheet { zoom: 1.15; } } @media screen and (max-width: 898px) { .sheet { zoom: 1.1; } } @media screen and (max-width: 858px) { .sheet { zoom: 1.05; } } @media screen and (max-width: 818px) { .sheet { zoom: 1.0; } } @media screen and (max-width: 779px) { .sheet { zoom: 0.95; } } @media screen and (max-width: 739px) { .sheet { zoom: 0.9; } } @media screen and (max-width: 699px) { .sheet { zoom: 0.85; } } @media screen and (max-width: 660px) { .sheet { zoom: 0.8; } } @media screen and (max-width: 620px) { .sheet { zoom: 0.75; } } @media screen and (max-width: 580px) { .sheet { zoom: 0.7; } } @media screen and (max-width: 541px) { .sheet { zoom: 0.65; } } @media screen and (max-width: 501px) { .sheet { zoom: 0.6; } } @media screen and (max-width: 461px) { .sheet { zoom: 0.55; } } @media screen and (max-width: 421px) { .sheet { zoom: 0.5; } } @media screen and (max-width: 382px) { .sheet { zoom: 0.45; } } @media screen and (max-width: 342px) { .sheet { zoom: 0.4; } }</style>\n")
SECTION_LABEL = {"action": "다음에 하실 일", "support": "받으실 수 있는 돈", "insurance": "보험", "empty": "빈 종이"}
VERDICT_LABEL = {"REJECT": "반려", "PASS": "통과"}     # 검수 시도 줄의 판정 글자(재생 시연에서 반려→통과가 보인다)
SOURCE_LABEL = {"ai_pass": "AI 문장 통과", "template": "기본 문장(템플릿)"}
RULE_NAME = {"SCHEMA": "문장 형식", "LENGTH": "문장 길이", "NUM_DIGIT": "숫자를 씀", "NUM_SINO_UNIT": "숫자 단위(한자어)",
             "NUM_NATIVE_UNIT": "숫자 단위(고유어)", "NUM_WORD": "수량 표현", "FORECAST": "가격 전망", "CERTAINTY": "단정하는 말",
             "COMPARE": "상인·농협 견주기", "RIGHTS": "권리처럼 말함", "RAW_PROGRAM": "제도 이름을 그대로 씀",
             "NOT_IN_SHEET": "종이에 없는 제도", "NO_CITE": "근거가 없음", "BAD_CITE": "근거가 잘못됨",
             "UNSUPPORTED": "근거 없는 말", "WRONG_STATUS": "상태가 틀림", "OVERPROMISE": "과장"}   # 검수 규칙 코드 → 한글 이름(담당자용 접힌 칸)


def _to_input() -> Response:
    return RedirectResponse("/counsel/input", status_code=303)


class PaperError(Exception):
    """종이를 만들지 못함(표·계산 오류). 화면에는 일반 사유만 보이고 원인은 로그에 남긴다."""


AI_WAIT_S = 0.3          # 화면을 그릴 때 뒤 작업이 이만큼 안에 끝나면 처음부터 채워서 보낸다(재생·시험은 바로 끝난다)
PRINT_BUDGET_S = 45.0    # 인쇄·noscript 길이 AI 글을 기다리는 한도. 넘기면 기본 문장으로 간다
JOB_LOCK = threading.Lock()


class AiJob:
    """상담(프로필) 하나의 종이 묶음. 바탕(fs·sheet·기본 문장 종이)은 만들 때 바로 있고, AI 글과 그것이 든 종이는 뒤 작업이 채운다.

    state: "run"(쓰는 중) · "done"(됨, 또는 AI 글이 필요 없는 상담) · "failed"(못 씀: 기본 문장으로). 뒤 작업이 이 객체에만 쓰므로
    답을 고쳐 프로필이 바뀌면 새 AiJob 이 생기고 옛 작업의 결과는 새 상담에 섞이지 않는다.
    """

    def __init__(self, profile, fs, sheet, replay_msg, render=None) -> None:
        self.profile, self.fs, self.sheet, self.replay_msg = profile, fs, sheet, replay_msg
        self.render = render            # (설명 글, 새 공고 묶음) -> 종이 HTML 또는 None(검사에 걸림). 맞춰 보기가 끝난 뒤 새 공고 묶음이 든 종이를 그릴 때 쓴다
        self._with_match: dict[tuple, str | None] = {}
        self._render_lock = threading.Lock()
        self.state = "run"
        self.done = threading.Event()
        self.base: dict = {"profile": profile, "fs": fs, "html": "", "calendar3": sheet.front.calendar3, "sheet": sheet, "narr": {},
                           "outcomes": None, "rules": {}, "trail": {}, "replay_msg": replay_msg, "texts": None}
        self.result: dict | None = None
        self.match = match_job.MatchJob()      # 새 공고 맞춰 보기(설명 글과 나란히, 서로 기다리지 않는다). 인쇄에는 paper()["match"] 로 쓴다

    def finish(self, state: str, **ai) -> None:
        self.result = {**self.base, **ai}
        self.state = state
        self.done.set()

    def _match_html(self, src: dict, m: dict) -> str | None:
        """맞춰 보기가 끝나 어르신 화면에 보일 새 공고가 있으면 그 묶음이 든 종이 HTML, 아니면 None(지금 종이 그대로). 같은 내용은 한 번만 그린다."""
        if self.render is None or m["state"] != "done" or not (m["lines"] or m["more_names"]):
            return None
        key = (self.state, json.dumps([m["lines"], m["more_names"]], ensure_ascii=False, sort_keys=True))
        with self._render_lock:
            if key not in self._with_match:
                self._with_match[key] = self.render(src.get("texts"), {"lines": m["lines"], "more_names": m["more_names"]})
            return self._with_match[key]

    def paper(self) -> dict:
        """지금 쓸 수 있는 종이 묶음 {profile, fs, html, calendar3, sheet, narr, outcomes, rules, trail, replay_msg, texts, state, match, match_staff, match_links}.
        match 는 어르신 화면이 받는 응답(staff 는 개수·한 줄뿐), match_staff 는 직원이 볼 내용 칸 자료(안 맞음 공고 이름·판정 근거 포함)다.
        맞춰 보기가 끝나 보일 새 공고가 있으면 html 은 새로 나온 공고 묶음이 든 종이다(없으면 전과 글자 하나 다르지 않다)."""
        state, result = self.state, self.result
        src = result if state != "run" and result is not None else self.base
        m = self.match.view()
        out = {**src, "state": state, "match": m, "match_staff": self.match.staff_view(), "match_links": self.match.links()}
        html = self._match_html(src, m)
        if html is not None:
            out["html"] = html
        return out


def _render(state, job: AiJob, texts, match=None) -> str:
    return render_sheet(job.sheet, job.fs, texts, state.cfg, crop_labels={c.crop_code: c.label for c in state.tables.crops},
                        replay_line=state.replay_line, match=match, programs=state.tables.programs)


def _render_with_match(state, job: AiJob, texts, match) -> str | None:
    """새로 나온 공고 묶음이 든 종이. 인쇄 전 검사에 걸리면 None(이 묶음 없이 뽑는다: 새 공고 때문에 종이가 막히면 안 된다)."""
    try:
        html = _render(state, job, texts, match)
        codes = preflight(html, job.fs, state.cfg)
    except Exception:
        log.exception("새로 나온 공고 묶음이 든 종이를 만들지 못해 이 묶음 없이 뽑습니다")
        return None
    if codes:
        log.warning("새로 나온 공고 묶음이 든 종이가 검사에 걸려 이 묶음 없이 뽑습니다: %s", ",".join(codes))
        return None
    return html


def _run_job(state, job: AiJob) -> None:
    """뒤 작업(스레드): 설명 문장을 만들고 검사한 뒤 그것이 든 종이를 그린다. NARRATOR_LOCK·검수 로그 자르기는 예전 그대로."""
    narrative, rules, trail, ok = None, {}, {}, True
    try:
        entries = getattr(getattr(state, "review_log", None), "entries", None)
        with NARRATOR_LOCK:
            before = len(entries) if entries is not None else 0
            try:
                narrative = state.narrator(job.fs)
            except Exception:
                ok = False
                log.exception("설명 문장을 만들지 못해 설명 없이 인쇄합니다")
            for e in (entries[before:] if entries is not None else ()):
                rules.setdefault(e.get("section"), []).extend(c["rule"] for c in e.get("checks", ()))
                if e.get("attempt", 0) >= 1 and e.get("verdict") in VERDICT_LABEL:
                    trail.setdefault(e.get("section"), []).append(
                        {"attempt": e["attempt"], "verdict": VERDICT_LABEL[e["verdict"]], "injected": bool(e.get("injected"))})
        texts = narrative.texts() if narrative is not None else None
        html = _render(state, job, texts) if texts is not None else job.base["html"]
        job.finish("done" if ok else "failed", html=html, texts=texts, narr=_narrative_slots(texts),
                   outcomes=getattr(narrative, "sections", None), rules=rules, trail=trail)
    except Exception:
        log.exception("설명 문장이 든 종이를 만들지 못해 기본 문장으로 갑니다")
        job.finish("failed")


def _job(request: Request, session: dict) -> AiJob:
    """이 상담의 AiJob. 프로필이 그대로인 동안 하나만 만들고(두 번 띄우지 않는다) 프로필이 바뀌면 새로 만든다. 바탕을 못 만들면 PaperError."""
    with JOB_LOCK:
        job = session.get("job")
        if job is not None and job.profile is session["profile"]:
            return job
        state = request.app.state
        cfg, bundle = state.cfg, state.tables
        try:
            fs = build_fact_sheet(session["profile"], bundle, state.snapshot, cfg.as_of, state.data_version, demo_asof=cfg.demo_asof)
        except Exception as e:
            log.exception("FactSheet를 만들지 못했습니다")
            raise PaperError from e
        replay_msg = state.replay_check(fs) if state.replay_check is not None else None   # 재생 모드: 녹화와 다른 입력
        try:
            sheet = build_sheet(fs, bundle, cfg.as_of)
            sheet = sheet.model_copy(update={"back": sheet.back.model_copy(update={"fingerprint_slot": f"계산 지문 {fs.fingerprint}"})})
            job = AiJob(session["profile"], fs, sheet, replay_msg)
            job.render = lambda texts, match, _job=job: _render_with_match(request.app.state, _job, texts, match)
            job.base["html"] = _render(state, job, None)
        except Exception as e:
            log.exception("종이를 그리지 못했습니다")
            raise PaperError from e
        try:
            pool = match_job.pool_for(request)
        except Exception:
            log.exception("맞춰 볼 새 공고를 고르지 못해 맞춰 보기를 건너뜁니다")
            pool = []
        match_job.launch(job.match, getattr(state, "matcher", None), session["profile"], fs, pool)     # 설명 글과 나란히 돈다
        if state.narrator is None or replay_msg is not None:      # AI 글이 필요 없는 상담: 바탕이 곧 종이
            job.finish("done")
        else:
            threading.Thread(target=_run_job, args=(state, job), name="ai-job", daemon=True).start()
        state.sessions.put(request.cookies.get(COOKIE), job=job)
        return job


def _paper(request: Request, session: dict, wait: float = 0.0) -> dict:
    """상담 하나의 종이 묶음. 바탕은 바로 있고, AI 글이 아직이면 wait 초까지만 기다린 뒤 있는 대로(기본 문장 종이) 돌려준다(paper["state"] == "run")."""
    job = _job(request, session)
    if wait > 0:        # 설명 글과 맞춰 보기를 같은 한도 안에서 함께 기다린다(따로 더 기다리지 않는다). 끝내 안 끝나면 있는 대로(그 묶음 없이)
        end = time.monotonic() + wait
        if job.state == "run":
            job.done.wait(wait)
        job.match.done.wait(max(0.0, end - time.monotonic()))
    return job.paper()


def _review_rows(paper: dict) -> list[dict]:
    """검수 과정 보기 표: 구획마다 (이름, 시도 횟수, 걸린 규칙 코드, 최종 출처). 이 상담에서 걸린 규칙만 보인다."""
    outcomes: Mapping[str, ReviewOutcome] | None = paper["outcomes"]
    if not outcomes:
        return []
    return [{"name": SECTION_LABEL.get(kind, kind), "attempts": o.attempts, "source": SOURCE_LABEL.get(o.source, o.source),
             "rules": [RULE_NAME.get(r, "그 밖의 규칙") for r in dict.fromkeys(paper["rules"].get(kind, ()))],
             "trail": paper["trail"].get(kind, [])}
            for kind, o in outcomes.items()]


def _ai_steps(request: Request, paper: dict, codes: list[str]) -> list[str]:
    """결과 화면 "AI가 한 일" 세 줄(어르신 말). 숫자·상태는 이 상담의 실제 값에서 온다."""
    outcomes = paper["outcomes"] or {}
    sources = [o.source for o in outcomes.values()]
    if sources and all(s == "ai_pass" for s in sources):
        second = "AI가 쉬운 말로 설명 문장을 썼어요"
    elif "ai_pass" in sources:
        second = "AI가 쉬운 말로 설명 문장을 썼어요(일부는 미리 써 둔 기본 문장)"
    else:
        second = "설명 문장은 미리 써 둔 기본 문장을 썼어요"
    n = len({m.program_key for m in paper["fs"].matches})
    third = ("숫자와 지원 이름이 틀리지 않았는지 검사했고 통과했어요" if not codes
             else "종이 검사에서 걸린 곳이 있어요. 직원에게 알려 주세요")
    return [f"지원 {n}가지의 조건과 하나씩 맞춰 봤어요", second, third]


def _hold(request: Request, reasons: list[tuple[str, str]]) -> Response:
    return request.app.state.templates.TemplateResponse(request, "print_hold.html", {"reasons": reasons})


BUILD_FAILED = ("BUILD_FAILED", "종이를 만들지 못했어요. 직원에게 알려 주세요.")


@router.get("/working", response_class=HTMLResponse)
def working(request: Request) -> Response:
    """찾는 중 화면: 1~2초 넘김. 같은 상담에서 뒤 작업은 한 번만 뜬다."""
    session = profile_session(request)
    if session is None:
        return _to_input()
    try:
        _job(request, session)      # 바탕을 만들고 AI 글 뒤 작업을 띄운다(이 화면은 기다리지 않는다)
    except PaperError:
        pass                        # 결과 화면이 같은 오류를 쉬운 말로 보인다
    return request.app.state.templates.TemplateResponse(request, "working.html", {})


@router.get("/preview", response_class=HTMLResponse)
def preview(request: Request, view: str | None = None, wait: str | None = None) -> Response:
    session = profile_session(request)
    if session is None:
        return _to_input()
    try:
        paper = _paper(request, session, PRINT_BUDGET_S if wait else AI_WAIT_S)
    except PaperError:
        return _hold(request, [BUILD_FAILED])
    if view == "screen":
        return HTMLResponse(paper["html"].replace("</head>", SCREEN_CSS + "</head>", 1))
    state = request.app.state
    codes = preflight(paper["html"], paper["fs"], state.cfg)
    return state.templates.TemplateResponse(request, "result.html", {
        "review_rows": _review_rows(paper), "fingerprint": paper["fs"].fingerprint,
        "replay_msg": paper["replay_msg"], "reminder_line": _reminder_line(session), "reminder_saved": bool(session.get("reminder_saved")),
        "reminder_sid": _reminder_sid(session), "consent_lines": forms.CONSENT_LINES,
        "v": build_view(paper["sheet"], paper["fs"], state.tables, state.cfg.as_of, paper["narr"], links=_official_links(state), screen=True),
        "ai_steps": _ai_steps(request, paper, codes), "printed": bool(session.get("printed")), "ai_pending": paper["state"] == "run",
        "m": paper["match"], "ms": paper["match_staff"], "match_links": paper["match_links"], "nn_show": _nn_visible(paper["match"])})


@router.get("/print", response_class=HTMLResponse)
def print_sheet(request: Request, auto: str | None = None) -> Response:
    session = profile_session(request)
    if session is None:
        return _to_input()
    try:
        paper = _paper(request, session, PRINT_BUDGET_S)    # AI 글을 기다리되 한도를 넘기면 기본 문장으로 뽑는다
    except PaperError:
        return _hold(request, [BUILD_FAILED])
    codes = preflight(paper["html"], paper["fs"], request.app.state.cfg)
    if codes:
        return _hold(request, [(c, REASONS.get(c, c)) for c in codes])
    request.app.state.sessions.put(request.cookies.get(COOKIE), printed=True)
    html = paper["html"]
    if auto:      # 결과 화면의 "종이로 뽑기": 새 탭이 열리자마자 인쇄 창을 띄운다(검사를 통과한 종이에만)
        html = html.replace("</body>", AUTO_PRINT + "</body>", 1)
    return HTMLResponse(html)


def _store_reminder(request: Request, session: dict, paper: dict, req: forms.ReminderRequest) -> None:
    """재방문 문자를 저장하고 결과를 세션의 reminder_saved·reminder_count·reminder_failed에 둔다. 실패해도 화면은 그대로 간다.

    번호는 이 함수의 인자로만 오가고 세션·로그에는 두지 않는다. 저장된 것은 암호화 파일뿐이다.
    상담번호(counsel_id)는 상담당 하나다(다시 신청하면 같은 파일을 새 번호로 덮어쓴다).
    """
    state = request.app.state
    sid = session.get("counsel_id") or store.new_session(state.cfg.as_of)
    count, failed = 0, False
    try:
        count = reminders.save(sid, req, paper["calendar3"], state.cfg.as_of, bundle=state.tables,
                               center_phone=state.cfg.center_phone)
    except (OSError, NotImplementedError):
        failed = True
        log.exception("재방문 문자를 저장하지 못했습니다")
    state.sessions.put(request.cookies.get(COOKIE), counsel_id=sid, reminder_saved=count > 0, reminder_count=count,
                       reminder_failed=failed, reminder_none=(count == 0 and not failed))


AUTO_PRINT = ("<style>@media screen { .replay-line { display: none !important; } body { padding-bottom: 110px; } }"
              " @media print { .print-back { display: none !important; } }"
              " .print-back { position: fixed; left: 0; right: 0; bottom: 0; background: #fff; border-top: 4px solid #2B2724; padding: 14px; text-align: center; z-index: 99; }"
              " .print-back button { font: 800 32px 'Pretendard', 'Malgun Gothic', sans-serif; padding: 16px 48px; border-radius: 18px; border: 4px solid #2B2724; background: #fff; color: #2B2724; cursor: pointer; }</style>"
              "<div class=\"print-back\"><button type=\"button\" onclick=\"window.close()\">이 화면을 닫고 돌아가기</button></div>"
              "<script>window.addEventListener('load', function () { setTimeout(function () { window.print(); }, 400); });"
              " window.addEventListener('afterprint', function () { setTimeout(function () { window.close(); }, 600); });</script>")


@router.get("/print-status", response_class=PlainTextResponse)
def print_status(request: Request) -> Response:
    """결과 화면이 인쇄 탭에서 돌아왔을 때 읽는 곳: "1"이면 종이가 나갔다."""
    session = profile_session(request)
    return PlainTextResponse("1" if session and session.get("printed") else "0", headers={"Cache-Control": "no-store"})


NO_SLOT_LINE = "이 종이에는 문자로 알려 드릴 시기가 없어서 번호를 저장하지 않았어요"
SAVE_FAILED_LINE = "문자 알림 번호를 저장하지 못했어요. 직원이 적어 드릴게요"


def _reminder_sid(session: dict) -> str:
    """직원용 상담번호(저장된 번호를 나중에 지울 때 쓴다). 어르신 화면의 저장 확인 글에는 싣지 않고 '직원이 볼 내용' 칸에만 둔다."""
    return str(session.get("counsel_id") or "") if session.get("reminder_saved") else ""


def _reminder_line(session: dict) -> str:
    """문자 안내 저장 결과 한 줄(번호는 싣지 않는다). 아직 인쇄 전이거나 요청이 없으면 빈 문자열."""
    if session.get("reminder_failed"):
        return SAVE_FAILED_LINE
    if session.get("reminder_saved"):
        return f"문자 알림을 {session.get('reminder_count', 1)}개 저장했어요"
    if session.get("reminder_none"):
        return NO_SLOT_LINE
    return ""


@router.get("/reminder-status", response_class=PlainTextResponse)
def reminder_status(request: Request) -> Response:
    """미리보기 화면이 인쇄 뒤에 저장 결과 줄을 다시 읽는 곳."""
    session = profile_session(request)
    return PlainTextResponse(_reminder_line(session) if session else "", headers={"Cache-Control": "no-store"})


@router.post("/reminder")
async def submit_reminder(request: Request) -> Response:
    """결과 화면 덮개의 "신청하기". 번호(숫자판으로 넣은 숫자 11자리도 됨)와 동의를 지금 규칙(forms.reminder_errors)대로 검사해
    바로 저장하고 JSON {ok, line, errors}로 답한다. 번호가 없거나 동의가 없으면 저장하지 않는다. 번호는 로그에 쓰지 않는다."""
    session = profile_session(request)
    if session is None:
        return JSONResponse({"ok": False, "line": "상담이 끝났어요. 처음부터 다시 해 주세요.", "errors": {}}, status_code=409)
    form = forms.phone_from_digits({k: v for k, v in (await request.form()).items() if isinstance(v, str)})
    errors = forms.reminder_errors(form)
    if not errors and not form.get("reminder_phone", "").strip():
        errors = forms.FormErrors({"reminder_phone": "휴대폰 번호를 눌러 주세요."})
    if errors:
        if "reminder_consent" in errors:      # 화면에서는 동의 단추를 누르라는 말로 보인다
            errors["reminder_consent"] = "동의하시면 위 단추를 눌러 주세요. 안 하시면 '닫기'를 눌러 주세요."
        return JSONResponse({"ok": False, "line": "", "errors": dict(errors)})
    try:
        paper = _paper(request, session)
    except PaperError:
        return JSONResponse({"ok": False, "line": "지금은 저장하지 못했어요. 직원에게 말씀해 주세요.", "errors": {}})
    _store_reminder(request, session, paper, forms.to_reminder(form))
    after = profile_session(request) or {}
    return JSONResponse({"ok": bool(after.get("reminder_saved")), "line": _reminder_line(after), "sid": _reminder_sid(after), "errors": {}},
                        headers={"Cache-Control": "no-store"})


AI_SLOTS = ("sub", "speak", "detail_ai", "staff")     # 결과 화면의 "AI 글 자리" 이름. 새 묶음은 여기에 이름을 더하고 아래 조각 만드는 곳에서 채운다(맞춰 보기 조각은 따로 끝나므로 MATCH_SLOTS)
MATCH_SLOTS = ("new_notices", "match_alert", "match_links")     # 새 공고 맞춰 보기가 끝난 뒤에만 채우는 자리(어르신 칸 조각. 직원 칸은 /counsel/match-staff)


def _nn_visible(m: Mapping) -> bool:
    """지금 접수 중인 공고 자리가 보이는가: 도는 중(작은 한 줄)이거나, 끝났고 맞을 수 있는 공고(줄)가 있을 때."""
    return m["state"] == "run" or (m["state"] == "done" and bool(m["lines"]))


def match_fragments(request: Request, paper: dict) -> dict[str, str]:
    """맞춰 보기가 끝났을 때 결과 화면 자리마다 채울 조각(어르신 칸). 도는 중이면 비어 있다. 보일 것이 없으면 자리 이름마다 빈 글."""
    m = paper["match"]
    if m["state"] == "run":
        return {}
    env = request.app.state.templates.env
    box = env.get_template("_new_notices.html").render({"m": m}) if _nn_visible(m) else ""
    return {"new_notices": box, "match_alert": env.get_template("_match_alert.html").render({"m": m}),
            "match_links": env.get_template("_match_links.html").render({"links": paper["match_links"]})}


def ai_fragments(request: Request, session: dict, paper: dict) -> dict[str, str]:
    """AI 글이 다 됐을 때 결과 화면 자리마다 채울 조각. sub·speak 는 글, 나머지는 HTML. 비어 있으면 자리를 접는다."""
    state = request.app.state
    codes = preflight(paper["html"], paper["fs"], state.cfg)
    v = build_view(paper["sheet"], paper["fs"], state.tables, state.cfg.as_of, paper["narr"], screen=True)
    ctx = {"d": v["detail"], "review_rows": _review_rows(paper), "fingerprint": paper["fs"].fingerprint,
           "replay_msg": paper["replay_msg"], "ai_steps": _ai_steps(request, paper, codes), "ai_pending": False}
    env = state.templates.env
    return {"sub": v["sub"] or "", "speak": v["speak"],
            "detail_ai": env.get_template("_ai_detail.html").render(ctx),
            "staff": env.get_template("_ai_staff.html").render(ctx)}


@router.get("/ai")
def ai_status(request: Request) -> Response:
    """결과 화면이 1초마다 묻는 곳: AI 글 쓰기 상태와 다 되면 채울 조각(묶음 이름 → 조각). 기다리지 않고 바로 답한다."""
    headers = {"Cache-Control": "no-store"}
    session = profile_session(request)
    if session is None:
        return JSONResponse({"state": "none", "fragments": {}}, status_code=409, headers=headers)
    try:
        paper = _paper(request, session)
    except PaperError:
        return JSONResponse({"state": "failed", "fragments": {}, "match": match_job.none_view(), "match_html": {}}, headers=headers)
    mh = match_fragments(request, paper)
    if paper["state"] == "run":
        return JSONResponse({"state": "run", "fragments": {}, "match": paper["match"], "match_html": mh}, headers=headers)
    return JSONResponse({"state": paper["state"], "fragments": ai_fragments(request, session, paper), "match": paper["match"], "match_html": mh}, headers=headers)


@router.get("/match-staff")
def match_staff(request: Request) -> Response:
    """직원이 볼 내용 칸의 새 공고 맞춰 보기 요약. 어르신 화면이 받는 /counsel/ai 와 따로 둔다(안 맞음 공고 이름·확인 기록이 들어 있다). 도는 중이면 {"state": "run", "html": ""}."""
    headers = {"Cache-Control": "no-store"}
    session = profile_session(request)
    if session is None:
        return JSONResponse({"state": "none", "html": ""}, status_code=409, headers=headers)
    try:
        paper = _paper(request, session)
    except PaperError:
        return JSONResponse({"state": "none", "html": ""}, headers=headers)
    m = paper["match"]
    if m["state"] == "run":
        return JSONResponse({"state": "run", "html": ""}, headers=headers)
    html = request.app.state.templates.env.get_template("_match_staff.html").render({"m": m, "ms": paper["match_staff"]})
    return JSONResponse({"state": m["state"], "html": html}, headers=headers)
