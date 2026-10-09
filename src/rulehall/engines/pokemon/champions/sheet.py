from collections.abc import Sequence
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.validation import Mutable, Refusal, Slug
from rulehall.core.views import Rows
from rulehall.engines.pokemon.champions.data import CompetitiveSet, champions_data
from rulehall.engines.pokemon.champions.rules import check_team, require_archetype
from rulehall.engines.pokemon.champions.season import (
    TIERS,
    Finish,
    Tier,
    total_cp,
    unlocked_tiers,
)
from rulehall.engines.pokemon.dex import avatars, dex
from rulehall.engines.pokemon.trainers import AVATAR_ID, LOSE_LINE, RIVAL, STYLE, WIN_LINE
from rulehall.engines.rooms.world import Dweller
from rulehall.engines.sheet import Sheeted

type Roster = Literal["open", "story"]
KEY_TRAINER = "key trainer (a trainer with an archetype, or the rival)"
ARCHETYPE_ID = (
    "Exact id from ARCHETYPES for a key trainer who enters this map's event with a team of that "
    "archetype. Null for anyone else, and for the rival."
)
ACE_SPECIES_ID = (
    "Exact id from ACE SPECIES: the signature Pokemon code puts on this key trainer's team. "
    "Null for no ace."
)
LOCKED = "the team is registered for an event and locked until the event ends"


class ChampionsSheet(Mutable):
    roster: Roster
    team: list[CompetitiveSet]
    registered: tuple[CompetitiveSet, ...] | None = None
    owned_species_ids: list[Slug] = Field(min_length=1)
    finishes: list[Finish] = Field(default_factory=list)
    recruits_left: int = Field(ge=0)

    @model_validator(mode="after")
    def _a_legal_team(self) -> Self:
        check_team(self.team, self.allowed_species_ids)
        return self

    @property
    def allowed_species_ids(self) -> list[Slug] | None:
        return self.owned_species_ids if self.roster == "story" else None

    def cp(self) -> int:
        return total_cp(self.finishes)

    def unlocked_tiers(self) -> tuple[Tier, ...]:
        return unlocked_tiers(self.finishes)

    def refuse_while_registered(self) -> None:
        if self.registered is not None:
            raise Refusal(LOCKED)

    def replace_team(self, sets: Sequence[CompetitiveSet]) -> None:
        self.refuse_while_registered()
        check_team(sets, self.allowed_species_ids)
        self.team = list(sets)


class ChampionsTrainer(Sheeted[ChampionsSheet], Dweller):
    style: str = Field(
        default="",
        description=STYLE.format(key_trainer=KEY_TRAINER, example="sets Tailwind, then hits hard"),
    )
    win_line: str = Field(default="", description=WIN_LINE.format(key_trainer=KEY_TRAINER))
    lose_line: str = Field(default="", description=LOSE_LINE.format(key_trainer=KEY_TRAINER))
    avatar_id: Slug = Field(description=AVATAR_ID)
    rival: bool = Field(
        default=False,
        description=RIVAL.format(span="season")
        + " Code builds the rival's team and brings them to every event.",
    )
    archetype_id: Slug | None = Field(default=None, description=ARCHETYPE_ID)
    ace_species_id: Slug | None = Field(default=None, description=ACE_SPECIES_ID)
    team: SkipJsonSchema[tuple[CompetitiveSet, ...]] = ()

    @model_validator(mode="after")
    def _a_listed_look_and_archetype(self) -> Self:
        if self.sheet is not None and self.avatar_id not in avatars().player:
            raise ValueError(f"{self.avatar_id!r} is no player look")
        if self.sheet is None and self.avatar_id not in avatars().npc_ids():
            raise ValueError(f"{self.avatar_id!r} is no id from TRAINER LOOKS")
        if self.archetype_id is not None:
            _ = require_archetype(self.archetype_id)
        if self.archetype_id is not None and self.rival:
            raise ValueError(f"{self.name} is the rival: code builds their team, with no archetype")
        if self.ace_species_id is not None:
            if self.archetype_id is None:
                raise ValueError(f"{self.name} has an ace but no archetype")
            if self.ace_species_id not in champions_data().presets:
                raise ValueError(f"{self.ace_species_id!r} is no id from ACE SPECIES")
        return self

    def is_key(self) -> bool:
        return self.rival or self.archetype_id is not None

    def rows(self) -> Rows:
        sheet = self.sheet
        if sheet is None:
            archetype = (
                "" if self.archetype_id is None else require_archetype(self.archetype_id).name
            )
            ace = "" if self.ace_species_id is None else dex().species[self.ace_species_id].name
            shown = (
                ("Rival", "the rival of the season" if self.rival else ""),
                ("Archetype", archetype),
                ("Ace", ace),
                ("Style", self.style),
            )
            return tuple((label, value) for label, value in shown if value)
        unlocked = ", ".join(TIERS[tier].name for tier in sheet.unlocked_tiers())
        return (
            ("Team", ", ".join(dex().species[each.species_id].name for each in sheet.team)),
            ("Tier", unlocked or "none"),
            ("CP", str(sheet.cp())),
            ("Registered", "yes: the team is locked" if sheet.registered else "no"),
        )
