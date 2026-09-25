from asyncio import get_running_loop
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from itertools import groupby
from pathlib import Path
from typing import Self

from nicegui import app, ui
from nicegui.events import GenericEventArguments, ScrollEventArguments

from rulehall.app.session import Busy, GameService
from rulehall.core.play import Answer, Exchange, PendingDecision, PendingOption
from rulehall.core.validation import Refusal
from rulehall.core.views import PanelRow, PlayerView
from rulehall.ui import transcript
from rulehall.ui.battle import BattlePanel
from rulehall.ui.drawer import Drawer, panel_row
from rulehall.ui.transcript import Chat, LiveTurn, TurnProgress
from rulehall.ui.widgets import (
    ARROW_ICON,
    DICE_CLIP,
    PASS_THROUGH,
    TURN_FAILED,
    Banner,
    Confirm,
    Sounds,
    alert,
    choice_button,
    decision_options,
    heading,
    icon_button,
    media_url,
    page_header,
    typed,
    warn,
)

SOUND_ICONS = {True: "sym_r_volume_up", False: "sym_r_volume_off"}


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Snapshot:
    view: PlayerView
    history: tuple[Exchange, ...]
    progress: TurnProgress
    held_elsewhere: bool
    in_battle: bool
    can_rewind: bool

    @classmethod
    def of(cls, session: GameService) -> Self:
        admitted = session.gate.admitted
        return cls(
            view=session.player_view(),
            history=session.history(),
            progress=TurnProgress.of(session),
            held_elsewhere=admitted is not None and admitted is not session,
            in_battle=session.engine.in_battle(session.state),
            can_rewind=session.rewind_point is not None,
        )

    @property
    def blocker(self) -> transcript.Blocker | None:
        return transcript.blocker(self.view, self.progress.working_role, in_battle=self.in_battle)

    @property
    def battle_waits(self) -> bool:
        return self.in_battle and self.progress.working_role is None

    def rolled_since(self, drawn: Self) -> bool:
        if len(self.history) > len(drawn.history):
            newest = self.history[-1]
            # The battle's closing exchange repeats the throws, whose dice already played live.
            seen = drawn.progress.fact_count
            if newest.cause != "battle" and transcript.rolled_since(newest.facts, seen):
                return True
        turn = self.progress.turn
        if turn is None:
            return False
        seen = drawn.progress.fact_count if turn is drawn.progress.turn else 0
        return transcript.rolled_since(turn.facts[: self.progress.fact_count], seen)

    def moved_since(self, drawn: Self) -> bool:
        now, before = self.progress, drawn.progress
        return (
            len(self.history) != len(drawn.history)
            or now.working_role != before.working_role
            or now.fact_count != before.fact_count
            or now.intent != before.intent
            or now.live != before.live
            or self.view.way_on != drawn.view.way_on
            or self.view.ending != drawn.view.ending
        )


class SceneHeader:
    def __init__(self, session: GameService) -> None:
        self.session = session
        self.art: Path | None = None

    def build(self, view: PlayerView) -> None:
        self.art = self.session.scene_art()
        card = ui.element("div").classes("game-scene")
        card.on("click", lambda: card.classes(toggle="game-scene-open"))
        with card:
            self.draw(view, self.art)

    def sync(self, now: Snapshot, drawn: Snapshot) -> None:
        view, before = now.view, drawn.view
        if (view.scene_title, view.situation) != (before.scene_title, before.situation):
            self.draw.refresh(view, self.art)

    def sync_art(self, view: PlayerView) -> None:
        art = self.session.scene_art()
        if art != self.art:
            self.art = art
            self.draw.refresh(view, art)

    @ui.refreshable_method
    def draw(self, view: PlayerView, art: Path | None) -> None:
        if art is not None:
            ui.image(media_url(art)).classes("game-scene-wash")
        with ui.row().classes("game-scene-body w-full no-wrap game-gap-0"):
            with ui.column().classes("game-scene-text game-gap-3xs"):
                ui.label("current scene").classes("text-xs game-eyebrow")
                ui.label(view.scene_title).classes("game-title game-scene-title")
                ui.label(view.situation).classes("text-sm opacity-80 game-scene-situation")
            if art is not None:
                ui.image(media_url(art)).props("fit=contain").classes("game-scene-art")
        ui.icon("sym_r_expand_more").classes("game-scene-chevron lt-sm")


class DecisionPanel:
    def __init__(self, play: Callable[[Answer], Awaitable[object]]) -> None:
        self.play = play

    def build(self, now: Snapshot) -> None:
        self.draw(now.view.decision, enabled=now.progress.working_role is None, entering=False)

    def sync(self, now: Snapshot, drawn: Snapshot) -> None:
        entering = now.view.decision != drawn.view.decision
        idle = now.progress.working_role is None
        if entering or idle != (drawn.progress.working_role is None):
            self.draw.refresh(now.view.decision, enabled=idle, entering=entering)

    @ui.refreshable_method
    def draw(self, pending: PendingDecision | None, *, enabled: bool, entering: bool) -> None:
        if pending is None:
            return
        banner = Banner("sym_r_help", pending.kind, pending.prompt)
        if entering:
            banner.classes("game-enter")
        if not pending.options:
            return
        with banner:
            decision_options(pending.options, self.play, enabled=enabled)
            if pending.allows_text:
                ui.label("Or answer in your own words below.").classes("game-hint")


class GamePage:
    """One page object per browser tab; several tabs can share one session."""

    def __init__(self, session: GameService) -> None:
        self.session = session
        self.drawn: Snapshot
        self.scene = SceneHeader(session)
        self.chat = Chat(session)
        self.live_turn = LiveTurn(session)
        self.decision = DecisionPanel(self.play)
        self.drawer: Drawer
        self.battle_panel: BattlePanel | None = None
        self.sounds: Sounds
        self.sound: ui.button
        self.scroll: ui.scroll_area
        self.new_activity: ui.button
        self.box: ui.input
        self.send_button: ui.button
        self.way_on: Banner
        self.way_on_button: ui.button
        self.ending: ui.label
        self.restart_item: ui.menu_item
        self.rewind_button: ui.button
        self.debrief_button: ui.button
        self.restart_dialog: Confirm
        self.row_dialog = ui.dialog()
        self.debrief_dialog = ui.dialog()
        self.at_end: bool = True
        self.own_move: bool = False

    def build(self) -> None:
        session = self.session
        now = self.drawn = Snapshot.of(session)
        self.drawer = Drawer(session, now.view, self.open_row, self.prefill)
        self.sounds = Sounds()
        self.sounds.on("sound", self.sound_state)
        if session.engine.battle_script is not None:
            self.battle_panel = BattlePanel(session, self.sounds, self.tick)
        if session.unopened:
            opener = ui.timer(0.1, lambda: self._opened(opener))
        else:
            session.present()
        self.header()

        ui.query(".nicegui-content").style("padding: 0; gap: 0")
        with ui.row().classes("w-full h-full no-wrap game-gap-0"):
            self.drawer.build_rail()
            with (
                ui.column()
                .classes("self-stretch flex-grow game-panel game-main game-gap-0")
                .style("min-width: 0")
            ):
                with ui.element("div").style(PASS_THROUGH) as story:
                    self.scene.build(now.view)
                    # No padding class: NiceGUI pads the scroll content; twice would misalign.
                    with ui.scroll_area().classes("w-full flex-grow game-transcript") as scroll:
                        self.chat.build(now.view, now.history)
                        self.live_turn.build(now.progress)
                    self.scroll = scroll
                    scroll.on_scroll(self.scrolled)
                    ui.timer(0.5, lambda: scroll.scroll_to(percent=1.0), once=True)
                    self.foot(now)
                if self.battle_panel is not None:
                    self.battle_panel.build(story)
        self.drawer.build(now.view, now.history)
        self.restart_dialog = Confirm(keep="Keep playing", confirm="Restart")

        self.sync_controls(now)
        if self.battle_panel is not None:
            self.battle_panel.sync(live=now.battle_waits)
        self._clear_spent_draft(now)
        ui.timer(0.25, self.tick)
        ui.timer(3.0, self.sync_art)

    def tick(self) -> None:
        now, drawn = Snapshot.of(self.session), self.drawn
        if now.progress.working_role != drawn.progress.working_role:
            # Its buttons were enabled for the old step and its rows are the old view's.
            self.row_dialog.close()
        if now.rolled_since(drawn):
            self.sounds.play(DICE_CLIP)
        if len(now.history) > len(drawn.history):
            self._clear_spent_draft(now)
        self.scene.sync(now, drawn)
        self.chat.sync(now.view, now.history, drawn_history=drawn.history)
        self.live_turn.sync(now.progress, drawn.progress)
        self.decision.sync(now, drawn)
        self.drawer.sync(now.view, now.history, drawn_view=drawn.view, drawn_history=drawn.history)
        self.sync_controls(now)
        if self.battle_panel is not None:
            self.battle_panel.sync(live=now.battle_waits)
        if now.moved_since(drawn):
            self._scroll(follow=self.at_end or self.own_move)
        self.drawn = now

    def sync_art(self) -> None:
        view = self.drawn.view
        self.scene.sync_art(view)
        self.drawer.sync_icons(view)

    def sync_controls(self, now: Snapshot) -> None:
        blocked, idle = now.blocker, now.progress.working_role is None
        typing = not now.held_elsewhere and blocked in (None, "answer")
        for widget in (self.box, self.send_button, self.way_on_button):
            widget.set_enabled(typing)
        self.box.props(f'placeholder="{transcript.PLACEHOLDERS[blocked]}"')
        way_on, ending = now.view.way_on, now.view.ending
        self.way_on.set_visibility(way_on is not None)
        self.way_on_button.set_text("" if way_on is None else way_on.name)
        self.way_on.text.set_text("" if way_on is None else way_on.brief)
        self.ending.set_text(ending or "")
        self.ending.set_visibility(ending is not None)
        self.restart_item.set_enabled(idle)
        self.rewind_button.set_enabled(not now.held_elsewhere and idle and now.can_rewind)
        self.debrief_button.set_enabled(bool(now.history) or not idle)

    def header(self) -> None:
        session = self.session
        with page_header(
            session.state.scenario.title, session.engine.title, look=session.engine.look
        ):
            ui.space()
            self.rewind_button = icon_button("sym_r_undo", "Rewind last turn", self.rewind)
            self.debrief_button = icon_button("sym_r_summarize", "Story so far", self.show_debrief)
            self.sound = icon_button(SOUND_ICONS[True], "Sound", self.toggle_sound)
            icon_button("sym_r_menu_book", "Scene and journal", self.drawer.toggle)
            with (
                icon_button("sym_r_more_vert", "More"),
                ui.menu(),
                ui.menu_item(on_click=self.confirm_restart) as self.restart_item,
            ):
                with ui.item_section().props("avatar"):
                    ui.icon("sym_r_restart_alt").classes("text-negative")
                ui.item_section("Restart this game")

    def foot(self, now: Snapshot) -> None:
        """In the column, not `ui.footer`: a page-wide footer ignores the rail and the drawer."""
        with (
            ui.column().classes("w-full game-foot"),
            ui.column().classes("w-full game-measure game-foot-body game-gap-lg"),
        ):
            self.new_activity = ui.button(
                "New activity", icon="sym_r_arrow_downward", on_click=self.catch_up
            ).props("dense color=primary")
            self.new_activity.classes("game-activity")
            self.show_activity(visible=False)
            self.decision.build(now)
            self.way_on = Banner("sym_r_explore", "way on")
            with self.way_on.actions:
                self.way_on_button = (
                    ui.button(on_click=self.take_way_on)
                    .props(f"outline icon-right={ARROW_ICON}")
                    .classes("game-way-on")
                )
            if self.battle_panel is not None:
                self.battle_panel.build_banner()
            self.ending = ui.label().classes("text-xs game-over")
            self.composer()

    def composer(self) -> None:
        with ui.row().classes("w-full no-wrap items-end game-composer game-gap-lg"):
            self.box = (
                ui.input()
                .classes("flex-grow")
                # theme.py's default w-full would fight flex-grow and squeeze the send button.
                .classes(remove="w-full")
                .props('autogrow type=textarea borderless input-style="max-height: 9rem"')
                .props(remove="outlined")
            )
            self.box.bind_value(app.storage.tab, f"draft:{self.session.target.slug}")
            # Enter sends on a fine pointer only; a touch keyboard's Enter must stay a newline.
            self.box.on(
                "keydown.enter",
                self.submit,
                js_handler=(
                    '(e) => { if (e.shiftKey || !matchMedia("(pointer: fine)").matches) return; '
                    "e.preventDefault(); emit(); }"
                ),
            )
            # `color=None`: Quasar's `text-primary` would paint the glyph the button's own gold.
            self.send_button = (
                ui.button(icon="sym_r_arrow_upward", on_click=self.submit, color=None)
                .props("round flat aria-label=Send")
                .classes("game-send")
            )

    def open_row(self, row: PanelRow) -> None:
        self.row_dialog.clear()
        now = self.drawn
        reason = transcript.CLOSED_REASONS[now.blocker]
        groups = [
            (group, tuple(options))
            for group, options in groupby(row.options, key=lambda option: option.group)
        ]
        with self.row_dialog, ui.card().classes("game-row-dialog game-gap-md"):
            panel_row(row, self.session.icon)
            if reason and row.options:
                ui.label(reason).classes("game-hint")
            for group, options in groups:
                if len(groups) > 1:
                    heading(group)
                with ui.row().classes("w-full items-start game-choices game-gap-md"):
                    for option in options:
                        choice_button(
                            option.name,
                            option.refusal or option.brief,
                            partial(self.use_panel_option, option),
                            enabled=not reason and not option.refusal,
                        )
            for panel in row.detail:
                heading(panel.title)
                for each in panel.rows:
                    panel_row(each, self.session.icon)
        self.row_dialog.open()

    async def use_panel_option(self, option: PendingOption) -> None:
        self.row_dialog.close()
        self.own_move = True
        await self._run(lambda: self.session.use_panel_option(option))

    def prefill(self, words: str) -> None:
        self._set_box(words)
        self.box.run_method("focus")

    async def play(self, answer: Answer) -> bool:
        self.own_move = True
        return await self._run(lambda: self.session.play(answer))

    async def submit(self) -> None:
        words = typed(self.box)
        if not words:
            return
        if await self.play(Answer(text=words)):
            self._set_box()

    async def take_way_on(self) -> None:
        way_on = self.drawn.view.way_on
        if way_on is None:
            warn("The way on has changed.")
            return
        words = typed(self.box)
        self.own_move = True
        if await self._run(lambda: self.session.take_way_on(way_on.id, words)):
            self._set_box()

    async def rewind(self) -> None:
        try:
            words = await self.session.rewind()
        except Refusal as error:
            alert(str(error))
            return
        if words:
            self._set_box(words)
        self.tick()

    async def show_debrief(self) -> None:
        view = self.drawn.view
        self.debrief_dialog.clear()
        with self.debrief_dialog, ui.card().classes("game-row-dialog game-gap-md"):
            ui.label(view.scene_title).classes("game-title")
            ui.label(view.situation).classes("text-sm opacity-80")
            with ui.column().classes("w-full game-gap-md") as body:
                ui.spinner()
        self.debrief_dialog.open()
        try:
            debrief = await self.session.debrief()
        except Refusal:
            debrief = None
        if body.is_deleted or not self.debrief_dialog.value:
            return
        body.clear()
        with body:
            if debrief is None:
                ui.label("The story so far could not be written. Try again later.")
                return
            for title, lines in (
                ("Story so far", (debrief.story_so_far,)),
                ("Current aim", (debrief.current_aim,)),
                ("Open threads", debrief.open_threads),
                ("Last beats", debrief.last_beats),
            ):
                heading(title)
                for line in lines:
                    ui.label(line)

    async def restart(self) -> None:
        # A menu action, not a composer double-click: any refusal here must reach the player.
        try:
            await self.session.restart()
        except Refusal as error:
            alert(str(error))
            return
        self.tick()
        await self._run(self.session.open)

    async def confirm_restart(self) -> None:
        history = self.drawn.history
        if not history:
            await self.restart()
            return
        title = self.session.state.scenario.title
        if await self.restart_dialog.ask(f"Restart {title}? {len(history)} turns are erased."):
            await self.restart()

    def toggle_sound(self) -> None:
        self.sounds.run_method("toggleSound")

    def sound_state(self, event: GenericEventArguments) -> None:
        self.sound.set_icon(SOUND_ICONS[bool(event.args)])

    def scrolled(self, event: ScrollEventArguments) -> None:
        self.at_end = transcript.near_end(
            event.vertical_position, event.vertical_size, event.vertical_container_size
        )
        if self.at_end:
            self.show_activity(visible=False)

    def catch_up(self) -> None:
        self.scroll.scroll_to(percent=1.0)
        self.show_activity(visible=False)

    def show_activity(self, *, visible: bool) -> None:
        """The class is set again, not kept: a CSS animation replays only when it is added."""
        self.new_activity.classes(add="game-enter" if visible else "", remove="game-enter")
        self.new_activity.set_visibility(visible)

    def _clear_spent_draft(self, now: Snapshot) -> None:
        newest_prompt = now.history[-1].words if now.history else ""
        if transcript.draft_spent(typed(self.box), newest_prompt):
            self._set_box()

    def _set_box(self, words: str = "") -> None:
        box = self.box
        box.value = words
        # Quasar never saw the value change, so only an explicit push empties the composer.
        box.run_method("updateValue")

    def _scroll(self, *, follow: bool) -> None:
        if not follow:
            self.show_activity(visible=True)
            return
        self.show_activity(visible=False)
        # A method call on an existing element needs no NiceGUI slot; `ui.timer` here would.
        get_running_loop().call_later(0.1, lambda: self.scroll.scroll_to(percent=1.0))

    async def _opened(self, opener: ui.timer) -> None:
        blocked = False

        async def opening() -> None:
            nonlocal blocked
            try:
                await self.session.open()
            except Busy:
                blocked = True

        try:
            _ = await self._run(opening)
        finally:
            # A raise must still stop the timer: NiceGUI swallows it and fires again in 0.1s.
            if blocked:
                opener.interval = 1.0
            else:
                opener.cancel()

    async def _run(self, playing: Callable[[], Awaitable[None]]) -> bool:
        # The composer greys at once, not at the next tick: a second Enter has nothing to hit.
        for widget in (self.box, self.send_button, self.way_on_button):
            widget.set_enabled(False)
        try:
            await playing()
        except Busy as busy:
            # Silent when it is this game's own turn: a double-click guard, not a message.
            if busy.elsewhere:
                alert(str(busy))
            return False
        except Refusal as error:
            alert(str(error))
            return False
        except Exception:
            # Announced, not handled: the re-raise is what logs the detail kept off the screen.
            alert(TURN_FAILED)
            raise
        finally:
            if not self.box.is_deleted:
                self.tick()
            # A move that changed nothing must not pull a reader down on the next change.
            self.own_move = False
        return True


def game_page(session: GameService) -> None:
    if ui.context.client.is_deleted:
        return
    GamePage(session).build()
