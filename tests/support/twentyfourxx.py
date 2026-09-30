from collections.abc import Mapping, Sequence
from functools import partial

from rulehall.core.game import ScenarioDescription
from rulehall.core.log import Chapter
from rulehall.core.validation import EngineId, Slug
from rulehall.engines.packs import SRD_PACK
from rulehall.engines.scenes.world import Scene
from rulehall.engines.sheet import PLAYER_ID
from rulehall.engines.twentyfourxx.engine import TwentyFourXXEngine
from rulehall.engines.twentyfourxx.rules import SkillDie
from rulehall.engines.twentyfourxx.sheet import Crewmate, CrewSheet, Gear
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame, TwentyFourXXWorld
from support.table import ENGINES_BUILT, TWENTYFOURXX, narrowed, open_table

KESTREL: Slug = "kestrel"
SABLE: Slug = "sable"
LOCKPICKS: Slug = "lockpicks"
SITUATION = (
    "Cargo containers stack three high across the loading bay, and the station's night crew "
    "has just killed the lights for a scheduled power-saving cycle."
)
ENGINE = narrowed(ENGINES_BUILT[TWENTYFOURXX], TwentyFourXXEngine)
# Shared by every test that builds a scene draft from scratch.
SCENE_BASE: Mapping[str, object] = {
    "place_id": "bay-office",
    "location": "The cargo station",
    "title": "The Bay Office",
    "situation": SITUATION,
    "arc": "Farther in, the fixer's own supplier still owes for the last load.",
}
# The first d6 of this seed is a 1, so a bad-luck test brings the trouble.
TROUBLE_SEED = 2
open_crew = partial(open_table, engine_id=TWENTYFOURXX, state_type=TwentyFourXXGame)


def small_world() -> TwentyFourXXGame:
    kestrel = Crewmate(id=KESTREL, name="Kestrel", voice="feminine", brief="A dockhand", known=True)
    sable = Crewmate(
        id=SABLE, name="Sable", voice="feminine", brief="A rival operator", known=False
    )
    world = TwentyFourXXWorld(
        cast={KESTREL: kestrel, SABLE: sable},
        player=_player(),
        scenes=[_scene(here=[KESTREL, SABLE])],
    )
    return TwentyFourXXGame(
        scenario_id="loading-bay",
        character_id="rook",
        scenario_description=ScenarioDescription(
            title="Loading Bay",
            premise="A cargo job gone quiet.",
            backdrop="Plain.",
            scope="One tense night shift.",
        ),
        engine_id=EngineId("twentyfourxx"),
        pack_id=SRD_PACK,
        chapters=[
            Chapter(
                title="The Loading Bay",
            )
        ],
        world=world,
    )


def hired(
    state: TwentyFourXXGame, entity_id: Slug, *, skills: dict[str, SkillDie]
) -> TwentyFourXXGame:
    """Give a cast member a sheet and put them in the party, for tests that need a hired hand."""
    draft = state.draft()
    draft.world.cast[entity_id].sheet = CrewSheet(specialty="Muscle", skills=skills)
    draft.world.party_ids.append(entity_id)
    return draft.validated()


def _scene(*, here: Sequence[Slug] = ()) -> Scene:
    return Scene(
        place_id="loading-bay",
        location="The cargo station",
        title="The Loading Bay",
        situation=SITUATION,
        here_ids=list(here),
    )


def _player() -> Crewmate:
    return Crewmate(
        id=PLAYER_ID,
        name="Rook",
        voice="masculine",
        brief="A quiet operator",
        known=True,
        sheet=CrewSheet(
            specialty="Sneak",
            origin="Human",
            skills={"Stealth": 10},
            items={LOCKPICKS: Gear(name="Lockpick set")},
        ),
    )
