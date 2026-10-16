from collections.abc import Iterable, Iterator, Mapping
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.prompt import lines_of
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique, parse
from rulehall.engines.sheet import PLAYER_ID, Entity, Person, rows_text
from rulehall.engines.world import IS_DEAD, UNKNOWN_ID, OpeningProposal, World, check_filing

MEANWHILE_EVERY = 4
MEANWHILE_CHANGES_MIN = 2
MEANWHILE_CHANGES_MAX = 6
OFF_MAP_ID: Slug = "off-map"
EXTEND_REQUEST: Slug = "extend"


class Dweller(Person):
    place_id: Slug


class Item(Entity):
    holder_id: Slug


class Place(Entity):
    description: str = Field(min_length=1)


class Way(Mutable):
    """One way out, in one direction, from the place it is filed under."""

    to_id: Slug
    known: bool = Field(
        default=True, description="False only for a secret way the story must find."
    )
    locked: bool = False

    def lock_text(self) -> str:
        return "; locked" if self.locked else ""


class Region(Mutable):
    start_id: Slug
    name: str = Field(min_length=1)
    place_ids: list[Slug] = Field(min_length=1)

    @model_validator(mode="after")
    def _starts_inside(self) -> Self:
        if self.start_id not in self.place_ids:
            raise ValueError(f"region {self.name} does not hold its start {self.start_id!r}")
        return self


class MapContents[P: Dweller, I: Item = Item, L: Place = Place, WayT: Way = Way](Mutable):
    places: dict[Slug, L] = Field(default_factory=dict)
    ways: dict[Slug, list[WayT]] = Field(default_factory=dict)
    npcs: dict[Slug, P] = Field(default_factory=dict)
    items: dict[Slug, I] = Field(default_factory=dict)
    arc: str = Field(
        default="",
        description="The truth behind this map: secrets, what can come, and what ties one "
        "hidden thing to another. The player never reads it.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_filing(self.places)
        check_filing(self.npcs)
        check_filing(self.items)
        check_unique(
            "ids across places, npcs and items",
            (*self.places, *self.npcs, *self.items, PLAYER_ID, OFF_MAP_ID),
        )
        for npc in self.npcs.values():
            if npc.place_id != OFF_MAP_ID and npc.place_id not in self.places:
                raise ValueError(f"{npc.name} is in no place: {npc.place_id!r}")
        holders = {*self.npcs, *self.places, PLAYER_ID}
        for item in self.items.values():
            if item.holder_id not in holders:
                raise ValueError(f"{item.name} is on nothing: {item.holder_id!r}")
            if item.holder_id == PLAYER_ID and not item.known:
                raise ValueError(f"{item.name} is on the player but unknown to them")
        for from_id, ways in self.ways.items():
            if from_id not in self.places:
                raise ValueError(f"ways are filed under {from_id!r}, which is not a place")
            check_unique(f"ways out of {from_id!r}", (way.to_id for way in ways))
            for way in ways:
                if way.to_id not in self.places:
                    raise ValueError(
                        f"a way from {from_id!r} leads to {way.to_id!r}, which is not a place"
                    )
                if way.to_id == from_id:
                    raise ValueError(f"a way from {from_id!r} cannot lead back to itself")
        return self

    def find_entity(self, entity_id: Slug) -> P | I | L | None:
        return self.places.get(entity_id) or self.npcs.get(entity_id) or self.items.get(entity_id)

    def require_entity(self, entity_id: Slug) -> P | I | L:
        entity = self.find_entity(entity_id)
        if entity is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        return entity

    def require_place(self, entity_id: Slug) -> L:
        place = self.places.get(entity_id)
        if place is None:
            _ = self.require_entity(entity_id)
            raise Refusal(f"{entity_id!r} is not a place")
        return place

    def find_way(self, from_id: Slug, to_id: Slug) -> WayT | None:
        return next((way for way in self.ways.get(from_id, ()) if way.to_id == to_id), None)

    def at(self, place_id: Slug) -> Iterator[P]:
        return (npc for npc in self.npcs.values() if npc.place_id == place_id)

    def carried(self, holder_id: Slug) -> Iterator[I]:
        return (item for item in self.items.values() if item.holder_id == holder_id)

    def entities_at(self, place_id: Slug) -> Iterator[P | I]:
        npcs = list(self.at(place_id))
        yield from npcs
        for holder in (place_id, *(npc.id for npc in npcs)):
            yield from self.carried(holder)

    def reachable(self, start_id: Slug, *, past_locks: bool = False) -> set[Slug]:
        reached = {start_id}
        pending = [start_id]
        while pending:
            current = pending.pop()
            for way in self.ways.get(current, ()):
                if way.to_id in reached or (way.locked and not past_locks):
                    continue
                reached.add(way.to_id)
                pending.append(way.to_id)
        return reached


class MapProposal[P: Dweller, I: Item = Item, L: Place = Place, WayT: Way = Way](
    MapContents[P, I, L, WayT], OpeningProposal
):
    start_id: Slug = Field(description="Exact id of the place this map starts from.")
    region_name: str = Field(
        min_length=1,
        description="The name of this part of the map as the player knows it, such as a "
        "district, a level of a dungeon, an island or a city: never one room. Once the player "
        "leaves it, the map shows the whole region under this name. Name nothing hidden.",
    )

    def premise(self) -> str:
        start = self.places.get(self.start_id)
        return "" if start is None else start.description


class RegionProposal[P: Dweller, I: Item = Item, L: Place = Place, WayT: Way = Way](
    MapProposal[P, I, L, WayT]
):
    recap: str = Field(
        min_length=1,
        description="One paragraph on the part of the map the player leaves behind: what the "
        "player did there, paid and learned. The narrator reads it. Name nothing hidden.",
    )


class MapWorld[P: Dweller, I: Item = Item, L: Place = Place, WayT: Way = Way](
    MapContents[P, I, L, WayT], World[P]
):
    visited_place_ids: list[Slug] = Field(min_length=1)
    regions: list[Region] = Field(min_length=1)
    turns_since_meanwhile: int = Field(default=0, ge=0)
    meanwhile_due: bool = False

    @model_validator(mode="after")
    def _playable(self) -> Self:
        for place_id in self.visited_place_ids:
            self.require_place(place_id)
        region_place_ids = [place_id for region in self.regions for place_id in region.place_ids]
        check_unique("places across regions", region_place_ids)
        if stray := sorted(set(region_place_ids) - set(self.places)):
            raise ValueError(f"regions hold ids that are not places: {stray}")
        if outside := sorted(set(self.places) - set(region_place_ids)):
            raise ValueError(f"places in no region: {outside}")
        for member_id in self.party_ids:
            npc = self.npcs[member_id]
            if npc.place_id != self.current.id:
                raise ValueError(f"{member_id!r} travels with the player but is not at their place")
        return self

    @classmethod
    def opening(
        cls,
        proposal: MapProposal[P, I, L, WayT],
        player: P,
        items: Iterable[I],
        **extra_fields: object,
    ) -> Self:
        return parse(
            cls,
            {
                "places": proposal.places,
                "ways": proposal.ways,
                "npcs": proposal.npcs,
                "items": {**proposal.items, **{item.id: item for item in items}},
                "player": player,
                "visited_place_ids": [proposal.start_id],
                "regions": [
                    {
                        "start_id": proposal.start_id,
                        "name": proposal.region_name,
                        "place_ids": list(proposal.places),
                    }
                ],
                **extra_fields,
            },
        )

    @property
    def current(self) -> L:
        return self.places[self.visited_place_ids[-1]]

    @property
    def current_region(self) -> Region:
        return self.require_region(self.current.id)

    def require_region(self, place_id: Slug) -> Region:
        return next(region for region in self.regions if place_id in region.place_ids)

    def visited_region_places(self) -> list[L]:
        place_ids = self.current_region.place_ids
        return [place for place in self.visited_places() if place.id in place_ids]

    def at_map_edge(self) -> bool:
        return not self.has_frontier()

    def has_frontier(self) -> bool:
        visited = set(self.visited_place_ids)
        region_ids = set(self.current_region.place_ids)
        return any(
            way.known and not way.locked and way.to_id not in visited
            for place_id in visited & region_ids & self.reachable(self.current.id)
            for way in self.ways.get(place_id, ())
        )

    def is_unexplored(self, way: Way) -> bool:
        return way.known and not self.require_place(way.to_id).known

    def find_entity(self, entity_id: Slug) -> P | I | L | None:
        return self.player if entity_id == self.player.id else super().find_entity(entity_id)

    @property
    def roster(self) -> Mapping[Slug, P]:
        return self.npcs

    def here(self) -> Iterator[P]:
        yield self.player
        yield from self.at(self.current.id)

    def known_names(self) -> Iterator[str]:
        yield from (place.name for place in self.places.values() if place.known)
        yield from (item.name for item in self.items.values() if item.known)
        yield from (region.name for region in self.regions)

    def holders_here(self) -> set[Slug]:
        return {self.current.id, *(entity.id for entity in self.here())}

    def require_dweller(self, entity_id: Slug) -> P:
        npc = self.npcs.get(entity_id)
        if npc is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        if not npc.alive:
            raise Refusal(IS_DEAD.format(name=npc.name))
        return npc

    def require_item(self, item_id: Slug) -> I:
        item = self.items.get(item_id)
        if item is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=item_id))
        return item

    def require_person_here(self, entity_id: Slug) -> P:
        npc = self.require_dweller(entity_id)
        if npc.place_id != self.current.id or not npc.known:
            raise Refusal(f"{npc.name} is not here with the player")
        return npc

    def require_item_here(self, item_id: Slug) -> I:
        item = self.items.get(item_id)
        if item is None:
            _ = self.require_entity(item_id)
            raise Refusal(f"{item_id!r} is not an item")
        if item.holder_id not in self.holders_here():
            raise Refusal(f"{item.name} is not here with the player")
        return item

    def require_carried_items(self, holder: Person, item_ids: tuple[Slug, ...]) -> tuple[I, ...]:
        check_unique("items", item_ids)
        items: list[I] = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item is None or item.holder_id != holder.id or not item.known:
                raise Refusal(f"{item_id!r} is not in {holder.name}'s hands")
            items.append(item)
        return tuple(items)

    def count_turn(self) -> None:
        if self.meanwhile_due or not self.can_move_offscreen():
            return
        self.turns_since_meanwhile += 1
        if self.turns_since_meanwhile >= MEANWHILE_EVERY:
            self.turns_since_meanwhile = 0
            self.meanwhile_due = True

    def meanwhile_cap(self) -> int:
        return min(
            MEANWHILE_CHANGES_MAX,
            max(MEANWHILE_CHANGES_MIN, len(self.visited_places()) // 3),
        )

    def _learn_way(self, way: Way, destination: L) -> None:
        way.known = True
        if (back := self.find_way(destination.id, self.current.id)) is not None:
            back.known = True

    def move(self, to_id: Slug, with_ids: tuple[Slug, ...]) -> list[Fact]:
        here = self.current
        destination = self.require_place(to_id)
        way = self.find_way(here.id, destination.id)
        if way is None:
            options = ", ".join(
                self.require_place(other.to_id).name for other in self.ways.get(here.id, ())
            )
            raise Refusal(
                f"no way leads from {here.name} to {destination.name}; ways out: "
                f"{options or '(none)'}"
            )
        if way.locked:
            raise Refusal(f"the way to {destination.name} is locked; open the lock first")
        self._learn_way(way, destination)
        facts = destination.reveal()
        check_unique("with_ids", with_ids)
        coming: list[P] = []
        for npc_id in with_ids:
            if npc_id == self.player.id:
                raise Refusal("the player already comes along")
            npc = self.require_person_here(npc_id)
            if npc.id in self.party_ids:
                raise Refusal(
                    f"{npc.name} travels with the player and comes along without with_ids"
                )
            coming.append(npc)
        travelers = [*self.party_members(), *coming]
        for npc in travelers:
            npc.place_id = destination.id
        self.visited_place_ids.append(destination.id)
        trace = f"the player arrives at {destination.mention}"
        if travelers:
            names = " and ".join(npc.name for npc in travelers)
            verb = "comes" if len(travelers) == 1 else "come"
            trace += f", and {names} {verb} along"
        facts.append(destination.fact(trace, card=f"Arrived at {destination.name}"))
        return facts

    def unlock_way(self, to_id: Slug) -> list[Fact]:
        here = self.current
        destination = self.require_place(to_id)
        way = self.find_way(here.id, destination.id)
        if way is None:
            raise Refusal(f"no way leads from {here.name} to {destination.name}")
        if not way.locked:
            raise Refusal(f"the way from {here.name} to {destination.name} is not locked")
        self.set_locked(here.id, destination.id, locked=False)
        self._learn_way(way, destination)
        trace = f"the way from {here.mention} to {destination.mention} is unlocked"
        card = f"{destination.name} unlocked"
        return [*destination.reveal(), here.fact(trace, card=card)]

    def reveal_hidden(self, entity_id: Slug) -> list[Fact]:
        entity = self.require_entity(entity_id)
        location = (
            entity.place_id
            if isinstance(entity, Dweller)
            else entity.holder_id
            if isinstance(entity, Item)
            else None
        )
        if location not in self.holders_here():
            raise Refusal(f"{entity.name} is not here with the player")
        found = "found" if isinstance(entity, Item) else "discovered"
        if entity.known:
            raise Refusal(f"the player has already {found} {entity.name}")
        return entity.reveal(card=f"{entity.name} {found}")

    def move_item(self, item_id: Slug, holder_id: Slug) -> list[Fact]:
        item = self.require_item_here(item_id)
        if holder_id != self.player.id and holder_id != self.current.id:
            npc = next(
                (other for other in self.here() if other.id == holder_id and other.alive), None
            )
            if npc is None:
                raise Refusal(
                    f"{holder_id!r} cannot hold {item.name}; give the player, a living npc here, "
                    "or this place"
                )
        holder = self.require_entity(holder_id)
        if not holder.known:
            raise Refusal(f"the player has not met {holder.name}; reveal them first")
        if item.holder_id == holder_id:
            raise Refusal(f"{item.name} is already there")
        facts = item.reveal()
        item.holder_id = holder_id
        card = (
            f"Took {item.name}" if holder_id == self.player.id else f"{item.name} → {holder.name}"
        )
        trace = f"{item.mention} moves to {holder.mention}"
        return [*facts, item.fact(trace, card=card)]

    def walk(self, npc: P, place: L) -> Fact:
        self._refuse_party(npc)
        if not npc.alive:
            raise Refusal(IS_DEAD.format(name=npc.name))
        if npc.place_id == OFF_MAP_ID:
            raise Refusal(f"{npc.name} has left the map")
        origin = self.require_place(npc.place_id)
        walked = self.find_way(origin.id, place.id)
        if walked is None or walked.locked:
            raise Refusal(f"no unlocked way leads from {origin.name} to {place.name}")
        npc.place_id = place.id
        untold = f"{npc.ref} walks from {origin.ref} to {place.ref}"
        if place.id == self.current.id:
            trace = f"{npc.mention} walks in" + _end_phrase(origin, walked, " from ")
            return _told_or_untold(npc, trace, f"{npc.name} walks in", untold)
        if origin.id == self.current.id:
            trace = f"{npc.mention} walks out" + _end_phrase(place, walked, " to ")
            return _told_or_untold(npc, trace, f"{npc.name} leaves", untold)
        return Fact(trace=untold)

    def carry(self, item: I, holder: P | I | L) -> Fact:
        source = self._item_place(item)
        if isinstance(holder, Place):
            destination = holder
        elif isinstance(holder, Dweller) and holder.alive and holder.place_id != OFF_MAP_ID:
            self._refuse_party(holder)
            destination = self.require_place(holder.place_id)
        else:
            raise Refusal(
                f"{holder.name} cannot hold {item.name}; give a place or a living dweller"
            )
        if destination.id not in {self.current.id, *(place.id for place in self.elsewhere())}:
            raise Refusal(f"{destination.name} is not listed under ELSEWHERE")
        if item.holder_id == holder.id:
            raise Refusal(f"{item.name} is already there")
        here = self.current
        if source.id == here.id and destination.id == here.id:
            raise Refusal(f"{item.name} stays with the player; call move_item for that")
        item.holder_id = holder.id
        untold = f"{item.ref} goes from {source.ref} to {holder.ref}"
        if isinstance(holder, Dweller) and not holder.known:
            return Fact(trace=untold)
        if destination.id == here.id:
            way = self.find_way(here.id, source.id)
            trace = f"{item.mention} turns up here" + _end_phrase(source, way, " from ")
            return _told_or_untold(item, trace, f"{item.name} turns up here", untold)
        if source.id == here.id:
            return _told_or_untold(item, f"{item.mention} is gone", f"{item.name} is gone", untold)
        return Fact(trace=untold)

    def shut_way(self, start: L, end: L) -> Fact:
        if self._require_known_way(start, end).locked:
            raise Refusal(f"the way from {start.name} to {end.name} is already shut")
        here = self.current
        if here.id in (start.id, end.id):
            other = self._other_end(start, end)
            if not any(
                way.known and not way.locked and way.to_id != other.id
                for way in self.ways.get(here.id, ())
            ):
                raise Refusal("a shut never leaves the player's place with no open way out")
        self.set_locked(start.id, end.id, locked=True)
        return self._way_fact(start, end, "shuts")

    def open_way(self, start: L, end: L) -> Fact:
        way = self._require_known_way(start, end)
        if not way.locked:
            raise Refusal(f"the way from {start.name} to {end.name} is not locked")
        if not self.opens_offscreen(way):
            raise Refusal(f"the way from {start.name} to {end.name} does not open offscreen")
        self.set_locked(start.id, end.id, locked=False)
        return self._way_fact(start, end, "opens")

    def set_locked(self, start_id: Slug, end_id: Slug, *, locked: bool) -> None:
        for from_id, to_id in ((start_id, end_id), (end_id, start_id)):
            if (way := self.find_way(from_id, to_id)) is not None:
                way.locked = locked

    def fall(self, npc: P) -> Fact:
        self._refuse_party(npc)
        if npc.place_id == OFF_MAP_ID:
            raise Refusal(f"{npc.name} has left the map")
        if npc.place_id == self.current.id:
            raise Refusal(f"{npc.name} stands with the player; call kill for that")
        _ = self.die(npc)
        for item in self.carried(npc.id):
            item.holder_id = npc.place_id
        return Fact(trace=f"{npc.ref} dies at {self.require_place(npc.place_id).ref}")

    def _refuse_party(self, person: Person) -> None:
        if person.id == self.player.id or person.id in self.party_ids:
            raise Refusal(f"{person.name} travels with the player and never changes offscreen")

    def _item_place(self, item: I) -> L:
        if item.holder_id in self.places:
            return self.places[item.holder_id]
        holder = self.npcs.get(item.holder_id)
        if holder is None or holder.place_id == OFF_MAP_ID:
            raise Refusal(f"{item.name} is not on the map or travels with the player")
        self._refuse_party(holder)
        return self.require_place(holder.place_id)

    def _require_known_way(self, start: L, end: L) -> WayT:
        way = self.find_way(start.id, end.id)
        if way is None:
            raise Refusal(f"no way leads from {start.name} to {end.name}")
        if not way.known:
            raise Refusal(f"the player has not found the way from {start.name} to {end.name}")
        return way

    def _other_end(self, start: L, end: L) -> L:
        return end if start.id == self.current.id else start

    def _way_fact(self, start: L, end: L, verb: str) -> Fact:
        here = self.current
        if here.id not in (start.id, end.id):
            return Fact(trace=f"the way between {start.ref} and {end.ref} {verb}")
        other = self._other_end(start, end)
        name = other.name if other.known else "an unknown place"
        trace = f"the way from {here.mention} to {other.mention if other.known else name} {verb}"
        return here.fact(trace, card=f"The way to {name} {verb}")

    def kill(self, entity_id: Slug) -> list[Fact]:
        actor: P = (
            self.player if entity_id == self.player.id else self.require_person_here(entity_id)
        )
        card = self.die(actor)
        facts: list[Fact] = []
        dropped = list(self.carried(actor.id))
        for item in dropped:
            item.holder_id = self.current.id
            facts.append(item.fact(f"{item.mention} fell loose here"))
        if shown := [item.name for item in dropped if item.known]:
            card += f" — pack dropped: {', '.join(shown)}"
        facts.append(actor.fact(f"{actor.mention} is dead", card=card))
        return facts

    def apply_region(self, region: RegionProposal[P, I, L, WayT], way_model: type[WayT]) -> None:
        """No check runs here: every caller refuses first, so a refused region leaves it alone."""
        anchor_id = self.current.id
        self.places.update(region.places)
        # Copied: the anchor ways appended below must not land in the proposal's own lists.
        self.ways.update({key: [*ways] for key, ways in region.ways.items()})
        self.npcs.update(region.npcs)
        self.items.update(region.items)
        self.arc = "\n".join(part for part in (self.arc, region.arc) if part)
        self.regions.append(
            Region(start_id=region.start_id, name=region.region_name, place_ids=list(region.places))
        )
        self.ways.setdefault(anchor_id, []).append(way_model(to_id=region.start_id))
        self.ways.setdefault(region.start_id, []).append(way_model(to_id=anchor_id))

    def place_text(self) -> str:
        place = self.current
        return "\n".join(
            part for part in (place.ref, place.description, rows_text(place.rows())) if part
        )

    def carrying_lines(self) -> str:
        return lines_of(self.line(item) for item in self.carried(self.player.id))

    def line(self, entity: P | I) -> str:
        return entity.line(rows=self.sheet_rows()) if entity.id == self.player.id else entity.line()

    def others(self) -> Iterator[P]:
        return (
            npc for npc in self.at(self.current.id) if npc.known and npc.id not in self.party_ids
        )

    def place_lines(self, *, known: bool) -> str:
        return lines_of(
            self.line(entity)
            for entity in self.entities_at(self.current.id)
            if entity.known == known and entity.id not in self.party_ids
        )

    def ways_lines(self) -> str:
        return lines_of(
            f"- {self.require_place(way.to_id).ref} — {'known' if way.known else 'unknown'}"
            + ("; destination unknown to the player" if self.is_unexplored(way) else "")
            + way.lock_text()
            + self._leads_into(way)
            for way in self.ways.get(self.current.id, ())
        )

    def _leads_into(self, way: Way) -> str:
        region = self.require_region(way.to_id)
        return "" if region is self.current_region else f"; leads into {region.name}"

    def region_lines(self) -> str:
        visited_ids = {place.id for place in self.visited_places()}
        visited_regions = [
            region for region in self.regions if visited_ids.intersection(region.place_ids)
        ]
        if len(visited_regions) < 2:
            return ""
        lines = [f"the player is in {self.current_region.name}"]
        joined: set[frozenset[Slug]] = set()
        for region in visited_regions:
            for place_id in region.place_ids:
                for way in self.ways.get(place_id, ()):
                    other = self.require_region(way.to_id)
                    pair = frozenset((place_id, way.to_id))
                    if (
                        not way.known
                        or other is region
                        or not any(other is visited for visited in visited_regions)
                        or pair in joined
                    ):
                        continue
                    joined.add(pair)
                    lines.append(
                        f"- {region.name}: {self.require_place(place_id).ref} ⇄ "
                        f"{other.name}: {self.require_place(way.to_id).ref}"
                    )
        return "\n".join(lines)

    def elsewhere_lines(self) -> str:
        return lines_of(
            (
                f"at most {self.meanwhile_cap()} changes in one call",
                *(self._offscreen_line(place) for place in self.elsewhere()),
            )
        )

    def _offscreen_line(self, place: L) -> str:
        standing = ", ".join(
            entity.ref
            for entity in self.entities_at(place.id)
            if not isinstance(entity, Person) or entity.alive
        )
        ways = ", ".join(
            self.require_place(way.to_id).ref
            + (" (locked)" if way.locked else "")
            + ("" if way.known else " (unfound)")
            for way in self.ways.get(place.id, ())
        )
        way_to_player = self.find_way(place.id, self.current.id)
        nearby = (
            " (next to the player)"
            if way_to_player is not None and not way_to_player.locked
            else ""
        )
        return (
            f"- {place.ref}{nearby} — {standing or '(nobody, nothing)'}; ways: {ways or '(none)'}"
        )

    def elsewhere(self) -> list[L]:
        place_ids = dict.fromkeys(
            (*self.current_region.place_ids, *(place.id for place in self.visited_places()))
        )
        return [self.places[place_id] for place_id in place_ids if place_id != self.current.id]

    def can_move_offscreen(self) -> bool:
        here = self.current.id
        away = {place.id for place in self.elsewhere()}
        dwellers = [
            npc
            for npc in self.npcs.values()
            if npc.place_id in away and npc.id not in self.party_ids
        ]
        holders = away | {npc.id for npc in dwellers}
        return (
            any(npc.alive and not self.is_pinned(npc) for npc in dwellers)
            or any(item.holder_id in holders for item in self.items.values())
            or any(
                way.known
                and (way.to_id in away or (way.locked and way.to_id == here))
                and (not way.locked or self.opens_offscreen(way))
                for place_id in away
                for way in self.ways.get(place_id, ())
            )
        )

    def is_pinned(self, npc: P) -> bool:  # noqa: ARG002
        return False

    def opens_offscreen(self, way: WayT) -> bool:  # noqa: ARG002
        return True

    def visited_places(self) -> list[L]:
        seen: dict[Slug, L] = {}
        for place_id in self.visited_place_ids:
            seen.setdefault(place_id, self.require_place(place_id))
        return list(seen.values())

    def map_so_far(self) -> str:
        lines: list[str] = []
        for place in self.visited_places():
            known_ways = ", ".join(
                self.require_place(way.to_id).name
                for way in self.ways.get(place.id, ())
                if way.known
            )
            here = ", ".join(
                f"{entity.ref} ({entity.met_label})" for entity in self.entities_at(place.id)
            )
            lines.append(
                f"{place.ref} — {place.description}\n  known ways out: {known_ways or '(none)'}"
                f"\n  here: {here or '(nobody, nothing)'}"
            )
        lines.append("ids in use: " + ", ".join(sorted((*self.places, *self.npcs, *self.items))))
        return "\n".join(lines)


def _told_or_untold(subject: Entity, trace: str, card: str, untold: str) -> Fact:
    return subject.fact(trace, card=card) if subject.known else Fact(trace=untold)


def _end_phrase(place: Place, way: Way | None, joint: str) -> str:
    return f"{joint}{place.mention}" if place.known and way is not None and way.known else ""
