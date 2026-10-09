from functools import cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.stores import read_model
from rulehall.core.validation import Frozen, Refusal, Slug, check_unique
from rulehall.engines.pokemon.battle.models import ChampionsFormatId, Nature, Spread
from rulehall.engines.pokemon.dex import Stats, dex

DATA_FILE = Path(__file__).parent / "data.json"
PRESETS_MAX = 3

type Percent = Annotated[float, Field(ge=0, le=100)]
type Share = Annotated[float, Field(ge=0, le=1)]
type Pool = Literal["finalist", "top4", "top8"]


class CompetitiveSet(Frozen):
    species_id: Slug
    ability_id: Slug
    item_id: Slug
    move_ids: tuple[Slug, ...] = Field(min_length=1)
    nature: Nature
    sp: Stats

    @model_validator(mode="after")
    def _check_moves(self) -> Self:
        check_unique(f"moves of {self.species_id}", self.move_ids)
        return self


class CompetitiveTeam(Frozen):
    archetype_ids: tuple[Slug, ...] = Field(min_length=1)
    sets: tuple[CompetitiveSet, ...] = Field(min_length=1)


class RealTeam(CompetitiveTeam):
    team_id: Slug
    label: str = Field(min_length=1)
    credit: str = Field(min_length=1)
    regulation: ChampionsFormatId
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    players: int = Field(gt=0)
    placing: int = Field(gt=0)
    pool: Pool


class UsageSource(Frozen):
    format_id: ChampionsFormatId
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    cutoff: int = Field(ge=0)
    battles: int = Field(gt=0)


class LegalSpecies(Frozen):
    base_species_id: Slug
    ability_ids: tuple[Slug, ...] = Field(min_length=1)
    move_ids: tuple[Slug, ...] = Field(min_length=1)


class Legality(Frozen):
    species: dict[Slug, LegalSpecies] = Field(min_length=1)
    item_ids: tuple[Slug, ...] = Field(min_length=1)
    mega_formes: dict[Slug, dict[Slug, Slug]]
    sp_max: int = Field(gt=0)
    sp_total: int = Field(gt=0)
    team_size: int = Field(gt=0)
    level: int = Field(gt=0)
    moves_max: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_mega_formes(self) -> Self:
        pokedex = dex()
        for stone_id, formes in self.mega_formes.items():
            if stone_id not in self.item_ids:
                raise Refusal(f"Mega Stone {stone_id!r} is not legal in the format")
            for holder_id, forme_id in formes.items():
                self.require_species(holder_id)
                pokedex.require_species(forme_id)
                if forme_id in self.species:
                    raise Refusal(f"{forme_id!r} is no Mega forme of {holder_id}")
        return self

    def find_mega_forme_id(self, item_id: Slug | None, species_id: Slug) -> Slug | None:
        if item_id is None:
            return None
        return self.mega_formes.get(item_id, {}).get(species_id)

    def require_species(self, species_id: str) -> LegalSpecies:
        found = self.species.get(species_id)
        if found is None:
            raise Refusal(f"{species_id!r} is not legal in the format")
        return found

    def check_set(self, competitive_set: CompetitiveSet) -> None:
        legal = self.require_species(competitive_set.species_id)
        where = competitive_set.species_id
        if competitive_set.ability_id not in legal.ability_ids:
            raise Refusal(f"{where} cannot have {competitive_set.ability_id!r}")
        if len(competitive_set.move_ids) > self.moves_max:
            raise Refusal(f"{where} has more than {self.moves_max} moves")
        if unknown := set(competitive_set.move_ids) - set(legal.move_ids):
            raise Refusal(f"{where} cannot learn {sorted(unknown)}")
        if competitive_set.item_id not in self.item_ids:
            raise Refusal(f"{competitive_set.item_id!r} is not legal in the format")
        if not all(0 <= points <= self.sp_max for points in competitive_set.sp):
            raise Refusal(f"{where} has a stat outside 0 to {self.sp_max} stat points")
        if sum(competitive_set.sp) > self.sp_total:
            raise Refusal(f"{where} has more than {self.sp_total} stat points")


class SpeciesShare(Frozen):
    species_id: Slug
    percent: Percent


class ItemShare(Frozen):
    item_id: Slug
    percent: Percent


class MoveShare(Frozen):
    move_id: Slug
    percent: Percent


class AbilityShare(Frozen):
    ability_id: Slug
    percent: Percent


class SpreadShare(Frozen):
    nature: Nature
    sp: Stats
    percent: Percent


class UsageCard(Frozen):
    source: Literal["smogon", "limitless"]
    usage_percent: Percent
    teammates: tuple[SpeciesShare, ...]
    abilities: tuple[AbilityShare, ...]
    items: tuple[ItemShare, ...]
    moves: tuple[MoveShare, ...]
    spreads: tuple[SpreadShare, ...]
    checks: tuple[SpeciesShare, ...]


class SpeciesPool(Frozen):
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    mega_batches: tuple[tuple[Slug, ...], ...]


class Archetype(Frozen):
    archetype_id: Slug
    name: str = Field(min_length=1)
    move_ids: tuple[Slug, ...]
    ability_ids: tuple[Slug, ...]
    setter_id: Slug
    core_ids: tuple[Slug, ...]
    leads: tuple[Slug, Slug]
    team: CompetitiveTeam

    @model_validator(mode="after")
    def _check_members(self) -> Self:
        members = {each.species_id for each in self.team.sets}
        if not {self.setter_id, *self.core_ids, *self.leads} <= members:
            raise Refusal(f"the setter, cores or leads of {self.archetype_id} are not on its team")
        return self


class Role(Frozen):
    name: str = Field(min_length=1)
    move_ids: tuple[Slug, ...]
    ability_ids: tuple[Slug, ...]


class ChampionsData(Frozen):
    source: UsageSource
    legal: Legality
    roles: dict[Slug, Role] = Field(min_length=1)
    presets: dict[
        Slug, Annotated[tuple[CompetitiveSet, ...], Field(min_length=1, max_length=PRESETS_MAX)]
    ]
    assumed: dict[Slug, tuple[Spread, ...]]
    usage: dict[Slug, UsageCard]
    teammates: dict[Slug, dict[Slug, Share]]
    pool: SpeciesPool
    archetypes: tuple[Archetype, ...] = Field(min_length=1)
    real_teams: tuple[RealTeam, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        cards = self.usage.values()
        for species_id in {
            *self.assumed,
            *self.usage,
            *self.teammates,
            *(mate_id for shares in self.teammates.values() for mate_id in shares),
            *(each.species_id for card in cards for each in (*card.teammates, *card.checks)),
        }:
            self.legal.require_species(species_id)
        self._check_roles()
        for species_id, presets in self.presets.items():
            for preset in presets:
                if preset.species_id != species_id:
                    raise Refusal(f"a {preset.species_id} preset is listed under {species_id}")
                self._check_set(preset)
        archetype_ids = [archetype.archetype_id for archetype in self.archetypes]
        check_unique("archetype ids", archetype_ids)
        check_unique("team ids", (team.team_id for team in self.real_teams))
        teams = (
            *((f"archetype {each.archetype_id}", each.team) for each in self.archetypes),
            *((team.team_id, team) for team in self.real_teams),
        )
        for where, team in teams:
            if len(team.sets) != self.legal.team_size:
                raise Refusal(f"{where} needs {self.legal.team_size} sets")
            for each in team.sets:
                self._check_set(each)
            base_ids = (self.legal.species[each.species_id].base_species_id for each in team.sets)
            check_unique(f"species on {where}", base_ids)
            check_unique(f"items on {where}", (each.item_id for each in team.sets))
            if unknown := set(team.archetype_ids) - set(archetype_ids):
                raise Refusal(f"{where} has no archetypes {sorted(unknown)}")
        for species_id in self.pool.species_ids:
            if species_id not in self.presets:
                raise Refusal(f"pool species {species_id} has no preset")
        for stone_id in (stone for batch in self.pool.mega_batches for stone in batch):
            if stone_id not in self.legal.mega_formes:
                raise Refusal(f"{stone_id!r} is no Mega Stone of the format")
        return self

    def _check_roles(self) -> None:
        species = self.legal.species.values()
        move_ids = {move_id for each in species for move_id in each.move_ids}
        ability_ids = {ability_id for each in species for ability_id in each.ability_ids}
        for role_id, role in self.roles.items():
            if unknown := (set(role.move_ids) - move_ids) | (set(role.ability_ids) - ability_ids):
                raise Refusal(f"role {role_id} has ids not legal in the format: {sorted(unknown)}")

    def _check_set(self, competitive_set: CompetitiveSet) -> None:
        self.legal.check_set(competitive_set)
        pokedex = dex()
        where = pokedex.require_species(competitive_set.species_id).name
        if unknown := set(competitive_set.move_ids) - set(pokedex.moves):
            raise Refusal(f"{where} has moves the dex lacks: {sorted(unknown)}")
        if competitive_set.ability_id not in pokedex.ability_names:
            raise Refusal(f"{where} has an ability the dex lacks: {competitive_set.ability_id!r}")
        if competitive_set.species_id not in self.assumed:
            raise Refusal(f"{competitive_set.species_id} has no assumed spread")
        if competitive_set.species_id not in self.usage:
            raise Refusal(f"{competitive_set.species_id} has no usage card")


@cache
def champions_data() -> ChampionsData:
    return read_model(DATA_FILE, ChampionsData)


def move_shares(species_id: Slug) -> dict[Slug, float]:
    card = champions_data().usage.get(species_id)
    return {} if card is None else {each.move_id: each.percent for each in card.moves}
