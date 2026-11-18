"""data.bat의 진입점(Task 26, U26): python -X utf8 -m app.data_layer.refresh_cli [--asof ...]

가격표(허브 1361)와 수급센터 감귤 자료를 증분 갱신한다. 시계는 app.config가 읽은 기준일만 쓴다.
키는 KeyStore("hub")에서 읽고 화면에 찍지 않는다. --asof(시연)면 갱신을 거부한다.
뒤 작업이 app/cli.py의 `data refresh`로 이 main을 연결한다.
"""
from __future__ import annotations

import sys

from app.data_layer.refresh import RefreshRefused, RefreshReport, update

_HUB_TEXT = {"ok": "갱신됨", "offline": "갱신 못함(직전 자료 사용)", "capped": "오늘 호출 한도까지만 갱신"}


def main(argv: list[str] | None = None) -> int:
    from app.agents.llm.keystore import KeyStore
    from app.config import load_config

    cfg = load_config(list(sys.argv[1:] if argv is None else argv))
    keys = {"hub": KeyStore().get("hub") or ""}
    try:
        rep: RefreshReport = update(cfg, cfg.snapshot_dir, keys)
    except RefreshRefused as e:
        print(str(e))
        return 2
    print(f"가격표(허브 1361): {_HUB_TEXT.get(rep.hub, rep.hub)} · 호출 {rep.calls_1361}회")
    print(f"수급센터 감귤: {_HUB_TEXT.get(rep.jasdc, rep.jasdc)}")
    if rep.partial_days:
        print("하루치를 다 받지 못한 날: " + ", ".join(rep.partial_days))
    if rep.rewritten:
        print("새로 쓴 파일: " + ", ".join(rep.rewritten))
    for m in rep.messages:
        print(m)
    return 0 if rep.hub != "offline" or rep.jasdc != "offline" else 1


if __name__ == "__main__":
    raise SystemExit(main())
