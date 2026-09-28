from asyncio import get_running_loop
from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import ui
from nicegui.events import GenericEventArguments, ScrollEventArguments

from rulehall.app.catalog import SavedGameKey
from rulehall.app.game_session import Busy, GameSession, SessionSnapshot
from rulehall.app.runtime import Runtime
from rulehall.core.decisions import ActionOption, Decision, PlayerInput
from rulehall.core.validation import Refusal, content_id
from rulehall.core.views import PanelRow, PlayerView
from rulehall.ui.battle import BattlePanel
from rulehall.ui.composer import CLOSED_REASONS, Composer, composer_lock
from rulehall.ui.drawer import Drawer
from rulehall.ui.panel_parts import choice_groups, panel_row
from rulehall.ui.routes import HOME
from rulehall.ui.transcript import Chat, LiveTurn
from rulehall.ui.widgets import (
    HOME_ICON,
    PASS_THROUGH,
    Banner,
    Confirm,
    Sounds,
    attempt,
    empty_state,
    heading,
    icon_button,
    media_url,
    page_body,
    page_header,
)

TURN_FAILED = "Something went wrong. The turn did not complete. Look in the server log."
REWIND_FAILED = "Something went wrong. The rewind did not complete. Look in the server log."
RESTART_FAILED = "Something went wrong. The restart did not complete. Look in the server log."
CHOICES_ROW = "row w-full items-start game-choices game-gap-md"
NEAR_END = 48
SOUND_ICONS = {True: "sym_r_volume_up", False: "sym_r_volume_off"}


class SceneHeader:
    def __init__(self, session: GameSession, now: SessionSnapshot) -> None:
        self.session = session
        self.art = session.scene_art()
        card = ui.element("div").classes("game-scene")
        card.on("click", lambda: card.classes(toggle="game-scene-open"))
        with card:
            self.draw(now.view, self.art)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        view, before = now.view, drawn.view
        if (view.scene_title, view.situation) != (before.scene_title, before.situation):
            self.draw.refresh(view, self.art)

    def sync_images(self, view: PlayerView) -> None:
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
    def __init__(
        self, now: SessionSnapshot, play: Callable[[PlayerInput], Awaitable[object]]
    ) -> None:
        self.play = play
        self.draw(now.view.decision, enabled=now.working_role is None, entering=False)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        entering = now.view.decision != drawn.view.decision
        idle = now.working_role is None
        if entering or idle != (drawn.working_role is None):
            self.draw.refresh(now.view.decision, enabled=idle, entering=entering)

    @ui.refreshable_method
    def draw(self, pending: Decision | None, *, enabled: bool, entering: bool) -> None:
        if pending is None:
            return
        banner = Banner("sym_r_help", pending.kind, pending.prompt)
        if entering:
            banner.classes("game-enter")
        if not pending.options:
            return
        with banner:
            choice_groups(
                pending.options,
                lambda option: self.play(PlayerInput(option_id=option.id)),
                enabled=enabled,
                row_class=CHOICES_ROW,
            )
            if pending.allows_text:
                ui.label("Or answer in your own words below.").classes("game-hint")


class GamePage:
    def __init__(self, session: GameSession) -> None:
        self.session = session
        self.drawn: SessionSnapshot
        self.scene: SceneHeader
        self.decision: DecisionPanel
        self.composer: Composer
        self.drawer: Drawer
        self.battle_panel: BattlePanel | None = None
        self.parts: tuple[
            SceneHeader | Chat | LiveTurn | DecisionPanel | Composer | Drawer | BattlePanel, ...
        ]
        self.sounds: Sounds
        self.sound: ui.button
        self.scroll: ui.scroll_area
        self.new_activity: ui.button
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
        now = self.drawn = session.snapshot()
        self.drawer = Drawer(
            session, now.view, self.open_row, lambda words: self.composer.prefill(words)
        )
        self.sounds = Sounds()
        self.sounds.on("sound", self.sound_state)
        if session.engine.battle_script is not None:
            self.battle_panel = BattlePanel(session, self.sounds, self.tick)
        opener = ui.timer(0.1, lambda: self._run(lambda: self._open_game(opener)))
        self.draw_header()

        ui.query(".nicegui-content").style("padding: 0; gap: 0")
        with ui.row().classes("w-full h-full no-wrap game-gap-0"):
            self.drawer.build_rail()
            with (
                ui.column()
                .classes("self-stretch flex-grow game-panel game-main game-gap-0")
                .style("min-width: 0")
            ):
                with ui.element("div").style(PASS_THROUGH) as story:
                    self.scene = SceneHeader(session, now)
                    # No padding class: NiceGUI pads the scroll content; twice would misalign.
                    with ui.scroll_area().classes("w-full flex-grow game-transcript") as scroll:
                        chat = Chat(now, session.icon, self.sounds)
                        live_turn = LiveTurn(now, session.icon, self.sounds)
                    self.scroll = scroll
                    scroll.on_scroll(self.scrolled)
                    ui.timer(0.5, lambda: scroll.scroll_to(percent=1.0), once=True)
                    self.draw_foot(now)
                if self.battle_panel is not None:
                    self.battle_panel.build(story, now)
        self.drawer.build(now)
        self.restart_dialog = Confirm(keep="Keep playing", confirm="Restart")

        self.parts = (self.scene, chat, live_turn, self.decision, self.composer, self.drawer)
        if self.battle_panel is not None:
            self.parts += (self.battle_panel,)
        self.tick()
        ui.timer(0.25, self.tick)
        ui.timer(3.0, self.sync_images)

    def tick(self) -> None:
        now, drawn = self.session.snapshot(), self.drawn
        if now.working_role != drawn.working_role:
            self.row_dialog.close()
        for part in self.parts:
            part.sync(now, drawn)
        self.sync_controls(now)
        if moved_since(now, drawn):
            self._scroll(follow=self.at_end or self.own_move)
        self.drawn = now

    def sync_images(self) -> None:
        view = self.drawn.view
        self.scene.sync_images(view)
        self.drawer.sync_icons(view)

    def sync_controls(self, now: SessionSnapshot) -> None:
        idle = now.working_role is None
        self.restart_item.set_enabled(idle)
        self.rewind_button.set_enabled(not now.held_elsewhere and idle and now.can_rewind)
        self.debrief_button.set_enabled(bool(now.log_entries) and idle and not now.held_elsewhere)

    def draw_header(self) -> None:
        session = self.session
        with page_header(
            session.state.scenario_description.title, session.engine.title, look=session.engine.look
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

    def draw_foot(self, now: SessionSnapshot) -> None:
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
            self.decision = DecisionPanel(now, self.play)
            battle = self.battle_panel
            self.composer = Composer(
                self.session,
                now,
                self.move,
                build_battle_banner=(lambda: None) if battle is None else battle.build_banner,
            )

    def open_row(self, row: PanelRow) -> None:
        self.row_dialog.clear()
        reason = CLOSED_REASONS[composer_lock(self.drawn)]
        with self.row_dialog, ui.card().classes("game-row-dialog game-gap-md"):
            panel_row(row, self.session.icon)
            if reason and row.options:
                ui.label(reason).classes("game-hint")
            choice_groups(
                row.options,
                self.use_panel_option,
                enabled=not reason,
                row_class=CHOICES_ROW,
            )
            for panel in row.detail:
                heading(panel.title)
                for each in panel.rows:
                    panel_row(each, self.session.icon)
        self.row_dialog.open()

    async def use_panel_option(self, option: ActionOption) -> None:
        self.row_dialog.close()
        await self.move(lambda: self.session.use_panel_option(option))

    async def play(self, answer: PlayerInput) -> bool:
        return await self.move(lambda: self.session.play(answer))

    async def move(self, action: Callable[[], Awaitable[None]]) -> bool:
        self.own_move = True
        return await self._run(action)

    async def rewind(self) -> None:
        if await attempt(self._rewound, failed=REWIND_FAILED):
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
        if await attempt(self.session.restart, failed=RESTART_FAILED):
            self.tick()
            await self._run(self.session.open)

    async def confirm_restart(self) -> None:
        history = self.drawn.log_entries
        if not history:
            await self.restart()
            return
        title = self.session.state.scenario_description.title
        if await self.restart_dialog.ask(f"Restart {title}? {len(history)} turns are erased."):
            await self.restart()

    def toggle_sound(self) -> None:
        self.sounds.run_method("toggleSound")

    def sound_state(self, event: GenericEventArguments) -> None:
        self.sound.set_icon(SOUND_ICONS[bool(event.args)])

    def scrolled(self, event: ScrollEventArguments) -> None:
        unseen = event.vertical_size - event.vertical_position - event.vertical_container_size
        self.at_end = unseen <= NEAR_END
        if self.at_end:
            self.show_activity(visible=False)

    def catch_up(self) -> None:
        self.scroll.scroll_to(percent=1.0)
        self.show_activity(visible=False)

    def show_activity(self, *, visible: bool) -> None:
        """The class is set again, not kept: a CSS animation replays only when it is added."""
        self.new_activity.classes(add="game-enter" if visible else "", remove="game-enter")
        self.new_activity.set_visibility(visible)

    def _scroll(self, *, follow: bool) -> None:
        if not follow:
            self.show_activity(visible=True)
            return
        self.show_activity(visible=False)
        # A method call on an existing element needs no NiceGUI slot; `ui.timer` here would.
        get_running_loop().call_later(0.1, lambda: self.scroll.scroll_to(percent=1.0))

    async def _rewound(self) -> None:
        if words := await self.session.rewind():
            self.composer.set_input(words)

    async def _open_game(self, opener: ui.timer) -> None:
        # A raise must still stop the timer: NiceGUI swallows it and fires again in 0.1s.
        opener.deactivate()
        try:
            await self.session.open()
        except Busy:
            opener.interval = 1.0
            opener.activate()
            return
        opener.cancel()

    async def _run(self, action: Callable[[], Awaitable[None]]) -> bool:
        self.composer.set_enabled(enabled=False)
        try:
            return await attempt(action, failed=TURN_FAILED)
        finally:
            if not self.composer.composer_input.is_deleted:
                self.tick()
            self.own_move = False


async def game_page(runtime: Runtime, scenario: str, character: str) -> None:
    try:
        session = runtime.session_for(
            SavedGameKey(scenario_id=content_id(scenario), character_id=content_id(character))
        )
    except Refusal as refused:
        _refused_page(str(refused))
        return
    # Tab storage (the composer draft) is readable only after the handshake.
    await ui.context.client.connected()
    if ui.context.client.is_deleted:
        return
    GamePage(session).build()


def moved_since(now: SessionSnapshot, drawn: SessionSnapshot) -> bool:
    if now == drawn:
        return False
    return (
        len(now.log_entries) != len(drawn.log_entries)
        or now.working_role != drawn.working_role
        or now.facts_and_refusals != drawn.facts_and_refusals
        or now.words != drawn.words
        or now.live != drawn.live
        or now.view.composer_option != drawn.view.composer_option
        or now.view.composer_only != drawn.view.composer_only
        or now.view.ending != drawn.view.ending
    )


def _refused_page(message: str) -> None:
    page_header("Rulehall")
    with (
        page_body(),
        ui.card().classes("w-full"),
        ui.column().classes("w-full items-center game-gap-2xl"),
    ):
        empty_state("sym_r_explore_off", message)
        ui.button("Home", icon=HOME_ICON, on_click=lambda: ui.navigate.to(HOME)).props(
            "color=primary"
        )
