"""지원 표의 행(Program)에서 어르신 말 태그를 만든다. 규칙만 쓰고 AI는 부르지 않는다(설계서 B-2).

- 조건 태그를 중요한 순서로: 작물 → 성별·나이 → 지역 → 농협 출하·자조금 → 땅 넓이 → 농사·거주 햇수 → 소득 심사 → 경영체 등록.
- 3개가 안 되면 지원 종류, 신청 방식, 사업 기관 순으로 채운다. 4개를 넘기지 않는다.
- 태그 글은 모두 그 행의 칸 값에서만 나온다(숫자는 칸 값 그대로, 넓이의 평 환산만 '약'을 붙여 보탠다).
- 제도에 행이 여럿(작물별·읍면별)이면 모든 행에 똑같이 있는 태그만 남기고, 작물은 행들의 합쳐서 한 태그로 쓴다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.models import Program
from app.core.tables_models import Crop

MAX_TAGS = 4
MIN_TAGS = 3
MAX_CROP_NAMES = 3          # 작물이 이만큼보다 많으면 "여러 작물"
SQM_PER_PYEONG = Decimal("3.3058")      # schema.json: 1평 = 3.3058㎡, 1ha = 10,000㎡
CROP_SHORT = {"감귤_노지": "노지감귤", "감귤_만감": "만감류"}        # crops.csv 이름("노지감귤(온주)")은 태그로 길다
CITRUS = ("노지감귤", "만감류")

CATEGORY_ORDER = ("crop", "crop_x", "who", "region", "trade", "area", "years", "income", "mgmt")
KIND_TAG = {"현금": "현금 지원", "보험료지원": "보험료 지원", "현물·자재": "자재 지원", "서비스": "서비스 지원",
            "감면": "보험료 줄여 줌", "사업비보조": "사업비 보조", "연금": "연금"}
LEVEL_TAG = {"국가": "나라 사업", "도": "제주도 사업", "제주시": "제주시 사업", "서귀포시": "서귀포시 사업",
             "농협": "농협 사업", "공사": "농어촌공사 사업", "공단": "공단 사업"}
HEALTH_WORD = {"지역": "지역가입자", "직장": "직장가입자", "피부양자": "피부양자"}


@dataclass(frozen=True)
class Tag:
    text: str
    cat: str            # CATEGORY_ORDER 의 하나, 채움 태그는 kind·mode·level


def crop_labels(crops: Sequence[Crop]) -> dict[str, str]:
    """crop_code → 태그에 쓸 짧은 이름. crops.csv 에 없는 묶음 이름(밭작물, 월동채소)은 그대로 쓴다."""
    return {c.crop_code: CROP_SHORT.get(c.crop_code, c.label) for c in crops}


def crop_names(codes: Sequence[str], labels: Mapping[str, str]) -> list[str]:
    """작물 코드들의 쉬운 이름(중복 없이, 처음 나온 차례). 노지감귤과 만감류가 함께 있으면 '감귤' 하나로 합친다."""
    names: list[str] = []
    for code in codes:
        name = labels.get(code, code)
        if name not in names:
            names.append(name)
    if all(c in names for c in CITRUS):
        at = min(names.index(c) for c in CITRUS)
        names = [n for n in names if n not in CITRUS]
        names.insert(at, "감귤")
    return names


def crop_tag_text(names: Sequence[str]) -> str:
    return "·".join(names) if len(names) <= MAX_CROP_NAMES else "여러 작물"


# --- 숫자 글 ---------------------------------------------------------------------------------

def num(d: Decimal | int) -> str:
    """0.50 → '0.5', 30 → '30'. 칸 값 그대로(끝 0만 뗀다)."""
    s = format(Decimal(d).normalize(), "f")
    return s


def pyeong(ha: Decimal) -> int:
    """ha → 평(100평 단위로 반올림, 최소 100). 태그의 '약 ○평'에만 쓴다."""
    py = Decimal(ha) * 10000 / SQM_PER_PYEONG
    return max(100, int((py / 100).to_integral_value(ROUND_HALF_UP)) * 100)


def area_text(lo: Decimal | None, hi: Decimal | None, with_py: bool = True) -> str:
    if lo is not None and hi is not None:
        return f"{num(lo)}~{num(hi)}ha"
    if lo is not None:
        return f"{num(lo)}ha 이상" + (f"(약 {pyeong(lo):,}평)" if with_py else "")
    return f"{num(hi)}ha 이하" + (f"(약 {pyeong(hi):,}평)" if with_py else "")


def age_text(p: Program) -> str | None:
    """나이 조건 한 줄. 출생일로 끊는 공고는 태어난 해로 적는다(born_before 는 그 날짜 '전'까지, born_after 는 그 날짜 '이후')."""
    if p.born_before or p.born_after:
        after = p.born_after.year if p.born_after else None
        before = _born_before_year(p.born_before) if p.born_before else None
        if after and before:
            return f"{after}~{before}년생"
        if after:
            return f"{after}년 이후 출생"
        return f"{before}년 이전 출생" if p.born_before.month == 1 and p.born_before.day == 1 \
            else f"{p.born_before.month}월 {p.born_before.day}일 전 출생"
    if p.min_age is not None and p.max_age is not None:
        return f"{p.min_age}~{p.max_age}세"
    if p.min_age is not None:
        return f"{p.min_age}세 이상"
    if p.max_age is not None:
        return f"{p.max_age}세 이하"
    return None


def _born_before_year(d: date) -> int:
    return d.year - 1 if d.month == 1 and d.day == 1 else d.year


# --- 조건 태그 -------------------------------------------------------------------------------

def condition_tags(p: Program, labels: Mapping[str, str]) -> list[Tag]:
    """행 하나의 조건 태그(중요한 순서). 개수는 자르지 않는다."""
    out: list[Tag] = []
    if p.crop_in:
        out.append(Tag(crop_tag_text(crop_names(p.crop_in, labels)), "crop"))
    elif p.crop_not_in:
        out.append(Tag(f"{'·'.join(crop_names(p.crop_not_in, labels))} 제외", "crop_x"))
    if p.facility:
        out.append(Tag(f"{p.facility} 재배", "crop_x"))
    if p.sex:
        out.append(Tag("여성", "who"))
    if age := age_text(p):
        out.append(Tag(age, "who"))
    if p.region_in:
        out.append(Tag(f"{p.region_in} 농지" if p.region_basis == "농지소재지" else f"{p.region_in} 주소지"
                       if p.region_basis == "주소지" else p.region_in, "region"))
    if p.area_type_in:
        out.append(Tag("읍·면 지역" if p.area_type_in == "읍면" else "동 지역", "region"))
    if p.health_ins_in:
        out.append(Tag("건강보험 " + "·".join(HEALTH_WORD[h] for h in p.health_ins_in), "region"))
    if p.needs_coop == "E" and p.needs_selfpay_fund == "E":
        out.append(Tag("농협 출하나 자조금 가입", "trade"))
    else:
        if p.needs_coop:
            out.append(Tag("농협에 파는 농가" if p.needs_coop == "Y" else "농협 출하(또는 자조금)", "trade"))
        if p.needs_selfpay_fund:
            out.append(Tag("자조금 가입" if p.needs_selfpay_fund == "Y" else "자조금 가입(또는 농협 출하)", "trade"))
    if p.needs_enrollment:
        out.append(Tag("미리 참여 신청", "trade"))
    if p.min_ha is not None or p.max_ha is not None:
        out.append(Tag(area_text(p.min_ha, p.max_ha), "area"))
    if p.owns_land:
        out.append(Tag(f"농지 {p.land_hold_years}년 이상 보유" if p.land_hold_years else "농지 소유", "area"))
    if p.max_owned_ha is not None:
        out.append(Tag(f"소유 농지 {num(p.max_owned_ha)}ha 이하", "area"))
    if p.min_farming_years:
        out.append(Tag(f"농사 {p.min_farming_years}년 이상", "years"))
    if p.min_residence_years:
        out.append(Tag(f"제주 거주 {p.min_residence_years}년 이상", "years"))
    if p.income_test == "상한":
        out.append(Tag(f"농외소득 {p.income_max_manwon:,}만 원 이하" if p.income_max_manwon else "소득 상한 있음", "income"))
    elif p.income_test == "심사":
        out.append(Tag("소득 심사", "income"))
    if p.needs_mgmt:
        out.append(Tag(f"농업경영체 등록 {p.min_mgmt_years}년 이상" if p.min_mgmt_years else "농업경영체 등록", "mgmt"))
    return out


# --- 채움 태그(지원 종류·신청 방식·사업 기관) --------------------------------------------------

def mode_tag(p: Program) -> str:
    """신청 방식. 값이 내릴 때·재해처럼 일이 생겨야 주는 지원은 그 일을, 아니면 신청 주기를 적는다."""
    if p.trigger == "price_stab":
        return "값이 내릴 때 지원"
    if p.trigger == "logistics":
        return "운송비 지원"
    if p.trigger == "disaster":
        return "재해가 났을 때"
    if p.apply_cycle == "사후신청":
        return {"재해": "재해가 났을 때 신청", "사고": "사고가 났을 때 신청"}.get(p.event_type or "", "일이 생긴 뒤 신청")
    return {"상시": "상시 신청", "연1회": "해마다 한 번 신청", "자동": "따로 신청하지 않아요"}[p.apply_cycle]


def fill_tags(p: Program) -> list[Tag]:
    return [Tag(KIND_TAG[p.kind], "kind"), Tag(mode_tag(p), "mode"), Tag(LEVEL_TAG[p.agency_level], "level")]


# --- 합치기 ----------------------------------------------------------------------------------

def group_tags(rows: Sequence[Program], labels: Mapping[str, str]) -> tuple[str, ...]:
    """제도 하나(행 하나 이상)의 태그 3~4개. 모든 행에 똑같이 있는 것만 남긴다(작물은 합침)."""
    per_row = [condition_tags(r, labels) for r in rows]
    first = per_row[0]
    kept = [t for t in first if t.cat != "crop" and all(t in other for other in per_row[1:])]
    crops = [r.crop_in for r in rows]
    crop_tag: list[Tag] = []
    if all(crops):
        merged = crop_names([c for codes in crops for c in codes], labels)
        crop_tag = [Tag(crop_tag_text(merged), "crop")]
    conds = sorted(crop_tag + kept, key=lambda t: CATEGORY_ORDER.index(t.cat))[:MAX_TAGS]
    texts = [t.text for t in conds]
    if len(texts) < MIN_TAGS:
        fills = [fill_tags(r) for r in rows]
        for t in fills[0]:
            if len(texts) >= MIN_TAGS:
                break
            if all(t in other for other in fills[1:]) and t.text not in texts:
                texts.append(t.text)
    return tuple(texts)


def row_tags(p: Program, labels: Mapping[str, str]) -> tuple[str, ...]:
    return group_tags([p], labels)
