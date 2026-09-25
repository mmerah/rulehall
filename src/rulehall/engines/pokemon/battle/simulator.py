import json
from asyncio import Task, create_task, gather
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from random import Random
from typing import Literal, Protocol, Self

from pydantic import Field

from rulehall.core.facts import Fact
from rulehall.core.io import read_cached_text
from rulehall.core.model import RoleAnswer
from rulehall.core.validation import Loose, Slug, parse_json
from rulehall.core.views import Choice
from rulehall.engines.engine import Resolution, Transport
from rulehall.engines.pokemon.battle.models import (
    STATUSES,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
    Outcome,
    Throw,
)
from rulehall.engines.pokemon.battle.opponent import (
    Assessment,
    OpponentAnswer,
    check_command,
    render_opponent,
)
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.panels import type_tag
from rulehall.engines.pokemon.rules import TIMES, max_hp
from rulehall.engines.pokemon.world import PokemonGame

FORMAT = "gen9customgame@@@Terastal Clause"
SHOWDOWN = Path(__file__).parents[1] / "showdown"
ASSESS_JS = SHOWDOWN / "assess.js"
SIDES = ("p1", "p2")
SWITCH = "Switch"
BALLS = "Balls"
BALL = "ball "
LEAVE = "leave"
DUMPED = '||<<< "'
SNAPSHOT = (
    "Object.fromEntries([battle.p1, battle.p2].map((side) => [side.id, "
    "side.pokemon.map((mon) => ({slot: side.team.indexOf(mon.set), hp: mon.hp, "
    "status: mon.status, pp: mon.baseMoveSlots.map((move) => move.pp), "
    "out: mon.previouslySwitchedIn, held: !mon.lastItem}))]))"
)
DUMP = f">eval JSON.stringify({SNAPSHOT})"
RESTORE = (
    ">eval const states = STATES; [battle.p1, battle.p2].forEach((side, number) => "
    "states[number].forEach(([hp, status, pp], index) => { const mon = side.pokemon[index]; "
    "mon.sethp(hp); if (status) mon.setStatus(status, null, null, true); "
    "mon.baseMoveSlots.forEach((slot, move) => { slot.pp = pp[move]; }); }))"
)


class DumpMon(Loose):
    slot: int
    hp: int
    status: str
    pp: tuple[int, ...]
    out: int
    held: bool


class Dump(Loose):
    p1: tuple[DumpMon, ...]
    p2: tuple[DumpMon, ...]
    assessment: Assessment | None = None


class RequestMove(Loose):
    move: str
    id: str
    pp: int | None = None
    maxpp: int | None = None
    disabled: bool | str = False


class ActiveRequest(Loose):
    moves: tuple[RequestMove, ...]
    trapped: bool = False


class SideMon(Loose):
    details: str
    condition: str
    active: bool

    @property
    def fainted(self) -> bool:
        return self.condition.endswith(" fnt")

    @property
    def name(self) -> str:
        return self.details.partition(",")[0]


class Side(Loose):
    pokemon: tuple[SideMon, ...]


class SideRequest(Loose):
    side: Side
    active: tuple[ActiveRequest, ...] = ()
    force_switch: tuple[bool, ...] = Field(default=(), alias="forceSwitch")
    team_preview: bool = Field(default=False, alias="teamPreview")
    wait: bool = False


@dataclass(frozen=True, slots=True)
class Block:
    kind: Literal["update", "sideupdate", "end"]
    lines: tuple[str, ...]

    @classmethod
    def of(cls, lines: Sequence[str]) -> Self:
        kind, *rest = lines
        match kind:
            case "update" | "sideupdate" | "end":
                return cls(kind, tuple(rest))
            case _:
                raise ValueError(f"unknown simulator block {kind!r}")


class Rules(Protocol):
    def end_battle(self, draft: PokemonGame, result: BattleResult, /) -> Resolution: ...
    def throw_ball(
        self, draft: PokemonGame, ball_id: Slug, foe: Battler, rng: Random, /
    ) -> Throw: ...


@dataclass(slots=True, kw_only=True)
class ShowdownRun:
    battle: Battle
    transport: Transport
    rules: Rules
    opponent: RoleAnswer | None = None
    inputs: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    asks: dict[str, SideRequest] = field(default_factory=dict)
    side_request: SideRequest | None = None
    dump: Dump | None = None
    outcome: Outcome | None = None
    result: BattleResult | None = None
    resolution: Resolution | None = None
    thinking: Task[OpponentAnswer] | None = None

    @classmethod
    async def start(
        cls,
        draft: PokemonGame,
        transport: Transport,
        rules: Rules,
        opponent: RoleAnswer | None = None,
    ) -> Self:
        battle = draft.world.battle
        assert battle is not None
        run = cls(
            battle=battle,
            transport=transport,
            rules=rules,
            # A wild Pokemon has no trainer: it picks at random, as in the games.
            opponent=opponent if battle.setup.kind == "trainer" else None,
            facts=[throw.fact for throw in battle.throws],
        )
        await transport.send(start_lines(battle.setup))
        await run._play(list(battle.inputs))
        if battle.throws and battle.throws[-1].caught:
            await run._end("caught")
        run._settle(draft)
        return run

    @property
    def setup(self) -> BattleSetup:
        return self.battle.setup

    def props(self) -> Mapping[str, str | bool]:
        return {"wild": self.setup.kind == "wild"}

    def choices(self) -> tuple[Choice, ...]:
        request = self.side_request
        if request is None:
            return ()
        refusal = self._ball_refusal(request)
        balls = tuple(
            Choice(
                command=f"{BALL}{ball.item_id}",
                name=f"{ball.name} {TIMES}{ball.count}",
                group=BALLS,
                refusal=refusal,
            )
            for ball in self.battle.balls_left()
        )
        leave = Choice(command=LEAVE, name="Run" if self.setup.kind == "wild" else "Forfeit")
        return (*choices_of(request, self.setup.team), *balls, leave)

    async def choose(self, draft: PokemonGame, command: str, rng: Random) -> None:
        # The run keeps the record between calls; each draft is a fresh copy of the save.
        draft.world.battle = self.battle
        if command == LEAVE:
            await self._end("fled" if self.setup.kind == "wild" else "lost")
        elif command.startswith(BALL):
            throw = self.rules.throw_ball(draft, command.removeprefix(BALL), self._foe(), rng)
            self.facts.append(throw.fact)
            if throw.caught:
                await self._end("caught")
        else:
            await self._play([f">p1 {command}"])
        self._settle(draft)

    async def close(self) -> None:
        if self.thinking is not None:
            self.thinking.cancel()
            await gather(self.thinking, return_exceptions=True)
        await self.transport.close()

    def _foe(self) -> Battler:
        assert self.dump is not None
        return _first_foe(self.setup, self.dump)

    def _ball_refusal(self, request: SideRequest) -> str:
        if request.team_preview or any(request.force_switch):
            return "Send out a Pokemon first"
        return "" if self.battle.can_throw() else "One ball a turn"

    async def _end(self, outcome: Literal["lost", "fled", "caught"]) -> None:
        self.outcome = outcome
        self.asks.clear()
        self.side_request = None
        await self.transport.send([">forcewin p1" if outcome == "caught" else ">forcewin p2", DUMP])
        while self.result is None:
            self._read(await self._block())

    def _settle(self, draft: PokemonGame) -> None:
        self.battle.inputs = list(self.inputs)
        draft.world.battle = self.battle
        if self.result is not None:
            self.resolution = self.rules.end_battle(draft, self.result)

    async def _block(self) -> Block:
        return Block.of(await self.transport.receive())

    async def _think(self, ask: SideRequest) -> Task[OpponentAnswer] | None:
        if self.opponent is None or ask.wait or ask.team_preview:
            return None
        choices = tuple(choice for choice in choices_of(ask, self.setup.foes) if not choice.refusal)
        if len(choices) == 1:
            return None
        await self.transport.send([assess_line()])
        self._read(await self._block())
        assert self.dump is not None and self.dump.assessment is not None
        prompt = render_opponent(self.setup, self.dump.assessment, choices)
        return create_task(self.opponent(prompt, OpponentAnswer, partial(check_command, choices)))

    async def _play(self, queue: list[str]) -> None:
        while self.result is None:
            if all(side in self.asks for side in SIDES):
                lines: list[str] = []
                for side in SIDES:
                    ask = self.asks[side]
                    if ask.wait:
                        continue
                    if queue:
                        lines.append(queue.pop(0))
                    elif side == "p1":
                        self.thinking = await self._think(self.asks["p2"])
                        self.side_request = ask
                        return
                    elif thinking := self.thinking or await self._think(ask):
                        # The buttons go while the opponent thinks, until the next request.
                        self.side_request = None
                        lines.append(f">p2 {(await thinking).command}")
                    else:
                        rng = Random(f"{self.setup.seed} {len(self.inputs)}")
                        lines.append(f">p2 {opponent_choice(ask, rng)}")
                self.inputs.extend(lines)
                self.asks.clear()
                self.side_request = None
                self.thinking = None
                await self.transport.send([*lines, DUMP])
            self._read(await self._block())

    def _read(self, block: Block) -> None:
        match block.kind:
            case "update":
                view, dump = read_update(block.lines, opening=not self.log)
                self.log.extend(view)
                if dump is not None:
                    self.dump = dump
            case "sideupdate":
                side, *messages = block.lines
                for message in messages:
                    if message.startswith("|error|"):
                        raise ValueError(message)
                    if message.startswith("|request|") and message != "|request|null":
                        self.asks[side] = parse_json(SideRequest, message.removeprefix("|request|"))
            case "end":
                assert self.dump is not None
                self.result = battle_result(self.setup, self.dump, self.outcome)


def packed(battler: Battler) -> str:
    moves = ",".join(move.move_id for move in battler.moves)
    gender = "" if battler.gender == "N" else battler.gender
    evs, ivs = (",".join(map(str, stats)) for stats in (battler.evs, battler.ivs))
    return (
        f"{battler.name}|{battler.species_id}|{battler.item_id or ''}|{battler.ability}|{moves}"
        f"|{battler.nature}|{evs}|{gender}|{ivs}||{battler.level}|{battler.friendship}"
    )


def start_lines(setup: BattleSetup) -> tuple[str, ...]:
    states = [
        [[battler.hp, battler.status, [move.pp for move in battler.moves]] for battler in side]
        for side in (setup.team, setup.foes)
    ]
    p1 = {
        "name": setup.player_name,
        "avatar": setup.player_avatar_id,
        "team": _packed_team(setup.team),
    }
    p2 = {
        "name": setup.foe_name,
        "avatar": setup.foe_avatar_id or "",
        "team": _packed_team(setup.foes),
    }
    return (
        f">start {json.dumps({'formatid': FORMAT, 'seed': list(setup.seed)})}",
        f">player p1 {json.dumps(p1)}",
        f">player p2 {json.dumps(p2)}",
        RESTORE.replace("STATES", json.dumps(states)),
        DUMP,
    )


def read_update(lines: Sequence[str], *, opening: bool) -> tuple[tuple[str, ...], Dump | None]:
    view: list[str] = []
    dump: Dump | None = None
    rows = iter(lines)
    for line in rows:
        if line.startswith("|split|"):
            line = next(rows)
            next(rows)
        if line.startswith(DUMPED):
            dump = parse_json(Dump, line.removeprefix(DUMPED).removesuffix('"'))
        elif line.startswith("||<<< error"):
            raise ValueError(line)
        elif not line.startswith(("||", "|debug|")) and not (opening and line.startswith("|-")):
            view.append(line)
    return tuple(view), dump


def opponent_choice(request: SideRequest, rng: Random) -> str:
    if request.team_preview:
        return "team 1"
    if any(request.force_switch):
        bench = [
            number
            for number, mon in enumerate(request.side.pokemon, 1)
            if not mon.active and not mon.fainted
        ]
        return f"switch {rng.choice(bench)}"
    moves = [number for number, move in enumerate(request.active[0].moves, 1) if not move.disabled]
    return f"move {rng.choice(moves)}"


def assess_line() -> str:
    # `>eval` turns each form feed back into a newline, so the file goes as one input line.
    code = "\f".join(line for line in read_cached_text(ASSESS_JS).splitlines() if line)
    return f">eval JSON.stringify({{...{SNAPSHOT}, assessment: {code}}})"


def choices_of(request: SideRequest, battlers: Sequence[Battler]) -> tuple[Choice, ...]:
    team = request.side.pokemon
    tags = {
        battler.name: tuple(type_tag(kind) for kind in dex().species[battler.species_id].types)
        for battler in battlers
    }
    if request.team_preview:
        # The preview request comes before RESTORE: its conditions are all full HP.
        return tuple(
            Choice(
                command=f"team {number}",
                name=mon.name,
                brief=f"HP {battler.hp}/{max_hp(battler)} {battler.status}".rstrip(),
                tags=tags.get(mon.name, ()),
            )
            for number, (mon, battler) in enumerate(zip(team, battlers, strict=True), 1)
        )
    switches = tuple(
        Choice(
            command=f"switch {number}",
            name=mon.name,
            brief=f"HP {mon.condition}",
            group=SWITCH,
            refusal="Fainted" if mon.fainted else "",
            tags=tags.get(mon.name, ()),
        )
        for number, mon in enumerate(team, 1)
        if not mon.active
    )
    if any(request.force_switch):
        return switches
    move_types = {move.move_id: move.type for battler in battlers for move in battler.moves}
    moves = tuple(
        Choice(
            command=f"move {number}",
            name=move.move,
            brief="" if move.pp is None else f"{move.pp}/{move.maxpp} PP",
            refusal="Disabled" if move.disabled else "",
            tags=(type_tag(kind),) if (kind := move_types.get(move.id)) else (),
        )
        for number, move in enumerate(request.active[0].moves, 1)
    )
    return moves if request.active[0].trapped else moves + switches


def as_dumped(battler: Battler, dumped: DumpMon) -> Battler:
    moves = tuple(
        move.model_copy(update={"pp": pp})
        for move, pp in zip(battler.moves, dumped.pp, strict=True)
    )
    status = dumped.status if dumped.status in STATUSES else ""
    item_id = battler.item_id if dumped.held else None
    return battler.model_copy(
        update={"hp": dumped.hp, "status": status, "moves": moves, "item_id": item_id}
    )


def battle_result(setup: BattleSetup, dump: Dump, outcome: Outcome | None) -> BattleResult:
    won = all(mon.hp == 0 for mon in dump.p2) and any(mon.hp > 0 for mon in dump.p1)
    decided: Outcome = outcome or ("won" if won else "lost")
    return BattleResult(
        outcome=decided,
        team=tuple(as_dumped(setup.team[mon.slot], mon) for mon in dump.p1),
        fainted_foes=tuple(setup.foes[mon.slot] for mon in dump.p2 if mon.hp == 0),
        on_field=tuple(setup.team[mon.slot].mon_id for mon in dump.p1 if mon.out > 0),
        caught=_first_foe(setup, dump) if decided == "caught" else None,
    )


def _packed_team(battlers: Sequence[Battler]) -> str:
    return "]".join(packed(battler) for battler in battlers)


def _first_foe(setup: BattleSetup, dump: Dump) -> Battler:
    return as_dumped(setup.foes[0], next(mon for mon in dump.p2 if mon.slot == 0))
