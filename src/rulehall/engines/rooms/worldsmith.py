from rulehall.core.prompt import Sections
from rulehall.core.validation import Refusal
from rulehall.engines.name_leaks import leaked_names
from rulehall.engines.rooms.world import (
    OFF_MAP_ID,
    Dweller,
    MapProposal,
    RegionProposal,
    RoomMap,
    RoomWorld,
)
from rulehall.engines.sheet import PLAYER_ID

MAP_ASK = "Write the opening map."
OPENING_SECTIONS: Sections = (
    ("MAP SO FAR", "(no map yet)"),
    ("SCENES SO FAR", "(no scenes yet — write the opening)"),
    ("THE PLAYER", "(no player yet — you write the map before anyone stands in it)"),
)


def check_opening[P: Dweller](proposal: MapProposal[P]) -> None:
    if needs := (
        _map_needs(proposal, start_known=True) + _standing_needs(proposal) + _named_needs(proposal)
    ):
        raise Refusal("the map needs " + "; ".join(needs))


def check_next[P: Dweller](proposal: RegionProposal[P], world: RoomWorld[P]) -> None:
    if not proposal.places:
        raise Refusal("the extension needs at least one new place")
    if needs := (
        _map_needs(proposal, start_known=False)
        + _standing_needs(proposal)
        + _overlap_needs(proposal, world)
        + _named_needs(proposal)
        + _planted_needs(proposal)
    ):
        raise Refusal("the extension needs " + "; ".join(needs))
    world.refuse_unmet_names(proposal.recap)


def _planted_needs[P: Dweller](proposal: MapProposal[P]) -> list[str]:
    if planted := sorted(
        item.id for item in proposal.items.values() if item.holder_id == PLAYER_ID
    ):
        return [f"no item planted on the player: {planted}"]
    return []


def _map_needs[P: Dweller](proposal: MapProposal[P], *, start_known: bool) -> list[str]:
    places = proposal.places
    if proposal.start_id not in places:
        return [f"a starting place {proposal.start_id!r}"]
    needs: list[str] = []
    if places[proposal.start_id].known != start_known:
        needs.append(
            "the starting place known to the player"
            if start_known
            else "a starting place hidden from the player"
        )
    if missing := sorted(set(places) - proposal.reachable(proposal.start_id, past_locks=True)):
        needs.append(f"places no walk of ways reaches from {proposal.start_id!r}: {missing}")
    return needs


def _standing_needs[P: Dweller](proposal: MapProposal[P]) -> list[str]:
    if strays := sorted(npc.id for npc in proposal.npcs.values() if npc.place_id == OFF_MAP_ID):
        return [f"every npc in a place of this map: {strays}"]
    return []


def _overlap_needs[P: Dweller](proposal: MapProposal[P], world: RoomMap[P]) -> list[str]:
    existing = {*world.places, *world.npcs, *world.items}
    added = {*proposal.places, *proposal.npcs, *proposal.items}
    if overlap := sorted(existing & added):
        return [f"ids not already in the world: {overlap}"]
    return []


def _named_needs[P: Dweller](proposal: MapProposal[P]) -> list[str]:
    leaked: set[str] = set()
    hidden = [
        entity for entity in (*proposal.npcs.values(), *proposal.items.values()) if not entity.known
    ]
    for place_id, place in proposal.places.items():
        entities = [
            *proposal.entities_at(place_id),
            *(proposal.carried(PLAYER_ID) if place_id == proposal.start_id else ()),
        ]
        read = "\n".join((place.name, place.brief, place.description))
        leaked.update(leaked_names(read, entities, hidden))
    if named := sorted(leaked):
        return [f"places that do not name what the player has not met: {named}"]
    return []
