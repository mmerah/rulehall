from collections.abc import Sequence
from time import monotonic

from nicegui import ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.config import Role
from rulehall.core.facts import DiceEvent, Fact, told_cards
from rulehall.core.log import Cause, LogEntry, RefusedCall, SpokenLine, facts_and_refusals
from rulehall.core.validation import Slug
from rulehall.core.views import PlayerView
from rulehall.ui.panel_parts import IconOf, avatar
from rulehall.ui.widgets import DICE_CLIP, PASS_THROUGH, Sounds

ROLE_COPY: dict[Role, tuple[str, str]] = {
    "master": (
        "Game Master",
        "Decides what your action does: who reacts, what changes, "
        "and if the dice decide the result.",
    ),
    "narrator": ("Narrator", "Writes what you see and hear this turn."),
    "worldsmith": (
        "Worldsmith",
        "Writes the next scene or region, or what the game master asks for. The text shows "
        "where the story goes and who waits there. This step is slow. A few minutes is usual.",
    ),
    "opponent": ("Opponent", "Chooses the other side's move in the battle."),
}
CAUSE_LABELS: dict[Cause, str] = {
    "opening": "(the story begins)",
    "story": "(the story goes on)",
    "battle": "(the battle ends)",
}
FACT_ICONS = {False: "sym_r_bolt", True: "sym_r_casino"}
SPUN_LINES = 12


class Chat:
    def __init__(self, now: SessionSnapshot, icon_of: IconOf, sounds: Sounds) -> None:
        self.icon_of = icon_of
        self.sounds = sounds
        self.premise: ui.label | None = None
        self.pause_line: ui.label | None = None
        self.column = ui.element("div").style(PASS_THROUGH)
        self.redraw(now)
        self.show_pause(now.view)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        appended = appended_since(now.log_entries, drawn.log_entries)
        if appended is None:
            self.redraw(now)
        elif appended:
            self.append(appended, refusals=now.show_refusals, entering=True)
            newest = appended[-1]
            seen = sum(isinstance(entry, Fact) for entry in drawn.facts_and_refusals)
            if newest.cause != "battle" and rolled_since(newest.facts, seen):
                self.sounds.play(DICE_CLIP)
        self.show_pause(now.view)

    def show_pause(self, view: PlayerView) -> None:
        if self.pause_line is not None:
            self.pause_line.set_visibility(view.decision is None)

    def redraw(self, now: SessionSnapshot) -> None:
        self.column.clear()
        self.pause_line = None
        if not now.log_entries:
            with self.column:
                self.premise = ui.label(now.view.premise).classes("game-lead text-sm italic")
        self.append(now.log_entries, refusals=now.show_refusals, entering=False)

    def append(self, entries: Sequence[LogEntry], *, refusals: bool, entering: bool) -> None:
        if not entries:
            return
        if self.premise is not None:
            self.premise.delete()
            self.premise = None
        if self.pause_line is not None:
            self.pause_line.set_visibility(True)
        with self.column:
            for entry in entries:
                draw_log_entry(entry, self.icon_of, refusals=refusals, entering=entering)
                self.pause_line = (
                    ui.label(f"Paused: {entry.decision}").classes("game-paused")
                    if entry.decision
                    else None
                )


class LiveTurn:
    def __init__(self, now: SessionSnapshot, icon_of: IconOf, sounds: Sounds) -> None:
        self.icon_of = icon_of
        self.sounds = sounds
        self.step_started = monotonic()
        self.ticker: ui.label | None = None
        self.draw_player_words(now.words)
        self.cards = ui.element("div").style(PASS_THROUGH)
        with self.cards:
            draw_fact_cards(now.facts_and_refusals)
        self.draw_live_lines(now.live)
        self.draw_working_status(now.working_role)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        fresh = appended_since(now.facts_and_refusals, drawn.facts_and_refusals)
        if fresh is None or now.words != drawn.words:
            self.draw_player_words.refresh(now.words)
            self.cards.clear()
            fresh = now.facts_and_refusals
        if fresh:
            with self.cards:
                draw_fact_cards(fresh, live=True)
            if rolled_since([entry for entry in fresh if isinstance(entry, Fact)], 0):
                self.sounds.play(DICE_CLIP)
        if now.live != drawn.live:
            self.draw_live_lines.refresh(now.live)
        if now.working_role != drawn.working_role:
            self.draw_working_status.refresh(now.working_role)
        if self.ticker is not None:
            self.ticker.set_text(clock(monotonic() - self.step_started))

    @ui.refreshable_method
    def draw_player_words(self, words: str) -> None:
        if words:
            draw_player_message(words)

    @ui.refreshable_method
    def draw_live_lines(self, live: tuple[SpokenLine, ...]) -> None:
        draw_speaker_messages(live, self.icon_of)

    @ui.refreshable_method
    def draw_working_status(self, working_role: Role | None) -> None:
        self.step_started = monotonic()
        self.ticker = None if working_role is None else draw_working_status_row(working_role)


def appended_since[T](now: Sequence[T], drawn: Sequence[T]) -> Sequence[T] | None:
    kept = len(drawn)
    if len(now) < kept or (kept and now[kept - 1] != drawn[-1]):
        return None
    return now[kept:]


def draw_log_entry(entry: LogEntry, icon_of: IconOf, *, refusals: bool, entering: bool) -> None:
    if entry.cause is not None:
        ui.label(CAUSE_LABELS[entry.cause]).classes("game-cause" + _entering(on=entering))
    else:
        draw_player_message(entry.words)
    draw_fact_cards(facts_and_refusals(entry.facts, entry.refused, refusals=refusals))
    draw_speaker_messages(entry.lines, icon_of, entering=entering)


def draw_speaker_messages(
    lines: Sequence[SpokenLine], icon_of: IconOf, *, entering: bool = False
) -> None:
    for index, line in enumerate(lines):
        draw_speaker_message(
            icon_of,
            line.speaker_id,
            line.speaker,
            line.text,
            named=index == 0 or line.speaker_id != lines[index - 1].speaker_id,
            entering=entering,
        )


def draw_fact_cards(entries: Sequence[Fact | RefusedCall], *, live: bool = False) -> None:
    for entry in entries:
        if isinstance(entry, Fact):
            if entry.told and entry.card:
                draw_fact_card(entry, live=live)
        else:
            draw_refusal_card(entry, live=live)


def draw_fact_card(fact: Fact, *, live: bool = False) -> None:
    headline, *detail = fact.card.split("\n")
    with ui.column().classes("game-card game-fact w-full game-gap-sm" + _entering(on=live)):
        with ui.row().classes("items-center no-wrap game-gap-md"):
            ui.icon(FACT_ICONS[bool(fact.dice)]).classes("game-fact-icon")
            ui.label(headline).classes("game-fact-head")
        for line in detail:
            ui.label(line).classes("text-xs opacity-80")
        if fact.dice:
            with ui.row().classes("items-start game-gap-2xl"):
                for group in fact.dice:
                    draw_dice_group(group, live=live)


def draw_refusal_card(refused: RefusedCall, *, live: bool) -> None:
    with ui.column().classes(
        "game-card game-fact game-refused w-full game-gap-sm" + _entering(on=live)
    ):
        with ui.row().classes("items-center no-wrap game-gap-md"):
            ui.icon("sym_r_block").classes("game-fact-icon")
            ui.label(f"The rules refused {refused.tool}").classes("game-fact-head")
        ui.label(refused.reason).classes("text-xs opacity-80")


def draw_dice_group(die: DiceEvent, *, live: bool) -> None:
    with ui.column().classes("game-gap-2xs"):
        ui.label(die.label).classes("text-xs opacity-60")
        with ui.row().classes("no-wrap game-gap-sm"):
            for index, (face, value) in enumerate(zip(die.faces, die.rolled, strict=True)):
                with ui.column().classes(
                    "game-die game-gap-0"
                    + (" game-die-kept" if index in die.highlight else "")
                    + (" game-die-live" if live else "")
                ):
                    ui.label(f"d{face}").classes("game-die-face")
                    with ui.element("div").classes("game-die-window"):
                        label = ui.label(_reel(value, face) if live else str(value)).classes(
                            "game-die-value"
                        )
                        if live:
                            label.props(f'role=img aria-label="{value}"')


def draw_player_message(words: str) -> None:
    ui.chat_message(words, sent=True).classes("w-full game-message")


def draw_speaker_message(
    icon_of: IconOf,
    speaker_id: Slug | None,
    name: str,
    text: str,
    *,
    named: bool = True,
    entering: bool = False,
) -> None:
    narration = speaker_id is None
    chat_name = "DM" if narration else name
    message = ui.chat_message(text, name=chat_name if named else None).classes(
        "w-full game-message" + _entering(on=entering)
    )
    if not named:
        message.classes("game-message-more")
    elif narration:
        with message.add_slot("avatar"):
            avatar(None, None)
    else:
        with message.add_slot("avatar"):
            avatar(icon_of(speaker_id), name)


def draw_working_status_row(role: Role) -> ui.label:
    name, description = ROLE_COPY[role]
    with ui.row().classes("w-full items-start no-wrap q-py-xs game-gap-lg"):
        avatar(None, None)
        with ui.column().classes("game-working game-gap-xs"):
            with ui.row().classes("items-center no-wrap game-gap-md"):
                _draw_dots()
                ui.label(name).classes("text-sm font-bold")
                ticker = ui.label(clock(0)).classes("text-xs font-mono opacity-70")
            ui.label(description).classes("text-xs opacity-70")
    return ticker


def clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


def rolled_since(facts: Sequence[Fact], seen: int) -> bool:
    return any(fact.dice for fact in told_cards(facts[seen:]))


def _draw_dots() -> None:
    with ui.element("div").classes("game-dots"):
        for _ in range(3):
            ui.element("span")


def _entering(*, on: bool) -> str:
    return " game-enter" if on else ""


def _reel(value: int, face: int) -> str:
    return "\n".join(str((value - 1 + step) % face + 1) for step in range(SPUN_LINES))
