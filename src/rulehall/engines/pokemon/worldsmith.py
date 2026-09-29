from collections.abc import Collection

from rulehall.core.validation import Refusal, Slug
from rulehall.engines.pokemon.battle.models import DOUBLE_TEAM_MIN
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import (
    BADGE_LEVELS,
    LEVEL_SPREAD,
    REGULAR_TRAINERS_MAX,
    is_legendary,
    level_for,
)
from rulehall.engines.pokemon.scheme import Operation, Scheme, SchemeDue
from rulehall.engines.pokemon.sheet import KEY_TRAINER, Trainer
from rulehall.engines.pokemon.world import (
    PokemonMap,
    PokemonOpeningProposal,
    PokemonRegionProposal,
    PokemonWorld,
    unknown_wild_places,
)
from rulehall.engines.rooms.worldsmith import check_next as check_room_map_next
from rulehall.engines.rooms.worldsmith import check_opening as check_room_map_opening

LATER_ACES = ", ".join(str(level) for level in BADGE_LEVELS[3:-1])
WORLDSMITH_GUIDANCE = (
    "POKEMON AUTHORING\n"
    "A place is one town, route, cave, gym or building of the region. `wild` gives the wild table "
    "of each new place: species ids from SPECIES, the lowest level, the highest level and a "
    "weight. A route, a cave or a shore has a table. A town or a building has none. Every town "
    "has a Pokemon Center, a place of its own that `center_place_ids` lists: the team heals only "
    "there, so the opening map has one. A person who battles has a `roster` of one to six "
    "species ids with levels. A gym leader also has a `badge`, such as 'Tide Badge', and a "
    "`trial`, the task the challenger meets before the leader. Lock the way to the leader until "
    "the trial is done. A trainer with `double` true, such "
    "as twins, a pair or a gym that fights in doubles, always battles two-on-two and needs a "
    "roster of at least two. The ace of a gym leader, the highest level of the roster, "
    f"follows the badge table: the first gym's ace is level {BADGE_LEVELS[0]}, the second's "
    f"{BADGE_LEVELS[1]}, the third's {BADGE_LEVELS[2]}, then {LATER_ACES} and {BADGE_LEVELS[-1]}, "
    f"each give or take {LEVEL_SPREAD}. Write a few meaningful trainers: at most "
    f"{REGULAR_TRAINERS_MAX} people besides the key trainers battle in one map. A person who does "
    "not battle has no `roster`. Every key trainer, a gym leader, the rival, a leader of the evil "
    "team or its boss, has a `style`, a `win_line` and a `lose_line`. The opening map holds one "
    "rival, with `rival` true and no `roster`: code builds the rival's team. A later map adds no "
    "rival. The opening map also writes the evil team's `scheme`: a name, the boss's goal, four "
    "`stages` the player learns as its four operations end, and a `legendary_id` it is after, or "
    "null. The opening map holds its first `operation`; a later map writes one, or the lair and "
    "its boss, only when the request asks. An operation is the one problem of its map: a place "
    "the map's start reaches without a lock, a leader with a roster and no badge (or an earlier "
    "leader) and a goal. THE SCHEME's goal "
    "and its stages not yet told are hidden: never write them into a place, a person or the "
    "recap. Every person has an "
    "`avatar_id` from TRAINER CLASSES: the look that fits them, such as 'hiker' or 'nurse'. "
    "Early routes hold levels 2 to 6. A locked way can be a thin tree that Cut clears, or a "
    "closed gym door. Never write `sheet`, `beaten`, `team` or `last_battle_visit`. Code writes "
    "the player's team."
)
NOT_DUE = "leave `{field}` null: this request does not ask for it"
DUE_ASKS: dict[SchemeDue, str] = {
    "operation": "this region carries the team's next operation: write `operation`",
    "lair": "this region holds the team's lair: write the boss as an npc of this region with a "
    "roster, no badge and the three key lines, and name it in `boss_id`",
}


def check_opening(proposal: PokemonOpeningProposal, species_ids: Collection[Slug]) -> None:
    check_room_map_opening(proposal)
    _check_pokemon_map(proposal, species_ids, gyms_before=0, leader_ids=())
    _check_scheme(proposal.scheme, species_ids)


def check_next(proposal: PokemonRegionProposal, world: PokemonWorld) -> None:
    check_room_map_next(proposal, world)
    due = world.evil_team.due()
    operation_due, lair_due = due == "operation", due == "lair"
    if (proposal.operation is not None) != operation_due:
        raise Refusal(DUE_ASKS["operation"] if operation_due else NOT_DUE.format(field="operation"))
    if (proposal.boss_id is not None) != lair_due:
        raise Refusal(DUE_ASKS["lair"] if lair_due else NOT_DUE.format(field="boss_id"))
    gyms = sum(1 for npc in world.npcs.values() if npc.badge)
    _check_pokemon_map(
        proposal, world.species_ids, gyms_before=gyms, leader_ids=world.evil_team.leader_ids
    )


def _check_pokemon_map(
    proposal: PokemonOpeningProposal | PokemonRegionProposal,
    species_ids: Collection[Slug],
    *,
    gyms_before: int,
    leader_ids: Collection[Slug],
) -> None:
    opening = isinstance(proposal, PokemonOpeningProposal)
    operation = proposal.operation
    boss_id = None if opening else proposal.boss_id
    if strays := unknown_wild_places(proposal.wild, proposal.places):
        raise Refusal(f"wild tables for places this map does not add: {strays}")
    if strays := sorted(set(proposal.center_place_ids) - set(proposal.places)):
        raise Refusal(f"`center_place_ids` names places this map does not add: {strays}")
    if opening and not proposal.center_place_ids:
        raise Refusal("the opening map needs a Pokemon Center in `center_place_ids`")
    trainers = list(proposal.npcs.values())
    used = {slot.species_id for rows in proposal.wild.values() for slot in rows} | {
        slot.species_id for npc in trainers for slot in npc.roster
    }
    if strays := sorted(used - set(species_ids)):
        raise Refusal(f"species outside this region: {strays}; use only ids from SPECIES")
    leader_id = None if operation is None else operation.leader_id
    named = [key_id for key_id in (leader_id, boss_id) if key_id is not None]
    if mute := [
        npc.id
        for npc in trainers
        if npc.is_key(named) and not (npc.style and npc.win_line and npc.lose_line)
    ]:
        raise Refusal(f"each {KEY_TRAINER} needs a style, a win_line and a lose_line: {mute}")
    if short := [npc.id for npc in trainers if npc.double and len(npc.roster) < DOUBLE_TEAM_MIN]:
        raise Refusal(f"a `double` trainer needs a roster of at least {DOUBLE_TEAM_MIN}: {short}")
    if untried := [npc.id for npc in trainers if npc.badge and not npc.trial]:
        raise Refusal(f"each gym leader needs a trial: {untried}")
    for index, leader in enumerate((npc for npc in trainers if npc.badge), gyms_before):
        _check_ace(leader, index)
    regulars = [npc.id for npc in trainers if npc.roster and not npc.is_key(named)]
    if len(regulars) > REGULAR_TRAINERS_MAX:
        raise Refusal(
            f"at most {REGULAR_TRAINERS_MAX} people besides the key trainers battle in one "
            f"map, not {len(regulars)}: {regulars}; give the others no roster"
        )
    rivals = [npc for npc in trainers if npc.rival]
    if opening and len(rivals) != 1:
        raise Refusal(f"the opening map needs exactly one rival, not {len(rivals)}")
    if not opening and rivals:
        raise Refusal("the rival stands in the opening map; a new region adds no rival")
    if any(rival.roster for rival in rivals):
        raise Refusal("the rival has no roster: code builds their team")
    if operation is not None:
        _check_operation(proposal, operation, leader_ids)
    boss = None if boss_id is None else proposal.npcs.get(boss_id)
    if boss_id is not None and (boss is None or not boss.roster or boss.badge):
        raise Refusal(f"the boss {boss_id!r} is a person of this map with a roster, no badge")


def _check_ace(leader: Trainer, index: int) -> None:
    if not leader.roster:
        raise Refusal(f"{leader.name} gives a badge, so they need a roster")
    table = level_for(index)
    ace = max(slot.level for slot in leader.roster)
    if abs(ace - table) > LEVEL_SPREAD:
        raise Refusal(
            f"{leader.name}'s ace is L{ace}; the ace of gym {index + 1} is "
            f"L{table - LEVEL_SPREAD} to L{table + LEVEL_SPREAD}"
        )


def _check_scheme(scheme: Scheme, species_ids: Collection[Slug]) -> None:
    legendary_id = scheme.legendary_id
    if legendary_id is not None and (
        legendary_id not in species_ids or not is_legendary(dex().species[legendary_id])
    ):
        raise Refusal(f"`legendary_id` {legendary_id!r} is no legendary species of SPECIES")


def _check_operation(
    proposal: PokemonMap, operation: Operation, leader_ids: Collection[Slug]
) -> None:
    start_id = operation.place_id
    if start_id not in proposal.reachable(proposal.start_id):
        raise Refusal(
            f"the operation's place {start_id!r} is a place of this map that its start reaches "
            "without a lock"
        )
    leader = proposal.npcs.get(operation.leader_id)
    if (leader is None or not leader.roster or leader.badge) and (
        operation.leader_id not in leader_ids
    ):
        raise Refusal(
            f"the operation's leader {operation.leader_id!r} is a person of this map with a "
            f"roster and no badge, or an earlier leader: {list(leader_ids)}"
        )
