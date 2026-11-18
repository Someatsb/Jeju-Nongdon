"""새 공고 맞춰 보기가 볼 공고 고르기. 지원 전체 보기 목록에 '새 공고'로 올라와 있는 것 중 신청이 끝나지 않은 것만 쓴다.

- 표의 제도와 같다고 보여 목록이 숨긴 공고(table_key 가 표에 있음)는 목록에 없으므로 여기서도 빠진다.
- 신청이 끝난 공고는 목록이 '신청이 끝났어요'로 맨 뒤에 두는 것(RANK_ENDED)이다. 끝 날짜를 읽지 못하는 공고는 남는다.
- 목록의 글(신청 기간 한 줄, 가실 곳)을 그대로 쓰도록 공고와 목록 항목을 짝지어 돌려준다. 시계를 읽지 않는다.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from app.catalog.build import Catalog, Entry, build_catalog
from app.catalog.links import LinkTableError, load_links
from app.catalog.notices import NoticeRecord, load_notices
from app.catalog.texts import RANK_ENDED
from app.core.tables_models import TableBundle

_log = logging.getLogger(__name__)


def match_pool(catalog: Catalog, notices: Sequence[NoticeRecord]) -> list[tuple[NoticeRecord, Entry]]:
    """(공고, 목록 항목) 짝. 공고의 원래 순서를 지킨다."""
    out = []
    for n in notices:
        e = catalog.get(n.key)
        if e is None or e.kind != "notice" or e.window_rank == RANK_ENDED:
            continue
        out.append((n, e))
    return out


def load_pool(catalog_dir: Path, tables: TableBundle, today: date) -> list[tuple[NoticeRecord, Entry]]:
    """지원 전체 보기와 같은 자료(catalog_dir)로 목록을 만들어 맞춰 볼 공고를 고른다. 폴더가 없으면 빈 목록."""
    cdir = Path(catalog_dir)
    try:
        links = load_links(cdir / "links.csv")
    except LinkTableError as e:
        _log.warning("원문 링크 표를 읽지 못해 링크 없이 맞춥니다: %s", e)
        links = {}
    notices = load_notices(cdir / "notices")
    return match_pool(build_catalog(tables, today, links, notices), notices)
