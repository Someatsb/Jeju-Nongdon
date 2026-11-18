"""종이 글자 규칙(Task 15): 줄 길이 맞추기, 날짜·금액·배지 글자, 고정 문장. Line 모델은 sheet.py가 갖는다.

줄 길이 상한(한 줄에 찍을 수 있는 글자 수): 22pt 24자 / 18pt 26자 / 16pt 30자 / 14pt 36자 / 13pt 40자.
글자는 모두 표·판정에서 온 값을 끼워 넣을 뿐이고, 숫자를 새로 만들지 않는다(금액은 fmt_won).
"""
from datetime import date
from typing import Literal

from app.core.models import AmountLine, ApplyWindow, Program, RowStatus
from app.core.units import fmt_won
from app.core.when_text import ALWAYS, ASK_WHEN, month_when_of

Pt = Literal[22, 18, 16, 14, 13]
LIMIT: dict[int, int] = {22: 24, 18: 26, 16: 30, 14: 36, 13: 40}
SIZES: tuple[Pt, ...] = (22, 18, 16, 14, 13)

CHECK_TAG = "확인할 조건 있음"
EMPTY_TITLE = "다 챙기고 계세요"
BRING_TEXT = "가실 때: 이 종이와 신분증 · 필요한 서류는 창구에서 알려 줘요"
FARM_HELPER_TEXT = "영농도우미: 다치거나 3일 넘게 입원하면 60일 안에 농협에 신청하세요"
DISASTER_ASK_TEXT = "재해 피해는 꼭 말씀해 주세요"
DISCLAIMER = ("이 종이를 뽑아 준 곳: 제주빅데이터센터 창구 · 궁금한 점도 그곳에",
              "공문서가 아니에요 · 신청과 결정은 해당 기관이 해요",
              "금액은 약·범위·최대 기준이에요 · 공고가 바뀌면 달라질 수 있어요")
PREREQ_MONEY = "조건이 맞으면"      # 먼저 하실 일 줄이 받을 돈을 말하는 글의 앞말(화면·종이가 이 앞말로 줄을 알아본다)
MGMT_PHONE = "농관원 1644-8778"   # 경영체 등록 창구(골든 P4)

TRIGGER_WORD = {"MET": "열림", "MET_ESTIMATED": "열림(추정)", "NEAR": "곧 열릴 수 있음", "NOT_MET": "아직",
                "OUT_OF_SEASON": "시즌 전", "STALE": "자료 오래됨", "NO_DATA": "자료 오래됨"}
RULE_LABEL = {"PRICE_STAB": "가격안정관리제", "LOGISTICS": "물류비 지원", "ISOLATION_HISTORY": "수매·격리 이력"}
FIELD_LABEL = {"min_age": "나이", "max_age": "나이", "sex": "성별", "min_ha": "면적", "max_ha": "면적",
               "max_owned_ha": "소유 면적", "owns_land": "땅 소유", "crop_in": "작물", "crop_not_in": "작물",
               "facility": "재배 형태", "region_in": "지역", "area_type_in": "지역", "health_ins_in": "건강보험",
               "min_residence_years": "거주 기간", "min_farming_years": "영농 햇수", "land_hold_years": "땅 보유 기간",
               "born_before": "나이", "born_after": "나이", "event_type": "재해·사고 여부",
               "needs_mgmt": "경영체 등록", "min_mgmt_years": "경영체 등록 햇수", "needs_enrollment": "참여 신청",
               "needs_cert": "인증", "income_test": "소득 기준", "needs_coop": "농협 출하", "needs_selfpay_fund": "자조금 가입",
               "rent_all": "임차"}
UNIT_OF = {"min_ha": "ha", "max_ha": "ha", "max_owned_ha": "ha", "min_residence_years": "년", "min_farming_years": "년",
           "min_mgmt_years": "년", "land_hold_years": "년", "min_age": "세", "max_age": "세", "income_test": "만 원"}
KEY_NOTE = {"NAT-DIRECT-ANY": "직불금(어떤 직불인지 모름)"}   # R1 [받고 있음]에만 있고 표에는 없는 칸
YN_LABEL = {"Y": "예", "N": "아니오", "NA": "해당 없음", "E": "둘 중 하나"}
# 코드값 → 한글(뒷면 입력 요약·조건표). 칸마다 같은 코드(none 등)가 다른 뜻이라 칸별로 둔다.
VALUE_LABEL: dict[str, dict[str, str]] = {
    "mgmt_status": {"over_2y": "2년 이상 등록", "under_2y": "2년 미만 등록", "none": "등록 안 함", "unknown": "모름"},
    "land_tenure": {"own_all": "전부 내 땅", "own_part": "일부 내 땅", "rent_all": "임차", "unknown": "모름"},
    "health_ins": {"regional": "지역가입자", "dependent": "피부양자", "employee": "직장가입자", "unknown": "모름"},
    "spouse": {"registered": "경영체에 등록", "cofarming_unregistered": "함께 짓지만 미등록", "none": "없음"},
    "selfpay_fund": {"paid": "가입", "not_paid": "미가입", "unknown": "모름", "na": "해당 없음"},
    "sales_channel": {"coop": "농협 출하", "field_contract_done": "밭떼기 계약", "merchant_planned": "상인 판매 예정",
                      "direct": "직접 판매", "unknown": "모름"}}


def fit(text: str, pt: int) -> tuple[str, Pt]:
    """pt 이하의 크기 중 text가 한 줄에 들어가는 가장 큰 것. 13pt에도 넘으면 줄여서 '…'."""
    for size in SIZES:
        if size <= pt and len(text) <= LIMIT[size]:
            return text, size
    return text[:LIMIT[13] - 1] + "…", 13


def md(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def amount_text(a: AmountLine | None) -> str | None:
    """금액 글자. 금액이 없거나 공개 안 된 줄은 None."""
    if a is None or a.kind == "UNDISCLOSED" or (a.low_won is None and a.high_won is None):
        return None
    body = fmt_won(a.low_won, a.high_won)
    return {"REFERENCE_LAST_SEASON": "작년 ", "PER_KG_TRIGGER": "열리면 "}.get(a.kind, "") + body


def notice_badge(status: RowStatus | None, month: int | None, as_of: date) -> str | None:
    """작년 공고 기준 행의 배지. 달을 모르면 '공고 시기 확인'. 공고 달이 올해 아직 앞(또는 이번 달)이면 '올해 공고 전', 지났으면 내년."""
    if status != "prior_year_reference":
        return None
    tail = f"{month}월 확인" if month else "공고 시기 확인"
    notice = as_of.year if month and as_of.month <= month else as_of.year + 1     # 올해 공고 달이 아직 앞이면 올해 공고 전
    return f"{notice - 1}년 기준 · {notice}년 공고 전 · {tail}"


def window_text(w: ApplyWindow, status: RowStatus, as_of: date) -> str:
    """신청 시기 글자. 작년 공고 기준이면 날짜 대신 기준일에서 본 '내년 3월쯤'(올해 안이면 '올해 12월쯤')."""
    if w.always_open:
        return ALWAYS
    first = w.first_date
    if w.open_now and status != "prior_year_reference":
        return "지금 신청할 수 있어요" + (f" · {md(w.next_end)}까지" if w.next_end else "")
    if first is None:
        return ASK_WHEN
    if status == "prior_year_reference":
        return "지금도 신청할 수 있어요" if w.open_now else month_when_of(first, as_of)
    return f"{md(first)}부터" if w.next_start else f"{md(first)}까지"


def first_segment(manual_check: str | None) -> str | None:
    """manual_check의 첫 토막(' / '로 나뉜 것). 표 글자 그대로."""
    return manual_check.split(" / ")[0].strip() if manual_check else None


def join(*parts: str | None) -> str | None:
    kept = [p for p in parts if p]
    return " · ".join(kept) if kept else None


def program_label(p: Program) -> str:
    return p.name or p.program_key
