from asyncio import get_running_loop
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path

from nicegui import ui
from nicegui.events import GenericEventArguments, ScrollEventArguments

from rulehall.app.catalog import SavedGameKey
from rulehall.app.game_session import Busy, GameSession, SessionSnapshot
from rulehall.app.runtime import Runtime
from rulehall.core.decisions import ActionOption, PlayerInput
from rulehall.core.validation import Frozen, Refusal, content_id, parse
from rulehall.core.views import PanelRow, PlayerView
from rulehall.ui import theme
from rulehall.ui.battle import BattlePanel
from rulehall.ui.composer import CLOSED_REASONS, Composer, composer_lock
from rulehall.ui.drawer import Drawer
from rulehall.ui.panel_parts import CHOICES_ROW, choice_groups, panel_row
from rulehall.ui.routes import hall_path
from rulehall.ui.transcript import Transcript
from rulehall.ui.voice import VoicePlayer
from rulehall.ui.widgets import (
    PASS_THROUGH,
    Confirm,
    Sounds,
    Speech,
    attempt,
    failure_notice,
    heading,
    icon_button,
    media_url,
    page_header,
    refused_page,
)

TURN_FAILED = failure_notice("The turn did not complete.")
REWIND_FAILED = failure_notice("The rewind did not complete.")
RESTART_FAILED = failure_notice("The restart did not complete.")
NEAR_END = 48
SOUND_ICONS = {True: "sym_r_volume_up", False: "sym_r_volume_off"}
AUTO_READ_ICONS = {True: "sym_r_record_voice_over", False: "sym_r_voice_over_off"}
JUMP_LABEL = "Jump to latest"
# Collapsed turns size themselves late: one scroll lands short, so the hold follows each resize.
HOLD_AT_END = """<script>
window.holdAtEnd = (id) => {
  const started = performance.now();
  const attach = () => {
    const area = getHtmlElement(id);
    const box = area?.querySelector(".q-scrollarea__container");
    const content = box?.querySelector(".q-scrollarea__content");
    if (!content) {
      if (performance.now() - started < 10000) requestAnimationFrame(attach);
      return;
    }
    area.releaseEnd?.();
    const grabs = ["wheel", "touchstart", "pointerdown", "keydown"];
    let quiet;
    const toEnd = () => {
      box.scrollTop = box.scrollHeight;
      clearTimeout(quiet);
      quiet = setTimeout(release, 1500);
    };
    const sizes = new ResizeObserver(toEnd);
    function release() {
      sizes.disconnect();
      clearTimeout(quiet);
      for (const name of grabs) area.removeEventListener(name, release);
      delete area.releaseEnd;
    }
    for (const name of grabs) area.addEventListener(name, release, {passive: true});
    area.releaseEnd = release;
    sizes.observe(content);
    toEnd();
  };
  attach();
};
</script>"""


class Speaking(Frozen):
    bubble_id: int | None
    off_screen: bool


class SceneHeaderView:
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


class GamePage:
    def __init__(self, session: GameSession) -> None:
        self.session = session
        self.drawn: SessionSnapshot
        self.scene: SceneHeaderView
        self.composer: Composer
        self.drawer: Drawer
        self.battle_panel: BattlePanel | None = None
        self.parts: tuple[SceneHeaderView | Transcript | Composer | Drawer | BattlePanel, ...]
        self.sounds: Sounds
        self.sound: ui.button
        self.voice_player: VoicePlayer | None = None
        self.auto_read_button: ui.button
        self.scroll: ui.scroll_area
        self.transcript: Transcript
        self.jump: ui.button
        self.speaking_pill: ui.row
        self.restart_item: ui.menu_item
        self.rewind_button: ui.button
        self.debrief_button: ui.button
        self.restart_dialog: Confirm
        self.row_dialog = ui.dialog()
        self.debrief_dialog = ui.dialog()
        self.at_end: bool = True
        self.unseen_activity: bool = False
        self.jump_shown: tuple[bool, bool] = (False, False)
        self.own_move: bool = False

    def build(self) -> None:
        session = self.session
        now = self.drawn = session.snapshot()
        self.drawer = Drawer(
            session,
            now.view,
            self.open_row,
            self.pick_option,
            lambda words: self.composer.prefill(words),
        )
        self.sounds = Sounds()
        self.sounds.on("sound", self.sound_state)
        if session.live_settings.current.speech.enabled:
            player = self.voice_player = VoicePlayer(session, Speech())
            player.speech.on("auto_read", partial(self.auto_read_state, player))
            player.speech.on("speaking", partial(self.speaking_state, player))
            player.speech.on("escaped", player.stop)
        if session.battle_script is not None:
            self.battle_panel = BattlePanel(session, self.sounds, self.show_battle)
        opener = ui.timer(0.1, lambda: self._run(lambda: self._open_game(opener)))
        self.draw_header()

        with ui.row().classes("w-full h-full no-wrap game-gap-0"):
            self.drawer.build_rail()
            with (
                ui.column()
                .classes("self-stretch flex-grow game-panel game-main game-gap-0")
                .style("min-width: 0")
            ):
                with ui.element("div").style(PASS_THROUGH) as story:
                    self.scene = SceneHeaderView(session, now)
                    # No padding class: NiceGUI pads the scroll content; twice would misalign.
                    with ui.scroll_area().classes("w-full flex-grow game-transcript") as scroll:
                        self.transcript = Transcript(
                            now,
                            session.icon,
                            self.sounds,
                            None if self.voice_player is None else self.voice_player.read_aloud,
                        )
                    self.scroll = scroll
                    scroll.on_scroll(self.scrolled)
                    self.scroll_to_end()
                    self.draw_foot(now)
                if self.battle_panel is not None:
                    self.battle_panel.build(story, now)
        self.drawer.build(now)
        self.restart_dialog = Confirm(keep="Keep playing", confirm="Restart")

        self.parts = (self.scene, self.transcript, self.composer, self.drawer)
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
        if (player := self.voice_player) is not None:
            if self.transcript.redrawn:
                player.stop()
            else:
                if self.transcript.withdrawn:
                    player.stop()
                player.hear(self.transcript.finished_bubbles)
        self.sync_controls(now)
        if moved_since(now, drawn):
            self.follow(now, drawn)
        self.drawn = now

    def show_battle(self) -> None:
        if self.voice_player is not None:
            self.voice_player.stop()
        self.tick()

    def sync_images(self) -> None:
        view = self.drawn.view
        self.scene.sync_images(view)
        self.drawer.sync_icons()

    def sync_controls(self, now: SessionSnapshot) -> None:
        idle = now.working_role is None
        self.restart_item.set_enabled(idle)
        self.rewind_button.set_enabled(not now.held_elsewhere and idle and now.can_rewind)
        self.debrief_button.set_enabled(bool(now.log_entries) and idle and not now.held_elsewhere)

    def draw_header(self) -> None:
        session = self.session
        with page_header(
            session.state.scenario_description.title,
            session.engine.title,
            back=hall_path(session.engine.id, session.key.character_id),
            look=session.engine.look,
        ):
            ui.space()
            self.rewind_button = icon_button("sym_r_undo", "Rewind last turn", self.rewind)
            self.debrief_button = icon_button("sym_r_summarize", "Story so far", self.show_debrief)
            self.sound = icon_button(SOUND_ICONS[True], "Sound", self.toggle_sound)
            if (player := self.voice_player) is not None:
                self.auto_read_button = icon_button(
                    AUTO_READ_ICONS[False], "Voice", player.speech.toggle_auto_read
                )
            ui.button("Sheet", icon="sym_r_menu_book", on_click=self.drawer.toggle).props(
                "flat no-caps aria-label=Sheet"
            ).classes("game-sheet-button")
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
        with ui.element("div").classes("game-jump-dock"):
            self.jump = (
                ui.button(icon="sym_r_arrow_downward", on_click=self.catch_up)
                .props(f'dense color=primary aria-label="{JUMP_LABEL}"')
                .classes("game-jump")
            )
            self.jump.set_visibility(False)
        with (
            ui.column().classes("w-full game-foot"),
            ui.column().classes("w-full game-measure game-foot-body game-gap-lg"),
        ):
            if (player := self.voice_player) is not None:
                self.draw_speaking_pill(player)
            if self.battle_panel is not None:
                self.battle_panel.build_banner()
            self.composer = Composer(
                self.session,
                now,
                self.choose,
                None if self.voice_player is None else self.voice_player.speech,
            )

    def draw_speaking_pill(self, player: VoicePlayer) -> None:
        with ui.row().classes("game-speaking no-wrap items-center game-gap-0") as pill:
            ui.button("Speaking", icon="sym_r_graphic_eq", on_click=player.speech.reveal).props(
                "flat dense no-caps"
            )
            icon_button("sym_r_stop", "Stop reading", player.stop).props("dense")
        pill.set_visibility(False)
        self.speaking_pill = pill

    def open_row(self, row: PanelRow) -> None:
        self.row_dialog.clear()
        reason = CLOSED_REASONS[composer_lock(self.drawn)]
        with self.row_dialog, ui.card().classes("game-row-dialog game-gap-md"):
            panel_row(row, self.session.icon)
            if reason and row.options:
                ui.label(reason).classes("game-hint")
            choice_groups(row.options, self.pick_option, enabled=not reason, row_class=CHOICES_ROW)
            for panel in row.detail:
                heading(panel.title, help=panel.help)
                for each in panel.rows:
                    panel_row(each, self.session.icon)
        self.row_dialog.open()

    async def pick_option(self, option: ActionOption) -> bool:
        self.row_dialog.close()
        return await self.choose(PlayerInput(option_id=option.id))

    async def choose(self, answer: PlayerInput) -> bool:
        return await self.move(lambda: self.session.choose(answer))

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

    def auto_read_state(self, player: VoicePlayer, event: GenericEventArguments) -> None:
        on = bool(event.args)
        self.auto_read_button.set_icon(AUTO_READ_ICONS[on])
        player.switch(on=on)

    def speaking_state(self, player: VoicePlayer, event: GenericEventArguments) -> None:
        speaking = parse(Speaking, event.args)
        player.show_speaking(speaking.bubble_id, off_screen=speaking.off_screen)
        self.show_speaking_pill(player)

    def show_speaking_pill(self, player: VoicePlayer) -> None:
        """Hidden at the end too: the page's own scroll to a new reply lags the first clip."""
        self.speaking_pill.set_visibility(
            player.speaking_id is not None and player.off_screen and not self.at_end
        )

    def scrolled(self, event: ScrollEventArguments) -> None:
        unseen = event.vertical_size - event.vertical_position - event.vertical_container_size
        self.at_end = unseen <= NEAR_END
        if self.at_end:
            self.unseen_activity = False
        self.show_jump()
        if (player := self.voice_player) is not None:
            self.show_speaking_pill(player)

    def catch_up(self) -> None:
        self.scroll_to_end()
        self.unseen_activity = False
        self.show_jump()

    def scroll_to_end(self) -> None:
        self.scroll.client.run_javascript(f"holdAtEnd({self.scroll.id})")

    def show_jump(self) -> None:
        news = self.unseen_activity
        visible = not self.at_end or news
        if (visible, news) == self.jump_shown:
            return
        self.jump_shown = (visible, news)
        jump = self.jump
        jump.set_text("New activity" if news else "")
        if news:
            jump.props(remove="aria-label")
        else:
            jump.props(f'aria-label="{JUMP_LABEL}"')
        jump.classes(add="game-jump-news" if news else "", remove="game-jump-news")
        jump.set_visibility(visible)

    def follow(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        if drawn.live:
            return
        reply_top_id = self.transcript.reply_top_id
        landed = len(now.log_entries) > len(drawn.log_entries)
        if reply_top_id is not None and (now.live or landed):
            self._scroll_to_reply_top(reply_top_id)
        else:
            self._scroll(follow=self.at_end or self.own_move)

    def _scroll_to_reply_top(self, element_id: int) -> None:
        if not (self.at_end or self.own_move):
            self.unseen_activity = True
            self.show_jump()
            return
        self.own_move = False
        self.unseen_activity = False
        self.show_jump()
        script = (
            f"getHtmlElement({self.scroll.id})?.releaseEnd?.();"
            f"getHtmlElement({element_id})?.scrollIntoView({{block: 'start'}})"
        )
        get_running_loop().call_later(0.1, lambda: self.scroll.client.run_javascript(script))

    def _scroll(self, *, follow: bool) -> None:
        self.unseen_activity = not follow
        self.show_jump()
        if follow:
            self.scroll_to_end()

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
            if not self.composer.words_input.is_deleted:
                self.tick()
            self.own_move = False


async def game_page(runtime: Runtime, scenario: str, character: str) -> None:
    try:
        session = runtime.session_for(
            SavedGameKey(scenario_id=content_id(scenario), character_id=content_id(character))
        )
    except Refusal as refused:
        refused_page(str(refused))
        return
    # A script added after the handshake is inserted as inert HTML and never runs.
    ui.add_body_html(HOLD_AT_END)
    theme.fit_to_viewport()
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
        or now.turn_facts != drawn.turn_facts
        or now.words != drawn.words
        or now.live != drawn.live
        or now.view.ending != drawn.view.ending
    )
