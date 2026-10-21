import logging
from asyncio import CancelledError, Task, create_task, current_task
from collections.abc import Generator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

from rulehall.app.battle_process import start_battle_process
from rulehall.app.catalog import SavedGameKey
from rulehall.app.gate import Busy, Gate
from rulehall.app.illustration import Illustrator, find_sprite
from rulehall.app.role_prompts import (
    OPENING_NARRATION,
    Debrief,
    render_debrief,
    render_evidence,
    render_master,
    render_narrator,
)
from rulehall.app.roles import RoleRunner, ask_with_retry, role_answer
from rulehall.app.speech import Speaker
from rulehall.app.turn import Turn
from rulehall.config import LiveSettings, Role
from rulehall.core.decisions import ActionOption, PlayerInput, find_option
from rulehall.core.facts import Fact, Resolution
from rulehall.core.game import AnyCharacter, AnyGame, AnyScenario
from rulehall.core.log import Cause, LogEntry, SpokenLine
from rulehall.core.narration import Narration, NarratorView, partial_lines
from rulehall.core.stores import Library, SaveStore
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.core.views import PlayerView, ScreenSlot, Sprite
from rulehall.engines.battles import BattleRun, BattleServices, StartTransport
from rulehall.engines.engine import AnyEngine

LOGGER = logging.getLogger(__name__)

NOTHING_TO_REWIND = "there is no turn to rewind"
TURN_STOPPED = "the turn was stopped"
NO_WORDS_NOW = "the page takes one of its options now, not words"
BATTLE_ON = "a battle is on: finish it on the battle screen"
NOTHING_TO_UNDO = "there is no edit to undo"
NOT_AN_EDIT = "{name} is not an edit now"
GAME_OVER_FOR_PLAYER = "the game is over ({ending}): it continues only after a restart"


class TurnStopped(Refusal):
    def __init__(self) -> None:
        super().__init__(TURN_STOPPED)


@dataclass(frozen=True, slots=True)
class RunningMove:
    work: Task[None]
    words: str


@dataclass(frozen=True, slots=True)
class Change:
    before: AnyGame
    after: AnyGame
    words: str | None


@dataclass(frozen=True, slots=True)
class SilentOption:
    option: ActionOption


@dataclass(frozen=True, slots=True)
class OptionIntoTurn:
    option: ActionOption
    words: str


@dataclass(frozen=True, slots=True)
class PlainTurn:
    pass


type Route = SilentOption | OptionIntoTurn | PlainTurn


@dataclass(frozen=True, kw_only=True, slots=True)
class BattleSnapshot:
    run: BattleRun = field(compare=False)
    log: tuple[str, ...]
    facts: tuple[Fact, ...]
    view: Frozen


@dataclass(frozen=True, kw_only=True, slots=True)
class SessionSnapshot:
    view: PlayerView
    log_entries: tuple[LogEntry, ...]
    working_role: Role | None
    words: str
    turn_facts: tuple[Fact, ...]
    live: tuple[SpokenLine, ...]
    held_elsewhere: bool
    in_battle: bool
    can_rewind: bool
    can_stop: bool
    battle: BattleSnapshot | None
    screen_slots: tuple[ScreenSlot, ...]

    def require_screen_slot(self, screen_id: Slug) -> ScreenSlot:
        found = next((each for each in self.screen_slots if each.screen_id == screen_id), None)
        if found is None:
            raise ValueError(f"the engine shows no screen slot {screen_id!r}")
        return found


@dataclass(frozen=True, slots=True)
class CachedViews:
    state: AnyGame
    view: PlayerView
    log_entries: tuple[LogEntry, ...]
    screen_slots: tuple[ScreenSlot, ...]


@dataclass(frozen=True, slots=True)
class DebriefMemo:
    state: AnyGame
    debrief: Debrief


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
    gate: "Gate[GameSession]" = field(repr=False, compare=False)
    illustrator: Illustrator
    speaker: Speaker
    start_transport: StartTransport = start_battle_process
    live_settings: LiveSettings
    rng: Random = field(default_factory=Random)
    working_role: Role | None = None
    pending_words: str = ""
    live: tuple[SpokenLine, ...] = ()
    turn: Turn | None = None
    last_change: Change | None = None
    battle_run: BattleRun | None = None
    view_cache: CachedViews | None = field(default=None, repr=False, compare=False)
    debriefed: DebriefMemo | None = field(default=None, repr=False, compare=False)
    running: RunningMove | None = field(default=None, repr=False, compare=False)

    async def open(self) -> None:
        # A second tab's timer must not run the page reset over an opening already in flight.
        if self.working_role is not None or self.log_entries():
            self.illustrate_later()
            return
        with self.gate.admit(self), self.mark_working("narrator"):
            draft = self.state.draft()
            lines = await self._narrate(draft, (), OPENING_NARRATION)
            if lines:
                self.save(self.engine.record(draft, lines, (), cause="opening"))
            self.illustrate_later()

    async def choose(self, answer: PlayerInput) -> None:
        with self.gate.admit(self), self._remember_change(words=answer.text):
            route = self._route(answer)
            before, character = self.state, self.character
            work = create_task(self._play(route, answer))
            self.running = RunningMove(work, answer.text)
            try:
                await work
            except CancelledError:
                self._restore(before, character)
                outer = current_task()
                if work.cancelled() and outer is not None and outer.cancelling() == 0:
                    raise TurnStopped from None
                raise
            finally:
                self.running = None

    async def open_battle(self, *, ask_opponent: bool) -> None:
        with self.gate.admit(self):
            if (
                self.battle_run is not None
                or (battles := self.engine.battles) is None
                or not battles.in_battle(self.state)
            ):
                return
            draft = self.state.draft()
            opponent = role_answer(self.roles, "opponent") if ask_opponent else None
            services = BattleServices(opponent=opponent, start_transport=self.start_transport)
            run = self.battle_run = await battles.open_battle(draft, services)
            await self._save_battle_progress(run, draft)

    async def battle_command(self, command: str) -> None:
        with self.gate.admit(self):
            if (run := self.battle_run) is None:
                raise Refusal("the battle is still starting")
            require_not_over(self.engine, self.state)
            run.require_command(self.state, command)
            draft = self.state.draft()
            try:
                await run.choose(draft, command, self.rng)
            except BaseException:
                await self._close_battle()
                raise
            await self._save_battle_progress(run, draft)

    async def rewind(self) -> str:
        with self.gate.admit(self):
            if (change := self._find_rewind()) is None or (words := change.words) is None:
                raise Refusal(NOTHING_TO_REWIND)
            self.save(change.before)
            self.illustrate_later()
            return words

    def stop(self) -> str:
        # Silent when nothing stops: a double press, or a move that ended before the press landed.
        if (running := self.running) is None or not running.work.cancel():
            return ""
        self.running = None
        return running.words

    async def restart(self) -> None:
        with self.gate.admit(self):
            await self._close_battle()
            opening = self.engine.begin(self.key.scenario_id, self.scenario, self.character)
            self.store.discard(self.key.save_id)
            self.state = opening

    async def debrief(self) -> Debrief:
        with self.gate.admit(self):
            state = self.state
            if self.debriefed is not None and self.debriefed.state is state:
                return self.debriefed.debrief
            prompt = render_debrief(self.engine.narrator_view(state), state)
            answer = await ask_with_retry(self.roles, "narrator", prompt, Debrief, Debrief.check)
            self.debriefed = DebriefMemo(state, answer)
            return answer

    def require_idle(self) -> None:
        save_id = self.key.save_id
        if self.working_role is not None:
            raise Refusal(f"{save_id} is taking a turn: wait for that turn to end, then delete")
        if self.battle_run is not None:
            raise Refusal(f"{save_id} is in a battle: end that battle, then delete")

    def illustrate_later(self) -> None:
        view = self.engine.narrator_view(self.state)
        self.illustrator.illustrate_later(view, self.player_view().player)

    def snapshot(self) -> SessionSnapshot:
        turn, run, admitted = self.turn, self.battle_run, self.gate.admitted
        return SessionSnapshot(
            view=self.player_view(),
            log_entries=self.log_entries(),
            working_role=self.working_role,
            words=self.pending_words if turn is None else turn.logged_words,
            turn_facts=() if turn is None else tuple(turn.facts),
            live=self.live,
            held_elsewhere=admitted is not None and admitted is not self,
            in_battle=self.engine.in_battle(self.state),
            can_rewind=self._find_rewind() is not None,
            can_stop=self.running is not None,
            battle=None
            if run is None
            else BattleSnapshot(
                run=run,
                log=tuple(run.log(self.state)),
                facts=tuple(run.facts(self.state)),
                view=run.view(self.state),
            ),
            screen_slots=self.screen_slots(),
        )

    def edit(self, option: ActionOption) -> None:
        if option.action_name not in self.engine.edits:
            raise Refusal(NOT_AN_EDIT.format(name=option.action_name))
        self._require_unoccupied()
        with self._remember_change(words=None):
            draft = self.state.draft()
            self.engine.play_edit(draft, option, self.rng)
            self.save(self.engine.accept(draft))

    def undo_edit(self) -> None:
        self._require_unoccupied()
        if (change := self._find_undoable_change()) is None or change.words is not None:
            raise Refusal(NOTHING_TO_UNDO)
        self.save(change.before)

    def screen_slots(self) -> tuple[ScreenSlot, ...]:
        return self._cached_views().screen_slots

    def player_view(self) -> PlayerView:
        return self._cached_views().view

    def log_entries(self) -> tuple[LogEntry, ...]:
        return self._cached_views().log_entries

    def scene_art(self) -> Path | None:
        return self.illustrator.scene_art(self.engine.narrator_view(self.state))

    def icon(self, entity_id: Slug) -> Sprite | Path | None:
        sprite = self.engine.sprite(self.state, entity_id)
        return self.illustrator.icon(entity_id) if sprite is None else self.find_asset(sprite)

    def find_asset(self, sprite: Sprite) -> Sprite | None:
        return find_sprite(self.engine.assets, sprite)

    def save(self, state: AnyGame) -> None:
        self.store.write(self.key.save_id, state)
        self.state = state

    async def close(self) -> None:
        await self._close_battle()
        await self.illustrator.close()
        await self.speaker.close()

    @contextmanager
    def mark_working(self, role: Role) -> Generator[None]:
        self.working_role = role
        try:
            yield
        finally:
            self.working_role = None

    @contextmanager
    def _remember_change(self, *, words: str | None) -> Generator[None]:
        before = self.state
        yield
        if self.state is not before:
            self.last_change = Change(before, self.state, words)

    def _route(self, answer: PlayerInput) -> Route:
        if (pending := self.state.pending) is not None:
            silent_option = (
                find_option(pending.options, answer.option_id)
                if pending.silent and answer.option_id is not None and not self.state.unnarrated
                else None
            )
            if silent_option is None:
                return PlainTurn()
            require_playable(self.engine, self.state)
            return SilentOption(silent_option.with_words(answer.text))
        require_playable(self.engine, self.state)
        view = self.player_view()
        if answer.option_id is None:
            if not view.allows_text:
                raise Refusal(NO_WORDS_NOW)
            return PlainTurn()
        offered = view.require_option(answer.option_id)
        option = offered.with_words(answer.text)
        if offered.needs_words or offered.told_in_turn:
            return OptionIntoTurn(option, answer.text or offered.name)
        return SilentOption(option)

    async def _play(self, route: Route, answer: PlayerInput) -> None:
        match route:
            case SilentOption(option):
                await self._play_silent(option)
            case OptionIntoTurn(option, words):
                await self._play_into_turn(option, words)
            case PlainTurn():
                await self._turn(answer, self.state, self.rng)

    def _restore(self, before: AnyGame, character: AnyCharacter) -> None:
        if self.state is not before:
            self.save(before)
        # The stopped move may have shown its rolls: a resend must not draw the same dice again.
        self.rng.seed(self.rng.getrandbits(64))
        if self.character != character:
            self._rewrite_character(character)

    def _find_undoable_change(self) -> Change | None:
        change = self.last_change
        return change if change is not None and change.after is self.state else None

    def _find_rewind(self) -> Change | None:
        change = self._find_undoable_change()
        return change if change is not None and change.words is not None else None

    async def _play_silent(self, option: ActionOption) -> None:
        draft = self.state.draft()
        draft.pending = None
        facts = self.engine.play_option(draft, option, self.rng)
        accepted = self.engine.accept(draft)
        self.save(self.engine.record(accepted, (), facts, words=option.name, by_option=True))
        await self._grow_world(words="", cause="story")

    async def _play_into_turn(self, option: ActionOption, words: str) -> None:
        draft, dice = self.state.draft(), deepcopy(self.rng)
        played = self.engine.play_option(draft, option, dice)
        state = self.engine.accept(draft)
        if state.request is not None:
            self.rng.setstate(dice.getstate())
            self.save(state)
            self.pending_words = words
            try:
                world_grew = await self._grow_world(words=words, cause=None)
            finally:
                self.pending_words = ""
            if not world_grew:
                return
            state = self.state
        await self._turn(PlayerInput(text=words), state, dice, played)

    async def _turn(
        self, answer: PlayerInput, state: AnyGame, rng: Random, played: tuple[Fact, ...] = ()
    ) -> None:
        require_playable(self.engine, state)
        turn = Turn.begin(self.engine, state, answer, rng, played)
        before = self.engine.narrator_view(state)
        self.turn = turn
        try:
            with self.mark_working("master"):
                if turn.master_plays_this_turn:
                    await self._play_master(turn)
            lines: tuple[SpokenLine, ...] = ()
            if turn.needs_narration:
                with self.mark_working("narrator"):
                    lines = await self._narrate(
                        turn.draft,
                        turn.told,
                        turn.logged_words,
                        landed=turn.state_changed,
                        before=before,
                    )
            state = turn.finish(lines)
        finally:
            self.turn = None
        self.save(state)
        self.rng.setstate(turn.rng.getstate())
        self.illustrate_later()
        await self._grow_world(words="", cause="story")

    async def _grow_world(self, *, words: str, cause: Cause | None) -> bool:
        if (request := self.state.request) is None:
            self._write_back_if_grown()
            return False
        draft = self.state.draft()
        draft.request = None
        if self.engine.ending(self.state) is not None:
            self.save(self.engine.accept(draft))
            self._write_back_if_grown()
            return False
        handler = self.engine.request_handlers()[request.kind]
        world_grew = True
        try:
            with self.mark_working("worldsmith"):
                resolution = await handler.write(
                    draft, request, role_answer(self.roles, "worldsmith")
                )
            landed = await self._narrate_and_record(draft, resolution, words=words, cause=cause)
        except Refusal as failed:
            LOGGER.warning("the world did not grow: %s", failed)
            draft = self.state.draft()
            draft.request = None
            failure = (handler.failure_fact,)
            landed = self.engine.record(draft, (), failure, words=words, cause=cause)
            world_grew = False
        self.save(landed)
        self._write_back_if_grown()
        self.illustrate_later()
        return world_grew

    def _write_back_if_grown(self) -> None:
        character = self.engine.grown_character(self.state)
        if character is None or character == self.character:
            return
        self._rewrite_character(character)

    def _rewrite_character(self, character: AnyCharacter) -> None:
        self.character = character
        try:
            self.library.rewrite_character(character)
        except Refusal as refused:
            LOGGER.warning("the grown sheet was not written back: %s", refused)

    async def _narrate_and_record(
        self, draft: AnyGame, resolution: Resolution, *, words: str, cause: Cause | None
    ) -> AnyGame:
        if resolution.narrator_cue is None:
            if not resolution.facts:
                return self.engine.accept(draft)
            return self.engine.record(draft, (), resolution.facts, cause="story")
        with self.mark_working("narrator"):
            lines = await self._narrate(draft, resolution.facts, resolution.narrator_cue)
        return self.engine.record(draft, lines, resolution.facts, words=words, cause=cause)

    async def _narrate(
        self,
        draft: AnyGame,
        facts: tuple[Fact, ...],
        cue: str,
        *,
        landed: bool = True,
        before: NarratorView | None = None,
    ) -> tuple[SpokenLine, ...]:
        view = self.engine.narrator_view(draft)
        try:
            if before is not None:
                view = view.after(before)

            def overheard(text: str) -> None:
                self.live = view.spoken(partial_lines(text))

            evidence = render_evidence(facts, draft, in_battle=self.engine.in_battle(draft))
            prompt = render_narrator(view, draft, evidence=evidence, cue=cue)
            narration = await ask_with_retry(
                self.roles, "narrator", prompt, Narration, view.check_narration, overheard
            )
            return view.spoken(narration.lines)
        except Refusal as failed:
            if not landed:
                raise
            LOGGER.warning("the turn went unnarrated: %s", failed)
            return ()
        finally:
            self.live = ()

    def _require_unoccupied(self) -> None:
        if self.gate.admitted is self or self.working_role is not None:
            raise Busy(elsewhere=False)

    def _cached_views(self) -> CachedViews:
        state = self.state
        if self.view_cache is None or self.view_cache.state is not state:
            self.view_cache = CachedViews(
                state,
                self.engine.player_view(state),
                state.log_entries(),
                self.engine.screen_slots(state),
            )
        return self.view_cache

    async def _play_master(self, turn: Turn) -> None:
        prompt = render_master(
            self.engine.instructions,
            self.engine.master_sections(turn.draft),
            turn.draft,
            turn.master_action_text,
            notes=turn.notes,
        )
        try:
            await self.roles.play_tools("master", prompt, turn)
        except Refusal as failed:
            if not turn.state_changed:
                raise
            LOGGER.warning(
                "the game master failed after applying %d facts: %s", len(turn.facts), failed
            )

    async def _save_battle_progress(self, run: BattleRun, draft: AnyGame) -> None:
        self.save(self.engine.accept(draft))
        if (resolution := run.resolution) is None:
            return
        await self._close_battle()
        self.save(await self._narrate_and_record(draft, resolution, words="", cause="battle"))
        self.illustrate_later()

    async def _close_battle(self) -> None:
        if (run := self.battle_run) is None:
            return
        await run.close()
        self.battle_run = None


def require_not_over(engine: AnyEngine, state: AnyGame) -> None:
    if (ended := engine.ending(state)) is not None:
        raise Refusal(GAME_OVER_FOR_PLAYER.format(ending=ended.rstrip(".")))


def require_playable(engine: AnyEngine, state: AnyGame) -> None:
    require_not_over(engine, state)
    if engine.in_battle(state):
        raise Refusal(BATTLE_ON)
