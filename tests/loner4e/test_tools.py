from random import Random

import pytest
from pydantic import JsonValue
from support.game import ENGINE, MARA, TOMAS, initialized, loner_sheet, with_entity
from support.table import change, refused, run_action

from rulehall.app.turn import Turn
from rulehall.core.decisions import PlayerInput
from rulehall.core.facts import told_cards
from rulehall.core.log import SpokenLine
from rulehall.engines.loner4e.engine import BROKE_AWAY
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.sheet import PLAYER_ID


def test_a_name_the_player_is_told_or_narrated_is_met_where_loner_refused_it() -> None:
    _, state = initialized()
    draft = state.draft()
    hunter = "Brother Tomas hunts him"

    _ = change(ENGINE, draft, "drive", actor_id=PLAYER_ID, nemesis=hunter)
    narrated = ENGINE.record(draft, (SpokenLine(text="Elena's lamp burns above."),), ())

    assert loner_sheet(draft, PLAYER_ID).nemesis == hunter
    assert [narrated.world.cast[entry].known for entry in (TOMAS, "elena")] == [True, True]
    assert TOMAS not in narrated.world.scene.here_ids


def test_spend_luck_is_published_only_when_the_pack_spends_it() -> None:
    _, state = initialized()
    fantasy = state.model_copy(update={"pack_id": "ap01-fantasy"})

    assert "spend_luck" not in {tool.name for tool in ENGINE.published(state)}
    assert "spend_luck" in {tool.name for tool in ENGINE.published(fantasy)}


def test_spend_luck_on_a_pack_without_luck_is_refused_as_not_a_tool_now() -> None:
    _, state = initialized()

    assert refused(ENGINE, state.draft(), "spend_luck") == "'spend_luck' is not a tool now"


def test_spend_luck_lands_one_fact() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.pack_id = "ap01-fantasy"
    fantasy = draft.validated()

    facts = change(
        ENGINE, fantasy.draft(), "spend_luck", actor_id=PLAYER_ID, amount=2, why="A ward"
    )

    (event,) = told_cards(facts)
    assert event.card == "Luck -2 → 4/6"


@pytest.mark.parametrize(
    ("fields", "refusal"),
    [
        ({"helps": ["Picks Any Lock"]}, "no such tag here"),
        ({"helps": ["Slow to Trust"], "hinders": ["slow to trust"]}, "duplicate cited tags"),
        ({"opponent_id": PLAYER_ID}, "never the player"),
        ({"helps": ["Untrained"]}, "never helps"),
    ],
)
def test_ask_refuses_what_it_cannot_net_or_face(fields: dict[str, JsonValue], refusal: str) -> None:
    _, state = initialized()
    args = {"question": "Does he slip past unheard?"} | fields
    assert refusal in refused(ENGINE, state.draft(), "ask", **args)


def test_a_tag_helps_or_hinders_bare_or_listed_and_is_lost_in_any_case_or_kind() -> None:
    _, state = initialized()
    draft = state.draft()
    asked: dict[str, JsonValue] = {"question": "Does he slip past unheard?"}
    either_side: tuple[dict[str, JsonValue], ...] = (
        {"helps": "Knows the Catalogue", "hinders": ["quiet hands"]},
        {"helps": ["Slow to Trust"], "hinders": "Never Walks Away"},
    )
    for fields in either_side:
        _ = change(ENGINE, draft, "ask", **asked, **fields)

    _ = change(ENGINE, draft, "change_tags", actor_id=PLAYER_ID, kind="gear", lost="quiet hands")
    assert loner_sheet(draft, PLAYER_ID).tagged("skill") == ["Reads Old Stonework"]
    _ = run_action(ENGINE, draft, "mark_status", column="physical")
    _ = change(ENGINE, draft, "ask", **asked, hinders=["Hurt (1/3)"])


def test_a_new_id_files_a_met_stranger_someone_elsewhere_enters_and_a_repeat_changes_nothing() -> (
    None
):
    _, state = initialized()
    crane = Loner4eEntity(id="silas-crane", name="Silas Crane", brief="a clerk with a sword")
    draft = with_entity(state, crane).draft()

    _ = change(ENGINE, draft, "enter", target_id="dock-guard")
    _ = change(ENGINE, draft, "change_tags", actor_id="old-monk", kind="condition", gained="Wary")
    _ = change(ENGINE, draft, "enter", target_id="crane")
    assert change(ENGINE, draft, "enter", target_id="crane") == []
    assert change(ENGINE, draft, "leave", target_id="nowhere") == []
    _ = change(ENGINE, draft, "change_tags", actor_id=TOMAS, kind="condition", gained="Wary")

    world = draft.world
    assert world.scene.here_ids[-4:] == ["silas-crane", "dock-guard", "old-monk", TOMAS]
    assert loner_sheet(draft, "old-monk").name == "Old Monk"
    assert loner_sheet(draft, "old-monk").tagged("condition") == ["Wary"]
    _ = change(ENGINE, draft, "kill", target_id=TOMAS)
    assert change(ENGINE, draft, "leave", target_id=TOMAS) == []


def test_a_conflict_marks_the_protagonist_with_no_condition() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = run_action(ENGINE, draft, "fight", opponent_id=MARA)
    hurt: dict[str, JsonValue] = {
        "actor_id": PLAYER_ID,
        "kind": "condition",
        "gained": ["Bleeding"],
    }
    assert "Status pick" in refused(ENGINE, draft, "change_tags", **hurt)

    _ = change(ENGINE, draft, "withdraw")
    _ = change(ENGINE, draft, "change_tags", **hurt)
    assert loner_sheet(draft, PLAYER_ID).tagged("condition") == ["Bleeding"]


def test_a_withdraw_cost_passes_another_defeat() -> None:
    _, state = initialized()
    mob = Loner4eEntity(id="mob", name="The Mob", brief="half the town", known=True, group=True)
    draft = with_entity(state, mob).draft()
    draft.pack_id = "ap01-fantasy"
    hurt: dict[str, JsonValue] = {"actor_id": PLAYER_ID, "kind": "condition", "gained": "Bleeding"}
    asked: dict[str, JsonValue] = {"question": "Do I break through?"}
    _ = change(ENGINE, draft, "ask", **asked, opponent_id="mob")
    _ = change(ENGINE, draft, "ask", **asked, opponent_id=MARA)

    left = loner_sheet(draft, MARA).luck.current
    _ = change(ENGINE, draft, "spend_luck", actor_id=MARA, amount=left, why="A bolt")
    _ = change(ENGINE, draft, "withdraw")
    _ = change(ENGINE, draft, "change_tags", **hurt)
    assert loner_sheet(draft, PLAYER_ID).tagged("condition") == ["Bleeding"]


def test_a_player_question_with_no_conflict_open_is_a_plain_question() -> None:
    _, state = initialized()
    draft = state.draft()
    words = "Is the gunman afraid to shoot me?"
    _ = run_action(ENGINE, draft, "ask_oracle", words=words)

    _ = change(ENGINE, draft, "ask", question=None, opponent_id=MARA)

    assert draft.world.opponent_ids == []
    assert draft.world.scene.settled[-1].question == words


def test_a_scene_detail_needs_no_kind_and_old_beats_give_way_to_new_ones() -> None:
    _, state = initialized()
    draft = state.draft()
    beats = [f"Beat {number}" for number in range(8)]
    facts = [
        fact
        for beat in beats
        for fact in change(ENGINE, draft, "change_tags", actor_id="scene", gained=beat)
    ]

    assert draft.world.frame.details == beats[-6:]
    assert not any("No longer" in fact.card for fact in facts)


def test_a_tag_on_a_person_defaults_to_a_condition() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = change(ENGINE, draft, "change_tags", actor_id=PLAYER_ID, gained="Soaked")

    assert "Soaked" in draft.world.player.tagged("condition")
    assert "Soaked" not in draft.world.frame.details


def test_after_the_close_only_direct_is_left() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = change(ENGINE, draft, "close_scene", reason="resolved")
    after_close: tuple[tuple[str, dict[str, JsonValue]], ...] = (
        ("ask", {"question": "Does he slip past unheard?"}),
        ("drive", {"actor_id": PLAYER_ID, "goal": "Run"}),
        ("change_tags", {"actor_id": "scene", "kind": "detail", "gained": ["Smoke"]}),
        ("enter", {"target_id": TOMAS}),
        ("leave", {"target_id": MARA}),
    )
    for name, args in after_close:
        assert "call `direct` now" in refused(ENGINE, draft, name, **args)
    _ = change(ENGINE, draft, "direct", text="The study falls behind him.")


def test_a_null_question_rolls_the_player_question_word_for_word_and_clears_it() -> None:
    _, state = initialized()
    draft = state.draft()
    words = "Is the abbot's desk unlocked?"
    _ = run_action(ENGINE, draft, "ask_oracle", words=words)

    facts = change(ENGINE, draft, "ask", question=None)

    assert told_cards(facts)[0].card.startswith(words)
    assert draft.world.scene.settled[-1].question == words
    assert draft.world.player_question == ""


@pytest.mark.parametrize("sent", ["Does he slip past unheard?", "null"])
def test_the_waiting_player_question_wins_whatever_the_master_sends(sent: str) -> None:
    _, state = initialized()
    draft = state.draft()
    words = "Is the abbot's desk unlocked?"
    _ = run_action(ENGINE, draft, "ask_oracle", words=words)

    _ = change(ENGINE, draft, "ask", question=sent)

    assert draft.world.scene.settled[-1].question == words


def test_the_end_of_the_turn_drops_an_unasked_player_question() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = run_action(ENGINE, draft, "ask_oracle", words="Is the abbot's desk unlocked?")

    ENGINE.end_turn(draft, acted=False)

    assert draft.world.player_question == ""


def test_a_note_the_tool_answer_shows_is_not_shown_again_next_turn() -> None:
    engine, state = initialized()
    draft = state.draft()
    _ = run_action(ENGINE, draft, "fight", opponent_id=MARA)
    turn = Turn.begin(engine, draft.validated(), PlayerInput(text="I run."), Random(0))

    assert BROKE_AWAY in turn.call_tool("withdraw", {})
    after = turn.finish(())
    assert Turn.begin(engine, after, PlayerInput(text="I catch my breath."), Random(0)).notes == []


def test_in_a_conflict_every_ask_is_an_exchange_against_the_one_fought_last() -> None:
    _, state = initialized()
    mob = Loner4eEntity(id="mob", name="The Mob", brief="half the town", known=True, group=True)
    draft = with_entity(state, mob).draft()
    asked: dict[str, JsonValue] = {"question": "Do I break through?"}

    _ = change(ENGINE, draft, "ask", **asked, opponent_id="mob")
    _ = change(ENGINE, draft, "ask", **asked, opponent_id=MARA)
    struck = change(ENGINE, draft, "ask", **asked)
    assert any("Mara" in fact.trace and "exchange" in fact.trace for fact in struck)
    assert draft.world.opponent_ids == ["mob", MARA]
    assert loner_sheet(draft, "mob").luck.maximum == 8
    assert draft.world.scene.settled == []

    _ = change(ENGINE, draft, "withdraw")
    _ = change(ENGINE, draft, "ask", **asked)
    assert [entry.question for entry in draft.world.scene.settled] == ["Do I break through?"]


def test_the_growth_waits_for_the_end_and_is_written_once() -> None:
    _, state = initialized()
    draft = state.draft()
    grown: dict[str, JsonValue] = {"actor_id": PLAYER_ID, "kind": "skill", "gained": "Patience"}

    assert "only after the player picks End it" in refused(ENGINE, draft, "change_tags", **grown)
    _ = run_action(ENGINE, draft, "confirm_end")
    _ = change(ENGINE, draft, "change_tags", **grown)
    again = grown | {"kind": "frailty", "gained": "Old Scars"}
    assert "it is written" in refused(ENGINE, draft, "change_tags", **again)
    assert loner_sheet(draft, PLAYER_ID).tagged("skill")[-1] == "Patience"
