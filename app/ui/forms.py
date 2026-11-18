"""입력 화면 폼 → FarmProfile·문자 안내 요청(Task 7, U07).

- 칸 이름은 FarmProfile 필드 이름이다. 작물은 crop1_*·crop2_*, 면적은 평으로 받아 *_area_py로 쓴다.
  flags의 두 값은 disaster_damage·direct_payment_education 칸으로 펼쳐 받는다.
- 항목 순서·선택지 문구·"모르면" 처리는 research/dept/round2-A-service.md §1-1 입력 표 그대로다.
  답을 안 고른 항목은 그 표의 "모르면" 칸 값으로 두고 막지 않는다. 막는 것은 읍면동·작물 누락, 목록 밖 값,
  면적 0 이하·30ha 초과, 태어난 해 1900~2010 밖, 총면적 < 작물 합, 문자 번호 형식·동의 누락뿐이다.
- 입력 표에는 있지만 FarmProfile에 담을 칸이 없어 묻지 않는 것: 8번 배우자 태어난 해·성별,
  12번 가격안정관리제 "참여 신청"(코어 모델에 필드가 생기면 더한다).
- 문자 안내 두 칸(reminder_phone·reminder_consent)은 FarmProfile에 넣지 않는다. to_profile은 무시하고
  to_reminder가 따로 뽑는다. 번호는 로그·LLM 입력에 넣지 않는다(이 파일은 로그를 쓰지 않는다).
"""
import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import MAX_AREA_M2, FarmProfile, ReminderRequest   # ReminderRequest는 core.models로 옮겼다(여기서도 그대로 쓸 수 있게 다시 내보낸다)

# 1평 = 3.3058㎡(반올림). app/core/units.py(Task 4)의 py_to_m2와 같은 값·같은 식이다.
# 이 작업 트리에는 그 파일이 없어 여기 두었다. 레인을 합칠 때 그쪽 py_to_m2로 바꾼다.
PYEONG_M2 = Decimal("3.3058")


def py_to_m2(py: int) -> int:
    """평 → ㎡(반올림). 1,500평 → 4,959㎡."""
    return int((Decimal(py) * PYEONG_M2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- 목록 ----------------------------------------------------------------------------------------

# 1번 읍면동 43곳(제주시 4읍 3면 19동, 서귀포시 3읍 2면 12동). emd_code는 이 이름 문자열이다.
EMD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("제주시", ("한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "추자면", "우도면",
              "일도1동", "일도2동", "이도1동", "이도2동", "삼도1동", "삼도2동", "용담1동", "용담2동", "건입동",
              "화북동", "삼양동", "봉개동", "아라동", "오라동", "연동", "노형동", "외도동", "이호동", "도두동")),
    ("서귀포시", ("대정읍", "남원읍", "성산읍", "안덕면", "표선면",
               "송산동", "정방동", "중앙동", "천지동", "효돈동", "영천동", "동홍동", "서홍동", "대륜동", "대천동",
               "중문동", "예래동")),
)
EMD_NAMES: tuple[str, ...] = tuple(name for _, names in EMD_GROUPS for name in names)

# 3번 작물: data/tables/crops.csv의 (crop_code, label) 그대로(시험이 표와 같은지 본다).
CROPS: tuple[tuple[str, str], ...] = (
    ("당근", "당근"), ("월동무", "월동무"), ("양배추", "양배추"), ("브로콜리", "브로콜리"),
    ("마늘", "마늘"), ("양파", "양파"), ("감자", "감자"), ("감귤_노지", "노지감귤(온주)"),
    ("감귤_만감", "만감류"), ("기타과수", "기타 과수"), ("시설과채", "시설 과채"),
)
# 작물 그림 단추 아래 작은 글(묶음 이름인 단추에만): data/tables/crops.csv aliases 에 있는 낱말만 쓴다(시험이 표와 같은지 본다).
CROP_HINTS: dict[str, str] = {
    "감귤_노지": "극조생·조생 귤", "감귤_만감": "한라봉·천혜향·레드향", "기타과수": "키위·망고·블루베리", "시설과채": "토마토·딸기·파프리카",
}
# 12번 자조금을 묻는 작물: supports.csv에서 자조금 조건(needs_selfpay_fund Y·E)이 붙은 행의 crop_in
# (그룹 "월동채소"는 crops.csv groups로 풂). 다른 작물은 selfpay_fund="na". 시험이 표와 같은지 본다.
SELFPAY_CROPS = frozenset({"당근", "월동무", "양배추", "브로콜리", "마늘", "양파", "감귤_노지", "감귤_만감"})

# 5a는 4번(없으면 3번 합계)이 이 범위(소농 판정 범위)이고 땅이 전부·일부 내 땅일 때만 묻는다.
ASK_5A_PY = (302, 2890)
OWN_LAND = ("own_all", "own_part")

# (칸 값, 화면 문구). 칸 값은 FarmProfile 값 그대로다(spouse "separate"와 예·아니오·모름만 바꿔 읽는다).
VISITOR = (("self", "본인"), ("family_proxy", "가족"), ("village_head_proxy", "이장·작목반장"))
PROXY_VISITOR = VISITOR[1:]
OWNER_SEX = (("F", "여"), ("M", "남"))
LAND_TENURE = (("own_all", "전부 내 땅"), ("own_part", "일부"), ("rent_all", "전부 빌림"), ("unknown", "모름"))
YES_NO_UNKNOWN = (("yes", "예"), ("no", "아니오"), ("unknown", "모름"))
MGMT_STATUS = (("over_2y", "2년 넘음"), ("under_2y", "2년 안 됨"), ("none", "안 함"), ("unknown", "모름"))
SPOUSE = (("registered", "같이 등록됨"), ("cofarming_unregistered", "같이 짓지만 미등록"),
          ("separate", "따로 일함·안 지음"), ("none", "없음"))
HEALTH_INS = (("regional", "고지서 받아 직접 냄"), ("dependent", "가족(자녀·배우자) 회사 밑에 올라 있음"),
              ("employee", "본인이 회사에서 냄"), ("unknown", "모름"))
SALES_CHANNEL = (("coop", "농협(계통·계약재배)"), ("field_contract_done", "상인 밭떼기 계약함"),
                 ("merchant_planned", "상인 예정"), ("unknown", "모름"), ("direct", "직접 판매"))
SELFPAY_FUND = (("paid", "냄"), ("not_paid", "안 냄"), ("unknown", "모름"))
DISASTER = (("yes", "있음"), ("no", "없음"))
EDUCATION = (("Y", "예"), ("N", "아니오"), ("NA", "직불 안 받음"))

YES_NO_VALUE = {"yes": True, "no": False, "unknown": None}

# 문자 안내 동의 문구(고정 4줄).
CONSENT_LINES = (            # 법으로 알려야 하는 네 가지: 모으는 것 · 쓰는 곳 · 지우는 때 · 동의 안 해도 불이익 없음
    "모으는 것은 휴대폰 번호뿐이에요.",
    "보험에 들거나 신청할 때가 되면 문자로 알려 드리는 데만 써요.",
    "알림을 다 보내면 지우고, 늦어도 13개월 뒤에는 지워요.",
    "동의하지 않으셔도 상담과 종이에 불이익이 없어요.",
)
PHONE = re.compile(r"010-[0-9]{4}-[0-9]{4}")

MSG_PICK = "목록에서 하나 눌러 주세요."
MSG_AREA = "평수는 숫자만 눌러 주세요(예: 1500). 모르시면 비워 두세요."
MSG_AREA_ZERO = "평수는 0보다 커야 해요. 모르시면 비워 두세요."
MSG_AREA_30HA = "평수가 너무 커요(90,750평이 넘어요). 평수가 맞는지 봐 주세요."
MSG_BIRTH = "태어난 해는 1900~2010 사이 네 자리로 눌러 주세요."


class FormErrors(dict[str, str]):
    """칸 이름 → 그 칸 아래에 띄울 한국어 오류. 비어 있지 않으면 제출을 막는다."""


def initial_values(*, proxy: bool) -> dict[str, str]:
    """빈 화면의 기본 선택: 없음. 마지막 화면의 햇수·배우자·거주는 눌러야 선택되고(눌러 둔 채로 열지 않는다),
    안 눌렀을 때는 서버 기본값이 간다(거주 3년은 예). 오신 분(visitor)·땅 2년(land_held_2y)은 화면에서 묻지 않는다."""
    return {}


class _Reader:
    """폼 칸을 읽으며 오류를 모은다."""

    def __init__(self, form: Mapping[str, str]) -> None:
        self.form = form
        self.errors = FormErrors()

    def text(self, name: str) -> str:
        return (self.form.get(name) or "").strip()

    def choice(self, name: str, options: tuple[tuple[str, str], ...], default: str | None) -> str | None:
        value = self.text(name)
        if not value:
            return default
        if value not in dict(options):
            self.errors[name] = MSG_PICK
            return default
        return value

    def yes_no(self, name: str, default: bool | None) -> bool | None:
        value = self.choice(name, YES_NO_UNKNOWN, None)
        return default if value is None else YES_NO_VALUE[value]

    def number(self, name: str, low: int, high: int, message: str) -> int | None:
        value = self.text(name).replace(",", "")
        if not value:
            return None
        if not re.fullmatch(r"[0-9]+", value) or not low <= int(value) <= high:
            self.errors[name] = message
            return None
        return int(value)

    def area_py(self, name: str) -> int | None:
        """평 한 칸. 0 이하·30ha 초과는 오류."""
        py = self.number(name, 0, 10**9, MSG_AREA)
        if py is None:
            return None
        if py == 0:
            self.errors[name] = MSG_AREA_ZERO
            return None
        if py_to_m2(py) > MAX_AREA_M2:
            self.errors[name] = MSG_AREA_30HA
            return None
        return py

    def checked(self, name: str) -> bool:
        return bool(self.text(name))


def _crop(r: _Reader, i: int) -> tuple[dict, int | None] | None:
    """i번째 작물 줄 → (CropPlot 값, 평) 또는 None(작물을 안 고름)."""
    p = f"crop{i}_"
    code = r.choice(p + "crop_code", CROPS, None)
    if code is None:
        if r.text(p + "area_py") and p + "crop_code" not in r.errors:
            r.errors[p + "crop_code"] = "평수만 들어 있어요. 작물을 눌러 주세요."
        return None
    py = r.area_py(p + "area_py")
    fund = r.choice(p + "selfpay_fund", SELFPAY_FUND, "unknown") if code in SELFPAY_CROPS else "na"
    plot = {"crop_code": code, "area_m2": None if py is None else py_to_m2(py),
            "sales_channel": r.choice(p + "sales_channel", SALES_CHANNEL, "unknown"), "selfpay_fund": fund}
    return plot, py


def to_profile(form: Mapping[str, str], *, proxy: bool = False) -> FarmProfile | FormErrors:
    """입력 폼 → FarmProfile, 막을 것이 있으면 FormErrors. proxy=True(대신 입력)면 오신 분은 가족·이장 중 하나."""
    r = _Reader(form)

    # 대신 입력 화면은 오신 분을 묻지 않는다: 안 오면 "가족". 목록 밖 값이 오면 오류.
    visitor = r.choice("visitor", PROXY_VISITOR if proxy else VISITOR, "family_proxy" if proxy else "self")
    emd = r.choice("emd_code", tuple((n, n) for n in EMD_NAMES), None)
    if emd is None and "emd_code" not in r.errors:
        r.errors["emd_code"] = "사시는 읍·면·동을 눌러 주세요."
    birth_year = r.number("birth_year", 1900, 2010, MSG_BIRTH)

    rows = [row for row in (_crop(r, 1), _crop(r, 2)) if row is not None]
    if not rows and "crop1_crop_code" not in r.errors:
        r.errors["crop1_crop_code"] = "키우시는 것을 하나 눌러 주세요."
    if len(rows) == 2 and rows[0][0]["crop_code"] == rows[1][0]["crop_code"]:
        r.errors["crop2_crop_code"] = "같은 작물을 두 번 누르셨어요. 평수를 합쳐 한 줄에 눌러 주세요."
    crop_py = [py for _, py in rows]
    known_py = sum(py for py in crop_py if py is not None)

    total_py = r.area_py("total_area_py")
    from_crops = total_py is None and not r.text("total_area_py") and bool(rows) and None not in crop_py
    if from_crops:  # 4번 모르면: 3번 합계를 쓰고 "총면적 확인"
        total_py = known_py
        if py_to_m2(total_py) > MAX_AREA_M2:
            r.errors["total_area_py"] = "작물 평수를 합치면 너무 커요(90,750평이 넘어요). 평수가 맞는지 봐 주세요."
    elif total_py is not None and total_py < known_py:
        r.errors["total_area_py"] = "전체 땅이 작물 땅을 합친 것보다 작아요. 다시 눌러 주세요."

    land = r.choice("land_tenure", LAND_TENURE, "unknown")
    owns = land in OWN_LAND
    asks_5a = owns and total_py is not None and ASK_5A_PY[0] <= total_py <= ASK_5A_PY[1]

    mgmt = r.choice("mgmt_status", MGMT_STATUS, "unknown")
    reg_year = r.number("mgmt_last_reg_year", 1900, 2100, "해를 네 자리로 눌러 주세요. 모르시면 비워 두세요.")
    spouse = r.choice("spouse", SPOUSE, "none")

    values = dict(
        visitor=visitor,
        owner_sex=r.choice("owner_sex", OWNER_SEX, None),
        emd_code=emd,
        birth_year=birth_year,
        birth_year_approx=r.checked("birth_year_approx"),
        crops=tuple(plot for plot, _ in rows),
        total_area_m2=None if total_py is None else py_to_m2(total_py),
        total_area_is_crop_sum=from_crops,
        land_tenure=land,
        land_held_2y=r.yes_no("land_held_2y", True) if owns else None,
        owned_over_4700py=r.yes_no("owned_over_4700py", None) if asks_5a else None,
        mgmt_status=mgmt,
        mgmt_last_reg_year=None if mgmt == "none" else reg_year,
        spouse="none" if spouse == "separate" else spouse,
        farming_years=r.number("farming_years", 0, 100, "농사 지은 햇수는 0~100 사이 숫자로 눌러 주세요."),
        farming_10y_plus=r.checked("farming_10y_plus"),
        residence_3y=r.checked("residence_3y") if "residence_3y" in form else True,   # 칸이 아예 없으면 "예"(칸을 빼도 농민수당 줄이 사라지지 않게)
        health_ins=r.choice("health_ins", HEALTH_INS, "unknown"),
        flags={"disaster_damage": r.choice("disaster_damage", DISASTER, "no") == "yes",
               "direct_payment_education": r.choice("direct_payment_education", EDUCATION, "NA")},
    )
    if r.errors:
        return r.errors
    return FarmProfile(**values)


def phone_from_digits(form: Mapping[str, str]) -> dict[str, str]:
    """결과 화면의 번호 칸은 화면 숫자판(숫자만)으로 넣는다: 010으로 시작하는 숫자 11자리면 010-0000-0000 꼴로 바꾼다. 아니면 그대로 둔다."""
    out = dict(form)
    digits = re.sub(r"[\s-]", "", out.get("reminder_phone", ""))
    if re.fullmatch(r"010[0-9]{8}", digits):
        out["reminder_phone"] = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return out


def reminder_errors(form: Mapping[str, str]) -> FormErrors:
    """문자 안내 칸 검사: 번호는 010-0000-0000 형식, 번호가 있으면 동의 체크가 있어야 한다."""
    r = _Reader(form)
    phone = r.text("reminder_phone")
    if phone and not PHONE.fullmatch(phone):
        r.errors["reminder_phone"] = "휴대폰 번호는 010으로 시작하는 숫자 11개를 눌러 주세요."
    elif phone and not r.checked("reminder_consent"):
        r.errors["reminder_consent"] = "동의 체크가 필요해요. 동의하지 않으시면 번호를 지워 주세요."
    return r.errors


def to_reminder(form: Mapping[str, str]) -> ReminderRequest | None:
    """문자 안내 요청(번호가 없으면 None). reminder_errors가 빈 폼에만 부른다."""
    r = _Reader(form)
    phone = r.text("reminder_phone")
    return ReminderRequest(phone=phone, consent=r.checked("reminder_consent")) if phone else None
