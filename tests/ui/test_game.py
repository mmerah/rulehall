from asyncio import sleep
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from random import Random

import pytest
from nicegui import Client, ui
from support.game import open_game
from support.table import (
    Table,
    play_turn,
)

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.app.turn import Turn
from rulehall.config import TranscriptConfig
from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame
from rulehall.core.log import RefusedCall, SpokenLine
from rulehall.core.views import SCENE_TAB, PlayerView, Subject
from rulehall.ui.composer import composer_lock
from rulehall.ui.drawer import DrawerTab
from rulehall.ui.game import DecisionPanel, GamePage, game_page
from rulehall.ui.transcript import Chat, LiveTurn
from rulehall.ui.widgets import Sounds

WREN = Subject(id="player", name="Wren", brief="A quiet scout")


def _view(decision: Decision | None = None, ending: str | None = None) -> PlayerView:
    return PlayerView(
        premise="",
        player=WREN,
        scene_title="The Cloister Walk",
        situation="Rain drums the arcade.",
        panels=(),
        decision=decision,
        ending=ending,
    )


def _told(card: str) -> Fact:
    return Fact(trace=card, told=True, card=card)


def _suspend[G: AnyGame](table: Table[G], decision: Decision) -> None:
    """A turn that ends on a pause, the way a suspending rule leaves one."""
    service = table.session
    draft = service.state.draft()
    draft.pending = decision
    lines = (SpokenLine(text="Two doors, and no light under either."),)
    service.save(service.engine.record(draft, lines, (), words="I look."))


def _pick(*, allows_text: bool) -> Decision:
    return Decision(
        kind="pick",
        prompt="Which door?",
        options=(ActionOption(id="left", name="Left", action_name="pick"),),
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


def test_the_composer_lock_names_what_closes_the_composer(tmp_path: Path) -> None:
    now = replace(open_game(tmp_path).session.snapshot(), working_role=None, in_battle=False)
    assert composer_lock(replace(now, view=_view())) is None
    assert composer_lock(replace(now, view=_view(), working_role="master")) == "master"
    assert composer_lock(replace(now, view=_view(), in_battle=True)) == "battle"
    assert composer_lock(replace(now, view=_view(decision=_pick(allows_text=True)))) == "answer"
    assert composer_lock(replace(now, view=_view(decision=_pick(allows_text=False)))) == "choose"
    ending = replace(now, view=_view(ending="Wren is dead"), working_role="master")
    assert composer_lock(ending) == "over"


async def test_a_tick_follows_only_on_the_readers_own_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    # A tab's storage needs a socket; the composer's draft binds to a plain dict instead.
    monkeypatch.setattr("nicegui.storage.Storage.tab", property(lambda _storage: {}))
    table = open_game(tmp_path)
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    page()
    screen = GamePage(table.session)
    screen.build()
    screen.at_end = False
    screen.own_move = True

    table.session.working_role = "master"  # another tab's turn starting: not the reader's move
    screen.tick()
    assert screen.new_activity.visible is False

    screen.own_move = False
    table.session.working_role = "narrator"
    screen.tick()
    assert screen.new_activity.visible is True


async def test_the_live_turn_draws_each_fact_card_once_and_the_narration_heard_so_far(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    page()
    held = ui.element("div")
    drawn = service.snapshot()
    with held:
        live = LiveTurn(drawn, service.icon, Sounds())

    async def synced(drawn: SessionSnapshot) -> SessionSnapshot:
        now = service.snapshot()
        live.sync(now, drawn)
        await sleep(0)  # A refresh runs on the next loop pass.
        return now

    service.turn = Turn(
        engine=service.engine,
        draft=service.state.draft(),
        rng=Random(1),
        logged_words="I look.",
        facts=[_told("One"), _told("Two")],
    )
    drawn = await synced(drawn)
    drawn = await synced(drawn)
    assert len(live.cards.default_slot.children) == 2

    service.turn.facts.append(_told("Three"))
    service.live = (SpokenLine(text="Nothing"),)
    drawn = await synced(drawn)
    assert len(live.cards.default_slot.children) == 3
    assert _texts(held) == ["I look.", "Nothing"]

    service.turn = None
    service.live = ()
    drawn = await synced(drawn)
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
    service = table.session
    service.live_settings.current = service.live_settings.current.model_copy(
        update={"transcript": TranscriptConfig(refusals=shown)}
    )
    page()
    drawn = service.snapshot()
    with ui.element("div"):
        live = LiveTurn(drawn, service.icon, Sounds())
    service.turn = Turn(
        engine=service.engine, draft=service.state.draft(), rng=Random(1), facts=[_told("One")]
    )
    now = service.snapshot()
    live.sync(now, drawn)

    service.turn.refused.append(RefusedCall(tool="reveal", reason="no such thing", after_facts=1))
    service.turn.facts.append(_told("Two"))
    live.sync(service.snapshot(), now)

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

    key = table.session.key
    await game_page(table.runtime, key.scenario_id, key.character_id)

    assert built == []


async def test_a_landed_exchange_appends_its_bubbles_and_a_rewind_redraws(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    page()
    held = ui.element("div")
    first = service.snapshot()
    with held:
        chat = Chat(first, service.icon, Sounds())
    old = list(chat.column.default_slot.children)
    assert _texts(held, eased=True) == []

    before = service.state
    _ = await play_turn(table, "I listen.", narration="A drip.")
    landed = service.snapshot()
    chat.sync(landed, first)
    assert chat.column.default_slot.children[: len(old)] == old
    assert _texts(held, eased=True) == ["A drip."]

    chat.sync(service.snapshot(), landed)
    assert _texts(held) == ["I wait.", "Nothing stirs.", "I listen.", "A drip."]

    service.save(before)
    chat.sync(service.snapshot(), landed)
    assert _texts(held) == ["I wait.", "Nothing stirs."]
    assert chat.column.default_slot.children[0] not in old


async def test_a_pause_line_is_hidden_on_load_while_its_decision_is_still_open(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    _suspend(table, _pick(allows_text=True))
    page()
    chat = Chat(service.snapshot(), service.icon, Sounds())
    assert chat.pause_line is not None
    assert chat.pause_line.visible is False


async def test_the_decision_panel_enters_on_the_tick_that_brings_it_and_not_the_next(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    page()

    async def play(_answer: object) -> None:
        return None

    held = ui.element("div")
    drawn = service.snapshot()
    with held:
        panel = DecisionPanel(drawn, play)

    def entered() -> list[bool]:
        return [
            "game-enter" in banner.classes
            for banner in held.descendants()
            if isinstance(banner, ui.column) and "game-decision" in banner.classes
        ]

    assert entered() == []

    _suspend(table, _pick(allows_text=True))
    brought = service.snapshot()
    panel.sync(brought, drawn)
    await sleep(0)
    assert entered() == [True]

    service.working_role = "master"
    panel.sync(service.snapshot(), brought)
    await sleep(0)
    assert entered() == [False]


async def test_a_portrait_drawn_after_the_panel_shows_on_the_art_tick(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    drawn: list[Path] = []

    def icon(_session: GameSession, _subject_id: str) -> Path | None:
        return drawn[0] if drawn else None

    monkeypatch.setattr(GameSession, "icon", icon)
    page()
    tab = DrawerTab(service, SCENE_TAB, lambda _row: None)
    held = ui.element("div")
    with held:
        tab.draw_panels(service.snapshot().view)

    def portraits() -> list[ui.image]:
        return [image for image in held.descendants() if isinstance(image, ui.image)]

    assert portraits() == []

    drawn.append(tmp_path / "wren.png")
    tab.sync_icons(service.snapshot().view)
    await sleep(0)
    assert portraits() != []
