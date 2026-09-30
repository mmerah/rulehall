import json
from asyncio import Task, create_task, gather
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from random import Random
from typing import Literal, Self

from rulehall.core.facts import Fact
from rulehall.core.game import RoleAnswer
from rulehall.core.stores import read_cached_text
from rulehall.core.validation import Loose, parse_json
from rulehall.core.views import BattleChoice, BattleHeader
from rulehall.engines.battles import Transport
from rulehall.engines.engine import Resolution
from rulehall.engines.pokemon.battle.assessment import Assessment
from rulehall.engines.pokemon.battle.choices import (
    Hand,
    SeatRequest,
    SideRequest,
    opponent_choice,
)
from rulehall.engines.pokemon.battle.header import battle_header
from rulehall.engines.pokemon.battle.highlights import battle_highlights
from rulehall.engines.pokemon.battle.models import (
    STATUSES,
    TERRAINS,
    WEATHERS,
    Ally,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
    DumpMon,
    Edge,
    Outcome,
    Policy,
    RoleSeat,
    Seat,
)
from rulehall.engines.pokemon.battle.opponent import (
    Offer,
    OpponentAnswer,
    check_commands,
    greedy_choice,
    render_opponent,
)
from rulehall.engines.pokemon.panels import item_sprite
from rulehall.engines.pokemon.rules import TIMES
from rulehall.engines.pokemon.world import PokemonGame

type SideId = Literal["p1", "p2"]

SINGLES_FORMAT = "gen9customgame@@@Terastal Clause"
DOUBLES_FORMAT = "gen9doublescustomgame@@@Terastal Clause"
SHOWDOWN = Path(__file__).parents[1] / "showdown"
ASSESS_JS = SHOWDOWN / "assess.js"
BOSS_BEATEN = (
    "The boss is beaten. Tell how it ended from WHAT HAPPENED, then close the story in a short "
    "epilogue."
)
BATTLE_OVER = (
    "The battle is over. Tell how it ended from WHAT HAPPENED, in a few sentences. The player "
    "watched every move, so do not tell the fight again; you may give one short nod to a "
    "highlight. Settle nothing else."
)
SIDES: tuple[SideId, ...] = ("p1", "p2")
SIDE_OF: dict[RoleSeat, SideId] = {"foe": "p2", "ally": "p1"}
TURN_ENDS = ("|upkeep", "|turn|", "|win|", "|tie")
BACK = "back"
NEXT = "next"
BALL = "ball "
LEAVE = "leave"
DUMPED = '||<<< "'
SNAPSHOT = (
    "Object.fromEntries([battle.p1, battle.p2].map((side) => [side.id, "
    "side.pokemon.map((mon) => ({slot: side.team.indexOf(mon.set), hp: mon.hp, "
    "status: mon.status, pp: mon.baseMoveSlots.map((move) => move.pp), "
    "out: mon.previouslySwitchedIn, held: !mon.lastItem, active: mon.isActive, "
    "boosts: mon.boosts}))]))"
)
DUMP = f">eval JSON.stringify({SNAPSHOT})"
RESTORE = (
    ">eval const states = STATES; [battle.p1, battle.p2].forEach((side, number) => "
    "states[number].forEach(([hp, status, pp], index) => { const mon = side.pokemon[index]; "
    "mon.sethp(hp); if (status) mon.setStatus(status, null, null, true); "
    "mon.baseMoveSlots.forEach((slot, move) => { slot.pp = pp[move]; }); }))"
)
# A duration of 0 never runs out: story weather and terrain last until a move changes them.
WEATHER_JS = "battle.field.setWeather('{id}', 'debug'); battle.field.weatherState.duration = 0"
TERRAIN_JS = "battle.field.setTerrain('{id}', 'debug'); battle.field.terrainState.duration = 0"
EDGE_JS: dict[Edge, str] = {
    "foe-asleep": "battle.p2.active[0].setStatus('slp', null, null, true)",
    "foe-paralysed": "battle.p2.active[0].setStatus('par', null, null, true)",
    "attack-up": "battle.boost({atk: 1}, battle.p1.active[0])",
    "special-attack-up": "battle.boost({spa: 1}, battle.p1.active[0])",
    "speed-up": "battle.boost({spe: 1}, battle.p1.active[0])",
    "stealth-rock": "battle.p2.addSideCondition('stealthrock', 'debug')",
    "spikes": "battle.p2.addSideCondition('spikes', 'debug')",
}


class Dump(Loose):
    p1: tuple[DumpMon, ...]
    p2: tuple[DumpMon, ...]
    assessment: Assessment | None = None


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


@dataclass(slots=True, kw_only=True)
class ShowdownRun:
    battle: Battle
    transport: Transport
    policy: Policy
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
    thinking: dict[RoleSeat, Task[OpponentAnswer]] = field(default_factory=dict)
    said: list[str] = field(default_factory=list)
    picks: list[str] = field(default_factory=list)
    aiming: str = ""

    @classmethod
    async def start(
        cls,
        draft: PokemonGame,
        transport: Transport,
        opponent: RoleAnswer | None = None,
    ) -> Self:
        battle = draft.world.battle
        assert battle is not None
        policy = battle.setup.policy
        if policy == "model" and opponent is None:
            policy = "scripted"
        run = cls(
            battle=battle,
            transport=transport,
            policy=policy,
            opponent=opponent if policy == "model" or battle.setup.ally is not None else None,
            facts=[
                *(draft.world.player.card_fact(text) for text in battle.setup.condition_texts()),
                *(throw.fact for throw in battle.throws),
            ],
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

    def header(self) -> BattleHeader:
        assert self.dump is not None
        return battle_header(
            self.setup, self.dump.p1, self.dump.p2, self.log, self._deciding_slot()
        )

    def choices(self) -> tuple[BattleChoice, ...]:
        request = self.side_request
        if request is None:
            return ()
        refusal = self._ball_refusal(request)
        balls = tuple(
            BattleChoice(
                command=f"{BALL}{ball.item_id}",
                kind="item",
                name=f"{ball.name} {TIMES}{ball.count}",
                refusal=refusal,
                sprite=item_sprite(ball.item_id),
            )
            for ball in self.battle.balls_left()
        )
        leave = BattleChoice(
            command=LEAVE, kind="leave", name="Run" if self.setup.wild else "Forfeit"
        )
        return (*self._slot_choices(request), *balls, leave)

    async def choose(self, draft: PokemonGame, command: str, rng: Random) -> None:
        draft.world.battle = self.battle
        if command == LEAVE:
            await self._end("fled" if self.setup.wild else "lost")
        elif command.startswith(BALL):
            throw = draft.world.throw_ball(command.removeprefix(BALL), self._foe(), rng)
            self.facts.append(throw.fact)
            if throw.caught:
                await self._end("caught")
        elif command == BACK:
            if self.aiming:
                self.aiming = ""
            else:
                self.picks.pop()
        else:
            await self._pick(command)
        self._settle(draft)

    async def close(self) -> None:
        for thinking in self.thinking.values():
            thinking.cancel()
        await gather(*self.thinking.values(), return_exceptions=True)
        await self.transport.close()

    def _deciding_slot(self) -> int | None:
        request = self.side_request
        if request is None:
            return None
        slots = self._seated("player", request).deciding_slots()
        return slots[len(self.picks)] if slots else None

    def _slot_choices(self, request: SideRequest) -> tuple[BattleChoice, ...]:
        seated = self._seated("player", request)
        slots = seated.deciding_slots()
        if not slots:
            help = "None of your Pokemon can act. Your partner fights this turn."
            return (BattleChoice(command=NEXT, kind="next", name="Next turn", help=help),)
        slot = slots[len(self.picks)]
        choices = (
            seated.target_choices(slot, self.aiming)
            if self.aiming
            else seated.choices(slot, self.picks)
        )
        if not (self.picks or self.aiming):
            return choices
        back = BattleChoice(
            command=BACK, kind="back", name="Back", group=request.side.pokemon[slot].name
        )
        return (*choices, back)

    async def _pick(self, command: str) -> None:
        request = self.side_request
        assert request is not None
        slots = self._seated("player", request).deciding_slots()
        if command != NEXT:
            if not self.aiming and request.needs_target(slots[len(self.picks)], command):
                self.aiming = command
                return
            self.aiming = ""
            self.picks.append(command)
        if len(self.picks) == len(slots):
            picked = dict(zip(slots, self.picks, strict=True)) | await self._decide("ally", request)
            self.picks = []
            await self._play([f">p1 {request.joined(picked)}"])

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
            self.resolution = end_battle(draft, self.result)

    async def _block(self) -> Block:
        return Block.of(await self.transport.receive())

    def _hand(self, seat: Seat) -> Hand:
        assert self.dump is not None
        if seat == "foe":
            return frozenset(range(len(self.dump.p2)))
        allied = len(self.setup.team)
        return frozenset(
            at for at, mon in enumerate(self.dump.p1) if (mon.slot >= allied) == (seat == "ally")
        )

    def _slots(self, seat: Seat) -> frozenset[int]:
        tag = self.setup.ally is not None
        match seat:
            case "ally":
                return frozenset({1} if tag else ())
            case "player" if tag:
                return frozenset({0})
            case _:
                return frozenset(range(2 if self.setup.double else 1))

    def _seated(self, seat: Seat, ask: SideRequest) -> SeatRequest:
        assert self.dump is not None
        dumped, battlers, foe = (
            (self.dump.p2, self.setup.foes, "p1")
            if seat == "foe"
            else (self.dump.p1, self.setup.player_side(), "p2")
        )
        return SeatRequest(
            request=ask,
            battlers=tuple(battlers[mon.slot] for mon in dumped),
            foe_side=self.asks[foe].side,
            hand=self._hand(seat),
            slots=self._slots(seat),
        )

    def _ally(self) -> Ally:
        assert self.setup.ally is not None
        return self.setup.ally

    async def _think(self, seat: RoleSeat, ask: SideRequest) -> Task[OpponentAnswer] | None:
        role = self.opponent
        if role is None or (seat == "foe" and self.policy != "model"):
            return None
        if ask.wait or ask.team_preview:
            return None
        seated = self._seated(seat, ask)
        offers = tuple(
            Offer(
                slot=slot,
                mon_name=ask.side.pokemon[slot].name,
                choices=tuple(
                    choice for choice in seated.aimed_choices(slot, ()) if not choice.refusal
                ),
            )
            for slot in seated.deciding_slots()
        )
        if all(len(offer.choices) == 1 for offer in offers):
            return None
        assessment = await self._assess(SIDE_OF[seat])
        prompt = render_opponent(self.setup, seat, assessment, offers, self._hand(seat), self.log)
        return create_task(role(prompt, OpponentAnswer, partial(check_commands, offers)))

    async def _decide(self, seat: RoleSeat, ask: SideRequest) -> dict[int, str]:
        seated = self._seated(seat, ask)
        slots = seated.deciding_slots()
        if not slots:
            return {}
        if ask.team_preview:
            leads = sorted(seated.hand)
            return {slot: f"team {at + 1}" for slot, at in zip(slots, leads, strict=False)}
        if thinking := self.thinking.pop(seat, None) or await self._think(seat, ask):
            answer = await thinking
            if answer.line:
                name = self.setup.foe_name if seat == "foe" else self._ally().name
                self.said.append(f"|c|{name}|{answer.line}")
            return dict(zip(slots, answer.commands, strict=True))
        if self.policy == "random":
            rng = Random(f"{self.setup.seed} {len(self.inputs)}")
            return {slot: opponent_choice(ask, rng) for slot in slots}
        assessment = await self._assess(SIDE_OF[seat])
        picks: list[str] = []
        for slot in slots:
            picks.append(greedy_choice(assessment, seated.aimed_choices(slot, picks), slot))
        return dict(zip(slots, picks, strict=True))

    async def _assess(self, side: SideId) -> Assessment:
        await self.transport.send([assess_line(side)])
        self._read(await self._block())
        assert self.dump is not None and self.dump.assessment is not None
        return self.dump.assessment

    async def _play(self, queue: list[str]) -> None:
        while self.result is None:
            if all(side in self.asks for side in SIDES):
                # The leads are out once team preview is answered: the conditions go in then.
                opening = condition_lines(self.setup) if self.asks["p1"].team_preview else ()
                lines: list[str] = []
                for side in SIDES:
                    ask = self.asks[side]
                    if ask.wait:
                        continue
                    if queue:
                        lines.append(queue.pop(0))
                    elif side == "p2":
                        self.side_request = None
                        lines.append(f">p2 {ask.joined(await self._decide('foe', ask))}")
                    elif self._waits_on_player(ask):
                        for seat, seat_side in SIDE_OF.items():
                            if thinking := await self._think(seat, self.asks[seat_side]):
                                self.thinking[seat] = thinking
                        self.side_request = ask
                        return
                    else:
                        lines.append(f">p1 {ask.joined(await self._decide('ally', ask))}")
                self.inputs.extend(lines)
                self.asks.clear()
                self.side_request = None
                self.thinking.clear()
                await self.transport.send([*lines, *opening, DUMP])
            self._read(await self._block())

    def _waits_on_player(self, ask: SideRequest) -> bool:
        # A player with no Pokemon to play still sees each turn, to watch it or to forfeit.
        new_turn = bool(ask.active) and not (ask.team_preview or any(ask.force_switch))
        return new_turn or bool(self._seated("player", ask).deciding_slots())

    def _read(self, block: Block) -> None:
        match block.kind:
            case "update":
                view, dump = read_update(block.lines, opening=not self.log)
                # Chat lines go before the turn's end marker so they show inside the turn they
                # were chosen for.
                if self.said and view:
                    ends = (at for at, line in enumerate(view) if line.startswith(TURN_ENDS))
                    at = next(ends, len(view))
                    view = (*view[:at], *self.said, *view[at:])
                    self.said.clear()
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
                highlights = battle_highlights(self.battle, self.log)
                self.result = battle_result(self.setup, self.dump, self.outcome, highlights)


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
        for side in (setup.player_side(), setup.foes)
    ]
    format_id = DOUBLES_FORMAT if setup.double else SINGLES_FORMAT
    p1 = {
        "name": setup.player_name,
        "avatar": setup.player_avatar_id,
        "team": _packed_team(setup.player_side()),
    }
    p2 = {
        "name": setup.foe_name,
        "avatar": setup.foe_avatar_id or "",
        "team": _packed_team(setup.foes),
    }
    return (
        f">start {json.dumps({'formatid': format_id, 'seed': list(setup.seed)})}",
        f">player p1 {json.dumps(p1)}",
        f">player p2 {json.dumps(p2)}",
        RESTORE.replace("STATES", json.dumps(states)),
        DUMP,
    )


def condition_lines(setup: BattleSetup) -> tuple[str, ...]:
    # The edge goes first: a misty or electric terrain would block its sleep.
    code = (
        "" if setup.edge is None else EDGE_JS.get(setup.edge, ""),
        "" if setup.weather is None else WEATHER_JS.format(id=WEATHERS[setup.weather].showdown_id),
        "" if setup.terrain is None else TERRAIN_JS.format(id=TERRAINS[setup.terrain].showdown_id),
    )
    joined = "; ".join(part for part in code if part)
    return (f">eval {joined}",) if joined else ()


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


def assess_line(side: SideId) -> str:
    # `>eval` turns each form feed back into a newline, so the file goes as one input line.
    code = "\f".join(line for line in read_cached_text(ASSESS_JS).splitlines() if line)
    opposite = "p2" if side == "p1" else "p1"
    code = code.replace("SIDES", f"battle.{side}, battle.{opposite}")
    return f">eval JSON.stringify({{...{SNAPSHOT}, assessment: {code}}})"


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


def battle_result(
    setup: BattleSetup, dump: Dump, outcome: Outcome | None, highlights: tuple[str, ...]
) -> BattleResult:
    won = all(mon.hp == 0 for mon in dump.p2) and any(mon.hp > 0 for mon in dump.p1)
    decided: Outcome = outcome or ("won" if won else "lost")
    # An ally's Pokemon come after the player's and fight fresh each battle: none is kept.
    own = tuple(mon for mon in dump.p1 if mon.slot < len(setup.team))
    return BattleResult(
        outcome=decided,
        team=tuple(as_dumped(setup.team[mon.slot], mon) for mon in own),
        sent_out_foes=tuple(
            as_dumped(setup.foes[mon.slot], mon)
            for mon in sorted(dump.p2, key=lambda foe: foe.slot)
            if mon.out > 0
        ),
        on_field_mon_ids=tuple(setup.team[mon.slot].mon_id for mon in own if mon.out > 0),
        caught=_first_foe(setup, dump) if decided == "caught" else None,
        highlights=highlights,
    )


def _packed_team(battlers: Sequence[Battler]) -> str:
    return "]".join(packed(battler) for battler in battlers)


def _first_foe(setup: BattleSetup, dump: Dump) -> Battler:
    return as_dumped(setup.foes[0], next(mon for mon in dump.p2 if mon.slot == 0))


def end_battle(draft: PokemonGame, result: BattleResult) -> Resolution:
    facts, notes = draft.world.settle_battle(result)
    for note in notes:
        draft.note(note)
    return Resolution(
        tuple(facts), BOSS_BEATEN if draft.world.evil_team.boss_beaten else BATTLE_OVER
    )
