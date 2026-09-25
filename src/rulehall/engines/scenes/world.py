from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.prompt import lines_of, sentence
from rulehall.core.validation import (
    Frozen,
    Mutable,
    Refusal,
    Slug,
    check_unique,
    parse,
)
from rulehall.engines.entities import (
    IS_DEAD,
    UNKNOWN_ID,
    OpeningProposal,
    Person,
    Thing,
    World,
    check_filing,
)

WAY_OFFERED = Fact(
    trace=(
        "this scene offers a way on. Ask the player what they want to pursue next. Ask in "
        "the fiction, and name what the scene left open. Never ask with a list of choices. The "
        "player can also stay and keep playing here, so ask; do not push the player out"
    ),
    told=True,
)


class Scene(Mutable):
    # Names the art cache entry, so returning to a place reuses its picture.
    place_id: Slug
    location: str = Field(min_length=1)
    title: str
    situation: str = Field(min_length=1)
    here: list[Slug] = Field(default_factory=list)
    way_offered: bool = False


class SceneProposal[C: Person](Frozen, OpeningProposal):
    place_id: Slug = Field(
        description="Slug naming the place. Reuse it when the player returns here."
    )
    location: str = Field(
        default="",
        description="The wider location of the scene: a station, a ship, a town or a wild "
        "region, not a room or a spot in it. Many scenes share one location. Leave it empty "
        "when the scene is in the location of THE SCENE NOW. Write a name only when the player "
        "arrives in a different location. Use the same name again when the player returns to "
        "a location.",
    )
    title: str = Field(description="The scene's title, read by the player. Name nothing hidden.")
    situation: str = Field(
        min_length=1,
        description="The place as it stands: what the player sees, hears and smells here, and "
        "what the place offers or blocks. Describe the place. Never narrate an action, and "
        "never tell what the player does. Hold nothing hidden here.",
    )
    present: tuple[str, ...] = Field(
        default=(), description="Ids of who and what is in the scene now."
    )
    hidden: tuple[str, ...] = Field(default=(), description="Ids of what is hidden here.")
    cast: dict[Slug, C] = Field(
        default_factory=dict,
        description="New people and things, each filed under its own id. The player reads a "
        "brief and a sheet after they meet that entry. Name nothing still hidden in either one.",
    )
    arc: str = Field(
        default="",
        description="The long game that spans the scenes: pressures, motives, secrets, and what "
        "can come later. Never what is true in this scene now. The player never reads it. Put "
        "here what ties one hidden thing to another.",
    )

    def premise(self) -> str:
        return self.situation


class NextProposal[C: Person](SceneProposal[C]):
    recap: str = Field(
        min_length=1,
        description="One paragraph on the scene the player leaves: what the player did, paid "
        "and learned. The narrator reads it. Name nothing hidden.",
    )


class SceneWorld[C: Person](World[C]):
    meanwhile_every = 6

    scenes: list[Scene] = Field(min_length=1)
    cast: dict[Slug, C] = Field(default_factory=dict)
    arc: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_filing(self.cast)
        if self.player.id in self.cast:
            raise ValueError("the player is in the cast")
        # Ahead of `check_named`, whose generic "not in the cast" message would win instead.
        if self.player.id in self.scene.here:
            raise ValueError("the player is in every scene and is never listed in it")
        check_named(self.scene.here, self.cast)
        if left := sorted(set(self.party) - set(self.scene.here)):
            raise ValueError(f"the party is in every scene; {left} are not in this one")
        return self

    @classmethod
    def opening(cls, proposal: SceneProposal[C], player: C) -> Self:
        """The player is added by code and never authored, so no scenario can claim their id."""
        cast, scene = settled(proposal, player, dict(proposal.cast), (), proposal.location)
        return parse(cls, {"player": player, "cast": cast, "scenes": [scene], "arc": proposal.arc})

    @property
    def scene(self) -> Scene:
        return self.scenes[-1]

    def present(self) -> list[Slug]:
        return [entity_id for entity_id in self.scene.here if self.cast[entity_id].known]

    def hidden(self) -> list[Slug]:
        return [entity_id for entity_id in self.scene.here if not self.cast[entity_id].known]

    def last_seen(self, entity_id: Slug) -> str:
        """Scans every scene, so an entity the story dropped is still placed."""
        for scene in reversed(self.scenes):
            if entity_id in scene.here:
                return f"last seen in: {scene.title}"
        return ""

    def party_members(self) -> list[C]:
        return [self.cast[member_id] for member_id in self.party]

    def person_of(self, person_id: Slug) -> C | None:
        return self.cast.get(person_id)

    def require(self, entity_id: Slug) -> C:
        if entity_id == self.player.id:
            return self.player
        entity = self.cast.get(entity_id)
        if entity is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        return entity

    def require_here(self, entity_id: Slug) -> C:
        entity = self.require(entity_id)
        if entity.id == self.player.id:
            return entity
        if entity.id not in self.scene.here or not entity.known:
            raise Refusal(
                f"{entity.name} is not here with the player. "
                "Bring them here first, or act on who is here."
            )
        return entity

    def require_living_here(self, entity_id: Slug) -> C:
        entity = self.require_here(entity_id)
        if not entity.alive:
            raise Refusal(IS_DEAD.format(name=entity.name))
        return entity

    def here(self) -> Iterator[C]:
        yield self.player
        for entity_id in self.present():
            yield self.cast[entity_id]

    def require_person_here(self, entity_id: Slug) -> C:
        if entity_id == self.player.id:
            raise Refusal("the player is not a party member")
        return self.require_living_here(entity_id)

    def unmet(self) -> Iterable[C]:
        """The whole cast, not this scene's hidden list: a sheet row outlives its scene."""
        return (entry for entry in self.cast.values() if not entry.known)

    def others(self) -> Iterator[C]:
        return (self.cast[entity_id] for entity_id in self.present() if entity_id not in self.party)

    def here_lines(self) -> str:
        return lines_of(other.line() for other in self.others())

    def hidden_lines(self) -> str:
        return lines_of(self.require(entity_id).line() for entity_id in self.hidden())

    def scene_lines(self) -> str:
        scene = self.scene
        present = ", ".join(self.cast[entity_id].tag for entity_id in self.present())
        hidden = ", ".join(self.cast[entity_id].tag for entity_id in self.hidden())
        return (
            f"{scene.title} [{scene.place_id}]\nlocation: {scene.location}\n{scene.situation}\n"
            f"present: {present or '(nobody)'}\nhidden: {hidden or '(nothing)'}"
        )

    def player_line(self) -> str:
        return self.player.line(rows=self.sheet_rows())

    def cast_lines(self) -> str:
        lines = [self.player_line()]
        for entry in self.cast.values():
            where = (
                "travels with the player" if entry.id in self.party else self.last_seen(entry.id)
            )
            lines.append(
                entry.line(detail=f"{entry.met_label}; {where}" if where else entry.met_label)
            )
        return "\n".join(lines)

    def reveal_hidden(self, entity_id: Slug) -> list[Fact]:
        entity = self.require(entity_id)
        if entity_id not in self.scene.here or entity.known:
            raise Refusal(f"{entity_id!r} is not hidden here")
        return entity.reveal(card=sentence(f"{entity.name} discovered"))

    def enter(self, entity_id: Slug) -> list[Fact]:
        if entity_id == self.player.id:
            raise Refusal("the player is in every scene; move the story on instead")
        entity = self.require(entity_id)
        if entity.id in self.scene.here:
            raise Refusal(f"{entity.name} is already here")
        if not entity.alive:
            raise Refusal(IS_DEAD.format(name=entity.name))
        self.scene.here.append(entity.id)
        trace = f"{entity.mention} arrives"
        return [
            *entity.reveal(),
            entity.fact(trace, card=f"{entity.name} arrives"),
        ]

    def leave(self, entity_id: Slug) -> list[Fact]:
        if entity_id == self.player.id:
            raise Refusal("the player is in every scene; move the story on instead")
        entity = self.require_living_here(entity_id)
        if entity.id in self.party:
            raise Refusal(f"{entity.name} travels with the player and leaves through `leave_party`")
        self.scene.here.remove(entity.id)
        card = f"{entity.name} leaves"
        return [entity.fact(f"{entity.mention} leaves", card=card)]

    def kill(self, entity_id: Slug) -> list[Fact]:
        entity = self.require_here(entity_id)
        return [entity.fact(f"{entity.mention} is dead", card=self.die(entity))]

    def offer_way_on(self) -> list[Fact]:
        if self.scene.way_offered:
            raise Refusal("this scene already offers the way on; play on, or send them off")
        self.scene.way_offered = True
        return [WAY_OFFERED]

    def merged_cast(self, cast: Mapping[Slug, C]) -> dict[Slug, C]:
        return {
            **self.cast,
            **{
                entity_id: filed.model_copy(update={"brief": entry.brief})
                if (filed := self.cast.get(entity_id)) is not None
                else entry
                for entity_id, entry in cast.items()
            },
        }

    def apply_scene(self, proposal: SceneProposal[C]) -> None:
        self.cast, scene = settled(
            proposal,
            self.player,
            self.merged_cast(proposal.cast),
            self.party,
            proposal.location or self.scene.location,
        )
        self.arc = proposal.arc or self.arc
        self.scenes.append(scene)


def settled[C: Person](
    proposal: SceneProposal[C],
    player: Person,
    cast: dict[Slug, C],
    party: Sequence[Slug],
    location: str,
) -> tuple[dict[Slug, C], Scene]:
    """The world may not exist yet, so this takes the cast and the party as arguments."""
    everyone: Mapping[Slug, Thing] = {player.id: player, **cast}
    present = resolved_ids(proposal.present, everyone, "present")
    hidden = resolved_ids(proposal.hidden, everyone, "hidden")
    for entity_id in present:
        cast[entity_id].known = True
    scene = Scene(
        place_id=proposal.place_id,
        location=location,
        title=proposal.title,
        situation=proposal.situation,
        here=[*party, *present, *hidden],
    )
    return cast, scene


def check_named(here: Sequence[Slug], cast: Mapping[Slug, Thing]) -> None:
    check_unique("ids in the scene", here)
    for who in here:
        if who not in cast:
            raise ValueError(f"scene names {who!r}, who is not in the cast")


def resolved_id(wanted: str, cast: Mapping[Slug, Thing]) -> Slug | None:
    """Ids are the worldsmith's failure mode: an unknown one matches a cast name before refusal."""
    if wanted in cast:
        return wanted
    matches = [entry.id for entry in cast.values() if entry.name.casefold() == wanted.casefold()]
    return matches[0] if len(matches) == 1 else None


def resolved_ids(wanted: Iterable[str], cast: Mapping[Slug, Thing], where: str) -> list[Slug]:
    found: list[Slug] = []
    for name in wanted:
        matched = resolved_id(name, cast)
        if matched is None:
            raise Refusal(f"the scene lists {name!r} as {where}, and no such id or name exists")
        if matched not in found:
            found.append(matched)
    return found
