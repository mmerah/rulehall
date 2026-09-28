from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import ClassVar, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.prompt import lines_of
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique, parse
from rulehall.engines.sheet import PLAYER_ID, Entity, Person
from rulehall.engines.world import IS_DEAD, UNKNOWN_ID, OpeningProposal, World, check_filing


class Dweller(Person):
    place_id: Slug


class Item(Entity):
    holder_id: Slug


class Place(Entity):
    description: str = Field(min_length=1)


class Way(Mutable):
    """One way out, in one direction, from the place it is filed under."""

    to_id: Slug
    known: bool = False
    locked: bool = False


class RoomMap[P: Dweller](Mutable):
    places: dict[Slug, Place] = Field(default_factory=dict)
    ways: dict[Slug, list[Way]] = Field(default_factory=dict)
    npcs: dict[Slug, P] = Field(default_factory=dict)
    items: dict[Slug, Item] = Field(default_factory=dict)
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
            "ids across places, npcs and items", (*self.places, *self.npcs, *self.items, PLAYER_ID)
        )
        for npc in self.npcs.values():
            if npc.place_id not in self.places:
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

    def find_entity(self, entity_id: Slug) -> Person | Item | Place | None:
        return self.places.get(entity_id) or self.npcs.get(entity_id) or self.items.get(entity_id)

    def require(self, entity_id: Slug) -> Person | Item | Place:
        entity = self.find_entity(entity_id)
        if entity is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        return entity

    def require_place(self, entity_id: Slug) -> Place:
        entity = self.require(entity_id)
        if not isinstance(entity, Place):
            raise Refusal(f"{entity_id!r} is not a place")
        return entity

    def find_way(self, from_id: Slug, to_id: Slug) -> Way | None:
        return next((way for way in self.ways.get(from_id, ()) if way.to_id == to_id), None)

    def at(self, place_id: Slug) -> Iterator[P]:
        return (npc for npc in self.npcs.values() if npc.place_id == place_id)

    def carried(self, holder_id: Slug) -> Iterator[Item]:
        return (item for item in self.items.values() if item.holder_id == holder_id)

    def entities_at(self, place_id: Slug) -> Iterator[P | Item]:
        npcs = list(self.at(place_id))
        yield from npcs
        for holder in (place_id, *(npc.id for npc in npcs)):
            yield from self.carried(holder)

    def reachable(
        self,
        start_id: Slug,
        *,
        past_locks: bool = False,
        cut: Collection[tuple[Slug, Slug]] = (),
    ) -> set[Slug]:
        blocked = {*cut, *((to_id, from_id) for from_id, to_id in cut)}
        reached = {start_id}
        pending = [start_id]
        while pending:
            current = pending.pop()
            for way in self.ways.get(current, ()):
                if (
                    way.to_id in reached
                    or (way.locked and not past_locks)
                    or (current, way.to_id) in blocked
                ):
                    continue
                reached.add(way.to_id)
                pending.append(way.to_id)
        return reached

    def add_way(self, from_id: Slug, to_id: Slug, *, known: bool) -> None:
        self.ways.setdefault(from_id, []).append(Way(to_id=to_id, known=known))


class MapProposal[P: Dweller](RoomMap[P], OpeningProposal):
    start_id: Slug = Field(description="Exact id of the place this map starts from.")

    def premise(self) -> str:
        start = self.places.get(self.start_id)
        return "" if start is None else start.description


class RegionProposal[P: Dweller](MapProposal[P]):
    recap: str = Field(
        min_length=1,
        description="One paragraph on the part of the map the player leaves behind: what the "
        "player did there, paid and learned. The narrator reads it. Name nothing hidden.",
    )


class RoomWorld[P: Dweller](RoomMap[P], World[P]):
    meanwhile_every: ClassVar[int]

    visited_place_ids: list[Slug] = Field(min_length=1)
    turns_since_meanwhile: int = Field(default=0, ge=0)
    meanwhile_due: bool = False

    @model_validator(mode="after")
    def _playable(self) -> Self:
        for place_id in self.visited_place_ids:
            self.require_place(place_id)
        for member_id in self.party_ids:
            npc = self.npcs[member_id]
            if npc.place_id != self.current.id:
                raise ValueError(f"{member_id!r} travels with the player but is not at their place")
        return self

    @classmethod
    def opening(
        cls, proposal: MapProposal[P], player: P, items: Iterable[Item], **extra_fields: object
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
                **extra_fields,
            },
        )

    @property
    def current(self) -> Place:
        return self.places[self.visited_place_ids[-1]]

    def frontier(self) -> int:
        return sum(
            not self.require_place(place_id).known for place_id in self.reachable(self.current.id)
        )

    def find_entity(self, entity_id: Slug) -> Person | Item | Place | None:
        return self.player if entity_id == self.player.id else super().find_entity(entity_id)

    @property
    def roster(self) -> Mapping[Slug, P]:
        return self.npcs

    def here(self) -> Iterator[P]:
        yield self.player
        yield from self.at(self.current.id)

    def holders_here(self) -> set[Slug]:
        return {self.current.id, *(entity.id for entity in self.here())}

    def require_dweller(self, entity_id: Slug) -> P:
        npc = self.npcs.get(entity_id)
        if npc is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        if not npc.alive:
            raise Refusal(IS_DEAD.format(name=npc.name))
        return npc

    def require_item(self, item_id: Slug) -> Item:
        item = self.items.get(item_id)
        if item is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=item_id))
        return item

    def require_person_here(self, entity_id: Slug) -> P:
        npc = self.require_dweller(entity_id)
        if npc.place_id != self.current.id or not npc.known:
            raise Refusal(f"{npc.name} is not here with the player")
        return npc

    def require_item_here(self, item_id: Slug) -> Item:
        item = self.require(item_id)
        if not isinstance(item, Item):
            raise Refusal(f"{item_id!r} is not an item")
        if item.holder_id not in self.holders_here():
            raise Refusal(f"{item.name} is not here with the player")
        return item

    def carried_items(self, holder: Person, item_ids: tuple[Slug, ...]) -> tuple[Item, ...]:
        check_unique("items", item_ids)
        items: list[Item] = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item is None or item.holder_id != holder.id or not item.known:
                raise Refusal(f"{item_id!r} is not in {holder.name}'s hands")
            items.append(item)
        return tuple(items)

    def count_turn(self) -> None:
        armed = self.meanwhile_due
        if not armed and not self.can_move_offscreen():
            return
        self.turns_since_meanwhile += 1
        fired = self.turns_since_meanwhile >= self.meanwhile_every
        if fired:
            self.turns_since_meanwhile = 0
        self.meanwhile_due = fired and not armed

    def _open_way(self, way: Way, destination: Place) -> None:
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
        self._open_way(way, destination)
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
        way.locked = False
        self._open_way(way, destination)
        if (back := self.find_way(destination.id, here.id)) is not None:
            back.locked = False
        trace = f"the way from {here.mention} to {destination.mention} is unlocked"
        card = f"{destination.name} unlocked"
        return [here.fact(trace, card=card)]

    def reveal_hidden(self, entity_id: Slug) -> list[Fact]:
        entity = self.require(entity_id)
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
        holder = self.require(holder_id)
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

    def require_offscreen_place(self, place_id: Slug) -> Place:
        away = self.elsewhere()
        found = next((place for place in away if place.id == place_id), None)
        if found is None:
            options = ", ".join(place.name for place in away) or "(none)"
            raise Refusal(f"{place_id!r} is not a place the player has walked away from: {options}")
        return found

    def walk_offscreen(self, npc: P, place: Place) -> Fact:
        if npc.place_id == self.current.id:
            raise Refusal(f"{npc.name} stands with the player; that is not offscreen")
        walked = self.find_way(npc.place_id, place.id)
        if walked is None or walked.locked:
            origin = self.require_place(npc.place_id).name
            raise Refusal(f"no unlocked way leads from {origin} to {place.name}")
        npc.place_id = place.id
        return Fact(trace=f"{npc.name} walks to {place.name}")

    def drift_item(self, item: Item, place: Place) -> Fact:
        if item.holder_id in self.holders_here():
            raise Refusal(f"{item.name} is here with the player")
        if item.holder_id == place.id:
            raise Refusal(f"{item.name} is already there")
        item.holder_id = place.id
        return Fact(trace=f"{item.name} moves to {place.name}")

    def shut_way(self, start: Place, end: Place) -> Fact:
        if self.current.id in (start.id, end.id):
            raise Refusal("a way at the player's place cannot shut offscreen")
        shut = self.find_way(start.id, end.id)
        if shut is None:
            raise Refusal(f"no way leads from {start.name} to {end.name}")
        if shut.locked:
            raise Refusal(f"the way from {start.name} to {end.name} is already shut")
        if not shut.known:
            raise Refusal(f"the player has not found the way from {start.name} to {end.name}")
        shut.locked = True
        if (back := self.find_way(end.id, start.id)) is not None:
            back.locked = True
        return Fact(trace=f"the way from {start.name} to {end.name} shuts")

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

    def attach(self, region: RoomMap[P], start_id: Slug) -> None:
        """No check runs here: every caller refuses first, so a refused region leaves it alone."""
        anchor_id = self.current.id
        self.places.update(region.places)
        # Copied: the anchor ways appended below must not land in the proposal's own lists.
        self.ways.update({key: [*ways] for key, ways in region.ways.items()})
        self.npcs.update(region.npcs)
        self.items.update(region.items)
        self.arc = "\n".join(part for part in (self.arc, region.arc) if part)
        self.add_way(anchor_id, start_id, known=False)
        self.add_way(start_id, anchor_id, known=False)

    def line(self, entity: P | Item) -> str:
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
            f"- {self.require_place(way.to_id).tag} — "
            + ("known" if way.known else "unknown")
            + ("; locked" if way.locked else "")
            for way in self.ways.get(self.current.id, ())
        )

    def elsewhere_lines(self) -> str:
        return lines_of(self._offscreen_line(place) for place in self.elsewhere())

    def _offscreen_line(self, place: Place) -> str:
        standing = ", ".join(
            entity.tag
            for entity in self.entities_at(place.id)
            if not isinstance(entity, Person) or entity.alive
        )
        ways = ", ".join(
            f"{self.require_place(way.to_id).tag}{'' if way.known else ' (unfound)'}"
            for way in self.ways.get(place.id, ())
            if not way.locked
        )
        return f"- {place.tag} — {standing or '(nobody, nothing)'}; ways: {ways or '(none)'}"

    def elsewhere(self) -> list[Place]:
        return [place for place in self.visited_places() if place.id != self.current.id]

    def can_move_offscreen(self) -> bool:
        here = self.current.id
        away = {place.id for place in self.elsewhere()}
        if not away:
            return False
        offscreen = {npc.id for npc in self.npcs.values() if npc.place_id in away}
        if any(
            item.holder_id in away or item.holder_id in offscreen for item in self.items.values()
        ):
            return True
        walkers = {npc.place_id for npc in self.npcs.values() if npc.alive and npc.place_id in away}
        return any(
            (way.to_id in away and place_id in walkers) or (way.known and way.to_id != here)
            for place_id in away
            for way in self.ways.get(place_id, ())
            if not way.locked
        )

    def visited_places(self) -> list[Place]:
        seen: dict[Slug, Place] = {}
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
                f"{entity.tag} ({entity.met_label})" for entity in self.entities_at(place.id)
            )
            lines.append(
                f"{place.tag} — {place.description}\n  known ways out: {known_ways or '(none)'}"
                f"\n  here: {here or '(nobody, nothing)'}"
            )
        lines.append("ids in use: " + ", ".join(sorted((*self.places, *self.npcs, *self.items))))
        return "\n".join(lines)
