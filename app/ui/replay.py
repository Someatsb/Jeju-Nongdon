"""재생 모드 연결(Task 32, U32): `--replay`면 data/replay/P*.json의 녹화 답으로 설명 문장을 만든다. 실제 LLM은 부르지 않는다.

- 모든 화면 위 띠(app.state.replay_banner)와 종이의 숫자 없는 줄(replay_line)을 채운다.
- 상담의 계산 지문(fingerprint)이 녹화의 input_hash와 같은 녹화를 찾아 ReplayClient로 narrate를 돌린다.
  같은 녹화가 없으면(시연 농가가 아님) 설명 없이 템플릿으로 가고, 결과 화면에 "녹화와 입력이 다릅니다…"를 보인다(오류 화면 아님).
- 검수 로그 줄에 injected를 더한다: 그 시도의 답이 녹화에서 injected인 것이면 화면이 "주입"으로 보인다.
"""
import logging
import re
from pathlib import Path

from fastapi import FastAPI

from app.agents.counsel import Narrative, narrate
from app.agents.llm.factory import make_llm_client
from app.agents.llm.keystore import KeyStore
from app.agents.llm.recording import PAPER_LINE, REPLAY_MISMATCH_MESSAGE, Recording, ReplayClient, banner_for, load_recording
from app.agents.reviewer import MemoryReviewLog
from app.agents.match import MatchReport
from app.core.models import FactSheet
from app.core.pipeline import fingerprint
from app.ui.match_job import make_matcher

_log = logging.getLogger(__name__)
MIXED = "녹화 여러 건(혼합) — 실제 LLM 호출 아님"


class _NoKeyring:
    """재생 모드는 열쇠 저장소를 읽지 않는다(공장이 replay를 먼저 본다). 그래도 시스템 keyring에는 손대지 않는다."""

    def get_password(self, service, username):
        return None


NO_MATCH_RECORDING = "이 농가의 저장된 맞춰 보기 녹화(data/replay/M-P1.json 등)가 없어요"
NO_RECORDING = "재생할 녹화 파일(data/replay/P1.json 등)이 없어요. 담당자에게 알려 주세요."


class ReplayDeck:
    """data/replay의 시연 농가 녹화(P1~P5)."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        paths = sorted(p for p in self.directory.glob("P*.json") if re.fullmatch(r"P\d+\.json", p.name))
        loaded: list[tuple[Path, Recording]] = []
        self.unreadable = 0
        for p in paths:
            try:
                loaded.append((p, load_recording(p)))
            except (OSError, ValueError):     # 깨진 JSON·형식 오류(pydantic ValidationError는 ValueError)
                self.unreadable += 1
                _log.exception("녹화 파일을 읽지 못해 건너뜁니다: %s", p.name)
        self._paths = {r.sample_id: p for p, r in loaded}
        self._match_paths: dict[str, Path] = {}      # 상담 지문 -> 새 공고 맞춰 보기 녹화(M-P<번호>.json). 상담 설명 녹화와 따로 둔다
        for p in sorted(self.directory.glob("M-P*.json")):
            if not re.fullmatch(r"M-P\d+\.json", p.name):
                continue
            try:
                self._match_paths[load_recording(p).input_hash] = p
            except (OSError, ValueError):
                self.unreadable += 1
                _log.exception("맞춰 보기 녹화 파일을 읽지 못해 건너뜁니다: %s", p.name)
        self.recordings: tuple[Recording, ...] = tuple(r for _, r in loaded)

    @property
    def banner(self) -> str:
        if not self.recordings:
            text = NO_RECORDING
        else:
            kinds = {(r.source, r.provider, r.model) for r in self.recordings}
            text = banner_for(self.recordings[0]) if len(kinds) == 1 else MIXED
        if self.unreadable:
            text += f" · 녹화 파일 {self.unreadable}개를 읽을 수 없어요"
        return text

    def find(self, fs: FactSheet) -> Recording | None:
        fp = fingerprint(fs)
        return next((r for r in self.recordings if r.input_hash == fp), None)

    def check(self, fs: FactSheet) -> str | None:
        return None if self.find(fs) is not None else REPLAY_MISMATCH_MESSAGE

    def matcher(self, crops, as_of):
        """새 공고 맞춰 보기: 이 상담의 지문과 같은 녹화(M-P*.json)가 있으면 그것으로 돌리고, 없으면 source="none"."""
        def run(profile, fs: FactSheet, notices):
            path = self._match_paths.get(fingerprint(fs))
            if path is None:
                return MatchReport(source="none", note=NO_MATCH_RECORDING)
            client = make_llm_client(KeyStore(backend=_NoKeyring()), replay=path)
            return make_matcher(client, crops, as_of)(profile, fs, notices)
        return run

    def narrator(self, log: MemoryReviewLog):
        def run(fs: FactSheet) -> Narrative:
            rec = self.find(fs)
            if rec is None:
                raise LookupError(REPLAY_MISMATCH_MESSAGE)
            client = make_llm_client(KeyStore(backend=_NoKeyring()), replay=self._paths[rec.sample_id])
            assert isinstance(client, ReplayClient)
            before = len(log.entries)
            narrative = narrate(fs, client, log)
            _mark_injected(log.entries[before:], client)
            return narrative
        return run


def _mark_injected(entries: list[dict], client: ReplayClient) -> None:
    """섹션 안에서 k번째 설명 요청의 답이 주입이면 검수 로그의 attempt k 줄에 injected=True."""
    nth: dict[str | None, list[bool]] = {}
    for purpose, section, injected in client.served:
        if purpose == "narrate":
            nth.setdefault(section, []).append(injected)
    for e in entries:
        attempt = e.get("attempt", 0)
        flags = nth.get(e.get("section"), [])
        e["replay"] = True
        if attempt >= 1 and attempt <= len(flags) and flags[attempt - 1]:
            e["injected"] = True


def install_replay(app: FastAPI, directory: Path) -> ReplayDeck:
    deck = ReplayDeck(directory)
    state = app.state
    state.replay_banner = deck.banner
    state.replay_line = PAPER_LINE
    state.replay_check = deck.check
    state.review_log = log = MemoryReviewLog()
    state.narrator = deck.narrator(log)
    state.matcher = deck.matcher(state.tables.crops, state.cfg.as_of)
    return deck
