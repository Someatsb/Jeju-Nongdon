"""표 관리·키 명령줄(Task 25, U25). 인자 해석과 출력만 한다. 일은 app/data_layer/tables_admin.py와 KeyStore가 한다.

  python -m app.cli tables check | diff <새.csv> | apply <새.csv> --by KJ | rollback
  python -m app.cli keys set llm|hub | show | test | delete llm|hub
  python -m app.cli data refresh [--asof ...]     (app.data_layer.refresh_cli로 넘긴다)
  python -m app.cli reminders due --month YYYY-MM [--export 파일.csv] | sent --month YYYY-MM | forget <상담번호> | purge
  python -m app.cli notice <공고.pdf|공고.txt>     → data/inbox/<id>/{draft.json,check.json,report.html} (Task 29)
  python -m app.cli notice --url <공고 주소>        서귀포시·제주시·제주도청 공고 페이지를 받아 읽는다(그 밖의 주소는 거절)
  공고를 읽은 뒤 조건을 채운 사업은 data/catalog/notices/<이름>.json 으로 지원 전체 보기에 올라간다(--no-catalog 면 올리지 않는다)
  python -m app.cli notice --scout [--days N] [--dry-run]   공식 게시판 네 곳을 AI 가 훑어 새 농가 지원 공고를 골라 읽고 목록에 올린다
      → data/inbox/scout-<날짜시각>/{report.json,report.html}. --dry-run 은 고르기까지만. --no-catalog 는 올리지도, 이미 읽은 글 표시도 하지 않는다

시계: 백업·기록 시각의 날짜는 cfg.as_of(app/config.py), 시·분·초는 이 파일의 `_clock()` 한 곳에서만 읽는다.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable

from keyring.errors import KeyringError

from app.agents.llm.base import LLMClient
from app.agents.llm.factory import make_llm_client
from app.agents.llm.keystore import KeyStore
from app.agents.notice import dump_json, run_notice, unreadable
from app.agents.scout import run_scout, unavailable_text
from app.catalog.publish import publish_notice
from app.config import APP_ROOT, load_config
from app.data_layer import reminders
from app.data_layer import tables_admin as admin
from app.data_layer.docs_in import Doc, UnsupportedFormat, extract
from app.data_layer.notice_board import BoardClient, KnownNotices, RequestLimit, url_inbox_id
from app.data_layer.notice_url import Http, NoticeUrlError, fetch_notice, source_url_of
from app.data_layer.supports_index import load_program_index
from app.tools import draft_checks
from app.tools.models import ToolLog
from app.ui.report_notice import DECISION_LABEL, render_notice_report
from app.ui.report_scout import render_scout_report

KEY_NAMES = ("llm", "hub")


def _clock() -> time:
    return datetime.now().time().replace(microsecond=0)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="제주 농돈 표 관리·키")
    p.add_argument("--asof", metavar="YYYY-MM-DD", help="시연 기준일(시험용)")
    top = p.add_subparsers(dest="group", required=True)
    t = top.add_parser("tables", help="지원제도표(supports.csv) 관리").add_subparsers(dest="cmd", required=True)
    t.add_parser("check", help="표 검사")
    t.add_parser("diff", help="새 파일과 지금 표 비교").add_argument("new_csv")
    ap = t.add_parser("apply", help="검사 통과 시 새 파일로 교체")
    ap.add_argument("new_csv")
    ap.add_argument("--by", required=True, help="바꾼 사람 이니셜")
    t.add_parser("rollback", help="가장 최근 백업으로 되돌리기")
    k = top.add_parser("keys", help="API 키 관리").add_subparsers(dest="cmd", required=True)
    k.add_parser("set", help="키 저장(입력은 화면에 안 보임)").add_argument("name", choices=KEY_NAMES)
    k.add_parser("show", help="저장된 키 끝 4자리")
    k.add_parser("test", help="자격 증명 저장소 점검")
    k.add_parser("delete", help="키 지우기(이름 필수)").add_argument("name", nargs="?", choices=KEY_NAMES)
    d = top.add_parser("data", help="자료 갱신").add_subparsers(dest="cmd", required=True)
    d.add_parser("refresh", help="가격표·수급센터 자료 갱신(나머지 인자는 refresh_cli로 넘김)", add_help=False)         .add_argument("rest", nargs=argparse.REMAINDER)
    r = top.add_parser("reminders", help="재방문 문자 안내(동의한 번호)").add_subparsers(dest="cmd", required=True)
    rd = r.add_parser("due", help="그 달에 보낼 목록")
    rd.add_argument("--month", required=True, type=_month)
    rd.add_argument("--export", metavar="path.csv", help="전체 번호 CSV(센터 문자 발송용)")
    r.add_parser("sent", help="그 달 발송 완료 표시").add_argument("--month", required=True, type=_month)
    r.add_parser("forget", help="한 사람의 번호 지우기").add_argument("session_id")
    r.add_parser("purge", help="보관 기간이 지난 번호 지우기")
    n = top.add_parser("notice", help="공고 파일이나 주소를 읽어 초안과 근거 보고서를 만든다")
    n.add_argument("file", nargs="?", help="공고 PDF 또는 텍스트 파일(첫 줄이 '출처: 주소'면 그 주소를 원문 링크로 쓴다)")
    n.add_argument("--url", help="공고 주소(서귀포시·제주시·제주도청). 페이지를 받아 본문 글을 읽는다")
    n.add_argument("--no-catalog", action="store_true", help="읽은 뒤 지원 전체 보기 목록에 올리지 않는다")
    n.add_argument("--scout", action="store_true", help="공식 게시판 네 곳에서 새 농가 지원 공고를 AI 가 찾아 읽는다(파일·주소는 넣지 않는다)")
    n.add_argument("--days", type=int, default=None, help="--scout: 최근 며칠 글까지 볼지(기본 30)")
    n.add_argument("--dry-run", action="store_true", help="--scout: 고르기까지만 하고 공고는 읽지 않는다")
    n.add_argument("--catalog-dir", type=Path, default=None, help=argparse.SUPPRESS)   # 시험용: 목록 자료 폴더(받은 함은 그 옆 inbox)
    return p


def _month(text: str) -> date:
    msg = f"달은 2027-04처럼 YYYY-MM으로 넣어 주세요: {text}"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", text):
        raise argparse.ArgumentTypeError(msg)
    try:
        return date.fromisoformat(text + "-01")
    except ValueError:
        raise argparse.ArgumentTypeError(msg) from None


def _mask(phone: str) -> str:
    return "010-****-" + phone[-4:]


_DEMO_RO = "시연 기준일(--asof)에서는 저장된 알림을 지우거나 고치지 않습니다(읽기만 합니다)."


def _export_refusal(path: Path, root: Path) -> str | None:
    if path.exists():
        return f"{path} 이미 파일이 있습니다. 다른 이름을 쓰거나 먼저 지워 주세요."
    target = path.resolve()
    for data in {(root / "data").resolve(), (APP_ROOT / "data").resolve()}:
        if target == data or data in target.parents:
            return f"설치 폴더의 data 안에는 내보낼 수 없습니다: {path}"
    return None


def _reminders(args, root: Path, cfg) -> int:
    base = root / "data" / "reminders"
    demo = cfg.demo_asof
    try:
        if args.cmd == "due":
            if args.export:
                if demo:
                    print("시연 기준일(--asof)에서는 전체 번호를 내보낼 수 없습니다. 화면 표만 볼 수 있습니다.")
                    return 1
                why = _export_refusal(Path(args.export), root)
                if why:
                    print(why)
                    return 1
            res = reminders.due(args.month, cfg.as_of, base=base, readonly=demo)
            print(f"{args.month:%Y-%m} 발송 대상 {len(res.items)}건")
            for it in res.items:
                print(f"  {it.session_id}  {_mask(it.phone)}  {it.text}")
            if res.unreadable:
                print(f"읽을 수 없는 알림 파일 {len(res.unreadable)}건: {', '.join(res.unreadable)} "
                      "(다른 PC/사용자에서 저장했거나 손상). 삭제하려면 reminders forget <상담번호>")
            if res.deleted:
                print(f"보관 기간이 지나 지운 파일 {len(res.deleted)}건: {', '.join(res.deleted)}")
            if demo:
                print(_DEMO_RO)
            if args.export:
                with Path(args.export).open("x", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["상담번호", "전화번호", "문구"])
                    w.writerows((it.session_id, it.phone, it.text) for it in res.items)
                print(f"{args.export} 에 전체 번호를 적었습니다. 발송 후 삭제하세요.")
        elif args.cmd == "sent":
            if demo:
                print(_DEMO_RO)
                return 0
            ids = {it.session_id for it in reminders.due(args.month, cfg.as_of, base=base).items}
            for sid in sorted(ids):
                reminders.mark_sent(sid, args.month, base=base)
            print(f"{args.month:%Y-%m} {len(ids)}건을 발송 완료로 표시했습니다.")
        elif args.cmd == "forget":
            print("지웠습니다." if reminders.forget(args.session_id, base=base) else "그 상담번호로 저장된 번호가 없습니다.")
        else:
            gone = reminders.purge(cfg.as_of, base=base, readonly=demo)
            if demo:
                print(f"보관 기간이 지난 파일 {len(gone)}건이 있습니다.")
                print(_DEMO_RO)
            else:
                print(f"보관 기간이 지난 {len(gone)}건을 지웠습니다." + (f" ({', '.join(gone)})" if gone else ""))
    except (ValueError, OSError, NotImplementedError) as e:
        print(f"문자 안내 자료를 다룰 수 없습니다: {e}")
        return 1
    return 0


def _print_diff(d: admin.Diff) -> None:
    print(f"추가 {len(d.added)}건, 빠짐 {len(d.removed)}건, 바뀜 {len(d.changed)}건")
    for i in d.added:
        print(f"  추가: {i}")
    for i in d.removed:
        print(f"  빠짐: {i}")
    for i, cols in d.changed.items():
        print(f"  바뀜: {i} ({', '.join(cols)})")


def _tables(args, root: Path, as_of, stamp: datetime) -> int:
    if args.cmd == "check":
        issues = admin.check(root / "data" / "tables", as_of)
        for i in issues:
            print(admin.format_issue(i))
        errors = sum(i.level == "error" for i in issues)
        print(f"오류 {errors}건, 경고 {len(issues) - errors}건" + (" - 표를 쓸 수 없습니다." if errors else " - 이상 없음."))
        return 1 if errors else 0
    try:
        if args.cmd == "diff":
            _print_diff(admin.diff_supports(root / "data" / "tables" / admin.SUPPORTS, Path(args.new_csv)))
        elif args.cmd == "apply":
            r = admin.apply(root, Path(args.new_csv), args.by, stamp)
            for w in r.warnings:
                print(admin.format_issue(w))
            _print_diff(r.diff)
            print(f"적용했습니다. 백업: {r.backup.name}")
            if r.log_error:
                print(r.log_error)
                return 1
        else:
            b = admin.rollback(root, stamp)
            print(f"되돌렸습니다. 백업 {b.name}의 내용으로 복원했습니다.")
    except admin.LogFailed as e:                 # 되돌리기는 끝났고 기록만 실패
        print("되돌렸습니다.\n" + str(e))
        return 1
    except admin.AlreadySame as e:
        print(str(e))
        return 0
    except admin.AdminError as e:
        print(str(e))
        return 1
    return 0


_KEYRING_DOWN = "자격 증명 저장소를 쓸 수 없습니다 ({why}). 이 PC의 Windows 자격 증명 관리자를 확인하세요."


def _inbox_id(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", path.stem).strip("._") or "notice"
    return f"{stem}-{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"


def _url_inbox_id(url: str) -> str:
    return url_inbox_id(url)


def _notice(args, root: Path, llm: LLMClient, read_date: date, catalog_dir: Path | None = None) -> int:
    url: str | None = None
    title: str
    if args.url:
        if args.file:
            print("공고 파일과 --url 은 하나만 넣어 주세요")
            return 2
        try:
            fetched = fetch_notice(args.url)
        except NoticeUrlError as e:
            print(str(e))
            return 2
        url, title, inbox_id, doc = fetched.url, fetched.title, _url_inbox_id(fetched.url), fetched.doc
        if fetched.removed_lines:
            print(f"개인정보(휴대전화·메일)가 든 줄 {fetched.removed_lines}개는 빼고 읽었습니다")
    else:
        if not args.file:
            print("사용법: notice.bat 공고파일.pdf   또는   notice.bat --url 공고주소")
            return 2
        path = Path(args.file)
        if not path.is_file():
            print(f"파일을 찾을 수 없습니다: {path}")
            return 2
        title, inbox_id, doc = path.name, _inbox_id(path), None
    _read_notice(root, llm, read_date, url=url, title=title, inbox_id=inbox_id, doc=doc,
                 path=None if args.url else path, no_catalog=args.no_catalog, catalog_dir=catalog_dir)
    return 0


def _inbox_root(root: Path, catalog_dir: Path | None) -> Path:
    """읽은 것을 두는 받은 함 폴더: 목록 자료 폴더의 옆 inbox(기본 root/data/catalog 면 root/data/inbox)."""
    return (Path(catalog_dir) if catalog_dir is not None else root / "data" / "catalog").parent / "inbox"


def _read_notice(root: Path, llm: LLMClient, read_date: date, *, url: str | None, title: str, inbox_id: str,
                 doc: Doc | None, path: Path | None, no_catalog: bool, progress: Callable[..., None] | None = None,
                 catalog_dir: Path | None = None):
    """공고 하나를 읽어 data/inbox/<id>/ 에 초안·검사·보고서를 쓰고, 목록에 올린다. (결과, 폴더, 올림 보고)를 돌려준다."""
    bundle = load_program_index(root / "data" / "tables")
    log = ToolLog()
    try:
        if doc is None:
            doc = extract(path)
            url = source_url_of(doc)
        result = run_notice(doc, bundle, llm, log)
    except UnsupportedFormat as e:
        result = unreadable(str(e))
    except Exception as e:      # 깨진 파일·글자 깨짐 등: 직원에게 오류 추적 대신 안내를 보인다
        result = unreadable(f"파일을 읽는 중 문제가 생겼습니다({type(e).__name__}). 공고 본문을 복사해 붙여 넣어 주세요 "
                            "(본문을 붙여 넣으면 바로 읽습니다)")
        doc = None
    if progress:
        progress("verify")
    issues = draft_checks.run(result, doc, bundle) if doc is not None and result.programs else []
    out = _inbox_root(root, catalog_dir) / inbox_id
    out.mkdir(parents=True, exist_ok=True)
    check = {"decision": result.decision, "partial": result.partial, "tool_calls": log.tool_calls,
             "issues": [i.model_dump(mode="json") for i in issues]}
    for name, text in (("draft.json", dump_json(result)),
                       ("check.json", json.dumps(check, ensure_ascii=False, indent=2) + chr(10)),
                       ("report.html", render_notice_report(result, issues, doc, title))):   # 보고서가 마지막
        tmp = out / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline=chr(10))
        os.replace(tmp, out / name)
    print(f"{result.decision}: {out / 'report.html'}")
    report = None
    if not no_catalog:
        report = publish_notice(result, doc, url=url, read_date=read_date, root=root, bundle=bundle, catalog_dir=catalog_dir)
        for p in report.written:
            print(f"지원 전체 보기에 올렸습니다: {p.name}")
        for name in report.replaced:
            print(f"같은 주소의 옛 공고를 바꿨습니다: {name}")
        for text in report.upgraded:
            print(text)
        for why in report.skipped:
            print(f"지원 전체 보기에 올리지 않았습니다: {why}")
    return result, out, report


def _scout(args, root: Path, llm: LLMClient, read_date: date, stamp: datetime, http: Http | None,
           sleep: Callable[[float], None] | None, catalog_dir: Path | None = None) -> int:
    """공식 게시판을 AI 가 훑어 새 농가 지원 공고를 고르고, 고른 글마다 fetch_notice → run_notice → publish_notice 를 돌린다."""
    if args.file or args.url:
        print("--scout 는 공고 파일이나 --url 과 같이 쓸 수 없습니다")
        return 2
    days = 30 if args.days is None else args.days
    if not 1 <= days <= 365:
        print("--days 는 1에서 365 사이 숫자로 넣어 주세요")
        return 2
    print("공식 게시판 네 곳에서 새 농가 지원 공고를 찾습니다(게시판에 부담을 주지 않으려고 요청 사이에 쉬므로 몇 분 걸릴 수 있습니다)")
    data, out, down = scout_run(root, llm, read_date, stamp, http, sleep, days=days, dry_run=args.dry_run,
                                no_catalog=args.no_catalog, echo=print, catalog_dir=catalog_dir)
    print(f"고른 글 {len(data['picks'])}건, 건너뛴 글 {len(data['skips'])}건")
    if data["stop"]:
        print(f"중간에 멈춘 이유: {data['stop']}")
    for limit in data["limits"]:
        print(f"한도에 닿았습니다: {limit}")
    print(f"보고서: {out / 'report.html'}")
    return 1 if down else 0


def _rel(out: Path, root: Path) -> str:
    try:
        return str(out.relative_to(root)).replace(os.sep, "/")
    except ValueError:                      # 목록 자료 폴더를 다른 곳으로 준 경우: 받은 함은 root 밖이다
        return f"inbox/{out.name}"


def scout_run(root: Path, llm: LLMClient, read_date: date, stamp: datetime, http: Http | None,
              sleep: Callable[[float], None] | None, *, days: int = 30, dry_run: bool = False, no_catalog: bool = False,
              progress: Callable[..., None] | None = None, echo: Callable[[str], None] = lambda text: None,
              catalog_dir: Path | None = None) -> tuple[dict, Path, bool]:
    """찾아오기 한 판(명령줄과 직원 화면이 같이 쓴다). (보고서 dict, 보고서 폴더, AI 를 못 써서 끝까지 못 읽었는지)를 돌려준다.

    progress(단계, **정보): "scout"(tools=ScoutTools, last=방금 쓴 도구 이름 또는 "") · "read"(n, total, title) · "verify" · "write".
    보고서(report.json·report.html)는 root/data/inbox/scout-<날짜시각>/ 에 쓴다."""
    tick = progress or (lambda *a, **k: None)
    client = BoardClient(http, sleep) if sleep else BoardClient(http)
    known = None if no_catalog else KnownNotices.from_root(root, catalog_dir)
    found = run_scout(None, llm, ToolLog(), as_of=read_date, days=days, known=known, client=client,
                      on_step=lambda tools, last: tick("scout", tools=tools, last=last))
    picks = []
    read_down = ""
    for n, pick in enumerate(found.picks, 1):
        row = pick.row
        entry = {"row": row.no, "board": row.board.name, "title": row.title, "posted": row.posted.isoformat() if row.posted else "",
                 "dept": row.dept, "url": row.url, "reason": pick.reason, "decision": None, "decision_label": "",
                 "published": [], "not_published": [], "inbox": "", "error": "", "note": ""}
        picks.append(entry)
        echo(f"[{n}/{len(found.picks)}] 고른 글: {row.title}")
        if dry_run:
            entry["note"] = "시험 삼아 고르기까지만 해서 읽지 않았습니다"
            continue
        tick("read", n=n, total=len(found.picks), title=row.title)
        try:
            fetched = found.fetched.get(row.url) or fetch_notice(row.url, http=client.fetch)
        except RequestLimit:
            entry["error"] = "한 번 찾기에 받을 수 있는 요청 수를 다 써서 이 글은 읽지 못했습니다"
        except NoticeUrlError as e:
            entry["error"] = str(e)
        else:
            result, out, report = _read_notice(root, llm, read_date, url=fetched.url, title=fetched.title,
                                               inbox_id=_url_inbox_id(fetched.url), doc=fetched.doc, path=None,
                                               no_catalog=no_catalog, progress=tick, catalog_dir=catalog_dir)
            entry.update(decision=result.decision, decision_label=DECISION_LABEL[result.decision],
                         inbox=_rel(out, root))
            if report is None:
                entry["note"] = "목록에 올리지 않았습니다(--no-catalog)"
            else:
                entry["published"] = [p.name for p in report.written]
                entry["not_published"] = list(report.skipped)
                entry["replaced"] = list(report.replaced)
                entry["upgraded"] = list(report.upgraded)
                if result.partial or result.decision not in ("DRAFT_READY", "NOT_RELEVANT", "BLOCKED_PII"):
                    entry["not_published"].append("끝까지 읽힌 글이 아니라서 다시 찾으면 또 나옵니다")
            if result.partial and (m := re.search(r"AI를 쓸 수 없어\((\w+)\)", result.reason)):
                read_down = read_down or m[1]
        if entry["error"]:
            echo(f"  읽지 못했습니다: {entry['error']}")
    stops = found.stop
    if read_down:
        stops = (stops + " " if stops else "") + f"고른 글을 읽는 중 {unavailable_text(read_down)} 일부는 끝까지 읽지 못했습니다"
    if found.unavailable == "NO_KEY":
        stops += "(keys.bat 으로 열쇠를 넣은 뒤 다시 하세요)"
    data = {"as_of": read_date.isoformat(), "days": days, "dry_run": bool(dry_run), "no_catalog": bool(no_catalog),
            "stop": stops, "unavailable": found.unavailable, "summary": found.summary, "limits": found.limits,
            "requests": client.count, "tool_calls": found.tool_calls,
            "boards": [{"name": b.name, "pages": b.pages, "seen": b.seen, "hidden_old": b.hidden_old, "undated": b.undated, "dropped": b.dropped,
                        "error": b.error} for b in found.stats],
            "picks": picks,
            "skips": [{"title": s.row.title, "posted": s.row.posted.isoformat() if s.row.posted else "", "dept": s.row.dept,
                       "url": s.row.url, "reason": s.reason} for s in found.skips]}
    tick("write")
    out = _inbox_root(root, catalog_dir) / f"scout-{stamp:%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    for name, text in (("report.json", json.dumps(data, ensure_ascii=False, indent=2) + chr(10)),
                       ("report.html", render_scout_report(data))):    # 보고서가 마지막
        tmp = out / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline=chr(10))
        os.replace(tmp, out / name)
    return data, out, bool(found.unavailable or read_down)


def _keys(args, backend) -> int:
    if args.cmd == "delete" and not args.name:
        print("사용법: python -m app.cli keys delete llm|hub  (지울 키 이름을 꼭 적어 주세요)")
        return 2
    try:
        return _keys_run(args, KeyStore(backend=backend))
    except (KeyringError, RuntimeError) as e:
        print(_KEYRING_DOWN.format(why=type(e).__name__))
        return 1


def _keys_run(args, store: KeyStore) -> int:
    if args.cmd == "set":
        value = getpass.getpass(f"{args.name} 키를 붙여넣고 Enter (화면에 보이지 않습니다): ")
        try:
            store.set(args.name, value)
        except ValueError as e:
            print(str(e))
            return 1
        print(f"{args.name} 키를 저장했습니다.")
    elif args.cmd == "show":
        for name in KEY_NAMES:
            print(f"{name}: {store.get_masked(name) or '저장된 키 없음'}")
    elif args.cmd == "test":
        c = store.test()
        print(f"자격 증명 저장소({c.backend}): " + ("정상" if c.ok else "쓸 수 없음"))
        return 0 if c.ok else 1
    else:
        store.delete(args.name)
        print(f"{args.name} 키를 지웠습니다.")
    return 0


def main(argv: list[str] | None = None, *, root: Path | None = None,
         clock: Callable[[], time] = _clock, backend=None, llm: LLMClient | None = None,
         http: Http | None = None, sleep: Callable[[float], None] | None = None, catalog_dir: Path | None = None) -> int:
    """명령줄 진입점. 반환값이 종료 코드.

    root, clock, backend, llm은 시험 전용 인자다. 운영에서는 쓰지 않는다.
      root    표·백업·로그가 있는 설치 폴더(기본 APP_ROOT)
      clock   시·분·초를 돌려주는 함수(기본 실제 시계)
      backend 키 저장소(기본 시스템 keyring)
      llm     공고 처리 LLM 클라이언트(기본 make_llm_client: 키 없으면 NullClient)
      http    notice --scout 의 게시판·공고 페이지 받기 대체(주소 → 바이트). 시험·시연 재생에서 고정본을 넘긴다
      sleep   notice --scout 의 요청 사이 쉬기 대체(시험에서는 기다리지 않게)
      catalog_dir  목록 자료 폴더(기본 root/data/catalog). 받은 함은 그 옆 inbox. notice 의 --catalog-dir 와 같다
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    # `data refresh` 뒤의 인자는 옵션(--help, --asof)까지 통째로 refresh_cli가 해석한다.
    # argparse.REMAINDER는 맨 앞 옵션을 못 받으므로, 머리말(전역 --asof + data refresh)만 파서에 준다.
    tail: list[str] = []
    for k in range(len(argv) - 1):
        if argv[k:k + 2] == ["data", "refresh"] and (k == 0 or (k == 2 and argv[0] == "--asof")):
            argv, tail = argv[:k + 2], argv[k + 2:]
            break
    args = _parser().parse_args(argv)
    if args.group == "data":                     # 나머지 인자(--help 포함)는 refresh_cli가 해석한다
        from app.data_layer import refresh_cli
        return refresh_cli.main((["--asof", args.asof] if args.asof else []) + list(args.rest) + tail)
    cfg = load_config(["--asof", args.asof] if args.asof else [])
    root = Path(root) if root else APP_ROOT
    if args.group == "tables":
        return _tables(args, root, cfg.as_of, datetime.combine(cfg.as_of, clock()))
    if args.group == "reminders":
        return _reminders(args, root, cfg)
    if args.group == "notice":
        if not args.scout and (args.days is not None or args.dry_run):
            print("--days 와 --dry-run 은 --scout 와 함께만 쓸 수 있습니다")
            return 2
        client = llm or make_llm_client(KeyStore(backend), today_fn=lambda: cfg.as_of)
        cdir = catalog_dir if catalog_dir is not None else args.catalog_dir
        if args.scout:
            return _scout(args, root, client, cfg.as_of, datetime.combine(cfg.as_of, clock()), http, sleep, cdir)
        return _notice(args, root, client, cfg.as_of, cdir)
    return _keys(args, backend)


if __name__ == "__main__":
    sys.exit(main())
