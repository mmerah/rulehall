from pathlib import Path

from rulehall.screens.pokemon.battle import BATTLE_SCREEN_ID, BattleScreen
from rulehall.screens.pokemon.team_builder import TEAM_BUILDER_SCREEN_ID, TeamBuilderScreen
from rulehall.ui.screen_host import ScreenFactories

SCREEN_FACTORIES: ScreenFactories = {
    BATTLE_SCREEN_ID: BattleScreen,
    TEAM_BUILDER_SCREEN_ID: TeamBuilderScreen,
}
STYLES = (Path(__file__).parent / "pokemon" / "pokemon.css",)
