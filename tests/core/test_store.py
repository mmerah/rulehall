from pathlib import Path

import pytest
from support.game import character, initialized, scenario
from support.table import ENGINES_BUILT, LONER3E, NO_SHIPPED, SCENARIO_MODELS, updated

from rulehall.core.facts import Fact
from rulehall.core.io import ENCODING, FileStore, Library, partial_lines, publish, write_text
from rulehall.core.play import Exchange, Line
from rulehall.core.validation import EngineId, Refusal

MIRROR = EngineId("mirror")


def test_a_saved_games_history_round_trips(tmp_path: Path) -> None:
    engine, state = initialized()
    draft = state.draft()
    draft.log[-1].exchanges = [
        Exchange(
            words="I take the map.",
            lines=(),
            facts=(
                Fact(
                    trace="the vault map moved to Kael",
                    told=True,
                    card="Took the vault map",
                ),
            ),
        ),
    ]
    saved = draft.commit()
    store = FileStore(tmp_path)

    store.write("roundtrip", saved)
    reloaded = store.read("roundtrip")

    assert reloaded is not None
    assert engine.restore(reloaded).exchanges() == saved.exchanges()


@pytest.mark.parametrize("slug", ("../escape", "/absolute", "bad slug", ""))
def test_storage_rejects_unsafe_slugs(tmp_path: Path, slug: str) -> None:
    store = FileStore(tmp_path)

    with pytest.raises(ValueError, match="invalid storage slug"):
        store.read(slug)


def test_content_paths_reject_an_unsafe_id(tmp_path: Path) -> None:
    engine = ENGINES_BUILT[LONER3E]
    library = Library(tmp_path, tmp_path, NO_SHIPPED)
    with pytest.raises(Refusal, match="invalid content id"):
        library.read_scenario("../escape", SCENARIO_MODELS)
    with pytest.raises(Refusal, match="invalid content id"):
        library.read_character("kael/../..", engine.id, engine.character)


def test_write_scenario_round_trips_and_refuses_a_duplicate(tmp_path: Path) -> None:
    original = scenario()
    library = Library(tmp_path, tmp_path, NO_SHIPPED)

    library.write_scenario("vault-copy", original)
    loaded = library.read_scenario("vault-copy", SCENARIO_MODELS)

    assert loaded == original
    with pytest.raises(Refusal, match="already exists"):
        library.write_scenario("vault-copy", original)


def _beside_a_broken_world(directory: Path, world: bytes) -> Library:
    library = Library(directory, directory, NO_SHIPPED)
    library.write_scenario("good", scenario())
    (directory / "broken").mkdir()
    (directory / "broken" / "world.json").write_bytes(world)
    return library


def test_read_scenarios_skips_a_world_that_fails_to_validate(tmp_path: Path) -> None:
    library = _beside_a_broken_world(tmp_path, b'{"meta": {}}')

    assert [slug for slug, _ in library.read_scenarios(SCENARIO_MODELS)] == ["good"]


def test_shipped_content_is_read_only_and_wins_an_id_over_player_content(tmp_path: Path) -> None:
    engine = ENGINES_BUILT[LONER3E]
    shipped = Library(tmp_path / "scenarios", tmp_path / "characters", NO_SHIPPED)
    shipped.write_scenario("vault", scenario())
    shipped.write_character(character())
    player = tmp_path / "user"
    unshipped = Library(player, player, NO_SHIPPED)
    unshipped.write_scenario("vault", updated(scenario(), meta=updated(scenario().meta, title="X")))
    unshipped.write_character(updated(character(), sheet=updated(character().sheet, name="Mira")))
    library = Library(player, player, tmp_path)

    library.write_scenario("mine", scenario())

    assert (player / "mine" / "world.json").is_file()
    assert [slug for slug, _ in library.read_scenarios(SCENARIO_MODELS)] == ["mine", "vault"]
    assert library.read_scenario("vault", SCENARIO_MODELS) == scenario()
    assert library.read_character("kael", engine.id, engine.character).sheet.name == "Kael"
    with pytest.raises(Refusal, match="already exists"):
        library.write_scenario("vault", scenario())
    with pytest.raises(Refusal, match="ships with the game"):
        library.write_character(character())


def test_a_character_written_for_a_second_engine_must_keep_its_name(tmp_path: Path) -> None:
    engine = ENGINES_BUILT[LONER3E]
    filed = character()
    library = Library(tmp_path, tmp_path, NO_SHIPPED)
    library.write_character(filed)

    renamed = updated(filed, engine_id=MIRROR, sheet=updated(filed.sheet, name="Mira"))
    with pytest.raises(Refusal, match="is 'Kael', not 'Mira'"):
        library.write_character(renamed)

    library.write_character(updated(filed, engine_id=MIRROR))
    assert library.read_character("kael", engine.id, engine.character).sheet.name == "Kael"


def test_a_save_that_cannot_be_written_refuses_without_leaking_the_path(tmp_path: Path) -> None:
    blocking = tmp_path / "saves"
    blocking.write_text("", encoding=ENCODING)

    with pytest.raises(Refusal, match="cannot be written") as raised:
        write_text(blocking / "game.json", "{}")

    assert str(tmp_path) not in str(raised.value)


def test_a_write_that_fails_midway_leaves_the_old_file_and_no_staged_file(tmp_path: Path) -> None:
    path = tmp_path / "game.json"
    path.write_text("old", encoding=ENCODING)

    def _broken(staged: Path) -> None:
        staged.write_text("partial", encoding=ENCODING)
        raise OSError("disk full")

    with pytest.raises(Refusal, match="cannot be written"):
        publish(path, _broken)

    assert path.read_text(encoding=ENCODING) == "old"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("raw", "lines"),
    (
        ('```json\n{"lines":[{"speaker_id":null,"text":"The ro', (Line(text="The ro"),)),
        ('{"lines":[{"speaker_id":null,"text":"A"},{"speaker_id":"gu', (Line(text="A"),)),
        ('{"lines":[{"speaker_id":null,"text":""},{"speaker_id":null,"text":"B"}]}', ()),
        ("Sure, here it is:", ()),
    ),
    ids=("unfinished line", "unfinished speaker", "invalid line", "no object yet"),
)
def test_partial_lines_keeps_only_the_lines_finished_enough_to_show(
    raw: str, lines: tuple[Line, ...]
) -> None:
    assert partial_lines(raw) == lines
