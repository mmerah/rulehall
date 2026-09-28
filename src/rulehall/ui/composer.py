from collections.abc import Awaitable, Callable
from typing import Literal

from nicegui import app, ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.config import Role
from rulehall.core.decisions import ActionOption, PlayerInput
from rulehall.core.views import PlayerView
from rulehall.ui.panel_parts import choice_button
from rulehall.ui.transcript import ROLE_COPY
from rulehall.ui.widgets import HELP_ICON, entered_text, warn

type ComposerLock = Literal["over", "battle", "answer", "choose"] | Role
type PromptState = Literal["asking", "over"]

GAME_OVER = "The game is over. Restart it from the menu."
BATTLE_ON = "A battle is on. Finish it on the battle screen."
ANSWER_FIRST = "Answer the question above first."
PLACEHOLDERS: dict[ComposerLock, str] = {
    "over": GAME_OVER,
    "battle": BATTLE_ON,
    "answer": "Type your answer.",
    **{role: f"{name} is working..." for role, (name, _) in ROLE_COPY.items()},
}
CLOSED_REASONS: dict[ComposerLock | None, str] = {
    "over": GAME_OVER,
    "battle": BATTLE_ON,
    "answer": ANSWER_FIRST,
    "choose": ANSWER_FIRST,
    None: "",
    **{role: f"{name} is working. Wait for it." for role, (name, _) in ROLE_COPY.items()},
}
PROMPT_ICONS: dict[PromptState, str] = {
    "asking": "sym_r_help",
    "over": "sym_r_flag",
}
PROMPT_CLASSES: dict[PromptState, str] = {
    "asking": "game-asking",
    "over": "game-action-over",
}


class ActionBar:
    def __init__(
        self,
        session: GameSession,
        now: SessionSnapshot,
        choose: Callable[[PlayerInput], Awaitable[bool]],
    ) -> None:
        self.choose = choose
        self.view = now.view
        self.lock: ComposerLock | None = composer_lock(now)
        self.armed: ActionOption | None = None
        self.acting = False
        self.explained = False
        self.chips: list[tuple[ui.button, ActionOption]] = []
        with ui.column().classes("w-full game-action-bar game-gap-md") as self.bar:
            with ui.row().classes(
                "w-full items-start no-wrap game-action-prompt game-gap-md"
            ) as self.prompt_row:
                self.prompt_icon = ui.icon(PROMPT_ICONS["asking"])
                self.prompt = ui.label()
            with ui.column().classes("w-full game-composer game-gap-0"):
                with ui.element("div").classes("game-moves-line") as self.moves_line:
                    self.chip_row = ui.element("div").classes("game-moves")
                    self.explain_button = (
                        ui.button(icon=HELP_ICON, on_click=self.toggle_explained, color=None)
                        .props('flat aria-label="Explain the moves" aria-pressed=false')
                        .classes("game-explain")
                    )
                with ui.row().classes(
                    "w-full no-wrap items-end game-composer-line game-gap-lg"
                ) as self.input_row:
                    self.composer_input = (
                        ui.input()
                        .classes("flex-grow")
                        # theme.py's default w-full would fight flex-grow and squeeze the send.
                        .classes(remove="w-full")
                        .props(
                            'autogrow dense type=textarea borderless input-style="max-height: 9rem"'
                        )
                        .props(remove="outlined")
                    )
                    self.composer_input.bind_value(app.storage.tab, f"draft:{session.key.save_id}")
                    # Enter sends on a fine pointer only; a touch keyboard's Enter stays a newline.
                    self.composer_input.on(
                        "keydown.enter",
                        self.submit,
                        js_handler=(
                            '(e) => { if (e.shiftKey || !matchMedia("(pointer: fine)").matches) '
                            "return; e.preventDefault(); emit(); }"
                        ),
                    )
                    # `color=None`: Quasar's `text-primary` would paint the glyph the fill's gold.
                    self.send_button = (
                        ui.button(icon="sym_r_arrow_upward", on_click=self.submit, color=None)
                        .props("round flat no-caps aria-label=Send")
                        .classes("game-send")
                    )
        self._clear_spent_draft(now)
        self._draw_chips()
        self._show(now, entering=False)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.view = now.view
        self.lock = composer_lock(now)
        if len(now.log_entries) > len(drawn.log_entries):
            self._clear_spent_draft(now)
        if self.armed not in self.view.moves:
            self.armed = None
        if offered(self.view) != offered(drawn.view):
            self._draw_chips()
        self._show(now, entering=self.view.decision not in (None, drawn.view.decision))

    def set_enabled(self, *, enabled: bool) -> None:
        self.acting = enabled
        for widget in (self.composer_input, self.send_button, *(chip for chip, _ in self.chips)):
            widget.set_enabled(enabled)

    def prefill(self, words: str) -> None:
        self.armed = None
        self._show_armed()
        self.set_input(words)
        self.composer_input.run_method("focus")

    def arm(self, move: ActionOption | None) -> None:
        self.armed = move
        self._show_armed()
        self.composer_input.run_method("focus")

    def toggle_explained(self) -> None:
        self.explained = not self.explained
        self.explain_button.props(f"aria-pressed={str(self.explained).lower()}")
        self.explain_button.classes(
            add="game-explain-on" if self.explained else "", remove="game-explain-on"
        )
        self._draw_chips()
        self._show_chips()

    async def pick(self, option: ActionOption) -> None:
        if option.needs_words:
            self.arm(None if option == self.armed else option)
            return
        _ = await self.choose(PlayerInput(option_id=option.id))

    async def submit(self) -> None:
        words = entered_text(self.composer_input)
        move = self.armed or forced_move(self.view)
        if not words:
            if move is not None:
                warn(f"Type your words, then press {move.name}.")
            return
        if await self.choose(PlayerInput(option_id=None if move is None else move.id, text=words)):
            self.set_input()
            self.armed = None
            self._show_armed()

    def set_input(self, words: str = "") -> None:
        self.composer_input.value = words
        # Quasar never saw the value change, so only an explicit push empties the composer.
        self.composer_input.run_method("updateValue")

    def _clear_spent_draft(self, now: SessionSnapshot) -> None:
        draft = entered_text(self.composer_input)
        if draft and now.log_entries and draft == now.log_entries[-1].words:
            self.set_input()

    def _draw_chips(self) -> None:
        options = offered(self.view)
        lines = [self._cell_line(option) for option in options]
        self.chip_row.clear()
        self.chips = []
        with self.chip_row:
            for option, line in zip(options, lines, strict=True):
                chip = choice_button(
                    option.name, line, lambda chosen=option: self.pick(chosen), enabled=False
                )
                if (help := option.refusal or option.help) and help != line:
                    with chip:
                        ui.tooltip(help).classes("game-help-tip")
                self.chips.append((chip, option))
        self.moves_line.set_visibility(bool(self.chips))
        self.chip_row.classes(
            add="game-moves-briefed" if any(lines) else "", remove="game-moves-briefed"
        )
        self.explain_button.set_visibility(any(option.refusal or option.help for option in options))

    def _cell_line(self, option: ActionOption) -> str:
        asking = self.view.decision is not None
        if self.explained:
            return option.refusal or option.help or (option.brief if asking else "")
        return (option.refusal or option.brief) if asking else ""

    def _show_chips(self) -> None:
        for chip, option in self.chips:
            chip.set_enabled(self.acting and not option.refusal)
        self._show_armed()

    def _show(self, now: SessionSnapshot, *, entering: bool) -> None:
        view, lock = self.view, self.lock
        self.acting = not now.held_elsewhere and lock in (None, "answer", "choose")
        worded = lock != "choose" and (
            view.allows_text or any(move.needs_words for move in view.moves)
        )
        self.input_row.set_visibility(worded)
        self.composer_input.set_enabled(self.acting and worded)
        self.send_button.set_enabled(self.acting and worded)
        state: PromptState | None
        if view.ending is not None:
            state, text = "over", view.ending
        elif view.decision is not None:
            state, text = "asking", view.decision.prompt
        else:
            state, text = None, ""
        self.prompt.set_text(text)
        self.prompt_row.set_visibility(state is not None)
        if state is not None:
            self.prompt_icon.set_name(PROMPT_ICONS[state])
        self.bar.classes(
            add=(PROMPT_CLASSES[state] if state else "") + (" game-enter" if entering else ""),
            remove=" ".join((*PROMPT_CLASSES.values(), "game-enter")),
        )
        self._show_chips()

    def _show_armed(self) -> None:
        forced = forced_move(self.view)
        move = self.armed or forced
        for chip, option in self.chips:
            chip.classes(add="game-choice-on" if option == move else "", remove="game-choice-on")
        if self.lock not in (None, "choose"):
            placeholder = PLACEHOLDERS[self.lock]
        elif self.armed is not None and forced is None:
            placeholder = self.armed.help or f"Type your words, then press {self.armed.name}."
        else:
            placeholder = forced.help if forced and forced.help else self.view.hint
        self.composer_input.props["placeholder"] = placeholder
        self.send_button.set_text("" if move is None else move.name)
        if move is None:
            self.send_button.props("round").classes(remove="game-send-named")
        else:
            self.send_button.props(remove="round").classes("game-send-named")


def offered(view: PlayerView) -> tuple[ActionOption, ...]:
    return view.decision.options if view.decision is not None else view.moves


def forced_move(view: PlayerView) -> ActionOption | None:
    worded = [move for move in view.moves if move.needs_words]
    return worded[0] if not view.allows_text and len(worded) == 1 else None


def composer_lock(now: SessionSnapshot) -> ComposerLock | None:
    view = now.view
    if view.ending is not None:
        return "over"
    if now.working_role is not None:
        return now.working_role
    if now.in_battle:
        return "battle"
    if view.decision is not None:
        return "answer" if view.decision.allows_text else "choose"
    return None
