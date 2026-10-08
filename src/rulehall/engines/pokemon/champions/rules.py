from collections.abc import Collection, Iterable, Sequence
from random import Random

from rulehall.core.validation import Refusal, Slug
from rulehall.engines.pokemon.battle.models import FRIENDSHIP_MAX, BattleMove, Battler, Gender
from rulehall.engines.pokemon.champions.data import (
    Archetype,
    CompetitiveSet,
    Pool,
    RealTeam,
    champions_data,
)
from rulehall.engines.pokemon.champions.season import TIERS, Tier
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import IV_MAX, STAT_NAMES, stats

TEAM_SLOT_PREFIX = "team-"
RECRUITS_PER_EVENT = 1
KEY_TRAINERS_MAX = 3
PRESET_LETTERS = "abc"
RIVAL_CORE = 2


def require_preset(chosen_id: Slug) -> CompetitiveSet:
    species_id, _, letter = chosen_id.rpartition("-")
    presets = champions_data().presets.get(species_id, ())
    index = PRESET_LETTERS.find(letter) if len(letter) == 1 else -1
    if not 0 <= index < len(presets):
        raise Refusal(f"{chosen_id!r} is no preset id")
    return presets[index]


def require_archetype(archetype_id: Slug) -> Archetype:
    found = next(
        (each for each in champions_data().archetypes if each.archetype_id == archetype_id), None
    )
    if found is None:
        known = ", ".join(each.archetype_id for each in champions_data().archetypes)
        raise Refusal(f"{archetype_id!r} is no archetype id; archetypes: {known}")
    return found


def require_template(template_id: Slug) -> tuple[CompetitiveSet, ...]:
    data = champions_data()
    for archetype in data.archetypes:
        if archetype.archetype_id == template_id:
            return archetype.team.sets
    for team in data.real_teams:
        if team.team_id == template_id:
            return team.sets
    raise Refusal(f"{template_id!r} is no archetype id or real team id")


def battler_of_set(competitive_set: CompetitiveSet, mon_id: Slug) -> Battler:
    pokedex = dex()
    species = pokedex.require_species(competitive_set.species_id)
    level = champions_data().legal.level
    ivs = (IV_MAX,) * len(STAT_NAMES)
    gender: Gender = species.gender or ("M" if species.male_share >= 0.5 else "F")
    return Battler(
        mon_id=mon_id,
        species_id=competitive_set.species_id,
        name=species.name,
        level=level,
        nature=competitive_set.nature,
        ability=pokedex.ability_names[competitive_set.ability_id],
        gender=gender,
        ivs=ivs,
        evs=competitive_set.sp,
        friendship=FRIENDSHIP_MAX,
        item_id=competitive_set.item_id,
        moves=tuple(
            BattleMove(
                move_id=move_id,
                name=pokedex.moves[move_id].name,
                type=pokedex.moves[move_id].type,
                pp=pokedex.moves[move_id].pp,
            )
            for move_id in competitive_set.move_ids
        ),
        hp=stats(species, level, competitive_set.nature, ivs, competitive_set.sp, stat_points=True)[
            0
        ],
    )


def check_team(sets: Sequence[CompetitiveSet], owned_species_ids: Collection[Slug] | None) -> None:
    legal = champions_data().legal
    if len(sets) != legal.team_size:
        raise Refusal(f"a team has {legal.team_size} Pokemon, not {len(sets)}")
    for each in sets:
        legal.check_set(each)
    if clashes := _clashes(sets):
        raise Refusal(clashes)
    if owned_species_ids is not None and (
        unowned := sorted({each.species_id for each in sets} - set(owned_species_ids))
    ):
        raise Refusal(f"the player has not recruited {unowned}")


def build_key_team(
    archetype_id: Slug,
    ace_species_id: Slug | None,
    pools: Collection[Pool],
    used_team_ids: Collection[Slug],
    rng: Random,
) -> tuple[RealTeam | None, tuple[CompetitiveSet, ...]]:
    data = champions_data()
    archetype = require_archetype(archetype_id)
    real_teams = _by_recency(
        team
        for team in data.real_teams
        if team.pool in pools
        and team.archetype_ids[0] == archetype_id
        and team.team_id not in used_team_ids
    )
    real_team = real_teams[0] if real_teams else None
    sets = archetype.team.sets if real_team is None else real_team.sets
    legal = data.legal
    if ace_species_id is None or legal.require_species(ace_species_id).base_species_id in {
        legal.species[each.species_id].base_species_id for each in sets
    }:
        return real_team, sets
    presets = list(data.presets[ace_species_id])
    rng.shuffle(presets)
    shares = data.teammates.get(ace_species_id, {})
    victims = sorted(
        (index for index, each in enumerate(sets) if each.species_id != archetype.setter_id),
        key=lambda index: shares.get(sets[index].species_id, 0.0),
    )
    for index in victims:
        for preset in presets:
            swapped = (*sets[:index], preset, *sets[index + 1 :])
            if not _clashes(swapped):
                return real_team, swapped
    raise Refusal(f"{ace_species_id!r} cannot join a {archetype.name} team")


def build_rival(player_species_ids: Collection[Slug], rng: Random) -> tuple[CompetitiveSet, ...]:
    data = champions_data()
    legal = data.legal
    taken = {legal.require_species(species_id).base_species_id for species_id in player_species_ids}
    core: list[CompetitiveSet] = []
    pool = list(data.pool.species_ids)
    rng.shuffle(pool)
    for species_id in pool:
        if len(core) == RIVAL_CORE:
            break
        if legal.species[species_id].base_species_id in taken:
            continue
        if fitting := [each for each in data.presets[species_id] if not _clashes((*core, each))]:
            core.append(rng.choice(fitting))

    def weight(candidate: CompetitiveSet) -> float:
        return sum(
            data.teammates.get(member.species_id, {}).get(candidate.species_id, 0.0)
            for member in core
        )

    templates = sorted(
        (archetype.team for archetype in data.archetypes),
        key=lambda team: -sum(weight(each) for each in team.sets),
    )
    sets = list(core)
    for template in templates:
        for candidate in sorted(template.sets, key=lambda each: -weight(each)):
            fresh = legal.species[candidate.species_id].base_species_id not in taken
            if fresh and not _clashes((*sets, candidate)):
                sets.append(candidate)
    if len(sets) != legal.team_size:
        raise ValueError("the archetype teams cannot complete the rival")
    return tuple(sets)


def draw_field(
    tier: Tier,
    count: int,
    used_team_ids: Collection[Slug],
    key_team_ids: Collection[Slug],
    rng: Random,
) -> tuple[RealTeam | Archetype, ...]:
    data = champions_data()
    pools = TIERS[tier].pools
    archetypes = data.archetypes if "archetype" in pools else ()
    ranked = [
        each
        for each in (
            *archetypes,
            *_by_recency(team for team in data.real_teams if team.pool in pools),
        )
        if field_id(each) not in key_team_ids
    ]
    fresh = [each for each in ranked if field_id(each) not in used_team_ids][: 2 * count]
    drawn = rng.sample(fresh, min(count, len(fresh)))
    drawn_ids = {field_id(each) for each in drawn}
    stale = [each for each in ranked if field_id(each) not in drawn_ids]
    return (*drawn, *stale[: count - len(drawn)])


def key_team_pools(tier: Tier) -> tuple[Pool, ...]:
    return tuple(pool for pool in TIERS[tier].pools if pool != "archetype")


def field_id(drawn: RealTeam | Archetype) -> Slug:
    return drawn.team_id if isinstance(drawn, RealTeam) else drawn.archetype_id


def _by_recency(teams: Iterable[RealTeam]) -> list[RealTeam]:
    current = champions_data().source.format_id
    by_date = sorted(teams, key=lambda team: team.date, reverse=True)
    return sorted(by_date, key=lambda team: team.regulation != current)


def _clashes(sets: Sequence[CompetitiveSet]) -> str:
    legal = champions_data().legal
    if len(sets) > legal.team_size:
        return f"a team has at most {legal.team_size} Pokemon"
    base_ids = [legal.require_species(each.species_id).base_species_id for each in sets]
    if len(set(base_ids)) != len(base_ids):
        return "a team holds each species once"
    item_ids = [each.item_id for each in sets]
    if len(set(item_ids)) != len(item_ids):
        return "a team holds each item once"
    return ""
