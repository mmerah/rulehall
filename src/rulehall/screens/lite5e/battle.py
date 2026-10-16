from asyncio import sleep
from collections.abc import Sequence
from functools import partial

from nicegui import background_tasks, ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.engines.lite5e.battle.battling import BATTLE_SCREEN_ID
from rulehall.engines.lite5e.battle.views import (
    AUTO,
    NEXT,
    BattleChoice,
    CombatantCard,
    Lite5eBattleView,
    TurnSlot,
)
from rulehall.engines.lite5e.rules import FormationRow
from rulehall.ui.battle_screen import RESOLVING, BattleScreenBase, facts_of
from rulehall.ui.panel_parts import avatar, choice_button, meter_grid, tag_row
from rulehall.ui.screen_host import ScreenHost
from rulehall.ui.widgets import heading

FOE_TURN_PAUSE = 0.6
FOE_ROWS: tuple[FormationRow, ...] = ("back", "front")
PARTY_ROWS: tuple[FormationRow, ...] = ("front", "back")


class Lite5eBattleScreen(BattleScreenBase[Lite5eBattleView]):
    screen_id = BATTLE_SCREEN_ID
    view_type = Lite5eBattleView

    def __init__(self, host: ScreenHost) -> None:
        super().__init__(host)
        self.sending = False
        self.thinking: ui.label

    def build(self, now: SessionSnapshot) -> None:
        view = self.battle_view(now)
        with ui.column().classes("w-full flex-grow min-h-0 game-lite5e game-gap-md") as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            self.thinking = ui.label("The foes are deciding…").classes("game-lite5e-thinking")
            self.draw_field(view)
            self.draw_menu(view)
            self.cards = ui.element("div").classes("game-lite5e-cards")
        self.column.set_visibility(False)
        self._draw_cards(facts_of(now), live=False)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        super().sync(now, drawn)
        view = self.battle_view(now)
        self.thinking.set_visibility(view is not None and view.thinking)
        if self.shown and not self.sending and _foes_play(view):
            self.sending = True
            background_tasks.create(self._play_foe_turn(), name="play a foe turn")  # pyright: ignore[reportUnknownMemberType]

    @ui.refreshable_method
    def draw_field(self, view: Lite5eBattleView | None) -> None:
        if view is None:
            return
        with ui.element("div").classes("game-lite5e-field"):
            for row in FOE_ROWS:
                self._draw_row(view.foes, row)
            self._draw_order(view.round, view.order)
            for row in PARTY_ROWS:
                self._draw_row(view.party, row)

    @ui.refreshable_method
    def draw_menu(self, view: Lite5eBattleView | None) -> None:
        if view is None or not view.choices:
            return
        with ui.element("div").classes("game-lite5e-menu"):
            heading(view.step)
            for group in dict.fromkeys(choice.group for choice in view.choices):
                with ui.element("div").classes("game-lite5e-group"):
                    if group:
                        ui.label(group).classes("game-lite5e-group-name")
                    with ui.element("div").classes("game-lite5e-choices"):
                        for choice in view.choices:
                            if choice.group == group:
                                self._draw_choice(choice)

    def _redraw(self, now: SessionSnapshot) -> None:
        view = self.battle_view(now)
        self._refresh_field(view)
        self._refresh_menu(view)

    def _update(self, now: SessionSnapshot, drawn: SessionSnapshot) -> bool:
        view, before = self.battle_view(now), self.battle_view(drawn)
        if _field(view) != _field(before):
            self._refresh_field(view)
        if _menu(view) != _menu(before):
            self._refresh_menu(view)
        return True

    def _refresh_field(self, view: Lite5eBattleView | None) -> None:
        self._forget_buttons(auto=True)
        self.draw_field.refresh(view)

    def _refresh_menu(self, view: Lite5eBattleView | None) -> None:
        self._forget_buttons(auto=False)
        self.column.classes(remove=RESOLVING)
        self.draw_menu.refresh(view)

    def _forget_buttons(self, *, auto: bool) -> None:
        self.choice_buttons = {
            command: button
            for command, button in self.choice_buttons.items()
            if command.startswith(f"{AUTO} ") != auto
        }

    def _draw_row(self, cards: Sequence[CombatantCard], row: FormationRow) -> None:
        if not (in_row := [card for card in cards if card.row == row]):
            return
        with ui.element("div").classes(f"game-lite5e-row game-lite5e-row-{row}"):
            ui.label(f"{row.title()} row").classes("game-lite5e-row-name")
            with ui.element("div").classes("game-lite5e-row-cards"):
                for card in in_row:
                    self._draw_card(card)

    def _draw_card(self, card: CombatantCard) -> None:
        current = " game-lite5e-card-current" if card.current else ""
        with ui.element("div").classes(f"game-lite5e-card game-lite5e-card-{card.side}{current}"):
            avatar(self.session.find_asset(card.sprite), card.name)
            with ui.element("div").classes("game-lite5e-card-body"):
                with ui.element("div").classes("game-lite5e-card-head"):
                    ui.label(card.name).classes("game-lite5e-card-name")
                    tag_row(card.tags if card.band is None else (card.band, *card.tags))
                if card.hp is not None:
                    meter_grid((card.hp,))
            if card.auto is not None:
                command = f"{AUTO} {card.combatant_id}"
                button = ui.button("Auto", on_click=partial(self._choose, command))
                button.props(f"{'unelevated' if card.auto else 'outline'} no-caps dense")
                button.classes("game-lite5e-auto")
                self.choice_buttons[command] = button

    def _draw_order(self, round_number: int, order: Sequence[TurnSlot]) -> None:
        with ui.element("div").classes("game-lite5e-order"):
            ui.label(f"Round {round_number}").classes("game-lite5e-round")
            for slot in order:
                current = " game-lite5e-turn-current" if slot.current else ""
                ui.label(slot.name).classes(f"game-lite5e-turn{current}")

    def _draw_choice(self, choice: BattleChoice) -> None:
        self.choice_buttons[choice.command] = choice_button(
            choice.name,
            choice.brief,
            partial(self._choose, choice.command),
            enabled=True,
            help=choice.help,
            tags=choice.tags,
            icon=None if choice.sprite is None else self.session.find_asset(choice.sprite),
        ).classes(f"game-choice-{choice.kind}")

    async def _play_foe_turn(self) -> None:
        try:
            await sleep(FOE_TURN_PAUSE)
            # The player may have sent the turn by hand during the pause.
            if self.shown and _foes_play(self.battle_view(self.session.snapshot())):
                await self._choose(NEXT)
        finally:
            self.sending = False


def _field(view: Lite5eBattleView | None) -> Lite5eBattleView | None:
    if view is None:
        return None
    return view.model_copy(update={"step": "", "thinking": False, "choices": ()})


def _menu(view: Lite5eBattleView | None) -> tuple[str, tuple[BattleChoice, ...]] | None:
    return None if view is None else (view.step, view.choices)


def _foes_play(view: Lite5eBattleView | None) -> bool:
    return (
        view is not None
        and view.phase == "foes"
        and any(choice.command == NEXT for choice in view.choices)
    )
