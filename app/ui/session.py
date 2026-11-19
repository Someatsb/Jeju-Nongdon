"""상담 세션(Task 7, U07): 쿠키 하나로 찾는 프로세스 안 dict 저장소.

11-13판은 센터 PC 한 대에서 프로그램 하나가 도므로 메모리 dict로 충분하다(외부 세션 부품 없음).
프로그램을 끄면 사라진다. 모르는 세션 id가 오면 받지 않고 새로 만든다.
화면 사이에 넘기는 값만 둔다: `profile`(FarmProfile), `reminder`(ReminderRequest 또는 None), `proxy`(대신 입력 화면이면 True).
문자 번호는 저장·암호화(Task 39) 전까지 이 메모리에만 있고, 로그에는 쓰지 않는다.
"""
import secrets
import time
from collections.abc import Callable
from typing import Any

from starlette.responses import Response

COOKIE = "chaenggim_sid"
IDLE_TTL_S = 30 * 60      # 30분 동안 아무 화면도 열지 않으면 다음 사람에게 앞 사람 상담이 보이지 않게 지운다
MAX_EXPIRED_KEPT = 64


class SessionStore:
    def __init__(self, *, ttl_s: float = IDLE_TTL_S, clock: Callable[[], float] = time.monotonic,
                 max_sessions: int | None = None) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        self._touched: dict[str, float] = {}
        self._expired: dict[str, None] = {}     # 시간이 다 돼 지운 id(입력 화면 안내용, 오래된 것부터 버린다)
        self.ttl_s, self._clock = ttl_s, clock
        self.max_sessions = max_sessions      # 인터넷 판만 둔다(None이면 한도 없음). 새 상담을 만들 때 넘으면 가장 오래 안 쓴 것부터 지운다

    def _make_room(self) -> None:
        now = self._clock()
        for sid in [s for s, t in self._touched.items() if now - t > self.ttl_s]:
            self.drop(sid)
        while len(self._by_id) >= self.max_sessions:
            # 결과 단계(job)까지 간 상담은 나중에 지운다: 쿠키 없이 주소만 계속 부르는 쪽이 남의 진행 중 상담을 밀어내지 못하게
            idle = [s for s in self._touched if self._by_id[s].get("job") is None] or list(self._touched)
            self.drop(min(idle, key=self._touched.get))

    def get(self, sid: str | None) -> dict[str, Any] | None:
        """세션 값(없거나 모르는 id면 None). 마지막으로 만진 지 ttl_s가 넘었으면 지우고 None. 열 때마다 시계를 새로 시작한다."""
        if not sid or sid not in self._by_id:
            return None
        now = self._clock()
        if now - self._touched[sid] > self.ttl_s:
            self.drop(sid)
            self._expired[sid] = None
            while len(self._expired) > MAX_EXPIRED_KEPT:
                self._expired.pop(next(iter(self._expired)))
            return None
        self._touched[sid] = now
        return self._by_id[sid]

    def was_expired(self, sid: str | None) -> bool:
        """이 id의 세션이 시간이 다 돼 지워졌는가(입력 화면의 "새 상담으로 시작합니다" 안내용)."""
        return bool(sid) and sid in self._expired

    def put(self, sid: str | None, **values: Any) -> str:
        """values를 세션에 쓰고 세션 id를 돌려준다. id가 없거나 모르는 값이면 새 세션을 만든다."""
        if sid not in self._by_id or self.get(sid) is None:
            if self.max_sessions is not None:
                self._make_room()
            sid = secrets.token_urlsafe(16)
            self._by_id[sid] = {}
        self._touched[sid] = self._clock()
        self._by_id[sid].update(values)
        return sid

    def drop(self, sid: str | None) -> None:
        """세션을 통째로 지운다(프로필·문자 번호·대신 입력 표시). 없는 id여도 조용히 넘어간다."""
        if sid:
            self._by_id.pop(sid, None)
            self._touched.pop(sid, None)


def profile_session(request) -> dict[str, Any] | None:
    """요청 쿠키의 상담 세션. 프로필이 아직 없으면(입력 전) None — 화면 경로는 이때 입력 화면으로 보낸다."""
    session = request.app.state.sessions.get(request.cookies.get(COOKIE))
    return session if session and "profile" in session else None


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(COOKIE, sid, httponly=True, samesite="strict", path="/")
