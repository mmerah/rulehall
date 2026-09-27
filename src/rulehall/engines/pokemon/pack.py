from typing import Self

from pydantic import Field, model_validator

from rulehall.core.prompt import Sections
from rulehall.core.validation import Slug, check_unique
from rulehall.engines.packs import Pack, PackHead
from rulehall.engines.pokemon.dex import avatars, dex
from rulehall.engines.pokemon.rules import BADGE_LEVELS, LEVEL_SPREAD, REGULAR_TRAINERS_MAX

LATER_ACES = ", ".join(str(level) for level in BADGE_LEVELS[3:-1])
WORLDSMITH_GUIDANCE = (
    "POKEMON AUTHORING\n"
    "A place is one town, route, cave, gym or building of the region. `wild` gives the wild table "
    "of each new place: species ids from SPECIES, the lowest level, the highest level and a "
    "weight. A route, a cave or a shore has a table. A town or a building has none. Every town "
    "has a Pokemon Center, a place of its own that `centers` lists: the team heals only there, "
    "so the opening map has one. A person who battles has a `roster` of one to six species ids "
    "with levels. A gym leader also has a `badge`, such as 'Tide Badge'. The ace of a gym "
    "leader, the highest level of the roster, "
    f"follows the badge table: the first gym's ace is level {BADGE_LEVELS[0]}, the second's "
    f"{BADGE_LEVELS[1]}, the third's {BADGE_LEVELS[2]}, then {LATER_ACES} and {BADGE_LEVELS[-1]}, "
    f"each give or take {LEVEL_SPREAD}. Write a few meaningful trainers: at most "
    f"{REGULAR_TRAINERS_MAX} people without a badge battle in one map. A person who does not "
    "battle has no `roster`. Every gym leader and the rival has a `style`, a `win_line` and a "
    "`lose_line`. The opening map holds one rival, with `rival` true and no `roster`: code builds "
    "the rival's team. A later map adds no rival. Every person has an `avatar_id` from TRAINER "
    "CLASSES: the look that fits them, such as 'hiker' or 'nurse'. Early routes hold levels 2 to "
    "6. A locked way can be a thin tree that Cut clears, or a closed gym door. Never write "
    "`sheet`, `beaten`, `team` or `last_battle_visit`. Code writes the player's team."
)


class PokemonPack(Pack):
    species: tuple[Slug, ...] = Field(min_length=1)
    starters: tuple[Slug, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _species_of_the_dex(self) -> Self:
        check_unique("species", self.species)
        check_unique("starters", self.starters)
        if strays := sorted(set(self.species) - set(dex().species)):
            raise ValueError(f"species the dex lacks: {strays}")
        if strays := sorted(set(self.starters) - set(self.species)):
            raise ValueError(f"starters that are not in species: {strays}")
        return self

    def sections(self, *, opening: bool) -> Sections:
        pokedex = dex()
        return (
            *super().sections(opening=opening),
            ("SPECIES", ", ".join(pokedex.tag(species_id) for species_id in self.species)),
            ("TRAINER CLASSES", ", ".join(avatars().npc)),
        )


class PokemonHead(PackHead):
    species: tuple[Slug, ...] = Field(
        min_length=10,
        description="Ids of the species that live in this region. An id is the Showdown id: the "
        "name in lower case, with no spaces or marks, such as 'mrmime' or 'raichualola'. Any "
        "species of the national dex, with its regional formes.",
    )
    starters: tuple[Slug, ...] = Field(
        min_length=3,
        max_length=3,
        description="Three ids from `species` that a new trainer picks from.",
    )
