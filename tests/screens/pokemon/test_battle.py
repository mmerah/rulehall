from asyncio import Task, gather, get_running_loop
from collections.abc import Callable
from pathlib import Path
from typing import cast

from nicegui import Client, background_tasks
from support.journey import into_wild_battle
from support.showdown import ScriptedSimulator, started

from rulehall.app.game_session import SessionSnapshot
from rulehall.engines.battles import BattleSupport
from rulehall.screens.pokemon.battle import BattleScreen
from rulehall.ui.screen_host import ScreenHost
from rulehall.ui.widgets import Sounds

NO_BLOCK_LEFT = "the scripted simulator has no block left"


async def test_a_refused_command_keeps_the_battle_screen_and_only_a_refused_opening_leaves_it(
    tmp_path: Path, page: Callable[[], Client], notified: list[str]
) -> None:
    table = await into_wild_battle(tmp_path, "You slip away from the Pidgey.")
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup))

    async def start(_battles: BattleSupport) -> ScriptedSimulator:
        return simulator

    table.session.start_transport = start
    page()
    panel = BattleScreen(ScreenHost(session=table.session, sounds=Sounds(), on_toggle=lambda: None))
    panel.build_banner()
    drawn = table.session.snapshot()
    panel.build(drawn)

    panel.show()
    drawn = await _synced(panel, drawn)
    drawn = await _synced(panel, drawn)
    assert drawn.battle is not None

    await panel._choose("leave")  # pyright: ignore[reportPrivateUsage]
    assert notified == [NO_BLOCK_LEFT]
    drawn = await _synced(panel, drawn)
    assert panel.column.visible

    assert notified == [NO_BLOCK_LEFT, NO_BLOCK_LEFT]
    _ = await _synced(panel, drawn)
    assert not panel.column.visible
    assert panel.banner.visible


async def _synced(panel: BattleScreen, drawn: SessionSnapshot) -> SessionSnapshot:
    now = panel.session.snapshot()
    panel.sync(now, drawn)
    loop, tasks = get_running_loop(), cast(set[Task[object]], background_tasks.running_tasks)
    await gather(*(task for task in tasks.copy() if task.get_loop() is loop))
    return now
