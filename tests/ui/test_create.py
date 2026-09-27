from collections.abc import Callable
from pathlib import Path

from nicegui import Client, ui
from nicegui.events import ValueChangeEventArguments
from support.table import ENGINES_BUILT, LONER4E, ScriptedSpawner, offline_settings

from rulehall.app.launch import CatalogEntry, LauncherCatalog
from rulehall.app.runtime import Runtime
from rulehall.engines.packs import SRD_PACK
from rulehall.ui.create import CharacterForm, ScenarioForm

FANTASY = "ap01-fantasy"
FANTASY_SKILL = "swordsmanship"  # ap01's alone: the SRD's tables never offer it


def test_rolling_a_seed_writes_one_of_the_chosen_packs_seeds(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    entry = CatalogEntry(
        id="kael",
        engine_id=LONER4E,
        name="Kael",
        brief="a wanderer",
        rules="LONER 4E",
        look=ENGINES_BUILT[LONER4E].look,
    )
    catalog = LauncherCatalog(scenarios=(), characters=(entry,), packs=(), saves=(), unresumable=())
    runtime = Runtime(offline_settings(tmp_path), spawner=ScriptedSpawner())
    form = ScenarioForm(runtime, catalog)
    page()
    form.build()
    form.pack_id = FANTASY

    form.roll_seed()

    assert form.premise.value in ENGINES_BUILT[LONER4E].packs.installed[FANTASY].seeds


# Async: a refreshable's `refresh()` schedules a NiceGUI background task on the running loop.
async def test_a_trait_no_pack_offers_is_kept_as_the_players_own_through_a_pack_change(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    runtime = Runtime(offline_settings(tmp_path), spawner=ScriptedSpawner())
    form = CharacterForm(runtime)
    client = page()
    form.build()
    form.picks["skill-1"] = FANTASY_SKILL
    form.answered()
    assert form.picks["skill-1"] == FANTASY_SKILL

    form.picks["skill-1"] = FANTASY_SKILL
    form.choose_pack(
        ValueChangeEventArguments(
            sender=ui.label(), client=client, value=FANTASY, previous_value=SRD_PACK
        )
    )

    assert form.pack_id == FANTASY
    assert form.picks["skill-1"] == FANTASY_SKILL
