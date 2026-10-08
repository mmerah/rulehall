from collections.abc import Sequence
from dataclasses import dataclass
from random import Random

from pydantic import Field

from rulehall.core.validation import Loose
from rulehall.core.views import BattleChoice, Tag
from rulehall.engines.pokemon.battle.models import Battler, FormatSpec
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import max_hp
from rulehall.engines.pokemon.sprites import (
    category_tag,
    hp_meter,
    mon_sprite,
    move_stats,
    move_summary,
    pp_meter,
    status_tag,
    type_tag,
)

# The positions, in a side request, of one trainer's own Pokemon.
type Hand = frozenset[int]

PASS = "pass"
PICKED = "Picked for another Pokemon"
MEGA_SUFFIX = " mega"
TARGETED = frozenset({"normal", "any", "adjacentAlly", "adjacentAllyOrSelf", "adjacentFoe"})


class RequestMove(Loose):
    move: str
    id: str
    pp: int | None = None
    maxpp: int | None = None
    disabled: bool | str = False
    # A locked move, such as Recharge, comes without a target: Showdown aims it.
    target: str = ""


class ActiveRequest(Loose):
    moves: tuple[RequestMove, ...]
    trapped: bool = False
    can_mega_evo: bool = Field(default=False, alias="canMegaEvo")


class SideMon(Loose):
    ident: str
    condition: str
    active: bool

    @property
    def fainted(self) -> bool:
        return self.condition.endswith(" fnt")

    @property
    def hp(self) -> int:
        return int(self.condition.partition("/")[0].partition(" ")[0])

    @property
    def status(self) -> str:
        return self.condition.partition(" ")[2]

    @property
    def name(self) -> str:
        return self.ident.partition(": ")[2]


class Side(Loose):
    pokemon: tuple[SideMon, ...]


class SideRequest(Loose):
    side: Side
    active: tuple[ActiveRequest, ...] = ()
    force_switch: tuple[bool, ...] = Field(default=(), alias="forceSwitch")
    team_preview: bool = Field(default=False, alias="teamPreview")
    # Only a format that brings some of the team, such as 4 of 6, sets it.
    max_chosen_team_size: int | None = Field(default=None, alias="maxChosenTeamSize")
    wait: bool = False

    def joined(self, picked: dict[int, str]) -> str:
        if self.team_preview:
            return "team " + ", ".join(
                picked[slot].removeprefix("team ") for slot in sorted(picked)
            )
        fielded = len(self.force_switch) or len(self.active)
        return ", ".join(picked.get(slot, PASS) for slot in range(fielded))

    def needs_target(self, slot: int, command: str) -> bool:
        verb, _, number = command.partition(" ")
        return (
            verb == "move"
            and len(self.active) > 1
            and self.active[slot].moves[int(number) - 1].target in TARGETED
        )


@dataclass(frozen=True, slots=True)
class SeatRequest:
    request: SideRequest
    # The side's battlers in the request's order: the actives first, in field order.
    battlers: tuple[Battler, ...]
    foe_side: Side
    hand: Hand
    # The field slots this trainer plays, whoever's Pokemon stands there.
    slots: frozenset[int]
    spec: FormatSpec

    def deciding_slots(self) -> tuple[int, ...]:
        request = self.request
        if request.max_chosen_team_size is not None and request.team_preview:
            # Each pick is a position in the order brought: the leads first, then the back.
            return tuple(range(min(request.max_chosen_team_size, len(self.hand))))
        if request.team_preview:
            return tuple(sorted(self.slots))
        team = request.side.pokemon
        able = frozenset(at for at, mon in enumerate(team) if not mon.fainted)
        if any(request.force_switch):
            bench = frozenset(at for at in able if not team[at].active)
            forced = [slot for slot, needed in enumerate(request.force_switch) if needed]
            mine = [slot for slot in forced if slot in self.slots]
            theirs = [slot for slot in forced if slot not in self.slots]
            own_bench, their_bench = len(bench & self.hand), len(bench - self.hand)
            # Showdown fills every slot it can: a slot whose trainer has no bench left takes
            # the partner's.
            spare = max(own_bench - len(mine), 0)
            return tuple(sorted((*mine[:own_bench], *theirs[their_bench:][:spare])))
        mine_left, theirs_left = bool(able & self.hand), bool(able - self.hand)
        return tuple(
            slot
            for slot in range(len(request.active))
            if not team[slot].fainted and (mine_left if slot in self.slots else not theirs_left)
        )

    def choices(self, slot: int, picks: Sequence[str]) -> tuple[BattleChoice, ...]:
        request = self.request
        team = request.side.pokemon
        if request.team_preview:
            # The preview request comes before RESTORE: its conditions are all full HP.
            return tuple(
                _mon_choice(
                    f"team {at + 1}",
                    self.battlers[at],
                    self.battlers[at].hp,
                    self.battlers[at].status,
                    self.spec,
                    group=self._preview_group(slot),
                    refusal=self._preview_refusal(f"team {at + 1}", picks),
                )
                for at in sorted(self.hand)
            )
        user = team[slot].name if len(request.force_switch or request.active) > 1 else ""
        switches = tuple(
            _mon_choice(
                f"switch {at + 1}",
                self.battlers[at],
                mon.hp,
                mon.status,
                self.spec,
                group=user,
                refusal="Fainted" if mon.fainted else PICKED if f"switch {at + 1}" in picks else "",
            )
            for at, mon in enumerate(team)
            if not mon.active and at in self.hand
        )
        if any(request.force_switch):
            return switches
        active = request.active[slot]
        moves = tuple(
            BattleChoice(
                command=f"move {number}",
                kind="move",
                name=move.move,
                brief="" if (known := dex().moves.get(move.id)) is None else move_stats(known),
                help="" if known is None else move_summary(known),
                group=user,
                refusal="Disabled"
                if move.disabled
                else "No target"
                if request.needs_target(slot, f"move {number}")
                and not self._targets(slot, move.target)
                else "",
                tags=(
                    *self._move_tags(slot, move),
                    *(() if known is None else (category_tag(known.category),)),
                ),
                meters=()
                if move.pp is None or not move.maxpp
                else (pp_meter(move.pp, move.maxpp),),
            )
            for number, move in enumerate(active.moves, 1)
        )
        return moves if active.trapped else moves + switches

    def can_mega(self, slot: int, picks: Sequence[str]) -> bool:
        request = self.request
        return (
            not request.team_preview
            and not any(request.force_switch)
            and request.active[slot].can_mega_evo
            and not any(pick.endswith(MEGA_SUFFIX) for pick in picks)
        )

    def pick_label(self, position: int) -> str:
        leads = self.spec.active_slots
        return f"Lead {position + 1}" if position < leads else f"Back {position - leads + 1}"

    def target_choices(self, slot: int, command: str) -> tuple[BattleChoice, ...]:
        move = self.request.active[slot].moves[int(command.split()[1]) - 1]
        return tuple(
            BattleChoice(
                command=f"{command} {target}",
                kind="move",
                name=f"{move.move} at your ally {mon.name}"
                if target.startswith("-") and target != f"-{slot + 1}"
                else f"{move.move} at {mon.name}",
                group=self.request.side.pokemon[slot].name,
                tags=self._move_tags(slot, move),
            )
            for target, mon in self._targets(slot, move.target)
        )

    def aimed_choices(self, slot: int, picks: Sequence[str]) -> tuple[BattleChoice, ...]:
        return tuple(
            aimed
            for choice in self.choices(slot, picks)
            for aimed in (
                self.target_choices(slot, choice.command)
                if not choice.refusal and self.request.needs_target(slot, choice.command)
                else (choice,)
            )
        )

    def _preview_group(self, position: int) -> str:
        return "" if self.request.max_chosen_team_size is None else self.pick_label(position)

    def _preview_refusal(self, command: str, picks: Sequence[str]) -> str:
        if command not in picks:
            return ""
        if self.request.max_chosen_team_size is None:
            return PICKED
        return f"Picked: {self.pick_label(picks.index(command))}"

    def _move_tags(self, slot: int, move: RequestMove) -> tuple[Tag, ...]:
        kinds = {known.move_id: known.type for known in self.battlers[slot].moves}
        return (type_tag(kinds[move.id]),) if move.id in kinds else ()

    def _targets(self, slot: int, kind: str) -> tuple[tuple[str, SideMon], ...]:
        # A side lists its actives first, in field order; a foe is +N, an ally -N.
        fielded = len(self.request.active)
        own = self.request.side.pokemon
        foes = tuple((str(at), mon) for at, mon in enumerate(self.foe_side.pokemon[:fielded], 1))
        allies = tuple((f"-{at}", mon) for at, mon in enumerate(own[:fielded], 1) if at != slot + 1)
        match kind:
            case "adjacentFoe":
                aimed = foes
            case "adjacentAlly":
                aimed = allies
            case "adjacentAllyOrSelf":
                aimed = ((f"-{slot + 1}", own[slot]), *allies)
            case _:
                aimed = (*foes, *allies)
        return tuple((target, mon) for target, mon in aimed if mon.active and not mon.fainted)


def opponent_choice(request: SideRequest, rng: Random) -> str:
    if any(request.force_switch):
        bench = [
            number
            for number, mon in enumerate(request.side.pokemon, 1)
            if not mon.active and not mon.fainted
        ]
        return f"switch {rng.choice(bench)}"
    moves = [number for number, move in enumerate(request.active[0].moves, 1) if not move.disabled]
    return f"move {rng.choice(moves)}"


def _mon_choice(
    command: str,
    battler: Battler,
    hp: int,
    status: str,
    spec: FormatSpec,
    *,
    group: str = "",
    refusal: str = "",
) -> BattleChoice:
    return BattleChoice(
        command=command,
        kind="switch",
        name=battler.name,
        group=group,
        refusal=refusal,
        tags=(
            *(type_tag(kind) for kind in dex().species[battler.species_id].types),
            *((status_tag(status),) if status else ()),
        ),
        meters=(hp_meter(hp, max_hp(battler, stat_points=spec.stat_points)),),
        sprite=mon_sprite(dex().species[battler.species_id]),
    )
