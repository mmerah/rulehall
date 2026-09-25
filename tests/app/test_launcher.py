import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue
from support.game import TARGET
from support.table import (
    ENGINES_BUILT,
    LONER3E,
    NO_PACKS,
    NO_SHIPPED,
    POKEMON,
    REPOSITORY_ROOT,
    SCENARIOS,
    TUNNELGOONS,
    TWENTYFOURXX,
    ScriptedSpawner,
    narrowed,
    offline_settings,
    updated,
)

from rulehall.app.launch import LauncherCatalog
from rulehall.app.runtime import Runtime
from rulehall.config import Settings
from rulehall.core.io import ENCODING, FileStore, Library
from rulehall.core.model import ScenarioMeta
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner3e.engine import Loner3eEngine
from rulehall.engines.loner3e.world import Loner3eGame

MIRROR = EngineId("mirror")
_MIRRORED = Loner3eEngine(NO_PACKS)
_MIRRORED.id = MIRROR
# A second engine installed, so the engine the launcher pairs on is observable at all.
INSTALLED = {**ENGINES_BUILT, MIRROR: _MIRRORED}
KAEL_FOR_EACH = [
    ("kael", LONER3E),
    ("kael", TUNNELGOONS),
    ("kael", TWENTYFOURXX),
    ("kael", POKEMON),
]


def _catalog(settings: Settings, engines: Mapping[EngineId, AnyEngine]) -> LauncherCatalog:
    library = Library(settings.scenarios_dir, settings.characters_dir, NO_SHIPPED)
    return LauncherCatalog.read(library, FileStore(settings.saves_dir), engines)


def _opening_state(settings: Settings) -> Loner3eGame:
    """The launcher reads saves, so a test needs a state a real game would have written."""
    runtime = Runtime(settings, spawner=ScriptedSpawner())
    return narrowed(runtime.session(TARGET).state, Loner3eGame)


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
    meta = canon["meta"]
    assert isinstance(meta, dict)
    canon["meta"] = meta | {"title": "The Vault, Renamed"}
    _ = world.write_text(json.dumps(canon), encoding=ENCODING)
    return scenarios


def test_the_catalog_pairs_a_scenario_with_a_character(tmp_path: Path) -> None:
    catalog = _catalog(offline_settings(tmp_path), ENGINES_BUILT)

    assert catalog.scenario("whispering-vault").name == "The Whispering Vault"
    assert [(entry.id, entry.engine_id) for entry in catalog.characters] == KAEL_FOR_EACH
    assert catalog.target("whispering-vault", "kael") == TARGET


def test_a_character_is_offered_only_to_the_rules_it_is_written_for(tmp_path: Path) -> None:
    catalog = _catalog(offline_settings(tmp_path, _declaring(tmp_path, MIRROR)), INSTALLED)

    assert [entry.id for entry in catalog.characters_for(LONER3E)] == ["kael"]
    assert catalog.characters_for(MIRROR) == ()
    with pytest.raises(Refusal, match="no character 'kael' is written for the 'mirror' rules"):
        _ = catalog.target("whispering-vault", "kael")


def test_launcher_lists_and_resolves_an_existing_save(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path)
    FileStore(tmp_path).write("whispering-vault--kael", _opening_state(settings))

    catalog = _catalog(settings, ENGINES_BUILT)
    (saved,) = catalog.saves

    assert (saved.scenario_label, saved.character_label, saved.turn, saved.rules) == (
        "The Whispering Vault",
        "Kael",
        0,
        "LONER 3E",
    )
    assert catalog.scenario("whispering-vault").rules == "LONER 3E"
    assert saved.target == TARGET


type BadSave = tuple[Settings, Mapping[EngineId, AnyEngine], str]


def _playing_another_engine(tmp_path: Path) -> BadSave:
    """The scenario and the character are both still there; only the rules disagree."""
    FileStore(tmp_path).write(TARGET.slug, _opening_state(offline_settings(tmp_path)))
    return offline_settings(tmp_path, _declaring(tmp_path, MIRROR)), INSTALLED, TARGET.slug


def _filed_under_another_stem(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    FileStore(tmp_path).write("old-game", _opening_state(settings))
    return settings, ENGINES_BUILT, "old-game"


def _playing_an_uninstalled_pack(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    FileStore(tmp_path).write(TARGET.slug, updated(_opening_state(settings), pack_id="gone"))
    return settings, ENGINES_BUILT, TARGET.slug


def _whose_scenario_drifted(tmp_path: Path) -> BadSave:
    FileStore(tmp_path).write(TARGET.slug, _opening_state(offline_settings(tmp_path)))
    return offline_settings(tmp_path, _retitled(tmp_path)), ENGINES_BUILT, TARGET.slug


def _that_will_not_restore(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    state = _opening_state(settings)
    FileStore(tmp_path).write(TARGET.slug, state)
    broken = state.model_dump(mode="json")
    broken["world"]["cast"]["ghost"] = {"name": "Ghost"}
    _ = (tmp_path / "unopenable.json").write_text(json.dumps(broken), encoding=ENCODING)
    return settings, ENGINES_BUILT, "unopenable"


def _that_is_not_utf8(tmp_path: Path) -> BadSave:
    settings = offline_settings(tmp_path)
    FileStore(tmp_path).write(TARGET.slug, _opening_state(settings))
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
    assert [save.target.slug for save in catalog.saves] == [stem for stem in written if stem != bad]
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
    "present": ["hana"],
    "hidden": ["bell-rope"],
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
    thin = json.dumps({**_OPENING, "present": ["nobody-here"]})
    spawner = ScriptedSpawner(answers={"worldsmith": [thin, json.dumps(_OPENING)]})
    runtime = Runtime(settings, spawner=spawner)

    meta = ScenarioMeta(
        title="The Sunken Bell",
        premise="The tide took the lower town.",
        backdrop="Plain.",
        scope="One crossing, before the tide turns.",
        art_style="woodcut",
    )
    name = await runtime.new_scenario(LONER3E, meta, None, "srd", "kael")

    # The scene bar refuses the first answer, and the reason goes back with the re-prompt.
    assert "these name nobody" in spawner.prompts[1][1]
    # The selected pack is the setting's vocabulary, so the worldsmith is given its tables.
    assert "Quiet Hands" in spawner.prompt("worldsmith")
    catalog = _catalog(settings, runtime.engines)
    state = runtime.session(catalog.target(name, "kael")).state
    assert (name, len(state.exchanges())) == ("the-sunken-bell", 0)
    assert state.world.scene.title == "The Bell Under the Water"
    assert state.world.player.name == "Kael"
    assert state.source.startswith("PREMISE:")
    world = json.loads((settings.scenarios_dir / name / "world.json").read_text(encoding=ENCODING))
    assert world["meta"]["art_style"] == "woodcut"


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
    spawner = ScriptedSpawner(answers={"worldsmith": [broken, broken]})
    runtime = Runtime(offline_settings(tmp_path, scenarios), spawner=spawner)

    with pytest.raises(Refusal, match="the worldsmith answered nothing usable"):
        _ = await runtime.new_scenario(
            LONER3E,
            ScenarioMeta(
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
    runtime = Runtime(offline_settings(tmp_path), spawner=ScriptedSpawner())
    meta = ScenarioMeta(title="Nowhere", premise="Nothing.", backdrop="Plain.", scope="Brief.")

    with pytest.raises(Refusal, match="no rules 'nowhere'"):
        _ = await runtime.new_scenario(EngineId("nowhere"), meta, None, "srd", "kael")


async def test_a_scenario_written_from_a_document_carries_its_text(tmp_path: Path) -> None:
    scenarios = tmp_path / "scenarios"
    spawner = ScriptedSpawner(answers={"worldsmith": [json.dumps(_OPENING)]})
    runtime = Runtime(offline_settings(tmp_path, scenarios), spawner=spawner)

    name = await runtime.new_scenario(
        LONER3E,
        ScenarioMeta(title="The Sunken Bell", premise="", backdrop="Plain.", scope="One crossing."),
        SOURCE_MD,
        "srd",
        "kael",
    )

    catalog = _catalog(runtime.settings, runtime.engines)
    state = runtime.session(catalog.target(name, "kael")).state
    assert state.source.startswith("SOURCE DOCUMENT:")
    # The premise the player never wrote is the scene's own words.
    assert state.scenario.premise == _OPENING["situation"]
