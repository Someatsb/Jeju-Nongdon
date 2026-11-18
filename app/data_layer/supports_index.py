"""지원 표의 제도 행 묶음(Task 18 대역을 Task 28에서 load_tables로 바꿈).

load_tables가 검사하고 형 변환한 programs를 .programs로 노출한다(TableBundle과 같은 이름).
as_of는 superseded 판단에만 쓰이며 식별에는 영향이 없어, 모르면 시연 기준일을 쓴다(여기서 시계를 읽지 않는다).
"""
from datetime import date
from pathlib import Path

from app.core.models import CoreModel, Program
from app.data_layer.tables import load_tables

DEFAULT_AS_OF = date(2026, 11, 13)


class ProgramIndex(CoreModel):
    programs: tuple[Program, ...]


def load_program_index(tables_dir: Path, as_of: date | None = None) -> ProgramIndex:
    return ProgramIndex(programs=load_tables(Path(tables_dir), as_of or DEFAULT_AS_OF).programs)
