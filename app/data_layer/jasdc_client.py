"""감귤출하연합회 수급센터 클라이언트(Task 26, U26). 노지온주(kind=1) 일별.

호출: GET {base}/api/proxy/price/term-day.jsp?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&yearTerm=1&kind=1
응답: {"dataList": [{dealDate, avg(원/5kg 상자), high, low, deal(톤), ...}]}
deal=0(거래 없음) 행은 뺀다. 5kg 상자 단위 값이 아니면(원/kg로 보이거나 터무니없으면) 이번 달 전체를 거부한다.
"""
from __future__ import annotations

import calendar
import http.client
import json
import re
import urllib.error
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from app.data_layer.hub_client import Http, urlopen_bytes

__all__ = ["JasdcClient", "JasdcError", "BOX_WON_MIN", "BOX_WON_MAX"]

BOX_WON_MIN, BOX_WON_MAX = 500, 200_000          # 5kg 상자당 원. 실측 평균은 약 5천~2만, 최고가는 4만 안팎
_MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")


class JasdcError(Exception):
    """수급센터 호출·응답 오류. 메시지는 한국어."""


def _dec(v: Any, what: str) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise JasdcError(f"수급센터 응답의 {what} 값을 읽지 못했습니다.") from None


class JasdcClient:
    def __init__(self, base_url: str = "https://jasdc.or.kr", *, http: Http | None = None):
        self._base = base_url.rstrip("/")
        self._http = http or urlopen_bytes
        self.notes: list[str] = []                 # 건너뛴 줄 안내(한국어)

    def url_month(self, month: str) -> str:
        m = _MONTH.fullmatch(month)
        if not m:
            raise ValueError(f"월은 2026-11처럼 YYYY-MM으로 넣어 주세요: {month}")
        y, mo = int(m[1]), int(m[2])
        last = calendar.monthrange(y, mo)[1]
        q = urlencode({"startDate": f"{month}-01", "endDate": f"{month}-{last:02d}", "yearTerm": 1, "kind": 1})
        return f"{self._base}/api/proxy/price/term-day.jsp?{q}"

    def fetch_citrus(self, month: str) -> list[dict[str, str]]:
        url = self.url_month(month)
        try:
            raw = self._http(url)
        except urllib.error.HTTPError as e:
            raise JasdcError(f"수급센터가 오류로 답했습니다(HTTP {e.code}).") from None
        except (OSError, ValueError, http.client.HTTPException):
            raise JasdcError("수급센터에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
        try:
            items = json.loads(raw)["dataList"]
            if not isinstance(items, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise JasdcError("수급센터 응답을 읽지 못했습니다(형식이 다릅니다).") from None
        out: list[dict[str, str]] = []
        for it in items:
            if not isinstance(it, dict) or "dealDate" not in it:
                raise JasdcError("수급센터 응답에 날짜가 없는 줄이 있습니다.")
            deal = _dec(it.get("deal", 0), "거래량")
            if deal <= 0:
                continue
            if any(it.get(k) is None for k in ("avg", "high", "low")):
                self.notes.append(f"수급센터 {it['dealDate']} 줄에 가격 칸이 비어 있어 건너뛰었습니다.")
                continue
            avg, high, low = (_dec(it[k], k) for k in ("avg", "high", "low"))
            for name, v in (("평균", avg), ("최고", high), ("최저", low)):
                if not BOX_WON_MIN <= v <= BOX_WON_MAX:
                    raise JasdcError(f"{it['dealDate']} {name}가격 {v}원이 5kg 상자 단위({BOX_WON_MIN:,}~{BOX_WON_MAX:,}원) 범위를 벗어났습니다. "
                                     "이번 달 자료는 쓰지 않습니다.")
            out.append({"dealDate": str(it["dealDate"]), "avg": f"{avg.normalize():f}", "high": f"{high.normalize():f}",
                        "low": f"{low.normalize():f}", "deal": f"{deal.normalize():f}", "marketCd": ""})
        return out
