from random import Random

from support.game import ENGINE, initialized, loner_sheet, with_entity
from support.table import change, refused

from rulehall.core.facts import cards
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner3e.args import Roll
from rulehall.engines.loner3e.world import Loner3eEntity

FOE = "mara"
HIDDEN = Loner3eEntity(id="watcher", name="The Watcher", brief="unseen so far", known=False)
REVEALED = Loner3eEntity(id="warden", name="The Warden", brief="already met", known=True)


def _seal(**args: object) -> Roll:
    return Roll.model_validate(
        {
            "what": "Force the seal",
            "actor_id": PLAYER_ID,
            "question": "Does he get the seal open before the whispering finds him?",
        }
        | args
    )


def test_a_neutral_question_shows_one_chance_die_and_one_risk_die() -> None:
    _, state = initialized()
    facts = ENGINE.roll(state.draft(), _seal(), Random(0))

    (oracle,) = cards(facts)
    assert [die.label for die in oracle.dice] == ["Chance", "Risk"]
    assert len(oracle.dice[0].rolled) == 1
    assert len(oracle.dice[1].rolled) == 1
    assert oracle.card.startswith("Force the seal — oracle, neutral: ")


def test_advantage_rolls_two_chance_dice() -> None:
    _, state = initialized()
    facts = ENGINE.roll(state.draft(), _seal(position="advantage", edge="Relic Hunter"), Random(0))

    (oracle,) = cards(facts)
    assert len(oracle.dice[0].rolled) == 2
    assert len(oracle.dice[1].rolled) == 1
    assert oracle.card.startswith("Force the seal — oracle, advantage (Relic Hunter): ")
    assert oracle.trace == oracle.card


def test_drive_refuses_naming_a_hidden_entity_but_allows_a_revealed_one() -> None:
    _, state = initialized()
    state = with_entity(with_entity(state, HIDDEN), REVEALED)
    draft = state.draft()
    kael = loner_sheet(draft, PLAYER_ID)

    assert "not met" in refused(
        ENGINE, draft, "drive", actor_id=PLAYER_ID, nemesis="The Watcher hunts him"
    )
    assert kael.nemesis == ""

    _ = change(ENGINE, draft, "drive", actor_id=PLAYER_ID, nemesis="The Warden hunts him")
    assert kael.nemesis == "The Warden hunts him"


def test_spend_luck_is_refused_when_the_pack_does_not_spend_it() -> None:
    _, state = initialized()

    assert "this pack does not spend luck" in refused(
        ENGINE, state.draft(), "spend_luck", actor_id=PLAYER_ID, amount=2, why="A ward"
    )


def test_spend_luck_lands_one_fact_and_no_defeat() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.pack_id = "ap01-fantasy"
    fantasy = draft.commit()

    facts = change(
        ENGINE, fantasy.draft(), "spend_luck", actor_id=PLAYER_ID, amount=2, why="A ward"
    )

    (event,) = cards(facts)
    assert event.card == "Luck -2 → 4/6"
    assert not loner_sheet(fantasy, PLAYER_ID).defeated
