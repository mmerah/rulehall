from rulehall.engines.pokemon.engine import PokemonEngine
from rulehall.engines.pokemon.world import PokemonGame
from support.table import ENGINES_BUILT, POKEMON, game, narrowed

ENGINE = narrowed(ENGINES_BUILT[POKEMON], PokemonEngine)


def started() -> PokemonGame:
    _, begun = game(POKEMON)
    return narrowed(begun, PokemonGame)
