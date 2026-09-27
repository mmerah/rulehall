import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pytest
from pydantic import BaseModel
from support.game import ENGINE as LONER4E_ENGINE
from support.game import MARA, TOMAS, initialized
from support.game import SITUATION as LONER4E_SITUATION
from support.table import narrowed
from support.twentyfourxx import ENGINE as TWENTYFOURXX_ENGINE
from support.twentyfourxx import KESTREL, SABLE
from support.twentyfourxx import SCENE_BASE as TWENTYFOURXX_BASE
from support.twentyfourxx import small_world as twentyfourxx_world

from rulehall.core.model import AnyGame
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.entities import PLAYER_ID, Person
from rulehall.engines.loner4e.engine import Loner4eEngine
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.loner4e.world import Loner4eWorld
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import check_next
from rulehall.engines.twentyfourxx.engine import TwentyFourXXEngine
from rulehall.engines.twentyfourxx.sheet import Crewmate
from rulehall.engines.twentyfourxx.world import TwentyFourXXWorld

BAR_RECAP = "They moved on."
DECOY_CAST_ENTRY = {"id": PLAYER_ID, "name": "Someone", "brief": "filed wrongly", "known": True}
LONER4E_BASE: Mapping[str, object] = {
    "place_id": "cloister",
    "location": "The abbey",
    "title": "The Cloister",
    "situation": LONER4E_SITUATION,
    "arc": "Farther along, the stair still leads down to what Tomas would not speak of.",
}


@dataclass(frozen=True, slots=True)
class SceneCase:
    engine: Loner4eEngine | TwentyFourXXEngine
    game: Callable[[], AnyGame]
    base: Mapping[str, object]  # the draft fields every scene of this case starts from
    bar: Callable[[Mapping[str, object]], None]
    apply: Callable[[AnyGame, Mapping[str, object]], None]
    player: str
    met: Slug
    unmet: Slug


def _draft[P: BaseModel](
    draft_type: type[P], base: Mapping[str, object]
) -> Callable[[Mapping[str, object]], P]:
    """The case's draft shape over its base fields; every helper below builds one."""
    return lambda fields: draft_type.model_validate(dict(base) | dict(fields))


def _bar[C: Person](
    draft_type: type[NextProposal[C]],
    world: type[SceneWorld[C]],
    base: Mapping[str, object],
    game: Callable[[], AnyGame],
) -> Callable[[Mapping[str, object]], None]:
    draft = _draft(draft_type, {**base, "recap": BAR_RECAP})

    def bar(fields: Mapping[str, object]) -> None:
        check_next(draft(fields), narrowed(game().world, world))

    return bar


def _apply[C: Person](
    draft_type: type[SceneProposal[C]], base: Mapping[str, object]
) -> Callable[[AnyGame, Mapping[str, object]], None]:
    """`case.bar`'s counterpart: hands the same draft shape to a real world's `apply_scene`."""
    draft = _draft(draft_type, base)

    def apply(state: AnyGame, fields: Mapping[str, object]) -> None:
        state.world.apply_scene(draft(fields))

    return apply


CASES = (
    SceneCase(
        engine=TWENTYFOURXX_ENGINE,
        game=twentyfourxx_world,
        base=TWENTYFOURXX_BASE,
        bar=_bar(NextProposal[Crewmate], TwentyFourXXWorld, TWENTYFOURXX_BASE, twentyfourxx_world),
        apply=_apply(SceneProposal[Crewmate], TWENTYFOURXX_BASE),
        player="Rook",
        met=KESTREL,
        unmet=SABLE,
    ),
    SceneCase(
        engine=LONER4E_ENGINE,
        game=lambda: initialized()[1],
        base=LONER4E_BASE,
        bar=_bar(NextProposal[Loner4eEntity], Loner4eWorld, LONER4E_BASE, lambda: initialized()[1]),
        apply=_apply(SceneProposal[Loner4eEntity], LONER4E_BASE),
        player="Kael",
        met=MARA,
        unmet=TOMAS,
    ),
)


def _case_id(case: SceneCase) -> str:
    return case.engine.id


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_a_scene_that_lists_the_player_passes_the_bar_and_code_drops_the_player(
    case: SceneCase,
) -> None:
    fields = {"present": (case.player, case.met)}
    case.bar(fields)
    state = case.game()
    case.apply(state, fields)
    assert state.world.scene.here == [case.met]


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_the_bar_refuses_a_draft_cast_entry_under_player_id(case: SceneCase) -> None:
    with pytest.raises(Refusal, match="rewrites the player"):
        case.bar({"cast": {PLAYER_ID: DECOY_CAST_ENTRY}})


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_the_bar_refuses_hiding_someone_met(case: SceneCase) -> None:
    with pytest.raises(Refusal, match="already met"):
        case.bar({"hidden": (case.met,)})


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_a_dead_draft_cast_member_is_refused(case: SceneCase) -> None:
    ghost = {"id": "ghost", "name": "Ghost", "brief": "", "alive": False}
    with pytest.raises(Refusal, match="may write them"):
        case.bar({"present": (case.met,), "cast": {"ghost": ghost}})


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_the_bar_refuses_present_hidden_overlap(case: SceneCase) -> None:
    message = f"nobody listed as both present and hidden: ['{case.unmet}']"
    with pytest.raises(Refusal, match=re.escape(message)):
        case.bar({"present": (case.unmet,), "hidden": (case.unmet,)})


def test_a_situation_naming_an_unmet_cast_member_not_in_this_scene_is_refused() -> None:
    case = CASES[0]  # Loner has no one unmet
    name = case.game().world.cast[case.unmet].name
    with pytest.raises(Refusal, match="does not name"):
        case.bar({"situation": f"{case.base['situation']} {name} is spoken of."})


def test_a_party_members_stored_brief_naming_an_absent_unmet_neighbour_is_accepted() -> None:
    """An old brief naming someone unmet outside this scene must not wedge every later one."""
    world = twentyfourxx_world().world
    world.cast[KESTREL].brief = "She is watching for Sable."
    world.join_party(KESTREL)
    proposal = NextProposal[Crewmate].model_validate({**TWENTYFOURXX_BASE, "recap": BAR_RECAP})
    check_next(proposal, world)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_a_game_naming_an_uninstalled_pack_is_refused_by_restore(case: SceneCase) -> None:
    stale = case.game().model_copy(update={"pack_id": "gone"})
    with pytest.raises(Refusal, match="is not installed"):
        _ = case.engine.restore(stale.model_dump_json())


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_apply_scene_resolves_present_by_name(case: SceneCase) -> None:
    state = case.game()
    name = state.world.cast[case.unmet].name
    case.apply(state, {"present": (name,)})
    assert case.unmet in state.world.present()


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_apply_scene_marks_present_cast_known(case: SceneCase) -> None:
    state = case.game()
    case.apply(state, {"present": (str(case.unmet),)})
    assert state.world.cast[case.unmet].known is True


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_apply_scene_lands_new_cast(case: SceneCase) -> None:
    state = case.game()
    stranger = "stranger"
    case.apply(
        state,
        {
            "present": (str(case.met), stranger),
            "cast": {
                stranger: {"id": stranger, "name": "A Stranger", "brief": "unknown to the world"}
            },
        },
    )
    assert stranger in state.world.cast


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_apply_scene_refuses_a_present_name_that_resolves_to_nobody(case: SceneCase) -> None:
    state = case.game()
    with pytest.raises(Refusal, match="no such id or name exists"):
        case.apply(state, {"present": ("nobody",)})


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_an_entity_is_never_lost_when_a_scene_leaves_it_behind(case: SceneCase) -> None:
    state = case.game()
    left_title = state.world.scene.title
    scenes_before = len(state.world.scenes)
    case.apply(state, {})
    assert state.world.last_seen(case.met) == f"last seen in: {left_title}"
    assert case.met in state.world.cast
    assert len(state.world.scenes) == scenes_before + 1


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_a_cast_that_holds_the_player_is_refused(case: SceneCase) -> None:
    world = case.game().world
    decoy = world.cast[case.met].model_copy(update={"id": PLAYER_ID})
    with pytest.raises(ValueError, match="the player is in the cast"):
        type(world)(**(dict(world) | {"cast": {**world.cast, PLAYER_ID: decoy}}))


def test_require_actor_refuses_an_unsheeted_member() -> None:
    world = twentyfourxx_world().world
    world.party = [KESTREL]
    with pytest.raises(Refusal, match="not the player or a hired party member"):
        world.require_actor(KESTREL)
