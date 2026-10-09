from collections.abc import Collection
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.validation import Frozen, Mutable, Slug
from rulehall.engines.pokemon.battle.models import LEVEL_MAX, TEAM_MAX
from rulehall.engines.pokemon.journey.rules import BOSS_RISE, LEGENDARY_AT, RosterSlot, rescaled
from rulehall.engines.pokemon.journey.sheet import JourneyTrainer

type SchemeDue = Literal["operation", "lair"]
type Outcome = Literal["foiled", "succeeded"]

SCHEME_STAGES = 4
BADGES_PER_OPERATION = 2


class Stage(Frozen):
    foiled: str = Field(
        min_length=1, description="What the player learns when this operation is foiled."
    )
    succeeded: str = Field(
        min_length=1, description="What the player learns when this operation succeeds."
    )

    def text_for(self, outcome: Outcome) -> str:
        return self.foiled if outcome == "foiled" else self.succeeded


class Scheme(Frozen):
    name: str = Field(min_length=1, description="The evil team's name, such as 'Team Tide'.")
    goal: str = Field(min_length=1, description="What the team's boss wants in the end.")
    stages: tuple[Stage, Stage, Stage, Stage] = Field(
        description="The four operations in order, each with what the player learns of the "
        "scheme as it ends: one text for when it is foiled, one for when it succeeds."
    )
    legendary_id: Slug | None = Field(
        default=None,
        description="A legendary species id from SPECIES that the team is after: it joins the "
        "boss's team when three operations succeed. Null for none.",
    )


class Operation(Frozen):
    place_id: Slug = Field(
        description="Exact id of the place of this map where the team works. The map's start "
        "reaches it without a lock."
    )
    leader_id: Slug = Field(
        description="Exact id of its leader: a person of this map with a roster and no badge, or "
        "an earlier leader that THE SCHEME names."
    )
    goal: str = Field(min_length=1, description="What the team does there.")


class EvilTeam(Mutable):
    scheme: Scheme | None = None
    operation: Operation | None = None
    outcomes: list[Outcome] = Field(default_factory=list)
    opened_at_badges: int = Field(default=0, ge=0)
    leader_ids: list[Slug] = Field(default_factory=list)
    boss_id: Slug | None = None
    boss_beaten: bool = False

    @model_validator(mode="after")
    def _a_consistent_scheme(self) -> Self:
        if self.scheme is None and (self.operation or self.boss_id):
            raise ValueError("an operation or a boss needs a scheme")
        if self.stage() > SCHEME_STAGES:
            raise ValueError(f"the scheme has {SCHEME_STAGES} stages, not {self.stage()}")
        operation = self.operation
        if operation is not None and operation.leader_id not in self.leader_ids:
            raise ValueError(f"the operation's leader is no leader: {operation.leader_id!r}")
        return self

    def require_scheme(self) -> Scheme:
        assert self.scheme is not None
        return self.scheme

    def stage(self) -> int:
        return len(self.outcomes)

    def foiled(self) -> int:
        return self.outcomes.count("foiled")

    def succeeded(self) -> int:
        return self.outcomes.count("succeeded")

    def due(self, badges: int) -> SchemeDue | None:
        if (
            self.stage() < SCHEME_STAGES
            and self.operation is None
            and badges >= self.next_operation_badges()
        ):
            return "operation"
        if self.stage() == SCHEME_STAGES and self.boss_id is None:
            return "lair"
        return None

    def key_ids(self) -> tuple[Slug, ...]:
        return (*self.leader_ids, *filter(None, (self.boss_id,)))

    def joining_legendary_id(self) -> Slug | None:
        if self.succeeded() < LEGENDARY_AT:
            return None
        return self.require_scheme().legendary_id

    def next_operation_badges(self) -> int:
        return min(
            self.opened_at_badges + BADGES_PER_OPERATION, BADGES_PER_OPERATION * (self.stage() + 1)
        )

    def open_operation(self, operation: Operation, badges: int) -> None:
        self.operation = operation
        self.opened_at_badges = badges
        if operation.leader_id not in self.leader_ids:
            self.leader_ids.append(operation.leader_id)

    def record_outcome(self, outcome: Outcome) -> str:
        self.operation = None
        self.outcomes.append(outcome)
        return self.require_scheme().stages[self.stage() - 1].text_for(outcome)

    def boss_roster(
        self, boss: JourneyTrainer, table_level: int, species_ids: Collection[Slug]
    ) -> tuple[RosterSlot, ...]:
        ace_level = min(table_level + BOSS_RISE * self.succeeded(), LEVEL_MAX)
        roster = rescaled(boss.roster, ace_level, species_ids)
        legendary_id = self.joining_legendary_id()
        if legendary_id is None:
            return roster
        kept = sorted(roster, key=lambda slot: slot.level)[1 - TEAM_MAX :]
        return (*kept, RosterSlot(species_id=legendary_id, level=ace_level))
