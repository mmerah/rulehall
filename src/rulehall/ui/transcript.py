from collections.abc import Callable, Sequence
from functools import partial
from html import escape
from time import monotonic

from nicegui import ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.config import Role
from rulehall.core.facts import DiceEvent, Fact, told_cards
from rulehall.core.log import Cause, LogEntry, SpokenLine
from rulehall.core.views import PlayerView
from rulehall.ui.panel_parts import IconOf, avatar
from rulehall.ui.widgets import PASS_THROUGH, Sounds

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
READ_ALOUD = "Read aloud"

type ReadAloud = Callable[[SpokenLine, int], None]


class TurnBlock:
    def __init__(self, icon_of: IconOf) -> None:
        self.icon_of = icon_of
        self.head: tuple[str, Cause | None] = ("", None)
        self.cards: tuple[Fact, ...] = ()
        self.lines: tuple[SpokenLine, ...] = ()
        self.bubbles: list[tuple[ui.chat_message, ui.html]] = []
        self.heard: set[tuple[SpokenLine, int]] = set()
        with ui.element("div").classes("game-turn"):
            self.head_slot = ui.element("div").style(PASS_THROUGH)
            self.card_slot = ui.element("div").style(PASS_THROUGH)
            self.line_slot = ui.element("div").style(PASS_THROUGH)

    def show_entry(self, entry: LogEntry, *, entering: bool) -> Sequence[Fact]:
        self.show_head(entry.words, entry.cause, entering=entering)
        fresh = self.show_cards(entry.facts, entering=entering)
        self.show_lines(entry.lines, entering=entering)
        return fresh

    def show_head(self, words: str, cause: Cause | None, *, entering: bool) -> None:
        if (words, cause) == self.head:
            return
        self.head = (words, cause)
        self.head_slot.clear()
        with self.head_slot:
            if cause is not None:
                ui.label(CAUSE_LABELS[cause]).classes("game-cause" + _entering(on=entering))
            elif words:
                draw_player_message(words)

    def show_cards(self, cards: Sequence[Fact], *, entering: bool) -> Sequence[Fact]:
        fresh = appended_since(cards, self.cards)
        if fresh is None:
            self.card_slot.clear()
            fresh = cards
        self.cards = tuple(cards)
        with self.card_slot:
            draw_fact_cards(fresh, live=entering)
        return fresh

    def show_lines(self, lines: Sequence[SpokenLine], *, entering: bool) -> None:
        kept = 0
        for drawn, line in zip(self.lines, lines, strict=False):
            if (drawn.speaker_id, drawn.speaker) != (line.speaker_id, line.speaker):
                break
            if drawn.text != line.text:
                self.bubbles[kept][1].set_content(_bubble_html(line.text))
            kept += 1
        for message, _ in self.bubbles[kept:]:
            message.delete()
        del self.bubbles[kept:]
        with self.line_slot:
            self.bubbles.extend(
                draw_speaker_message(
                    self.icon_of,
                    lines[index],
                    named=index == 0 or lines[index].speaker_id != lines[index - 1].speaker_id,
                    entering=entering,
                )
                for index in range(kept, len(lines))
            )
        self.lines = tuple(lines)

    def add_read_aloud(self, read_aloud: ReadAloud) -> None:
        for line, (message, body) in zip(self.lines, self.bubbles, strict=True):
            draw_read_aloud_button(message, body, partial(read_aloud, line, message.id))

    def take_unheard(self, *, landed: bool) -> tuple[list[tuple[SpokenLine, int]], bool]:
        pairs = [
            (line, message.id) for line, (message, _) in zip(self.lines, self.bubbles, strict=True)
        ]
        withdrawn = self.heard.difference(pairs)
        self.heard -= withdrawn
        unheard = [pair for pair in (pairs if landed else pairs[:-1]) if pair not in self.heard]
        self.heard.update(unheard)
        return unheard, bool(withdrawn)


class Transcript:
    def __init__(
        self,
        now: SessionSnapshot,
        icon_of: IconOf,
        sounds: Sounds,
        read_aloud: ReadAloud | None,
    ) -> None:
        self.icon_of = icon_of
        self.sounds = sounds
        self.read_aloud = read_aloud
        self.premise: ui.label | None = None
        self.pause_line: ui.label | None = None
        self.column = ui.element("div").style(PASS_THROUGH)
        self.live_block: TurnBlock
        self.landed_block: TurnBlock | None = None
        self.finished_bubbles: list[tuple[SpokenLine, int]] = []
        self.withdrawn = False
        self.redrawn = False
        self.redraw(now)
        self.show_pause(now.view)
        self.step_started = monotonic()
        self.ticker: ui.label | None = None
        self.draw_working_status(now.working_role)

    @property
    def reply_top_id(self) -> int | None:
        block = self.live_block if self.live_block.bubbles else self.landed_block
        return block.bubbles[0][0].id if block is not None and block.bubbles else None

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.finished_bubbles = []
        self.withdrawn = False
        appended = appended_since(now.log_entries, drawn.log_entries)
        self.redrawn = appended is None
        if appended is None:
            self.redraw(now)
        else:
            self.land(appended, entering=True)
            self.show_live(now, entering=True)
        self.show_pause(now.view)
        if now.working_role != drawn.working_role:
            self.draw_working_status.refresh(now.working_role)
        if self.ticker is not None:
            self.ticker.set_text(clock(monotonic() - self.step_started))

    def redraw(self, now: SessionSnapshot) -> None:
        self.column.clear()
        self.premise = self.pause_line = None
        self.landed_block = None
        with self.column:
            if not now.log_entries:
                self.premise = ui.label(now.view.premise).classes("game-lead text-sm italic")
            self.live_block = TurnBlock(self.icon_of)
        self.land(now.log_entries, entering=False)
        self.show_live(now, entering=False)

    def land(self, entries: Sequence[LogEntry], *, entering: bool) -> None:
        if not entries:
            return
        if self.premise is not None:
            self.premise.delete()
            self.premise = None
        if self.pause_line is not None:
            self.pause_line.set_visibility(True)
        for entry in entries:
            block = self.landed_block = self.live_block
            fresh = block.show_entry(entry, entering=entering)
            if self.read_aloud is not None:
                block.add_read_aloud(self.read_aloud)
            if entering:
                if entry.cause != "battle":
                    self.sounds.roll_dice(told_cards(fresh))
                self.take_finished(block, landed=True)
            with self.column:
                self.pause_line = (
                    ui.label(f"Paused: {entry.decision}").classes("game-paused")
                    if entry.decision
                    else None
                )
                self.live_block = TurnBlock(self.icon_of)

    def show_live(self, now: SessionSnapshot, *, entering: bool) -> None:
        block = self.live_block
        block.show_head(now.words, None, entering=False)
        fresh = block.show_cards(now.turn_facts, entering=entering)
        block.show_lines(now.live, entering=entering)
        if entering:
            self.sounds.roll_dice(told_cards(fresh))
            self.take_finished(block, landed=False)

    def take_finished(self, block: TurnBlock, *, landed: bool) -> None:
        unheard, withdrawn = block.take_unheard(landed=landed)
        self.finished_bubbles.extend(unheard)
        self.withdrawn = self.withdrawn or withdrawn

    def show_pause(self, view: PlayerView) -> None:
        if self.pause_line is not None:
            self.pause_line.set_visibility(view.decision is None)

    @ui.refreshable_method
    def draw_working_status(self, working_role: Role | None) -> None:
        self.step_started = monotonic()
        self.ticker = None if working_role is None else draw_working_status_row(working_role)


def appended_since[T](now: Sequence[T], drawn: Sequence[T]) -> Sequence[T] | None:
    kept = len(drawn)
    if len(now) < kept or (kept and now[kept - 1] != drawn[-1]):
        return None
    return now[kept:]


def draw_fact_cards(facts: Sequence[Fact], *, live: bool = False) -> None:
    for fact in told_cards(facts):
        draw_fact_card(fact, live=live)


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
                            label.props.update({"role": "img", "aria-label": str(value)})


def draw_player_message(words: str) -> None:
    ui.chat_message(words, sent=True).classes("w-full game-message")


def draw_speaker_message(
    icon_of: IconOf, line: SpokenLine, *, named: bool, entering: bool
) -> tuple[ui.chat_message, ui.html]:
    speaker_id = line.speaker_id
    message = ui.chat_message(
        name=("DM" if speaker_id is None else line.speaker) if named else None
    ).classes("w-full game-message" + _entering(on=entering))
    with message:
        body = ui.html(_bubble_html(line.text), sanitize=False)
    if not named:
        message.classes("game-message-more")
    elif speaker_id is None:
        with message.add_slot("avatar"):
            avatar(None, None)
    else:
        with message.add_slot("avatar"):
            avatar(icon_of(speaker_id), line.speaker)
    return message, body


def draw_read_aloud_button(
    message: ui.chat_message, body: ui.html, read_aloud: Callable[[], None]
) -> None:
    # One child: Quasar wraps each child of a chat message in a bubble of its own.
    with message, ui.element("div").style(PASS_THROUGH) as wrapper:
        body.move(wrapper)
        ui.button(icon="sym_r_volume_up", on_click=read_aloud).props(
            f'flat round dense aria-label="{READ_ALOUD}"'
        ).classes("game-read-aloud")


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


def _draw_dots() -> None:
    with ui.element("div").classes("game-dots"):
        for _ in range(3):
            ui.element("span")


def _bubble_html(text: str) -> str:
    return escape(text).replace("\n", "<br />")


def _entering(*, on: bool) -> str:
    return " game-enter" if on else ""


def _reel(value: int, face: int) -> str:
    return "\n".join(str((value - 1 + step) % face + 1) for step in range(SPUN_LINES))
