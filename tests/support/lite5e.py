from random import Random

from rulehall.core.stores import read_model
from rulehall.core.validation import Slug
from rulehall.engines.lite5e.data import DATA_DIR
from rulehall.engines.lite5e.hire import SheetProposal
from rulehall.engines.lite5e.pack import Lite5ePack
from rulehall.engines.lite5e.rules import Light
from rulehall.engines.lite5e.sheet import Lite5ePerson
from rulehall.engines.lite5e.world import (
    Goal,
    Hazard,
    Lite5eItem,
    Lite5eMapProposal,
    Lite5ePlace,
    Lite5eWay,
    Lite5eWorld,
)
from rulehall.engines.sheet import PLAYER_ID

PACK = read_model(DATA_DIR.parent / "packs" / "srd.json", Lite5ePack)
GATE: Slug = "gate"
HALL: Slug = "hall"
VAULT: Slug = "vault"
CRYPT: Slug = "crypt"
BANDITS: Slug = "bandits"
PIT: Slug = "pit"
PURSE: Slug = "purse"
DAGGER: Slug = "dagger"


class ScriptedDice(Random):
    def __init__(self, *faces: int) -> None:
        super().__init__()
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        face = self.faces.pop(0)
        assert a <= face <= b
        return face


def sheet_proposal(
    class_id: str = "rogue",
    species_id: str = "human",
    background_id: str = "criminal",
    *,
    subspecies_id: str | None = None,
) -> SheetProposal:
    return SheetProposal(
        kind="class",
        class_id=class_id,
        species_id=species_id,
        subspecies_id=subspecies_id,
        background_id=background_id,
    )


def person(
    person_id: Slug,
    place_id: Slug,
    stat_block_id: str = "commoner",
    *,
    count: int = 1,
    known: bool = True,
    hostile: bool = False,
    captive: bool = False,
) -> Lite5ePerson:
    return Lite5ePerson(
        id=person_id,
        name=person_id.title(),
        brief="Someone of the map",
        voice="other",
        known=known,
        place_id=place_id,
        stat_block_id=stat_block_id,
        count=count,
        hostile=hostile,
        captive=captive,
    )


def hero(proposal: SheetProposal | None = None, level: int = 1) -> Lite5ePerson:
    built = (proposal or sheet_proposal()).build_sheet(level, PACK.backgrounds)
    player = person(PLAYER_ID, GATE)
    player.sheet = built
    return player


def map_proposal(*npcs: Lite5ePerson) -> Lite5eMapProposal:
    names = {GATE: "Gate", HALL: "Hall", VAULT: "Vault", CRYPT: "Crypt"}
    lights: dict[Slug, Light] = {HALL: "dim", VAULT: "dark"}
    places = {
        place_id: Lite5ePlace(
            id=place_id,
            name=name,
            brief=f"The {name.lower()}",
            known=place_id == GATE,
            description=f"The {name.lower()} of the keep.",
            light=lights.get(place_id, "bright"),
            shop=("potion-of-healing",) if place_id == GATE else None,
        )
        for place_id, name in names.items()
    }
    return Lite5eMapProposal(
        places=places,
        ways={
            GATE: [Lite5eWay(to_id=HALL)],
            HALL: [Lite5eWay(to_id=GATE), Lite5eWay(to_id=VAULT, locked=True, lock="easy")],
            VAULT: [Lite5eWay(to_id=HALL, locked=True, lock="easy"), Lite5eWay(to_id=CRYPT)],
            CRYPT: [Lite5eWay(to_id=VAULT)],
        },
        npcs={npc.id: npc for npc in npcs},
        items={
            PIT: Lite5eItem(
                id=PIT,
                name="Pit trap",
                brief="A covered pit",
                holder_id=HALL,
                find="easy",
                trap=Hazard(
                    ability="dexterity",
                    difficulty="medium",
                    damage="light",
                    damage_type="bludgeoning",
                    on_fail="prone",
                    disarm="easy",
                ),
            ),
            PURSE: Lite5eItem(
                id=PURSE, name="Purse", brief="A small purse", holder_id=GATE, find="hard"
            ),
            DAGGER: Lite5eItem(
                id=DAGGER,
                name="Dagger",
                brief="A plain dagger",
                holder_id=GATE,
                known=True,
                gear="dagger",
            ),
        },
        start_id=GATE,
        region_name="The keep",
        goals={"clear-crypt": Goal(brief="Clear the crypt", size="moderate")},
    )


def world(
    *npcs: Lite5ePerson, player: Lite5ePerson | None = None, dice: Random | None = None
) -> Lite5eWorld:
    opening = map_proposal(*npcs)
    built = Lite5eWorld.opening(opening, player or hero(), ())
    built.apply_opening_extras(opening, dice or ScriptedDice())
    return built
