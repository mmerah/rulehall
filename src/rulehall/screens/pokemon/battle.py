from collections.abc import Sequence
from functools import partial

from nicegui import ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.engines.pokemon.battle.battling import BATTLE_SCREEN_ID
from rulehall.engines.pokemon.battle.views import (
    BattleChoice,
    BattleHeader,
    BattleMon,
    BattleSide,
    BattleView,
)
from rulehall.ui import transcript
from rulehall.ui.battle_screen import RESOLVING, BattleScreenBase, facts_of
from rulehall.ui.panel_parts import avatar, choice_button, meter_grid, tag_row, tint
from rulehall.ui.routes import assets_route
from rulehall.ui.screen_host import ScreenHost
from rulehall.ui.widgets import heading, help_tip

FOOT_KINDS = frozenset({"next", "back", "item", "leave"})
TEAM_OPEN = "game-battle-team-open"


class ShowdownView(ui.element, component="showdown_view.js"):
    pass


class BattleScreen(BattleScreenBase[BattleView]):
    screen_id = BATTLE_SCREEN_ID
    view_type = BattleView

    def __init__(self, host: ScreenHost) -> None:
        super().__init__(host)
        self.battle_view_element: ui.element | None = None
        self.grid: ui.element
        self.log_dock: ui.element

    def build(self, now: SessionSnapshot) -> None:
        view = self.battle_view(now)
        with ui.column().classes("w-full flex-grow min-h-0 game-battle game-gap-0") as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            with ui.element("div").classes("game-battle-grid") as self.grid:
                # The battle view teleports its log into the dock, so the rail comes first.
                with ui.element("div").classes("game-battle-rail"):
                    self.draw_speech(_header(view))
                    self.draw_team(_choices(view))
                    with ui.element("div").classes("game-battle-journal"):
                        self.log_dock = ui.element("div").classes("game-battle-log")
                    self.cards = ui.element("div").classes("game-battle-cards")
                with ui.element("div").classes("game-battle-main"):
                    with ui.element("div").classes("game-battle-scene"):
                        self.draw_header(_header(view))
                        self.draw_battle_screen(now)
                    self.draw_fielded(_header(view))
                    self.draw_choices(_choices(view))
        self.column.set_visibility(False)
        self._draw_cards(facts_of(now), live=False)

    @ui.refreshable_method
    def draw_battle_screen(self, now: SessionSnapshot) -> None:
        if (view := self.battle_view(now)) is None:
            self.battle_view_element = None
            return
        settings = self.session.live_settings.current.pokemon
        self.battle_view_element = element = ShowdownView()
        element.props.update(
            {
                "base": assets_route(self.session.engine.id),
                "lines": list(_lines(now)),
                "sprites": settings.sprites,
                "dock": f"#{self.log_dock.html_id}",
                "battle-background": view.background,
                "battle-music": view.music,
            }
        )

    @ui.refreshable_method
    def draw_header(self, header: BattleHeader | None) -> None:
        if header is None:
            return
        with ui.element("div").classes("game-battle-strip"):
            with ui.element("div").classes("game-battle-sides"):
                for side in (header.player, header.ally):
                    if side is not None:
                        self._draw_side(side)
            ui.label("vs").classes("game-battle-vs")
            with ui.element("div").classes("game-battle-sides game-battle-foe"):
                self._draw_side(header.foe)
        if header.conditions:
            with ui.element("div").classes("game-battle-conditions"):
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
    def draw_fielded(self, header: BattleHeader | None) -> None:
        if header is None or not header.fielded:
            return
        with ui.element("div").classes("game-battle-fielded"):
            for mon in header.fielded:
                self._draw_mon(mon)

    @ui.refreshable_method
    def draw_choices(self, choices: tuple[BattleChoice, ...]) -> None:
        group = _group(choices)
        moves = [choice for choice in choices if choice.kind == "move"]
        megas = [choice for choice in choices if choice.kind == "mega"]
        foot = [choice for choice in choices if choice.kind in FOOT_KINDS]
        if moves and any(choice.kind == "switch" for choice in choices):
            with ui.element("div").classes("game-battle-tabs"):
                for label, icon, show_team in (
                    ("Fight", "sym_r_swords", False),
                    ("Team", "sym_r_backpack", True),
                ):
                    tab = ui.button(
                        label, icon=icon, on_click=partial(self._show_team, show=show_team)
                    )
                    tab.props("flat no-caps").classes(
                        f"game-battle-tab game-battle-tab-{label.lower()}"
                    )
        if moves:
            with ui.element("div").classes("game-battle-moves"):
                if group:
                    heading(group)
                for choice in megas:
                    self._draw_choice(choice)
                for choice in moves:
                    self._draw_move(choice)
        if foot:
            with ui.element("div").classes("game-battle-foot"):
                for choice in foot:
                    self._draw_choice(choice)

    @ui.refreshable_method
    def draw_team(self, choices: tuple[BattleChoice, ...]) -> None:
        if team := [choice for choice in choices if choice.kind == "switch"]:
            with ui.element("div").classes("game-battle-team"):
                heading(_group(choices) or "Team")
                for choice in team:
                    self._draw_choice(choice)

    def _redraw(self, now: SessionSnapshot) -> None:
        view = self.battle_view(now)
        header = _header(view)
        self.draw_header.refresh(header)
        self.draw_battle_screen.refresh(now)
        self.draw_speech.refresh(header)
        self.draw_fielded.refresh(header)
        self._refresh_choices(_choices(view))

    def _update(self, now: SessionSnapshot, drawn: SessionSnapshot) -> bool:
        lines = transcript.appended_since(_lines(now), _lines(drawn))
        if lines is None:
            return False
        view, before = self.battle_view(now), self.battle_view(drawn)
        header, choices = _header(view), _choices(view)
        if self.battle_view_element is not None and lines:
            self.battle_view_element.run_method("add", list(lines))
        if header != _header(before):
            self.draw_header.refresh(header)
            self.draw_fielded.refresh(header)
        if _said(header) != _said(_header(before)):
            self.draw_speech.refresh(header)
        if choices != _choices(before):
            self._refresh_choices(choices)
        return True

    def _refresh_choices(self, choices: tuple[BattleChoice, ...]) -> None:
        self.choice_buttons.clear()
        self.grid.classes(remove=TEAM_OPEN)
        self.column.classes(remove=RESOLVING)
        self.draw_choices.refresh(choices)
        self.draw_team.refresh(choices)

    def _draw_side(self, side: BattleSide) -> None:
        with ui.element("div").classes("game-battle-side"):
            avatar(self.session.find_asset(side.sprite), side.name)
            with ui.column().classes("game-gap-2xs game-battle-trainer"):
                ui.label(side.name).classes("game-battle-name")
                with ui.element("div").classes("game-battle-pips"):
                    for pip in side.pips:
                        ui.element("span").classes(f"game-pip game-pip-{pip}")

    def _draw_mon(self, mon: BattleMon) -> None:
        with ui.element("div").classes(
            "game-battle-mon" + (" game-battle-mon-deciding" if mon.deciding else "")
        ):
            avatar(self.session.find_asset(mon.sprite), mon.name)
            with ui.element("div").classes("game-battle-mon-body"):
                with ui.element("div").classes("game-battle-mon-head"):
                    ui.label(mon.name).classes("game-battle-mon-name")
                    tag_row(mon.tags)
                meter_grid((mon.hp,))

    def _draw_move(self, choice: BattleChoice) -> None:
        button = ui.button(on_click=partial(self._choose, choice.command))
        tint(button.props("outline no-caps").classes("game-choice game-battle-move"), choice.tags)
        with button.set_enabled(not choice.refusal), ui.element("div").classes("game-move-body"):
            with ui.element("div").classes("game-move-head"):
                with ui.label(choice.name).classes("game-move-name"):
                    help_tip(choice.help)
                for meter in choice.meters:
                    ui.label(f"{meter.name} {meter.current}/{meter.maximum}").classes(
                        "game-move-pp"
                    ).style(f"--game-pp: {meter.colour}")
            with ui.element("div").classes("game-move-info"):
                tag_row(choice.tags, opens=False)
                if stats := choice.refusal or choice.brief:
                    ui.label(stats).classes("game-move-stats")
        self.choice_buttons[choice.command] = button

    def _draw_choice(self, choice: BattleChoice) -> None:
        self.choice_buttons[choice.command] = choice_button(
            choice.name,
            choice.refusal or choice.brief,
            partial(self._choose, choice.command),
            enabled=not choice.refusal,
            help=choice.help,
            tags=choice.tags,
            meters=choice.meters,
            icon=None if choice.sprite is None else self.session.find_asset(choice.sprite),
        ).classes(f"game-choice-{choice.kind}")

    def _show_team(self, *, show: bool) -> None:
        self.grid.classes(add=TEAM_OPEN if show else "", remove="" if show else TEAM_OPEN)


def _lines(now: SessionSnapshot) -> tuple[str, ...]:
    return () if now.battle is None else now.battle.log


def _header(view: BattleView | None) -> BattleHeader | None:
    return None if view is None else view.header


def _choices(view: BattleView | None) -> tuple[BattleChoice, ...]:
    return () if view is None else view.choices


def _group(choices: Sequence[BattleChoice]) -> str:
    return next((choice.group for choice in choices if choice.group), "")


def _said(header: BattleHeader | None) -> tuple[str, ...]:
    speakers = () if header is None else (header.ally, header.foe)
    return tuple(side.said for side in speakers if side is not None)
