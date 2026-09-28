from typing import Self

from pydantic import Field, model_validator

from rulehall.core.prompt import Sections
from rulehall.core.validation import Slug, check_unique
from rulehall.engines.packs import Pack, PackHead
from rulehall.engines.pokemon.dex import avatars, dex


class PokemonPack(Pack):
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    starters: tuple[Slug, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _species_of_the_dex(self) -> Self:
        check_unique("species_ids", self.species_ids)
        check_unique("starters", self.starters)
        if strays := sorted(set(self.species_ids) - set(dex().species)):
            raise ValueError(f"species the dex lacks: {strays}")
        if strays := sorted(set(self.starters) - set(self.species_ids)):
            raise ValueError(f"starters that are not in species_ids: {strays}")
        return self

    def sections(self, *, opening: bool) -> Sections:
        pokedex = dex()
        return (
            *super().sections(opening=opening),
            ("SPECIES", ", ".join(pokedex.tag(species_id) for species_id in self.species_ids)),
            ("TRAINER CLASSES", ", ".join(avatars().npc)),
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
