from rulehall.core.play import Chapter, Exchange, SpokenLine
from rulehall.core.prompt import TAIL_EXCHANGES, render_history


def _told(words: str) -> Exchange:
    return Exchange(words=words, lines=(SpokenLine(text=f"{words} happens."),))


def test_render_history_prints_an_older_scenes_recap_and_not_its_exchanges() -> None:
    older = Chapter(
        title="The Drowned Hall",
        recap="You found the drowned hall and left it behind.",
        exchanges=[_told("dropped")],
    )
    scenes = [older, Chapter(title="A1"), Chapter(title="A2")]

    history = render_history(scenes)

    assert "what happened: You found the drowned hall and left it behind." in history
    assert "dropped" not in history


def test_render_history_shows_an_older_scenes_last_tail_exchanges_only() -> None:
    words_list = [f"p{number}" for number in range(TAIL_EXCHANGES + 2)]
    older = Chapter(title="Hub", exchanges=[_told(w) for w in words_list])
    scenes = [older, Chapter(title="A1"), Chapter(title="A2")]

    history = render_history(scenes)

    for kept in words_list[-TAIL_EXCHANGES:]:
        assert f"> {kept}" in history
    for dropped in words_list[:-TAIL_EXCHANGES]:
        assert f"> {dropped}\n" not in history


def test_render_history_marks_only_the_context_lines_an_exchange_changed() -> None:
    def at(words: str, context: str) -> Exchange:
        return _told(words).model_copy(update={"context": context})

    scene = Chapter(
        title="Hall",
        context="place: Hall\njob: none",
        exchanges=[at("look", "place: Hall\njob: none"), at("go", "place: Crypt\njob: none")],
    )

    history = render_history([scene])

    assert history.count("→") == 1
    assert "go happens.\n→ place: Crypt" in history
