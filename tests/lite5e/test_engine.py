from pathlib import Path
from random import Random

import pytest
from support.lite5e import BANDITS, GATE, hero, person, sheet_proposal, world

from rulehall.core.game import ScenarioDescription
from rulehall.core.validation import Refusal
from rulehall.engines.args import HireOrJoin
from rulehall.engines.lite5e.args import GiveReward, LevelPick
from rulehall.engines.lite5e.data import TimedCondition
from rulehall.engines.lite5e.engine import Lite5eEngine
from rulehall.engines.lite5e.sheet import Lite5ePerson
from rulehall.engines.lite5e.world import Lite5eGame, Lite5eWorld
from rulehall.engines.sheet import PLAYER_ID


@pytest.fixture
def engine(tmp_path: Path) -> Lite5eEngine:
    return Lite5eEngine(tmp_path)


def _game(engine: Lite5eEngine, played: Lite5eWorld) -> Lite5eGame:
    return Lite5eGame(
        scenario_id="keep",
        character_id="hero",
        scenario_description=ScenarioDescription(
            title="The keep", premise="", backdrop="An old keep", scope="One night"
        ),
        engine_id=engine.id,
        pack_id="srd",
        extra_pack_ids=(),
        world=played,
    )


def test_a_group_never_joins_whole(engine: Lite5eEngine) -> None:
    draft = _game(engine, world(person(BANDITS, GATE, "bandit", count=2)))

    _ = engine.join_party(draft, HireOrJoin(target_id=BANDITS), Random(1))

    assert draft.world.party_ids == [f"{BANDITS}-2"]


def test_a_level_up_is_written_back(engine: Lite5eEngine) -> None:
    wizard = hero(sheet_proposal("wizard", "human", "sage"))
    draft = _game(engine, world(player=wizard))
    draft.world.goals["clear-crypt"] = draft.world.goals["clear-crypt"].model_copy(
        update={"size": "high"}
    )
    draft.world.player.require_sheet().xp = 250
    draft.world.player.conditions.append(TimedCondition(condition="poisoned", tier="long-rest"))
    assert engine.grown_character(draft) is None

    reward = GiveReward.model_validate({"reward": {"kind": "goal", "goal_id": "clear-crypt"}})
    facts = engine.reward(draft, reward, Random(1))
    engine.after_each_change(draft)
    while draft.pending is not None and draft.pending.kind == "level-up":
        option = draft.pending.options[0]
        _ = engine.level_pick(draft, LevelPick.model_validate(option.args), Random(1))
        engine.after_each_change(draft)

    grown = engine.grown_character(draft)
    assert facts
    assert grown is not None
    assert isinstance(grown.person, Lite5ePerson)
    assert grown.person.id == PLAYER_ID
    assert grown.person.conditions == []
    sheet = grown.person.require_sheet()
    assert sheet.level == 2
    assert len(sheet.pick_ids("spellbook")) == 8


def _rewarded(engine: Lite5eEngine, draft: Lite5eGame, **reward: object) -> None:
    _ = engine.reward(draft, GiveReward.model_validate({"reward": reward}), Random(1))


def test_a_coin_change_gives_takes_and_never_goes_below_zero(engine: Lite5eEngine) -> None:
    draft = _game(engine, world())
    sheet = draft.world.player.require_sheet()
    sheet.coins_cp = 500

    _rewarded(engine, draft, kind="coins", cp=300, reason="a bounty")
    _rewarded(engine, draft, kind="coins", cp=-700, reason="a bribe")

    assert sheet.coins_cp == 100
    with pytest.raises(Refusal, match="holds only"):
        _rewarded(engine, draft, kind="coins", cp=-200, reason="a toll")
    assert sheet.coins_cp == 100
