"""지원 전체 보기: GET /supports(목록), GET /supports/{제도}(지원 안내).

자료는 app.catalog 가 만든다(표의 지원을 제도로 묶고, 공고 에이전트가 읽은 새 공고를 더한 것). 이 파일은 그것을 화면으로 잇기만 하고
숫자·날짜·금액을 새로 만들지 않는다. 기준일은 첫 화면의 마감 카드와 같다(시연 기준일로 띄워도 실제 오늘로 센다).
없는 제도 주소는 쉬운 오류 화면(404)으로 보낸다.
"""
import logging
import os
from datetime import date

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from app.catalog import Catalog, LinkTableError, build_catalog, load_links, load_notices
from app.catalog.layout import FOCUS_WORDS, glance, groups_of, is_legal, split_legal, variant_table
from app.catalog.texts import PRIOR_NOTE
from app.config import today_fn
from app.ui.check_items import classify

log = logging.getLogger(__name__)
router = APIRouter()

# 원문 링크 단추 글(link_kind 별). 새 창으로 열리는 것을 모든 단추 아래에 안내한다.
LINK_LABEL = {"공고 원문": "공고문 보기", "사업 안내": "안내 페이지 보기", "신청 안내(정부24)": "신청 안내 보기(정부24)",
              "통합 공고": "공고문 보기"}
NEW_WINDOW_NOTE = "새 창이 열려요. 다 보시면 그 창을 닫으세요"
NO_LINK_NOTE = "인터넷 안내가 없어요. 위에 적힌 곳에 물어보세요"
FROM_RESULT = "result"                                           # 주소 표시 ?from=result: 결과 화면의 새로 나온 공고 줄에서 왔다
RESULT_BACK = "/counsel/preview#new-notices"                      # 돌아가는 곳: 결과 화면(상담은 세션에 그대로 있다)의 새로 나온 공고 상자
NEW_NOTICE_WARN = "AI가 공고에서 읽은 내용이에요. 금액과 자격은 따지지 않았으니 자세한 조건은 창구에 물어보세요"


def check_say(piece: str) -> str:
    """안내 화면 '창구에서 확인하실 것'의 조각 하나. 어르신이 네/아니요로 답할 수 있는 조각은 같이 확인해요 표(check_items.csv)의 쉬운 말로, 그 밖의 조각은 표 글자 그대로."""
    kind, easy = classify(piece)
    return easy if kind == "ask" and easy else piece


def today_of(request: Request) -> date:
    """첫 화면·지원 전체 보기·맞춰 보기 공고 고르기가 함께 쓰는 '오늘'.
    체험(재생) 모드(--replay)는 상담 기준일(--asof)로 센다. 며칠 뒤에 열어도 화면이 설명서·보고서와 같고 맞춰 보기 녹화(M-P)가 맞는다.
    그 밖의 시연 기준일 서버는 실제 오늘, 실제 모드(기준일 없음)는 cfg.as_of(= 실제 오늘).
    시연 서버에서만 환경 변수 JEJU_SHOW_TODAY=YYYY-MM-DD 가 먼저다(급한 남은 날 표시를 보여 주려고). 읽을 수 없는 값은 무시한다."""
    cfg = request.app.state.cfg
    if not cfg.demo_asof:
        return cfg.as_of
    try:
        return date.fromisoformat(os.environ["JEJU_SHOW_TODAY"].strip())
    except (KeyError, ValueError):
        return cfg.as_of if cfg.replay else today_fn()


def load_catalog_for(request: Request, today: date | None = None) -> Catalog:
    """요청마다 새로 만든다(약 2ms). 공고를 새로 읽어 폴더에 올라오면 바로 목록에 보인다."""
    st = request.app.state
    cdir = st.cfg.catalog_dir
    try:
        links = load_links(cdir / "links.csv")
    except LinkTableError as e:
        log.warning("원문 링크 표를 읽지 못해 링크 없이 보여 줍니다: %s", e)
        links = {}
    return build_catalog(st.tables, today or today_of(request), links, load_notices(cdir / "notices"))


def staff_line(catalog: Catalog) -> str:
    """직원 메뉴 한 줄: 표 ○가지 · 새 공고 ○건(마지막으로 읽은 날 ○)."""
    notices = [e for e in catalog.entries if e.kind == "notice"]
    tables = len(catalog.entries) - len(notices)
    if not notices:
        return f"표 {tables}가지 · AI가 읽은 공고 0건"
    last = max(e.verified_date for e in notices)
    if last > catalog.as_of:         # 시연 기준일보다 뒤에 읽은 공고가 든 자료: 기준일보다 앞선 날짜로 읽을 수 없으니 날짜를 적지 않고 시연 자료라고 밝힌다
        return f"표 {tables}가지 · AI가 읽은 공고 {len(notices)}건(시연 자료)"
    return f"표 {tables}가지 · AI가 읽은 공고 {len(notices)}건(마지막으로 읽은 날 {last.month}월 {last.day}일)"


@router.get("/supports", response_class=HTMLResponse)
def supports_list(request: Request, f: str | None = None) -> Response:
    st = request.app.state
    catalog = load_catalog_for(request)
    known = {x.id for x in catalog.filters()}
    current = f if f in known else "all"
    entries = catalog.select(current)
    focus = current if current in FOCUS_WORDS else None          # 감귤 걸러 보기: 작물마다 기간이 다른 제도는 감귤 줄의 기간으로 보인다
    return st.templates.TemplateResponse(request, "supports.html", {
        "catalog": catalog, "filters": catalog.filters(), "current": current, "entries": entries, "groups": groups_of(entries, focus, catalog.as_of),
        "qs": "" if current == "all" else f"?f={current}",           # 줄을 눌러 간 안내에서 '목록으로'가 보던 걸러 보기로 돌아오게
        "has_new": any(e.kind == "notice" for e in entries),
        "as_of_md": f"{catalog.as_of.month}월 {catalog.as_of.day}일"})


@router.get("/supports/{key}", response_class=HTMLResponse)
def support_page(request: Request, key: str, f: str | None = None, from_: str | None = Query(None, alias="from")) -> Response:
    st = request.app.state
    catalog = load_catalog_for(request)
    entry = catalog.get(key)
    if entry is None:
        return st.templates.TemplateResponse(request, "error.html", {}, status_code=404)
    link_label = LINK_LABEL.get(entry.link.kind, "원문 보기") if entry.link else ""
    known = {x.id for x in catalog.filters()} - {"all"}
    shown = f if f in known else None                            # 목록에서 걸러 보다 온 길: '목록으로'가 그리로 돌아가고, 감귤이면 감귤 줄을 먼저 보인다
    focus = shown if shown in FOCUS_WORDS else None
    plain, legal = split_legal(entry.new_target_lines)
    from_result = from_ == FROM_RESULT                           # 결과 화면의 "새로 나온 공고"에서 왔다: '목록으로' 자리에 '결과로 돌아가기'(다른 값은 무시)
    return st.templates.TemplateResponse(request, "support.html", {
        "e": entry, "cells": glance(entry, focus), "vtable": variant_table(entry, focus) if entry.kind == "table" else None,
        "back_href": RESULT_BACK if from_result else (f"/supports?f={shown}" if shown else "/supports"),
        "back_label": "결과로 돌아가기" if from_result else "목록으로",
        "link_label": link_label, "new_window_note": NEW_WINDOW_NOTE, "no_link_note": NO_LINK_NOTE,
        "new_warn": NEW_NOTICE_WARN, "checks": [check_say(c) for c in entry.checks], "target_plain": plain, "target_legal": legal, "is_legal": is_legal, "prior_note": PRIOR_NOTE})
