from rulehall.engines.pokemon.journey.engine import JourneyEngine
from rulehall.engines.pokemon.journey.world import JourneyGame
from support.table import ENGINES_BUILT, POKEMON, game, narrowed

ENGINE = narrowed(ENGINES_BUILT[POKEMON], JourneyEngine)


def started() -> JourneyGame:
    _, begun = game(POKEMON)
    return narrowed(begun, JourneyGame)
