"""인터넷 판 실행기(공개 서버 모드). `python -X utf8 -m app.serve` 로 띄운다. Render 같은 서버용이다.

PC 실행기(app/launch.py)와 달리 포트를 훑지 않고, 이미 켜져 있나 보지 않고, 브라우저를 열지 않는다.
- 0.0.0.0:$PORT(없으면 10000)에 묶는다. 앞의 https 프록시가 보내는 X-Forwarded-* 를 믿는다.
- 재생 모드도, 기준일 고정도 아니다. 날짜는 한국 시간 오늘이고 요청마다 바뀌었는지 본다. 실제 AI 를 쓰고, 키는 환경변수 ANTHROPIC_API_KEY 에서만 읽는다
  (공급자·모델은 JC_LLM_PROVIDER·JC_LLM_MODEL, 하루 호출 한도는 JC_AI_DAILY_MAX). 키가 없으면 AI 없이 규칙 계산 결과만 나온다.
- 인터넷 판 모드(app/ui/public_demo.py)를 켠다.
"""
import os
import sys
from dataclasses import replace

import uvicorn

from app.config import kst_today, load_config
from app.ui.app import create_app

DEFAULT_PORT = 10000


def make_app(port: int = DEFAULT_PORT, *, llm=None):
    """llm: 시험용으로 끼우는 AI 클라이언트(없으면 환경변수 키로 만든다)."""
    os.environ.setdefault("JC_PUBLIC_DEMO", "1")
    cfg = load_config(["--port", str(port)])
    return create_app(replace(cfg, as_of=kst_today(), public_demo=True), llm=llm)


def main() -> int:
    port = int(os.environ.get("PORT") or DEFAULT_PORT)
    app = make_app(port)
    # Windows 에서만 Selector 루프를 지정한다(launch.py 와 같은 이유). 리눅스는 기본 asyncio 루프.
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "asyncio"
    ai = "실제 AI" if app.state.ai_live else "AI 키 없음(규칙 결과만)"
    print(f"인터넷 판을 켭니다: 0.0.0.0:{port} · 오늘 {app.state.cfg.as_of.isoformat()}(한국 시간) · {ai}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, loop=loop, log_level="warning", access_log=False,
                proxy_headers=True, forwarded_allow_ips="*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
