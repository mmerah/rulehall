from collections.abc import Sequence

import pytest
from support.table import (
    ENGINES_BUILT,
    LIBRARY,
    LONER4E,
    SCENARIO_MODELS,
    game,
    narrowed,
    scenario_for,
)

from rulehall.core.model import WorldsmithRequest
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.entities import PLAYER_ID, Person
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.scenes.world import NextProposal, Scene, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import check_next, check_opening

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


def test_only_leave_party_takes_a_member_out_and_an_unknown_leave_is_nothing() -> None:
    world = _travelling()
    with pytest.raises(Refusal, match="leaves through `leave_party`"):
        _ = world.leave(MARA)
    assert world.present() == [MARA]
    assert world.leave("nobody-filed") == []


def test_killing_a_party_member_drops_them_from_the_party() -> None:
    world = _travelling()
    facts = world.kill(MARA)
    assert world.party == []
    assert not world.cast[MARA].alive
    assert any(fact.card == "Mara is dead" for fact in facts)


def test_entering_someone_hidden_is_refused_and_entering_them_once_revealed_is_nothing() -> None:
    mara = Person(id=MARA, name="Mara", brief="A guide", known=False)
    world = _world(_scene("a1", "A1", here=[MARA]), cast={MARA: mara})
    with pytest.raises(Refusal, match="hidden here"):
        _ = world.enter(MARA)
    _ = world.reveal_hidden(MARA)
    assert MARA in world.present()
    assert world.enter(MARA) == []


def test_a_next_proposal_naming_no_one_but_the_player_passes_and_installs() -> None:
    world = _world(_scene("a1", "A1"))
    proposal = NextProposal[Person](
        place_id="a2",
        title="A2",
        situation=SITUATION,
        recap=RECAP,
    )

    check_next(proposal, world)

    world.apply_scene(proposal)

    assert world.scenes[-1].title == "A2"


def test_a_scene_keeps_its_location_until_a_next_scene_names_a_new_one() -> None:
    world = _world(_scene("a1", "A1"))
    stays = NextProposal[Person](place_id="a2", title="A2", situation=SITUATION, recap=RECAP)
    travels = stays.model_copy(update={"location": "The village"})

    check_next(travels, world)
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
        check_next(proposal, world)


def test_a_scene_engine_refuses_a_request_kind_not_its_own() -> None:
    engine, state = game(LONER4E)
    draft = narrowed(state, Loner4eGame).draft()
    draft.request = WorldsmithRequest(kind="hire", detail="Hire a fixer.")

    with pytest.raises(Refusal, match="writes no 'hire'"):
        engine.validate(draft)


def test_beginning_the_game_does_not_mutate_the_authored_scenario() -> None:
    engine = ENGINES_BUILT[LONER4E]
    scenario_id = scenario_for(LONER4E)
    scenario = LIBRARY.read_scenario(scenario_id, SCENARIO_MODELS)
    before = scenario.opening.model_dump()
    character = LIBRARY.read_character("kael", engine.id, engine.character)
    draft = engine.begin(scenario_id, scenario, character)
    world = narrowed(draft, Loner4eGame).world

    world.cast[MARA].name = "Someone else"

    assert scenario.opening.model_dump() == before
