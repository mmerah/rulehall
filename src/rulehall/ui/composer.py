from collections.abc import Awaitable, Callable
from typing import Literal

from nicegui import app, ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.config import Role
from rulehall.core.decisions import PlayerInput
from rulehall.ui.transcript import ROLE_COPY
from rulehall.ui.widgets import ARROW_ICON, Banner, entered_text, warn

type ComposerLock = Literal["over", "battle", "answer", "choose"] | Role

GAME_OVER = "The game is over. Restart it from the menu."
BATTLE_ON = "A battle is on. Finish it on the battle screen."
ANSWER_FIRST = "Answer the question above first."
PLACEHOLDERS: dict[ComposerLock | None, str] = {
    "over": GAME_OVER,
    "battle": BATTLE_ON,
    "answer": "The game is waiting on your answer.",
    "choose": "Choose an option above.",
    None: "What do you do?",
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


class Composer:
    def __init__(
        self,
        session: GameSession,
        now: SessionSnapshot,
        run_move: Callable[[Callable[[], Awaitable[None]]], Awaitable[bool]],
        build_battle_banner: Callable[[], None],
    ) -> None:
        self.session = session
        self.run_move = run_move
        self.view = now.view
        self.option_banner = Banner("sym_r_explore", "next", kind="game-offer")
        with self.option_banner.actions:
            self.option_button = (
                ui.button(on_click=self.use_composer_option)
                .props(f"outline icon-right={ARROW_ICON}")
                .classes("game-composer-option")
            )
        build_battle_banner()
        self.ending = ui.label().classes("text-xs game-over")
        with ui.row().classes("w-full no-wrap items-end game-composer game-gap-lg"):
            self.composer_input = (
                ui.input()
                .classes("flex-grow")
                # theme.py's default w-full would fight flex-grow and squeeze the send button.
                .classes(remove="w-full")
                .props('autogrow type=textarea borderless input-style="max-height: 9rem"')
                .props(remove="outlined")
            )
            self.composer_input.bind_value(app.storage.tab, f"draft:{session.key.save_id}")
            # Enter sends on a fine pointer only; a touch keyboard's Enter must stay a newline.
            self.composer_input.on(
                "keydown.enter",
                self.submit,
                js_handler=(
                    '(e) => { if (e.shiftKey || !matchMedia("(pointer: fine)").matches) return; '
                    "e.preventDefault(); emit(); }"
                ),
            )
            # `color=None`: Quasar's `text-primary` would paint the glyph the button's own gold.
            self.send_button = (
                ui.button(icon="sym_r_arrow_upward", on_click=self.submit, color=None)
                .props("round flat aria-label=Send")
                .classes("game-send")
            )
        self._clear_spent_draft(now)
        self._show_controls(now)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.view = now.view
        if len(now.log_entries) > len(drawn.log_entries):
            self._clear_spent_draft(now)
        self._show_controls(now)

    def set_enabled(self, *, enabled: bool) -> None:
        for widget in (self.composer_input, self.send_button, self.option_button):
            widget.set_enabled(enabled)

    def prefill(self, words: str) -> None:
        self.set_input(words)
        self.composer_input.run_method("focus")

    async def submit(self) -> None:
        if self.view.composer_only:
            await self.use_composer_option()
            return
        words = entered_text(self.composer_input)
        if not words:
            return
        if await self.run_move(lambda: self.session.play(PlayerInput(text=words))):
            self.set_input()

    async def use_composer_option(self) -> None:
        option = self.view.composer_option
        if option is None:
            warn("The page has changed.")
            return
        words = entered_text(self.composer_input)
        if not words:
            warn(f"Type your words, then press {option.name}.")
            return
        if await self.run_move(lambda: self.session.use_composer_option(option, words)):
            self.set_input()

    def set_input(self, words: str = "") -> None:
        self.composer_input.value = words
        # Quasar never saw the value change, so only an explicit push empties the composer.
        self.composer_input.run_method("updateValue")

    def _clear_spent_draft(self, now: SessionSnapshot) -> None:
        draft = entered_text(self.composer_input)
        if draft and now.log_entries and draft == now.log_entries[-1].words:
            self.set_input()

    def _show_controls(self, now: SessionSnapshot) -> None:
        view = now.view
        lock = composer_lock(now)
        self.set_enabled(enabled=not now.held_elsewhere and lock in (None, "answer"))
        self.composer_input.props(f'placeholder="{PLACEHOLDERS[lock]}"')
        option, ending = view.composer_option, view.ending
        self.option_banner.set_visibility(option is not None)
        self.option_button.set_text("" if option is None else option.name)
        self.option_banner.text.set_text("" if option is None else option.brief)
        self.send_button.set_visibility(not view.composer_only)
        self.ending.set_text(ending or "")
        self.ending.set_visibility(ending is not None)


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
