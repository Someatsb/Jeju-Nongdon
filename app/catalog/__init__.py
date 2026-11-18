"""지원 전체 보기의 자료(화면 말고 자료): 표의 지원을 제도로 묶고, 태그·기간·금액·링크·새 공고를 모은다.

화면이 쓰는 것:
    from app.catalog import load_catalog
    catalog = load_catalog(root, tables, as_of)        # Catalog (entries, filters(), select(), get(), key_for_name())
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.catalog.build import (
    Catalog,
    Contact,
    Entry,
    FilterDef,
    Variant,
    base_key,
    build_catalog,
    key_for_name,
    support_href,
)
from app.catalog.links import Link, LinkTableError, load_links
from app.catalog.notices import NoticeRecord, load_notices
from app.core.tables_models import TableBundle

__all__ = ["Catalog", "Contact", "Entry", "FilterDef", "Link", "LinkTableError", "NoticeRecord", "Variant", "base_key",
           "build_catalog", "key_for_name", "load_catalog", "load_links", "load_notices", "support_href"]


def load_catalog(root: Path, tables: TableBundle, as_of: date) -> Catalog:
    """설치 폴더(root)의 data/catalog 를 읽어 목록 자료를 만든다. links.csv 나 notices 폴더가 없어도 된다."""
    cdir = Path(root) / "data" / "catalog"
    return build_catalog(tables, as_of, load_links(cdir / "links.csv"), load_notices(cdir / "notices"))
