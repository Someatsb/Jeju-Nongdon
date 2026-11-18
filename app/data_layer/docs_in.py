"""공고 문서 읽기(Task 18, U18) — PDF·텍스트를 쪽·줄로 나눈다. LLM 없이, 결정적으로.

- extract(경로 또는 본문 글) -> Doc. .pdf는 pypdf, .txt와 붙여넣은 글은 그대로(쪽 구분은 폼피드 \f).
- 줄은 앞뒤 공백을 떼고 빈 줄을 버린다. 앵커 "p쪽:L줄"의 번호는 이 줄 기준이다.
- 스캔본 판정: 쪽의 공백 아닌 글자가 50 미만이면 글자 층이 없는 쪽으로 센다.
  그런 쪽이 전체의 절반을 넘으면(글이 없는 문서 포함) scanned=True. 일부 쪽만 비어 있으면(표지·빈 서식) 본문이 있는 문서로 본다.
- .hwp/.hwpx는 읽지 않고 UnsupportedFormat. 암호 PDF와 깨진·PDF 아닌 파일도 같다(본문 붙여넣기 안내).
"""
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

MIN_PAGE_CHARS = 50
_TEXT_SUFFIXES = {".txt", ".pdf", ".hwp", ".hwpx"}


class UnsupportedFormat(ValueError):
    """읽을 수 없는 형식. 메시지는 직원에게 그대로 보여 줄 한국어 안내다."""


@dataclass(frozen=True)
class Page:
    number: int                  # 1부터
    lines: tuple[str, ...]

    @cached_property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def chars(self) -> int:
        return sum(1 for ch in self.text if not ch.isspace())


@dataclass(frozen=True)
class Doc:
    pages: tuple[Page, ...]
    scanned: bool

    @cached_property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)


def _page(number: int, raw: str) -> Page:
    lines = tuple(s for s in (ln.strip() for ln in raw.splitlines()) if s)
    return Page(number, lines)


def _build(raw_pages: list[str]) -> Doc:
    pages = tuple(_page(i, raw) for i, raw in enumerate(raw_pages, 1))
    thin = sum(1 for p in pages if p.chars < MIN_PAGE_CHARS)
    return Doc(pages, scanned=thin * 2 > len(pages) or not pages)


def _read_pdf(path: Path) -> list[str]:
    from pypdf import PdfReader  # 지연 import: PDF를 읽을 때만 필요하다

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnsupportedFormat("암호가 걸린 PDF입니다. 암호를 풀어 저장한 뒤 다시 넣어 주세요")
        return [page.extract_text() or "" for page in reader.pages]
    except UnsupportedFormat:
        raise
    except Exception as exc:  # pypdf의 읽기 오류 전부(깨진·잘린·PDF 아닌 파일)
        raise UnsupportedFormat(
            f"PDF를 읽을 수 없습니다(파일이 깨졌거나 PDF가 아닙니다: {type(exc).__name__}). "
            "공고 본문을 붙여넣어 주세요(본문을 붙여넣으면 바로 읽습니다)") from exc


def _as_path(src: "str | Path") -> Path | None:
    if isinstance(src, Path):
        return src
    if "\n" not in src and "\f" not in src and len(src) < 260 and Path(src).suffix.lower() in _TEXT_SUFFIXES:
        return Path(src)
    return None


def extract(path_or_text: "str | Path") -> Doc:
    path = _as_path(path_or_text)
    if path is None:
        return _build(str(path_or_text).split("\f"))
    suffix = path.suffix.lower()
    if suffix in (".hwp", ".hwpx"):
        raise UnsupportedFormat("HWP는 PDF로 저장해 주세요")
    if suffix in (".pdf", ".txt") and not path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    if suffix == ".pdf":
        return _build(_read_pdf(path))
    if suffix == ".txt":
        return _build(path.read_text(encoding="utf-8-sig").split("\f"))
    raise UnsupportedFormat(f"읽을 수 없는 형식입니다({suffix or '확장자 없음'}). PDF나 텍스트로 넣어 주세요")
