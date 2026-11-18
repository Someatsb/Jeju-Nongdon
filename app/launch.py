"""실행기(Task 6, U06). run.bat이 부른다: python -X utf8 -m app.launch [--asof YYYY-MM-DD] [--replay] [--port N] [--nobrowser]

1. 8765~8775를 한 번 훑는다. 포트마다 127.0.0.1에 bind를 한 번만 해 본다(0.0.0.0 금지, 방화벽 허용 창을 피함).
   - 묶이면 빈 포트다. 첫 빈 포트의 소켓은 들고 있다가 그대로 uvicorn에 넘긴다(닫았다 다시 묶지 않는다).
   - 안 묶이면 쓰이는 포트다. 그 포트만 /health로 물어 우리 앱이면 브라우저만 연다(두 번 더블클릭 대비).
     빈 포트에 연결을 시도하면 Windows는 거절까지 2초쯤 기다리므로 빈 포트에는 묻지 않는다.
2. 서버가 뜨는 순간(startup 끝) Edge를 연다: start msedge http://127.0.0.1:<port>
3. 소켓 호출을 가로채는 보안 프로그램이 깔린 PC에서는 bind·listen과 asyncio 루프 만들기가 가끔 WinError 10014로
   실패하고, 닫은 포트가 바로 풀리지 않는다(개발 PC 실측). 그래서 bind는 몇 번 다시 해 보고, 뜨기 전 실패는 다음
   포트로 처음부터 다시 하며, 15초 안에 못 켜지면 한국어로 알리고 끝낸다(종료 코드 1).
OS 호출(소켓·프로세스·브라우저)은 이 파일에만 둔다. app/core에는 두지 않는다.
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import replace

import httpx
import uvicorn

from app.config import PORT_FIRST, PORT_LAST, load_config
from app.data_layer.snapshot import SnapshotError
from app.data_layer.tables import TableLoadError
from app.ui.app import create_app

HOST = "127.0.0.1"
FIRST_LINE = "이 검은 창을 닫으면 프로그램이 꺼집니다. 창은 최소화해 두세요."
HEALTH_KEYS = {"ok", "as_of", "demo"}
WSAEFAULT = 10014        # 가로채인 소켓 호출이 내는 일시 오류
BIND_ATTEMPTS = 5
START_ATTEMPTS = 10      # 실패한 시도는 0.5초 안에 끝난다. 실패는 몰려서 오므로 넉넉히 둔다
START_WAIT_S = 15.0
# Windows 기본 Proactor 루프는 accept 하나가 실패하면(WinError 64, 연결이 accept 전에 끊김) 듣는 소켓을
# 닫아 버려 창은 떠 있는데 화면이 안 열린다(실측). Selector 루프는 그 오류를 기록만 하고 계속 받는다.
SERVER_LOOP = "asyncio:SelectorEventLoop"

Running = tuple[int, dict]  # (포트, /health 응답)


def candidate_ports(start: int) -> list[int]:
    """시작 포트가 8765~8775 안이면 거기서 8775까지, 밖이면 그 포트 하나."""
    return list(range(start, PORT_LAST + 1)) if PORT_FIRST <= start <= PORT_LAST else [start]


def try_bind(port: int) -> socket.socket | None:
    """127.0.0.1:port에 묶은 소켓. 쓰이는 포트면 None."""
    for _ in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # SO_REUSEADDR 없음: Windows에서는 남의 포트를 빼앗는다
        try:
            sock.bind((HOST, port))
            return sock
        except OSError as e:
            sock.close()
            if getattr(e, "winerror", None) != WSAEFAULT:
                return None
            time.sleep(0.02)
    return None


def probe_health(port: int) -> dict | None:
    """우리 앱의 /health 응답이면 그 dict, 아니면 None."""
    for _ in range(2):
        try:
            r = httpx.get(f"http://{HOST}:{port}/health", timeout=1.0, trust_env=False)
            body = r.json()
        except httpx.ConnectError:
            continue  # 일시 오류일 수 있어 다시 묻는다(쓰이는 포트에만 묻으므로 거절은 드물다)
        except (httpx.HTTPError, ValueError):
            return None
        if r.status_code == 200 and isinstance(body, dict) and HEALTH_KEYS <= body.keys() and body["ok"] is True:
            return body
        return None
    return None


def scan(ports: Sequence[int], bind: Callable[[int], socket.socket | None] = try_bind,
         probe: Callable[[int], dict | None] = probe_health) -> tuple[Running | None, socket.socket | None]:
    """(이미 떠 있는 우리 앱, 첫 빈 포트에 묶은 소켓). 앱을 찾으면 소켓은 닫고 None."""
    free = None
    for port in ports:
        sock = bind(port)
        if sock is None:
            health = probe(port)
            if health is not None:
                if free is not None:
                    free.close()
                return (port, health), None
        elif free is None:
            free = sock
        else:
            sock.close()
    return None, free


def open_browser(url: str) -> None:
    if sys.platform == "win32":
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "msedge", url])
            return
        except OSError:
            pass
    webbrowser.open(url)


class _Server(uvicorn.Server):
    """startup이 끝나 요청을 받을 수 있게 된 뒤에 ready를 켜고 on_started를 부른다(브라우저를 너무 일찍 열지 않게)."""

    def __init__(self, config: uvicorn.Config, ready: threading.Event, on_started: Callable[[], None] | None) -> None:
        super().__init__(config)
        self.ready, self.on_started = ready, on_started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self.ready.set()
            if self.on_started is not None:
                self.on_started()


def _watchdog(ready: threading.Event) -> None:
    """15초 안에 못 켜지면 알리고 끝낸다. Windows asyncio는 루프를 만들 때 127.0.0.1 소켓 쌍을 만드는데,
    그 연결이 가로채이면 accept에서 아무 말 없이 멈추기 때문이다(개발 PC 실측)."""
    if not ready.wait(START_WAIT_S):
        print("프로그램이 15초 안에 켜지지 않았습니다. 검은 창을 닫고 다시 실행해 주세요.", flush=True)
        os._exit(1)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    no_browser = "--nobrowser" in argv
    cfg = load_config([a for a in argv if a != "--nobrowser"])
    print(FIRST_LINE, flush=True)
    ports = candidate_ports(cfg.port)
    ready = threading.Event()
    watchdog = threading.Thread(target=_watchdog, args=(ready,), daemon=True)

    for attempt in range(1, START_ATTEMPTS + 1):
        running, sock = scan(ports)
        if running is not None:
            port, health = running
            print(f"이미 켜져 있습니다. 브라우저만 엽니다: http://{HOST}:{port}", flush=True)
            if (health["as_of"], health["demo"]) != (cfg.as_of.isoformat(), cfg.demo_asof):
                print(f"켜져 있는 프로그램의 기준일은 {health['as_of']}{'(시연)' if health['demo'] else ''}입니다. "
                      "바꾸려면 그 검은 창을 닫고 다시 실행해 주세요.", flush=True)
            if not no_browser:
                open_browser(f"http://{HOST}:{port}")
            return 0
        if sock is None:
            span = f"{ports[0]}~{ports[-1]}번 포트가 모두" if len(ports) > 1 else f"{ports[0]}번 포트가"
            print(f"{span} 다른 프로그램에 쓰이고 있습니다. 그 프로그램을 닫고 다시 실행해 주세요.", flush=True)
            return 1

        port = sock.getsockname()[1]
        url = f"http://{HOST}:{port}"
        try:
            app = create_app(replace(cfg, port=port))  # Origin 검사가 실제 포트를 쓰도록
        except (TableLoadError, SnapshotError, FileNotFoundError) as e:
            sock.close()
            reason = " ".join(str(e).split())[:200] or type(e).__name__
            print(f"표 또는 저장본 파일을 읽지 못해 켜지 않았습니다: {reason} — 담당자에게 알리고, 먼저 tables.bat check 로 확인해 주세요.", flush=True)
            return 2
        config = uvicorn.Config(app, host=HOST, port=port, loop=SERVER_LOOP, log_level="warning",
                                access_log=False)  # 접속 기록에 주소창 값이 남지 않게
        server = _Server(config, ready, None if no_browser else (lambda u=url: open_browser(u)))
        print(f"주소: {url}" + (f" · 기준일 {cfg.as_of.isoformat()}(시연)" if cfg.demo_asof else ""), flush=True)
        if watchdog.ident is None:  # 첫 시도에서 한 번만 켠다
            watchdog.start()
        try:
            server.run(sockets=[sock])
            return 0
        except OSError as e:
            sock.close()
            if server.started or attempt == START_ATTEMPTS:
                print(f"프로그램을 켜지 못했습니다({e}). 검은 창을 닫고 다시 실행해 주세요.", flush=True)
                return 1
            print("켜는 중 소켓 오류가 나서 다시 시도합니다.", flush=True)
            if len(ports) > 1:
                ports = [p for p in ports if p != port]  # 방금 닫은 포트는 바로 풀리지 않을 수 있다
            time.sleep(0.3)
    return 1


if __name__ == "__main__":
    sys.exit(main())
