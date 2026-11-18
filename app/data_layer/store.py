"""익명 기록(Task 26, U26). 상담번호 6자리와 띠(월·행정시·나이대·면적대)·코드만 logs/sessions/YYYY-MM.jsonl에 남긴다.

읍면동·태어난 해·면적 원값은 어떤 칸에도 없다(SessionLog가 extra="forbid"이고 band_profile은 띠만 만든다).
이 파일은 시계를 읽지 않는다. 기준일 as_of는 부르는 쪽이 넘긴다.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.models import FarmProfile

__all__ = ["ALPHABET", "SessionLog", "age_band", "area_band", "band_profile", "log", "new_session"]

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # 0/O, 1/I 없음
ID_LEN = 6
LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
_MONTH = re.compile(r"20\d\d-(0[1-9]|1[0-2])")
_ID = re.compile(rf"[{ALPHABET}]{{{ID_LEN}}}")
HA = 10_000                                          # ㎡


class SessionLog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    month: str                                       # YYYY-MM
    city: Literal["제주시", "서귀포시"]
    age_band: str
    area_band: str
    crops: tuple[str, ...]
    mgmt_status: str
    sales_channel: str
    matched_ids: tuple[str, ...]
    already_ids: tuple[str, ...]
    first_heard_count: int
    prereq_ids: tuple[str, ...]
    printed: bool
    reminder_saved: bool = False

    @field_validator("month")
    @classmethod
    def _month(cls, v: str) -> str:
        if not _MONTH.fullmatch(v):
            raise ValueError("월은 2026-11처럼 YYYY-MM으로 적어 주세요.")
        return v


def new_session(as_of: date) -> str:
    """상담번호 6자리. 기준일은 번호에 넣지 않는다(번호만으로 날짜를 짐작하지 못하게)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))


def log(session_id: str, entry: SessionLog, *, logs_dir: Path | None = None) -> dict:
    """entry의 월 파일에 JSON 한 줄을 덧붙이고, 적은 dict를 돌려 준다."""
    if not _ID.fullmatch(session_id):
        raise ValueError(f"상담번호 형식이 아닙니다: {session_id!r}")
    row = {"session": session_id, **entry.model_dump(mode="json")}
    path = Path(logs_dir or LOGS_DIR) / "sessions" / f"{entry.month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def age_band(birth_year: int | None, as_of: date) -> str:
    if birth_year is None:
        return "모름"
    age = as_of.year - birth_year
    if age < 30:
        return "30세 미만"
    return "80대 이상" if age >= 80 else f"{age // 10 * 10}대"


def area_band(area_m2: int | None) -> str:
    if area_m2 is None:
        return "모름"
    for limit, label in ((HA // 2, "≤0.5ha"), (HA, "0.5~1ha"), (2 * HA, "1~2ha"), (5 * HA, "2~5ha")):
        if area_m2 <= limit:
            return label
    return "5ha+"


def band_profile(profile: FarmProfile, as_of: date, *, city: Literal["제주시", "서귀포시"],
                 matched_ids: tuple[str, ...] = (), prereq_ids: tuple[str, ...] = (), printed: bool = False,
                 reminder_saved: bool = False) -> SessionLog:
    """프로필에서 띠만 뽑는다. 행정시는 읍면동 이름을 로그에 넣지 않으려고 부르는 쪽(화면의 읍면동 목록)이 준다."""
    area = profile.total_area_m2
    if area is None and profile.crops and all(c.area_m2 is not None for c in profile.crops):
        area = sum(c.area_m2 for c in profile.crops)
    channels = {c.sales_channel for c in profile.crops}
    return SessionLog(
        month=as_of.strftime("%Y-%m"), city=city, age_band=age_band(profile.birth_year, as_of), area_band=area_band(area),
        crops=tuple(c.crop_code for c in profile.crops), mgmt_status=profile.mgmt_status,
        sales_channel=channels.pop() if len(channels) == 1 else "mixed" if channels else "unknown",
        matched_ids=tuple(matched_ids), already_ids=tuple(sorted(profile.already_receiving)),
        first_heard_count=len(profile.first_heard), prereq_ids=tuple(prereq_ids), printed=printed,
        reminder_saved=reminder_saved)
