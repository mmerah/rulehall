from pydantic import Field

from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.pokemon.battle.models import TEAM_MAX
from rulehall.engines.pokemon.champions.data import CompetitiveSet


class SetSlot(Frozen):
    slot: int = Field(ge=1, le=TEAM_MAX)
    competitive_set: CompetitiveSet


class MoveSlot(Frozen):
    slot: int = Field(ge=1, le=TEAM_MAX)
    to_slot: int = Field(ge=1, le=TEAM_MAX)


class ApplyPreset(Frozen):
    slot: int = Field(ge=1, le=TEAM_MAX)
    preset_id: Slug


class LoadTemplate(Frozen):
    template_id: Slug


class SaveTeam(Frozen):
    sets: tuple[CompetitiveSet, ...]


class Recruit(Frozen):
    species_id: Slug = Field(
        description="Exact id of a species legal in the format, such as 'garchomp'."
    )
    how: PlayerFacing = Field(
        min_length=1,
        description="How the Pokemon joins the player, such as 'traded for at the practice "
        "hall'. The player reads it.",
    )
