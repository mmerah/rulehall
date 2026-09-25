from rulehall.core.model import ScenarioMeta
from rulehall.core.play import Chapter
from rulehall.core.validation import EngineId, Slug
from rulehall.engines.entities import PLAYER_ID, Gauge
from rulehall.engines.rooms.world import Place, Prop, Way
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine
from rulehall.engines.tunnelgoons.world import (
    HP_START,
    Goon,
    GoonSheet,
    TunnelGoonsGame,
    TunnelGoonsWorld,
)
from support.table import ENGINES_BUILT, TUNNELGOONS, narrowed

START: Slug = "start"
HALL: Slug = "hall"
VAULT: Slug = "vault"
CRYPT: Slug = "crypt"
MIRA: Slug = "mira"
MANTIS: Slug = "mantis"
ROPE: Slug = "rope"
TORCH: Slug = "torch"
KEY: Slug = "key"
LANTERN: Slug = "lantern"
GATE: Slug = "gate"
YARD: Slug = "yard"
CELLAR: Slug = "cellar"
WELL: Slug = "well"
WARDEN: Slug = "warden"
ENGINE = narrowed(ENGINES_BUILT[TUNNELGOONS], TunnelGoonsEngine)


def _map_pieces() -> tuple[
    dict[Slug, Place],
    dict[Slug, list[Way]],
    dict[Slug, Goon],
    dict[Slug, Prop],
]:
    """A line of four places, a start->vault shortcut, and hall->vault locked."""
    places = {
        START: Place(
            id=START,
            name="Start",
            brief="Where you begin",
            known=True,
            description="Light seeps under a heavy door.",
        ),
        HALL: Place(
            id=HALL,
            name="Hall",
            brief="A long hall",
            known=True,
            description="Cracked flagstones run its length.",
        ),
        VAULT: Place(
            id=VAULT,
            name="Vault",
            brief="A sealed vault",
            known=False,
            description="Iron bands hold an old door shut.",
        ),
        CRYPT: Place(
            id=CRYPT,
            name="Crypt",
            brief="A quiet crypt",
            known=False,
            description="Dust-choked shelves of bone.",
        ),
    }
    ways = {
        START: [Way(to_id=HALL, known=True), Way(to_id=VAULT, known=False)],
        HALL: [Way(to_id=START, known=True), Way(to_id=VAULT, known=True, locked=True)],
        VAULT: [
            Way(to_id=HALL, known=False),
            Way(to_id=CRYPT, known=False),
            Way(to_id=START, known=False),
        ],
        CRYPT: [Way(to_id=VAULT, known=False)],
    }
    mira = Goon(
        id=MIRA,
        name="Mira",
        brief="A cautious guide",
        known=True,
        place_id=START,
        hp=Gauge(current=8, maximum=8),
    )
    mantis = Goon(
        id=MANTIS,
        name="Robo Mantis",
        brief="A clicking husk of gears",
        known=False,
        place_id=HALL,
        hp=Gauge(current=4, maximum=4),
    )
    items = {
        ROPE: Prop(id=ROPE, name="Rope", brief="A coil of rope", known=True, holder_id=PLAYER_ID),
        TORCH: Prop(
            id=TORCH, name="Torch", brief="An unlit torch", known=True, holder_id=PLAYER_ID
        ),
        KEY: Prop(id=KEY, name="Key", brief="A tarnished key", known=False, holder_id=HALL),
        LANTERN: Prop(
            id=LANTERN, name="Lantern", brief="A dented lantern", known=True, holder_id=START
        ),
    }
    return places, ways, {mira.id: mira, mantis.id: mantis}, items


def _kael() -> Goon:
    return Goon(
        id=PLAYER_ID,
        name="Kael",
        brief="A wiry scavenger",
        known=True,
        place_id=PLAYER_ID,
        hp=Gauge(current=HP_START, maximum=HP_START),
        sheet=GoonSheet(abilities={"brute": 1, "skulker": 1, "erudite": 1}),
        kit=("Rope", "Torch", "Lantern"),
    )


def _game(world: TunnelGoonsWorld, *, scenario_id: Slug, chapter: Chapter) -> TunnelGoonsGame:
    return TunnelGoonsGame(
        scenario_id=scenario_id,
        character_id="kael",
        scenario=ScenarioMeta(
            title="Test",
            premise="A test dungeon.",
            backdrop="Plain.",
            scope="One dungeon, played to its end.",
        ),
        engine_id=EngineId("tunnelgoons"),
        pack_id="srd",
        log=[chapter],
        world=world,
    )


def small_world() -> TunnelGoonsGame:
    places, ways, npcs, items = _map_pieces()
    world = TunnelGoonsWorld(
        places=places,
        ways=ways,
        npcs=npcs,
        items=items,
        player=_kael(),
        visits=[START],
    )
    return _game(world, scenario_id="test", chapter=Chapter(title="Start"))


def _keep_place(place_id: Slug, name: str, *, known: bool) -> Place:
    return Place(id=place_id, name=name, brief=f"The {name.lower()}", known=known, description=name)


def keep() -> TunnelGoonsGame:
    places = {
        GATE: _keep_place(GATE, "Gate", known=True),
        YARD: _keep_place(YARD, "Yard", known=False),
        CELLAR: _keep_place(CELLAR, "Cellar", known=False),
        WELL: _keep_place(WELL, "Well", known=False),
    }
    ways = {
        GATE: [Way(to_id=YARD, known=True)],
        YARD: [Way(to_id=CELLAR), Way(to_id=WELL, locked=True)],
        CELLAR: [Way(to_id=WELL)],
    }
    warden = Goon(
        id=WARDEN,
        name="Warden",
        brief="Keeps the gate",
        known=True,
        place_id=GATE,
        hp=Gauge(current=8, maximum=8),
    )
    lantern = Prop(id=LANTERN, name="Lantern", brief="A dim lantern", known=False, holder_id=YARD)
    world = TunnelGoonsWorld(
        places=places,
        ways=ways,
        npcs={WARDEN: warden},
        items={LANTERN: lantern},
        player=_kael(),
        visits=[GATE],
    )
    return _game(world, scenario_id="the-keep", chapter=Chapter(title="Gate"))
