from collections.abc import Collection
from random import Random

from rulehall.core.validation import Refusal, Slug
from rulehall.engines.pokemon.champions.rules import (
    KEY_TRAINERS_MAX,
    build_key_team,
    key_team_pools,
)
from rulehall.engines.pokemon.champions.season import TIERS, Tier
from rulehall.engines.pokemon.champions.sheet import KEY_TRAINER
from rulehall.engines.pokemon.champions.world import (
    ChampionsMapProposal,
    ChampionsOpeningProposal,
    ChampionsRegionProposal,
    ChampionsWorld,
)
from rulehall.engines.pokemon.trainers import check_key_lines, check_rivals
from rulehall.engines.rooms.worldsmith import check_next as check_room_map_next
from rulehall.engines.rooms.worldsmith import check_opening as check_room_map_opening

WORLDSMITH_GUIDANCE = (
    "POKEMON CHAMPIONS AUTHORING\n"
    "Each map is the host city of one event of the circuit season. Write a few places: the "
    "venue where the matches are played, the hotel, a practice hall or cafe where players test "
    "teams, and a street or station between them. `event` names the event: its `tier` from "
    "SEASON, a `name` that carries the tier, such as 'Lumiose Locals', the `venue_id` of the "
    "venue, and the `battle_background` of its matches, such as 'gen3-arena' or 'gen6-city'. "
    "The start reaches the venue without a lock. "
    f"Write at most {KEY_TRAINERS_MAX} key trainers: players of this event with an "
    "`archetype_id` from ARCHETYPES and, if they have a signature Pokemon, an `ace_species_id` "
    "from ACE SPECIES. Every key trainer and the rival has a `style`, a `win_line` and a "
    "`lose_line`. The opening map holds one rival, with `rival` true and no archetype: code "
    "builds the rival's team and brings the rival to every event. A later map adds no rival. "
    "Other people, such as judges, staff, friends and fans, do not play. Every person has an "
    "`avatar_id` from TRAINER LOOKS: a rival look goes only to the rival; everyone else takes "
    "a class. Never write `sheet` or `team`. Code writes every team."
)


def check_opening(proposal: ChampionsOpeningProposal) -> None:
    check_room_map_opening(proposal)
    _check_champions_map(proposal, opening=True, unlocked=("locals",), used_team_ids=())


def check_next(proposal: ChampionsRegionProposal, world: ChampionsWorld) -> None:
    check_room_map_next(proposal, world)
    _check_champions_map(
        proposal,
        opening=False,
        unlocked=world.player_sheet.unlocked_tiers(),
        used_team_ids=world.used_team_ids,
    )


def _check_champions_map(
    proposal: ChampionsMapProposal,
    *,
    opening: bool,
    unlocked: Collection[Tier],
    used_team_ids: Collection[Slug],
) -> None:
    event = proposal.event
    tier = TIERS[event.tier]
    if event.tier not in unlocked:
        open_names = ", ".join(TIERS[each].name for each in unlocked)
        raise Refusal(f"{tier.name} is not open to the player; open tiers: {open_names}")
    if tier.name.casefold() not in event.name.casefold():
        raise Refusal(f"the event's name carries its tier: {tier.name}")
    if event.venue_id not in proposal.places:
        raise Refusal(f"`event.venue_id` {event.venue_id!r} is no place of this map")
    if event.venue_id not in proposal.reachable(proposal.start_id):
        raise Refusal(f"the venue {event.venue_id!r} is reached from the start without a lock")
    trainers = list(proposal.npcs.values())
    if written := [npc.id for npc in trainers if npc.team]:
        raise Refusal(f"never write `team`; code writes it: {written}")
    check_rivals(trainers, opening=opening)
    keys = [npc for npc in trainers if npc.is_key()]
    check_key_lines(keys, KEY_TRAINER)
    players = [npc for npc in keys if npc.archetype_id is not None]
    if len(players) > KEY_TRAINERS_MAX:
        raise Refusal(f"at most {KEY_TRAINERS_MAX} key trainers play in one event")
    pools = key_team_pools(event.tier)
    used = list(used_team_ids)
    unbuilt: list[str] = []
    for npc in players:
        assert npc.archetype_id is not None
        try:
            real_team, _ = build_key_team(
                npc.archetype_id, npc.ace_species_id, pools, used, Random(0)
            )
        except Refusal as refused:
            unbuilt.append(f"{npc.id}: {refused}")
            continue
        if real_team is not None:
            used.append(real_team.team_id)
    if unbuilt:
        raise Refusal("pick another ace or archetype; " + "; ".join(unbuilt))
