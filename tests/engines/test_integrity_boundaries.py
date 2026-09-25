import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.game import character, initialized, loner_sheet, scenario
from support.table import ENGINES_BUILT, LONER3E, NO_SHIPPED, SCENARIO_MODELS, SCENARIOS, updated

from rulehall.core.io import Library
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner3e.rules import LUCK_MAX
from rulehall.engines.loner3e.world import Loner3eGame, Loner3eWorld

MARA = "mara"
OTHER = EngineId("ruleless")


def test_a_doubled_id_in_a_world_file_is_refused(tmp_path: Path) -> None:
    world = (SCENARIOS / "whispering-vault" / "world.json").read_text(encoding="utf-8")
    doubled = world.replace('"mara": {', '"mara": {}, "mara": {', 1)
    (tmp_path / "doubled").mkdir()
    _ = (tmp_path / "doubled" / "world.json").write_text(doubled, encoding="utf-8")
    with pytest.raises(Refusal, match="duplicate keys"):
        _ = Library(tmp_path, tmp_path, NO_SHIPPED).read_scenario("doubled", SCENARIO_MODELS)


def test_a_doubled_key_in_a_save_is_refused() -> None:
    engine, state = initialized()
    doubled = state.model_dump_json().replace('{"scenario_id"', '{"notes": [], "scenario_id"', 1)
    with pytest.raises(Refusal, match="duplicate keys"):
        _ = engine.restore(doubled)


def test_a_doubled_key_in_a_character_file_is_refused(tmp_path: Path) -> None:
    filed = character()
    folder = tmp_path / filed.id
    folder.mkdir()
    doubled = filed.model_dump_json().replace('{"id"', '{"engine_id": "other", "id"', 1)
    _ = (folder / f"{filed.engine_id}.json").write_text(doubled, encoding="utf-8")
    with pytest.raises(Refusal, match="duplicate keys"):
        _ = Library(tmp_path, tmp_path, NO_SHIPPED).read_character(
            filed.id, filed.engine_id, ENGINES_BUILT[LONER3E].character
        )


def test_the_scene_world_rejects_state_it_cannot_stand_on() -> None:
    _, state = initialized()
    world = state.world

    with pytest.raises(ValidationError, match="filed under"):
        _ = updated(world, cast={"someone-else": world.player.model_dump(round_trip=True)})

    with pytest.raises(ValidationError, match="unknown to themselves"):
        _ = updated(world, player=world.player.model_copy(update={"known": False}))

    with pytest.raises(ValidationError, match="scene names"):
        _ = _with_scene(world, here=["ghost"])


def _with_scene(world: Loner3eWorld, **changes: object) -> Loner3eWorld:
    return updated(world, scenes=[world.scene.model_dump(round_trip=True) | changes])


def test_the_party_rules_refuse_the_dead_and_the_doubled() -> None:
    _, state = initialized()
    dead = state.draft()
    dead.world.require(MARA).alive = False
    dead.world.party.append(MARA)
    with pytest.raises(Refusal, match="cannot travel with the player"):
        _ = dead.commit()

    twice = state.draft()
    twice.world.party.extend((MARA, MARA))
    with pytest.raises(Refusal, match="duplicate party"):
        _ = twice.commit()


def test_an_unknown_party_id_is_refused_by_the_base_validator() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.party.append("ghost")
    with pytest.raises(Refusal, match="travels with the player but is not known"):
        _ = draft.commit()


def test_a_committed_game_refuses_a_player_who_travels_with_themselves() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.party.append(draft.world.player.id)
    with pytest.raises(Refusal, match="cannot travel with themselves"):
        _ = draft.commit()


def test_entity_and_scene_ids_use_one_grammar() -> None:
    _, state = initialized()
    with pytest.raises(ValidationError, match="pattern"):
        _ = updated(state.world.require(MARA), id="bell_tower")
    with pytest.raises(ValidationError, match="pattern"):
        _ = updated(state.world.scene, here=["study_1"])


def test_a_game_is_refused_a_scenario_or_a_character_from_another_engine() -> None:
    engine = ENGINES_BUILT[LONER3E]
    with pytest.raises(Refusal, match="authored for the 'ruleless' rules"):
        _ = engine.begin("whispering-vault", updated(scenario(), engine_id=OTHER), character())
    with pytest.raises(Refusal, match="written for the 'ruleless' rules"):
        _ = engine.begin("whispering-vault", scenario(), updated(character(), engine_id=OTHER))


def test_a_character_file_belongs_to_its_folder_and_its_engine(tmp_path: Path) -> None:
    text = character().model_dump_json()
    foreign = json.dumps(json.loads(text) | {"engine_id": OTHER})
    (tmp_path / "kael").mkdir()
    _ = (tmp_path / "kael" / f"{LONER3E}.json").write_text(foreign, encoding="utf-8")
    (tmp_path / "mira").mkdir()
    _ = (tmp_path / "mira" / f"{LONER3E}.json").write_text(text, encoding="utf-8")

    library, engine = Library(tmp_path, tmp_path, NO_SHIPPED), ENGINES_BUILT[LONER3E]
    with pytest.raises(Refusal, match="plays 'ruleless', not 'loner3e'"):
        _ = library.read_character("kael", engine.id, engine.character)
    with pytest.raises(Refusal, match="'kael' is filed under 'mira'"):
        _ = library.read_character("mira", engine.id, engine.character)


def _luck(state: Loner3eGame) -> int:
    return loner_sheet(state, PLAYER_ID).luck.current


def test_a_rules_mutation_lands_on_the_commit_and_nowhere_else() -> None:
    _, state = initialized()
    draft = state.draft()
    loner_sheet(draft, PLAYER_ID).luck.current = 1

    committed = draft.commit()

    assert _luck(committed) == 1
    assert _luck(state) == LUCK_MAX


def test_a_save_whose_world_the_engine_rejects_is_refused() -> None:
    engine, state = initialized()
    raw = state.model_dump(mode="json")
    raw["world"]["cast"]["ghost"] = {"name": "Ghost"}
    with pytest.raises(Refusal):
        _ = engine.restore(json.dumps(raw))


def test_a_save_naming_a_pack_no_longer_installed_is_refused() -> None:
    engine, state = initialized()
    raw = state.model_dump(mode="json")
    raw["pack_id"] = "gone"
    with pytest.raises(Refusal, match="is not installed"):
        _ = engine.restore(json.dumps(raw))


def test_a_save_from_other_rules_is_refused_before_it_is_read() -> None:
    engine, state = initialized()
    foreign = json.dumps(state.model_dump(mode="json") | {"engine_id": OTHER})
    with pytest.raises(Refusal, match="the save plays 'ruleless', not 'loner3e'"):
        _ = engine.restore(foreign)
