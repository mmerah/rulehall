from random import Random

from support.game import ENGINE, MARA, initialized, loner_sheet

from rulehall.core.views import Panel
from rulehall.engines.loner4e.args import Ask, SpendLuck
from rulehall.engines.loner4e.engine import BROKE_AWAY, DEFEATED
from rulehall.engines.loner4e.panels import BREAK_AWAY, MOVE_ON
from rulehall.engines.loner4e.rules import DOUBLES_PER_TWIST, LUCK_MAX, outcome_for
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.sheet import PLAYER_ID

DUEL = Ask(question="Does he force her back from the door?", opponent_id=MARA)


def _panel(state: Loner4eGame, title: str) -> Panel:
    return next(panel for panel in ENGINE.scene_panels(state) if panel.title == title)


def test_the_outcome_ladder_covers_every_pair_of_dice() -> None:
    tally: dict[str, int] = {}
    for chance in range(1, 7):
        for risk in range(1, 7):
            outcome = outcome_for(chance, risk)
            tally[outcome.id] = tally.get(outcome.id, 0) + 1
    assert tally == {
        "yes-and": 3,
        "yes": 9,
        "yes-but": 9,
        "no-but": 3,
        "no": 9,
        "no-and": 3,
    }


def test_a_conflict_start_refills_both_sides_and_its_doubles_tick_no_twist() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.player.luck.current = 2
    draft.world.twist.current = DOUBLES_PER_TWIST - 1

    # Seed 0 rolls chance 4 against risk 4: doubles, a yes-but that costs Mara one luck.
    _ = ENGINE.ask(draft, DUEL, Random(0))

    assert draft.world.opponent_ids == [MARA]
    assert loner_sheet(draft, PLAYER_ID).luck.current == LUCK_MAX
    assert loner_sheet(draft, MARA).luck.current == LUCK_MAX - 1
    assert draft.world.twist.current == DOUBLES_PER_TWIST - 1


def test_the_last_opponent_out_ends_the_conflict_and_refills_everyone() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = ENGINE.ask(draft, DUEL, Random(0))
    draft.world.player.luck.current = 3
    loner_sheet(draft, MARA).luck.current = 1

    _ = ENGINE.ask(draft, DUEL, Random(0))

    assert draft.world.opponent_ids == []
    assert loner_sheet(draft, PLAYER_ID).luck.current == LUCK_MAX
    assert loner_sheet(draft, MARA).luck.current == LUCK_MAX
    assert DEFEATED.format(name="Mara") in draft.notes


def test_a_twist_that_ends_the_scene_closes_it_in_the_same_ask() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.twist.current = DOUBLES_PER_TWIST - 1

    # Seed 13 rolls chance 3 against risk 3, then the twist pair 6 / 6: An object / Ends the scene.
    facts = ENGINE.ask(draft, Ask(question="Does the flagstone lift?"), Random(13))

    assert draft.world.twist.current == 0
    assert draft.world.frame.closed_by == "twist"
    assert not draft.world.frame.open
    assert any(fact.card.startswith("Scene closes: twist") for fact in facts)


def test_a_spend_to_zero_in_a_conflict_loses_it() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.pack_id = "ap01-fantasy"
    _ = ENGINE.ask(draft, DUEL, Random(0))

    _ = ENGINE.spend_luck(
        draft, SpendLuck(actor_id=PLAYER_ID, amount=LUCK_MAX, why="A bolt"), Random(0)
    )

    assert draft.world.opponent_ids == []
    assert loner_sheet(draft, PLAYER_ID).luck.current == LUCK_MAX
    assert DEFEATED.format(name="Kael") in draft.notes


def test_break_away_ends_the_conflict_and_move_on_waits_until_it_is_over() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = ENGINE.ask(draft, DUEL, Random(0))
    goal, _place, conflict = _panel(draft, "Dramatic scene").rows
    assert (goal.options, conflict.options) == ((), (BREAK_AWAY,))

    _ = ENGINE.play_option(draft, BREAK_AWAY, Random(0))

    assert draft.world.opponent_ids == []
    assert BROKE_AWAY in draft.notes
    assert _panel(draft, "Dramatic scene").rows[0].options == (MOVE_ON,)


def test_fight_opens_the_conflict_and_the_lone_opponent_gets_the_next_ask() -> None:
    _, state = initialized()
    draft = state.draft()
    (fight,) = (
        option
        for row in _panel(draft, "Also here").rows
        for option in row.options
        if option.args == {"opponent_id": MARA}
    )

    _ = ENGINE.play_option(draft, fight, Random(0))
    _ = ENGINE.ask(draft, Ask(question="Does he force her back from the door?"), Random(0))

    assert draft.world.opponent_ids == [MARA]
    assert loner_sheet(draft, MARA).luck.current == LUCK_MAX - 1
    assert draft.world.scene.settled == []


def test_an_exchange_against_a_new_id_brings_that_opponent_in() -> None:
    _, state = initialized()
    draft = state.draft()

    _ = ENGINE.ask(draft, Ask(question="Does he shove past?", opponent_id="dock-guard"), Random(0))

    guard = loner_sheet(draft, "dock-guard")
    assert (guard.name, guard.known, guard.luck.maximum) == ("Dock Guard", True, LUCK_MAX)
    assert "dock-guard" in draft.world.present()
    assert draft.world.opponent_ids == ["dock-guard"]
