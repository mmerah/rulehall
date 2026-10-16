import json
import logging
from asyncio import Task, create_task, gather
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from random import Random
from typing import Literal, Self

from rulehall.core.facts import Fact, Resolution
from rulehall.core.game import RoleAnswer
from rulehall.core.stores import read_cached_text
from rulehall.core.validation import Loose, Refusal, parse_json
from rulehall.core.views import Tag
from rulehall.engines.battles import Transport
from rulehall.engines.pokemon.battle.assessment import Assessment
from rulehall.engines.pokemon.battle.choices import (
    MEGA_SUFFIX,
    SeatRequest,
    SideRequest,
    TeamPositions,
    opponent_choice,
)
from rulehall.engines.pokemon.battle.header import battle_header
from rulehall.engines.pokemon.battle.highlights import battle_highlights
from rulehall.engines.pokemon.battle.models import (
    SIDE_OF,
    STATUSES,
    TERRAINS,
    WEATHERS,
    Ally,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
    Edge,
    MonSnapshot,
    Outcome,
    Policy,
    RoleSeat,
    Seat,
    SideId,
)
from rulehall.engines.pokemon.battle.opponent import (
    Offer,
    OpponentAnswer,
    check_commands,
    render_opponent,
)
from rulehall.engines.pokemon.battle.preview import render_preview, scripted_preview
from rulehall.engines.pokemon.battle.tactics import advised_switch, greedy_choice
from rulehall.engines.pokemon.battle.views import BattleChoice, BattleHeader, BattleView
from rulehall.engines.pokemon.battle.world import BattleGame
from rulehall.engines.pokemon.dex import Species, dex
from rulehall.engines.pokemon.rules import TIMES
from rulehall.engines.pokemon.sprites import MEGA_COLOUR, item_sprite

LOGGER = logging.getLogger(__name__)
SHOWDOWN = Path(__file__).parents[1] / "showdown"
ASSESS_JS = SHOWDOWN / "assess.js"
SIDES: tuple[SideId, ...] = ("p1", "p2")
TURN_ENDS = ("|upkeep", "|turn|", "|win|", "|tie")
TEAM_PREVIEW_LINE = "|teampreview"
# A Showdown sheet shows natures; only our own sheet line, added after, reaches the view.
SHOWDOWN_SHEET = "|showteam|"
BACK = "back"
NEXT = "next"
MEGA = "mega"
MEGA_HELP = (
    "Mega Evolve this Pokemon before its move this turn. Your team can Mega Evolve only once "
    "per battle."
)
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
# Open Team Sheets asks each seat in split lines whose blank half ends a block early: the
# battle drops the rule before team preview, and code shows its own sheet.
NO_SHEET_REQUEST = ">eval battle.ruleTable.delete('openteamsheets')"
# setStatus refuses a Pokemon that is not active, and RESTORE runs at team preview.
RESTORE = (
    ">eval const states = STATES; [battle.p1, battle.p2].forEach((side, number) => "
    "states[number].forEach(([hp, status, pp], index) => { const mon = side.pokemon[index]; "
    "mon.sethp(hp); if (status) { mon.status = status; "
    "mon.statusState = battle.initEffectState({id: status, target: mon, source: mon}); "
    "battle.singleEvent('Start', battle.dex.conditions.get(status), mon.statusState, mon); } "
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


class Snapshot(Loose):
    p1: tuple[MonSnapshot, ...]
    p2: tuple[MonSnapshot, ...]
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
    log_lines: list[str] = field(default_factory=list)
    battle_facts: list[Fact] = field(default_factory=list)
    requests_by_side: dict[str, SideRequest] = field(default_factory=dict)
    player_request: SideRequest | None = None
    snapshot: Snapshot | None = None
    outcome: Outcome | None = None
    result: BattleResult | None = None
    resolution: Resolution | None = None
    thinking: dict[RoleSeat, Task[OpponentAnswer]] = field(default_factory=dict)
    chat_lines: list[str] = field(default_factory=list)
    picks: list[str] = field(default_factory=list)
    aiming: str = ""
    mega: bool = False

    @classmethod
    async def start(
        cls,
        draft: BattleGame,
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
            battle_facts=[
                *(draft.world.player_card_fact(text) for text in battle.setup.condition_texts()),
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

    def log(self, _state: BattleGame, /) -> Sequence[str]:
        return self.log_lines

    def facts(self, _state: BattleGame, /) -> Sequence[Fact]:
        return self.battle_facts

    def view(self, _state: BattleGame, /) -> BattleView:
        return BattleView(
            header=self._header(),
            choices=self._choices(),
            background=self.setup.battle_background,
            music=self.setup.battle_music,
        )

    def require_command(self, _state: BattleGame, command: str, /) -> None:
        if command not in (choice.command for choice in self._choices() if not choice.refusal):
            raise Refusal(f"{command!r} is not a choice now")

    async def choose(self, draft: BattleGame, command: str, rng: Random) -> None:
        draft.world.battle = self.battle
        if command == LEAVE:
            await self._end("fled" if self.setup.wild else "lost")
        elif command.startswith(BALL):
            throw = draft.world.throw_ball(command.removeprefix(BALL), self._foe(), rng)
            self.battle_facts.append(throw.fact)
            if throw.caught:
                await self._end("caught")
        elif command == MEGA:
            self.mega = not self.mega
        elif command == BACK:
            self.mega = False
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

    def _header(self) -> BattleHeader:
        assert self.snapshot is not None
        return battle_header(
            self.setup, self.snapshot.p1, self.snapshot.p2, self.log_lines, self._deciding_slot()
        )

    def _choices(self) -> tuple[BattleChoice, ...]:
        request = self.player_request
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

    def _deciding_slot(self) -> int | None:
        request = self.player_request
        if request is None:
            return None
        slots = self._seat_request("player", request).deciding_slots()
        return slots[len(self.picks)] if slots else None

    def _slot_choices(self, request: SideRequest) -> tuple[BattleChoice, ...]:
        seated = self._seat_request("player", request)
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
        picking = request.team_preview and request.max_chosen_team_size is not None
        group = choices[0].group if picking else request.side.pokemon[slot].name
        mega = BattleChoice(
            command=MEGA,
            kind="mega",
            name="Mega Evolution: on" if self.mega else "Mega Evolve",
            help=MEGA_HELP,
            group=group,
            tags=(Tag(name="On", colour=MEGA_COLOUR),) if self.mega else (),
        )
        back = BattleChoice(command=BACK, kind="back", name="Back", group=group)
        return (
            *choices,
            *((mega,) if seated.can_mega(slot, self.picks) else ()),
            *((back,) if self.picks or self.aiming else ()),
        )

    async def _pick(self, command: str) -> None:
        request = self.player_request
        assert request is not None
        slots = self._seat_request("player", request).deciding_slots()
        if command != NEXT:
            if not self.aiming and request.needs_target(slots[len(self.picks)], command):
                self.aiming = command
                return
            self.aiming = ""
            mega = self.mega and command.startswith("move ")
            self.picks.append(f"{command}{MEGA_SUFFIX}" if mega else command)
            self.mega = False
        if len(self.picks) == len(slots):
            picked = dict(zip(slots, self.picks, strict=True)) | await self._decide("ally", request)
            self.picks = []
            await self._play([f">p1 {request.joined(picked)}"])

    def _foe(self) -> Battler:
        assert self.snapshot is not None
        return _first_foe(self.setup, self.snapshot)

    def _ball_refusal(self, request: SideRequest) -> str:
        if request.team_preview or any(request.force_switch):
            return "Send out a Pokemon first"
        return "" if self.battle.can_throw() else "One ball a turn"

    async def _end(self, outcome: Literal["lost", "fled", "caught"]) -> None:
        self.outcome = outcome
        self.requests_by_side.clear()
        self.player_request = None
        await self.transport.send([">forcewin p1" if outcome == "caught" else ">forcewin p2", DUMP])
        while self.result is None:
            self._read(await self._block())

    def _settle(self, draft: BattleGame) -> None:
        self.battle.inputs = list(self.inputs)
        draft.world.battle = self.battle
        if self.result is not None:
            self.resolution = end_battle(draft, self.result)

    async def _block(self) -> Block:
        return Block.of(await self.transport.receive())

    def _team_positions(self, seat: Seat) -> TeamPositions:
        assert self.snapshot is not None
        if seat == "foe":
            return frozenset(range(len(self.snapshot.p2)))
        allied = len(self.setup.team)
        return frozenset(
            at
            for at, mon in enumerate(self.snapshot.p1)
            if (mon.slot >= allied) == (seat == "ally")
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

    def _seat_request(self, seat: Seat, request: SideRequest) -> SeatRequest:
        assert self.snapshot is not None
        snapshot, battlers, foe = (
            (self.snapshot.p2, self.setup.foes, "p1")
            if seat == "foe"
            else (self.snapshot.p1, self.setup.player_side(), "p2")
        )
        return SeatRequest(
            request=request,
            battlers=tuple(battlers[mon.slot] for mon in snapshot),
            foe_side=self.requests_by_side[foe].side,
            team_positions=self._team_positions(seat),
            slots=self._slots(seat),
            spec=self.setup.format_spec(),
        )

    def _foe_species(self, seat: RoleSeat) -> tuple[Species, ...]:
        # Team preview shows each side the other's species, and nothing more.
        return tuple(dex().species[battler.species_id] for battler in self.setup.other_side(seat))

    def _ally(self) -> Ally:
        assert self.setup.ally is not None
        return self.setup.ally

    async def _think(self, seat: RoleSeat, ask: SideRequest) -> Task[OpponentAnswer] | None:
        role = self.opponent
        if role is None or (seat == "foe" and self.policy != "model"):
            return None
        if ask.wait or (ask.team_preview and ask.max_chosen_team_size is None):
            return None
        seated = self._seat_request(seat, ask)
        offers = tuple(
            Offer(
                slot=slot,
                mon_name=seated.pick_label(slot)
                if ask.team_preview
                else ask.side.pokemon[slot].name,
                choices=tuple(
                    choice for choice in seated.aimed_choices(slot, ()) if not choice.refusal
                ),
                can_mega=seated.can_mega(slot, ()),
            )
            for slot in seated.deciding_slots()
        )
        if all(len(offer.choices) == 1 for offer in offers):
            return None
        if ask.team_preview:
            own, team_positions, foes = (
                seated.battlers,
                seated.team_positions,
                self._foe_species(seat),
            )
            prompt = render_preview(self.setup, seat, offers, own, team_positions, foes)
        else:
            assessment = await self._assess(seat)
            prompt = render_opponent(
                self.setup, seat, assessment, offers, seated.team_positions, self.log_lines
            )
        return create_task(role(prompt, OpponentAnswer, partial(check_commands, offers)))

    async def _decide(self, seat: RoleSeat, ask: SideRequest) -> dict[int, str]:
        seated = self._seat_request(seat, ask)
        slots = seated.deciding_slots()
        if not slots:
            return {}
        if ask.team_preview and ask.max_chosen_team_size is None:
            leads = sorted(seated.team_positions)
            return {slot: f"team {at + 1}" for slot, at in zip(slots, leads, strict=False)}
        if thinking := self.thinking.pop(seat, None) or await self._think(seat, ask):
            try:
                answer = await thinking
            except Refusal as refused:
                LOGGER.warning("the %s plays the scripted choice: %s", seat, refused)
            else:
                if answer.line:
                    name = self.setup.foe_name if seat == "foe" else self._ally().name
                    self.chat_lines.append(f"|c|{name}|{answer.line}")
                return dict(zip(slots, answer.commands, strict=True))
        if ask.team_preview:
            leads = self.setup.format_spec().active_slots
            foes = self._foe_species(seat)
            picked = scripted_preview(
                seated.battlers, foes, seated.team_positions, len(slots), leads
            )
            return dict(zip(slots, picked, strict=True))
        if self.policy == "random":
            rng = Random(f"{self.setup.seed} {len(self.inputs)}")
            return {slot: opponent_choice(ask, rng) for slot in slots}
        assessment = await self._assess(seat)
        picks: list[str] = []
        for slot in slots:
            choices = seated.aimed_choices(slot, picks)
            pick = advised_switch(assessment, choices, slot, seat, self.log_lines) or greedy_choice(
                assessment, choices, slot
            )
            mega = pick.startswith("move ") and seated.can_mega(slot, picks)
            picks.append(f"{pick}{MEGA_SUFFIX}" if mega else pick)
        return dict(zip(slots, picks, strict=True))

    async def _assess(self, seat: RoleSeat) -> Assessment:
        await self.transport.send([assess_line(self.setup, seat)])
        self._read(await self._block())
        assert self.snapshot is not None and self.snapshot.assessment is not None
        return self.snapshot.assessment

    async def _play(self, queue: list[str]) -> None:
        while self.result is None:
            if all(side in self.requests_by_side for side in SIDES):
                # The leads are out once team preview is answered: the conditions go in then.
                opening = (
                    condition_lines(self.setup) if self.requests_by_side["p1"].team_preview else ()
                )
                lines: list[str] = []
                for side in SIDES:
                    ask = self.requests_by_side[side]
                    if ask.wait:
                        continue
                    if queue:
                        lines.append(queue.pop(0))
                    elif side == "p2":
                        self.player_request = None
                        lines.append(f">p2 {ask.joined(await self._decide('foe', ask))}")
                    elif self._waits_on_player(ask):
                        for seat, seat_side in SIDE_OF.items():
                            if thinking := await self._think(
                                seat, self.requests_by_side[seat_side]
                            ):
                                self.thinking[seat] = thinking
                        self.player_request = ask
                        return
                    else:
                        lines.append(f">p1 {ask.joined(await self._decide('ally', ask))}")
                self.inputs.extend(lines)
                self.requests_by_side.clear()
                self.player_request = None
                self.thinking.clear()
                await self.transport.send([*lines, *opening, DUMP])
            self._read(await self._block())

    def _waits_on_player(self, ask: SideRequest) -> bool:
        # A player with no Pokemon to play still sees each turn, to watch it or to forfeit.
        new_turn = bool(ask.active) and not (ask.team_preview or any(ask.force_switch))
        return new_turn or bool(self._seat_request("player", ask).deciding_slots())

    def _read(self, block: Block) -> None:
        match block.kind:
            case "update":
                view, snapshot = read_update(block.lines, opening=not self.log_lines)
                if self.setup.foe_sheet_open:
                    view = _with_open_sheet(view, self.setup.foes)
                # Chat lines go before the turn's end marker so they show inside the turn they
                # were chosen for.
                if self.chat_lines and view:
                    ends = (at for at, line in enumerate(view) if line.startswith(TURN_ENDS))
                    at = next(ends, len(view))
                    view = (*view[:at], *self.chat_lines, *view[at:])
                    self.chat_lines.clear()
                self.log_lines.extend(view)
                if snapshot is not None:
                    self.snapshot = snapshot
            case "sideupdate":
                side, *messages = block.lines
                for message in messages:
                    if message.startswith("|error|"):
                        raise ValueError(message)
                    if message.startswith("|request|") and message != "|request|null":
                        self.requests_by_side[side] = parse_json(
                            SideRequest, message.removeprefix("|request|")
                        )
            case "end":
                assert self.snapshot is not None
                highlights = battle_highlights(self.battle, self.log_lines)
                self.result = battle_result(self.setup, self.snapshot, self.outcome, highlights)


def packed(battler: Battler, *, open_sheet: bool = False) -> str:
    moves = ",".join(move.move_id for move in battler.moves)
    gender = "" if battler.gender == "N" else battler.gender
    evs, ivs = (
        "" if open_sheet else ",".join(map(str, stats)) for stats in (battler.evs, battler.ivs)
    )
    nature, friendship = ("", "") if open_sheet else (battler.nature, battler.friendship)
    return (
        f"{battler.name}|{battler.species_id}|{battler.item_id or ''}|{battler.ability}|{moves}"
        f"|{nature}|{evs}|{gender}|{ivs}||{battler.level}|{friendship}"
    )


def open_sheet_line(battlers: Sequence[Battler]) -> str:
    return f"|showteam|p2|{']'.join(packed(battler, open_sheet=True) for battler in battlers)}"


def start_lines(setup: BattleSetup) -> tuple[str, ...]:
    spec = setup.format_spec()
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
        f">start {json.dumps({'formatid': spec.showdown_id, 'seed': list(setup.seed)})}",
        *((NO_SHEET_REQUEST,) if spec.open_team_sheets else ()),
        f">player p1 {json.dumps(p1)}",
        f">player p2 {json.dumps(p2)}",
        *(_restore_lines(setup) if spec.carry_over else ()),
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


def read_update(lines: Sequence[str], *, opening: bool) -> tuple[tuple[str, ...], Snapshot | None]:
    view: list[str] = []
    snapshot: Snapshot | None = None
    rows = iter(lines)
    for line in rows:
        if line.startswith("|split|"):
            line = next(rows)
            next(rows)
        if line.startswith(DUMPED):
            snapshot = parse_json(Snapshot, line.removeprefix(DUMPED).removesuffix('"'))
        elif line.startswith("||<<< error"):
            raise ValueError(line)
        elif not line.startswith(("||", "|debug|", SHOWDOWN_SHEET)) and not (
            opening and line.startswith("|-")
        ):
            view.append(line)
    return tuple(view), snapshot


def assess_line(setup: BattleSetup, seat: RoleSeat) -> str:
    # `>eval` turns each form feed back into a newline, so the file goes as one input line.
    code = "\f".join(line for line in read_cached_text(ASSESS_JS).splitlines() if line)
    side = SIDE_OF[seat]
    opposite = "p2" if side == "p1" else "p1"
    estimates = json.dumps(
        [
            None if battler.estimate is None else battler.estimate.model_dump()
            for battler in setup.other_side(seat)
        ]
    )
    sheet_open = json.dumps(setup.sheet_open_to(seat))
    code = code.replace("ARGUMENTS", f"battle.{side}, battle.{opposite}, {sheet_open}, {estimates}")
    return f">eval JSON.stringify({{...{SNAPSHOT}, assessment: {code}}})"


def as_snapshot(battler: Battler, snapshot: MonSnapshot) -> Battler:
    moves = tuple(
        move.model_copy(update={"pp": pp})
        for move, pp in zip(battler.moves, snapshot.pp, strict=True)
    )
    status = snapshot.status if snapshot.status in STATUSES else ""
    item_id, holds_mega_stone = (
        (battler.item_id, battler.holds_mega_stone) if snapshot.held else (None, False)
    )
    return battler.model_copy(
        update={
            "hp": snapshot.hp,
            "status": status,
            "moves": moves,
            "item_id": item_id,
            "holds_mega_stone": holds_mega_stone,
        }
    )


def battle_result(
    setup: BattleSetup, snapshot: Snapshot, outcome: Outcome | None, highlights: tuple[str, ...]
) -> BattleResult:
    won = all(mon.hp == 0 for mon in snapshot.p2) and any(mon.hp > 0 for mon in snapshot.p1)
    decided: Outcome = outcome or ("won" if won else "lost")
    # An ally's Pokemon come after the player's and fight fresh each battle: none is kept.
    own = tuple(mon for mon in snapshot.p1 if mon.slot < len(setup.team))
    return BattleResult(
        outcome=decided,
        team=tuple(as_snapshot(setup.team[mon.slot], mon) for mon in own),
        sent_out_foes=tuple(
            as_snapshot(setup.foes[mon.slot], mon)
            for mon in sorted(snapshot.p2, key=lambda foe: foe.slot)
            if mon.out > 0
        ),
        on_field_mon_ids=tuple(setup.team[mon.slot].mon_id for mon in own if mon.out > 0),
        caught=_first_foe(setup, snapshot) if decided == "caught" else None,
        highlights=highlights,
    )


def _restore_lines(setup: BattleSetup) -> tuple[str]:
    states = [
        [[battler.hp, battler.status, [move.pp for move in battler.moves]] for battler in side]
        for side in (setup.player_side(), setup.foes)
    ]
    return (RESTORE.replace("STATES", json.dumps(states)),)


def _with_open_sheet(view: tuple[str, ...], foes: Sequence[Battler]) -> tuple[str, ...]:
    at = next((at for at, line in enumerate(view) if line.startswith(TEAM_PREVIEW_LINE)), None)
    if at is None:
        return view
    return (*view[: at + 1], open_sheet_line(foes), *view[at + 1 :])


def _packed_team(battlers: Sequence[Battler]) -> str:
    return "]".join(packed(battler) for battler in battlers)


def _first_foe(setup: BattleSetup, snapshot: Snapshot) -> Battler:
    return as_snapshot(setup.foes[0], next(mon for mon in snapshot.p2 if mon.slot == 0))


def end_battle(draft: BattleGame, result: BattleResult) -> Resolution:
    resolution, notes = draft.world.settle_battle(result)
    for note in notes:
        draft.note(note)
    return resolution
