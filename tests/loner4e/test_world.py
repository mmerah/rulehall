import pytest
from pydantic import JsonValue
from support.game import ENGINE, MARA, initialized
from support.table import change
from support.table import refused as change_refused

from rulehall.engines.loner4e.rules import DOUBLES_PER_TWIST, position_for
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.sheet import PLAYER_ID


def changed(draft: Loner4eGame, name: str, **fields: JsonValue) -> list[str]:
    return [fact.trace for fact in change(ENGINE, draft, name, **fields)]


def refused(draft: Loner4eGame, name: str, **fields: JsonValue) -> str:
    return change_refused(ENGINE, draft, name, **fields)


def test_change_tags_edits_one_list_and_refuses_what_it_cannot_move() -> None:
    _, state = initialized()
    draft = state.draft()

    assert "at least one" in refused(draft, "change_tags", actor_id=PLAYER_ID, kind="gear")

    traces = changed(draft, "change_tags", actor_id=PLAYER_ID, kind="gear", gained=["Rusty Key"])
    assert "Rusty Key" in draft.world.player.tagged("gear")
    assert traces[0].endswith("gear +Rusty Key")

    assert "already carries" in refused(
        draft, "change_tags", actor_id=PLAYER_ID, kind="gear", gained=["Rusty Key"]
    )

    traces = changed(
        draft, "change_tags", actor_id=PLAYER_ID, kind="condition", gained=["Listening"]
    )
    assert "Listening" in draft.world.player.tagged("condition")
    assert traces[0].endswith("condition +Listening")

    traces = changed(draft, "change_tags", actor_id=PLAYER_ID, kind="condition", lost=["Listening"])
    assert "Listening" not in draft.world.player.tagged("condition")
    assert traces[0].endswith("condition -Listening")

    assert "carries no condition" in refused(
        draft, "change_tags", actor_id=PLAYER_ID, kind="condition", lost=["Listening"]
    )

    assert "duplicate" in refused(
        draft, "change_tags", actor_id=PLAYER_ID, kind="gear", gained=["Rope", "Rope"]
    )

    assert "never on the player" in refused(
        draft, "change_tags", actor_id=PLAYER_ID, kind="relationship", gained=["Uneasy Ally"]
    )

    _ = changed(draft, "kill", target_id=MARA)
    assert "dead" in refused(draft, "change_tags", actor_id=MARA, kind="gear", gained=["Rope"])
    _ = draft.validated()


def test_drive_writes_what_play_revealed() -> None:
    _, state = initialized()
    draft = state.draft()

    traces = changed(draft, "drive", actor_id=PLAYER_ID, goal="Get out of the ruin alive")
    assert draft.world.player.goal == "Get out of the ruin alive"
    assert "goal: Get out of the ruin alive" in traces[0]

    assert "a nemesis or a concept" in refused(draft, "drive", actor_id=PLAYER_ID)

    _ = changed(draft, "kill", target_id=MARA)
    assert "dead" in refused(draft, "drive", actor_id=MARA, motive="Survive")
    _ = draft.validated()


def test_tick_twist_turns_over_on_the_third_call_and_resets() -> None:
    _, state = initialized()
    draft = state.draft()

    assert [draft.world.tick_twist() for _ in range(DOUBLES_PER_TWIST)] == [1, 2, 3]
    assert draft.world.twist.current == 0


@pytest.mark.parametrize(
    ("helps", "hinders", "position"),
    [(3, 1, "advantage"), (1, 2, "disadvantage"), (2, 2, "neutral"), (0, 0, "neutral")],
)
def test_tags_net_to_one_die_at_most(helps: int, hinders: int, position: str) -> None:
    assert position_for(helps, hinders) == position


def test_a_comma_inside_a_tag_reads_as_and() -> None:
    entity = Loner4eEntity(
        id="fen", name="Fen", voice="masculine", brief="", tags={"frailty": ["Proud, Stubborn"]}
    )
    assert entity.tags == {"frailty": ["Proud and Stubborn"]}
