"""제주데이터허브 1361 클라이언트(Task 26, U26). 표준 라이브러리만 쓴다.

호출: GET {base}/api/proxy/{dataKey}/{projectKey}?startDate=YYYYMMDD&endDate=YYYYMMDD&cultivar=품종&limit=100
응답: {"totCnt", "hasMore", "data": [{baseDate, cultivar, averagePrice, transactionVolume, transactionAmount}]}
한 번에 100행까지, 오프셋이 없다. 응답이 가득 찼거나 hasMore이면 날짜 창을 반으로 나눠 다시 받는다.
하루 창도 가득 차면 그날을 partial_days에 적는다. 프로젝트 키는 주소에 들어가므로 오류 문장·기록 어디에도 주소를 쓰지 않는다.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable
from urllib.parse import quote, urlencode

__all__ = ["HubClient", "HubError", "HubQuotaError", "Http", "urlopen_bytes"]

Http = Callable[[str], bytes]
TIMEOUT_S = 20
PAGE_LIMIT = 100


class HubError(Exception):
    """허브 호출 실패. 메시지는 한국어이고 키·주소를 담지 않는다."""


class HubQuotaError(HubError):
    """하루 호출 상한에 닿았다."""


def urlopen_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jeju-chaenggim/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


class HubClient:
    DATA_KEY_1361 = "13t6aat1at6166111Dtt1taa1ta1661t"     # 1361 품종별 일일 거래 통계(research/hub-api-verified.md)

    def __init__(self, base_url: str, key: str, *, http: Http | None = None, max_calls: int | None = None):
        if not key:
            raise HubError("허브 프로젝트 키가 없습니다. 키 설정에서 허브 키를 먼저 넣어 주세요.")
        self._base = base_url.rstrip("/")
        self._key = key
        self._http = http or urlopen_bytes
        self._max = max_calls
        self.calls = 0
        self.partial_days: list[str] = []

    def url_1361(self, cultivar: str, start: str, end: str, limit: int = PAGE_LIMIT) -> str:
        query = urlencode({"startDate": start, "endDate": end, "cultivar": cultivar, "limit": limit}, quote_via=quote)
        return f"{self._base}/api/proxy/{self.DATA_KEY_1361}/{quote(self._key, safe='')}?{query}"

    def _page(self, cultivar: str, start: str, end: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
        if self._max is not None and self.calls >= self._max:
            raise HubQuotaError(f"오늘 허브 호출 한도({self._max}회)에 닿았습니다. 내일 다시 갱신해 주세요.")
        self.calls += 1
        try:
            raw = self._http(self.url_1361(cultivar, start, end, limit))
        except urllib.error.HTTPError as e:
            raise HubError(f"허브가 오류로 답했습니다(HTTP {e.code}). 잠시 뒤 다시 해 보세요.") from None
        except (OSError, ValueError, http.client.HTTPException):
            raise HubError("허브에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
        try:
            body = json.loads(raw)
            data = body["data"]
            if not isinstance(data, list):
                raise TypeError
            return data, bool(body.get("hasMore", False))
        except (ValueError, KeyError, TypeError):
            raise HubError("허브 응답을 읽지 못했습니다(형식이 다릅니다).") from None

    def fetch_1361(self, cultivar: str, start: str, end: str, *, limit: int = PAGE_LIMIT) -> list[dict[str, Any]]:
        rows, more = self._page(cultivar, start, end, limit)
        if not more and len(rows) < limit:
            return rows
        a, b = _d(start), _d(end)
        if a >= b:
            self.partial_days.append(start)          # 하루치도 한 번에 못 받았다: 받은 만큼만 쓰고 알린다
            return rows
        mid = a + timedelta(days=(b - a).days // 2)
        left = self.fetch_1361(cultivar, start, mid.strftime("%Y%m%d"), limit=limit)
        right = self.fetch_1361(cultivar, (mid + timedelta(days=1)).strftime("%Y%m%d"), end, limit=limit)
        return left + right
