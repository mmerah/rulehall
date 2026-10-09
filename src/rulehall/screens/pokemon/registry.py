from pathlib import Path

from rulehall.engines.pokemon.battle.battling import BATTLE_SURFACE_ID
from rulehall.engines.pokemon.champions.team_builder import TEAM_BUILDER_SURFACE_ID
from rulehall.screens.pokemon.battle import BattleScreen
from rulehall.screens.pokemon.team_builder import TeamBuilderScreen
from rulehall.ui.surfaces import ScreenFactories

SCREEN_FACTORIES: ScreenFactories = {
    BATTLE_SURFACE_ID: BattleScreen,
    TEAM_BUILDER_SURFACE_ID: TeamBuilderScreen,
}
STYLES = (Path(__file__).with_name("pokemon.css"),)
