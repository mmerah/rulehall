from random import Random

from support.game import ENGINE, MARA, initialized, loner_sheet
from support.table import change, refused

from rulehall.core.facts import told_cards
from rulehall.engines.loner4e.args import Ask, SpendLuck
from rulehall.engines.loner4e.engine import SECOND_DEAD_END
from rulehall.engines.loner4e.rules import (
    DEAD_END_QUESTION,
    INSPIRATION_ADJECTIVES,
    INSPIRATION_NOUNS,
    INSPIRATION_VERBS,
    LUCK_MAX,
    RUN_ITS_COURSE_QUESTION,
)
from rulehall.engines.sheet import PLAYER_ID

YES_SEED = 5
NO_SEED = 1


def test_a_defeat_opens_no_pick_and_a_condition_may_mark_the_protagonist_in_a_conflict() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.pack_id = "ap01-fantasy"
    duel = Ask(question="Does he force her back from the door?", opponent_id=MARA)
    _ = ENGINE.ask(draft, duel, Random(0))
    _ = change(ENGINE, draft, "change_tags", actor_id=PLAYER_ID, gained="Bleeding")

    _ = ENGINE.spend_luck(
        draft, SpendLuck(actor_id=PLAYER_ID, amount=LUCK_MAX, why="A bolt"), Random(0)
    )

    assert draft.pending is None
    assert draft.world.opponent_ids == []
    assert loner_sheet(draft, PLAYER_ID).tagged("condition") == ["Bleeding"]


def test_a_second_dead_end_in_the_scene_is_refused() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = change(ENGINE, draft, "ask", question=DEAD_END_QUESTION)

    assert refused(ENGINE, draft, "ask", question=DEAD_END_QUESTION.lower()) == SECOND_DEAD_END


def test_any_yes_to_the_run_its_course_question_closes_the_scene_and_a_no_keeps_it() -> None:
    _, state = initialized()
    kept, closed = state.draft(), state.draft()

    _ = ENGINE.ask(kept, Ask(question=RUN_ITS_COURSE_QUESTION), Random(NO_SEED))
    facts = ENGINE.ask(closed, Ask(question=RUN_ITS_COURSE_QUESTION), Random(YES_SEED))

    assert kept.world.frame.open
    assert closed.world.frame.closed_by == "ran_its_course"
    assert any(fact.card.startswith("Scene closes: ran its course") for fact in told_cards(facts))


def test_the_inspiration_tables_give_a_verb_an_adjective_and_a_noun() -> None:
    _, state = initialized()
    draft = state.draft()

    [shown] = told_cards(change(ENGINE, draft, "roll_inspiration"))

    verb, adjective, noun = shown.card.removeprefix("Inspiration — ").split(" ")
    assert verb in {word for row in INSPIRATION_VERBS for word in row}
    assert adjective in {word for row in INSPIRATION_ADJECTIVES for word in row}
    assert noun in {word for row in INSPIRATION_NOUNS for word in row}
