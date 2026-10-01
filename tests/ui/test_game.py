from asyncio import sleep
from collections.abc import Callable, Sequence
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
from rulehall.core.decisions import ActionOption, Decision, PlayerInput
from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame
from rulehall.core.log import LogEntry, SpokenLine
from rulehall.core.views import SCENE_TAB, Panel, PanelRow, PlayerView, Subject
from rulehall.ui.composer import Composer, composer_lock
from rulehall.ui.drawer import DrawerTab, choosing
from rulehall.ui.game import GamePage, game_page
from rulehall.ui.transcript import Transcript
from rulehall.ui.voice import VoicePlayer
from rulehall.ui.widgets import Sounds, Speech

WREN = Subject(id="player", name="Wren", brief="A quiet scout", voice="feminine")


class HeardSpeech(Speech):
    def __init__(self) -> None:
        super().__init__()
        self.played: list[tuple[Path, int]] = []
        self.replayed: list[tuple[Path, int]] = []
        self.waited: list[int | None] = []
        self.stopped = 0

    def play(self, path: Path, bubble_id: int) -> None:
        self.played.append((path, bubble_id))

    def replay(self, path: Path, bubble_id: int) -> None:
        self.replayed.append((path, bubble_id))

    def wait(self, bubble_id: int | None) -> None:
        self.waited.append(bubble_id)

    def stop(self) -> None:
        self.stopped += 1


def _view(decision: Decision | None = None, ending: str | None = None) -> PlayerView:
    return PlayerView(
        premise="",
        player=WREN,
        scene_title="The Cloister Walk",
        situation="Rain drums the arcade.",
        panels=(),
        decision=decision,
        ending=ending,
        hint="Say what Wren does.",
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
        live = Transcript(drawn, service.icon, Sounds(), None)
    cards = live.live_block.card_slot

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
    assert len(cards.default_slot.children) == 2

    service.turn.facts.append(_told("Three"))
    service.live = (SpokenLine(text="Nothing"),)
    drawn = await synced(drawn)
    assert len(cards.default_slot.children) == 3
    assert _texts(held) == ["I look.", "Nothing"]
    bubble = live.live_block.bubbles[0]

    service.live = (SpokenLine(text="Nothing stirs"),)
    drawn = await synced(drawn)
    assert live.live_block.bubbles == [bubble]
    assert _texts(held) == ["I look.", "Nothing stirs"]

    service.turn = None
    service.live = ()
    drawn = await synced(drawn)
    assert cards.default_slot.children == []
    assert _texts(held) == []


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


async def test_a_landed_exchange_keeps_the_live_bubbles_and_a_rewind_redraws(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    page()
    held = ui.element("div")
    first = service.snapshot()
    with held:
        chat = Transcript(first, service.icon, Sounds(), None)
    old = list(chat.column.default_slot.children)
    assert _texts(held, eased=True) == []

    service.live = (SpokenLine(text="A dr"),)
    heard = service.snapshot()
    chat.sync(heard, first)
    streamed = chat.live_block.bubbles[0]

    before = service.state
    _ = await play_turn(table, "I listen.", narration="A drip.")
    landed = service.snapshot()
    chat.sync(landed, heard)
    assert chat.column.default_slot.children[: len(old)] == old
    assert streamed[0] in held.descendants()
    assert _texts(held, eased=True) == ["A drip."]

    chat.sync(service.snapshot(), landed)
    assert _texts(held) == ["I wait.", "Nothing stirs.", "I listen.", "A drip."]

    service.save(before)
    chat.sync(service.snapshot(), landed)
    assert _texts(held) == ["I wait.", "Nothing stirs."]
    assert chat.column.default_slot.children[0] not in old


async def test_a_live_line_is_handed_out_once_the_next_starts_and_the_last_at_landing(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    page()
    lines = (SpokenLine(text="Rain."), SpokenLine(text="Thunder."))
    before = replace(service.snapshot(), log_entries=(), live=())
    chat = Transcript(before, service.icon, Sounds(), None)

    first = replace(before, live=lines[:1])
    chat.sync(first, before)
    assert chat.finished_bubbles == []

    both = replace(before, live=lines)
    chat.sync(both, first)
    ids = [message.id for message, _ in chat.live_block.bubbles]
    assert chat.finished_bubbles == [(lines[0], ids[0])]

    chat.sync(both, both)
    assert chat.finished_bubbles == []

    landed = replace(before, log_entries=(LogEntry(words="I listen.", lines=lines),))
    chat.sync(landed, both)
    assert chat.finished_bubbles == [(lines[1], ids[1])]


async def test_a_restreamed_reply_withdraws_the_heard_lines_and_hands_out_the_new_once(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    page()
    refused = (SpokenLine(text="Rain."), SpokenLine(text="Thunder."))
    kept = (SpokenLine(text="Snow."), SpokenLine(text="Wind."))
    before = replace(service.snapshot(), log_entries=(), live=())
    chat = Transcript(before, service.icon, Sounds(), None)

    streamed = replace(before, live=refused)
    chat.sync(streamed, before)
    assert [line for line, _ in chat.finished_bubbles] == [refused[0]]
    assert not chat.withdrawn

    chat.sync(before, streamed)
    assert (chat.finished_bubbles, chat.withdrawn) == ([], True)

    restreamed = replace(before, live=kept)
    chat.sync(restreamed, before)
    assert [line for line, _ in chat.finished_bubbles] == [kept[0]]
    assert not chat.withdrawn

    chat.sync(restreamed, restreamed)
    assert (chat.finished_bubbles, chat.withdrawn) == ([], False)


async def test_a_battle_entrys_lines_are_handed_out(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    page()
    line = SpokenLine(text="The wild beast falls.")
    before = replace(service.snapshot(), log_entries=(), live=())
    chat = Transcript(before, service.icon, Sounds(), None)
    ended = LogEntry(words="", cause="battle", lines=(line,))
    chat.sync(replace(before, log_entries=(ended,)), before)
    assert [said for said, _ in chat.finished_bubbles] == [line]


async def test_a_pause_line_is_hidden_on_load_while_its_decision_is_still_open(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    table = open_game(tmp_path)
    service = table.session
    _suspend(table, _pick(allows_text=True))
    page()
    chat = Transcript(service.snapshot(), service.icon, Sounds(), None)
    assert chat.pause_line is not None
    assert chat.pause_line.visible is False


async def test_the_composer_asks_on_the_tick_that_brings_a_decision_and_not_the_next(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    monkeypatch.setattr("nicegui.storage.Storage.tab", property(lambda _storage: {}))
    table = open_game(tmp_path)
    service = table.session
    page()

    async def choose(_answer: PlayerInput) -> bool:
        return True

    drawn = service.snapshot()
    bar = Composer(service, drawn, choose, None)
    assert "game-asking" not in bar.row.classes

    _suspend(table, _pick(allows_text=True))
    brought = service.snapshot()
    bar.sync(brought, drawn)
    assert {"game-asking", "game-enter"} <= set(bar.row.classes)
    assert [member.id for _, members in bar.chips for member in members] == ["left"]

    service.working_role = "master"
    bar.sync(service.snapshot(), brought)
    assert "game-asking" in bar.row.classes
    assert "game-enter" not in bar.row.classes


async def test_the_composer_hides_the_words_box_when_a_decision_takes_no_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    monkeypatch.setattr("nicegui.storage.Storage.tab", property(lambda _storage: {}))
    table = open_game(tmp_path)
    service = table.session
    page()

    async def choose(_answer: PlayerInput) -> bool:
        return True

    idle = service.snapshot()
    bar = Composer(service, idle, choose, None)
    assert (bar.prompt_row.visible, bar.input_row.visible) == (False, True)
    assert bar.words_input.props["placeholder"] == idle.view.hint

    _suspend(table, _pick(allows_text=False))
    bar.sync(service.snapshot(), idle)
    assert (bar.prompt_row.visible, bar.input_row.visible) == (True, False)


async def test_a_portrait_drawn_after_the_panel_shows_on_the_art_tick(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    drawn: list[Path] = []

    def icon(_session: GameSession, _subject_id: str) -> Path | None:
        return drawn[0] if drawn else None

    monkeypatch.setattr(GameSession, "icon", icon)
    page()

    async def pick(_option: ActionOption) -> None:
        return None

    tab = DrawerTab(service, SCENE_TAB, lambda _row: None, pick)
    held = ui.element("div")
    with held:
        tab.draw_panels(service.snapshot().view, enabled=True)

    def portraits() -> list[ui.image]:
        return [image for image in held.descendants() if isinstance(image, ui.image)]

    assert portraits() == []

    drawn.append(tmp_path / "wren.png")
    tab.sync_icons()
    await sleep(0)
    assert portraits() != []


async def test_a_rows_own_options_close_while_the_game_is_busy(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    service = open_game(tmp_path).session
    now = replace(service.snapshot(), working_role=None, in_battle=False, held_elsewhere=False)
    assert choosing(replace(now, view=_view()))
    assert not choosing(replace(now, view=_view(), working_role="master"))
    assert not choosing(replace(now, view=_view(_pick(allows_text=False))))
    assert not choosing(replace(now, view=_view(), held_elsewhere=True))
    page()

    async def pick(_option: ActionOption) -> None:
        return None

    stow = ActionOption(id="stow", name="Stow", action_name="stow")
    rope = PanelRow(name="Rope", brief="", options=(stow,))
    view = _view().model_copy(update={"panels": (Panel(title="Gear", rows=(rope,)),)})
    tab = DrawerTab(service, SCENE_TAB, lambda _row: None, pick)
    with ui.element("div"):
        tab.draw_panels(view, enabled=True)
    [(button, _)] = tab.sections[0].choices
    assert button.enabled

    tab.sync(view, enabled=False)
    assert not button.enabled


async def test_the_voice_plays_landed_clips_in_order_and_a_redraw_is_flagged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    lines = tuple(SpokenLine(text=text) for text in ("Rain.", "Thunder.", "Silence."))
    ready = {lines[0].text, lines[2].text}
    spoken: list[SpokenLine] = []

    def speak_later(_session: GameSession, said: Sequence[SpokenLine]) -> None:
        spoken.extend(said)

    def find_clip(_session: GameSession, line: SpokenLine) -> Path | None:
        return tmp_path / line.text if line.text in ready else None

    monkeypatch.setattr(GameSession, "speak_later", speak_later)
    monkeypatch.setattr(GameSession, "find_clip", find_clip)
    service = open_game(tmp_path).session
    page()
    speech = HeardSpeech()
    before = replace(service.snapshot(), log_entries=())
    landed = replace(before, log_entries=(LogEntry(words="I listen.", lines=lines),))
    chat = Transcript(before, service.icon, Sounds(), None)
    player = VoicePlayer(service, speech)
    player.switch(on=True)

    chat.sync(landed, before)
    bubbles = chat.finished_bubbles
    player.hear(bubbles)
    assert spoken == list(lines)
    assert [path for path, _ in speech.played] == [tmp_path / "Rain."]

    ready.add(lines[1].text)
    chat.sync(landed, landed)
    player.hear(chat.finished_bubbles)
    assert speech.played == [(tmp_path / line.text, bubble_id) for line, bubble_id in bubbles]

    player.queued.append((lines[0], 0))
    chat.sync(before, landed)
    assert chat.redrawn
    player.stop()
    assert not player.queued
    assert speech.stopped == 1


async def test_a_replay_waits_for_a_missing_clip_and_a_stop_clears_the_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    line, other = SpokenLine(text="Rain."), SpokenLine(text="Thunder.")
    ready: set[str] = set()
    spoken: list[SpokenLine] = []

    def speak_later(_session: GameSession, said: Sequence[SpokenLine]) -> None:
        spoken.extend(said)

    def find_clip(_session: GameSession, line: SpokenLine) -> Path | None:
        return tmp_path / line.text if line.text in ready else None

    monkeypatch.setattr(GameSession, "speak_later", speak_later)
    monkeypatch.setattr(GameSession, "find_clip", find_clip)
    service = open_game(tmp_path).session
    page()
    speech = HeardSpeech()
    player = VoicePlayer(service, speech)

    player.read_aloud(line, 7)
    assert (spoken, speech.waited, speech.replayed) == ([line], [7], [])

    ready.add(line.text)
    player.hear(())
    assert speech.replayed == [(tmp_path / "Rain.", 7)]
    assert not player.queued

    player.read_aloud(other, 8)
    player.stop()
    assert not player.queued


async def test_the_voice_marks_a_blocked_head_as_waiting_until_its_clip_plays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, page: Callable[[], Client]
) -> None:
    line = SpokenLine(text="Rain.")
    ready: set[str] = set()

    def speak_later(_session: GameSession, _said: Sequence[SpokenLine]) -> None:
        return None

    def find_clip(_session: GameSession, line: SpokenLine) -> Path | None:
        return tmp_path / line.text if line.text in ready else None

    monkeypatch.setattr(GameSession, "speak_later", speak_later)
    monkeypatch.setattr(GameSession, "find_clip", find_clip)
    service = open_game(tmp_path).session
    page()
    speech = HeardSpeech()
    player = VoicePlayer(service, speech)
    player.switch(on=True)

    player.hear([(line, 3)])
    player.hear(())
    assert (speech.waited, speech.played) == ([3], [])

    ready.add(line.text)
    player.hear(())
    assert speech.played == [(tmp_path / "Rain.", 3)]
    assert speech.waited == [3, None]
