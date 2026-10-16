from pathlib import Path

from rulehall.screens.lite5e.battle import BATTLE_SCREEN_ID as LITE5E_BATTLE_SCREEN_ID
from rulehall.screens.lite5e.battle import Lite5eBattleScreen
from rulehall.screens.pokemon.battle import BATTLE_SCREEN_ID as POKEMON_BATTLE_SCREEN_ID
from rulehall.screens.pokemon.battle import BattleScreen
from rulehall.screens.pokemon.team_builder import TEAM_BUILDER_SCREEN_ID, TeamBuilderScreen
from rulehall.ui.screen_host import ScreenFactories

SCREEN_FACTORIES: ScreenFactories = {
    POKEMON_BATTLE_SCREEN_ID: BattleScreen,
    TEAM_BUILDER_SCREEN_ID: TeamBuilderScreen,
    LITE5E_BATTLE_SCREEN_ID: Lite5eBattleScreen,
}
STYLES = (
    Path(__file__).parent / "pokemon" / "pokemon.css",
    Path(__file__).parent / "lite5e" / "lite5e.css",
)
