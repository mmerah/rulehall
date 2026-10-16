from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.decisions import find_option
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.data import (
    Ability,
    ClassId,
    LevelPickKind,
    SpeciesId,
    SubspeciesId,
    srd,
)
from rulehall.engines.lite5e.pack import Background
from rulehall.engines.lite5e.rules import (
    ABILITIES,
    CASTING_ABILITIES,
    STANDARD_ARRAY,
    AbilityMethod,
    CastingAbility,
)
from rulehall.engines.lite5e.sheet import Lite5eSheet


class SheetProposal(Frozen):
    kind: Literal["class"] = Field(description="A class companion.")
    class_id: ClassId = Field(description="Exact id of the class.")
    species_id: SpeciesId = Field(description="Exact id of an SRD species.")
    subspecies_id: SubspeciesId | None = Field(
        default=None,
        description="Exact id of the species' lineage, ancestry or legacy. Null when it has none.",
    )
    background_id: Slug = Field(description="Exact id of the background.")
    method: AbilityMethod = Field(default="array", description="The standard array or a point buy.")
    scores: dict[Ability, int] = Field(
        default_factory=dict, description="One score per ability. Empty: the class's array."
    )
    increases: dict[Ability, int] = Field(
        default_factory=dict,
        description="The background's increases: +2 and +1, or three +1. Empty: the default.",
    )
    picks: dict[LevelPickKind, tuple[Slug, ...]] = Field(
        default_factory=dict,
        description="The level picks, keyed by pick kind: exact ids, one per pick. A kind left "
        "out takes the defaults.",
    )
    species_ability: CastingAbility | None = Field(
        default=None,
        description="The spellcasting ability of species spells. Null: the default.",
    )
    category_gear_ids: dict[Slug, Slug] = Field(
        default_factory=dict,
        description="The pick of each gear category, such as a holy symbol. Empty: the first.",
    )

    @model_validator(mode="after")
    def _scores_every_ability_or_none(self) -> Self:
        if self.scores and len(self.scores) != len(ABILITIES):
            raise ValueError("give a score for each of the six abilities, or none")
        return self

    def build_sheet(self, level: int, backgrounds: Sequence[Background]) -> Lite5eSheet:
        background = self.require_background(backgrounds)
        sheet = self.start_sheet(background)
        sheet.finish(
            level=level,
            background=background,
            category_gear_ids=self.category_gear_ids,
            picks=self.picks,
        )
        return sheet

    def start_sheet(self, background: Background) -> Lite5eSheet:
        srd_class = srd().require_class(self.class_id)
        species = srd().character_options.species[self.species_id]
        if species.subspecies and self.subspecies_id not in species.subspecies:
            raise Refusal(f"{species.name} needs one of {sorted(species.subspecies)}")
        if not species.subspecies and self.subspecies_id is not None:
            raise Refusal(f"{species.name} has no lineage: leave subspecies_id null")
        order = srd_class.defaults.ability_order
        scores = self.scores or dict(zip(order, STANDARD_ARRAY, strict=True))
        ranked = sorted(background.abilities, key=order.index)
        species_ability = None
        if any(trait.spell_ids for trait in species.lineage_traits(self.subspecies_id)):
            species_ability = self.species_ability or max(
                CASTING_ABILITIES,
                key=lambda ability: (ability == srd_class.spell_ability, scores[ability]),
            )
        elif self.species_ability is not None:
            raise Refusal(f"{species.name} casts no species spell: leave species_ability null")
        return Lite5eSheet.start(
            class_id=self.class_id,
            species_id=self.species_id,
            subspecies_id=self.subspecies_id,
            species_ability=species_ability,
            background=background,
            method=self.method,
            scores=scores,
            increases=self.increases or {ranked[0]: 2, ranked[1]: 1},
        )

    def require_background(self, backgrounds: Sequence[Background]) -> Background:
        background = find_option(backgrounds, self.background_id)
        if background is None:
            raise Refusal(
                f"{self.background_id!r} is no background: {[bg.id for bg in backgrounds]}"
            )
        return background


class StatBlockHire(Frozen):
    kind: Literal["stat_block"] = Field(description="A stat-block companion.")


class HireAnswer(Frozen):
    hire: Annotated[SheetProposal | StatBlockHire, Field(discriminator="kind")] = Field(
        description="How the person signs on."
    )
