"""실행 설정(Task 6, U06). 오늘 날짜를 읽는 곳은 이 파일의 `_today()` 하나뿐이다.

`--asof YYYY-MM-DD`를 주면 그날이 기준일이 되고 `demo_asof=True`가 된다. 화면·종이 머리에
"기준일 2026-11-13(시연)"이 찍히고, 뒤 작업이 네트워크 갱신을 끄고 스냅샷을 그날까지로 자른다.
`--replay`는 녹화 응답 재생(Task 32): 앱을 만들 때(ui/app.py) replay_dir의 녹화로 설명 문장을 만들고 모든 화면에 띠를 단다.
`port`는 시작 포트다. 기본 8765이고, 실행기(app/launch.py)가 8765~8775에서 첫 빈 포트를 고른다.
"""
import argparse
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PORT_FIRST, PORT_LAST = 8765, 8775


@dataclass(frozen=True)
class Config:
    as_of: date
    demo_asof: bool
    replay: bool
    port: int
    tables_dir: Path
    snapshot_dir: Path
    replay_dir: Path = APP_ROOT / "data" / "replay"    # --replay가 읽는 녹화 폴더(Task 32)
    service_name: str = "제주 농돈"      # 종이·화면 머리에 찍는 이름(Task 17)
    service_subtitle: str = "농가가 받을 돈, 한 장으로"   # 종이 머리 부제(Task 17)
    center_phone: str = ""               # 재방문 문자에 적는 센터 전화(Task 39). 비면 "센터로 연락 주세요"
    catalog_dir: Path = APP_ROOT / "data" / "catalog"   # 지원 전체 보기 자료(links.csv, notices/). --catalog-dir 로 시험용 폴더를 줄 수 있다
    public_demo: bool = False            # 공개 체험판 모드(환경변수 JC_PUBLIC_DEMO=1, 재생 모드와 함께만). 인터넷에 띄우는 심사용 체험판이다(ui/public_demo.py)


def _today() -> date:
    return date.today()


def today_fn() -> date:
    """공개 접근자: 오늘 날짜(하루 상한 같은 곳이 쓴다). 시계는 여전히 _today() 한 곳에서만 읽는다."""
    return _today()


def _asof(text: str) -> date:
    try:
        if len(text) != 10:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"기준일은 2026-11-13처럼 YYYY-MM-DD로 넣어 주세요: {text}") from None


def _port(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"포트는 1024~65535 사이 숫자로 넣어 주세요: {text}")
    return port


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run", description="제주 농돈 실행")
    p.add_argument("--asof", type=_asof, metavar="YYYY-MM-DD", help="시연 기준일(오늘 대신 이 날짜로 판정)")
    p.add_argument("--replay", action="store_true", help="녹화한 LLM 응답 재생")
    p.add_argument("--port", type=_port, default=PORT_FIRST,
                   help=f"시작 포트(기본 {PORT_FIRST}, {PORT_FIRST}~{PORT_LAST}에서 첫 빈 포트)")
    p.add_argument("--catalog-dir", type=Path, default=None, help=argparse.SUPPRESS)   # 화면 점검용: 지원 전체 보기 자료 폴더
    return p


def load_config(argv: list[str]) -> Config:
    args = _parser().parse_args(argv)
    return Config(
        as_of=args.asof if args.asof is not None else _today(),
        demo_asof=args.asof is not None,
        replay=args.replay,
        port=args.port,
        tables_dir=APP_ROOT / "data" / "tables",
        snapshot_dir=APP_ROOT / "data" / "snapshot",
        catalog_dir=args.catalog_dir if args.catalog_dir is not None else APP_ROOT / "data" / "catalog",
        public_demo=os.environ.get("JC_PUBLIC_DEMO") == "1",
    )
