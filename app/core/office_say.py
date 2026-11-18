"""가실 곳 이름을 화면·종이에 보일 때 어르신이 읽는 말로 한 가지로 맞춘다(2026-11-15 표현 정리).

자료(supports.csv office 칸)는 같은 곳을 지원마다 다르게 적었다('농지 소재 읍·면·동' · '농지 소재지 읍면동사무소' · '과원 소재지 …' 등).
표와 AI 입력은 고치지 않고, 보일 때만 이 함수로 바꾼다. 곳의 뜻·전화번호·숫자는 그대로이고 이름의 표기만 같아진다.
"""
from __future__ import annotations

import re

_EMD = r"읍[·ㆍ]?면[·ㆍ]?동"
# (찾는 글, 바꿀 글) 순서대로 적용한다. 앞의 것이 뒤의 것의 입력이 될 수 있다.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"건보공단"), "건강보험공단"),
    (re.compile(rf"농지\s*소재지?\s*({_EMD})(?:\s*사무소)?"), r"농지가 있는 \1"),
    (re.compile(r"농지\s*소재지?\s*지역\s*농협"), "농지가 있는 곳의 지역농협"),
    (re.compile(r"농지\s*소재지?"), "농지가 있는"),
    (re.compile(r"과원\s*소재지"), "과수원이 있는"),
    (re.compile(r"주소지\s*읍\s*\(면\)\s*사무소\s*및\s*동\s*주민센터"), "주소지 읍·면사무소, 동 주민센터"),
    (re.compile(rf"주소지\s*{_EMD}"), "주소지 읍·면사무소, 동 주민센터"),
    (re.compile(r"서귀포시\s*관내"), "서귀포시 안의"),
    (re.compile(r"거주지\s*지역\s*농협"), "사시는 곳의 지역농협"),
    (re.compile(r"관내"), "안의"),
    (re.compile(r"읍면동"), "읍·면·동"),
    (re.compile(r"읍면(?!동)"), "읍·면"),
)
_EXACT = {"별도 신청 없음(경영체 정보 기준) - 지역농협·농관원 확인":
          "따로 신청하지 않아요. 농업경영체에 등록한 내용으로 정해져요. 지역농협이나 농산물품질관리원에 물어보세요"}
_ONLINE = re.compile(r"\(비대면:\s*(.*?)\)")


def office_say(name: str | None) -> str | None:
    """'건보공단 지사' → '건강보험공단 지사', '농지 소재 읍·면·동' → '농지가 있는 읍·면·동', '과원 소재지 읍·면·동' → '과수원이 있는 읍·면·동',
    '주소지 읍(면)사무소 및 동 주민센터' → '주소지 읍·면사무소, 동 주민센터', '(비대면: 농업e지·ARS 1334)' → '(집에서는 농업e지나 전화 1334)'.
    농관원은 처음 나올 때 '농산물품질관리원(농관원)'으로 푼다. 못 알아보는 이름은 그대로."""
    if not name:
        return name
    if name in _EXACT:
        return _EXACT[name]
    for rx, repl in _RULES:
        name = rx.sub(repl, name)
    m = _ONLINE.search(name)
    if m:
        name = name.replace(m[0], "(집에서는 " + m[1].replace("·", "나 ").replace("ARS ", "전화 ") + ")")
    if "농관원" in name and "농산물품질관리원" not in name:
        name = name.replace("농관원", "농산물품질관리원(농관원)", 1)
    return name
