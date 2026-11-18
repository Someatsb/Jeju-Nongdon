# -*- coding: utf-8 -*-
"""결과 화면의 "새로 나온 공고" 자리 채우기(static/result.js 폴링)를 실제 브라우저로 확인한다.

설명 글(재생 녹화)은 곧 끝나고, 새 공고 맞춰 보기(가짜: 몇 초 뒤 끝남)가 늦게 끝나는 서버를 이 스크립트가 직접 띄운다. 실제 AI·인터넷은 쓰지 않는다.
확인하는 것: (1) 설명 글이 끝난 뒤에도 맞춰 보기가 도는 동안 계속 묻는다 (2) 도는 중에는 "새로 나온 공고도 살펴보고 있어요…" 한 줄
(3) 끝나면 같은 화면 안에서 상자·알림 줄·공고 원문 줄·직원 칸이 채워진다 (4) 화면 읽기 알림 "새로 나온 공고 ○건이 맞을 수 있어요".
사용: python -X utf8 scripts/check_new_notices_poll.py [포트]   (playwright 필요)
"""
import socket
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP / "scripts")]

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from _drive import demo_inputs, fill_and_submit  # noqa: E402
from app.agents.match import MatchCheck, MatchItem, MatchReport  # noqa: E402
from app.config import load_config  # noqa: E402
from app.ui.app import create_app  # noqa: E402

SLOW_S = 5.0


def fake(profile, fs, notices):
    time.sleep(SLOW_S)
    n = next(x for x in notices if "감귤" in x.name)
    return MatchReport(source="ai", candidates=len(notices), note="확인 1번", items=(
        MatchItem(key=n.key, name=n.name, verdict="맞을 수 있음", why="감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요", ask=("농협에서 받는지",),
                  period=n.apply_period, checks=(MatchCheck(kind="작물", quote=n.name, answer="예"),)),))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8894
    cfg = load_config(["--asof", "2026-11-13", "--replay", "--port", str(port)])
    app = create_app(cfg)
    app.state.matcher = fake
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    inp = demo_inputs()["P1"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_context(viewport={"width": 1920, "height": 940}).new_page()
        page.set_default_timeout(60000)
        fill_and_submit(page, base, inp["form"])
        for k in inp.get("already") or []:
            page.locator(f'input[name="already"][value="{k}"]').check(force=True)
        page.click("#next-btn")
        page.wait_for_url("**/counsel/preview")
        page.wait_for_selector(".rband")
        t0 = time.monotonic()
        # (1)(2) 설명 글은 곧 끝나는데 맞춰 보기는 아직: 한 줄만 있고 상자는 없다
        page.wait_for_selector("#ai-state[data-ai='done']", state="attached")
        assert page.locator("#ai-state").get_attribute("data-match") == "run"
        assert page.locator(".nn-run").inner_text().strip() == "새로 나온 공고도 살펴보고 있어요…"
        assert page.locator("#new-notices").count() == 0 and page.locator(".nn-alert").count() == 0
        # (3) 늦게 끝난 맞춰 보기가 같은 화면(새로 고침 없음)에 채워진다
        page.wait_for_selector("#new-notices", timeout=30000)
        waited = time.monotonic() - t0
        assert waited >= SLOW_S - 2.0, f"맞춰 보기가 끝나기 전에 채워졌다({waited:.1f}초)"
        assert page.locator(".nn-run").count() == 0
        assert page.locator("#new-notices .nn-row").count() == 1 and page.locator("a.nn-alert").count() == 1
        assert "새로 나온 공고 1건이 맞을 수 있어요" in page.locator("a.nn-alert").inner_text()
        assert page.locator("#nn-live").inner_text() == "새로 나온 공고 1건이 맞을 수 있어요"          # (4) 화면 읽기 프로그램 알림
        assert page.locator("#detail .lk-box li.lk[data-key^='new-']").count() == 1
        page.wait_for_function("document.querySelector('[data-match-staff] #match-staff') && !document.querySelector('[data-match-staff] .ai-pend')")
        assert "맞을 수 있음 1건" in page.locator("[data-match-staff]").inner_text()
        br.close()
    server.should_exit = True
    print(f"OK 맞춰 보기가 {waited:.1f}초 뒤 같은 화면에 채워짐(설명 글은 먼저 끝남)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
