"""공고 에이전트 결과를 목록에 올린다(설계서 B-3). 직원 확정은 없다. 아래를 모두 채운 사업만 파일이 된다.

- 읽을 수 있는 문서이고(UNREADABLE 아님), 개인정보 차단이 아니고(BLOCKED_PII 아님), 농가 대상 지원이다(NOT_RELEVANT 아님).
- 이름이 있다(공고 원문에서 근거를 확인한 이름, 또는 표의 같은 제도 이름).
- 근거 문장이 원문에 글자 그대로 있는 이름표가 2개 이상이다(여기서 한 번 더 원문과 대조한다).
  1개뿐이면 원문과 맞는 신청 기간 또는 접수처(apply_where)가 있어야 한다.
글은 근거 대조를 통과한 칸의 인용문(원문 그대로)만 싣는다. 대조에 실패한 칸, 개인정보가 든 글은 싣지 않는다.
같은 주소(url)의 공고 파일이 이미 있으면 새로 올린 뒤 그 옛 파일을 지운다(AI 가 지은 이름이 달라져도 목록에 같은 공고가 둘 생기지 않게).
주소가 달라도 이름이 같은 사업(notices.business_key)이 이미 목록에 있으면 올리지 않는다(같은 사업의 다른 글이 겹치지 않게).
다만 새 글에 접수처(apply_where)가 있고 옛 글에는 없으면 옛 것을 새 것으로 바꾼다(더 온전한 글).
못 올리면 이유를 돌려준다. 표(supports.csv)는 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.agents.notice import NoticeResult
from app.catalog.links import is_official_url
from app.catalog.notices import NOTICE_VERSION, business_key, enough_tags
from app.data_layer.docs_in import Doc
from app.tools.draft_checks import NONE_WORD, ProgramBundle, pii_labels, squash, tag_problem
from app.tools.models import DraftProgram

MAX_PUBLISHED_TAGS = 4
TARGET_FIELDS = ("applicant", "crop_in", "crop_not_in", "sex", "min_age", "max_age", "born_before", "born_after",
                 "min_residence_years", "min_farming_years", "needs_mgmt", "min_mgmt_years", "min_ha", "max_ha",
                 "max_owned_ha", "owns_land", "land_hold_years", "needs_coop", "needs_selfpay_fund", "needs_enrollment",
                 "needs_cert", "income_test", "income_max_manwon", "facility", "region_in", "area_type_in", "health_ins_in")
CONTENT_FIELDS = ("amount_type", "amount_value", "amount_min", "amount_max", "period", "calc_basis", "units_per_ha",
                  "unit_name", "cap_units", "rate_pct_min", "rate_pct_max", "cap_won", "amount_note", "payout_timing",
                  "amount_2plus_each")
PERIOD_FIELDS = ("apply_start", "apply_end")
NOT_PUBLISHED = {"UNREADABLE": "읽을 수 없는 문서라 목록에 올리지 않았습니다",
                 "BLOCKED_PII": "개인정보가 있어 목록에 올리지 않았습니다",
                 "NOT_RELEVANT": "농가에 닿는 지원사업이 아니라서 목록에 올리지 않았습니다"}


@dataclass
class PublishReport:
    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)       # 못 올린 이유(한국어)
    replaced: list[str] = field(default_factory=list)      # 같은 주소라서 지운 옛 공고 파일 이름
    upgraded: list[str] = field(default_factory=list)      # 같은 사업의 더 온전한 글(접수처 있음)로 바꾼 것: 사람이 읽는 문장
    superseded: list[Path] = field(default_factory=list)   # 위에서 지운 옛 파일(이름이 같은 사업, 주소는 다름)


def _present(v: Any) -> bool:
    return not (v is None or v == "" or v == [] or v == ())


def _verified_quotes(p: DraftProgram, names: tuple[str, ...], doc_squashed: str) -> list[str]:
    """칸들의 인용 중 원문에 글자 그대로 있는 것(중복 없이, 칸 차례)."""
    out: list[str] = []
    for name in names:
        f = p.fields.get(name)
        q = (f.quote or "").strip() if f is not None and _present(f.value) else ""
        if q and squash(q) in doc_squashed and q not in out and not pii_labels(q):
            out.append(q)
    return out


def _says_none(f: Any) -> bool:
    """칸 값이 "없음"(공고에 접수처가 없다는 뜻)인가."""
    return f is not None and isinstance(f.value, str) and f.value.strip() == NONE_WORD


def _name_of(p: DraftProgram, doc_squashed: str, bundle: ProgramBundle) -> tuple[str | None, str | None]:
    """(이름, 표의 같은 제도 열쇠). 이름은 원문 근거를 확인한 name 칸, 없으면 표의 같은 제도 이름."""
    rows = {r.id: r for r in bundle.programs}
    keys = {r.program_key for r in bundle.programs}
    row = rows.get(p.match_id or "")
    table_key = row.program_key if row else (p.program_key if p.program_key in keys else None)
    f = p.fields.get("name")
    if f is not None and isinstance(f.value, str) and f.value.strip() and f.quote and squash(f.quote) in doc_squashed \
            and not pii_labels(f.value):
        return f.value.strip(), table_key
    if row is not None and row.name:
        return row.name, table_key
    return None, table_key


def _stem(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("._")[:40] or "notice"


def _existing_url(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("url")
    except (OSError, ValueError, AttributeError):
        return None


def _stored_by_business(out_dir: Path, skip: set[Path]) -> dict[str, tuple[Path, str, bool]]:
    """이미 올라간 공고(skip 제외)의 {사업 열쇠: (파일, 이름, 접수처 있는지)}. 열쇠가 같은 것이 여럿이면 접수처 있는 쪽, 같으면 파일 이름이 뒤인 쪽."""
    found: dict[str, tuple[Path, str, bool]] = {}
    for q in sorted(out_dir.glob("*.json")) if out_dir.is_dir() else []:
        if q in skip:
            continue
        try:
            raw = json.loads(q.read_text(encoding="utf-8"))
            name, where = str(raw.get("name") or "").strip(), bool(str(raw.get("apply_where") or "").strip())
        except (OSError, ValueError, AttributeError):
            continue
        k = business_key(name)
        if k is not None and (k not in found or where >= found[k][2]):
            found[k] = (q, name, where)
    return found


def publish_notice(result: NoticeResult, doc: Doc | None, *, url: str | None, read_date: date, root: Path,
                   bundle: ProgramBundle, catalog_dir: Path | None = None) -> PublishReport:
    """사업마다 조건을 따져 <catalog_dir>/notices/<이름>.json(기본 root/data/catalog)을 쓴다."""
    report = PublishReport()
    url = url if url and is_official_url(url) else None        # 공식 사이트 주소가 아니면 링크 없이 올린다
    if result.decision in NOT_PUBLISHED:
        report.skipped.append(NOT_PUBLISHED[result.decision])
        return report
    if doc is None:
        report.skipped.append("문서를 읽지 못해 목록에 올리지 않았습니다")
        return report
    if not result.programs:
        report.skipped.append("초안에 사업이 없어 목록에 올리지 않았습니다")
        return report
    squashed = squash(doc.text)
    out_dir = (Path(catalog_dir) if catalog_dir is not None else Path(root) / "data" / "catalog") / "notices"
    same_url = sorted(q for q in out_dir.glob("*.json") if url and _existing_url(q) == url) if out_dir.is_dir() else []   # 올리기 전에 있던, 같은 주소의 파일들
    for n, p in enumerate(result.programs, start=1):
        name, table_key = _name_of(p, squashed, bundle)
        if not name:
            report.skipped.append(f"사업 {n}: 이름을 원문에서 확인하지 못해 올리지 않았습니다")
            continue
        tags, seen = [], set()
        for t in p.tags:
            label = t.label.strip()
            if tag_problem(t, squashed) is None and label not in seen:
                seen.add(label)
                tags.append({"label": label, "quote": (t.quote or "").strip(), "anchor": t.anchor})
        period = " ".join(_verified_quotes(p, PERIOD_FIELDS, squashed))
        where = _verified_quotes(p, ("office",), squashed) if not _says_none(p.fields.get("office")) else []   # 접수처·신청 방법. 공고에 없으면 빈 글
        if not enough_tags(len(tags), bool(period or where)):
            why = "원문과 맞는 조건 이름표가 없어" if not tags else "이름표가 하나뿐이고 원문과 맞는 기간·접수처가 없어"
            report.skipped.append(f"{name}: {why} 올리지 않았습니다")
            continue
        agency = ""
        af = p.fields.get("agency")
        if af is not None and isinstance(af.value, str) and af.quote and squash(af.quote) in squashed and not pii_labels(af.value) \
                and squash(af.value) and squash(af.value) in squash(af.quote):       # 담당 기관은 공고에 적힌 부서 이름 그대로(인용 안에 그 이름이 있어야 한다)
            agency = af.value.strip()
        record = {"version": NOTICE_VERSION, "name": name, "agency": agency, "apply_where": "\n".join(where),
                  "apply_period": period,
                  "target": "\n".join(_verified_quotes(p, TARGET_FIELDS, squashed)),
                  "content": "\n".join(_verified_quotes(p, CONTENT_FIELDS, squashed)),
                  "tags": tags[:MAX_PUBLISHED_TAGS], "url": url, "read_date": read_date.isoformat(),
                  "decision": result.decision, "table_key": table_key}
        if pii_labels(json.dumps(record, ensure_ascii=False)):
            report.skipped.append(f"{name}: 개인정보가 있어 올리지 않았습니다")
            continue
        same_biz = None
        key = business_key(name)
        if key is not None:
            same_biz = _stored_by_business(out_dir, {*same_url, *report.written}).get(key)
            if same_biz is not None and not (record["apply_where"] and not same_biz[2]):
                report.skipped.append(f"이미 목록에 있는 사업이라 올리지 않았습니다: {same_biz[1]}")
                continue
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_stem(name)}.json"
        if path.exists() and _existing_url(path) != url:                                         # 다른 공고의 같은 이름
            path = out_dir / f"{_stem(name)}-{hashlib.sha256((url or name).encode('utf-8')).hexdigest()[:8]}.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        report.written.append(path)
        if same_biz is not None:                                    # 더 온전한 글로 바꾼다: 새로 쓴 뒤 옛 파일을 지운다
            if same_biz[0] != path and same_biz[0].exists():
                same_biz[0].unlink()
                report.superseded.append(same_biz[0])
            report.upgraded.append(f"같은 사업의 더 온전한 글로 바꿨습니다: {same_biz[1]}")
    if report.written:                                              # 새로 올린 것이 있을 때만, 같은 주소의 옛 파일을 지운다
        for old in same_url:
            if old not in report.written and old.exists():
                old.unlink()
                report.replaced.append(old.name)
    return report
