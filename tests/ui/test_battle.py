from asyncio import Task, gather, get_running_loop
from collections.abc import Callable
from pathlib import Path
from random import Random
from typing import cast

from nicegui import Client, background_tasks, ui
from support.showdown import ScriptedSimulator, started
from support.table import POKEMON, narrated, open_table, play_turn, tool_call

from rulehall.engines.engine import AnyEngine
from rulehall.engines.pokemon.world import PokemonGame
from rulehall.ui.battle import BattlePanel
from rulehall.ui.widgets import Sounds

NO_BLOCK_LEFT = "the scripted simulator has no block left"


async def test_a_refused_command_keeps_the_battle_screen_and_only_a_refused_opening_leaves_it(
    tmp_path: Path, page: Callable[[], Client], notified: list[str]
) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame, rng=Random(1))
    _ = await play_turn(
        table,
        "I walk into the tall grass.",
        tool_call("start_wild_battle", species_id="pidgey"),
        tool_call("direct", text="A wild Pidgey flies at the player."),
        narration="A wild Pidgey bursts out of the grass.",
        then=(narrated("You slip away from the Pidgey."),),
    )
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup))

    async def start(_engine: AnyEngine) -> ScriptedSimulator:
        return simulator

    table.service.start_transport = start
    page()
    panel = BattlePanel(table.service, Sounds(), lambda: None)
    panel.build_banner()
    panel.build(ui.element("div"))

    panel.show()
    await _synced(panel)
    assert table.service.battle_run is not None

    await panel._choose("leave")  # pyright: ignore[reportPrivateUsage]
    assert notified == [NO_BLOCK_LEFT]
    await _synced(panel)
    assert panel.column.visible

    assert notified == [NO_BLOCK_LEFT, NO_BLOCK_LEFT]
    await _synced(panel)
    assert not panel.column.visible
    assert panel.banner.visible


async def _synced(panel: BattlePanel) -> None:
    panel.sync(live=True)
    loop, tasks = get_running_loop(), cast(set[Task[object]], background_tasks.running_tasks)
    await gather(*(task for task in tasks.copy() if task.get_loop() is loop))
