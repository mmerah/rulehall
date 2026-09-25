import pytest
from support.table import LIBRARY, TWENTYFOURXX
from support.twentyfourxx import ENGINE, SCENE_BASE

from rulehall.core.model import AnyScenario, ScenarioMeta
from rulehall.core.validation import Refusal
from rulehall.engines.twentyfourxx.pack import SheetProposal
from rulehall.engines.twentyfourxx.world import Crewmate, TwentyFourXXScene

SRD = ENGINE.packs.srd()


def test_sheet_check_accepts_a_muscle_with_intimidation_and_shooting() -> None:
    proposal = SheetProposal(
        specialty="Muscle", skills={"Intimidation": 8, "Shooting": 8}, items=("Firearm",)
    )
    proposal.check((SRD,))


def test_sheet_check_refuses_an_unknown_specialty() -> None:
    proposal = SheetProposal(specialty="Wizard", skills={"Shooting": 8}, items=())
    with pytest.raises(Refusal, match="Wizard"):
        proposal.check((SRD,))


def _proposal(**fields: object) -> TwentyFourXXScene:
    return TwentyFourXXScene.model_validate(dict(SCENE_BASE) | {"ship_here": False} | fields)


def _built(proposal: TwentyFourXXScene) -> AnyScenario:
    return ENGINE.build_scenario(
        ScenarioMeta(
            title="Loading Bay", premise="", backdrop="Plain.", scope="One tense night shift."
        ),
        "srd",
        proposal,
        "",
    )


def test_new_game_marks_present_known() -> None:
    stranger = "stranger"
    proposal = _proposal(
        present=(stranger,),
        cast={stranger: Crewmate(id=stranger, name="A Stranger", brief="new to the world")},
    )
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character)
    world = ENGINE.new_game(_built(proposal), character)
    assert world.cast[stranger].known is True


def test_new_game_takes_the_job_the_opening_wrote() -> None:
    terms = "Bring the station's beacon back up before the next convoy arrives."
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character)
    world = ENGINE.new_game(_built(_proposal(job=terms)), character)
    assert world.job == terms


def test_new_game_refuses_an_opening_job_that_names_the_unmet() -> None:
    lurker = "lurker"
    proposal = _proposal(
        hidden=(lurker,),
        cast={lurker: Crewmate(id=lurker, name="Sable", brief="a rival operator")},
        job="Find Sable and take the last load back.",
    )
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character)
    with pytest.raises(Refusal, match="Sable"):
        ENGINE.new_game(_built(proposal), character)
