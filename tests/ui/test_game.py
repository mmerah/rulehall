from asyncio import sleep
from collections.abc import Callable
from pathlib import Path
from random import Random

import pytest
from nicegui import Client, ui
from support.game import open_game
from support.table import (
    Table,
    play_turn,
)

from rulehall.app.session import GameService
from rulehall.app.turn import Turn
from rulehall.config import TranscriptConfig
from rulehall.core.facts import Fact
from rulehall.core.model import AnyGame
from rulehall.core.play import (
    PendingDecision,
    PendingOption,
    Refused,
    SpokenLine,
)
from rulehall.core.views import SCENE_TAB, PlayerView, Subject
from rulehall.ui.drawer import DrawerTab
from rulehall.ui.game import DecisionPanel, GamePage, Snapshot, game_page
from rulehall.ui.transcript import Chat, LiveTurn, TurnProgress, blocker

WREN = Subject(id="player", name="Wren", brief="A quiet scout")


def _view(decision: PendingDecision | None = None, ending: str | None = None) -> PlayerView:
    return PlayerView(
        premise="",
        player=WREN,
        scene_title="The Cloister Walk",
        situation="Rain drums the arcade.",
        panels=(),
        decision=decision,
        way_on=None,
        ending=ending,
    )


def _told(card: str) -> Fact:
    return Fact(trace=card, told=True, card=card)


def _suspend[G: AnyGame](table: Table[G], decision: PendingDecision) -> None:
    """A turn that ends on a pause, the way a suspending rule leaves one."""
    service = table.service
    draft = service.state.draft()
    draft.pending = decision
    lines = (SpokenLine(text="Two doors, and no light under either."),)
    service.save(service.engine.record(draft, lines, (), words="I look."))


def _pick(*, allows_text: bool) -> PendingDecision:
    return PendingDecision(
        kind="pick",
        prompt="Which door?",
        options=(PendingOption(id="left", name="Left", action_name="pick"),),
        allows_text=allows_text,
    )


def _texts(held: ui.element, *, eased: bool = False) -> list[str]:
    return [
        line.content
        for message in held.descendants()
        if isinstance(message, ui.chat_message) and (not eased or "game-enter" in message.classes)
        for line in message.descendants()
        if isinstance(line, ui.html)
    ]


def test_the_blocker_names_what_closes_the_composer() -> None:
    assert blocker(_view(), None, in_battle=False) is None
    assert blocker(_view(), "master", in_battle=False) == "master"
    assert blocker(_view(), None, in_battle=True) == "battle"
    assert blocker(_view(decision=_pick(allows_text=True)), None, in_battle=False) == "answer"
    assert blocker(_view(decision=_pick(allows_text=False)), None, in_battle=False) == "choose"
    assert blocker(_view(ending="Wren is dead"), "master", in_battle=False) == "over"


async def test_a_tick_follows_only_on_the_readers_own_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    # A tab's storage needs a socket; the composer's draft binds to a plain dict instead.
    monkeypatch.setattr("nicegui.storage.Storage.tab", property(lambda _storage: {}))
    table = open_game(tmp_path)
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    page()
    screen = GamePage(table.service)
    screen.build()
    screen.at_end = False
    screen.own_move = True

    table.service.working_role = "master"  # another tab's turn starting: not the reader's move
    screen.tick()
    assert screen.new_activity.visible is False

    screen.own_move = False
    table.service.working_role = "narrator"
    screen.tick()
    assert screen.new_activity.visible is True


async def test_the_live_turn_draws_each_fact_card_once_and_the_narration_heard_so_far(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.service
    page()
    live = LiveTurn(service)
    held = ui.element("div")
    drawn = TurnProgress.of(service)
    with held:
        live.build(drawn)

    async def synced() -> None:
        nonlocal drawn
        now = TurnProgress.of(service)
        live.sync(now, drawn)
        drawn = now
        await sleep(0)  # A refresh runs on the next loop pass.

    service.turn = Turn(
        engine=service.engine,
        draft=service.state.draft(),
        rng=Random(1),
        words="I look.",
        facts=[_told("One"), _told("Two")],
    )
    await synced()
    await synced()
    assert len(live.cards.default_slot.children) == 2

    service.turn.facts.append(_told("Three"))
    service.live = (SpokenLine(text="Nothing"),)
    await synced()
    assert len(live.cards.default_slot.children) == 3
    assert _texts(held) == ["I look.", "Nothing"]

    service.turn = None
    service.live = ()
    await synced()
    assert live.cards.default_slot.children == []
    assert _texts(held) == []


@pytest.mark.parametrize(
    ("shown", "heads"),
    [(True, ["One", "The rules refused reveal", "Two"]), (False, ["One", "Two"])],
)
async def test_the_live_turn_puts_a_refused_call_between_its_facts_only_when_shown(
    tmp_path: Path, page: Callable[[], Client], *, shown: bool, heads: list[str]
) -> None:
    table = open_game(tmp_path)
    service = table.service
    service.transcript_config = TranscriptConfig(refusals=shown)
    page()
    live = LiveTurn(service)
    drawn = TurnProgress.of(service)
    with ui.element("div"):
        live.build(drawn)
    service.turn = Turn(
        engine=service.engine, draft=service.state.draft(), rng=Random(1), facts=[_told("One")]
    )
    now = TurnProgress.of(service)
    live.sync(now, drawn)

    service.turn.refused.append(Refused(tool="reveal", reason="no such thing", after_facts=1))
    service.turn.facts.append(_told("Two"))
    live.sync(TurnProgress.of(service), now)

    drawn_heads = [
        label.text
        for label in live.cards.descendants()
        if isinstance(label, ui.label) and "game-fact-head" in label.classes
    ]
    assert drawn_heads == heads


async def test_a_page_is_not_built_for_a_client_deleted_before_the_handshake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    built: list[object] = []

    class _Recorder:
        def __init__(self, session: object) -> None:
            built.append(session)

        def build(self) -> None:
            built.append("built")

    monkeypatch.setattr("rulehall.ui.game.GamePage", _Recorder)
    client = page()
    client.delete()

    game_page(table.service)

    assert built == []


async def test_a_landed_exchange_appends_its_bubbles_and_a_rewind_redraws(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.service
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    page()
    chat = Chat(service)
    held = ui.element("div")
    first = service.history()
    with held:
        chat.build(service.player_view(), first)
    old = list(chat.column.default_slot.children)
    assert _texts(held, eased=True) == []

    before = service.state
    _ = await play_turn(table, "I listen.", narration="A drip.")
    landed = service.history()
    chat.sync(service.player_view(), landed, drawn_history=first)
    assert chat.column.default_slot.children[: len(old)] == old
    assert _texts(held, eased=True) == ["A drip."]

    chat.sync(service.player_view(), service.history(), drawn_history=landed)
    assert _texts(held) == ["I wait.", "Nothing stirs.", "I listen.", "A drip."]

    service.save(before)
    chat.sync(service.player_view(), service.history(), drawn_history=landed)
    assert _texts(held) == ["I wait.", "Nothing stirs."]
    assert chat.column.default_slot.children[0] not in old


async def test_a_pause_line_is_hidden_on_load_while_its_decision_is_still_open(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.service
    _suspend(table, _pick(allows_text=True))
    page()
    chat = Chat(service)
    chat.build(service.player_view(), service.history())
    assert chat.pause_line is not None
    assert chat.pause_line.visible is False


async def test_the_decision_panel_enters_on_the_tick_that_brings_it_and_not_the_next(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.service
    page()

    async def play(_answer: object) -> None:
        return None

    panel = DecisionPanel(play)
    held = ui.element("div")
    drawn = Snapshot.of(service)
    with held:
        panel.build(drawn)

    def entered() -> list[bool]:
        return [
            "game-enter" in banner.classes
            for banner in held.descendants()
            if isinstance(banner, ui.column) and "game-decision" in banner.classes
        ]

    assert entered() == []

    _suspend(table, _pick(allows_text=True))
    brought = Snapshot.of(service)
    panel.sync(brought, drawn)
    await sleep(0)
    assert entered() == [True]

    service.working_role = "master"
    panel.sync(Snapshot.of(service), brought)
    await sleep(0)
    assert entered() == [False]


async def test_a_portrait_drawn_after_the_panel_shows_on_the_art_tick(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).service
    drawn: list[Path] = []

    def icon(_session: GameService, _subject_id: str) -> Path | None:
        return drawn[0] if drawn else None

    monkeypatch.setattr(GameService, "icon", icon)
    page()
    tab = DrawerTab(service, SCENE_TAB, lambda _row: None)
    held = ui.element("div")
    with held:
        tab.panels(service.player_view())

    def portraits() -> list[ui.image]:
        return [image for image in held.descendants() if isinstance(image, ui.image)]

    assert portraits() == []

    drawn.append(tmp_path / "wren.png")
    tab.sync_icons(service.player_view())
    await sleep(0)
    assert portraits() != []
