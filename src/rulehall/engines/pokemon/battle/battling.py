from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rulehall.core.game import AnyGame, RoleAnswer
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import Surface
from rulehall.engines.battles import Battling, Transport
from rulehall.engines.engine import Engine
from rulehall.engines.packs import Pack
from rulehall.engines.pokemon.battle.simulator import SHOWDOWN, ShowdownRun
from rulehall.engines.pokemon.battle.world import BattleGame
from rulehall.engines.sheet import Person
from rulehall.engines.world import World

BATTLE_SURFACE_ID: Slug = "pokemon-battle"
SIMULATOR = SHOWDOWN / "node_modules" / "pokemon-showdown" / "pokemon-showdown"
ASSETS = Path(__file__).parents[5] / "vendor" / "showdown"
ASSETS_COMPLETE = ASSETS / "complete"
ASSETS_VERSION = SHOWDOWN / "assets-version"
SETUP_HINT = (
    "the battle simulator is not installed: run "
    "`npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again"
)
ASSETS_HINT = (
    "the Pokemon art and sound are not fetched or are out of date: run "
    "`npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again; "
    "in Docker, the container fetches them when it starts, so wait for "
    "'Pokemon art and sound: ready' in its log"
)


class ShowdownBattling[P: Person, W: World[Any], K: Pack, R: BaseModel](
    Battling, Engine[P, W, K, R]
):
    assets: Path | None = ASSETS

    def in_battle(self, state: BattleGame) -> bool:
        return state.world.battle is not None

    def surfaces(self, state: AnyGame, /) -> tuple[Surface, ...]:
        return (
            *super().surfaces(state),
            Surface(surface_id=BATTLE_SURFACE_ID, live=self.in_battle(state)),
        )

    def simulator_argv(self) -> tuple[str, ...]:
        if not SIMULATOR.is_file():
            raise Refusal(SETUP_HINT)
        if (
            not ASSETS_COMPLETE.is_file()
            or ASSETS_COMPLETE.read_text() != ASSETS_VERSION.read_text()
        ):
            raise Refusal(ASSETS_HINT)
        # The postinstall builds the simulator; a build run prints to stdout before the first block.
        return ("node", str(SIMULATOR), "simulate-battle", "--skip-build")

    async def open_battle(
        self, draft: BattleGame, transport: Transport, opponent: RoleAnswer | None
    ) -> ShowdownRun:
        return await ShowdownRun.start(draft, transport, opponent)
