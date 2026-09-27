from random import Random

from support.game import ENGINE, MARA, initialized
from support.table import run_action, stub_worldsmith

from rulehall.core.creation import option_of
from rulehall.core.model import WorldsmithRequest
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner4e.args import RECOVER, STATUS_PROMPT, Ask, SpendLuck
from rulehall.engines.loner4e.panels import sheet_panel
from rulehall.engines.loner4e.rules import LUCK_MAX

QUIET_SCENE: dict[str, object] = {
    "place_id": "cloister",
    "title": "The Cloister",
    "situation": "A frost-rimed colonnade around a dead garden, unswept for a long while.",
    "recap": "He limped out of the study.",
    "goal": "Bind the wound",
    "details": ["Frost-Rimed Colonnade"],
}


async def test_a_defeat_fills_the_picked_box_and_only_a_recovery_scene_clears_one() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.pack_id = "ap01-fantasy"
    world = draft.world
    world.status.boxes = ["Hurt"]
    duel = Ask(question="Does he force her back from the door?", against_id=MARA)
    _ = ENGINE.ask(draft, duel, Random(0))
    spent = SpendLuck(actor_id=PLAYER_ID, amount=LUCK_MAX, why="A bolt")

    _ = ENGINE.spend_luck(draft, spent, Random(0))

    decision = draft.pending
    assert decision is not None
    assert decision.prompt == STATUS_PROMPT
    social = option_of(decision.options, "social")
    assert social is not None
    draft.pending = None
    _ = ENGINE.play_option(draft, social, Random(0))
    assert world.status.boxes == ["Hurt", "On the Back Foot"]

    world.frame.next = "quiet"
    planning = WorldsmithRequest(kind="quiet", detail="I plan the way in.")
    _ = await ENGINE.request_handlers()["quiet"].write(
        draft, planning, stub_worldsmith(QUIET_SCENE)
    )
    assert world.status.boxes == ["Hurt", "On the Back Foot"]

    world.frame.next = "quiet"
    assert any(RECOVER in row.options for row in sheet_panel(world).rows)
    _ = run_action(ENGINE, draft, "recover")
    request = draft.request
    assert request is not None
    _ = await ENGINE.request_handlers()[request.kind].write(
        draft, request, stub_worldsmith(QUIET_SCENE)
    )
    assert world.status.boxes == ["Hurt"]
