# -*- coding: utf-8 -*-
"""재생 서버 화면 캡처: P4를 제출하고 입력·확인·결과 화면·직원용 창·공고 보고서·샘플 PDF 첫 쪽을 PNG로 저장한다.
사용: 1) 재생 서버를 먼저 띄운다: python -X utf8 -m app.launch --replay --asof 2026-11-13 --port <PORT> --nobrowser
      2) python -X utf8 scripts/capture_replay.py <PORT> <OUT_DIR>
      3) 끝나면 서버를 꼭 내린다(netstat -ano | findstr :<PORT> → taskkill /F /PID <PID>).
외부 네트워크·실호출 없음. 질문 화면 -> 확인 화면 -> 결과 화면 흐름은 scripts/_drive.py가 맡는다. 필요: playwright(chromium), Pillow, pypdfium2, samples/P4/print.pdf(make_samples.py), data/inbox/N1-*/report.html.
"""
import json, sys, shutil
from pathlib import Path
from PIL import Image
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright
APP = Path(__file__).resolve().parents[1]
PORT = sys.argv[1]; OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True); PW = 1600; PH = 3400
sys.path.insert(0, str(APP / "scripts"))
from _drive import fill_and_submit, to_result, goto as go  # noqa: E402
form = json.load(open(APP/"data/replay/demo_inputs.json", encoding="utf8"))["P4"]["form"]
B = f"http://127.0.0.1:{PORT}"
with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    page = ctx.new_page(); go(page, B+"/counsel/input")
    page.screenshot(path=str(OUT/"shot_b_input.png"))
    fill_and_submit(page, B, form)
    page.screenshot(path=str(OUT/"shot_b_confirm.png"), full_page=True)
    ctx.close()
    # 결과 화면(넓고 긴 창)
    ctx = br.new_context(viewport={"width": PW, "height": PH}, device_scale_factor=1)
    page = ctx.new_page(); to_result(page, B, form)
    page.screenshot(path=str(OUT/"shot_c_preview_tall.png"), full_page=True)
    page.click("#dt-open"); page.wait_for_timeout(300)          # 자세히 보기 덮개(직원이 볼 내용은 그 안)
    page.locator("details.staff").evaluate("e=>e.open=true")
    page.locator("details.staff").screenshot(path=str(OUT/"shot_c_review.png"))
    page.click('[data-pv-open="front"]'); page.wait_for_timeout(2500)          # 종이 크게 보기 덮개
    page.locator("iframe.pv-modal-frame").screenshot(path=str(OUT/"shot_c_preview_paper.png"))
    info = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
    fr = page.frame_locator("iframe.pv-modal-frame")
    txt = fr.locator("body").inner_text()
    print("page", info); print("PAPER_TEXT_HEAD", txt[:600].replace("\n"," | "))
    print("review_text", page.locator("details.staff").inner_text()[:300].replace("\n"," | "))
    print("replay_note", page.locator(".site-foot").first.inner_text())
    ctx.close()
    # notice report
    ctx = br.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto((next((APP/"data/inbox").glob("N1-*/report.html"))).as_uri())
    page.screenshot(path=str(OUT/"shot_f_notice.png"), full_page=True)
    print("notice text", page.locator("body").inner_text()[:500].replace("\n"," | "))
    br.close()
pdf = pdfium.PdfDocument(str(APP/"samples/P4/print.pdf"))
for i in range(len(pdf)):                                   # 종이는 한 면뿐(뒷면 없음). 쪽이 이어지면 front_P4_2 …
    pdf[i].render(scale=952/pdf[i].get_size()[0]).to_pil().save(OUT/("front_P4.png" if i == 0 else f"front_P4_{i + 1}.png"))
for f in sorted(OUT.glob("*.png")): print(f.name, Image.open(f).size)
