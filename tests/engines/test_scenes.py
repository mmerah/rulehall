from collections.abc import Sequence
from random import Random

import pytest
from support.table import (
    ENGINES_BUILT,
    LIBRARY,
    LONER3E,
    SCENARIO_MODELS,
    game,
    narrowed,
    scenario_for,
)

from rulehall.core.model import WorldsmithRequest
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.entities import PLAYER_ID, Person
from rulehall.engines.loner3e.engine import Loner3eEngine
from rulehall.engines.loner3e.world import Loner3eEntity, Loner3eGame
from rulehall.engines.scenes.engine import MOVE_ON
from rulehall.engines.scenes.world import NextProposal, Scene, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import MEANWHILE_NUDGE, check_next, check_opening

PLAYER = Person(id=PLAYER_ID, name="Player", brief="", known=True)
MARA = "mara"
SITUATION = "A long enough situation to satisfy the minimum length the model demands, twice over."
RECAP = "A long enough recap to satisfy the minimum length the model demands for what happened."
ARC = "A few lines on what waits farther in, long enough to satisfy the model's own minimum."


def _world(*scenes: Scene, **fields: object) -> SceneWorld[Person]:
    return SceneWorld[Person].model_validate({"player": PLAYER, "scenes": list(scenes), **fields})


def _scene(place: str, title: str, *, here: Sequence[Slug] = ()) -> Scene:
    return Scene(
        place_id=place,
        location="The abbey",
        title=title,
        situation=SITUATION,
        here=list(here),
    )


def _travelling() -> SceneWorld[Person]:
    """The player, one companion in the cast, and a scene the pair stand in."""
    mara = Person(id=MARA, name="Mara", brief="A guide", known=True)
    return _world(_scene("a1", "A1", here=[MARA]), cast={MARA: mara}, party=[MARA])


def test_a_party_member_leaves_the_scene_only_through_leave_party() -> None:
    world = _travelling()
    with pytest.raises(Refusal, match="leaves through `leave_party`"):
        _ = world.leave(MARA)
    assert world.present() == [MARA]


def test_killing_a_party_member_drops_them_from_the_party() -> None:
    world = _travelling()
    facts = world.kill(MARA)
    assert world.party == []
    assert not world.cast[MARA].alive
    assert any(fact.card == "Mara is dead" for fact in facts)


def test_render_next_carries_the_meanwhile_nudge_only_when_armed_and_install_clears_it() -> None:
    engine, state = game(LONER3E)
    assert isinstance(engine, Loner3eEngine)
    draft = narrowed(state, Loner3eGame).draft()

    assert MEANWHILE_NUDGE not in engine.render_next(draft, "Down the stair.").text

    draft.world.meanwhile_due = True
    assert MEANWHILE_NUDGE in engine.render_next(draft, "Down the stair.").text

    scene = NextProposal[Loner3eEntity](place_id="a2", title="A2", situation=SITUATION, recap=RECAP)
    engine.install(draft, scene)

    assert draft.world.meanwhile_due is False


def test_entering_someone_hidden_is_refused_reveal_makes_them_present() -> None:
    mara = Person(id=MARA, name="Mara", brief="A guide", known=False)
    world = _world(_scene("a1", "A1", here=[MARA]), cast={MARA: mara})
    with pytest.raises(Refusal, match="already here"):
        _ = world.enter(MARA)
    _ = world.reveal_hidden(MARA)
    assert MARA in world.present()


def test_a_next_proposal_naming_no_one_but_the_player_passes_and_installs() -> None:
    world = _world(_scene("a1", "A1"))
    proposal = NextProposal[Person](
        place_id="a2",
        title="A2",
        situation=SITUATION,
        recap=RECAP,
    )

    check_next(proposal, world, moving=True)

    world.apply_scene(proposal)

    assert world.scenes[-1].title == "A2"


def test_a_scene_keeps_its_location_until_a_departure_names_a_new_one() -> None:
    world = _world(_scene("a1", "A1"))
    stays = NextProposal[Person](place_id="a2", title="A2", situation=SITUATION, recap=RECAP)
    travels = stays.model_copy(update={"location": "The village"})

    with pytest.raises(Refusal, match="a complication happens where the player is"):
        check_next(travels, world, moving=False)
    check_next(travels, world, moving=True)
    world.apply_scene(stays)
    world.apply_scene(travels)

    assert [scene.location for scene in world.scenes] == ["The abbey", "The abbey", "The village"]


def test_an_opening_without_a_location_is_refused() -> None:
    opening = SceneProposal[Person](place_id="a1", title="A1", situation=SITUATION)
    with pytest.raises(Refusal, match="a `location`"):
        check_opening(opening)


def test_a_next_draft_whose_recap_names_a_hidden_entity_is_refused() -> None:
    mara = Person(id=MARA, name="Mara", brief="A guide", known=False)
    world = _world(_scene("a1", "A1", here=[MARA]), cast={MARA: mara})
    proposal = NextProposal[Person](
        place_id="a2",
        title="A2",
        situation=SITUATION,
        recap=f"{RECAP} Mara watched it all.",
    )

    with pytest.raises(Refusal, match="does not name what the player has not met"):
        check_next(proposal, world, moving=True)


def test_a_departure_over_an_offer_requests_the_crossing_and_leaves_the_offer() -> None:
    engine, state = game(LONER3E)
    draft = narrowed(state, Loner3eGame).draft()
    _ = engine.tools["next_scene"].call(draft, {}, Random(0))

    _ = engine.tools["next_scene"].call(draft, {"pursuit": "Down the stair."}, Random(0))

    assert draft.request is not None
    assert draft.request.detail == "Down the stair."


def test_a_scene_engine_refuses_a_request_kind_not_its_own() -> None:
    engine, state = game(LONER3E)
    draft = narrowed(state, Loner3eGame).draft()
    draft.request = WorldsmithRequest(kind="hire", detail="Hire a fixer.")

    with pytest.raises(Refusal, match="writes no 'hire'"):
        engine.validate(draft)


def test_an_action_the_scene_no_longer_offers_is_refused_and_notes_nothing() -> None:
    engine, state = game(LONER3E)
    draft = narrowed(state, Loner3eGame).draft()

    with pytest.raises(Refusal, match="the way on has changed"):
        engine.take_way_on(draft, MOVE_ON.id, "Down the stair.")

    assert draft.notes == []


def test_beginning_the_game_does_not_mutate_the_authored_scenario() -> None:
    engine = ENGINES_BUILT[LONER3E]
    scenario_id = scenario_for(LONER3E)
    scenario = LIBRARY.read_scenario(scenario_id, SCENARIO_MODELS)
    before = scenario.opening.model_dump()
    character = LIBRARY.read_character("kael", engine.id, engine.character)
    draft = engine.begin(scenario_id, scenario, character)
    world = narrowed(draft, Loner3eGame).world

    world.cast[MARA].name = "Someone else"

    assert scenario.opening.model_dump() == before
