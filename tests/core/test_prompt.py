from rulehall.core.log import Chapter, LogEntry, SpokenLine
from rulehall.core.prompt import TAIL_EXCHANGES, render_log


def _told(words: str) -> LogEntry:
    return LogEntry(words=words, lines=(SpokenLine(text=f"{words} happens."),))


def test_render_log_prints_an_older_scenes_recap_and_not_its_exchanges() -> None:
    older = Chapter(
        title="The Drowned Hall",
        recap="You found the drowned hall and left it behind.",
        entries=[_told("dropped")],
    )
    scenes = [older, Chapter(title="A1"), Chapter(title="A2")]

    history = render_log(scenes)

    assert "what happened: You found the drowned hall and left it behind." in history
    assert "dropped" not in history


def test_render_log_shows_an_older_scenes_last_tail_exchanges_only() -> None:
    words_list = [f"p{number}" for number in range(TAIL_EXCHANGES + 2)]
    older = Chapter(title="Hub", entries=[_told(w) for w in words_list])
    scenes = [older, Chapter(title="A1"), Chapter(title="A2")]

    history = render_log(scenes)

    for kept in words_list[-TAIL_EXCHANGES:]:
        assert f"> {kept}" in history
    for dropped in words_list[:-TAIL_EXCHANGES]:
        assert f"> {dropped}\n" not in history


def test_render_log_marks_only_the_context_lines_an_exchange_changed() -> None:
    def at(words: str, context: str) -> LogEntry:
        return _told(words).model_copy(update={"context": context})

    scene = Chapter(
        title="Hall",
        context="place: Hall\njob: none",
        entries=[at("look", "place: Hall\njob: none"), at("go", "place: Crypt\njob: none")],
    )

    history = render_log([scene])

    assert history.count("→") == 1
    assert "go happens.\n→ place: Crypt" in history
