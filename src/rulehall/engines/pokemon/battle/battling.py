from pathlib import Path

from rulehall.core.validation import Refusal, Slug
from rulehall.engines.battles import BattleServices
from rulehall.engines.pokemon.battle.simulator import SHOWDOWN, ShowdownRun
from rulehall.engines.pokemon.battle.world import BattleGame

BATTLE_SCREEN_ID: Slug = "pokemon-battle"
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


class ShowdownBattles:
    def in_battle(self, state: BattleGame, /) -> bool:
        return state.world.battle is not None

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

    async def open_battle(self, draft: BattleGame, services: BattleServices, /) -> ShowdownRun:
        transport = await services.start_transport(self.simulator_argv())
        try:
            return await ShowdownRun.start(draft, transport, services.opponent)
        except BaseException:
            await transport.close()
            raise
