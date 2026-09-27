from functools import partial
from pathlib import Path
from random import Random

from rulehall.app.launch import LaunchTarget
from rulehall.app.session import GameService
from rulehall.core.model import Character, Scenario
from rulehall.core.validation import Slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner4e.engine import Loner4eEngine
from rulehall.engines.loner4e.world import Loner4eEntity, Loner4eGame, Loner4eOpening
from support.table import (
    ENGINES_BUILT,
    LIBRARY,
    LONER4E,
    SCENARIO_MODELS,
    game,
    narrowed,
    open_table,
)

TARGET = LaunchTarget(scenario_id="whispering-vault", character_id="kael")
MARA: Slug = "mara"
TOMAS: Slug = "tomas"
SITUATION = (
    "A frost-rimed colonnade around a dead garden, and the way down is somewhere under it. "
    "Nothing here has been swept in a long while."
)
ENGINE = narrowed(ENGINES_BUILT[LONER4E], Loner4eEngine)


class Dice(Random):
    """Each die shows the next face given, in order."""

    def __init__(self, *faces: int) -> None:
        super().__init__()
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:  # noqa: ARG002
        return self.faces.pop(0)


def with_entity(state: Loner4eGame, entity: Loner4eEntity) -> Loner4eGame:
    """A met entity joins the scene too: a Loner scene holds nobody unmet."""
    draft = state.draft()
    draft.world.cast[entity.id] = entity
    if entity.known:
        draft.world.scene.here.append(entity.id)
    return draft.commit()


def loner_sheet(state: Loner4eGame, entity_id: Slug) -> Loner4eEntity:
    return state.world.require(entity_id)


def scenario() -> Scenario[Loner4eOpening]:
    scenario = LIBRARY.read_scenario("whispering-vault", SCENARIO_MODELS)
    return narrowed(scenario, Scenario[Loner4eOpening])


def character() -> Character[Loner4eEntity]:
    character = LIBRARY.read_character("kael", ENGINE.id, ENGINE.character)
    return narrowed(character, Character[Loner4eEntity])


def initialized() -> tuple[AnyEngine, Loner4eGame]:
    engine, state = game(LONER4E)
    return engine, narrowed(state, Loner4eGame)


open_game = partial(open_table, engine_id=LONER4E, state_type=Loner4eGame)


def session(directory: Path) -> GameService:
    return open_game(directory, rng=Random(1)).service
