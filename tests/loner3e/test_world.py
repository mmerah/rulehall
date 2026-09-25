from pydantic import JsonValue
from support.game import ENGINE, MARA, initialized
from support.table import change
from support.table import refused as change_refused

from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner3e.rules import TIES_PER_TWIST
from rulehall.engines.loner3e.world import Loner3eGame


def changed(draft: Loner3eGame, name: str, **fields: JsonValue) -> list[str]:
    return [fact.trace for fact in change(ENGINE, draft, name, **fields)]


def refused(draft: Loner3eGame, name: str, **fields: JsonValue) -> str:
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

    _ = changed(draft, "kill", target_id=MARA)
    assert "dead" in refused(draft, "change_tags", actor_id=MARA, kind="gear", gained=["Rope"])
    _ = draft.commit()


def test_drive_writes_what_play_revealed() -> None:
    _, state = initialized()
    draft = state.draft()

    traces = changed(draft, "drive", actor_id=PLAYER_ID, goal="Get out of the ruin alive")
    assert draft.world.player.goal == "Get out of the ruin alive"
    assert "goal: Get out of the ruin alive" in traces[0]

    assert "goal, a motive or a nemesis" in refused(draft, "drive", actor_id=PLAYER_ID)

    _ = changed(draft, "kill", target_id=MARA)
    assert "dead" in refused(draft, "drive", actor_id=MARA, motive="Survive")
    _ = draft.commit()


def test_tick_twist_turns_over_on_the_third_call_and_resets() -> None:
    _, state = initialized()
    draft = state.draft()

    assert draft.world.tick_twist() is False
    assert draft.world.twist.current == 1
    assert draft.world.tick_twist() is False
    assert draft.world.twist.current == TIES_PER_TWIST - 1
    assert draft.world.tick_twist() is True
    assert draft.world.twist.current == 0
