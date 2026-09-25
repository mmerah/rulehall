from rulehall.core.prompt import Sections
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID, leaked_names, required_needs
from rulehall.engines.rooms.world import Dungeon, Dweller, MapProposal, RegionProposal, RoomWorld

MAP_ASK = "Write the opening map."
OPENING_SECTIONS: Sections = (
    ("MAP SO FAR", "(no map yet)"),
    ("SCENES SO FAR", "(no scenes yet — write the opening)"),
    ("THE PLAYER", "(no player yet — you write the map before anyone stands in it)"),
)


def check_map[N: Dweller](proposal: MapProposal[N]) -> None:
    if needs := _map_needs(proposal, start_known=True) + _named_needs(proposal):
        raise Refusal("the map needs " + "; ".join(needs))


def check_next_map[N: Dweller](proposal: RegionProposal[N], world: RoomWorld[N]) -> None:
    if not proposal.places:
        raise Refusal("the extension needs at least one new place")
    if needs := (
        _map_needs(proposal, start_known=False)
        + _overlap_needs(proposal, world)
        + _named_needs(proposal)
        + _planted_needs(proposal)
    ):
        raise Refusal("the extension needs " + "; ".join(needs))
    world.check_unnamed(proposal.recap)


def _planted_needs[N: Dweller](proposal: MapProposal[N]) -> list[str]:
    """A new region may not put items straight into the player's pack: no fact, no narration."""
    if planted := sorted(
        item.id for item in proposal.items.values() if item.holder_id == PLAYER_ID
    ):
        return [f"no item planted on the player: {planted}"]
    return []


def _map_needs[N: Dweller](proposal: MapProposal[N], *, start_known: bool) -> list[str]:
    places = proposal.places
    if proposal.start_id not in places:
        return [f"a starting place {proposal.start_id!r}"]
    needs: list[str] = []
    if broken := required_needs(proposal.npcs, ()):
        needs.append(f"npcs as the worldsmith may write them: {broken}")
    if places[proposal.start_id].known != start_known:
        needs.append(
            "the starting place known to the player"
            if start_known
            else "a starting place hidden from the player"
        )
    if missing := sorted(set(places) - proposal.reachable(proposal.start_id, past_locks=True)):
        needs.append(f"places no walk of ways reaches from {proposal.start_id!r}: {missing}")
    return needs


def _overlap_needs[N: Dweller](proposal: MapProposal[N], world: Dungeon[N]) -> list[str]:
    existing = {*world.places, *world.npcs, *world.items}
    added = {*proposal.places, *proposal.npcs, *proposal.items}
    if overlap := sorted(existing & added):
        return [f"ids not already in the world: {overlap}"]
    return []


def _named_needs[N: Dweller](proposal: MapProposal[N]) -> list[str]:
    leaked: set[str] = set()
    hidden = [
        thing for thing in (*proposal.npcs.values(), *proposal.items.values()) if not thing.known
    ]
    for place_id, place in proposal.places.items():
        things = [
            *proposal.things_at(place_id),
            *(proposal.carried(PLAYER_ID) if place_id == proposal.start_id else ()),
        ]
        read = "\n".join((place.name, place.brief, place.description))
        leaked.update(leaked_names(read, things, hidden))
    if named := sorted(leaked):
        return [f"places that do not name what the player has not met: {named}"]
    return []
