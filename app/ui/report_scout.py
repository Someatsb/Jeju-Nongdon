"""새 공고 찾기 보고서(직원이 읽는 한 장). 명령줄 app/cli.py 가 찾기 결과를 dict 로 만들어 넘기면 쉬운 한국어 HTML 로 바꾼다.

싣는 것: 게시판별 본 글 수, 고른 글(제목·날짜·부서·이유·공고 에이전트 결정·목록에 올랐는지·못 올랐으면 이유), 건너뛴 글과 이유, 중단 사유.
사람 이름은 싣지 않는다(부서 칸은 찾을 때 이미 걸러진다). 글은 모두 html.escape 를 거치고, 링크는 공식 사이트 https 주소만 건다.
에이전트 층은 이 모듈을 부르지 않는다. 시연 재생(replay_cli)이 띠를 달 수 있도록 <body> 태그는 그대로 둔다.
"""
from __future__ import annotations

from html import escape
from typing import Any

from app.catalog.links import is_official_url

_CSS = """
body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:0;padding:24px;color:#1b1b1b;background:#fafaf7;line-height:1.55}
main{max-width:980px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.15rem;margin:28px 0 8px}
.sub{color:#555;margin:0 0 16px}
.box{border:1px solid #cfcfc4;border-radius:8px;padding:10px 14px;margin:12px 0;background:#fff}
.warn{border-color:#c0822b;background:#fff6e5}.ok{border-color:#4b8a5a;background:#eef8f0}
table{border-collapse:collapse;width:100%;background:#fff}
th,td{border:1px solid #d9d9cf;padding:6px 8px;text-align:left;vertical-align:top;font-size:.93rem}
th{background:#f0efe6}
.small{color:#666;font-size:.85rem}
a{color:#1a5fb4}
"""


def _t(value: Any) -> str:
    return escape("" if value is None else str(value))


def _title_cell(item: dict) -> str:
    title = _t(item.get("title"))
    url = item.get("url") or ""
    return f'<a href="{escape(url, quote=True)}">{title}</a>' if is_official_url(url) else title


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="small">{_t(empty)}</p>'
    head = "".join(f"<th>{_t(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _upload_cell(item: dict) -> str:
    if item.get("error"):
        return f"읽지 못했어요: {_t(item['error'])}"
    if item.get("note"):
        return _t(item["note"])
    if item.get("published"):
        again = " (같은 주소의 옛 공고를 바꿨어요)" if item.get("replaced") else ""
        better = "".join(f" ({_t(x)})" for x in item.get("upgraded", []))
        return "올렸어요: " + ", ".join(_t(n) for n in item["published"]) + again + better
    why = "; ".join(_t(x) for x in item.get("not_published", []))
    return "올리지 않았어요" + (f": {why}" if why else "")


def render_scout_report(data: dict) -> str:
    boards = [[_t(b["name"]), _t(b["seen"]) + "건" if b.get("pages") else "보지 않음", _t(b.get("hidden_old", 0)) + "건",
               _t(b["error"]) if b.get("error") else ("" if b.get("pages") else "이번에는 열지 않았어요")] for b in data.get("boards", [])]
    picks = [[_title_cell(p), _t(p.get("posted")), _t(p.get("dept")), _t(p.get("reason")),
              _t(p.get("decision_label") or "읽지 않음"), _upload_cell(p)] for p in data.get("picks", [])]
    skips = [[_title_cell(s), _t(s.get("posted")), _t(s.get("dept")), _t(s.get("reason"))] for s in data.get("skips", [])]
    parts = ['<!doctype html><html lang="ko"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             f"<title>공고 찾기 결과</title><style>{_CSS}</style></head>", "<body>", "<main>",
             "<h1>공고 찾기 결과</h1>",
             f'<p class="sub">기준일 {_t(data.get("as_of"))} · 최근 {_t(data.get("days"))}일 안의 글 · '
             f'게시판 요청 {_t(data.get("requests"))}번 · AI 도구 호출 {_t(data.get("tool_calls"))}번</p>']
    if data.get("dry_run"):
        parts.append('<div class="box warn">시험 삼아 고르기까지만 했어요. 고른 글은 읽지 않았고 목록에도 올리지 않았어요.</div>')
    if data.get("stop"):
        parts.append(f'<div class="box warn"><strong>중간에 멈춘 이유</strong><br>{_t(data["stop"])}</div>')
    elif data.get("summary"):
        parts.append('<div class="box ok">AI가 끝까지 살펴보고 마쳤어요.</div>')
    for limit in data.get("limits", []):
        parts.append(f'<div class="box warn">한도에 닿았어요: {_t(limit)}</div>')
    if data.get("summary"):
        parts.append(f'<h2>AI가 정리한 말</h2><div class="box">{_t(data["summary"])}</div>')
    parts += ["<h2>게시판별로 본 글</h2>",
              _table(["게시판", "본 글(최근 글)", "기간 밖이라 안 본 글", "열지 못한 이유"], boards, "살펴본 게시판이 없어요"),
              f"<h2>고른 글 {len(picks)}건</h2>",
              _table(["제목", "올린 날", "부서", "고른 이유", "공고 읽기 결정", "목록에 올랐는지"], picks, "고른 글이 없어요"),
              f"<h2>건너뛴 글 {len(skips)}건</h2>",
              _table(["제목", "올린 날", "부서", "건너뛴 이유"], skips, "건너뛴 글이 없어요"),
              '<p class="small">AI는 고르기만 해요. 목록에 올라간 내용은 공고 원문 문장으로 확인된 것만이고, 최종 확인은 직원이 해요.</p>',
              "</main></body></html>"]
    return "\n".join(parts) + "\n"
