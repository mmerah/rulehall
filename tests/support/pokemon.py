from rulehall.engines.pokemon.journey.engine import PokemonEngine
from rulehall.engines.pokemon.journey.world import PokemonGame
from support.table import ENGINES_BUILT, POKEMON, game, narrowed

ENGINE = narrowed(ENGINES_BUILT[POKEMON], PokemonEngine)


def started() -> PokemonGame:
    _, begun = game(POKEMON)
    return narrowed(begun, PokemonGame)
