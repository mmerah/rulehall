from functools import partial
from pathlib import Path
from random import Random

from rulehall.app.launch import LaunchTarget
from rulehall.app.session import GameService
from rulehall.core.model import Character, Scenario
from rulehall.core.validation import Slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner3e.engine import Loner3eEngine
from rulehall.engines.loner3e.world import Loner3eEntity, Loner3eGame
from rulehall.engines.scenes.world import SceneProposal
from support.table import (
    ENGINES_BUILT,
    LIBRARY,
    LONER3E,
    SCENARIO_MODELS,
    game,
    narrowed,
    open_table,
)

TARGET = LaunchTarget(scenario_id="whispering-vault", character_id="kael")
MAP: Slug = "vault-map"
MARA: Slug = "mara"
SITUATION = (
    "A frost-rimed colonnade around a dead garden, and the way down is somewhere under it. "
    "Nothing here has been swept in a long while."
)
ENGINE = narrowed(ENGINES_BUILT[LONER3E], Loner3eEngine)


def with_entity(state: Loner3eGame, entity: Loner3eEntity) -> Loner3eGame:
    """Added to the cast and to the scene; `known` alone decides present or hidden."""
    draft = state.draft()
    draft.world.cast[entity.id] = entity
    draft.world.scene.here.append(entity.id)
    return draft.commit()


def loner_sheet(state: Loner3eGame, entity_id: Slug) -> Loner3eEntity:
    return state.world.require(entity_id)


def scenario() -> Scenario[SceneProposal[Loner3eEntity]]:
    scenario = LIBRARY.read_scenario("whispering-vault", SCENARIO_MODELS)
    return narrowed(scenario, Scenario[SceneProposal[Loner3eEntity]])


def character() -> Character[Loner3eEntity]:
    character = LIBRARY.read_character("kael", ENGINE.id, ENGINE.character)
    return narrowed(character, Character[Loner3eEntity])


def initialized() -> tuple[AnyEngine, Loner3eGame]:
    engine, state = game(LONER3E)
    return engine, narrowed(state, Loner3eGame)


open_game = partial(open_table, engine_id=LONER3E, state_type=Loner3eGame)


def session(directory: Path) -> GameService:
    return open_game(directory, rng=Random(1)).service
