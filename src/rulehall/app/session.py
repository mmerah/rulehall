import logging
from asyncio import CancelledError
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from time import monotonic
from typing import Literal

from rulehall.app.illustration import Illustrator
from rulehall.app.launch import LaunchTarget
from rulehall.app.line_process import start_process
from rulehall.app.roles import OPENING_NARRATION, role_answer, run_debrief, run_master, run_narrator
from rulehall.app.spawn import Spawner
from rulehall.app.turn import NO_TURN, Turn, require_playable
from rulehall.config import BattleConfig
from rulehall.core.facts import Fact
from rulehall.core.io import FileStore
from rulehall.core.model import AnyCharacter, AnyGame, AnyScenario
from rulehall.core.play import Answer, Cause, Debrief, Exchange, PendingOption, SpokenLine
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import PlayerView, Sprite
from rulehall.engines.engine import AnyEngine, BattleRun, Resolution, Transport

LOGGER = logging.getLogger(__name__)

IN_FLIGHT_HERE = "A turn is already running in this game."
IN_FLIGHT_ELSEWHERE = "Another game is taking a turn. Wait for that turn to end, then try again."
NOTHING_TO_REWIND = "There is no turn to rewind."

type Step = Literal["master", "narrator", "worldsmith"]


@dataclass(frozen=True, slots=True)
class Rewind:
    state: AnyGame
    words: str


@dataclass(slots=True)
class StateCache[T]:
    held: tuple[AnyGame, T] | None = None

    def read(self, state: AnyGame, build: Callable[[AnyGame], T]) -> T:
        if self.held is None or self.held[0] is not state:
            self.held = (state, build(state))
        return self.held[1]


@dataclass(slots=True, kw_only=True)
class GameService:
    target: LaunchTarget
    scenario: AnyScenario
    character: AnyCharacter
    engine: AnyEngine
    spawner: Spawner
    store: FileStore
    state: AnyGame
    gate: "Gate" = field(repr=False, compare=False)
    illustrator: Illustrator
    start_transport: Callable[[AnyEngine], Awaitable[Transport]] = start_process
    battle_config: BattleConfig = field(default_factory=BattleConfig)
    rng: Random = field(default_factory=Random)
    working_role: Step | None = None
    # The player's words for a write that opens no turn; the page shows them as their bubble.
    intent: str = ""
    live: tuple[SpokenLine, ...] = ()
    turn: Turn | None = None
    rewind_point: Rewind | None = None
    battle_run: BattleRun[AnyGame] | None = None
    debriefed: tuple[AnyGame, Debrief] | None = field(default=None, repr=False)
    views: StateCache[PlayerView] = field(
        default_factory=StateCache[PlayerView], repr=False, compare=False
    )
    histories: StateCache[tuple[Exchange, ...]] = field(
        default_factory=StateCache[tuple[Exchange, ...]], repr=False, compare=False
    )

    @property
    def unopened(self) -> bool:
        return self.working_role is None and not self.history()

    async def open(self) -> None:
        """A failed narrator saves nothing: the player then reads the premise."""
        # A second tab's timer must not run the page reset over an opening already in flight.
        if not self.unopened:
            return
        with self.gate.admit(self), self.working("narrator"):
            draft = self.state.draft()
            lines = await self._narrated(draft, (), OPENING_NARRATION)
            if lines:
                self.save(self.engine.record(draft, lines, (), cause="opening"))
            self.present()

    async def play(self, answer: Answer) -> None:
        with self.gate.admit(self), self.remembered(answer.text):
            await self._turn(answer, self.state)

    async def take_way_on(self, way_on_id: Slug, words: str) -> None:
        with self.gate.admit(self), self.remembered(words):
            self._require_free()
            draft = self.state.draft()
            self.engine.take_way_on(draft, way_on_id, words)
            if draft.request is None:
                await self._turn(Answer(text=words), draft)
                return
            self.intent = words
            try:
                self.save(self.engine.accept(draft))
                grown = await self._write_request(words=words, cause=None)
            finally:
                self.intent = ""
            if grown:
                await self._turn(Answer(text=words), self.state)

    async def use_panel_option(self, option: PendingOption) -> None:
        with self.gate.admit(self), self.remembered(""):
            self._require_free()
            panels = self.player_view().panels
            if not any(option in row.options for panel in panels for row in panel.rows):
                raise Refusal(f"{option.name!r} is not an option now")
            draft = self.state.draft()
            facts = self.engine.play_option(draft, option, self.rng)
            accepted = self.engine.accept(draft)
            self.save(self.engine.record(accepted, (), facts, words=option.name))

    async def open_battle(self) -> None:
        with self.gate.admit(self):
            if self.battle_run is not None or not self.engine.in_battle(self.state):
                return
            self.rewind_point = None
            transport = await self.start_transport(self.engine)
            draft = self.state.draft()
            opponent = (
                role_answer(self.spawner, "opponent")
                if self.battle_config.opponent == "model"
                else None
            )
            try:
                run = self.battle_run = await self.engine.open_battle(draft, transport, opponent)
            except (Refusal, CancelledError):
                await transport.close()
                raise
            await self._settle(run, draft)

    async def battle_command(self, command: str) -> None:
        with self.gate.admit(self):
            if (run := self.battle_run) is None:
                raise Refusal("The battle is still starting.")
            if command not in (choice.command for choice in run.choices() if not choice.refusal):
                raise Refusal(f"{command!r} is not a choice now")
            draft = self.state.draft()
            try:
                await run.choose(draft, command, self.rng)
            except (Refusal, CancelledError):
                await self._close_battle()
                raise
            await self._settle(run, draft)

    async def rewind(self) -> str:
        with self.gate.admit(self):
            if (point := self.rewind_point) is None:
                raise Refusal(NOTHING_TO_REWIND)
            self.rewind_point = None
            self.save(point.state)
            self.present()
            return point.words

    async def restart(self) -> None:
        with self.gate.admit(self):
            await self._close_battle()
            opening = self.engine.begin(self.target.scenario_id, self.scenario, self.character)
            self.store.discard(self.target.slug)
            self.state = opening

    async def debrief(self) -> Debrief:
        state = self.state
        if self.debriefed is not None and self.debriefed[0] is state:
            return self.debriefed[1]
        answer = await run_debrief(self.spawner, self.engine, state)
        self.debriefed = (state, answer)
        return answer

    def present(self) -> None:
        view = self.engine.narrator_view(self.state)
        self.illustrator.illustrate_later(view, self.player_view().player)

    def player_view(self) -> PlayerView:
        return self.views.read(self.state, self.engine.player_view)

    def history(self) -> tuple[Exchange, ...]:
        return self.histories.read(self.state, lambda state: state.exchanges())

    def scene_art(self) -> Path | None:
        return self.illustrator.scene_art(self.engine.narrator_view(self.state))

    def icon(self, entity_id: Slug) -> Sprite | Path | None:
        sprite = self.engine.sprite(self.state, entity_id)
        if sprite is None or self.engine.assets is None:
            return self.illustrator.icon(entity_id)
        path = self.engine.assets / sprite.path
        return sprite.model_copy(update={"path": path}) if path.is_file() else None

    def save(self, state: AnyGame) -> None:
        self.store.write(self.target.slug, state)
        self.state = state

    async def close(self) -> None:
        await self._close_battle()
        await self.illustrator.close()

    @contextmanager
    def working(self, role: Step) -> Generator[None]:
        self.working_role = role
        try:
            yield
        finally:
            self.working_role = None

    @contextmanager
    def remembered(self, words: str) -> Generator[None]:
        before = self.state
        yield
        if self.state is not before:
            self.rewind_point = Rewind(state=before, words=words)

    def _require_free(self) -> None:
        require_playable(self.engine, self.state)
        if self.state.pending is not None:
            raise Refusal("the rules wait on the player's decision first")

    async def _turn(self, answer: Answer, state: AnyGame) -> None:
        turn = Turn.begin(self.engine, state, answer, self.rng)
        self.turn = turn
        try:
            with self.working("master"):
                if turn.played:
                    await run_master(self.spawner, turn)
            lines: tuple[SpokenLine, ...] = ()
            if turn.narrates:
                with self.working("narrator"):
                    lines = await self._narrated(
                        turn.draft, tuple(turn.facts), turn.words, landed=turn.landed
                    )
            state = turn.finish(lines)
        finally:
            # Cleared before arrival: the tool surface must not reach a turn nobody plays.
            self.turn = None
        self.save(state)
        self.rng.setstate(turn.rng.getstate())
        self.present()
        await self._write_request(words="", cause="story")

    async def _write_request(self, *, words: str, cause: Cause | None) -> bool:
        request = self.state.request
        if request is None:
            return False
        draft = self.state.draft()
        draft.request = None
        if self.engine.ending(self.state) is not None:
            self.save(self.engine.accept(draft))
            return False
        handler = self.engine.request_handlers()[request.kind]
        grown = True
        try:
            with self.working("worldsmith"):
                resolution = await handler.write(
                    draft, request, role_answer(self.spawner, "worldsmith")
                )
            landed = await self._land(draft, resolution, words=words, cause=cause)
        except Refusal as failed:
            LOGGER.warning("the world did not grow: %s", failed)
            draft = self.state.draft()
            draft.request = None
            failure = (handler.failure_fact,)
            landed = self.engine.record(draft, (), failure, words=words, cause=cause)
            grown = False
        self.save(landed)
        self.present()
        return grown

    async def _land(
        self, draft: AnyGame, resolution: Resolution, *, words: str, cause: Cause | None
    ) -> AnyGame:
        if resolution.narrator_cue is None:
            return self.engine.accept(draft)
        with self.working("narrator"):
            lines = await self._narrated(draft, resolution.facts, resolution.narrator_cue)
        return self.engine.record(draft, lines, resolution.facts, words=words, cause=cause)

    async def _narrated(
        self, draft: AnyGame, facts: tuple[Fact, ...], cue: str, *, landed: bool = True
    ) -> tuple[SpokenLine, ...]:
        """No landed fact means nothing to save, so the player hears why and keeps the words."""
        try:
            return await run_narrator(self.spawner, self.engine, draft, facts, cue, self._hear)
        except Refusal as failed:
            if not landed:
                raise
            LOGGER.warning("the turn went unnarrated: %s", failed)
            return ()
        finally:
            self.live = ()

    def _hear(self, lines: tuple[SpokenLine, ...]) -> None:
        self.live = lines

    async def _settle(self, run: BattleRun[AnyGame], draft: AnyGame) -> None:
        self.save(self.engine.accept(draft))
        if (resolution := run.resolution) is None:
            return
        await self._close_battle()
        self.save(await self._land(draft, resolution, words="", cause="battle"))
        self.present()

    async def _close_battle(self) -> None:
        if (run := self.battle_run) is None:
            return
        await run.close()
        self.battle_run = None


class Busy(Refusal):
    def __init__(self, *, elsewhere: bool) -> None:
        super().__init__(IN_FLIGHT_ELSEWHERE if elsewhere else IN_FLIGHT_HERE)
        self.elsewhere = elsewhere


@dataclass(slots=True)
class Gate:
    admitted: GameService | None = field(default=None, repr=False)
    creating: int = 0
    active_at: float = field(default_factory=monotonic)

    @property
    def busy(self) -> bool:
        return self.admitted is not None or self.creating > 0

    def status(self) -> dict[str, bool | float]:
        return {
            "busy": self.busy,
            "idle_seconds": 0.0 if self.busy else monotonic() - self.active_at,
        }

    @contextmanager
    def creation(self) -> Generator[None]:
        self.creating += 1
        try:
            yield
        finally:
            self.creating -= 1
            self.active_at = monotonic()

    @property
    def turn(self) -> Turn | None:
        return None if self.admitted is None else self.admitted.turn

    def require_turn(self) -> Turn:
        """A tool call between turns is a refusal, not a crash: nobody plays a turn."""
        if (turn := self.turn) is None:
            raise Refusal(NO_TURN)
        return turn

    @contextmanager
    def admit(self, session: GameService) -> Generator[None]:
        """One writer at a time: two turns on one save is the failure that costs a game."""
        if self.admitted is not None:
            raise Busy(elsewhere=self.admitted is not session)
        self.admitted = session
        try:
            yield
        finally:
            self.admitted = None
            self.active_at = monotonic()
