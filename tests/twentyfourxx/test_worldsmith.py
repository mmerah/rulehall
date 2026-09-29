import pytest
from support.table import LIBRARY, TWENTYFOURXX
from support.twentyfourxx import ENGINE, SCENE_BASE

from rulehall.core.game import AnyScenario, ScenarioDescription
from rulehall.core.validation import Refusal
from rulehall.engines.twentyfourxx.sheet import Crewmate
from rulehall.engines.twentyfourxx.world import TwentyFourXXSceneProposal

SRD = ENGINE.packs.srd()


def _proposal(**fields: object) -> TwentyFourXXSceneProposal:
    return TwentyFourXXSceneProposal.model_validate(dict(SCENE_BASE) | fields)


def _built(proposal: TwentyFourXXSceneProposal) -> AnyScenario:
    return ENGINE.scenario_model(
        description=ScenarioDescription(
            title="Loading Bay", premise="", backdrop="Plain.", scope="One tense night shift."
        ),
        engine_id=ENGINE.id,
        pack_id="srd",
        source="",
        opening=proposal,
    )


def test_new_game_files_the_cast_by_name() -> None:
    proposal = _proposal(
        present_ids=("stranger",),
        cast={"stranger": Crewmate(id="stranger", name="Bray Kell", brief="new to the world")},
    )
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character_model)
    world = ENGINE.new_game(_built(proposal), character)
    assert list(world.cast) == ["bray-kell"]
    assert world.cast["bray-kell"].known is True


def test_new_game_takes_the_job_the_opening_wrote() -> None:
    terms = "Bring the station's beacon back up before the next convoy arrives."
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character_model)
    world = ENGINE.new_game(_built(_proposal(job=terms)), character)
    assert world.job == terms


def test_new_game_refuses_an_opening_job_that_names_the_unmet() -> None:
    lurker = "lurker"
    proposal = _proposal(
        hidden_ids=(lurker,),
        cast={lurker: Crewmate(id=lurker, name="Sable", brief="a rival operator")},
        job="Find Sable and take the last load back.",
    )
    character = LIBRARY.read_character("kael", TWENTYFOURXX, ENGINE.character_model)
    with pytest.raises(Refusal, match="Sable"):
        ENGINE.new_game(_built(proposal), character)
