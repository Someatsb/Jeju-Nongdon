"""스냅샷 증분 갱신(Task 26, U26). 이 파일은 시계를 읽지 않는다: 날짜는 cfg.as_of로 받는다.

- 1361: 품종마다 스냅샷의 마지막 날 7일 앞부터 as_of까지, 92일(분기) 창으로 나눠 limit=100으로 받고, hasMore면 창을 반으로 쪼갠다
  (쪼개기는 HubClient). 하루 호출 상한 50회, 센 횟수는 <스냅샷 옆 live>/refresh_calls_YYYY-MM-DD.json에 남긴다.
  어떤 호출이든 실패하면 hub_1361.csv는 그대로 두고 사유만 보고한다. 상한에 닿으면 이미 끝난 품종까지만 반영한다(다음 날 이어서).
- 수급센터: 마지막 날 7일 앞이 든 달부터 as_of의 달까지 월 창. 한 달이라도 실패하면 그 파일은 그대로 둔다.
- 다시 쓴 파일만 manifest.json의 sha256을 새로 적는다(건드리지 않은 파일은 다시 보증하지 않는다).
- cfg.demo_asof(--asof 시연)면 RefreshRefused.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Protocol

from app.data_layer.hub_client import Http, HubClient, HubError, HubQuotaError
from app.data_layer.jasdc_client import JasdcClient, JasdcError
from app.data_layer.snapshot import DATASETS, MANIFEST

__all__ = ["DAILY_CAP", "OVERLAP_DAYS", "RefreshRefused", "RefreshReport", "update"]

DAILY_CAP = 50
OVERLAP_DAYS = 7
WINDOW_DAYS = 92                                  # 분기 한 창
HUB_URL = "https://open.jejudatahub.net"
JASDC_URL = "https://jasdc.or.kr"
HUB_HEAD = ("baseDate", "cultivar", "averagePrice", "transactionVolume", "transactionAmount")
JASDC_HEAD = ("dealDate", "avg", "high", "low", "deal", "marketCd")


class RefreshRefused(Exception):
    """--asof 시연 중에는 갱신하지 않는다."""


class _Cfg(Protocol):
    as_of: date
    demo_asof: bool


@dataclass
class RefreshReport:
    hub: str = "offline"                          # ok | offline | capped
    jasdc: str = "offline"                        # ok | offline
    calls_1361: int = 0
    partial_days: list[str] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)       # 다시 쓴 파일 이름
    messages: list[str] = field(default_factory=list)        # 한국어 사유·안내(키·주소 없음)


def _read_rows(path: Path, head: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        if tuple(rd.fieldnames or ()) != head:
            raise ValueError(f"{path.name} 머리줄이 예상과 다릅니다.")
        return [dict(r) for r in rd]


def _csv_bytes(head: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(head)
    for r in rows:
        w.writerow([r[k] for k in head])
    return buf.getvalue().encode("utf-8-sig")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)                 # 쓰기가 실패해도 찌꺼기 .tmp를 남기지 않는다


def _d8(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _two(v: object) -> str:
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise HubError("허브 응답에 숫자가 아닌 값이 있습니다.") from None


def windows(start: date, end: date) -> list[tuple[str, str]]:
    """start~end를 92일 이하 창(YYYYMMDD 쌍)으로 자른다."""
    out, a = [], start
    while a <= end:
        b = min(end, a + timedelta(days=WINDOW_DAYS - 1))
        out.append((a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
        a = b + timedelta(days=1)
    return out


def _calls_path(snap_dir: Path, as_of: date) -> Path:
    return snap_dir.parent / "live" / f"refresh_calls_{as_of.isoformat()}.json"


def _calls_used(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["calls"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _save_calls(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calls": n}) + "\n", encoding="utf-8", newline="\n")


def _write_manifest_file(path: Path, data: bytes) -> None:
    _atomic_write(path, data)


def _commit(snap_dir: Path, name: str, data: bytes, as_of: date, rep: RefreshReport) -> bool:
    """데이터 파일과 manifest를 짝으로 바꾼다. manifest를 못 쓰면 옛 데이터를 되돌려 짝을 지킨다.

    manifest 새 내용을 먼저 메모리에서 만들고, 옛 데이터 바이트를 쥔 채 데이터, manifest 순으로 교체한다.
    """
    path = snap_dir / DATASETS[name][0]
    mp = snap_dir / MANIFEST
    old_data = path.read_bytes()
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["datasets"][name]["sha256"] = hashlib.sha256(data).hexdigest()
        m["built_at"] = as_of.isoformat()
        new_manifest = (json.dumps(m, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        _atomic_write(path, data)
    except (OSError, ValueError, KeyError, TypeError) as e:
        rep.messages.append(f"{path.name}을 새로 쓰지 못했습니다({type(e).__name__}). 직전 스냅샷을 그대로 씁니다.")
        return False
    try:
        _write_manifest_file(mp, new_manifest)
    except OSError as e:
        try:
            _atomic_write(path, old_data)
            rep.messages.append(f"manifest.json을 쓰지 못해({type(e).__name__}) {path.name}을 직전 상태로 되돌렸습니다. 직전 스냅샷을 그대로 씁니다.")
        except OSError:
            rep.messages.append(f"manifest.json을 쓰지 못했고 {path.name}도 되돌리지 못했습니다. 스냅샷이 손상으로 보일 수 있으니 data/snapshot을 다시 받아 주세요.")
        return False
    rep.rewritten.append(path.name)
    return True


def _refresh_hub(client: HubClient, snap_dir: Path, as_of: date, rep: RefreshReport) -> None:
    path = snap_dir / DATASETS["hub_1361"][0]
    old = _read_rows(path, HUB_HEAD)
    last: dict[str, date] = {}
    for r in old:
        d = _d8(r["baseDate"])
        last[r["cultivar"]] = max(last.get(r["cultivar"], d), d)
    merged = {(r["baseDate"], r["cultivar"]): r for r in old}
    fresh: dict[tuple[str, str], dict[str, str]] = {}
    capped = False
    skipped = 0
    try:
        for cultivar in sorted(last):
            got: dict[tuple[str, str], dict[str, str]] = {}
            start = last[cultivar] - timedelta(days=OVERLAP_DAYS)
            for a, b in windows(start, as_of):
                for row in client.fetch_1361(cultivar, a, b):
                    if not isinstance(row, dict):
                        skipped += 1
                        continue
                    if row.get("cultivar") != cultivar or not str(row.get("baseDate", "")).isdigit():
                        raise HubError("허브 응답에 품종·날짜가 맞지 않는 줄이 있습니다.")
                    got[(str(row["baseDate"]), cultivar)] = {
                        "baseDate": str(row["baseDate"]), "cultivar": cultivar, "averagePrice": _two(row["averagePrice"]),
                        "transactionVolume": _two(row["transactionVolume"]), "transactionAmount": _two(row["transactionAmount"])}
            fresh.update(got)                                  # 품종 하나가 끝까지 받아졌을 때만 반영
    except HubQuotaError as e:
        capped = True
        rep.messages.append(str(e))
    except (HubError, KeyError) as e:
        rep.hub = "offline"
        rep.messages.append(f"{e} 직전 스냅샷을 그대로 씁니다." if isinstance(e, HubError) else "허브 응답에 빠진 칸이 있습니다. 직전 스냅샷을 그대로 씁니다.")
        return
    finally:
        rep.calls_1361 = client.calls
        rep.partial_days = list(client.partial_days)
    if skipped:
        rep.messages.append(f"허브 응답에서 형식이 다른 줄 {skipped}개를 건너뛰었습니다.")
    merged.update(fresh)
    rows = [merged[k] for k in sorted(merged, key=lambda k: (k[1], k[0]))]
    data = _csv_bytes(HUB_HEAD, rows)
    if data != path.read_bytes() and not _commit(snap_dir, "hub_1361", data, as_of, rep):
        rep.hub = "offline"
        return
    rep.hub = "capped" if capped else "ok"


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _refresh_jasdc(client: JasdcClient, snap_dir: Path, as_of: date, rep: RefreshReport) -> None:
    path = snap_dir / DATASETS["jasdc_citrus_k1"][0]
    try:
        old = _read_rows(path, JASDC_HEAD)
        merged = {r["dealDate"]: r for r in old}
        last = max((date.fromisoformat(k) for k in merged), default=as_of - timedelta(days=31))
        for month in _months(last - timedelta(days=OVERLAP_DAYS), as_of):
            for r in client.fetch_citrus(month):
                if date.fromisoformat(r["dealDate"]) <= as_of:
                    merged[r["dealDate"]] = r
        rep.messages.extend(client.notes)
    except (JasdcError, ValueError, OSError) as e:
        rep.jasdc = "offline"
        rep.messages.append(f"{e} 직전 수급센터 자료를 그대로 씁니다.")
        return
    data = _csv_bytes(JASDC_HEAD, [merged[k] for k in sorted(merged)])
    if data != path.read_bytes() and not _commit(snap_dir, "jasdc_citrus_k1", data, as_of, rep):
        rep.jasdc = "offline"
        return
    rep.jasdc = "ok"


def update(cfg: _Cfg, snap_dir: Path, keys: Mapping[str, str], *, http: Http | None = None,
           max_calls: int = DAILY_CAP, hub_url: str = HUB_URL, jasdc_url: str = JASDC_URL) -> RefreshReport:
    if cfg.demo_asof:
        raise RefreshRefused("--asof 시연 중에는 데이터를 갱신하지 않습니다. 시연 기준일을 빼고 다시 실행해 주세요.")
    snap_dir = Path(snap_dir)
    rep = RefreshReport()
    calls_file = _calls_path(snap_dir, cfg.as_of)
    used = _calls_used(calls_file)
    key = keys.get("hub") or ""
    if not key:
        rep.messages.append("허브 키가 없어 가격표는 갱신하지 못했습니다. 키 설정에서 허브 키를 넣어 주세요.")
    elif used >= max_calls:
        rep.hub = "capped"
        rep.messages.append(f"오늘 허브 호출 한도({max_calls}회)를 다 썼습니다. 내일 이어서 갱신합니다.")
    else:
        client = HubClient(hub_url, key, http=http, max_calls=max_calls - used)
        try:
            _refresh_hub(client, snap_dir, cfg.as_of, rep)
        except (ValueError, OSError) as e:                     # 스냅샷 파일을 못 읽거나 못 쓴 경우
            rep.hub = "offline"
            rep.messages.append(f"가격표 파일을 갱신하지 못했습니다({type(e).__name__}). 직전 스냅샷을 그대로 씁니다.")
        finally:
            _save_calls(calls_file, used + client.calls)
    try:
        _refresh_jasdc(JasdcClient(jasdc_url, http=http), snap_dir, cfg.as_of, rep)
    except OSError as e:
        rep.jasdc = "offline"
        rep.messages.append(f"수급센터 파일을 쓰지 못했습니다({type(e).__name__}). 직전 자료를 그대로 씁니다.")
    return rep
