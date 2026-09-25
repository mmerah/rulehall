from collections.abc import Callable, Sequence
from functools import cache, partial
from itertools import groupby
from pathlib import Path
from typing import cast

from nicegui import background_tasks, ui

from rulehall.app.session import Busy, GameService
from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.core.views import Choice
from rulehall.ui import transcript
from rulehall.ui.widgets import (
    BATTLE_FAILED,
    DICE_CLIP,
    Banner,
    Sounds,
    alert,
    assets_route,
    choice_button,
)


class BattlePanel:
    def __init__(self, session: GameService, sounds: Sounds, on_show: Callable[[], None]) -> None:
        self.session = session
        self.sounds = sounds
        self.on_show = on_show
        self.shown = False
        self._failed = False
        self.drawn_run = None
        self.view: ui.element | None = None
        self.log_lines_sent = 0
        self.shown_choices: tuple[Choice, ...] = ()
        self.facts: Sequence[Fact] = ()
        self.cards_drawn = 0
        self.banner: Banner
        self.story: ui.element
        self.column: ui.column
        self.hint: ui.label
        self.cards: ui.element

    def build_banner(self) -> None:
        self.banner = Banner("sym_r_swords", "battle", "A battle waits for you.")
        with self.banner.actions:
            ui.button("Battle", on_click=self.show).props("outline")

    def build(self, story: ui.element) -> None:
        self.story = story
        with ui.column().classes(
            "w-full flex-grow min-h-0 overflow-y-auto game-battle game-gap-lg"
        ) as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            self.screen()
            self.choices()
            self.cards = ui.element("div").classes("game-battle-cards")
        self.column.set_visibility(False)
        self.drawn_run = run = self.session.battle_run
        self._draw_cards(() if run is None else run.facts)

    def show(self) -> None:
        self.shown = True
        self._failed = False
        self.on_show()

    def sync(self, *, live: bool) -> None:
        # A run another tab closed waits for the next Battle click here.
        closed = self.session.battle_run is None and self.drawn_run is not None
        self.shown = self.shown and live and not self._failed and not closed
        if self.shown and not self.column.visible and self.session.battle_run is None:
            self._open()
        self.column.set_visibility(self.shown)
        self.banner.set_visibility(live and not self.shown)
        self.story.set_visibility(not self.shown)
        self._draw()

    @ui.refreshable_method
    def screen(self) -> None:
        session = self.session
        run = session.battle_run
        component = session.engine.battle_script
        if run is None or component is None:
            self.view = None
            return
        self.view = view = _view_element(component)()
        view.props.update(
            {
                "base": assets_route(session.engine.id),
                "lines": list(run.log),
                "sprites": session.battle_config.sprites,
                "music": session.battle_config.music,
                **run.props(),
            }
        )
        self.log_lines_sent = len(run.log)

    @ui.refreshable_method
    def choices(self) -> None:
        run = self.session.battle_run
        self.shown_choices = choices = () if run is None else run.choices()
        for group, row in groupby(choices, key=lambda choice: choice.group):
            if group:
                ui.label(group).classes("game-eyebrow")
            with ui.element("div").classes("game-battle-choices"):
                for choice in row:
                    choice_button(
                        choice.name,
                        choice.refusal or choice.brief,
                        partial(self._choose, choice.command),
                        enabled=not choice.refusal,
                        tags=choice.tags,
                    )

    def _draw(self) -> None:
        run = self.session.battle_run
        self.hint.set_visibility(run is None)
        if run is not self.drawn_run:
            # A throw that ends the battle closes the run before this sync; its die plays here.
            if any(fact.dice for fact in self.facts[self.cards_drawn :]):
                self.sounds.play(DICE_CLIP)
            self.drawn_run = run
            self.screen.refresh()
            self.choices.refresh()
            self.cards.clear()
            self._draw_cards(() if run is None else run.facts)
            return
        if run is None:
            return
        if self.view is not None and len(run.log) > self.log_lines_sent:
            self.view.run_method("add", list(run.log[self.log_lines_sent :]))
            self.log_lines_sent = len(run.log)
        if run.choices() != self.shown_choices:
            self.choices.refresh()
        fresh = run.facts[self.cards_drawn :]
        with self.cards:
            for fact in fresh:
                transcript.card(fact, live=True)
        if any(fact.dice for fact in fresh):
            self.sounds.play(DICE_CLIP)
        self.cards_drawn = len(run.facts)

    def _draw_cards(self, facts: Sequence[Fact]) -> None:
        self.facts = facts
        with self.cards:
            for fact in facts:
                transcript.card(fact)
        self.cards_drawn = len(facts)

    def _open(self) -> None:
        background_tasks.create(self._opened(), name="open battle")  # pyright: ignore[reportUnknownMemberType]

    async def _opened(self) -> None:
        try:
            await self.session.open_battle()
        except Busy as busy:
            self.shown = False
            if busy.elsewhere:
                with self.column:
                    alert(str(busy))
        except Refusal as refused:
            self._failed = True
            with self.column:
                alert(str(refused))
        except Exception:
            # A bug must not reopen the battle and leak a simulator on every Battle click.
            self._failed = True
            with self.column:
                alert(BATTLE_FAILED)
            raise

    async def _choose(self, command: str) -> None:
        try:
            await self.session.battle_command(command)
        except Busy:
            return
        except Refusal as refused:
            # The sync may have deleted the clicked button while the model was thinking.
            with self.column:
                alert(str(refused))
            if self.shown and self.session.battle_run is None:
                # Drawn closed first, so the sync keeps the screen for the reopening.
                self._draw()
                self._open()


@cache
def _view_element(component: Path) -> type[ui.element]:
    return cast(type[ui.element], type("BattleView", (ui.element,), {}, component=component))
