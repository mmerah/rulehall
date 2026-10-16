from rulehall.core.prompt import Sections
from rulehall.core.validation import Refusal
from rulehall.engines.bases.maps.world import (
    OFF_MAP_ID,
    Dweller,
    Item,
    MapContents,
    MapProposal,
    MapWorld,
    Place,
    RegionProposal,
    Way,
)
from rulehall.engines.name_leaks import leaked_names, names_in
from rulehall.engines.sheet import PLAYER_ID

MAP_ASK = "Write the opening map."
OPENING_SECTIONS: Sections = (
    ("MAP SO FAR", "(no map yet)"),
    ("SCENES SO FAR", "(no scenes yet — write the opening)"),
    ("THE PLAYER", "(no player yet — you write the map before anyone stands in it)"),
)


def check_opening[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT],
) -> None:
    if needs := (
        _map_needs(proposal, start_known=True) + _standing_needs(proposal) + _named_needs(proposal)
    ):
        raise Refusal("the map needs " + "; ".join(needs))


def check_next[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: RegionProposal[P, I, L, WayT], world: MapWorld[P, I, L, WayT]
) -> None:
    if not proposal.places:
        raise Refusal("the extension needs at least one new place")
    if needs := (
        _map_needs(proposal, start_known=False)
        + _standing_needs(proposal)
        + _overlap_needs(proposal, world)
        + _region_name_needs(proposal, world)
        + _named_needs(proposal)
        + _planted_needs(proposal)
    ):
        raise Refusal("the extension needs " + "; ".join(needs))
    world.refuse_unmet_names(proposal.recap, proposal.region_name)


def _planted_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT],
) -> list[str]:
    if planted := sorted(
        item.id for item in proposal.items.values() if item.holder_id == PLAYER_ID
    ):
        return [f"no item planted on the player: {planted}"]
    return []


def _map_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT], *, start_known: bool
) -> list[str]:
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


def _standing_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT],
) -> list[str]:
    if strays := sorted(npc.id for npc in proposal.npcs.values() if npc.place_id == OFF_MAP_ID):
        return [f"every npc in a place of this map: {strays}"]
    return []


def _overlap_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT], world: MapContents[P, I, L, WayT]
) -> list[str]:
    existing = {*world.places, *world.npcs, *world.items}
    added = {*proposal.places, *proposal.npcs, *proposal.items}
    if overlap := sorted(existing & added):
        return [f"ids not already in the world: {overlap}"]
    return []


def _region_name_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT], world: MapWorld[P, I, L, WayT]
) -> list[str]:
    if proposal.region_name.casefold() in {region.name.casefold() for region in world.regions}:
        return [f"a region name not already on the map: {proposal.region_name!r}"]
    return []


def _named_needs[P: Dweller, I: Item, L: Place, WayT: Way](
    proposal: MapProposal[P, I, L, WayT],
) -> list[str]:
    hidden = [
        entity for entity in (*proposal.npcs.values(), *proposal.items.values()) if not entity.known
    ]
    needs: list[str] = []
    if region_named := sorted(set(names_in(proposal.region_name, hidden))):
        needs.append(
            f"a region name that does not name what the player has not met: {region_named}"
        )
    leaked: set[str] = set()
    for place_id, place in proposal.places.items():
        entities = [
            *proposal.entities_at(place_id),
            *(proposal.carried(PLAYER_ID) if place_id == proposal.start_id else ()),
        ]
        read = "\n".join((place.name, place.brief, place.description))
        leaked.update(leaked_names(read, entities, hidden))
    if named := sorted(leaked):
        needs.append(f"places that do not name what the player has not met: {named}")
    return needs
