from collections.abc import Callable, Sequence
from functools import cache, partial
from pathlib import Path
from typing import cast

from nicegui import background_tasks, ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.facts import Fact
from rulehall.core.views import BattleChoice, BattleHeader, BattleMon, BattleSide
from rulehall.ui import transcript
from rulehall.ui.panel_parts import avatar, choice_button, meter_grid, tag_row, tint
from rulehall.ui.routes import assets_route
from rulehall.ui.widgets import Sounds, attempt, failure_notice, heading, help_tip

BATTLE_FAILED = failure_notice("The battle did not start.")
MOVE_FAILED = failure_notice("The move was not played.")
FOOT_KINDS = frozenset({"next", "back", "item", "leave"})
TEAM_OPEN = "game-battle-team-open"
RESOLVING = "game-battle-resolving"
PICKED = "game-choice-picked"


class BattlePanel:
    def __init__(self, session: GameSession, sounds: Sounds, on_show: Callable[[], None]) -> None:
        self.session = session
        self.sounds = sounds
        self.on_show = on_show
        self.shown = False
        self.opening = False
        self.battle_view_element: ui.element | None = None
        self.choice_buttons: dict[str, ui.button] = {}
        self.banner: ui.column
        self.story: ui.element
        self.column: ui.column
        self.hint: ui.label
        self.grid: ui.element
        self.log_dock: ui.element
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
        with ui.column().classes("w-full flex-grow min-h-0 game-battle game-gap-0") as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            with ui.element("div").classes("game-battle-grid") as self.grid:
                # The battle view teleports its log into the dock, so the rail comes first.
                with ui.element("div").classes("game-battle-rail"):
                    self.draw_speech(now.battle_header)
                    self.draw_team(now.battle_choices)
                    with ui.element("div").classes("game-battle-journal"):
                        self.log_dock = ui.element("div").classes("game-battle-log")
                    self.cards = ui.element("div").classes("game-battle-cards")
                with ui.element("div").classes("game-battle-main"):
                    with ui.element("div").classes("game-battle-scene"):
                        self.draw_header(now.battle_header)
                        self.draw_battle_screen(now)
                    self.draw_fielded(now.battle_header)
                    self.draw_choices(now.battle_choices)
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
                **run.view_props(),
                "base": assets_route(session.engine.id),
                "lines": list(now.battle_log),
                "sprites": session.live_settings.current.battle.sprites,
                "music": session.live_settings.current.battle.music,
                "dock": f"#{self.log_dock.html_id}",
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
            self.draw_fielded.refresh(now.battle_header)
            self._refresh_choices(now.battle_choices)
            self.cards.clear()
            self._draw_cards(now.battle_facts)
            return
        if self.battle_view_element is not None and lines:
            self.battle_view_element.run_method("add", list(lines))
        if now.battle_header != drawn.battle_header:
            self.draw_header.refresh(now.battle_header)
            self.draw_fielded.refresh(now.battle_header)
        if _said(now.battle_header) != _said(drawn.battle_header):
            self.draw_speech.refresh(now.battle_header)
        if now.battle_choices != drawn.battle_choices:
            self._refresh_choices(now.battle_choices)
        with self.cards:
            for fact in fresh:
                transcript.draw_fact_card(fact, live=True)
        self.sounds.roll_dice(fresh)

    def _refresh_choices(self, choices: tuple[BattleChoice, ...]) -> None:
        self.choice_buttons.clear()
        self.grid.classes(remove=f"{TEAM_OPEN} {RESOLVING}")
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
                tag_row(choice.tags)
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

    def _draw_cards(self, facts: Sequence[Fact]) -> None:
        with self.cards:
            for fact in facts:
                transcript.draw_fact_card(fact)

    def _show_team(self, *, show: bool) -> None:
        self.grid.classes(add=TEAM_OPEN if show else "", remove="" if show else TEAM_OPEN)

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
        picked = self.choice_buttons.get(command)
        self.grid.classes(RESOLVING)
        if picked is not None:
            picked.classes(PICKED)
        # The sync may have deleted the clicked button while the model was thinking.
        with self.column:
            chosen = await attempt(lambda: self.session.battle_command(command), failed=MOVE_FAILED)
        self.grid.classes(remove=RESOLVING)
        if picked is not None and not picked.is_deleted:
            picked.classes(remove=PICKED)
        if not chosen and self.shown and self.session.battle_run is None:
            self._open()


def _group(choices: Sequence[BattleChoice]) -> str:
    return next((choice.group for choice in choices if choice.group), "")


def _said(header: BattleHeader | None) -> tuple[str, ...]:
    speakers = () if header is None else (header.ally, header.foe)
    return tuple(side.said for side in speakers if side is not None)


@cache
def battle_component_class(component: Path) -> type[ui.element]:
    return cast(type[ui.element], type("BattleView", (ui.element,), {}, component=component))
