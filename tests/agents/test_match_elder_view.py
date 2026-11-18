"""어르신 화면용 묶음(elder_view) 시험. 순수 함수라 AI 도 시계도 필요 없다."""
from app.agents.match import ElderMatchView, MatchItem, MatchReport, elder_view


def item(key: str, verdict: str) -> MatchItem:
    return MatchItem(key=key, name=f"공고 {key}", verdict=verdict, why="왜", period="기간")


def report(*pairs: tuple[str, str], note: str = "메모") -> MatchReport:
    return MatchReport(items=tuple(item(k, v) for k, v in pairs), source="ai", candidates=len(pairs), note=note)


def test_mixed_verdicts_split_into_lines_more_names_and_hidden():
    rep = report(("a", "맞을 수 있음"), ("b", "알 수 없음"), ("c", "안 맞음"), ("d", "맞을 수 있음"), ("e", "알 수 없음"))
    view = elder_view(rep)
    assert isinstance(view, ElderMatchView)
    assert [i.key for i in view.lines] == ["a", "d"]
    assert view.more_names == ("공고 b", "공고 e")
    assert [i.key for i in view.hidden] == ["c"]
    assert view.note == "메모"


def test_fourth_fit_goes_to_more_names_in_original_order():
    rep = report(("a", "맞을 수 있음"), ("b", "알 수 없음"), ("c", "맞을 수 있음"), ("d", "맞을 수 있음"), ("e", "맞을 수 있음"), ("f", "알 수 없음"))
    view = elder_view(rep)
    assert [i.key for i in view.lines] == ["a", "c", "d"]
    assert view.more_names == ("공고 b", "공고 e", "공고 f")
    assert view.hidden == ()
    assert [i.key for i in elder_view(rep, max_lines=1).lines] == ["a"]


def test_empty_or_failed_report_gives_empty_view():
    assert elder_view(MatchReport(source="skipped", note="없어요")) == ElderMatchView(note="없어요")
    failed = MatchReport(source="none", note="시간 초과", candidates=3)
    view = elder_view(failed)
    assert view.lines == () and view.more_names == () and view.hidden == () and view.note == "시간 초과"
    ai_empty = MatchReport(source="ai", items=())
    assert elder_view(ai_empty).lines == ()
