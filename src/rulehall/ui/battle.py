from collections.abc import Callable, Sequence
from functools import cache
from pathlib import Path
from typing import cast

from nicegui import background_tasks, ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.facts import Fact
from rulehall.core.views import BattleChoice
from rulehall.ui import transcript
from rulehall.ui.panel_parts import choice_groups
from rulehall.ui.routes import assets_route
from rulehall.ui.widgets import DICE_CLIP, Banner, Sounds, attempt

BATTLE_FAILED = "Something went wrong. The battle did not start. Look in the server log."
MOVE_FAILED = "Something went wrong. The move was not played. Look in the server log."


class BattlePanel:
    def __init__(self, session: GameSession, sounds: Sounds, on_show: Callable[[], None]) -> None:
        self.session = session
        self.sounds = sounds
        self.on_show = on_show
        self.shown = False
        self.opening = False
        self.battle_view_element: ui.element | None = None
        self.banner: Banner
        self.story: ui.element
        self.column: ui.column
        self.hint: ui.label
        self.cards: ui.element

    def build_banner(self) -> None:
        self.banner = Banner("sym_r_swords", "battle", "A battle waits for you.")
        with self.banner.actions:
            ui.button("Battle", on_click=self.show).props("outline")

    def build(self, story: ui.element, now: SessionSnapshot) -> None:
        self.story = story
        with ui.column().classes(
            "w-full flex-grow min-h-0 overflow-y-auto game-battle game-gap-lg"
        ) as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            self.draw_battle_screen(now)
            self.draw_choices(now.battle_choices)
            self.cards = ui.element("div").classes("game-battle-cards")
        self.column.set_visibility(False)
        self._draw_cards(now.battle_facts)

    def show(self) -> None:
        self.shown = True
        self.on_show()

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        live = now.in_battle and now.working_role is None
        run = now.battle_run
        closed = run is None and drawn.battle_run is not None and not self.opening
        self.shown = self.shown and live and not closed
        if self.shown and not self.column.visible and run is None:
            self._open()
        self.column.set_visibility(self.shown)
        self.banner.set_visibility(live and not self.shown)
        self.story.set_visibility(not self.shown)
        self._draw(now, drawn)

    @ui.refreshable_method
    def draw_battle_screen(self, now: SessionSnapshot) -> None:
        session = self.session
        run = now.battle_run
        component = session.engine.battle_script
        if run is None or component is None:
            self.battle_view_element = None
            return
        self.battle_view_element = view = battle_component_class(component)()
        view.props.update(
            {
                "base": assets_route(session.engine.id),
                "lines": list(now.battle_log),
                "sprites": session.live_settings.current.battle.sprites,
                "music": session.live_settings.current.battle.music,
                **run.props(),
            }
        )

    @ui.refreshable_method
    def draw_choices(self, choices: tuple[BattleChoice, ...]) -> None:
        choice_groups(
            choices,
            lambda choice: self._choose(choice.command),
            enabled=True,
            row_class="game-battle-choices",
        )

    def _draw(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.hint.set_visibility(now.battle_run is None)
        lines = transcript.appended_since(now.battle_log, drawn.battle_log)
        fresh = transcript.appended_since(now.battle_facts, drawn.battle_facts)
        if now.battle_run is not drawn.battle_run or lines is None or fresh is None:
            closing = drawn.battle_run
            # A throw that ends the battle closes the run before this sync; its die plays here.
            if closing is not None and any(
                fact.dice for fact in closing.facts[len(drawn.battle_facts) :]
            ):
                self.sounds.play(DICE_CLIP)
            self.draw_battle_screen.refresh(now)
            self.draw_choices.refresh(now.battle_choices)
            self.cards.clear()
            self._draw_cards(now.battle_facts)
            return
        if self.battle_view_element is not None and lines:
            self.battle_view_element.run_method("add", list(lines))
        if now.battle_choices != drawn.battle_choices:
            self.draw_choices.refresh(now.battle_choices)
        with self.cards:
            for fact in fresh:
                transcript.draw_fact_card(fact, live=True)
        if any(fact.dice for fact in fresh):
            self.sounds.play(DICE_CLIP)

    def _draw_cards(self, facts: Sequence[Fact]) -> None:
        with self.cards:
            for fact in facts:
                transcript.draw_fact_card(fact)

    def _open(self) -> None:
        self.opening = True
        background_tasks.create(self._open_battle(), name="open battle")  # pyright: ignore[reportUnknownMemberType]

    async def _open_battle(self) -> None:
        try:
            with self.column:
                _ = await attempt(self.session.open_battle, failed=BATTLE_FAILED)
        finally:
            # A bug must not reopen the battle and leak a simulator on every Battle click.
            self.shown = self.shown and self.session.battle_run is not None
            self.opening = False

    async def _choose(self, command: str) -> None:
        # The sync may have deleted the clicked button while the model was thinking.
        with self.column:
            chosen = await attempt(lambda: self.session.battle_command(command), failed=MOVE_FAILED)
        if not chosen and self.shown and self.session.battle_run is None:
            self._open()


@cache
def battle_component_class(component: Path) -> type[ui.element]:
    return cast(type[ui.element], type("BattleView", (ui.element,), {}, component=component))
