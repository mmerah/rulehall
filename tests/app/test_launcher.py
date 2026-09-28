import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue
from support.game import KEY
from support.table import (
    ENGINES_BUILT,
    LONER4E,
    NO_PACKS,
    NO_SHIPPED,
    POKEMON,
    REPOSITORY_ROOT,
    SCENARIOS,
    TUNNELGOONS,
    TWENTYFOURXX,
    ScriptedRoles,
    narrowed,
    offline_settings,
    updated,
)

from rulehall.app.catalog import LauncherCatalog, SavedGameKey, scenario_models
from rulehall.app.runtime import Runtime
from rulehall.config import Settings
from rulehall.core.game import ScenarioDescription
from rulehall.core.stores import ENCODING, Library, SaveStore
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner4e.engine import Loner4eEngine
from rulehall.engines.loner4e.world import Loner4eGame

MIRROR = EngineId("mirror")
_MIRRORED = Loner4eEngine(NO_PACKS)
_MIRRORED.id = MIRROR
# A second engine installed, so the engine the launcher pairs on is observable at all.
INSTALLED = {**ENGINES_BUILT, MIRROR: _MIRRORED}
KAEL_FOR_EACH = [
    ("kael", LONER4E),
    ("kael", TUNNELGOONS),
    ("kael", TWENTYFOURXX),
    ("kael", POKEMON),
]


def _catalog(settings: Settings, engines: Mapping[EngineId, AnyEngine]) -> LauncherCatalog:
    library = Library(settings.scenarios_dir, settings.characters_dir, NO_SHIPPED)
    return LauncherCatalog.read(
        library, SaveStore(settings.saves_dir), engines, scenario_models(engines)
    )


def _opening_state(settings: Settings) -> Loner4eGame:
    """The launcher reads saves, so a test needs a state a real game would have written."""
    runtime = Runtime(settings, roles=ScriptedRoles())
    return narrowed(runtime.session_for(KEY).state, Loner4eGame)


def _scenarios_copy(tmp_path: Path) -> Path:
    """Copy only the shipped scenario so generated local scenarios cannot affect counts."""
    scenarios = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS / "whispering-vault", scenarios / "whispering-vault")
    return scenarios


def _declaring(tmp_path: Path, engine_id: str) -> Path:
    scenarios = _scenarios_copy(tmp_path)
    world = scenarios / "whispering-vault" / "world.json"
    canon: dict[str, JsonValue] = json.loads(world.read_text(encoding=ENCODING))
    canon["engine_id"] = engine_id
    _ = world.write_text(json.dumps(canon), encoding=ENCODING)
    return scenarios


def _retitled(tmp_path: Path) -> Path:
    scenarios = _scenarios_copy(tmp_path)
    world = scenarios / "whispering-vault" / "world.json"
    canon: dict[str, JsonValue] = json.loads(world.read_text(encoding=ENCODING))
    description = canon["description"]
    assert isinstance(description, dict)
    canon["description"] = description | {"title": "The Vault, Renamed"}
    _ = world.write_text(json.dumps(canon), encoding=ENCODING)
    return scenarios


def test_the_catalog_pairs_a_scenario_with_a_character(tmp_path: Path) -> None:
    catalog = _catalog(offline_settings(tmp_path), ENGINES_BUILT)

    assert [entry.name for entry in catalog.scenarios_for(LONER4E)] == ["The Whispering Vault"]
    assert [(entry.id, entry.engine_id) for entry in catalog.characters] == KAEL_FOR_EACH


def test_a_character_is_offered_only_to_the_rules_it_is_written_for(tmp_path: Path) -> None:
    catalog = _catalog(offline_settings(tmp_path, _declaring(tmp_path, MIRROR)), INSTALLED)

    assert [entry.id for entry in catalog.characters_for(LONER4E)] == ["kael"]
    assert [entry.id for entry in catalog.scenarios_for(MIRROR)] == ["whispering-vault"]
    assert catalog.characters_for(MIRROR) == ()


def test_launcher_lists_and_resolves_an_existing_save(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path)
    SaveStore(tmp_path).write("whispering-vault--kael", _opening_state(settings))

    catalog = _catalog(settings, ENGINES_BUILT)
    (saved,) = catalog.saves

    assert (saved.scenario_label, saved.character_label, saved.turn) == (
        "The Whispering Vault",
        "Kael",
        0,
    )
    assert saved.key == KEY


def test_saves_are_listed_newest_first_and_grouped_by_rules(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path)
    runtime = Runtime(settings, roles=ScriptedRoles())
    keep = SavedGameKey(scenario_id="buried-keep", character_id="kael")
    store = SaveStore(tmp_path)
    for key, played_at in ((KEY, 1_000), (keep, 2_000)):
        store.write(key.save_id, runtime.session_for(key).state)
        os.utime(tmp_path / f"{key.save_id}.json", (played_at, played_at))
    scenes = store.media_dir(keep.save_id)
    (scenes / "icons").mkdir(parents=True)
    for name, drawn_at in (("icons/player.png", 3_000), ("old.jpg", 1_000), ("new.png", 2_000)):
        (scenes / name).write_bytes(b"")
        os.utime(scenes / name, (drawn_at, drawn_at))

    catalog = _catalog(settings, ENGINES_BUILT)

    assert [save.key for save in catalog.saves] == [keep, KEY]
    assert [save.key for save in catalog.saves_for(LONER4E)] == [KEY]
    assert catalog.find_save(keep) is not None
    assert [save.cover for save in catalog.saves] == [scenes / "new.png", None]


type BadSave = tuple[Settings, Mapping[EngineId, AnyEngine], str]


def _playing_another_engine(tmp_path: Path) -> BadSave:
    """The scenario and the character are both still there; only the rules disagree."""
    SaveStore(tmp_path).write(KEY.save_id, _opening_state(offline_settings(tmp_path)))
    return offline_settings(tmp_path, _declaring(tmp_path, MIRROR)), INSTALLED, KEY.save_id


def _filed_under_another_stem(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    SaveStore(tmp_path).write("old-game", _opening_state(settings))
    return settings, ENGINES_BUILT, "old-game"


def _playing_an_uninstalled_pack(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    SaveStore(tmp_path).write(KEY.save_id, updated(_opening_state(settings), pack_id="gone"))
    return settings, ENGINES_BUILT, KEY.save_id


def _whose_scenario_drifted(tmp_path: Path) -> BadSave:
    SaveStore(tmp_path).write(KEY.save_id, _opening_state(offline_settings(tmp_path)))
    return offline_settings(tmp_path, _retitled(tmp_path)), ENGINES_BUILT, KEY.save_id


def _that_will_not_restore(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    state = _opening_state(settings)
    SaveStore(tmp_path).write(KEY.save_id, state)
    broken = state.model_dump(mode="json")
    broken["world"]["cast"]["ghost"] = {"name": "Ghost"}
    _ = (tmp_path / "unopenable.json").write_text(json.dumps(broken), encoding=ENCODING)
    return settings, ENGINES_BUILT, "unopenable"


def _that_is_not_utf8(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    SaveStore(tmp_path).write(KEY.save_id, _opening_state(settings))
    _ = (tmp_path / "binary.json").write_bytes(b"\xff\xfe not text")
    return settings, ENGINES_BUILT, "binary"


@pytest.mark.parametrize(
    "write",
    [
        _playing_another_engine,
        _filed_under_another_stem,
        _playing_an_uninstalled_pack,
        _whose_scenario_drifted,
        _that_will_not_restore,
        _that_is_not_utf8,
    ],
    ids=(
        "another engine",
        "another stem",
        "an uninstalled pack",
        "a drifted scenario",
        "a state that will not restore",
        "bytes that are not text",
    ),
)
def test_a_save_the_launcher_cannot_resume_is_skipped_not_listed(
    tmp_path: Path, write: Callable[[Path], BadSave]
) -> None:
    """A stale save is invalid outright: the catalog skips it rather than listing it unopenable."""
    settings, engines, bad = write(tmp_path)

    catalog = _catalog(settings, engines)

    written = sorted(path.stem for path in tmp_path.glob("*.json"))
    assert [save.key.save_id for save in catalog.saves] == [stem for stem in written if stem != bad]
    assert bad in catalog.unresumable


SOURCE_MD = REPOSITORY_ROOT / "tests/core/fixtures/source/drowned-road.md"
_OPENING_ITEM: JsonValue = {
    "id": "bell-rope",
    "name": "the bell rope",
    "brief": "Frayed, and still wet.",
}
_OPENING: dict[str, JsonValue] = {
    "place_id": "sunken-bell",
    "location": "The drowned town",
    "title": "The Bell Under the Water",
    "situation": "The tide has taken the lower town and left the bell tower standing in it, "
    "and something down there still rings the hour.",
    "goal": "Cross the drowned town before the tide turns",
    "details": ["Black Floodwater", "A Leaning Tower"],
    "present_ids": ["hana"],
    "arc": "Farther down, the bell tower's keeper is still owed for the crossing, and has not "
    "yet been met.",
    "cast": {
        "hana": {
            "id": "hana",
            "name": "Hana",
            "brief": "A ferrywoman who knows the flooded streets.",
            "concept": "A ferrywoman",
        },
        "bell-rope": _OPENING_ITEM,
    },
}


async def test_a_written_opening_becomes_a_playable_scenario(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path, tmp_path / "scenarios")
    thin = json.dumps({**_OPENING, "present_ids": ["nobody-here"]})
    roles = ScriptedRoles(answers={"worldsmith": [thin, json.dumps(_OPENING)]})
    runtime = Runtime(settings, roles=roles)

    description = ScenarioDescription(
        title="The Sunken Bell",
        premise="The tide took the lower town.",
        backdrop="Plain.",
        scope="One crossing, before the tide turns.",
        art_style="woodcut",
    )
    scenario_id = await runtime.new_scenario(LONER4E, description, None, "srd", "kael")

    # The scene bar refuses the first answer, and the reason goes back with the re-prompt.
    assert "these name nobody" in roles.prompts[1][1]
    # The selected pack is the setting's vocabulary, so the worldsmith is given its tables.
    assert "Quiet Hands" in roles.prompt("worldsmith")
    catalog = _catalog(settings, runtime.engines)
    assert scenario_id in {entry.id for entry in catalog.scenarios_for(LONER4E)}
    state = runtime.session_for(SavedGameKey(scenario_id=scenario_id, character_id="kael")).state
    assert (scenario_id, len(state.log_entries())) == ("the-sunken-bell", 0)
    assert state.world.scene.title == "The Bell Under the Water"
    assert state.world.player.name == "Kael"
    assert state.source.startswith("PREMISE:")
    world = json.loads(
        (settings.scenarios_dir / scenario_id / "world.json").read_text(encoding=ENCODING)
    )
    assert world["description"]["art_style"] == "woodcut"


async def test_an_opening_the_rules_will_not_play_never_reaches_disk(tmp_path: Path) -> None:
    """A structurally broken cast entry fails to parse on both tries, so nothing reaches disk."""
    scenarios = tmp_path / "scenarios"
    cast: dict[str, JsonValue] = {
        "hana": {
            "id": "hana-imposter",
            "name": "Hana",
            "brief": "A ferrywoman.",
        }
    }
    broken = json.dumps(_OPENING | {"cast": {**cast, "bell-rope": _OPENING_ITEM}})
    roles = ScriptedRoles(answers={"worldsmith": [broken, broken]})
    runtime = Runtime(offline_settings(tmp_path, scenarios), roles=roles)

    with pytest.raises(Refusal, match="the worldsmith answered nothing usable"):
        _ = await runtime.new_scenario(
            LONER4E,
            ScenarioDescription(
                title="The Sunken Bell",
                premise="The tide.",
                backdrop="Plain.",
                scope="One crossing.",
            ),
            None,
            "srd",
            "kael",
        )

    assert not scenarios.exists()


async def test_a_scenario_for_unknown_rules_is_refused(tmp_path: Path) -> None:
    runtime = Runtime(offline_settings(tmp_path), roles=ScriptedRoles())
    description = ScenarioDescription(
        title="Nowhere", premise="Nothing.", backdrop="Plain.", scope="Brief."
    )

    with pytest.raises(Refusal, match="no rules 'nowhere'"):
        _ = await runtime.new_scenario(EngineId("nowhere"), description, None, "srd", "kael")


async def test_a_scenario_written_from_a_document_carries_its_text(tmp_path: Path) -> None:
    scenarios = tmp_path / "scenarios"
    roles = ScriptedRoles(answers={"worldsmith": [json.dumps(_OPENING)]})
    runtime = Runtime(offline_settings(tmp_path, scenarios), roles=roles)

    scenario_id = await runtime.new_scenario(
        LONER4E,
        ScenarioDescription(
            title="The Sunken Bell", premise="", backdrop="Plain.", scope="One crossing."
        ),
        SOURCE_MD,
        "srd",
        "kael",
    )

    state = runtime.session_for(SavedGameKey(scenario_id=scenario_id, character_id="kael")).state
    assert state.source.startswith("SOURCE DOCUMENT:")
    # The premise the player never wrote is the scene's own words.
    assert state.scenario_description.premise == _OPENING["situation"]
