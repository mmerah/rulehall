from pathlib import Path
from random import Random

from rulehall.engines.pokemon.journey.engine import JourneyEngine
from rulehall.engines.pokemon.journey.world import JourneyGame
from support.table import (
    ENGINES_BUILT,
    POKEMON,
    Table,
    game,
    narrated,
    narrowed,
    open_table,
    play_turn,
    tool_call,
)

ENGINE = narrowed(ENGINES_BUILT[POKEMON], JourneyEngine)


def started() -> JourneyGame:
    _, begun = game(POKEMON)
    return narrowed(begun, JourneyGame)


async def into_wild_battle(saves: Path, *then: str) -> Table[JourneyGame]:
    table = open_table(saves, engine_id=POKEMON, state_type=JourneyGame, rng=Random(1))
    _ = await play_turn(
        table,
        "I walk into the tall grass.",
        tool_call("start_wild_battle", species_id="pidgey"),
        tool_call("direct", text="A wild Pidgey flies at the player."),
        narration="A wild Pidgey bursts out of the grass.",
        then=tuple(narrated(line) for line in then),
    )
    return table
