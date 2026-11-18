"""공고 받은편지함(Task 18) — 직원이 data/inbox/에 떨군 공고 파일을 나열하고 하나 꺼낸다. 최소한만."""
from pathlib import Path

from app.data_layer.docs_in import Doc, extract

INBOX = Path(__file__).resolve().parents[2] / "data" / "inbox"
SUFFIXES = (".pdf", ".txt", ".hwp", ".hwpx")


def list_inbox(inbox: Path = INBOX) -> "tuple[str, ...]":
    """받은 공고 파일 이름(이름순). 폴더가 없으면 빈 목록."""
    if not inbox.is_dir():
        return ()
    return tuple(sorted(p.name for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES))


def take(name: str, inbox: Path = INBOX) -> Doc:
    """이름으로 파일 하나를 읽어 Doc으로 돌려준다. 폴더 밖 경로는 거부한다."""
    if Path(name).name != name or name not in list_inbox(inbox):
        raise FileNotFoundError(f"받은편지함에 '{name}' 파일이 없습니다")
    return extract(inbox / name)


list_names = list_inbox  # 이전 이름 유지
