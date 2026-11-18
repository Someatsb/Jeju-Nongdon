"""표 검증기(Task 3, U03). 사원 B의 scripts/validate_tables_v0.py(R01~R17)를 옮기고 R18·R19를 더했다.

data/tables/schema.json 하나를 기준으로 이름이 정해진 표만 검사한다:
crops.csv, params_by_season.csv, interventions.csv, offices.csv, supports.csv.
같은 폴더의 다른 CSV(예: inbox_k_rows.csv)는 읽지 않는다.

- 오류(error) = 저장·로드 불가, 경고(warning) = 저장 가능하지만 확인 필요.
- 행 번호는 Excel 기준(머리글 = 1행, 첫 데이터 = 2행). 파일 전체 문제는 0행.
- v0와 달라진 점: R18·R19 추가, hold 행은 식별 4칸만 필수이고 칸 사이 규칙은 건너뜀(형식·id 검사만),
  깨진 글자 '�'(E05)는 오류, 정액 1,000원 미만(R15)과 manual_check 항목 60자 초과(R20, v0의 R15 경고)는
  경고에서 오류로 올림(인쇄가 틀어짐), list_str·list_int 칸도 검사(로더가 형 변환하다 깨지지 않게),
  offices.csv 검사.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

SHIPPED_SCHEMA = Path(__file__).resolve().parents[2] / "data" / "tables" / "schema.json"
TABLE_ORDER = ("crops", "params_by_season", "interventions", "offices", "supports")
IDENTITY = ("id", "program_key", "edition", "status")      # hold 행도 반드시 채우는 칸
R19_KEYS = ("verified_date", "verified_by")                # hold가 아닌 행만 필수
BROKEN = "�"                                          # cp949 파일을 UTF-8로 잘못 열어 저장하면 생김


class Issue(BaseModel):
    """검사 결과 한 건. message_ko는 직원에게 그대로 보여 주는 한국어 문장."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str                                  # "supports.csv"
    row_excel: int                             # 0 = 파일 전체, 1 = 머리글
    column: str                                # 컬럼 키, 없으면 ""
    level: Literal["error", "warning"]
    message_ko: str
    code: str = ""                             # E00~E16, R01~R20
    hint_ko: str = ""                          # 고치는 방법(있으면)


class _Report:
    def __init__(self) -> None:
        self.items: list[Issue] = []

    def add(self, level: Literal["error", "warning"], file: str, row: int, col: str, code: str, msg: str, hint: str = "") -> None:
        self.items.append(Issue(file=file, row_excel=row, column=col, level=level, message_ko=msg, code=code, hint_ko=hint))

    def err(self, *a: Any, **k: Any) -> None:
        self.add("error", *a, **k)

    def warn(self, *a: Any, **k: Any) -> None:
        self.add("warning", *a, **k)


# --- 파일 읽기 ------------------------------------------------------------------------------

def read_schema(tables_dir: Path, schema_path: Path | None = None) -> dict:
    """표 폴더의 schema.json, 없으면 배포 schema.json(올린 파일만 있는 임시 폴더 검사용)."""
    path = schema_path or (tables_dir / "schema.json" if (tables_dir / "schema.json").exists() else SHIPPED_SCHEMA)
    return json.loads(path.read_text(encoding="utf-8"))


def _cp949_ok(ch: str) -> bool:
    try:
        ch.encode("cp949")
        return True
    except UnicodeEncodeError:
        return False


def _decode(raw: bytes, rep: _Report, file: str) -> str | None:
    """utf-8-sig → utf-8 → cp949 순으로 읽는다(한국어 Windows Excel의 CSV 저장은 cp949)."""
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if enc == "cp949":
            rep.warn(file, 0, "", "E00", "파일이 cp949(Excel 기본)로 저장돼 있습니다. 저장할 때 UTF-8로 바꿉니다.")
        return text
    rep.err(file, 0, "", "E01", "파일 글자 인코딩을 읽을 수 없습니다.", "Excel에서 'CSV UTF-8'로 저장해 주세요.")
    return None


def _read_csv(path: Path, rep: _Report, file: str) -> tuple[list[str] | None, list[dict[str, str]]]:
    text = _decode(path.read_bytes(), rep, file)
    if text is None:
        return None, []
    bad = sorted({ch for ch in text if ord(ch) > 127 and ch != BROKEN and not _cp949_ok(ch)})
    if bad:
        rep.warn(file, 0, "", "R17", f"Excel에서 cp949 CSV로 저장하면 깨지는 글자가 있습니다: {' '.join(bad[:10])}",
                 "'-' 같은 기본 글자로 바꾸거나 'CSV UTF-8'로 저장해 주세요.")
    rd = csv.DictReader(io.StringIO(text, newline=""))
    return list(rd.fieldnames or []), list(rd)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """로더용: 같은 인코딩 규칙으로 읽기만 한다(검사 결과는 버림)."""
    header, rows = _read_csv(path, _Report(), path.name)
    if header is None:
        raise UnicodeError(f"{path.name} 파일 글자 인코딩을 읽을 수 없습니다.")
    return header, rows


# --- 칸 검사 --------------------------------------------------------------------------------

def _tokens(v: str) -> list[str]:
    return [t.strip() for t in v.split(";") if t.strip()]


def _check_columns(cols_def: list[dict], header: list[str], rep: _Report, file: str) -> bool:
    keys = [c["key"] for c in cols_def]
    missing = [k for k in keys if k not in header]
    for k in missing:
        lab = next(c["label"] for c in cols_def if c["key"] == k)
        rep.err(file, 1, k, "E02", f"'{lab}'({k}) 컬럼이 없습니다.", "양식 파일의 머리글을 그대로 써 주세요.")
    for h in header:
        if h not in keys:
            rep.err(file, 1, h, "E03", f"모르는 컬럼 '{h}'이 있습니다.", "오타인지 확인하거나 지워 주세요.")
    return not missing


def _check_broken(cols_def: list[dict], r: dict[str, str], rep: _Report, file: str, rn: int) -> None:
    for c in cols_def:
        if BROKEN in (r.get(c["key"]) or ""):
            rep.err(file, rn, c["key"], "E05", f"{rn}행 '{c['label']}'({c['key']})에 깨진 글자(�)가 있습니다.",
                    "cp949로 저장된 파일을 UTF-8로 잘못 열었던 흔적입니다. 원문에서 글자를 다시 옮겨 주세요.")


def _check_cell(c: dict, v: str | None, rep: _Report, file: str, rn: int, ctx: dict, required: bool | None = None) -> Any:
    key, lab, typ = c["key"], c["label"], c["type"]
    v = (v or "").strip()
    if v == "":
        if (c.get("required") is True) if required is None else required:
            rep.err(file, rn, key, "E10", f"{rn}행 '{lab}'({key})이 비어 있습니다.", c.get("help", ""))
        return None
    try:
        if typ == "int":
            x: Any = int(v)
        elif typ == "float":
            x = float(v)
            if not math.isfinite(x):
                raise ValueError(v)
        elif typ == "date":
            x = date.fromisoformat(v)
        elif typ == "list_int":
            x = [int(t) for t in _tokens(v)]
        else:
            x = v
    except ValueError:
        ex = {"int": "예: 60", "float": "예: 0.5", "date": "예: 2026-01-16", "list_int": "예: 11;12;1"}.get(typ, "")
        kind = "날짜" if typ == "date" else "숫자"
        rep.err(file, rn, key, "E11", f"{rn}행 '{lab}'({key})의 값 '{v}'은 {kind} 형식이 아닙니다. {ex}")
        return None
    if typ in ("int", "float"):
        if ("min" in c and x < c["min"]) or ("max" in c and x > c["max"]):
            rep.err(file, rn, key, "E12", f"{rn}행 '{lab}' 값 {v}이 허용 범위({c.get('min')}~{c.get('max')}) 밖입니다.")
    if typ in ("str", "text") and "max" in c and len(v) > c["max"]:
        rep.err(file, rn, key, "E13", f"{rn}행 '{lab}'이 {len(v)}자입니다. {c['max']}자 이하로 줄여 주세요.")
    if typ == "enum" and v not in c["enum"]:
        rep.err(file, rn, key, "E14", f"{rn}행 '{lab}'에 '{v}'는 쓸 수 없습니다. 쓸 수 있는 값: {', '.join(c['enum'])}")
    if typ == "list_enum":
        for t in _tokens(v):
            if t not in c["enum"]:
                rep.err(file, rn, key, "E14", f"{rn}행 '{lab}'에 '{t}'는 쓸 수 없습니다. 쓸 수 있는 값: {', '.join(c['enum'])}")
    if "pattern" in c and typ == "str" and not re.match(c["pattern"], v):
        rep.err(file, rn, key, "E15", f"{rn}행 '{lab}' 값 '{v}'의 모양이 규칙과 다릅니다.", c.get("example", ""))
    if typ == "list_crop":
        for t in _tokens(v):
            if t not in ctx["crop_tokens"]:
                sug = [k for k, al in ctx["crop_alias"].items() if t in al]
                rep.err(file, rn, key, "E16", f"{rn}행 '{lab}'에 '{t}'은 작물 목록에 없습니다." + (f" 혹시 '{sug[0]}'인가요?" if sug else ""),
                        "crops.csv의 crop_code 또는 그룹(밭작물·월동채소·과수·감귤)을 써 주세요.")
    if typ == "crop" and v not in ctx["crop_codes"]:
        rep.err(file, rn, key, "E16", f"{rn}행 '{lab}'에 '{v}'은 작물 목록에 없습니다.")
    return x


# --- 표별 검사 ------------------------------------------------------------------------------

def _validate_supports(path: Path, schema: dict, ctx: dict, rep: _Report, today: date | None) -> None:
    td = schema["tables"]["supports"]
    t, cols = td["file"], td["columns"]
    header, rows = _read_csv(path, rep, t)
    if header is None or not _check_columns(cols, header, rep, t):
        return
    labels = {c["key"]: c["label"] for c in cols}
    seen: dict[str, int] = {}
    for i, r in enumerate(rows):
        rn = i + 2

        def g(k: str) -> str:
            return (r.get(k) or "").strip()

        st = g("status")
        _check_broken(cols, r, rep, t, rn)
        V: dict[str, Any] = {}
        for c in cols:
            req = c.get("required") is True
            if c["key"] in R19_KEYS or (st == "hold" and c["key"] not in IDENTITY):
                req = False  # R19가 따로 알림 / hold 행은 식별 4칸만 필수
            V[c["key"]] = _check_cell(c, r.get(c["key"]), rep, t, rn, ctx, required=req)
        rid = g("id")
        if rid in seen:
            rep.err(t, rn, "id", "R13", f"{rn}행 id '{rid}'이 {seen[rid]}행과 겹칩니다.")
        seen[rid] = rn
        pk = g("program_key")
        if rid and pk and not rid.startswith(pk + "@"):
            rep.err(t, rn, "id", "R13", f"{rn}행 id는 program_key '{pk}@'로 시작해야 합니다.")
        if st == "hold":
            continue  # hold 행은 식별·형식 검사만(R19 규칙 글). 칸 사이 규칙(R01~R12·R15·R16·R18·R20)은 건너뜀
        # R01 출처
        if st in ("confirmed", "prior_year_reference"):
            for k, lab in (("source_title", "근거 문서"), ("source_url", "근거 주소")):
                if not g(k):
                    rep.err(t, rn, k, "R01", f"{rn}행 상태가 '{st}'인데 {lab}({k})가 비어 있습니다.", "'hold'로 두거나 출처를 넣어 주세요.")
            if g("source_url") and not all(u.strip().startswith("http") for u in g("source_url").split(" ; ")):
                rep.err(t, rn, "source_url", "R01", f"{rn}행 근거 주소는 http로 시작해야 합니다(여러 개면 ' ; ').")
        # R02 날짜 순서
        for a, b, la in (("valid_from", "valid_to", "적용 기간"), ("apply_start", "apply_end", "신청 기간")):
            if V.get(a) and V.get(b) and V[a] > V[b]:
                rep.err(t, rn, a, "R02", f"{rn}행 {la} 시작일({g(a)})이 끝나는 날({g(b)})보다 늦습니다.")
        # R03 신청 방식
        cyc = g("apply_cycle")
        if cyc == "연1회" and not g("apply_end"):
            rep.err(t, rn, "apply_end", "R03", f"{rn}행 신청 방식이 '연1회'인데 신청 마감일이 없습니다.")
        if cyc == "사후신청" and not g("event_type"):
            rep.err(t, rn, "event_type", "R03", f"{rn}행 '사후신청'은 어떤 일(재해/사고) 뒤인지 event_type이 있어야 합니다.")
        # R04 나이
        if (g("min_age") or g("max_age")) and not g("age_basis"):
            rep.err(t, rn, "age_basis", "R04", f"{rn}행 나이 조건이 있는데 나이 기준일(age_basis)이 없습니다.", "신청일/연말/1월1일 중 하나")
        if V.get("min_age") is not None and V.get("max_age") is not None and V["min_age"] > V["max_age"]:
            rep.err(t, rn, "min_age", "R04", f"{rn}행 최소 나이가 최대 나이보다 큽니다.")
        if V.get("born_after") and V.get("born_before") and V["born_after"] >= V["born_before"]:
            rep.err(t, rn, "born_after", "R04", f"{rn}행 born_after가 born_before보다 늦습니다.")
        # R05 면적
        if (g("min_ha") or g("max_ha")) and not g("area_basis"):
            rep.err(t, rn, "area_basis", "R05", f"{rn}행 면적 조건이 있는데 면적 기준(area_basis)이 없습니다.", "경작/해당작물/소유/인증 중 하나")
        if V.get("min_ha") is not None and V.get("max_ha") is not None and V["min_ha"] > V["max_ha"]:
            rep.err(t, rn, "min_ha", "R05", f"{rn}행 최소 면적이 최대 면적보다 큽니다.")
        for k in ("min_ha", "max_owned_ha"):
            if V.get(k) is not None and V[k] > 30:
                rep.warn(t, rn, k, "R15", f"{rn}행 '{k}' {g(k)} — ha 단위입니다. 평으로 넣으셨다면 {V[k] * 3.3058 / 10000:.4f}ha입니다.")
        # R06 E 짝
        if (g("needs_coop") == "E") != (g("needs_selfpay_fund") == "E"):
            rep.err(t, rn, "needs_coop", "R06", f"{rn}행 'E'(둘 중 하나)는 needs_coop와 needs_selfpay_fund에 함께 적어야 합니다.")
        # R07 소득
        if g("income_test") == "상한" and not g("income_max_manwon"):
            rep.err(t, rn, "income_max_manwon", "R07", f"{rn}행 소득 기준이 '상한'인데 상한 금액(만원)이 없습니다.")
        # R08 지역
        if g("region_in") and not g("region_basis"):
            rep.err(t, rn, "region_basis", "R08", f"{rn}행 행정시 조건이 있는데 주소지/농지소재지 기준이 없습니다.")
        # R09 금액 방식별 필수 칸
        at = g("amount_type")
        need = {"정액": ["amount_value"], "kg당": ["amount_value", "calc_basis"],
                "단위당": ["amount_value", "units_per_ha", "unit_name"], "규칙": ["rule_ref"]}.get(at, [])
        for k in need:
            if not g(k):
                rep.err(t, rn, k, "R09", f"{rn}행 금액 방식 '{at}'에는 '{k}' 칸이 필요합니다.")
        if at == "면적비례":
            if not (g("amount_value") or (g("amount_min") and g("amount_max"))):
                rep.err(t, rn, "amount_value", "R09", f"{rn}행 면적비례는 단가(amount_value) 또는 범위(amount_min~amount_max)가 필요합니다.")
            if not g("calc_basis"):
                rep.err(t, rn, "calc_basis", "R09", f"{rn}행 면적비례는 calc_basis(경작면적 등)가 필요합니다.")
        if at == "보조율" and not (g("rate_pct_min") or g("rate_pct_max")):
            rep.err(t, rn, "rate_pct_max", "R09", f"{rn}행 보조율 방식인데 보조율(%)이 없습니다.")
        if V.get("amount_min") is not None and V.get("amount_max") is not None and V["amount_min"] > V["amount_max"]:
            rep.err(t, rn, "amount_min", "R09", f"{rn}행 금액 하한이 상한보다 큽니다.")
        if V.get("rate_pct_min") is not None and V.get("rate_pct_max") is not None and V["rate_pct_min"] > V["rate_pct_max"]:
            rep.err(t, rn, "rate_pct_min", "R09", f"{rn}행 보조율 하한이 상한보다 큽니다.")
        if at == "정액" and V.get("amount_value") is not None and V["amount_value"] < 1000:
            rep.err(t, rn, "amount_value", "R15",
                    f"{rn}행 정액 {g('amount_value')}원 — 원 단위입니다. 만원으로 넣으셨다면 {V['amount_value'] * 10000:,}원입니다.")
        # R12 규칙 참조 → params
        if g("rule_ref"):
            key = "stab_base" if g("rule_ref") == "price_stab" else "logi_won_per_kg"
            for crop in _tokens(g("crop_in")):
                for cc in ctx["group_members"].get(crop, [crop]):
                    if (cc, key) not in ctx["params_keys"]:
                        rep.warn(t, rn, "rule_ref", "R12", f"{rn}행 '{cc}'의 {key} 값이 params_by_season.csv에 없습니다(판정 안 함으로 인쇄됩니다).")
        # R16 상태와 기간
        if st == "prior_year_reference" and cyc == "연1회" and not g("next_month"):
            rep.err(t, rn, "next_month", "R16", f"{rn}행 '작년 기준' 행은 다음 신청 예상 월이 있어야 '○월쯤'으로 인쇄됩니다.")
        if today is not None and st == "confirmed" and cyc == "연1회" and V.get("apply_end") and V["apply_end"] < today:
            rep.warn(t, rn, "status", "R16", f"{rn}행 신청 마감({g('apply_end')})이 지났습니다. 다음 회차 참고용이면 'prior_year_reference'로 바꿔 주세요.")
        # R18 작년 기준 행: 다음 공고 확인 월(source_url 빈칸은 R01이 알림)
        if st == "prior_year_reference" and not g("expected_notice_month"):
            rep.err(t, rn, "expected_notice_month", "R18",
                    f"{rn}행 '작년 기준'(prior_year_reference) 행은 다음 공고 확인 월(expected_notice_month)이 있어야 '○월 확인' 배지가 인쇄됩니다.",
                    "보통 다음 신청 예상 월(next_month)과 같습니다.")
        # R19 hold가 아닌 행: 확인일·확인자
        if st != "hold":
            for k in R19_KEYS:
                if not g(k):
                    rep.err(t, rn, k, "R19", f"{rn}행 상태가 '{st or '빈칸'}'인데 {labels[k]}({k})이 비어 있습니다.",
                            "원문을 확인한 날짜·확인자 이니셜을 넣거나 'hold'로 두세요.")
        # R15 경고(기준일이 있을 때만)
        if today is not None and V.get("verified_date") and (today - V["verified_date"]).days > 180:
            rep.warn(t, rn, "verified_date", "R15", f"{rn}행 확인일이 {(today - V['verified_date']).days}일 전입니다. 원문을 다시 확인해 주세요.")
        if today is not None and V.get("valid_to") and V["valid_to"] < today and st != "hold":
            rep.warn(t, rn, "valid_to", "R15", f"{rn}행 적용 기간이 끝났습니다({g('valid_to')}). 새 회차로 바꾸거나 'hold'로 두세요.")
        # R20 인쇄 '□ 확인할 것' 한 항목 길이
        for item in [x for x in g("manual_check").split(" / ") if x]:
            if len(item) > 60:
                rep.err(t, rn, "manual_check", "R20", f"{rn}행 확인 항목 한 개가 {len(item)}자입니다. 60자 이하로 나눠 주세요.")
    # R11 excludes
    keys = {(r.get("program_key") or "").strip() for r in rows}
    for i, r in enumerate(rows):
        if (r.get("status") or "").strip() == "hold":
            continue
        for x in _tokens(r.get("excludes") or ""):
            if x not in keys:
                rep.err(t, i + 2, "excludes", "R11", f"{i + 2}행 excludes의 '{x}'는 표에 없는 제도 키입니다.")


def _validate_params(path: Path, schema: dict, ctx: dict, rep: _Report) -> None:
    td = schema["tables"]["params_by_season"]
    t = td["file"]
    header, rows = _read_csv(path, rep, t)
    if header is None or not _check_columns(td["columns"], header, rep, t):
        return
    pdict = td["param_dict"]
    seen: dict[tuple[str, str, str], int] = {}
    for i, r in enumerate(rows):
        rn = i + 2
        _check_broken(td["columns"], r, rep, t, rn)
        for c in td["columns"]:
            if c["type"] != "param":
                _check_cell(c, r.get(c["key"]), rep, t, rn, ctx)

        def g(k: str) -> str:
            return (r.get(k) or "").strip()

        p, st = g("param"), g("status")
        if p not in pdict:
            rep.err(t, rn, "param", "R14", f"{rn}행 항목 '{p}'은 사전에 없습니다. 쓸 수 있는 항목: {', '.join(pdict)}")
            continue
        if g("unit") != pdict[p]["unit"]:
            rep.err(t, rn, "unit", "R14", f"{rn}행 '{p}'의 단위는 '{pdict[p]['unit']}'이어야 합니다(지금 '{g('unit')}').")
        if st in ("역산", "계산", "추정", "미확인") and not g("method"):
            rep.err(t, rn, "method", "R14", f"{rn}행 등급이 '{st}'이면 계산·판단 방법(method)을 적어 주세요.")
        if st != "미확인" and not g("value"):
            rep.err(t, rn, "value", "R14", f"{rn}행 값이 비어 있습니다. 모르면 등급을 '미확인'으로 두세요.")
        if st == "미확인" and g("value"):
            rep.warn(t, rn, "value", "R14", f"{rn}행 등급이 '미확인'인데 값이 있습니다. 판정에 쓰지 않습니다.")
        if st in ("공표", "공고", "보도") and not g("source_title") and not g("method"):
            rep.err(t, rn, "source_title", "R14", f"{rn}행 '{st}' 값에는 근거(source_title)나 방법(method)이 있어야 합니다.")
        k = (g("season"), g("crop"), p)
        if k in seen:
            rep.err(t, rn, "param", "R13", f"{rn}행 ({k[0]}, {k[1]}, {p})이 {seen[k]}행과 겹칩니다.")
        seen[k] = rn
        if g("value") and pdict[p]["unit"] in ("원/kg", "ha", "kg/10a"):
            try:
                if float(g("value")) <= 0:
                    rep.err(t, rn, "value", "E12", f"{rn}행 값은 0보다 커야 합니다.")
            except ValueError:
                rep.err(t, rn, "value", "E11", f"{rn}행 '{p}' 값 '{g('value')}'이 숫자가 아닙니다.")
        if g("value") and pdict[p]["unit"] == "날짜":
            try:
                date.fromisoformat(g("value"))
            except ValueError:
                rep.err(t, rn, "value", "E11", f"{rn}행 날짜 형식이 아닙니다(예: 2025-10-31).")
    # 역산 구간 짝
    by_key = {((r.get("season") or "").strip(), (r.get("crop") or "").strip(), (r.get("param") or "").strip()): r for r in rows}
    for (s, c, p), rn in seen.items():
        if p != "breakeven_lo":
            continue
        lo, hi = by_key[(s, c, "breakeven_lo")], by_key.get((s, c, "breakeven_hi"))
        if hi is None:
            rep.err(t, rn, "param", "R14", f"{rn}행 breakeven_lo에 짝인 breakeven_hi가 없습니다.")
            continue
        try:
            contradict = bool(lo["value"] and hi["value"]) and float(lo["value"]) >= float(hi["value"])
        except ValueError:
            continue  # 숫자가 아니면 위에서 E11로 알렸다
        if contradict:
            rep.err(t, rn, "value", "R14", f"{rn}행 역산 구간이 모순입니다(하한 {lo['value']} ≥ 상한 {hi['value']}). 판정을 끄려면 '미확인'으로.")


def _validate_simple(name: str, path: Path, schema: dict, ctx: dict, rep: _Report) -> None:
    td = schema["tables"][name]
    t = td["file"]
    header, rows = _read_csv(path, rep, t)
    if header is None or not _check_columns(td["columns"], header, rep, t):
        return
    keyspec = td["key"] if isinstance(td["key"], list) else [td["key"]]
    seen: dict[tuple[str, ...], int] = {}
    names: dict[str, int] = {}
    for i, r in enumerate(rows):
        rn = i + 2
        _check_broken(td["columns"], r, rep, t, rn)
        for c in td["columns"]:
            _check_cell(c, r.get(c["key"]), rep, t, rn, ctx)
        k = tuple((r.get(x) or "").strip() for x in keyspec)
        if k in seen:
            rep.err(t, rn, keyspec[0], "R13", f"{rn}행이 {seen[k]}행과 겹칩니다.")
        seen[k] = rn
        if name == "interventions" and r.get("confirmed") in ("확인", "보도1건") and r.get("type") != "없음" and not (r.get("source_url") or "").strip():
            rep.warn(t, rn, "source_url", "R15", f"{rn}행 '{r.get('confirmed')}'인데 근거 주소가 없습니다. 원문 링크를 보강해 주세요.")
        if name == "offices":
            nm = (r.get("name") or "").strip()
            if nm and nm in names:
                rep.err(t, rn, "name", "R13", f"{rn}행 창구 이름 '{nm}'이 {names[nm]}행과 겹칩니다(접수처 글자로 창구를 찾습니다).")
            names.setdefault(nm, rn)


def _build_ctx(schema: dict, tables_dir: Path) -> dict:
    ctx: dict[str, Any] = {"crop_codes": set(), "crop_tokens": set(), "crop_alias": {}, "group_members": {}, "params_keys": set()}
    crops_path = tables_dir / schema["tables"]["crops"]["file"]
    if crops_path.exists():
        _, rows = _read_csv(crops_path, _Report(), "crops")
        for r in rows:
            cc = (r.get("crop_code") or "").strip()
            ctx["crop_codes"].add(cc)
            ctx["crop_alias"][cc] = [a.strip() for a in (r.get("aliases") or "").split(";")]
            for gname in _tokens(r.get("groups") or ""):
                ctx["group_members"].setdefault(gname, []).append(cc)
        ctx["crop_tokens"] = ctx["crop_codes"] | set(ctx["group_members"])
    params_path = tables_dir / schema["tables"]["params_by_season"]["file"]
    if params_path.exists():
        _, rows = _read_csv(params_path, _Report(), "params")
        for r in rows:
            ctx["params_keys"].add(((r.get("crop") or "").strip(), (r.get("param") or "").strip()))
    return ctx


def validate_tables(tables_dir: Path, *, today: date | None = None, schema_path: Path | None = None) -> list[Issue]:
    """이름이 정해진 표 다섯 개를 검사한다. today는 경고(확인일 180일·적용 기간 끝남·마감 지남) 기준일.

    시계는 읽지 않는다(오늘 날짜는 app/config.py 한 곳에서만). today가 None이면 날짜 경고를 건너뛴다.
    """
    tables_dir = Path(tables_dir)
    schema = read_schema(tables_dir, schema_path)
    rep = _Report()
    ctx = _build_ctx(schema, tables_dir)
    for name in TABLE_ORDER:
        file = schema["tables"][name]["file"]
        path = tables_dir / file
        if not path.exists():
            rep.err(file, 0, "", "E04", f"{file} 파일이 없습니다.")
            continue
        if name == "supports":
            _validate_supports(path, schema, ctx, rep, today)
        elif name == "params_by_season":
            _validate_params(path, schema, ctx, rep)
        else:
            _validate_simple(name, path, schema, ctx, rep)
    return rep.items
