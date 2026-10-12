from collections.abc import Iterable, Sequence

from rulehall.engines.pokemon.battle.assessment import FULL, AimedHit, Assessment, OwnMon
from rulehall.engines.pokemon.battle.history import turns_on_field
from rulehall.engines.pokemon.battle.models import SIDE_OF, RoleSeat
from rulehall.engines.pokemon.battle.views import BattleChoice

LOSING_EDGE = -25
SWITCH_GAIN = 30
SETTLE_TURNS = 2
SPENT_SHARE = 33
POSITION_LETTERS = "ab"


def greedy_choice(assessment: Assessment, choices: Sequence[BattleChoice], slot: int) -> str:
    team = {mon.slot: mon for mon in assessment.team}
    # The actives lead the team, in field order: field slot 0 is team slot 1.
    active = team.get(slot + 1)
    partnered = any(mon.active and mon.hp > 0 and mon.slot != slot + 1 for mon in assessment.team)
    spread = {
        f"move {number}"
        for number, move in enumerate(() if active is None else active.moves, 1)
        if partnered and move.target == "allAdjacent"
    }
    allowed = [choice.command for choice in choices if not choice.refusal]
    offered = [command for command in allowed if command not in spread] or allowed
    hits = {
        command: _aimed_hits(active, command)
        for command in offered
        if active is not None and command.startswith("move ")
    }
    knockouts = [command for command, aimed in hits.items() if any(h.knocks_out for h in aimed)]
    if knockouts:
        return knockouts[0]
    shares = {command: share for command, aimed in hits.items() if (share := _best_share(aimed))}
    bench = {
        command: share
        for number, command in _numbered(offered, "switch").items()
        if (share := _best_share(hit for move in team[number].moves for hit in move.hits))
    }
    best = max(shares, key=shares.__getitem__, default=None) or max(
        bench, key=bench.__getitem__, default=None
    )
    return best or offered[0]


def advised_switch(
    assessment: Assessment,
    choices: Sequence[BattleChoice],
    slot: int,
    seat: RoleSeat,
    log: Sequence[str],
) -> str | None:
    advice = switch_for(assessment, choices, slot, seat, log)
    return None if advice is None else advice[0]


def switch_for(
    assessment: Assessment,
    choices: Sequence[BattleChoice],
    slot: int,
    seat: RoleSeat,
    log: Sequence[str],
) -> tuple[str, OwnMon] | None:
    team = {mon.slot: mon for mon in assessment.team}
    active = team.get(slot + 1)
    if (
        active is None
        or active.hp * FULL < SPENT_SHARE * active.maxhp
        or turns_on_field(log, _position(seat, slot)) < SETTLE_TURNS
        or active.matchup_edge() > LOSING_EDGE
    ):
        return None
    allowed = [choice.command for choice in choices if not choice.refusal]
    better = {
        command: team[number]
        for number, command in _numbered(allowed, "switch").items()
        if team[number].sure_taken() < active.sure_taken()
        and team[number].matchup_edge() - active.matchup_edge() >= SWITCH_GAIN
    }
    best = max(better, key=lambda command: better[command].matchup_edge(), default=None)
    return None if best is None else (best, better[best])


def _position(seat: RoleSeat, slot: int) -> str:
    return SIDE_OF[seat] + POSITION_LETTERS[slot]


def _numbered(commands: Sequence[str], verb: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for command in commands:
        head, _, number = command.partition(" ")
        if head == verb:
            found[int(number)] = command
    return found


def _aimed_hits(mon: OwnMon, command: str) -> tuple[AimedHit, ...]:
    _, number, *target = command.split()
    hits = mon.moves[int(number) - 1].hits if int(number) <= len(mon.moves) else ()
    return tuple(
        hit for hit in hits if hit.target > 0 and (not target or hit.target == int(target[0]))
    )


def _best_share(hits: Iterable[AimedHit]) -> int:
    return max((hit.dealt_share for hit in hits if hit.target > 0), default=0)
