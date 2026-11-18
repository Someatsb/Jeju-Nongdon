"""인터넷 체험판 실행기(공개 체험판 모드). `python -X utf8 -m app.serve` 로 띄운다. Render 같은 서버용이다.

PC 실행기(app/launch.py)와 달리 포트를 훑지 않고, 이미 켜져 있나 보지 않고, 브라우저를 열지 않는다.
- 0.0.0.0:$PORT(없으면 10000)에 묶는다. 앞의 https 프록시가 보내는 X-Forwarded-* 를 믿는다.
- 재생 모드 + 기준일 2026-11-13(시연)으로 고정한다(run_replay.bat 과 같은 설정). 실제 AI 를 부르지 않고 .env·열쇠를 읽지 않는다.
- 공개 체험판 모드(app/ui/public_demo.py)를 켠다.
"""
import os
import sys
from dataclasses import replace

import uvicorn

from app.config import load_config
from app.ui.app import create_app

DEFAULT_PORT = 10000
AS_OF = "2026-11-13"


def make_app(port: int = DEFAULT_PORT):
    os.environ.setdefault("JC_PUBLIC_DEMO", "1")
    cfg = load_config(["--replay", "--asof", AS_OF, "--port", str(port)])
    return create_app(replace(cfg, public_demo=True))


def main() -> int:
    port = int(os.environ.get("PORT") or DEFAULT_PORT)
    app = make_app(port)
    # Windows 에서만 Selector 루프를 지정한다(launch.py 와 같은 이유). 리눅스는 기본 asyncio 루프.
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "asyncio"
    print(f"체험판을 켭니다: 0.0.0.0:{port} · 기준일 {AS_OF}(시연) · 재생 모드", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, loop=loop, log_level="warning", access_log=False,
                proxy_headers=True, forwarded_allow_ips="*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
