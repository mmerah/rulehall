import logging
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from time import monotonic

from rulehall.app.battle_process import start_battle_process
from rulehall.app.catalog import SavedGameKey
from rulehall.app.illustration import Illustrator
from rulehall.app.roles import (
    OPENING_NARRATION,
    Debrief,
    RoleRunner,
    role_answer,
    run_debrief,
    run_master,
    run_narrator,
)
from rulehall.app.turn import Turn
from rulehall.config import LiveSettings, Role
from rulehall.core.decisions import ActionOption, PlayerInput
from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyGame, AnyScenario
from rulehall.core.log import Cause, LogEntry, RefusedCall, SpokenLine, facts_and_refusals
from rulehall.core.stores import Library, SaveStore
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import BattleChoice, NarratorView, PlayerView, Sprite
from rulehall.engines.engine import AnyEngine, BattleRun, Resolution, Transport

LOGGER = logging.getLogger(__name__)

IN_FLIGHT_HERE = "a turn is already running in this game"
IN_FLIGHT_ELSEWHERE = "another game is taking a turn: wait for that turn to end, then try again"
NOTHING_TO_REWIND = "there is no turn to rewind"
NO_TURN = "no turn is open: the player starts a turn from the page, so wait until you start again"
BATTLE_ON = "a battle is on: finish it on the battle screen"
GAME_OVER = "the game is over ({ending}): it continues only after a restart"


@dataclass(frozen=True, slots=True)
class Rewind:
    state: AnyGame
    words: str


@dataclass(frozen=True, kw_only=True, slots=True)
class SessionSnapshot:
    view: PlayerView
    log_entries: tuple[LogEntry, ...]
    working_role: Role | None
    words: str
    facts_and_refusals: tuple[Fact | RefusedCall, ...]
    live: tuple[SpokenLine, ...]
    held_elsewhere: bool
    in_battle: bool
    can_rewind: bool
    show_refusals: bool
    battle_run: BattleRun[AnyGame] | None = field(compare=False)
    battle_log: tuple[str, ...]
    battle_facts: tuple[Fact, ...]
    battle_choices: tuple[BattleChoice, ...]


@dataclass(slots=True)
class StateCache[T]:
    held: tuple[AnyGame, T] | None = None

    def find_cached(self, state: AnyGame) -> T | None:
        return self.held[1] if self.held is not None and self.held[0] is state else None

    def put(self, state: AnyGame, value: T) -> None:
        self.held = (state, value)

    def read(self, state: AnyGame, build: Callable[[AnyGame], T]) -> T:
        if self.held is None or self.held[0] is not state:
            self.held = (state, build(state))
        return self.held[1]


@dataclass(slots=True, kw_only=True)
class GameSession:
    key: SavedGameKey
    scenario: AnyScenario
    character: AnyCharacter
    engine: AnyEngine
    roles: RoleRunner
    store: SaveStore
    library: Library
    state: AnyGame
    gate: "Gate" = field(repr=False, compare=False)
    illustrator: Illustrator
    start_transport: Callable[[AnyEngine], Awaitable[Transport]] = start_battle_process
    live_settings: LiveSettings
    rng: Random = field(default_factory=Random)
    working_role: Role | None = None
    pending_words: str = ""
    live: tuple[SpokenLine, ...] = ()
    turn: Turn | None = None
    rewind_point: Rewind | None = None
    battle_run: BattleRun[AnyGame] | None = None
    debriefs: StateCache[Debrief] = field(
        default_factory=StateCache[Debrief], repr=False, compare=False
    )
    views: StateCache[PlayerView] = field(
        default_factory=StateCache[PlayerView], repr=False, compare=False
    )
    log_entries_cache: StateCache[tuple[LogEntry, ...]] = field(
        default_factory=StateCache[tuple[LogEntry, ...]], repr=False, compare=False
    )

    @property
    def unopened(self) -> bool:
        return self.working_role is None and not self.log_entries()

    async def open(self) -> None:
        # A second tab's timer must not run the page reset over an opening already in flight.
        if not self.unopened:
            self.present()
            return
        with self.gate.admit(self), self.mark_working("narrator"):
            draft = self.state.draft()
            lines = await self._narrated(draft, (), OPENING_NARRATION)
            if lines:
                self.save(self.engine.record(draft, lines, (), cause="opening"))
            self.present()

    async def play(self, answer: PlayerInput) -> None:
        with self.gate.admit(self), self.remember_for_rewind(answer.text):
            await self._turn(answer, self.state)

    async def use_composer_option(self, option: ActionOption, words: str) -> None:
        with self.gate.admit(self), self.remember_for_rewind(words):
            self._require_free()
            if option != self.player_view().composer_option:
                raise Refusal("the page changed; try again")
            draft = self.state.draft()
            chosen = option.model_copy(update={"args": {**option.args, "words": words}})
            _ = self.engine.play_option(draft, chosen, self.rng)
            if draft.request is None:
                await self._turn(PlayerInput(text=words), draft)
                return
            self.pending_words = words
            try:
                self.save(self.engine.accept(draft))
                grown = await self._write_request(words=words, cause=None)
            finally:
                self.pending_words = ""
            if grown:
                await self._turn(PlayerInput(text=words), self.state)

    async def use_panel_option(self, option: ActionOption) -> None:
        with self.gate.admit(self), self.remember_for_rewind(""):
            self._require_free()
            panels = self.player_view().panels
            if not any(option in row.options for panel in panels for row in panel.rows):
                raise Refusal(f"{option.name!r} is not an option now")
            draft = self.state.draft()
            facts = self.engine.play_option(draft, option, self.rng)
            if option.told_in_turn:
                draft.unnarrated = list(facts)
            accepted = self.engine.accept(draft)
            self.save(self.engine.record(accepted, (), facts, words=option.name, by_option=True))
            if self.state.request is not None and not await self._write_request(
                words="", cause="story"
            ):
                return
            if option.told_in_turn:
                await self._turn(PlayerInput(text=option.name), self.state)

    async def open_battle(self) -> None:
        with self.gate.admit(self):
            if self.battle_run is not None or not self.engine.in_battle(self.state):
                return
            self.rewind_point = None
            transport = await self.start_transport(self.engine)
            draft = self.state.draft()
            opponent = (
                role_answer(self.roles, "opponent")
                if self.live_settings.current.battle.opponent == "model"
                else None
            )
            try:
                run = self.battle_run = await self.engine.open_battle(draft, transport, opponent)
            except BaseException:
                await transport.close()
                raise
            await self._settle(run, draft)

    async def battle_command(self, command: str) -> None:
        with self.gate.admit(self):
            if (run := self.battle_run) is None:
                raise Refusal("the battle is still starting")
            if command not in (choice.command for choice in run.choices() if not choice.refusal):
                raise Refusal(f"{command!r} is not a choice now")
            draft = self.state.draft()
            try:
                await run.choose(draft, command, self.rng)
            except BaseException:
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
            opening = self.engine.begin(self.key.scenario_id, self.scenario, self.character)
            self.store.discard(self.key.save_id)
            self.state = opening

    async def debrief(self) -> Debrief:
        with self.gate.admit(self):
            state = self.state
            if (cached := self.debriefs.find_cached(state)) is not None:
                return cached
            answer = await run_debrief(self.roles, self.engine, state)
            self.debriefs.put(state, answer)
            return answer

    def require_idle(self) -> None:
        save_id = self.key.save_id
        if self.working_role is not None:
            raise Refusal(f"{save_id} is taking a turn: wait for that turn to end, then delete")
        if self.battle_run is not None:
            raise Refusal(f"{save_id} is in a battle: end that battle, then delete")

    def present(self) -> None:
        view = self.engine.narrator_view(self.state)
        self.illustrator.illustrate_later(view, self.player_view().player)

    def snapshot(self) -> SessionSnapshot:
        turn, run, admitted = self.turn, self.battle_run, self.gate.admitted
        show_refusals = self.live_settings.current.transcript.refusals
        return SessionSnapshot(
            view=self.player_view(),
            log_entries=self.log_entries(),
            working_role=self.working_role,
            words=self.pending_words if turn is None else turn.logged_words,
            facts_and_refusals=()
            if turn is None
            else facts_and_refusals(turn.facts, turn.refused, refusals=show_refusals),
            live=self.live,
            held_elsewhere=admitted is not None and admitted is not self,
            in_battle=self.engine.in_battle(self.state),
            can_rewind=self.rewind_point is not None,
            show_refusals=show_refusals,
            battle_run=run,
            battle_log=() if run is None else tuple(run.log),
            battle_facts=() if run is None else tuple(run.facts),
            battle_choices=() if run is None else run.choices(),
        )

    def player_view(self) -> PlayerView:
        return self.views.read(self.state, self.engine.player_view)

    def log_entries(self) -> tuple[LogEntry, ...]:
        return self.log_entries_cache.read(self.state, lambda state: state.log_entries())

    def scene_art(self) -> Path | None:
        return self.illustrator.scene_art(self.engine.narrator_view(self.state))

    def icon(self, entity_id: Slug) -> Sprite | Path | None:
        sprite = self.engine.sprite(self.state, entity_id)
        if sprite is None or self.engine.assets is None:
            return self.illustrator.icon(entity_id)
        path = self.engine.assets / sprite.path
        return sprite.model_copy(update={"path": path}) if path.is_file() else None

    def save(self, state: AnyGame) -> None:
        self.store.write(self.key.save_id, state)
        self.state = state

    async def close(self) -> None:
        await self._close_battle()
        await self.illustrator.close()

    @contextmanager
    def mark_working(self, role: Role) -> Generator[None]:
        self.working_role = role
        try:
            yield
        finally:
            self.working_role = None

    @contextmanager
    def remember_for_rewind(self, words: str) -> Generator[None]:
        before = self.state
        yield
        if self.state is not before:
            self.rewind_point = Rewind(state=before, words=words)

    def _require_free(self) -> None:
        require_playable(self.engine, self.state)
        if self.state.pending is not None:
            raise Refusal("the rules wait on the player's decision first")

    async def _turn(self, answer: PlayerInput, state: AnyGame) -> None:
        require_playable(self.engine, state)
        turn = Turn.begin(self.engine, state, answer, self.rng)
        before = self.engine.narrator_view(state)
        self.turn = turn
        try:
            with self.mark_working("master"):
                if turn.master_plays_this_turn:
                    await run_master(self.roles, turn)
            lines: tuple[SpokenLine, ...] = ()
            if turn.needs_narration:
                with self.mark_working("narrator"):
                    lines = await self._narrated(
                        turn.draft,
                        turn.told,
                        turn.logged_words,
                        landed=turn.state_changed,
                        before=before,
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
            with self.mark_working("worldsmith"):
                resolution = await handler.write(
                    draft, request, role_answer(self.roles, "worldsmith")
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
        if (character := self.engine.grown_character(self.state)) is not None:
            self._write_back(character)
        self.present()
        return grown

    def _write_back(self, character: AnyCharacter) -> None:
        try:
            self.library.rewrite_character(character)
        except Refusal as refused:
            LOGGER.warning("the grown sheet was not written back: %s", refused)
            return
        self.character = character

    async def _land(
        self, draft: AnyGame, resolution: Resolution, *, words: str, cause: Cause | None
    ) -> AnyGame:
        if resolution.narrator_cue is None:
            if not resolution.facts:
                return self.engine.accept(draft)
            return self.engine.record(draft, (), resolution.facts, cause="story")
        with self.mark_working("narrator"):
            lines = await self._narrated(draft, resolution.facts, resolution.narrator_cue)
        return self.engine.record(draft, lines, resolution.facts, words=words, cause=cause)

    async def _narrated(
        self,
        draft: AnyGame,
        facts: tuple[Fact, ...],
        cue: str,
        *,
        landed: bool = True,
        before: NarratorView | None = None,
    ) -> tuple[SpokenLine, ...]:
        try:
            return await run_narrator(
                self.roles, self.engine, draft, facts, cue, self._hear, before
            )
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
    admitted: GameSession | None = field(default=None, repr=False)
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
        if (turn := self.turn) is None:
            raise Refusal(NO_TURN)
        return turn

    @contextmanager
    def admit(self, session: GameSession) -> Generator[None]:
        if self.admitted is not None:
            raise Busy(elsewhere=self.admitted is not session)
        self.admitted = session
        try:
            yield
        finally:
            self.admitted = None
            self.active_at = monotonic()


def require_playable(engine: AnyEngine, state: AnyGame) -> None:
    if (ended := engine.ending(state)) is not None:
        raise Refusal(GAME_OVER.format(ending=ended.rstrip(".")))
    if engine.in_battle(state):
        raise Refusal(BATTLE_ON)
