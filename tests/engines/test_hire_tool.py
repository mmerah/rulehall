from collections.abc import Callable
from dataclasses import dataclass
from random import Random

import pytest
from pydantic import JsonValue
from support.table import narrowed, stub_worldsmith
from support.tunnelgoons import ENGINE as TUNNELGOONS_ENGINE
from support.tunnelgoons import MIRA as TUNNELGOONS_MIRA
from support.tunnelgoons import small_world as tunnelgoons_world
from support.twentyfourxx import ENGINE as TWENTYFOURXX_ENGINE
from support.twentyfourxx import KESTREL
from support.twentyfourxx import hired as twentyfourxx_hired
from support.twentyfourxx import small_world as twentyfourxx_world

from rulehall.core.model import AnyGame, WorldsmithRequest
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.hiring import HIRE, SIGNED_ON
from rulehall.engines.tunnelgoons.world import GoonSheet, TunnelGoonsGame
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame

TERMS = "Watch our backs"


@dataclass(frozen=True, slots=True)
class HireCase:
    engine: AnyEngine
    game: Callable[[], AnyGame]  # a fresh, unhired game
    member: Slug
    sheeted: Callable[[AnyGame], AnyGame]  # the game with `member` already carrying a sheet
    answer: dict[str, JsonValue]  # the worldsmith's sheet


def _twentyfourxx_sheeted(game: AnyGame) -> AnyGame:
    return twentyfourxx_hired(narrowed(game, TwentyFourXXGame), KESTREL, skills={"Intimidation": 8})


def _tunnelgoons_sheeted(game: AnyGame) -> AnyGame:
    tunnelgoons_game = narrowed(game, TunnelGoonsGame)
    tunnelgoons_game.world.npcs[TUNNELGOONS_MIRA].sheet = GoonSheet(
        abilities={"brute": 1, "skulker": 1, "erudite": 1}
    )
    return game


# 24XX reads a pack off the game when hiring, so its case carries one.
CASES = (
    HireCase(
        engine=TWENTYFOURXX_ENGINE,
        game=twentyfourxx_world,
        member=KESTREL,
        sheeted=_twentyfourxx_sheeted,
        answer={"specialty": "Muscle", "skills": {"Intimidation": 8}, "items": ["Crowbar"]},
    ),
    HireCase(
        engine=TUNNELGOONS_ENGINE,
        game=tunnelgoons_world,
        member=TUNNELGOONS_MIRA,
        sheeted=_tunnelgoons_sheeted,
        answer={"abilities": {"brute": 2, "skulker": 1, "erudite": 0}},
    ),
)


def _case_id(case: HireCase) -> str:
    return case.engine.id


def _join_party(case: HireCase, draft: AnyGame, terms: str) -> None:
    args: dict[str, JsonValue] = {"target_id": case.member, "terms": terms}
    _ = case.engine.tools["join_party"].call(draft, args, Random(0))


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_join_party_with_terms_files_the_hire_and_without_joins_at_once(case: HireCase) -> None:
    hiring = case.game().draft()
    _join_party(case, hiring, TERMS)
    assert hiring.request == WorldsmithRequest(kind=HIRE, detail=TERMS, target_id=case.member)
    assert case.member not in hiring.world.party

    joining = case.game().draft()
    _join_party(case, joining, "")
    assert joining.request is None
    assert case.member in joining.world.party


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_hire_refuses_a_sheeted_member(case: HireCase) -> None:
    draft = case.sheeted(case.game()).draft()
    with pytest.raises(Refusal, match="already carries a sheet"):
        _join_party(case, draft, TERMS)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
async def test_advance_on_a_hire_installs_the_sheet_and_joins_the_party(case: HireCase) -> None:
    draft = case.game().draft()
    request = WorldsmithRequest(kind=HIRE, detail=TERMS, target_id=case.member)
    resolution = await case.engine.request_handlers()[HIRE].write(
        draft, request, stub_worldsmith(case.answer)
    )
    world = draft.world
    member = world.require_person_here(case.member)
    assert member.hired
    assert case.member in world.party
    assert resolution.narrator_cue == SIGNED_ON.format(name=member.name)
