"""갱신 모듈(Task 26, U26). 가짜 http만 쓰고 네트워크는 열지 않는다."""
import hashlib
import json
import shutil
import urllib.error
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import Config
from app.data_layer import refresh
from app.data_layer.refresh import RefreshRefused
from app.data_layer.snapshot import load_snapshot, write_manifest

ROOT = Path(__file__).resolve().parents[2]
CFG = Config(as_of=date(2026, 11, 13), demo_asof=False, replay=False, port=8765,
             tables_dir=ROOT / "data" / "tables", snapshot_dir=ROOT / "data" / "snapshot")
CFG_DEMO = replace(CFG, demo_asof=True)
KEYS = {"hub": "TESTKEY12345678"}
NO_KEYS: dict[str, str] = {}
FILES = ("hub_1361.csv", "jasdc_citrus_k1.csv", "hub_854_jeju_raw.csv", "agg_869_ratio.csv", "manifest.json")


@pytest.fixture
def snap(tmp_path):
    d = tmp_path / "data" / "snapshot"
    shutil.copytree(ROOT / "data" / "snapshot", d)
    _align_hub_end(d, "20261105")
    return d


def _align_hub_end(d: Path, last: str) -> None:
    """모든 품종의 마지막 날을 같게 맞춘다(실제 스냅샷은 품종마다 끝나는 날이 다르다)."""
    p = d / "hub_1361.csv"
    rows = p.read_bytes().decode("utf-8-sig").splitlines()
    head, body = rows[0], [r.split(",") for r in rows[1:]]
    out, tail = [], {}
    for r in body:
        if r[0] <= last:
            out.append(r)
            tail[r[1]] = r
    for cultivar, r in sorted(tail.items()):
        if r[0] != last:
            out.append([last, *r[1:]])
    out.sort(key=lambda r: (r[1], r[0]))
    text = "\r\n".join([head, *(",".join(r) for r in out)]) + "\r\n"
    p.write_bytes(text.encode("utf-8-sig"))
    write_manifest(d, date(2026, 11, 8))


def digest(d: Path) -> dict[str, str]:
    return {f: hashlib.sha256((d / f).read_bytes()).hexdigest() for f in FILES}


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


def _days(start: str, end: str):
    return [date.fromordinal(o) for o in range(_d(start).toordinal(), _d(end).toordinal() + 1)]


def fake_http(page_cap: int | None = None, calls: list | None = None, citrus_fail: bool = False):
    """1361: 날짜마다 한 행(기준일 11-13까지). page_cap보다 많으면 hasMore. 수급센터: 11-12 한 행 + deal=0 한 행."""
    def http(url: str) -> bytes:
        u = urlparse(url)
        q = parse_qs(u.query)
        if "jasdc" in u.netloc:
            if citrus_fail:
                raise urllib.error.URLError("down")
            return json.dumps({"dataList": [
                {"dealDate": "2026-11-12", "avg": 9000, "high": 30000, "low": 3000, "deal": 500.5},
                {"dealDate": "2026-11-13", "avg": 0, "high": 0, "low": 0, "deal": 0}]}).encode()
        if calls is not None:
            calls.append((q["cultivar"][0], q["startDate"][0], q["endDate"][0]))
        days = [d for d in _days(q["startDate"][0], q["endDate"][0]) if d <= date(2026, 11, 13)]
        rows = [{"baseDate": d.strftime("%Y%m%d"), "cultivar": q["cultivar"][0], "averagePrice": 2000.0 + d.day,
                 "transactionVolume": 10.5, "transactionAmount": 21.0} for d in days]
        more = page_cap is not None and len(rows) > page_cap
        return json.dumps({"totCnt": len(rows), "hasMore": more, "data": rows[:page_cap] if more else rows}).encode()
    return http


@pytest.fixture
def http_offline():
    def http(url):
        raise urllib.error.URLError("offline")
    return http


@pytest.fixture
def http_recorded_hasmore():
    return fake_http(page_cap=8)


def test_refresh_offline_keeps_old(http_offline, snap):
    before = digest(snap)
    rep = refresh.update(CFG, snap, NO_KEYS, http=http_offline)
    assert rep.hub == "offline" and digest(snap) == before
    rep = refresh.update(CFG, snap, KEYS, http=http_offline)
    assert rep.hub == "offline" and rep.jasdc == "offline" and rep.rewritten == [] and digest(snap) == before
    assert all(any("가" <= ch <= "힣" for ch in m) for m in rep.messages) and "TESTKEY" not in " ".join(rep.messages)


def test_refresh_hasmore_splits(http_recorded_hasmore, snap):
    rep = refresh.update(CFG, snap, KEYS, http=http_recorded_hasmore)
    assert rep.calls_1361 > 10 and rep.partial_days == [] and rep.hub == "ok"
    s = load_snapshot(snap, CFG.as_of)
    assert max(p[0] for p in s.prices["당근(일반)"].points) == date(2026, 11, 13)


def test_refresh_refused_in_demo(snap):
    before = digest(snap)
    with pytest.raises(RefreshRefused):
        refresh.update(CFG_DEMO, snap, KEYS, http=fake_http())
    assert digest(snap) == before


def test_incremental_window_starts_seven_days_before_last_point(snap):
    calls = []
    refresh.update(CFG, snap, KEYS, http=fake_http(calls=calls))
    assert len(calls) == 10 and {c[1] for c in calls} == {"20261029"} and {c[2] for c in calls} == {"20261113"}


def test_only_rewritten_files_are_reblessed(snap):
    before = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    refresh.update(CFG, snap, KEYS, http=fake_http())
    after = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    for name in ("hub_854_jeju_raw", "agg_869_ratio"):
        assert after["datasets"][name] == before["datasets"][name]
    for name, f in (("hub_1361", "hub_1361.csv"), ("jasdc_citrus_k1", "jasdc_citrus_k1.csv")):
        assert after["datasets"][name]["sha256"] == hashlib.sha256((snap / f).read_bytes()).hexdigest()
        assert after["datasets"][name]["sha256"] != before["datasets"][name]["sha256"]
        assert after["datasets"][name]["source"] == before["datasets"][name]["source"]
    assert after["built_at"] == "2026-11-13"
    s = load_snapshot(snap, CFG.as_of)
    assert not s.damaged and max(p[0] for p in s.citrus.points) == date(2026, 11, 12)


def test_second_run_rewrites_nothing(snap):
    refresh.update(CFG, snap, KEYS, http=fake_http())
    d = digest(snap)
    rep = refresh.update(CFG, snap, KEYS, http=fake_http())
    assert rep.rewritten == [] and digest(snap) == d


def test_existing_rows_not_reformatted(snap):
    old = (snap / "hub_1361.csv").read_bytes().splitlines()
    refresh.update(CFG, snap, KEYS, http=fake_http())
    raw = (snap / "hub_1361.csv").read_bytes()
    new = set(raw.splitlines())
    assert all(line in new for line in old[:500]) and raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw


def test_daily_cap_persisted(snap):
    calls = []
    rep = refresh.update(CFG, snap, KEYS, http=fake_http(calls=calls), max_calls=4)
    assert rep.hub == "capped" and rep.calls_1361 == 4 and len(calls) == 4
    f = snap.parent / "live" / "refresh_calls_2026-11-13.json"
    assert json.loads(f.read_text(encoding="utf-8"))["calls"] == 4
    rep2 = refresh.update(CFG, snap, KEYS, http=fake_http(calls=calls), max_calls=4)
    assert rep2.calls_1361 == 0 and rep2.hub == "capped" and len(calls) == 4
    assert refresh.DAILY_CAP == 50


def test_citrus_failure_keeps_citrus_file_but_hub_still_updates(snap):
    before = digest(snap)
    rep = refresh.update(CFG, snap, KEYS, http=fake_http(citrus_fail=True))
    after = digest(snap)
    assert rep.hub == "ok" and rep.jasdc == "offline"
    assert after["jasdc_citrus_k1.csv"] == before["jasdc_citrus_k1.csv"] and after["hub_1361.csv"] != before["hub_1361.csv"]


def test_backfill_uses_quarter_windows(snap):
    calls = []
    p = snap / "hub_1361.csv"
    lines = p.read_bytes().decode("utf-8-sig").splitlines()
    keep = [r for r in lines if r.startswith("baseDate") or r.split(",")[1] != "마늘" or r.split(",")[0] < "20240101"]
    p.write_bytes(("\r\n".join(keep) + "\r\n").encode("utf-8-sig"))
    write_manifest(snap, date(2026, 11, 8))
    refresh.update(CFG, snap, KEYS, http=fake_http(calls=calls))
    garlic = [c for c in calls if c[0] == "마늘"]
    assert len(garlic) >= 10 and all(len(_days(a, b)) <= 93 for _, a, b in garlic)


def test_cli_refuses_in_demo(capsys):
    from app.data_layer import refresh_cli
    assert refresh_cli.main(["--asof", "2026-11-13"]) == 2
    assert "시연" in capsys.readouterr().out


def test_naqs_office_in_shipped_offices():
    import csv
    with (ROOT / "data" / "tables" / "offices.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert any(r["office_id"] == "naqs_jeju" and r["name"] == "국립농산물품질관리원 제주지원(농관원)" and r["phone"] == "1644-8778" for r in rows)


def test_manifest_write_failure_restores_old_data(snap, monkeypatch):
    before = digest(snap)

    def boom(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(refresh, "_write_manifest_file", boom)
    rep = refresh.update(CFG, snap, KEYS, http=fake_http())
    assert digest(snap) == before and rep.rewritten == [] and rep.hub == "offline" and rep.jasdc == "offline"
    assert any("되돌렸습니다" in m for m in rep.messages)
    assert not load_snapshot(snap, CFG.as_of).damaged
    assert not list(snap.glob("*.tmp"))


def test_failed_write_leaves_no_tmp(tmp_path, monkeypatch):
    def bad_replace(a, b):
        raise OSError("x")
    monkeypatch.setattr(refresh.os, "replace", bad_replace)
    with pytest.raises(OSError):
        refresh._atomic_write(tmp_path / "a.csv", b"x")
    assert list(tmp_path.iterdir()) == []


def test_non_dict_hub_row_is_skipped(snap):
    inner = fake_http()

    def http(url):
        if "jasdc" in url:
            return inner(url)
        body = json.loads(inner(url))
        body["data"].insert(0, "garbage")
        return json.dumps(body).encode()
    rep = refresh.update(CFG, snap, KEYS, http=http)
    assert rep.hub == "ok" and any("건너뛰" in m for m in rep.messages)
