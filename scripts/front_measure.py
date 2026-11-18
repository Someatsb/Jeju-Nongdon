# -*- coding: utf-8 -*-
"""종이(앞면만, 2026-11-18 뒷면을 없앴다)의 실제 넘침과 쪽 수를 잰다.

사용
  1) 재생 서버로 P1~P5 (설명 문장 포함):
       python -X utf8 -m app.launch --replay --asof 2026-11-13 --port <PORT> --nobrowser
       python -X utf8 scripts/front_measure.py --port <PORT> [--out <캡처·PDF 폴더>]
  2) 저장해 둔 종이 HTML 폴더(골든 22건 등. 폴더 안 *.html 전부):
       python -X utf8 scripts/front_measure.py --dir <HTML 폴더> [--out <폴더>]
  끝나면 서버를 꼭 내린다(netstat -ano | findstr :<PORT> → taskkill /F /PID <PID>). 외부 네트워크·실호출 없음. 필요: playwright(chromium).

사례마다 출력: 쪽마다 본문 넘침 px · 남는 px · 줄 수 어림(render.front_lines, 한도 CARD_LINE_LIMIT) · 가실 곳 수 · 글자 단계 ·
  고정 문장 세 줄이 쪽 안에 온전히 있고 본문과 겹치지 않는지 · PDF 쪽 수(A4 인쇄 모양).
넘침(overflow)이 0보다 크거나 고정 문장이 잘리거나 겹치거나 PDF 쪽 수가 화면에 그려진 쪽 수와 다르면 FAIL 이고 마지막에 종료 코드 1.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))
from app.ui.render import CARD_LINE_LIMIT, front_lines  # noqa: E402

JS = """() => {
  const sheets = [...document.querySelectorAll('.sheet.front')];
  const pages = sheets.map(sh => {
    const body = sh.querySelector('.body');
    const r = body.getBoundingClientRect();
    const last = body.lastElementChild ? body.lastElementChild.getBoundingClientRect().bottom : r.top;
    const shr = sh.getBoundingClientRect();
    const foot = [...sh.querySelectorAll('.foot .line')].map(e => e.getBoundingClientRect());
    const footTop = foot.length ? Math.min(...foot.map(f => f.top)) : shr.bottom;
    return {overflow: Math.round(body.scrollHeight - body.clientHeight), spare: Math.round(r.bottom - last), body: Math.round(r.height),
            sheetOverflow: Math.round(sh.scrollHeight - sh.clientHeight), tier: sh.dataset.tier,
            foot: {n: foot.length, inside: foot.every(f => f.bottom <= shr.bottom + 0.5), apart: last <= footTop + 0.5}};
  });
  return {pages, rows: document.querySelectorAll('.sheet.front .pg, .sheet.front .rrw').length, backs: document.querySelectorAll('.sheet.back, [data-page="back"]').length,
          text: document.body.innerText.includes('뒷면')};
}"""


def pdf_pages(page) -> int:
    data = page.pdf(prefer_css_page_size=True, print_background=True)
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))


def measure(page, html: str, name: str, out: Path | None) -> bool:
    page.set_content(html)
    page.wait_for_timeout(150)
    m = page.evaluate(JS)
    pages = pdf_pages(page)
    est = front_lines(html)
    ps = m["pages"]
    ok = (all(p["overflow"] <= 0 and p["foot"]["n"] == 3 and p["foot"]["inside"] and p["foot"]["apart"] for p in ps) and pages == len(ps) and not m["backs"] and not m["text"])
    cols = " ".join(f"[{i + 1}쪽 단계={p['tier']} 넘침={p['overflow']:3} 본문 아래 남음={p['spare']:4}px]" for i, p in enumerate(ps))
    print(f"{name:12} {'OK  ' if ok else 'FAIL'} {cols} 줄추정(첫쪽 포함 전체)={est:5.1f}/{CARD_LINE_LIMIT:g} 곳={m['rows']} | PDF {pages}쪽(그린 쪽 {len(ps)})"
          + (" | 뒷면 요소가 있다" if m["backs"] else "") + (" | 뒷면 글이 있다" if m["text"] else ""))
    if out:
        out.mkdir(parents=True, exist_ok=True)
        for i in range(len(ps)):
            page.locator(".sheet.front").nth(i).screenshot(path=str(out / f"{name}_front{i + 1}.png"))
        (out / f"{name}.html").write_text(html, encoding="utf-8")
        (out / f"{name}.pdf").write_bytes(page.pdf(prefer_css_page_size=True, print_background=True))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--dir")
    ap.add_argument("--out")
    args = ap.parse_args()
    out = Path(args.out) if args.out else None
    ok_all = True
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 794, "height": 1123}, device_scale_factor=1240 / 794)
        page = ctx.new_page()
        page.set_default_timeout(120000)
        if args.dir:
            for f in sorted(Path(args.dir).glob("*.html")):
                ok_all &= measure(page, f.read_text(encoding="utf-8"), f.stem, out)
        if args.port:
            from _drive import to_result
            base = f"http://127.0.0.1:{args.port}"
            cases = json.load(open(APP / "data/replay/demo_inputs.json", encoding="utf8"))
            drive = ctx.new_page()
            drive.set_default_timeout(120000)
            for key in ("P1", "P2", "P3", "P4", "P5"):
                to_result(drive, base, cases[key]["form"], cases[key].get("already") or [])
                html = drive.request.get(base + "/counsel/print").text()           # 인쇄 경로와 같은 종이(검사를 통과해야 종이가 나온다)
                if 'data-page="front"' not in html:
                    print(f"{key:12} FAIL 인쇄 보류 화면이 나왔다: " + re.sub(r"\s+", " ", re.sub(r"<style.*?</style>|<[^>]+>", " ", html, flags=re.S))[:300])
                    ok_all = False
                else:
                    ok_all &= measure(page, html, key, out)
                drive.goto(base + "/")
        br.close()
    print("ALL OK" if ok_all else "FAIL 있음")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
