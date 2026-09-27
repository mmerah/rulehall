import json
from collections.abc import Mapping
from pathlib import Path
from random import Random

import pytest
from pydantic import BaseModel, ValidationError
from support.game import ENGINE, MARA, TOMAS, Dice, initialized, open_game
from support.table import (
    LIBRARY,
    SCENARIO_MODELS,
    change,
    narrated,
    narrowed,
    play_turn,
    refused,
    stub_worldsmith,
    tool_call,
)

from rulehall.core.model import Check, RoleAnswer, WorldsmithRequest
from rulehall.core.play import Exchange, PendingDecision
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal
from rulehall.engines.loner4e.args import CloseScene
from rulehall.engines.loner4e.engine import ELSEWHERE_TITLE
from rulehall.engines.loner4e.panels import MOVE_ON, TAKE_BREATHER
from rulehall.engines.loner4e.rules import MEANWHILE_QUESTION, SceneKind, transition_for
from rulehall.engines.loner4e.world import (
    OFF_SCREEN,
    Loner4eGame,
    Loner4eNext,
    Loner4eOpening,
)
from rulehall.engines.scenes.worldsmith import check_opening

GOAL = "Find the stair down"
NEXT_SCENE: dict[str, object] = {
    "place_id": "cloister",
    "title": "The Cloister",
    "situation": "A frost-rimed colonnade around a dead garden, unswept for a long while.",
    "recap": "He left the study with what he came for.",
    "goal": GOAL,
    "details": ["Frost-Rimed Colonnade", "Dead Garden"],
}
CLOSED = tool_call("close_scene", reason="resolved")
DIRECTED = tool_call("direct", text="he has what he came for")


def _opening(**changes: object) -> Loner4eOpening:
    opening = LIBRARY.read_scenario("whispering-vault", SCENARIO_MODELS).opening
    return narrowed(opening, Loner4eOpening).model_copy(update=changes)


def _checking(answer: Mapping[str, object]) -> RoleAnswer:
    async def checked[M: BaseModel](_prompt: Prompt, model: type[M], check: Check[M]) -> M:
        parsed = model.model_validate_json(json.dumps(answer))
        check(parsed)
        return parsed

    return checked


def _meanwhile(follow_up: SceneKind, ally: str = "yes") -> tuple[Loner4eGame, WorldsmithRequest]:
    _, state = initialized()
    draft = _played(state)
    draft.world.frame.ally = ally
    draft.world.frame.next, draft.world.frame.meanwhile = follow_up, True
    draft.world.frame.closed_by = "resolved"
    return draft, WorldsmithRequest(kind="meanwhile", detail=follow_up)


def _played(state: Loner4eGame) -> Loner4eGame:
    draft = state.draft()
    draft.log[-1].exchanges.append(Exchange(words="I pocket the ledger.", lines=()))
    return draft


def _closed(state: Loner4eGame) -> Loner4eGame:
    draft = _played(state)
    _ = ENGINE.close_scene(draft, CloseScene(reason="resolved"), Random(1))
    return draft


def test_a_loner_scene_with_anything_hidden_is_refused() -> None:
    with pytest.raises(ValidationError, match="hidden"):
        _ = Loner4eNext.model_validate(NEXT_SCENE | {"hidden": ["tomas"]})


@pytest.mark.parametrize(
    ("face", "kind"),
    [(1, "dramatic"), (3, "dramatic"), (4, "quiet"), (5, "quiet"), (6, "meanwhile")],
)
def test_the_transition_follows_the_srd_table(face: int, kind: str) -> None:
    assert transition_for(face) == kind


@pytest.mark.parametrize(
    ("reason", "closed_first", "refusal"),
    [("resolved", True, "has closed"), ("turning_point", False, "quiet scene only")],
)
def test_close_scene_refuses_a_closed_scene_and_a_turning_point_outside_quiet(
    reason: str, refusal: str, *, closed_first: bool
) -> None:
    _, state = initialized()
    draft = _closed(state) if closed_first else state.draft()
    with pytest.raises(Refusal, match=refusal):
        _ = ENGINE.close_scene(draft, CloseScene.model_validate({"reason": reason}), Random(0))


def test_a_quiet_scene_does_not_close_as_resolved_on_the_turn_it_opens() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.frame.kind = "quiet"

    assert "a quiet scene lasts" in refused(ENGINE, draft, "close_scene", reason="resolved")
    _ = change(ENGINE, _played(draft), "close_scene", reason="resolved")


async def test_close_scene_then_direct_in_one_turn_both_land(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(1))
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]

    _ = await play_turn(table, "I pocket the ledger.", CLOSED, DIRECTED, arrival="Frost.")

    assert table.refusals == []
    assert any(fact.card.startswith("Scene closes: resolved") for fact in table.facts)
    assert any(fact.trace.startswith("the game master directs") for fact in table.facts)


async def test_move_on_rolls_the_transition_and_the_worldsmith_writes_the_next_scene(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Dice(2))
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    table.spawner.answers["narrator"] = [narrated("Frost.")]

    await table.service.use_panel_option(MOVE_ON)

    state = table.state
    closed = state.log[-2].exchanges[-1]
    assert closed.facts[-1].card == "Scene closes: moved on. Next: dramatic"
    assert (state.world.frame.goal, state.world.scene.place_id) == (GOAL, "cloister")


async def test_end_turn_requests_the_dramatic_scene_and_the_handler_installs_its_goal() -> None:
    _, state = initialized()
    draft = _closed(state)

    ENGINE.end_turn(draft, acted=True)

    request = draft.request
    assert request is not None
    assert request == WorldsmithRequest(kind="dramatic")
    handler = ENGINE.request_handlers()[request.kind]
    _ = await handler.write(draft, request, stub_worldsmith(NEXT_SCENE))
    frame = draft.world.frame
    assert (frame.kind, frame.goal, frame.open) == ("dramatic", GOAL, True)


def test_end_turn_requests_nothing_while_a_decision_waits() -> None:
    _, state = initialized()
    draft = _closed(state)
    draft.pending = PendingDecision(kind="test", prompt="Wait?", options=(), allows_text=True)

    ENGINE.end_turn(draft, acted=True)

    assert draft.request is None


async def test_the_breather_installs_a_quiet_scene_with_full_luck_and_records_its_card(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Random(0))
    draft = table.state.draft()
    draft.world.frame.next = "quiet"
    draft.world.player.luck.current = 2
    table.service.save(draft.commit())
    assert table.service.player_view().composer_only
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE | {"goal": "Rest at the inn"})]

    state = await play_turn(table, "I rest at the inn.", DIRECTED, composer=TAKE_BREATHER)

    world = state.world
    assert (world.frame.kind, world.frame.goal) == ("quiet", "Rest at the inn")
    assert world.player.luck.shortfall == 0
    assert any(
        fact.card == f"New scene: {NEXT_SCENE['title']}"
        for exchange in state.exchanges()
        for fact in exchange.facts
    )


async def test_a_failed_write_keeps_the_close_and_the_next_turn_asks_again_with_no_new_die(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Random(1))

    failed = await play_turn(table, "I pocket the ledger.", CLOSED, DIRECTED)

    assert failed.world.frame.next == "dramatic"
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    state = await play_turn(table, "I wait.", DIRECTED, arrival="Frost.")
    assert state.world.frame.goal == GOAL
    assert not any(fact.trace.startswith("scene transition") for fact in table.facts)


async def test_loner_knows_everyone_so_no_name_is_refused_and_a_stranger_is_met() -> None:
    check_opening(_opening(goal="Find Elena"))
    _, state = initialized()
    assert all(entry.known for entry in state.world.cast.values())
    request = WorldsmithRequest(kind="dramatic")
    checked = _checking(NEXT_SCENE | {"goal": "Find Elena"})
    _ = await ENGINE.request_handlers()["dramatic"].write(_closed(state), request, checked)
    draft = state.draft()

    _ = change(ENGINE, draft, "enter", target_id="dock-guard")

    assert draft.world.require("dock-guard").known


def test_the_master_reads_whom_the_player_met_elsewhere_by_id() -> None:
    _, state = initialized()
    draft = state.draft()

    sections = dict(ENGINE.master_sections(draft))

    assert sections[ELSEWHERE_TITLE] == (
        "- Brother Tomas[tomas] — A Deaf Old Porter\n- Elena[elena] — A Ruined Archivist\n"
        "- a bloated rat[cloister-rat] — A Bloated Cloister Rat"
    )


def test_a_six_rolls_the_ally_question_and_a_second_six_reads_as_dramatic() -> None:
    _, state = initialized()
    draft = _played(state)

    facts = ENGINE.close_scene(draft, CloseScene(reason="resolved"), Dice(6, 5, 2, 6))

    assert (draft.world.frame.next, draft.world.frame.meanwhile) == ("dramatic", True)
    assert draft.world.frame.ally == "yes"
    assert all(entry.question != MEANWHILE_QUESTION for entry in draft.world.scene.settled)
    ally_card = next(fact for fact in facts if MEANWHILE_QUESTION in fact.card)
    assert ally_card.trace == OFF_SCREEN
    assert any(
        f.card.startswith("Scene closes: resolved. Next: meanwhile, then dramatic.") for f in facts
    )
    ENGINE.end_turn(draft, acted=True)
    assert draft.request == WorldsmithRequest(kind="meanwhile", detail="dramatic")


def test_doubles_on_the_ally_question_tick_the_twist_counter_for_the_worlds_turn() -> None:
    _, state = initialized()
    draft = _played(state)
    draft.world.twist.current = 2

    facts = ENGINE.close_scene(draft, CloseScene(reason="resolved"), Dice(6, 3, 3, 1, 1, 2))

    assert draft.world.twist.current == 0
    assert draft.world.frame.twist in {fact.card.removeprefix("Twist — ") for fact in facts}


@pytest.mark.parametrize(("follow_up", "scene"), [("quiet", None), ("dramatic", NEXT_SCENE)])
async def test_the_meanwhile_tells_every_update_on_one_card_and_installs_or_opens_the_breather(
    follow_up: SceneKind, scene: dict[str, object] | None
) -> None:
    draft, request = _meanwhile(follow_up)
    answer = {
        "power": [{"entity_id": TOMAS, "kind": "condition", "gained": ["Sweeping the Crypt"]}],
        "ally": {"entity_id": MARA, "kind": "condition", "gained": ["On the Trail"]},
        "scene": scene,
    }

    resolution = await ENGINE.request_handlers()["meanwhile"].write(
        draft, request, _checking(answer)
    )

    told = [fact.card for fact in resolution.facts if fact.told and fact.card]
    assert (
        told[0]
        == "Meanwhile: Brother Tomas: Now: Sweeping the Crypt\nMeanwhile: Mara: Now: On the Trail"
    )
    frame = draft.world.frame
    if scene is None:
        assert frame.breather
        assert frame.offscreen == "Brother Tomas: Now: Sweeping the Crypt; Mara: Now: On the Trail"
    else:
        assert (frame.open, frame.goal, frame.offscreen) == (True, GOAL, "")


async def test_on_a_no_the_meanwhile_refuses_an_ally_and_a_lost_tag_nobody_carries() -> None:
    draft, request = _meanwhile("quiet", ally="no")
    answer = {
        "power": [{"entity_id": TOMAS, "kind": "gear", "lost": ["Rusty Key"]}],
        "ally": {"entity_id": MARA, "kind": "condition", "gained": ["On the Trail"]},
        "scene": None,
    }

    with pytest.raises(Refusal, match=r"allies hold.*carries no gear 'Rusty Key'"):
        _ = await ENGINE.request_handlers()["meanwhile"].write(draft, request, _checking(answer))
