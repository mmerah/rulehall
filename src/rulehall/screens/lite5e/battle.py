from asyncio import sleep
from collections.abc import Mapping, Sequence
from functools import partial

from nicegui import background_tasks, ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.core.validation import Slug
from rulehall.core.views import Tag
from rulehall.engines.lite5e.battle.battling import BATTLE_SCREEN_ID
from rulehall.engines.lite5e.battle.views import (
    AUTO,
    END,
    NEXT,
    BattleChoice,
    BattleChoiceKind,
    BudgetView,
    ChoiceCategory,
    CombatantCard,
    Lite5eBattleView,
    PoolPips,
    TurnSlot,
    ordinal,
)
from rulehall.ui.battle_screen import RESOLVING, BattleScreenBase, facts_of
from rulehall.ui.panel_parts import MOST_PIPS, avatar, meter_grid, tag_row
from rulehall.ui.screen_host import ScreenHost

FOE_TURN_PAUSE = 1.5
TABS: dict[ChoiceCategory, str] = {
    "spells": "Spells",
    "attacks": "Attacks",
    "actions": "Actions",
    "bonus": "Bonus",
    "items": "Items",
}
ICONS: dict[ChoiceCategory, str] = {
    "spells": "sym_r_auto_awesome",
    "attacks": "sym_r_swords",
    "actions": "sym_r_directions_run",
    "bonus": "sym_r_bolt",
    "items": "sym_r_science",
    "turn": "sym_r_flag",
    "step": "sym_r_ads_click",
}
AIM_KINDS: frozenset[BattleChoiceKind] = frozenset({"target", "slot", "done", "back"})
LOG_OPEN = "game-lite5e-log-open"
AIMING = "game-lite5e-aiming"
SELECTED = "game-lite5e-dock-selected"
SHOW_SHEET = (
    "const sheet = getHtmlElement({column_id})?.querySelector('.{selected} .game-lite5e-detail'); "
    "if (sheet && getComputedStyle(sheet).position === 'sticky') "
    "sheet.scrollIntoView({{block: 'end'}})"
)
BACK_ROW = Tag(name="Back")


class Lite5eBattleScreen(BattleScreenBase[Lite5eBattleView]):
    screen_id = BATTLE_SCREEN_ID
    view_type = Lite5eBattleView

    def __init__(self, host: ScreenHost) -> None:
        super().__init__(host)
        self.sending = False
        self.thinking: ui.label
        self.ribbon: ui.element
        self.shown_view: Lite5eBattleView | None = None
        self.field_commands: set[str] = set()
        self.turn: tuple[int, Slug] | None = None
        self.tab: ChoiceCategory = "spells"
        self.selected = ""
        self.option = ""

    def build(self, now: SessionSnapshot) -> None:
        view = self.battle_view(now)
        with ui.column().classes("w-full flex-grow min-h-0 game-lite5e game-gap-0") as self.column:
            self.hint = ui.label("Starting the battle…").classes("game-hint")
            self.thinking = ui.label("Foes thinking…").classes("game-lite5e-thinking")
            with ui.element("div").classes("game-lite5e-field"):
                self.draw_foes(view)
                with ui.element("div").classes("game-lite5e-ribbon") as self.ribbon:
                    with ui.element("div").classes("game-lite5e-log"):
                        self.cards = ui.element("div").classes("game-lite5e-cards")
                    ui.button("Log", icon="sym_r_history", on_click=self._toggle_log).props(
                        "flat no-caps dense"
                    ).classes("game-lite5e-log-toggle")
                self.draw_party(view)
            self.draw_dock(view)
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
    def draw_foes(self, view: Lite5eBattleView | None) -> None:
        if view is None:
            return
        self._draw_side(view, view.foes, "foes")
        self._draw_order(view.round, view.order)

    @ui.refreshable_method
    def draw_party(self, view: Lite5eBattleView | None) -> None:
        if view is None:
            return
        self._draw_side(view, view.party, "party")

    @ui.refreshable_method
    def draw_dock(self, view: Lite5eBattleView | None) -> None:
        self.shown_view = view
        aiming = view is not None and _aiming(view)
        if aiming:
            self.column.classes(add=AIMING)
        else:
            self.column.classes(remove=AIMING)
        if view is None:
            return
        if aiming:
            self._draw_aim(view)
        elif view.budget is None:
            self._draw_wait(view)
        else:
            self._draw_menu(view, view.budget)

    def _redraw(self, now: SessionSnapshot) -> None:
        self._reset_menu(None)
        view = self.battle_view(now)
        self._refresh_field(view)
        self._refresh_dock(view)

    def _update(self, now: SessionSnapshot, drawn: SessionSnapshot) -> bool:
        view, before = self.battle_view(now), self.battle_view(drawn)
        if _field(view) != _field(before):
            self._refresh_field(view)
        if _dock(view) != _dock(before):
            self._refresh_dock(view)
        return True

    def _refresh_field(self, view: Lite5eBattleView | None) -> None:
        self._forget_buttons(field=True)
        self.draw_foes.refresh(view)
        self.draw_party.refresh(view)

    def _refresh_dock(self, view: Lite5eBattleView | None) -> None:
        self._forget_buttons(field=False)
        self.column.classes(remove=RESOLVING)
        self.draw_dock.refresh(view)

    def _forget_buttons(self, *, field: bool) -> None:
        self.choice_buttons = {
            command: button
            for command, button in self.choice_buttons.items()
            if (command in self.field_commands) != field
        }
        if field:
            self.field_commands.clear()

    def _card_box(self, *, live: bool) -> ui.element:
        # The first batch of a page holds the whole log so far, not one action.
        action = live and bool(self.cards.default_slot.children)
        with self.cards:
            return ui.element("div").classes("game-lite5e-batch" + (" live" if action else ""))

    def _toggle_log(self) -> None:
        if LOG_OPEN in self.ribbon.classes:
            self.ribbon.classes(remove=LOG_OPEN)
        else:
            self.ribbon.classes(add=LOG_OPEN)

    def _reset_menu(self, turn: tuple[int, Slug] | None) -> None:
        self.turn, self.tab, self.selected, self.option = turn, "spells", "", ""

    def _field_button(self, command: str, button: ui.button) -> None:
        self.choice_buttons[command] = button
        self.field_commands.add(command)

    def _draw_side(self, view: Lite5eBattleView, cards: Sequence[CombatantCard], side: str) -> None:
        targets = {
            choice.target_id: choice for choice in view.choices if choice.target_id is not None
        }
        with ui.element("div").classes(f"game-lite5e-side game-lite5e-side-{side}"):
            for card in sorted(cards, key=lambda card: card.row != "front"):
                self._draw_card(card, targets)

    def _draw_card(self, card: CombatantCard, targets: Mapping[Slug, BattleChoice]) -> None:
        target = targets.get(card.combatant_id)
        classes = " ".join(
            (
                f"game-lite5e-card game-lite5e-card-{card.side}",
                "game-lite5e-card-current" if card.current else "",
                "game-lite5e-card-target" if target is not None else "",
                "game-lite5e-card-aimed" if card.picked else "",
            )
        )
        with ui.element("div").classes(classes):
            if card.current:
                ui.label("Now").classes("game-lite5e-now")
            avatar(self.session.find_asset(card.sprite), card.name)
            with ui.element("div").classes("game-lite5e-card-body"):
                ui.label(card.name).classes("game-lite5e-card-name")
                if card.hp is not None:
                    meter_grid((card.hp,))
                tags = (
                    *((BACK_ROW,) if card.row == "back" else ()),
                    *(() if card.band is None else (card.band,)),
                    *card.tags,
                )
                if tags:
                    tag_row(tags)
            if card.auto is not None:
                command = f"{AUTO} {card.combatant_id}"
                button = ui.button("Auto", on_click=partial(self._choose, command))
                button.props(f"{'unelevated' if card.auto else 'outline'} no-caps dense")
                self._field_button(command, button.classes("game-lite5e-auto"))
            if card.picked:
                with ui.element("div").classes("game-lite5e-picked"):
                    ui.icon("sym_r_my_location")
                    ui.label(f"{card.picked}")
            if target is not None:
                if target.brief:
                    chance = ui.label(target.brief).classes("game-lite5e-chance")
                    chance.props.update({"title": target.help})
                button = ui.button(on_click=partial(self._choose, target.command))
                button.props("flat").classes("game-lite5e-card-hit")
                button.props.update({"aria-label": f"Aim at {card.name}", "title": target.help})
                self._field_button(target.command, button)

    def _draw_order(self, round_number: int, order: Sequence[TurnSlot]) -> None:
        with ui.element("div").classes("game-lite5e-order"):
            ui.label(f"Round {round_number}").classes("game-lite5e-round")
            for index, slot in enumerate(order):
                if index:
                    ui.icon("sym_r_chevron_right").classes("game-lite5e-turn-sep")
                current = " game-lite5e-turn-current" if slot.current else ""
                ui.label(slot.name).classes(f"game-lite5e-turn{current}")
            ui.label(_order_line(round_number, order)).classes("game-lite5e-order-short")

    def _draw_wait(self, view: Lite5eBattleView) -> None:
        with ui.element("div").classes("game-lite5e-dock game-lite5e-dock-wait"):
            ui.label(view.step).classes("game-lite5e-who")
            for choice in view.choices:
                self._command_button(choice, choice.name, "sym_r_skip_next", primary=True)

    def _draw_aim(self, view: Lite5eBattleView) -> None:
        slots = [choice for choice in view.choices if choice.kind == "slot"]
        targets = any(choice.kind == "target" for choice in view.choices)
        with ui.element("div").classes("game-lite5e-dock game-lite5e-dock-aim"):
            with ui.element("div").classes("game-lite5e-aim-text"):
                ui.icon(ICONS["step"]).classes("game-lite5e-aim-icon")
                ui.label(view.step).classes("game-lite5e-aim-step")
                if targets and view.repeats:
                    repeat = ui.icon("sym_r_repeat").classes("game-lite5e-aim-repeat")
                    repeat.props.update({"title": "The same target may repeat"})
            if slots:
                with ui.element("div").classes("game-lite5e-aim-picks"):
                    for choice in slots:
                        self._option_button(choice)
            with ui.element("div").classes("game-lite5e-aim-actions"):
                for choice in view.choices:
                    if choice.kind == "back":
                        self._command_button(choice, "Back", "sym_r_undo", primary=False)
                for choice in view.choices:
                    if choice.kind == "done":
                        self._command_button(choice, "Done", "sym_r_check", primary=True)

    def _draw_menu(self, view: Lite5eBattleView, budget: BudgetView) -> None:
        member_id = next((card.combatant_id for card in view.party if card.current), "")
        if (view.round, member_id) != self.turn:
            self._reset_menu((view.round, member_id))
        heads = [choice for choice in view.choices if not choice.family and choice.command != END]
        tabs: dict[ChoiceCategory, list[BattleChoice]] = {
            category: [choice for choice in heads if _tab_of(choice) == category]
            for category in TABS
        }
        shown: list[ChoiceCategory] = [category for category, choices in tabs.items() if choices]
        if self.tab not in shown and shown:
            self.tab = shown[0]
        listed = tabs.get(self.tab, [])
        if self.selected not in {choice.command for choice in listed}:
            self.selected, self.option = "", ""
        selected = " " + SELECTED if self.selected else ""
        with ui.element("div").classes("game-lite5e-dock" + selected):
            self._draw_budget(view, budget)
            if not shown:
                return
            with ui.element("div").classes("game-lite5e-dock-main"):
                with ui.element("div").classes("game-lite5e-browse"):
                    with ui.element("div").classes("game-lite5e-tabs"):
                        for category in shown:
                            self._draw_tab(category)
                    with ui.element("div").classes("game-lite5e-list"):
                        if self.tab == "spells":
                            self._draw_spells(view, listed)
                        else:
                            self._draw_tiles(listed)
                with ui.element("div").classes("game-lite5e-detail"):
                    head = next((c for c in listed if c.command == self.selected), None)
                    if head is None:
                        _draw_detail_hint()
                    else:
                        self._draw_detail(head, _family(view, head))

    def _draw_budget(self, view: Lite5eBattleView, budget: BudgetView) -> None:
        with ui.element("div").classes("game-lite5e-budget"):
            ui.label(view.step).classes("game-lite5e-who")
            with ui.element("div").classes("game-lite5e-econ"):
                for name, open_ in (
                    ("Action", budget.action),
                    ("Bonus", budget.bonus),
                    ("Move", budget.move),
                ):
                    ui.label(name).classes("game-lite5e-econ-pill" + ("" if open_ else " used"))
                if budget.attacks_left:
                    ui.label(
                        f"{budget.attacks_left} attack{'' if budget.attacks_left == 1 else 's'}"
                    ).classes("game-lite5e-econ-pill")
            pools = [
                pool
                for pool in view.pools
                if pool.slot_level is None and self.tab in pool.categories
            ]
            if pools:
                with ui.element("div").classes("game-lite5e-pools"):
                    for pool in pools:
                        with ui.element("div").classes("game-lite5e-pool"):
                            ui.label(pool.name).classes("game-lite5e-pool-name")
                            _draw_pips(pool)
            with ui.element("div").classes("game-lite5e-budget-end"):
                for choice in view.choices:
                    if choice.command == END:
                        self._command_button(choice, "End turn", "sym_r_skip_next", primary=False)

    def _draw_tab(self, category: ChoiceCategory) -> None:
        on = " game-lite5e-tab-on" if category == self.tab else ""
        ui.button(TABS[category], on_click=partial(self._pick_tab, category)).props(
            "flat no-caps"
        ).classes("game-lite5e-tab" + on)

    def _draw_spells(self, view: Lite5eBattleView, spells: Sequence[BattleChoice]) -> None:
        pools = {pool.slot_level: pool for pool in view.pools if pool.slot_level is not None}
        for level in sorted({choice.level or 0 for choice in spells}):
            with ui.element("div").classes("game-lite5e-level"):
                ui.label("Cantrips" if level == 0 else ordinal(level))
                if (pool := pools.get(level)) is not None:
                    _draw_pips(pool)
            self._draw_tiles([c for c in spells if (c.level or 0) == level])

    def _draw_tiles(self, choices: Sequence[BattleChoice]) -> None:
        with ui.element("div").classes("game-lite5e-tiles"):
            for choice in choices:
                on = " game-lite5e-tile-on" if choice.command == self.selected else ""
                with (
                    ui.button(on_click=partial(self._select, choice.command))
                    .props("flat no-caps")
                    .classes(f"game-lite5e-tile game-lite5e-tile-{choice.category}{on}")
                ):
                    ui.icon(ICONS[choice.category]).classes("game-lite5e-tile-icon")
                    with ui.element("div").classes("game-lite5e-tile-head"):
                        ui.label(choice.name).classes("game-lite5e-tile-name")
                        if choice.ways:
                            ui.icon("sym_r_chevron_right").classes("game-lite5e-tile-more")
                    if brief := choice.brief or " · ".join(choice.stats):
                        ui.label(brief).classes("game-lite5e-tile-brief")

    def _draw_detail(self, head: BattleChoice, family: Sequence[BattleChoice]) -> None:
        if head.options and self.option not in head.options:
            self.option = head.options[0]
        column = head.options.index(self.option) if head.options else 0
        offered = [way.commands[column] for way in head.ways] or [head.command]
        command = next((found for found in offered if found is not None), None)
        chosen = next((choice for choice in family if choice.command == command), head)
        with ui.element("div").classes("game-lite5e-detail-body"):
            ui.label(head.name).classes("game-lite5e-detail-name")
            bonus = chosen.kind == "bonus"
            if bonus or chosen.stats:
                with ui.element("div").classes("game-lite5e-stats"):
                    if bonus:
                        ui.label("Bonus").classes("game-lite5e-stat game-lite5e-stat-bonus")
                    for part in chosen.stats:
                        ui.label(part).classes("game-lite5e-stat")
            if head.options:
                self._draw_options(head)
            if len(head.ways) > 1:
                with ui.element("div").classes("game-lite5e-variants"):
                    for way in head.ways:
                        self._draw_variant(way.variant, way.commands[column])
            _draw_help(head)
        with ui.element("div").classes("game-lite5e-confirm"):
            cancel = ui.button(icon="sym_r_close", on_click=partial(self._select, ""))
            cancel.props("outline").classes("game-lite5e-cancel")
            cancel.props.update({"aria-label": "Cancel"})
            if len(head.ways) > 1:
                return
            button = ui.button(_confirm_label(chosen), icon=ICONS[chosen.category])
            button.props("unelevated no-caps").classes("game-choice game-lite5e-command primary")
            if command is None:
                button.disable()
                return
            button.on_click(partial(self._choose, command))
            self.choice_buttons[command] = button

    def _draw_options(self, head: BattleChoice) -> None:
        with ui.element("div").classes("game-lite5e-toggle"):
            ui.label(head.option_label).classes("game-lite5e-option-label")
            for option in head.options:
                on = " game-lite5e-toggle-on" if option == self.option else ""
                ui.button(option or "None", on_click=partial(self._pick_option, option)).props(
                    "flat no-caps dense"
                ).classes("game-lite5e-toggle-button" + on)

    def _draw_variant(self, variant: str, command: str | None) -> None:
        button = ui.button(variant or "Standard").props("outline no-caps")
        button.classes("game-choice game-lite5e-variant")
        if command is None:
            button.disable()
            return
        button.on_click(partial(self._choose, command))
        self.choice_buttons[command] = button

    def _option_button(self, choice: BattleChoice) -> None:
        with (
            ui.button(on_click=partial(self._choose, choice.command))
            .props("outline no-caps")
            .classes("game-choice game-lite5e-option") as button
        ):
            ui.label(choice.name).classes("game-lite5e-option-name")
            if choice.brief:
                ui.label(choice.brief).classes("game-lite5e-option-brief")
        self.choice_buttons[choice.command] = button

    def _command_button(
        self, choice: BattleChoice, label: str, icon: str, *, primary: bool
    ) -> None:
        button = ui.button(label, icon=icon, on_click=partial(self._choose, choice.command))
        button.props(f"{'unelevated' if primary else 'outline'} no-caps")
        button.classes("game-choice game-lite5e-command" + (" primary" if primary else ""))
        self.choice_buttons[choice.command] = button

    async def _pick_tab(self, category: ChoiceCategory) -> None:
        self.tab, self.selected, self.option = category, "", ""
        await self._redock()

    async def _select(self, command: str) -> None:
        self.selected, self.option = command, ""
        await self._redock()
        if command:
            ui.run_javascript(SHOW_SHEET.format(column_id=self.column.id, selected=SELECTED))

    async def _pick_option(self, option: str) -> None:
        self.option = option
        await self._redock()

    async def _redock(self) -> None:
        self._forget_buttons(field=False)
        await self.draw_dock.refresh(self.shown_view)

    async def _play_foe_turn(self) -> None:
        try:
            await sleep(FOE_TURN_PAUSE)
            # The page may have closed, or the player sent the turn by hand, during the pause.
            if (
                not self.column.is_deleted
                and self.shown
                and _foes_play(self.battle_view(self.session.snapshot()))
            ):
                await self._choose(NEXT)
        finally:
            self.sending = False


def _field(view: Lite5eBattleView | None) -> Lite5eBattleView | None:
    if view is None:
        return None
    targets = tuple(choice for choice in view.choices if choice.target_id is not None)
    return view.model_copy(
        update={
            "step": "",
            "thinking": False,
            "choices": targets,
            "aiming": "",
            "repeats": False,
            "budget": None,
            "pools": (),
        }
    )


def _dock(view: Lite5eBattleView | None) -> Lite5eBattleView | None:
    if view is None:
        return None
    return view.model_copy(update={"thinking": False})


def _foes_play(view: Lite5eBattleView | None) -> bool:
    return (
        view is not None
        and view.phase == "foes"
        and any(choice.command == NEXT for choice in view.choices)
    )


def _aiming(view: Lite5eBattleView) -> bool:
    return any(choice.kind in AIM_KINDS for choice in view.choices)


def _tab_of(choice: BattleChoice) -> ChoiceCategory:
    return "actions" if choice.category == "turn" else choice.category


def _family(view: Lite5eBattleView, head: BattleChoice) -> list[BattleChoice]:
    return [head, *(choice for choice in view.choices if choice.family == head.command)]


def _order_line(round_number: int, order: Sequence[TurnSlot]) -> str:
    index = next((index for index, slot in enumerate(order) if slot.current), None)
    if index is None or len(order) < 2:
        return f"R{round_number}"
    return f"R{round_number} · next: {order[(index + 1) % len(order)].name}"


def _confirm_label(choice: BattleChoice) -> str:
    if choice.category == "spells":
        return "Cast"
    if choice.category == "turn":
        return choice.name
    return "Use"


def _draw_help(choice: BattleChoice) -> None:
    if choice.help:
        ui.label(choice.help).classes("game-lite5e-detail-text")
    if choice.rules:
        with ui.expansion("Rules").props("dense").classes("game-lite5e-rules"):
            for paragraph in choice.rules.splitlines():
                if paragraph.strip():
                    ui.label(paragraph).classes("game-lite5e-detail-text")


def _draw_detail_hint() -> None:
    with ui.element("div").classes("game-lite5e-detail-empty"):
        ui.icon("sym_r_touch_app").classes("game-lite5e-detail-icon")
        ui.label("Pick an action").classes("game-lite5e-detail-hint")


def _draw_pips(pool: PoolPips) -> None:
    if pool.maximum > MOST_PIPS:
        ui.label(f"{pool.left}/{pool.maximum}").classes("game-lite5e-pool-count")
        return
    with ui.element("div").classes("game-pips"):
        for index in range(pool.maximum):
            ui.element("span").classes("game-pip" + (" game-pip-on" if index < pool.left else ""))
