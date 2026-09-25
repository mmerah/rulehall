from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Self

from nicegui import ui

from rulehall.app.session import GameService, Step
from rulehall.app.turn import BATTLE_ON, Turn
from rulehall.core.facts import DiceEvent, Fact, cards
from rulehall.core.play import Cause, Exchange, Refused, SpokenLine
from rulehall.core.validation import Slug
from rulehall.core.views import PlayerView
from rulehall.ui.widgets import PASS_THROUGH, avatar

type Blocker = Literal["over", "battle", "answer", "choose"] | Step

STEP_COPY: dict[Step, tuple[str, str]] = {
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
}
CAUSE_LABELS: dict[Cause, str] = {
    "opening": "(the story begins)",
    "story": "(the story goes on)",
    "battle": "(the battle ends)",
}
FACT_ICONS = {False: "sym_r_bolt", True: "sym_r_casino"}
SPUN_LINES = 12
GAME_OVER = "The game is over. Restart it from the menu."
ANSWER_FIRST = "Answer the question above first."
PLACEHOLDERS: dict[Blocker | None, str] = {
    "over": GAME_OVER,
    "battle": BATTLE_ON,
    "answer": "The game is waiting on your answer.",
    "choose": "Choose an option above.",
    None: "What do you do?",
    **{role: f"{name} is working..." for role, (name, _) in STEP_COPY.items()},
}
CLOSED_REASONS: dict[Blocker | None, str] = {
    "over": GAME_OVER,
    "battle": BATTLE_ON,
    "answer": ANSWER_FIRST,
    "choose": ANSWER_FIRST,
    None: "",
    **{role: f"{name} is working. Wait for it." for role, (name, _) in STEP_COPY.items()},
}


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class TurnProgress:
    turn: Turn | None
    fact_count: int
    refused_count: int
    intent: str
    live: tuple[SpokenLine, ...]
    working_role: Step | None

    @classmethod
    def of(cls, session: GameService) -> Self:
        turn = session.turn
        return cls(
            turn=turn,
            fact_count=0 if turn is None else len(turn.facts),
            refused_count=0 if turn is None else len(turn.refused),
            intent=session.intent,
            live=session.live,
            working_role=session.working_role,
        )

    @property
    def words(self) -> str:
        return self.intent if self.turn is None else self.turn.words


class Chat:
    def __init__(self, session: GameService) -> None:
        self.session = session
        self.column: ui.element
        self.premise: ui.label | None = None
        self.pause_line: ui.label | None = None

    def build(self, view: PlayerView, history: tuple[Exchange, ...]) -> None:
        self.column = ui.element("div").style(PASS_THROUGH)
        self.redraw(view, history)
        self.show_pause(view)

    def sync(
        self,
        view: PlayerView,
        history: tuple[Exchange, ...],
        *,
        drawn_history: tuple[Exchange, ...],
    ) -> None:
        appended = appended_since(history, drawn_history)
        if appended is None:
            self.redraw(view, history)
        elif appended:
            self.append(appended, entering=True)
        self.show_pause(view)

    def show_pause(self, view: PlayerView) -> None:
        # The live decision widget sits directly below the last exchange, so it needs no pause line.
        if self.pause_line is not None:
            self.pause_line.set_visibility(view.decision is None)

    def redraw(self, view: PlayerView, history: tuple[Exchange, ...]) -> None:
        self.column.clear()
        self.pause_line = None
        if not history:
            with self.column:
                self.premise = ui.label(view.premise).classes("game-lead text-sm italic")
        self.append(history, entering=False)

    def append(self, exchanges: Sequence[Exchange], *, entering: bool) -> None:
        if not exchanges:
            return
        if self.premise is not None:
            self.premise.delete()
            self.premise = None
        if self.pause_line is not None:
            self.pause_line.set_visibility(True)
        with self.column:
            for exchange in exchanges:
                exchange_entry(self.session, exchange, entering=entering)
                self.pause_line = (
                    ui.label(f"Paused: {exchange.decision}").classes("game-paused")
                    if exchange.decision
                    else None
                )


class LiveTurn:
    def __init__(self, session: GameService) -> None:
        self.session = session
        self.cards: ui.element
        self.step_started = monotonic()
        self.ticker: ui.label | None = None

    def build(self, progress: TurnProgress) -> None:
        self.words(progress)
        self.cards = ui.element("div").style(PASS_THROUGH)
        self.add_cards(progress, 0, live=False)
        self.heard(progress.live)
        self.step(progress.working_role)

    def sync(self, now: TurnProgress, drawn: TurnProgress) -> None:
        if now.turn is not drawn.turn or now.intent != drawn.intent:
            self.words.refresh(now)
            self.cards.clear()
            self.add_cards(now, 0, live=True)
        elif (now.fact_count, now.refused_count) != (drawn.fact_count, drawn.refused_count):
            self.add_cards(now, drawn.fact_count + drawn.refused_count, live=True)
        if now.live != drawn.live:
            self.heard.refresh(now.live)
        if now.working_role != drawn.working_role:
            self.step.refresh(now.working_role)
        if self.ticker is not None:
            self.ticker.set_text(clock(monotonic() - self.step_started))

    @ui.refreshable_method
    def words(self, progress: TurnProgress) -> None:
        if progress.turn is not None or progress.words:
            said(progress.words)

    def add_cards(self, progress: TurnProgress, since: int, *, live: bool) -> None:
        turn = progress.turn
        if turn is None:
            return
        with self.cards:
            fact_cards(
                self.session,
                turn.facts[: progress.fact_count],
                turn.refused[: progress.refused_count],
                since=since,
                live=live,
            )

    @ui.refreshable_method
    def heard(self, live: tuple[SpokenLine, ...]) -> None:
        spoken(self.session, live)

    @ui.refreshable_method
    def step(self, working_role: Step | None) -> None:
        self.step_started = monotonic()
        self.ticker = None if working_role is None else inline_status(working_role)


def blocker(view: PlayerView, working_role: Step | None, *, in_battle: bool) -> Blocker | None:
    if view.ending is not None:
        return "over"
    if working_role is not None:
        return working_role
    if in_battle:
        return "battle"
    if view.decision is not None:
        return "answer" if view.decision.allows_text else "choose"
    return None


def appended_since(
    history: tuple[Exchange, ...], drawn: tuple[Exchange, ...]
) -> tuple[Exchange, ...] | None:
    kept = len(drawn)
    if history is drawn:
        return ()
    if len(history) < kept or (kept and history[kept - 1] != drawn[-1]):
        return None
    return history[kept:]


def exchange_entry(session: GameService, exchange: Exchange, *, entering: bool) -> None:
    if exchange.cause is not None:
        ui.label(CAUSE_LABELS[exchange.cause]).classes("game-cause" + _entering(on=entering))
    else:
        said(exchange.words)
    fact_cards(session, exchange.facts, exchange.refused)
    spoken(session, exchange.lines, entering=entering)


def spoken(session: GameService, lines: Sequence[SpokenLine], *, entering: bool = False) -> None:
    for index, line in enumerate(lines):
        bubble(
            session,
            line.speaker_id,
            line.speaker,
            line.text,
            named=index == 0 or line.speaker_id != lines[index - 1].speaker_id,
            entering=entering,
        )


def fact_cards(
    session: GameService,
    facts: Sequence[Fact],
    refused: Sequence[Refused],
    *,
    since: int = 0,
    live: bool = False,
) -> None:
    """`since` counts facts and refusals together, so a live turn draws only what is new."""
    for entry in in_order(facts, refused)[since:]:
        if isinstance(entry, Fact):
            if entry.told and entry.card:
                card(entry, live=live)
        elif session.transcript_config.refusals:
            refusal_card(entry, live=live)


def card(fact: Fact, *, live: bool = False) -> None:
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
                    dice_group(group, live=live)


def refusal_card(refused: Refused, *, live: bool) -> None:
    with ui.column().classes(
        "game-card game-fact game-refused w-full game-gap-sm" + _entering(on=live)
    ):
        with ui.row().classes("items-center no-wrap game-gap-md"):
            ui.icon("sym_r_block").classes("game-fact-icon")
            ui.label(f"The rules refused {refused.tool}").classes("game-fact-head")
        ui.label(refused.reason).classes("text-xs opacity-80")


def dice_group(die: DiceEvent, *, live: bool) -> None:
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


def said(words: str) -> None:
    ui.chat_message(words, sent=True).classes("w-full game-message")


def bubble(
    session: GameService,
    speaker_id: Slug | None,
    name: str,
    text: str,
    *,
    named: bool = True,
    entering: bool = False,
) -> None:
    """`named`: a run of lines from one speaker shows its name and avatar once, at its head."""
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
            avatar(session.icon(speaker_id), name)


def inline_status(step: Step) -> ui.label:
    name, description = STEP_COPY[step]
    with ui.row().classes("w-full items-start no-wrap q-py-xs game-gap-lg"):
        avatar(None, None)
        with ui.column().classes("game-working game-gap-xs"):
            with ui.row().classes("items-center no-wrap game-gap-md"):
                _dots()
                ui.label(name).classes("text-sm font-bold")
                ticker = ui.label(clock(0)).classes("text-xs font-mono opacity-70")
            ui.label(description).classes("text-xs opacity-70")
    return ticker


def clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


def near_end(position: float, size: float, container: float, slack: float = 48) -> bool:
    return size - position - container <= slack


def draft_spent(draft: str, newest_prompt: str) -> bool:
    return bool(draft) and draft == newest_prompt


def in_order(facts: Sequence[Fact], refused: Sequence[Refused]) -> list[Fact | Refused]:
    """A refusal goes after the facts that came before it and before the facts that came after."""
    placed: list[tuple[int, int, Fact | Refused]] = [
        (index, 1, fact) for index, fact in enumerate(facts)
    ]
    placed.extend((each.after_facts, 0, each) for each in refused)
    return [entry for *_, entry in sorted(placed, key=lambda slot: slot[:2])]


def rolled_since(facts: Sequence[Fact], seen: int) -> bool:
    return any(fact.dice for fact in cards(facts[seen:]))


def _dots() -> None:
    with ui.element("div").classes("game-dots"):
        for _ in range(3):
            ui.element("span")


def _entering(*, on: bool) -> str:
    return " game-enter" if on else ""


def _reel(value: int, face: int) -> str:
    return "\n".join(str((value - 1 + step) % face + 1) for step in range(SPUN_LINES))
