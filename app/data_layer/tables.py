"""표 로더(Task 3, U03). 이름이 정해진 표만 읽어 TableBundle로 넘긴다.

읽는 파일: supports.csv, params_by_season.csv, crops.csv, interventions.csv, offices.csv,
insurance.csv(있을 때만, Task 11). 같은 폴더의 다른 CSV는 읽지 않는다(`*.csv` 금지).

1. validate_tables로 먼저 검사하고, 오류가 한 건이라도 있으면 TableLoadError(읽지 않음).
2. schema.json 컬럼 형(type)대로 칸을 바꾼다: int → int, float → Decimal, date → date,
   ';' 목록 → tuple, 빈칸 → 기본값(None·()).
3. hold 행도 programs에 넣는다(status="hold"). 기준일까지 시작된 가장 최근 confirmed 회차가 있는
   제도는 그보다 앞 회차 행을 hold(hold_reason="superseded")로 바꾼다(mark_superseded).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from app.core.models import Program, SourceRef
from app.core.tables_models import Crop, InsuranceProduct, Intervention, Office, SeasonParam, TableBundle
from app.data_layer.validate import Issue, read_csv_rows, read_schema, validate_tables

INSURANCE_FILE = "insurance.csv"  # Task 11이 만든다. 없으면 insurance=()

__all__ = ["TableBundle", "TableLoadError", "load_tables", "mark_superseded"]


class TableLoadError(Exception):
    """표를 읽지 않은 이유. issues는 오류 목록(한국어 문장)."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        head = "\n".join(f"- {i.file} {i.message_ko}" for i in issues[:10])
        more = f"\n…외 {len(issues) - 10}건" if len(issues) > 10 else ""
        super().__init__(f"표에 오류가 {len(issues)}건 있어 읽지 않았습니다.\n{head}{more}")


def _load_error(file: str, row: int, msg: str) -> TableLoadError:
    return TableLoadError([Issue(file=file, row_excel=row, column="", level="error", message_ko=msg, code="L01")])


# --- 행 상태 --------------------------------------------------------------------------------

def _variant(p: Program) -> str:
    return p.id.partition("#")[2]          # "NAT-CROP-INS@2026#마늘" → "마늘"


def _first_year(edition: str) -> int | None:
    return int(edition[:4]) if edition[:4].isdigit() else None


def mark_superseded(programs: Iterable[Program], as_of: date) -> tuple[Program, ...]:
    """같은 제도·같은 '#작물·지역'(confirmed 행에 #가 없으면 모든 갈래)마다, 첫 해가 기준일 연도 이하인
    confirmed 행 중 가장 늦은 첫 해를 '현재 회차'로 잡고, 그보다 첫 해가 이른 행(prior_year_reference든
    옛 confirmed든)을 hold/superseded로 바꾼다. 첫 해 = edition 앞 네 자리("2027-28" → 2027).
    그래서 2028-01-10에도 2027-28 confirmed가 2026-27 행을 가린다. 기준일보다 미래 회차는 셈하지 않는다."""
    programs = tuple(programs)
    latest: dict[tuple[str, str], int] = {}
    for p in programs:
        first = _first_year(p.edition)
        if p.status == "confirmed" and first is not None and first <= as_of.year:
            k = (p.program_key, _variant(p))
            latest[k] = max(latest.get(k, first), first)

    def superseded(p: Program) -> bool:
        first = _first_year(p.edition)
        if p.status == "hold" or first is None:
            return False
        cur = [y for y in (latest.get((p.program_key, _variant(p))), latest.get((p.program_key, ""))) if y is not None]
        return bool(cur) and first < max(cur)

    # model_copy(update=)는 검증을 건너뛰므로 다시 만든다(Task 2 리뷰).
    return tuple(Program.model_validate({**p.model_dump(), "status": "hold", "hold_reason": "superseded"})
                 if superseded(p) else p for p in programs)


# --- 칸 변환 --------------------------------------------------------------------------------

def _typed(cols: list[dict], row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in cols:
        key, typ = c["key"], c["type"]
        v = (row.get(key) or "").strip()
        if v == "":
            continue                        # 모델 기본값(None·())
        if typ == "int":
            out[key] = int(v)
        elif typ == "float":
            out[key] = Decimal(v)
        elif typ == "date":
            out[key] = date.fromisoformat(v)
        elif typ.startswith("list_"):
            toks = [t.strip() for t in v.split(";") if t.strip()]
            out[key] = tuple(int(t) for t in toks) if typ == "list_int" else tuple(toks)
        else:
            out[key] = v
    return out


def _build(model: type, name: str, schema: dict, tables_dir: Path) -> tuple[Any, ...]:
    td = schema["tables"][name]
    _, rows = read_csv_rows(tables_dir / td["file"])
    out = []
    for i, r in enumerate(rows):
        try:
            out.append(model.model_validate(_typed(td["columns"], r)))
        except (ValidationError, ValueError) as e:
            raise _load_error(td["file"], i + 2, f"{i + 2}행을 표 모델로 바꾸지 못했습니다: {e}") from e
    return tuple(out)


_WINDOW = re.compile(r"^\d{2}-\d{2}~\d{2}-\d{2}$")
INSURANCE_COLUMNS = ("product_id", "crop_keys", "windows", "min_age", "max_age", "needs_mgmt", "office_id",
                     "subsidy_text", "extra_requirement", "source_id", "source_url", "verified_date")


def _load_insurance(path: Path) -> tuple[InsuranceProduct, ...]:
    """insurance.csv(Task 11) 잠정 컬럼: product_id, crop_keys(;), windows(MM-DD~MM-DD;…), min_age, max_age,
    needs_mgmt(Y/빈칸), office_id, subsidy_text, extra_requirement, source_id, source_url, verified_date.
    머리글에 하나라도 없으면 읽지 않는다(오타 난 crop_keys가 빈칸 = '모든 작물'로 읽히지 않게)."""
    if not path.exists():
        return ()
    header, rows = read_csv_rows(path)
    missing = [c for c in INSURANCE_COLUMNS if c not in header]
    if missing:
        raise TableLoadError([
            Issue(file=path.name, row_excel=1, column=c, level="error", code="L02",
                  message_ko=f"{path.name}에 '{c}' 컬럼이 없습니다. 머리글 오타인지 확인해 주세요.")
            for c in missing
        ])
    out = []
    for i, r in enumerate(rows):
        def g(k: str) -> str:
            return (r.get(k) or "").strip()

        try:
            wins = [w.strip() for w in g("windows").split(";") if w.strip()]
            if not all(_WINDOW.match(w) for w in wins):
                raise ValueError(f"가입 기간 '{g('windows')}'은 'MM-DD~MM-DD' 모양이어야 합니다")
            crops = tuple(t.strip() for t in g("crop_keys").split(";") if t.strip())
            out.append(InsuranceProduct(
                product_id=g("product_id"), crop_keys=crops or None,
                windows=tuple(tuple(w.split("~")) for w in wins),
                min_age=int(g("min_age")) if g("min_age") else None,
                max_age=int(g("max_age")) if g("max_age") else None,
                needs_mgmt=g("needs_mgmt") == "Y", office_id=g("office_id"), subsidy_text=g("subsidy_text"),
                extra_requirement=g("extra_requirement") or None,
                source=SourceRef(source_id=g("source_id"), url=g("source_url") or None,
                                 as_of=date.fromisoformat(g("verified_date"))),
            ))
        except (ValidationError, ValueError) as e:
            raise _load_error(path.name, i + 2, f"{i + 2}행을 보험 상품으로 바꾸지 못했습니다: {e}") from e
    return tuple(out)


def _tables_verified(programs: tuple[Program, ...]) -> date:
    """지원 표 확인일 = 종이에 나갈 수 있는(hold 아닌) 행 중 가장 오래된 확인일. 그런 행이 없으면 전체 중."""
    dates = [p.verified_date for p in programs if p.status != "hold" and p.verified_date]
    dates = dates or [p.verified_date for p in programs if p.verified_date]
    if not dates:
        raise _load_error("supports.csv", 0, "지원 표에 확인일이 있는 행이 없습니다.")
    return min(dates)


# --- 로더 -----------------------------------------------------------------------------------

def load_tables(tables_dir: Path, as_of: date, *, schema_path: Path | None = None) -> TableBundle:
    """표 폴더를 검사하고 읽는다. as_of는 superseded 판단에만 쓴다(행을 기간으로 거르지 않음)."""
    tables_dir = Path(tables_dir)
    schema = read_schema(tables_dir, schema_path)
    errors = [i for i in validate_tables(tables_dir, schema_path=schema_path) if i.level == "error"]
    if errors:
        raise TableLoadError(errors)
    programs = mark_superseded(_build(Program, "supports", schema, tables_dir), as_of)
    offices = _build(Office, "offices", schema, tables_dir)
    return TableBundle(
        programs=programs,
        params=_build(SeasonParam, "params_by_season", schema, tables_dir),
        crops=_build(Crop, "crops", schema, tables_dir),
        interventions=_build(Intervention, "interventions", schema, tables_dir),
        insurance=_load_insurance(tables_dir / INSURANCE_FILE),
        offices={o.office_id: o for o in offices},   # TableBundle이 읽기 전용 매핑으로 감싼다
        verified_date=_tables_verified(programs),
    )
