from asyncio import Task, gather, get_running_loop
from collections.abc import Callable
from pathlib import Path
from random import Random
from typing import cast

import pytest
from nicegui import Client, background_tasks, ui
from support.lite5e import person
from support.table import Table, open_table

from rulehall.app.game_session import SessionSnapshot
from rulehall.core.facts import Fact
from rulehall.core.validation import EngineId
from rulehall.engines.lite5e.battle.state import Battle
from rulehall.engines.lite5e.world import Lite5eGame
from rulehall.screens.lite5e import battle
from rulehall.screens.lite5e.battle import Lite5eBattleScreen
from rulehall.ui.screen_host import ScreenHost
from rulehall.ui.widgets import Sounds

LITE5E = EngineId("lite5e")
WOLVES = "wolves"


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(battle, "FOE_TURN_PAUSE", 0)


async def test_the_screen_draws_the_battle_plays_the_foe_turns_by_itself_and_sends_a_click(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = _in_battle(tmp_path)
    assert _battle(table).phase == "foes"
    page()
    panel = Lite5eBattleScreen(
        ScreenHost(session=table.session, sounds=Sounds(), on_toggle=lambda: None)
    )
    panel.build_banner()
    drawn = table.session.snapshot()
    panel.build(drawn)

    panel.show()
    drawn = await _synced(panel, drawn)
    assert table.session.battle_run is not None
    for _ in range(len(_battle(table).order)):
        if _battle(table).phase == "member":
            break
        drawn = await _synced(panel, drawn)
    drawn = await _synced(panel, drawn)

    assert _battle(table).phase == "member"
    assert _battle(table).turn_index > 0
    assert len(_classed(panel, "game-lite5e-card")) == len(_battle(table).combatants)
    assert {"end", "surrender"} <= set(panel.choice_buttons)

    await panel._choose("end")  # pyright: ignore[reportPrivateUsage]

    assert _battle(table).phase == "foes"
    assert panel.column.visible


async def test_a_closed_page_leaves_the_foe_turn_to_the_pages_still_open(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = _in_battle(tmp_path)
    client = page()
    panel = Lite5eBattleScreen(
        ScreenHost(session=table.session, sounds=Sounds(), on_toggle=lambda: None)
    )
    panel.build_banner()
    drawn = table.session.snapshot()
    panel.build(drawn)
    panel.show()
    panel.sync(table.session.snapshot(), drawn)
    await panel._open_battle()  # pyright: ignore[reportPrivateUsage]
    turn = _battle(table).turn_index

    panel.sync(table.session.snapshot(), drawn)
    client.delete()
    _ = await _synced_tasks()

    assert _battle(table).turn_index == turn
    assert not panel.sending


async def test_the_screen_draws_a_carded_fact_the_narrator_is_not_told(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = _in_battle(tmp_path)
    draft = table.state.draft()
    assert draft.world.battle is not None
    draft.world.battle.facts.append(Fact(trace="Wolves 1 says: Run.", card='Wolves 1: "Run."'))
    table.session.save(table.session.engine.accept(draft))
    page()
    panel = Lite5eBattleScreen(
        ScreenHost(session=table.session, sounds=Sounds(), on_toggle=lambda: None)
    )
    panel.build_banner()
    drawn = table.session.snapshot()
    panel.build(drawn)

    panel.show()
    _ = await _synced(panel, await _synced(panel, drawn))

    shown = [element.text for element in panel.cards.descendants() if isinstance(element, ui.label)]
    assert 'Wolves 1: "Run."' in shown


def _in_battle(saves: Path) -> Table[Lite5eGame]:
    table = open_table(saves, engine_id=LITE5E, state_type=Lite5eGame, rng=Random(0))
    session = table.session
    draft = table.state.draft()
    world = draft.world
    world.npcs[WOLVES] = person(WOLVES, world.current.id, "wolf", count=2, hostile=True)
    _ = session.engine.call_tool(
        draft, "start_battle", {"foe_ids": [WOLVES], "opening": "face_to_face"}, Random(3)
    )
    session.save(session.engine.accept(draft))
    return table


def _battle(table: Table[Lite5eGame]) -> Battle:
    found = table.state.world.battle
    assert found is not None
    return found


def _classed(panel: Lite5eBattleScreen, name: str) -> list[ui.element]:
    return [element for element in panel.column.descendants() if name in element.classes]


async def _synced(panel: Lite5eBattleScreen, drawn: SessionSnapshot) -> SessionSnapshot:
    now = panel.session.snapshot()
    panel.sync(now, drawn)
    _ = await _synced_tasks()
    return now


async def _synced_tasks() -> list[object]:
    loop, tasks = get_running_loop(), cast(set[Task[object]], background_tasks.running_tasks)
    return await gather(*(task for task in tasks.copy() if task.get_loop() is loop))
