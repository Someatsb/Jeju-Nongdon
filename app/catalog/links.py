"""원문 링크 표 data/catalog/links.csv 읽기(설계서 B-4).

열: program_key, url, link_kind, page_title, checked_date, note.
사람이 직접 열어 확인한 공식 주소만 넣는다. 주소는 https 이고 공식 도메인(go.kr, or.kr, apfs.kr, gov.kr)이어야 하며,
아니면 파일 전체를 읽지 않고 한국어 오류로 알린다. 파일이 없으면 링크가 없는 것으로 본다(오류 아님).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

LINK_KINDS = ("공고 원문", "사업 안내", "신청 안내(정부24)", "통합 공고")
OFFICIAL_SUFFIXES = ("go.kr", "or.kr", "apfs.kr", "gov.kr")
COLUMNS = ("program_key", "url", "link_kind", "page_title", "checked_date", "note")
OPEN_NOTE = "새 창이 열려요. 다 보시면 그 창을 닫으세요"


class LinkTableError(ValueError):
    """links.csv 를 읽을 수 없다. 메시지는 한국어."""


@dataclass(frozen=True)
class Link:
    program_key: str
    url: str
    kind: str
    title: str
    checked: date
    note: str = ""


def is_official_url(url: str) -> bool:
    """https 이고 공식 도메인(정확히 그 도메인이거나 그 아래 이름)이며 사용자 정보·특수 포트가 없는 주소."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443) or not host:
        return False
    return any(host == s or host.endswith("." + s) for s in OFFICIAL_SUFFIXES)


def load_links(path: Path) -> dict[str, Link]:
    """program_key → Link. 파일이 없으면 빈 사전."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise LinkTableError(f"원문 링크 표의 열이 맞지 않습니다({path.name}). 열: {', '.join(COLUMNS)}")
        out: dict[str, Link] = {}
        for n, row in enumerate(reader, start=2):
            key, url, kind = (row["program_key"] or "").strip(), (row["url"] or "").strip(), (row["link_kind"] or "").strip()
            where = f"원문 링크 표 {n}번째 줄"
            if not key or key in out:
                raise LinkTableError(f"{where}: 제도 열쇠가 비었거나 겹칩니다({key})")
            if not is_official_url(url):
                raise LinkTableError(f"{where}: 공식 사이트(go.kr, or.kr, apfs.kr, gov.kr)의 https 주소만 쓸 수 있습니다({url})")
            if kind not in LINK_KINDS:
                raise LinkTableError(f"{where}: 링크 종류가 맞지 않습니다({kind}). 쓸 수 있는 것: {', '.join(LINK_KINDS)}")
            try:
                checked = date.fromisoformat((row["checked_date"] or "").strip())
            except ValueError:
                raise LinkTableError(f"{where}: 확인한 날짜가 연-월-일 꼴이 아닙니다") from None
            out[key] = Link(key, url, kind, (row["page_title"] or "").strip(), checked, (row["note"] or "").strip())
    return out
