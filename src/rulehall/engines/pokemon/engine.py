from typing import Any

from rulehall.core.game import Game
from rulehall.core.validation import EngineId
from rulehall.core.views import ScreenSlot
from rulehall.engines.bases.maps.engine import MapEngine
from rulehall.engines.bases.maps.world import Dweller, MapWorld, RegionProposal
from rulehall.engines.engine import Joining
from rulehall.engines.packs import Pack
from rulehall.engines.pokemon.battle.battling import ASSETS, BATTLE_SCREEN_ID, ShowdownBattles

RULE_SET_ID = EngineId("pokemon")


class PokemonEngine[
    P: Dweller,
    W: MapWorld[Any, Any, Any, Any],
    K: Pack,
    R: RegionProposal[Any, Any, Any, Any],
](Joining[W], MapEngine[P, W, K, R]):
    title = "POKEMON"
    art_style = "Bright anime-style illustration, clean lines, soft colours, no text or lettering."
    portraits = False
    rule_set_id = RULE_SET_ID
    assets = ASSETS
    battles = ShowdownBattles()

    def screen_slots(self, state: Game[W], /) -> tuple[ScreenSlot, ...]:
        return (
            *super().screen_slots(state),
            ScreenSlot(screen_id=BATTLE_SCREEN_ID, live=self.in_battle(state)),
        )
