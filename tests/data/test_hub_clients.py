"""허브·수급센터 HTTP 클라이언트(Task 26, U26). 네트워크 없이 가짜 http로 본다."""
import http.client
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.data_layer.hub_client import HubClient, HubError, HubQuotaError
from app.data_layer.jasdc_client import JasdcClient, JasdcError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "http"
KEY = "TESTKEY12345678"


def fixture_bytes(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_hub_url_building():
    seen = []
    c = HubClient("https://open.example.net", KEY, http=lambda u: seen.append(u) or fixture_bytes("hub_1361_page_small.json"))
    c.fetch_1361("당근(일반)", "20261101", "20261102")
    q = parse_qs(urlparse(seen[0]).query)
    assert urlparse(seen[0]).path == f"/api/proxy/{HubClient.DATA_KEY_1361}/{KEY}"
    assert q == {"startDate": ["20261101"], "endDate": ["20261102"], "cultivar": ["당근(일반)"], "limit": ["100"]}
    assert c.calls == 1


def test_hub_returns_rows():
    c = HubClient("https://x", KEY, http=lambda u: fixture_bytes("hub_1361_page_small.json"))
    rows = c.fetch_1361("당근(일반)", "20261101", "20261102")
    assert [r["baseDate"] for r in rows] == ["20261101", "20261102"]


def test_hub_hasmore_halves_window():
    windows = []

    def http(url):
        q = parse_qs(urlparse(url).query)
        windows.append((q["startDate"][0], q["endDate"][0]))
        if q["startDate"][0] != q["endDate"][0]:
            return fixture_bytes("hub_1361_page_full.json")          # hasMore=true
        d = q["startDate"][0]
        return json.dumps({"hasMore": False, "data": [{"baseDate": d, "cultivar": "당근(일반)", "averagePrice": 1,
                                                       "transactionVolume": 1, "transactionAmount": 1}]}).encode()

    c = HubClient("https://x", KEY, http=http)
    rows = c.fetch_1361("당근(일반)", "20261101", "20261104")
    assert windows[:3] == [("20261101", "20261104"), ("20261101", "20261102"), ("20261101", "20261101")]
    assert sorted(r["baseDate"] for r in rows) == ["20261101", "20261102", "20261103", "20261104"]
    assert c.partial_days == []


def test_hub_single_day_still_full_is_partial_day():
    full = json.dumps({"hasMore": True, "data": [{"baseDate": "20261101"}]}).encode()
    c = HubClient("https://x", KEY, http=lambda u: full)
    c.fetch_1361("당근(일반)", "20261101", "20261101")
    assert c.partial_days == ["20261101"]


def test_hub_errors_are_korean_and_never_show_key():
    def boom(url):
        raise urllib.error.HTTPError(url, 500, "x", {}, None)

    with pytest.raises(HubError) as e:
        HubClient("https://x", KEY, http=boom).fetch_1361("a", "20261101", "20261101")
    assert KEY not in str(e.value) and "허브" in str(e.value) and "500" in str(e.value)
    with pytest.raises(HubError) as e2:
        HubClient("https://x", KEY, http=lambda u: b"<html>").fetch_1361("a", "20261101", "20261101")
    assert KEY not in str(e2.value) and "허브" in str(e2.value)
    with pytest.raises(HubError):
        HubClient("https://x", KEY, http=lambda u: b'{"nodata": 1}').fetch_1361("a", "20261101", "20261101")


def test_hub_quota_cap():
    c = HubClient("https://x", KEY, http=lambda u: fixture_bytes("hub_1361_page_small.json"), max_calls=1)
    c.fetch_1361("a", "20261101", "20261102")
    with pytest.raises(HubQuotaError):
        c.fetch_1361("a", "20261101", "20261102")


def test_hub_requires_key():
    with pytest.raises(HubError):
        HubClient("https://x", "", http=lambda u: b"")


def test_jasdc_excludes_deal_zero_and_maps_fields():
    seen = []
    c = JasdcClient("https://jasdc.example", http=lambda u: seen.append(u) or fixture_bytes("jasdc_term_day_2026-11.json"))
    rows = c.fetch_citrus("2026-11")
    q = parse_qs(urlparse(seen[0]).query)
    assert q["startDate"] == ["2026-11-01"] and q["endDate"] == ["2026-11-30"] and q["kind"] == ["1"]
    assert [r["dealDate"] for r in rows] == ["2026-11-05", "2026-11-06"]
    assert set(rows[0]) == {"dealDate", "avg", "high", "low", "deal", "marketCd"} and rows[0]["marketCd"] == ""


def test_jasdc_rejects_absurd_unit():
    c = JasdcClient("https://x", http=lambda u: fixture_bytes("jasdc_term_day_absurd.json"))
    with pytest.raises(JasdcError) as e:
        c.fetch_citrus("2026-11")
    assert "5kg" in str(e.value)


def test_jasdc_http_failure_is_korean():
    def boom(url):
        raise urllib.error.URLError("down")

    with pytest.raises(JasdcError) as e:
        JasdcClient("https://x", http=boom).fetch_citrus("2026-11")
    assert "수급" in str(e.value)
    with pytest.raises(JasdcError):
        JasdcClient("https://x", http=lambda u: b"nope").fetch_citrus("2026-11")
    with pytest.raises(ValueError):
        JasdcClient("https://x", http=lambda u: b"").fetch_citrus("2026/11")


def _dropped(url):
    raise http.client.RemoteDisconnected("closed")


def test_http_client_exceptions_become_korean_errors():
    with pytest.raises(HubError) as e:
        HubClient("https://x", KEY, http=_dropped).fetch_1361("a", "20261101", "20261101")
    assert KEY not in str(e.value) and "허브" in str(e.value)
    with pytest.raises(JasdcError) as e2:
        JasdcClient("https://x", http=_dropped).fetch_citrus("2026-11")
    assert "수급" in str(e2.value)


def _jasdc(rows):
    return JasdcClient("https://x", http=lambda u: json.dumps({"dataList": rows}).encode())


def test_jasdc_zero_avg_with_deal_fails_range():
    with pytest.raises(JasdcError):
        _jasdc([{"dealDate": "2026-11-05", "avg": 0, "high": 30000, "low": 3000, "deal": 5}]).fetch_citrus("2026-11")


def test_jasdc_missing_high_low_skips_row_with_note():
    c = _jasdc([{"dealDate": "2026-11-05", "avg": 9000, "deal": 5},
                {"dealDate": "2026-11-06", "avg": 9000, "high": 30000, "low": 3000, "deal": 5}])
    assert [r["dealDate"] for r in c.fetch_citrus("2026-11")] == ["2026-11-06"]
    assert c.notes and "2026-11-05" in c.notes[0]
