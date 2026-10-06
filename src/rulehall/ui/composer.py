from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated, Literal

from nicegui import app, ui
from nicegui.elements.mixins.disableable_element import DisableableElement
from nicegui.events import GenericEventArguments
from pydantic import Base64Bytes, Field

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.config import Role
from rulehall.core.decisions import ActionOption, PlayerInput
from rulehall.core.validation import Frozen, parse
from rulehall.core.views import PlayerView
from rulehall.ui.panel_parts import CHOICES_ROW, choice_button
from rulehall.ui.transcript import ROLE_COPY
from rulehall.ui.widgets import (
    HELP_ICON,
    Speech,
    attempt,
    entered_text,
    failure_notice,
    heading,
    warn,
)

type ComposerLock = Literal["over", "battle", "answer", "choose"] | Role
type PromptState = Literal["asking", "over"]
type ChipCell = tuple[str, tuple[ActionOption, ...]]

GAME_OVER = "The game is over. Restart it from the menu."
BATTLE_ON = "A battle is on. Finish it on the battle screen."
ANSWER_FIRST = "Answer the question above first."
HEARING_FAILED = failure_notice("The speech was not understood.")
# A blur closes the keyboard, the shell grows under the finger (theme.py KEYBOARD_FIT), and iOS
# drops the click.
KEEP_FOCUS = "(e) => e.preventDefault()"
MIC_ICONS = {True: "sym_r_stop", False: "sym_r_mic"}
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


class Recording(Frozen):
    audio: Annotated[Base64Bytes, Field(min_length=1, strict=False)]
    mime: str


class Composer:
    def __init__(
        self,
        session: GameSession,
        now: SessionSnapshot,
        choose: Callable[[PlayerInput], Awaitable[bool]],
        speech: Speech | None,
    ) -> None:
        self.session = session
        self.choose = choose
        self.view = now.view
        self.lock: ComposerLock | None = composer_lock(now)
        self.armed: ActionOption | None = None
        self.acting = False
        self.explained = False
        self.chips: list[tuple[ui.button, tuple[ActionOption, ...]]] = []
        self.group_dialog = ui.dialog()
        with ui.column().classes("w-full game-action-bar game-gap-md") as self.row:
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
                    self.words_input = (
                        ui.input()
                        .classes("flex-grow")
                        # theme.py's default w-full would fight flex-grow and squeeze the send.
                        .classes(remove="w-full")
                        .props(
                            'autogrow dense type=textarea borderless input-style="max-height: 9rem"'
                        )
                        .props(remove="outlined")
                    )
                    self.words_input.bind_value(app.storage.tab, f"draft:{session.key.save_id}")
                    # Enter sends on a fine pointer only; a touch keyboard's Enter stays a newline.
                    self.words_input.on(
                        "keydown.enter",
                        self.submit,
                        js_handler=(
                            '(e) => { if (e.shiftKey || !matchMedia("(pointer: fine)").matches) '
                            "return; e.preventDefault(); emit(); }"
                        ),
                    )
                    self.entry_controls: tuple[DisableableElement, ...] = (self.words_input,)
                    if speech is not None:
                        self.entry_controls += (self._build_mic(speech),)
                    # `color=None`: Quasar's `text-primary` would paint the glyph the fill's gold.
                    self.send_button = (
                        ui.button(icon="sym_r_arrow_upward", on_click=self.submit, color=None)
                        .props("round flat no-caps aria-label=Send")
                        .classes("game-send")
                        .on("mousedown", js_handler=KEEP_FOCUS)
                    )
                    self.entry_controls += (self.send_button,)
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
        for widget in (*self.entry_controls, *(chip for chip, _ in self.chips)):
            widget.set_enabled(enabled)

    def prefill(self, words: str) -> None:
        self.armed = None
        self._show_armed()
        self.set_input(words)
        self.words_input.run_method("focus")

    def arm(self, move: ActionOption | None) -> None:
        self.armed = move
        self._show_armed()
        self.words_input.run_method("focus")

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

    async def pick_among(self, members: tuple[ActionOption, ...]) -> None:
        if len(members) == 1:
            await self.pick(members[0])
            return
        self.group_dialog.clear()
        with self.group_dialog, ui.card().classes("game-row-dialog game-gap-md"):
            heading(members[0].group)
            with ui.element("div").classes(CHOICES_ROW):
                for member in members:
                    _ = choice_button(
                        member.name,
                        member.refusal or member.brief,
                        partial(self._pick_in_group, member),
                        enabled=self.acting and not member.refusal,
                        help=member.help,
                    )
        self.group_dialog.open()

    async def _pick_in_group(self, member: ActionOption) -> None:
        self.group_dialog.close()
        await self.pick(member)

    async def submit(self) -> None:
        words = entered_text(self.words_input)
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
        self.words_input.value = words
        # Quasar never saw the value change, so only an explicit push empties the composer.
        self.words_input.run_method("updateValue")

    def _build_mic(self, speech: Speech) -> ui.button:
        mic = (
            ui.button(icon=MIC_ICONS[False], on_click=speech.toggle_recording, color=None)
            .props('flat round aria-label="Speak your action"')
            .classes("game-mic")
            .on("mousedown", js_handler=KEEP_FOCUS)
        )
        mic.set_visibility(False)

        def show_recording(event: GenericEventArguments) -> None:
            recording = bool(event.args)
            mic.set_icon(MIC_ICONS[recording])
            mic.classes(add="game-mic-on" if recording else "", remove="game-mic-on")

        speech.on("microphone", lambda event: mic.set_visibility(bool(event.args)))
        speech.on("recording", show_recording)
        speech.on("recorded", self._hear)
        speech.on("denied", lambda: warn("The browser blocked the microphone."))
        return mic

    async def _hear(self, event: GenericEventArguments) -> None:
        async def transcribe() -> None:
            recording = parse(Recording, event.args)
            words = await self.session.transcribe(recording.audio, recording.mime)
            draft = entered_text(self.words_input)
            self.set_input(f"{draft} {words}" if draft else words)
            self.words_input.run_method("focus")

        await attempt(transcribe, failed=HEARING_FAILED)

    def _clear_spent_draft(self, now: SessionSnapshot) -> None:
        draft = entered_text(self.words_input)
        if draft and now.log_entries and draft == now.log_entries[-1].words:
            self.set_input()

    def _draw_chips(self) -> None:
        cells = chip_cells(self.view)
        lines = [self._cell_line(members[0]) if len(members) == 1 else "" for _, members in cells]
        self.chip_row.clear()
        self.chips = []
        with self.chip_row:
            for (name, members), line in zip(cells, lines, strict=True):
                chip = choice_button(
                    name, line, lambda chosen=members: self.pick_among(chosen), enabled=False
                )
                if (help := _chip_help(members)) and help != line:
                    with chip:
                        ui.tooltip(help).classes("game-help-tip")
                self.chips.append((chip, members))
        self.moves_line.set_visibility(bool(self.chips))
        self.chip_row.classes(
            add="game-moves-briefed" if any(lines) else "", remove="game-moves-briefed"
        )
        options = offered(self.view)
        self.explain_button.set_visibility(any(option.refusal or option.help for option in options))

    def _cell_line(self, option: ActionOption) -> str:
        asking = self.view.decision is not None
        if self.explained:
            return option.refusal or option.help or (option.brief if asking else "")
        return (option.refusal or option.brief) if asking else ""

    def _show_chips(self) -> None:
        for chip, members in self.chips:
            chip.set_enabled(self.acting and any(not member.refusal for member in members))
        self._show_armed()

    def _show(self, now: SessionSnapshot, *, entering: bool) -> None:
        view, lock = self.view, self.lock
        self.acting = not now.held_elsewhere and lock in (None, "answer", "choose")
        worded = lock != "choose" and (
            view.allows_text or any(move.needs_words for move in view.moves)
        )
        self.input_row.set_visibility(worded)
        for widget in self.entry_controls:
            widget.set_enabled(self.acting and worded)
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
        self.row.classes(
            add=(PROMPT_CLASSES[state] if state else "") + (" game-enter" if entering else ""),
            remove=" ".join((*PROMPT_CLASSES.values(), "game-enter")),
        )
        self._show_chips()

    def _show_armed(self) -> None:
        forced = forced_move(self.view)
        move = self.armed or forced
        for chip, members in self.chips:
            chip.classes(add="game-choice-on" if move in members else "", remove="game-choice-on")
        if self.lock not in (None, "choose"):
            placeholder = PLACEHOLDERS[self.lock]
        elif self.armed is not None and forced is None:
            placeholder = self.armed.help or f"Type your words, then press {self.armed.name}."
        else:
            placeholder = forced.help if forced and forced.help else self.view.hint
        self.words_input.props["placeholder"] = placeholder
        self.send_button.set_text("" if move is None else move.name)
        if move is None:
            self.send_button.props("round").classes(remove="game-send-named")
        else:
            self.send_button.props(remove="round").classes("game-send-named")


def offered(view: PlayerView) -> tuple[ActionOption, ...]:
    return view.decision.options if view.decision is not None else view.moves


def chip_cells(view: PlayerView) -> list[ChipCell]:
    """A decision's options each get a chip; moves that share a group share one chip."""
    if view.decision is not None:
        return [(option.name, (option,)) for option in view.decision.options]
    cells: dict[str, tuple[str, list[ActionOption]]] = {}
    for move in view.moves:
        key = f"group:{move.group}" if move.group else move.id
        cells.setdefault(key, (move.group or move.name, []))[1].append(move)
    return [(name, tuple(members)) for name, members in cells.values()]


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


def _chip_help(members: tuple[ActionOption, ...]) -> str:
    if len(members) == 1:
        return members[0].refusal or members[0].help
    return " / ".join(member.name for member in members)
