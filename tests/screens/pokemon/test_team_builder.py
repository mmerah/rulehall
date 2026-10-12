from collections.abc import Callable
from pathlib import Path

from nicegui import Client, app
from support.table import CHAMPIONS, open_table, play_turn, tool_call

from rulehall.engines.pokemon.champions.world import ChampionsGame
from rulehall.screens.pokemon.slot_editor import picked_ids
from rulehall.screens.pokemon.team_builder import TeamBuilderScreen
from rulehall.ui.screen_host import ScreenHost
from rulehall.ui.widgets import Sounds


def test_a_pick_fills_the_open_slot_or_replaces_the_one_aimed_at() -> None:
    assert picked_ids(("protect",), 1, "fakeout") == ("protect", "fakeout")
    assert picked_ids(("protect", "fakeout"), 0, "tailwind") == ("tailwind", "fakeout")


def test_a_move_already_in_the_set_swaps_places_instead_of_doubling() -> None:
    assert picked_ids(("protect", "fakeout"), 0, "fakeout") == ("fakeout", "protect")
    assert picked_ids(("protect", "fakeout"), 2, "fakeout") == ("protect", "fakeout")


async def test_the_banner_shows_until_the_team_is_registered(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_table(tmp_path, engine_id=CHAMPIONS, state_type=ChampionsGame)
    client = page()
    client.tab_id = "team-builder"
    await app.storage._create_tab_storage(client.tab_id)  # pyright: ignore[reportPrivateUsage]
    screen = TeamBuilderScreen(
        ScreenHost(session=table.session, sounds=Sounds(), on_toggle=lambda: None)
    )
    screen.build_banner()
    drawn = table.session.snapshot()
    screen.build(drawn)
    screen.sync(drawn, drawn)
    assert screen.banner.visible
    state = await play_turn(table, "I sign up.", tool_call("register_team"))
    assert state.world.player_sheet.registered is not None
    screen.sync(table.session.snapshot(), drawn)
    assert not screen.banner.visible
