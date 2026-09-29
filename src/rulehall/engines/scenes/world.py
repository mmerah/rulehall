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
    slug,
)
from rulehall.engines.sheet import PLAYER_ID, Entity, Person
from rulehall.engines.world import IS_DEAD, UNKNOWN_ID, OpeningProposal, World, check_filing

SETTLED_SHOWN = 12
ARC_DESCRIPTION = (
    "The long game that spans the scenes: pressure, intent and what can come later. Never "
    "restate or change what happened, and never what is true in this scene now. The player "
    "never reads it."
)
FILED = (
    "{name}[{entity_id}] is new to the cast, which also holds: {others}. Use one of those ids "
    "when you mean them"
)


class Settled(Frozen):
    question: str
    answer: str

    def line(self) -> str:
        return f"{self.question} — {self.answer}"


class Scene(Mutable):
    place_id: Slug
    location: str = Field(min_length=1)
    title: str
    situation: str = Field(min_length=1)
    here_ids: list[Slug] = Field(default_factory=list)
    settled: list[Settled] = Field(default_factory=list)


class SceneProposal[P: Person](Frozen, OpeningProposal):
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
    present_ids: tuple[str, ...] = Field(
        default=(), description="Ids of who and what is in the scene now."
    )
    hidden_ids: tuple[str, ...] = Field(default=(), description="Ids of what is hidden here.")
    cast: dict[Slug, P] = Field(
        default_factory=dict,
        description="New people and things. The engine files each entry under an id made from "
        "its name. The player reads a brief and a sheet after they meet that entry. Name "
        "nothing still hidden in either one.",
    )
    arc: str = Field(default="", description=ARC_DESCRIPTION)

    def premise(self) -> str:
        return self.situation

    def cast_with_hidden_unmet(self) -> dict[Slug, P]:
        return {
            entity_id: entry.model_copy(
                update={"known": False} if entity_id in self.hidden_ids else {}, deep=True
            )
            for entity_id, entry in self.cast.items()
        }

    def filed_by_name(self) -> Self:
        filed: dict[Slug, P] = {}
        renamed: dict[str, Slug] = {}
        for key, entry in self.cast.items():
            entity_id = PLAYER_ID if key == PLAYER_ID else slug(entry.name, {PLAYER_ID, *filed})
            renamed[key] = entity_id
            filed[entity_id] = entry.model_copy(update={"id": entity_id})
        return self.model_copy(
            update={
                "cast": filed,
                "present_ids": tuple(renamed.get(name, name) for name in self.present_ids),
                "hidden_ids": tuple(renamed.get(name, name) for name in self.hidden_ids),
            }
        )


class NextProposal[P: Person](SceneProposal[P]):
    recap: str = Field(
        min_length=1,
        description="One paragraph on the scene the player leaves: what the player did, paid "
        "and learned. The narrator reads it. Name nothing hidden.",
    )
    arc: str = Field(
        default="",
        description=f"{ARC_DESCRIPTION} Revise it only where what happened makes a change "
        "necessary, else leave it empty.",
    )


class SceneWorld[P: Person](World[P]):
    scenes: list[Scene] = Field(min_length=1)
    cast: dict[Slug, P] = Field(default_factory=dict)
    arc: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_filing(self.cast)
        if self.player.id in self.cast:
            raise ValueError("the player is in the cast")
        # Ahead of `check_named`, whose generic "not in the cast" message would win instead.
        if self.player.id in self.scene.here_ids:
            raise ValueError("the player is in every scene and is never listed in it")
        check_named(self.scene.here_ids, self.cast)
        if left := sorted(set(self.party_ids) - set(self.scene.here_ids)):
            raise ValueError(f"the party is in every scene; {left} are not in this one")
        return self

    @classmethod
    def opening(cls, proposal: SceneProposal[P], player: P) -> Self:
        cast, scene = built_scene(
            proposal, player, proposal.cast_with_hidden_unmet(), (), proposal.location
        )
        world = parse(cls, {"player": player, "cast": cast, "scenes": [scene], "arc": proposal.arc})
        world.apply_proposal_extras(proposal)
        return world

    @property
    def scene(self) -> Scene:
        return self.scenes[-1]

    def present(self) -> list[Slug]:
        return [entity_id for entity_id in self.scene.here_ids if self.cast[entity_id].known]

    def hidden(self) -> list[Slug]:
        return [entity_id for entity_id in self.scene.here_ids if not self.cast[entity_id].known]

    def last_seen(self, entity_id: Slug) -> str:
        for scene in reversed(self.scenes):
            if entity_id in scene.here_ids:
                return f"last seen in: {scene.title}"
        return ""

    @property
    def roster(self) -> Mapping[Slug, P]:
        return self.cast

    def find_entity_id(self, wanted: str) -> Slug | None:
        return find_cast_id(wanted, {self.player.id: self.player, **self.cast})

    def require_entity(self, entity_id: Slug) -> P:
        found_id = self.find_entity_id(entity_id)
        if found_id is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        return self.player if found_id == self.player.id else self.cast[found_id]

    def require_here(self, entity_id: Slug) -> P:
        entity = self.require_entity(entity_id)
        if entity.id == self.player.id:
            return entity
        if entity.id not in self.scene.here_ids or not entity.known:
            raise Refusal(
                f"{entity.name} is not here with the player; bring them here first, or act on "
                "who is here"
            )
        return entity

    def require_living_here(self, entity_id: Slug) -> P:
        entity = self.require_here(entity_id)
        if not entity.alive:
            raise Refusal(IS_DEAD.format(name=entity.name))
        return entity

    def here(self) -> Iterator[P]:
        yield self.player
        for entity_id in self.present():
            yield self.cast[entity_id]

    def require_person_here(self, entity_id: Slug) -> P:
        if entity_id == self.player.id:
            raise Refusal("the player is not a party member")
        return self.require_living_here(entity_id)

    def others(self) -> Iterator[P]:
        return (
            self.cast[entity_id] for entity_id in self.present() if entity_id not in self.party_ids
        )

    def here_lines(self) -> str:
        return lines_of(other.line() for other in self.others())

    def hidden_lines(self) -> str:
        return "\n".join(self.require_entity(entity_id).line() for entity_id in self.hidden())

    def scene_lines(self) -> str:
        scene = self.scene
        present = ", ".join(self.cast[entity_id].ref for entity_id in self.present())
        hidden = ", ".join(self.cast[entity_id].ref for entity_id in self.hidden())
        return (
            f"{scene.title} [{scene.place_id}]\nlocation: {scene.location}\n{scene.situation}"
            f"\npresent: {present or '(nobody)'}" + (f"\nhidden: {hidden}" if hidden else "")
        )

    def player_line(self) -> str:
        return self.player.line(rows=self.sheet_rows())

    def cast_lines(self) -> str:
        lines = [self.player_line()]
        for entry in self.cast.values():
            where = (
                "travels with the player"
                if entry.id in self.party_ids
                else self.last_seen(entry.id)
            )
            lines.append(
                entry.line(detail=f"{entry.met_label}; {where}" if where else entry.met_label)
            )
        return "\n".join(lines)

    def settle(self, question: str, answer: str) -> None:
        self.scene.settled.append(Settled(question=question, answer=answer))

    def settled_lines(self) -> str:
        shown = self.scene.settled[-SETTLED_SHOWN:]
        start = len(self.scene.settled) - len(shown) + 1
        return "\n".join(
            f"{number}. {entry.line()}" for number, entry in enumerate(shown, start=start)
        )

    def reveal_hidden(self, entity_id: Slug) -> list[Fact]:
        entity = self.require_entity(entity_id)
        if entity.id not in self.scene.here_ids or entity.known:
            raise Refusal(f"{entity_id!r} is not hidden here")
        return entity.reveal(card=sentence(f"{entity.name} discovered"))

    def enter(self, entity_id: Slug) -> list[Fact]:
        if entity_id == self.player.id:
            raise Refusal("the player is in every scene; move the story on instead")
        known_id = find_cast_id(entity_id, self.cast)
        if known_id is None:
            return [self.file_stranger(entity_id), *self.enter(entity_id)]
        entity = self.cast[known_id]
        if entity.id in self.scene.here_ids:
            if not entity.known:
                raise Refusal(f"{entity.name} is hidden here: `reveal` them")
            return []
        if not entity.alive:
            raise Refusal(IS_DEAD.format(name=entity.name))
        self.scene.here_ids.append(entity.id)
        trace = f"{entity.mention} arrives"
        return [
            *entity.reveal(),
            entity.fact(trace, card=f"{entity.name} arrives"),
        ]

    def leave(self, entity_id: Slug) -> list[Fact]:
        if entity_id == self.player.id:
            raise Refusal("the player is in every scene; move the story on instead")
        if entity_id not in self.cast or not self.cast[entity_id].alive:
            return []
        entity = self.require_living_here(entity_id)
        if entity.id in self.party_ids:
            raise Refusal(f"{entity.name} travels with the player and leaves through `leave_party`")
        self.scene.here_ids.remove(entity.id)
        card = f"{entity.name} leaves"
        return [entity.fact(f"{entity.mention} leaves", card=card)]

    def kill(self, entity_id: Slug) -> list[Fact]:
        entity = self.require_here(entity_id)
        return [entity.fact(f"{entity.mention} is dead", card=self.die(entity))]

    def file_stranger(self, entity_id: Slug) -> Fact:
        name = stranger_name(entity_id)
        self.refuse_unmet_names(name)
        others = ", ".join(entry.ref for entry in self.cast.values() if entry.alive)
        brief = f"met at {self.scene.title}"
        self.cast[entity_id] = type(self.player)(id=entity_id, name=name, brief=brief)
        return Fact(trace=FILED.format(name=name, entity_id=entity_id, others=others or "(no one)"))

    def merged_cast(self, cast: Mapping[Slug, P]) -> dict[Slug, P]:
        return {
            **self.cast,
            **{
                entity_id: filed.model_copy(update={"brief": entry.brief})
                if (filed := self.cast.get(entity_id)) is not None
                else entry
                for entity_id, entry in cast.items()
            },
        }

    def apply_scene(self, proposal: SceneProposal[P]) -> None:
        self.cast, scene = built_scene(
            proposal,
            self.player,
            self.merged_cast(proposal.cast_with_hidden_unmet()),
            self.party_ids,
            proposal.location or self.scene.location,
        )
        self.arc = proposal.arc or self.arc
        self.scenes.append(scene)
        self.apply_proposal_extras(proposal)


def built_scene[P: Person](
    proposal: SceneProposal[P],
    player: Person,
    cast: dict[Slug, P],
    party_ids: Sequence[Slug],
    location: str,
) -> tuple[dict[Slug, P], Scene]:
    everyone: Mapping[Slug, Entity] = {player.id: player, **cast}
    placed = {player.id, *party_ids}
    present = [
        who
        for who in require_resolved_ids(proposal.present_ids, everyone, "present")
        if who not in placed
    ]
    hidden = [
        who
        for who in require_resolved_ids(proposal.hidden_ids, everyone, "hidden")
        if who not in placed
    ]
    for entity_id in present:
        cast[entity_id].known = True
    scene = Scene(
        place_id=proposal.place_id,
        location=location,
        title=proposal.title,
        situation=proposal.situation,
        here_ids=[*party_ids, *present, *hidden],
    )
    return cast, scene


def stranger_name(entity_id: Slug) -> str:
    return entity_id.replace("-", " ").title()


def check_named(here: Sequence[Slug], cast: Mapping[Slug, Entity]) -> None:
    check_unique("ids in the scene", here)
    for who in here:
        if who not in cast:
            raise ValueError(f"scene names {who!r}, who is not in the cast")


def find_cast_id(wanted: str, cast: Mapping[Slug, Entity]) -> Slug | None:
    if wanted in cast:
        return wanted
    named = [entry.id for entry in cast.values() if entry.name.casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    tokened = [key for key in cast if f"-{wanted}-" in f"-{key}-"]
    return tokened[0] if len(tokened) == 1 else None


def require_resolved_ids(
    wanted: Iterable[str], cast: Mapping[Slug, Entity], where: str
) -> list[Slug]:
    found: list[Slug] = []
    for name in wanted:
        matched = find_cast_id(name, cast)
        if matched is None:
            raise Refusal(f"the scene lists {name!r} as {where}, and no such id or name exists")
        if matched not in found:
            found.append(matched)
    return found
