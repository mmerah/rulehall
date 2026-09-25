from collections.abc import Callable
from pathlib import Path

from nicegui import Client, ui
from nicegui.events import ValueChangeEventArguments
from support.table import ENGINES_BUILT, LONER3E, ScriptedSpawner, offline_settings

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
        engine_id=LONER3E,
        name="Kael",
        brief="a wanderer",
        rules="LONER 3E",
        look=ENGINES_BUILT[LONER3E].look,
    )
    catalog = LauncherCatalog(scenarios=(), characters=(entry,), packs=(), saves=(), unresumable=())
    runtime = Runtime(offline_settings(tmp_path), spawner=ScriptedSpawner())
    form = ScenarioForm(runtime, catalog)
    page()
    form.build()
    form.pack_id = FANTASY

    form.roll_seed()

    assert form.premise.value in ENGINES_BUILT[LONER3E].packs.installed[FANTASY].seeds


# Async: a refreshable's `refresh()` schedules a NiceGUI background task on the running loop.
async def test_choosing_a_pack_refreshes_the_steps_with_what_that_pack_offers(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    runtime = Runtime(offline_settings(tmp_path), spawner=ScriptedSpawner())
    form = CharacterForm(runtime)
    client = page()
    form.build()
    form.picks["skill-1"] = FANTASY_SKILL
    form.answered()
    assert "skill-1" not in form.picks

    form.picks["skill-1"] = FANTASY_SKILL
    form.choose_pack(
        ValueChangeEventArguments(
            sender=ui.label(), client=client, value=FANTASY, previous_value=SRD_PACK
        )
    )

    assert form.pack_id == FANTASY
    assert form.picks["skill-1"] == FANTASY_SKILL
