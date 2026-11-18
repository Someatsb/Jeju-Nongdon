# -*- coding: utf-8 -*-
"""실호출(키 있음) 화면 캡처: 재생 모드가 아닌 앱에서 P4를 제출하고 미리보기(검수 과정 표에 모델 판정이 보임)를 찍는다.
주의: 키 있는 실호출이라 비용이 든다(1회 약 $0.12). 재생(--replay)이 아닌 서버를 쓴다. 이 스크립트는 .env를 열지 않는다(키는 앱이 읽음).
사용: 1) 서버를 먼저 띄운다: python -X utf8 -m app.launch --asof 2026-11-13 --port <PORT> --nobrowser
      2) python -X utf8 scripts/capture_live.py <PORT> <OUT_DIR>
      3) 끝나면 서버를 꼭 내린다(netstat -ano | findstr :<PORT> → taskkill /F /PID <PID>).
필요: playwright(chromium), Pillow.
"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parents[1]
PORT = sys.argv[1]; OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
B = f"http://127.0.0.1:{PORT}"
form = json.load(open(APP / "data/replay/demo_inputs.json", encoding="utf8"))["P4"]["form"]


sys.path.insert(0, str(APP / "scripts"))
from _drive import to_result  # noqa: E402


with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 1600, "height": 3400}, device_scale_factor=1)
    page = ctx.new_page(); page.set_default_timeout(120000)
    t0 = time.monotonic()
    to_result(page, B, form)
    print("elapsed_s", round(time.monotonic() - t0, 1))
    page.screenshot(path=str(OUT / "shot_live_preview_tall.png"), full_page=True)
    page.click("#dt-open"); page.wait_for_timeout(300)          # 자세히 보기 덮개(직원이 볼 내용은 그 안)
    page.locator("details.staff").evaluate("e=>e.open=true")
    page.locator("details.staff").screenshot(path=str(OUT / "shot_live_review.png"))
    page.click('[data-pv-open="front"]'); page.wait_for_timeout(2500)          # 종이 크게 보기 덮개
    page.locator("iframe.pv-modal-frame").screenshot(path=str(OUT / "shot_live_paper.png"))
    print("replay note:", page.locator(".site-foot span").count(), "(실호출이면 체험 모드 문구가 없어야 함)")
    print("review text:", page.locator("details.staff").inner_text()[:800].replace("\n", " | "))
    fr = page.frame_locator("iframe.pv-modal-frame"); print("PAPER_HEAD", fr.locator("body").inner_text()[:500].replace("\n", " | "))
    br.close()
for f in sorted(OUT.glob("shot_live_*.png")):
    from PIL import Image; print(f.name, Image.open(f).size)
