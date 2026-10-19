from abc import ABC, abstractmethod
from collections.abc import Sequence
from functools import partial

from nicegui import background_tasks, ui

from rulehall.app.game_session import SessionSnapshot
from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Slug
from rulehall.core.views import require_view
from rulehall.ui import transcript
from rulehall.ui.screen_host import ScreenHost, screen_banner
from rulehall.ui.widgets import attempt, failure_notice

BATTLE_FAILED = failure_notice("The battle did not start.")
MOVE_FAILED = failure_notice("The move was not played.")
RESOLVING = "game-battle-resolving"
PICKED = "game-choice-picked"


class BattleScreenBase[ViewT: Frozen](ABC):
    opener_label = "Battle"
    opener_icon = "sym_r_swords"
    screen_id: Slug
    view_type: type[ViewT]

    def __init__(self, host: ScreenHost) -> None:
        self.host = host
        self.session = host.session
        self.shown = False
        self.opening = False
        self.choice_buttons: dict[str, ui.button] = {}
        self.banner: ui.column
        self.column: ui.column
        self.hint: ui.label
        self.cards: ui.element

    @abstractmethod
    def build(self, now: SessionSnapshot) -> None: ...

    def build_banner(self) -> None:
        self.banner, _ = screen_banner(self, "battle", "A battle waits for you.")

    def show(self) -> None:
        self.shown = True
        self.host.on_toggle()

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        live = now.require_screen_slot(self.screen_id).live and now.working_role is None
        closed = now.battle is None and drawn.battle is not None and not self.opening
        self.shown = self.shown and (live or self.opening) and not closed
        if self.shown and not self.column.visible and now.battle is None:
            self._open()
        self.column.set_visibility(self.shown)
        self.banner.set_visibility(live and not self.shown)
        self.hint.set_visibility(now.battle is None)
        self._draw(now, drawn)

    def battle_view(self, now: SessionSnapshot) -> ViewT | None:
        return None if now.battle is None else require_view(now.battle.view, self.view_type)

    @abstractmethod
    def _redraw(self, now: SessionSnapshot) -> None: ...

    @abstractmethod
    def _update(self, now: SessionSnapshot, drawn: SessionSnapshot) -> bool: ...

    def _draw(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        fresh = transcript.appended_since(facts_of(now), facts_of(drawn))
        if fresh is None or not same_run(now, drawn) or not self._update(now, drawn):
            self.host.sounds.roll_dice(_carded(self._closing_facts(drawn)))
            self._redraw(now)
            self.cards.clear()
            self._draw_cards(facts_of(now), live=False)
            return
        self._draw_cards(fresh, live=True)
        self.host.sounds.roll_dice(_carded(fresh))

    def _draw_cards(self, facts: Sequence[Fact], *, live: bool) -> None:
        if not (carded := _carded(facts)):
            return
        with self._card_box(live=live):
            for fact in carded:
                transcript.draw_fact_card(fact, live=live)

    def _card_box(self, *, live: bool) -> ui.element:  # noqa: ARG002
        return self.cards

    def _closing_facts(self, drawn: SessionSnapshot) -> Sequence[Fact]:
        # A move that ends the battle closes the run before this sync; its facts show here.
        closing = drawn.battle
        return (
            () if closing is None else closing.run.facts(self.session.state)[len(closing.facts) :]
        )

    def _open(self) -> None:
        self.opening = True
        background_tasks.create(self._open_battle(), name="open battle")  # pyright: ignore[reportUnknownMemberType]

    async def _open_battle(self) -> None:
        try:
            opponent = self.session.live_settings.current.battle.opponent
            with self.column:
                _ = await attempt(
                    partial(self.session.open_battle, ask_opponent=opponent == "model"),
                    failed=BATTLE_FAILED,
                )
        finally:
            # A bug must not reopen the battle on every Battle click.
            self.shown = self.shown and self.session.battle_run is not None
            self.opening = False

    async def _choose(self, command: str) -> None:
        picked = self.choice_buttons.get(command)
        self.column.classes(RESOLVING)
        if picked is not None:
            picked.classes(PICKED)
        # The sync may have deleted the clicked button while the foes were deciding.
        with self.column:
            chosen = await attempt(lambda: self.session.battle_command(command), failed=MOVE_FAILED)
        if self.column.is_deleted:
            return
        self.column.classes(remove=RESOLVING)
        if picked is not None and not picked.is_deleted:
            picked.classes(remove=PICKED)
        if not chosen and self.shown and self.session.battle_run is None:
            self._open()


def same_run(now: SessionSnapshot, drawn: SessionSnapshot) -> bool:
    if now.battle is None or drawn.battle is None:
        return now.battle is drawn.battle
    return now.battle.run is drawn.battle.run


def facts_of(now: SessionSnapshot) -> tuple[Fact, ...]:
    return () if now.battle is None else now.battle.facts


def _carded(facts: Sequence[Fact]) -> tuple[Fact, ...]:
    return tuple(fact for fact in facts if fact.card)
