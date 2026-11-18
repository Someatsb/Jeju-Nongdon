import re
from app.catalog.layout import _MANY_PLACES


def test_phone_is_not_shown_for_places_that_are_not_one_desk():
    """검수 2026-11-15: 지역농협·읍·면·동처럼 한 곳이 아닌 곳에는 담당과 번호를 붙이지 않는다."""
    for w in ("지역농협", "주소지 읍·면사무소", "농지 소재 읍·면·동", "읍·면·동 주민센터", "외 2곳"):
        assert _MANY_PLACES.search(w), w
    for w in ("건강보험공단 지사", "농산물품질관리원", "제주도 친환경농업정책과"):
        assert not _MANY_PLACES.search(w), w
