from collections.abc import Sequence
from typing import ClassVar, Self

from pydantic import Field, model_validator

from rulehall.core.prompt import Sections
from rulehall.core.validation import Slug, check_unique
from rulehall.engines.packs import Pack, PackHead
from rulehall.engines.pokemon.dex import avatars, dex


class PokemonPack(Pack):
    mixable: ClassVar[bool] = True
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    starters: tuple[Slug, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _species_of_the_dex(self) -> Self:
        check_unique("species_ids", self.species_ids)
        check_unique("starters", self.starters)
        pokedex = dex()
        if strays := sorted(set(self.species_ids) - set(pokedex.species)):
            raise ValueError(f"species the dex lacks: {strays}")
        if strays := sorted(
            species_id for species_id in self.species_ids if pokedex.species[species_id].forme_only
        ):
            raise ValueError(f"forme-only species, not for a journey: {strays}")
        if strays := sorted(set(self.starters) - set(self.species_ids)):
            raise ValueError(f"starters that are not in species_ids: {strays}")
        return self

    def joined(self, others: Sequence[Pack]) -> Self:
        if not others:
            return self
        species_ids = list(self.species_ids)
        for other in others:
            if not isinstance(other, PokemonPack):
                raise TypeError(f"a Pokemon pack joins no {type(other).__name__}")
            species_ids.extend(other.species_ids)
        return self.model_validate(
            {**self.model_dump(), "species_ids": tuple(dict.fromkeys(species_ids))}
        )

    def sections(self, *, opening: bool) -> Sections:
        pokedex = dex()
        return (
            *super().sections(opening=opening),
            (
                "SPECIES",
                ", ".join(pokedex.species_ref(species_id) for species_id in self.species_ids),
            ),
            ("TRAINER LOOKS", avatars().npc_group_lines()),
        )


class PokemonHead(PackHead):
    species_ids: tuple[Slug, ...] = Field(
        min_length=10,
        description="Ids of the species that live in this region. An id is the Showdown id: the "
        "name in lower case, with no spaces or marks, such as 'mrmime' or 'raichualola'. Any "
        "species of the national dex, with its regional formes.",
    )
    starters: tuple[Slug, ...] = Field(
        min_length=3,
        max_length=3,
        description="Three ids from `species_ids` that a new trainer picks from.",
    )
