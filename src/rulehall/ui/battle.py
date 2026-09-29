from collections.abc import Callable, Sequence
from functools import cache, partial
from pathlib import Path
from typing import cast

from nicegui import background_tasks, ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.facts import Fact
from rulehall.core.views import BattleChoice, BattleChoiceKind, BattleHeader, BattleSide
from rulehall.ui import transcript
from rulehall.ui.panel_parts import avatar, choice_button, tag_row
from rulehall.ui.routes import assets_route
from rulehall.ui.widgets import Sounds, attempt, failure_notice, heading

BATTLE_FAILED = failure_notice("The battle did not start.")
MOVE_FAILED = failure_notice("The move was not played.")
CHOICE_ROWS: tuple[tuple[frozenset[BattleChoiceKind], str], ...] = (
    (frozenset({"move"}), "game-battle-moves"),
    (frozenset({"switch"}), "game-battle-team"),
    (frozenset({"next", "back", "item", "leave"}), "game-battle-foot"),
)


class BattlePanel:
    def __init__(self, session: GameSession, sounds: Sounds, on_show: Callable[[], None]) -> None:
        self.session = session
        self.sounds = sounds
        self.on_show = on_show
        self.shown = False
        self.opening = False
        self.battle_view_element: ui.element | None = None
        self.banner: ui.column
        self.story: ui.element
        self.column: ui.column
        self.hint: ui.label
        self.cards: ui.element

    def build_banner(self) -> None:
        with (
            ui.column().classes(
                "game-card game-decision game-banner w-full game-gap-lg"
            ) as self.banner,
            ui.row().classes("w-full items-center no-wrap game-banner-head game-gap-xl"),
        ):
            ui.icon("sym_r_swords").classes("game-card-icon")
            with ui.column().classes("game-banner-text game-gap-3xs"):
                ui.label("battle").classes("game-banner-label")
                ui.label("A battle waits for you.").classes("game-banner-body")
            with ui.row().classes("items-center no-wrap game-banner-actions game-gap-md"):
                ui.button("Battle", on_click=self.show).props("outline")

    def build(self, story: ui.element, now: SessionSnapshot) -> None:
        self.story = story
        with ui.column().classes(
            "w-full flex-grow min-h-0 overflow-y-auto game-battle game-gap-lg"
        ) as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            self.draw_header(now.battle_header)
            with ui.element("div").classes("game-battle-arena"):
                self.draw_battle_screen(now)
                self.draw_speech(now.battle_header)
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
        component = session.battle_script
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
    def draw_header(self, header: BattleHeader | None) -> None:
        if header is None:
            return
        with ui.element("div").classes("game-battle-head"):
            with ui.element("div").classes("game-battle-sides"):
                for side in (header.player, header.ally):
                    if side is not None:
                        self._draw_side(side)
            ui.label("vs").classes("game-battle-vs")
            with ui.element("div").classes("game-battle-sides game-battle-foe"):
                self._draw_side(header.foe)
        if header.conditions:
            tag_row(header.conditions)

    @ui.refreshable_method
    def draw_speech(self, header: BattleHeader | None) -> None:
        speakers = () if header is None else (header.ally, header.foe)
        if not (said := [side for side in speakers if side is not None and side.said]):
            return
        with ui.element("div").classes("game-battle-voices"):
            for side in said:
                with ui.element("div").classes("game-battle-speech"):
                    ui.label(side.name).classes("game-battle-speaker")
                    ui.label(side.said)

    @ui.refreshable_method
    def draw_choices(self, choices: tuple[BattleChoice, ...]) -> None:
        if slot := next((choice.group for choice in choices if choice.group), ""):
            heading(slot)
        for kinds, row_class in CHOICE_ROWS:
            if members := [choice for choice in choices if choice.kind in kinds]:
                with ui.element("div").classes(row_class):
                    for choice in members:
                        self._draw_choice(choice)

    def _draw(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.hint.set_visibility(now.battle_run is None)
        lines = transcript.appended_since(now.battle_log, drawn.battle_log)
        fresh = transcript.appended_since(now.battle_facts, drawn.battle_facts)
        if now.battle_run is not drawn.battle_run or lines is None or fresh is None:
            closing = drawn.battle_run
            # A throw that ends the battle closes the run before this sync; its die plays here.
            if closing is not None:
                self.sounds.roll_dice(closing.facts[len(drawn.battle_facts) :])
            self.draw_header.refresh(now.battle_header)
            self.draw_battle_screen.refresh(now)
            self.draw_speech.refresh(now.battle_header)
            self.draw_choices.refresh(now.battle_choices)
            self.cards.clear()
            self._draw_cards(now.battle_facts)
            return
        if self.battle_view_element is not None and lines:
            self.battle_view_element.run_method("add", list(lines))
        if now.battle_header != drawn.battle_header:
            self.draw_header.refresh(now.battle_header)
        if _said(now.battle_header) != _said(drawn.battle_header):
            self.draw_speech.refresh(now.battle_header)
        if now.battle_choices != drawn.battle_choices:
            self.draw_choices.refresh(now.battle_choices)
        with self.cards:
            for fact in fresh:
                transcript.draw_fact_card(fact, live=True)
        self.sounds.roll_dice(fresh)

    def _draw_side(self, side: BattleSide) -> None:
        with ui.element("div").classes("game-battle-side"):
            avatar(self.session.find_asset(side.sprite), side.name)
            with ui.column().classes("game-gap-2xs game-battle-trainer"):
                ui.label(side.name).classes("game-battle-name")
                with ui.element("div").classes("game-battle-pips"):
                    for pip in side.pips:
                        ui.element("span").classes(f"game-pip game-pip-{pip}")

    def _draw_choice(self, choice: BattleChoice) -> None:
        _ = choice_button(
            choice.name,
            choice.refusal or choice.brief,
            partial(self._choose, choice.command),
            enabled=not choice.refusal,
            help=choice.help,
            tags=choice.tags,
            meters=choice.meters,
            icon=None if choice.sprite is None else self.session.find_asset(choice.sprite),
        ).classes(f"game-choice-{choice.kind}")

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


def _said(header: BattleHeader | None) -> tuple[str, ...]:
    speakers = () if header is None else (header.ally, header.foe)
    return tuple(side.said for side in speakers if side is not None)


@cache
def battle_component_class(component: Path) -> type[ui.element]:
    return cast(type[ui.element], type("BattleView", (ui.element,), {}, component=component))
