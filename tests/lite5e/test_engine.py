from pathlib import Path
from random import Random

import pytest
from support.lite5e import BANDITS, GATE, hero, person, sheet_proposal, world

from rulehall.core.game import ScenarioDescription
from rulehall.core.validation import Refusal, parse
from rulehall.engines.args import HireOrJoin, LeaveParty
from rulehall.engines.lite5e.args import GiveReward, LevelPick
from rulehall.engines.lite5e.data import TimedCondition
from rulehall.engines.lite5e.engine import Lite5eEngine
from rulehall.engines.lite5e.hire import HireAnswer, SheetProposal, StatBlockHire
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


def test_a_follower_cannot_be_hired_past_the_two_companions(engine: Lite5eEngine) -> None:
    draft = _game(engine, world(*(person(person_id, GATE) for person_id in ("a", "b", "c"))))
    for person_id in ("a", "b"):
        hired = draft.world.npcs[person_id]
        draft.world.join(hired)
        _ = engine.sign_on(draft, hired, HireAnswer(hire=StatBlockHire(kind="stat_block")))
    _ = engine.join_party(draft, HireOrJoin(target_id="c"), Random(1))

    with pytest.raises(Refusal, match="2 hired companions at most"):
        _ = engine.join_party(draft, HireOrJoin(target_id="c", terms="pay"), Random(1))


def test_a_companion_who_rejoins_comes_up_to_the_party_level(engine: Lite5eEngine) -> None:
    draft = _game(engine, world(person("ally", GATE)))
    ally = draft.world.npcs["ally"]
    _ = draft.world.join(ally)
    hire = HireAnswer(hire=sheet_proposal("fighter", "human", "soldier"))
    _ = engine.sign_on(draft, ally, hire)
    _ = engine.leave_party(draft, LeaveParty(target_id="ally"), Random(1))
    draft.world.player.require_sheet().xp = 300
    _ = draft.world.level_up()

    _ = engine.join_party(draft, HireOrJoin(target_id="ally"), Random(1))

    assert ally.require_sheet().level == draft.world.party_level() == 2


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


def test_a_hire_with_some_scores_is_refused() -> None:
    proposal = sheet_proposal("wizard", "elf", "sage", subspecies_id="elven-lineage-high-elf")

    with pytest.raises(Refusal, match="six abilities"):
        _ = parse(SheetProposal, {**proposal.model_dump(), "scores": {"strength": 15}})


def test_a_hire_with_a_gear_category_its_class_lacks_is_refused(engine: Lite5eEngine) -> None:
    draft = _game(engine, world(person("ally", GATE)))
    ally = draft.world.npcs["ally"]
    proposal = sheet_proposal("fighter", "human", "soldier")
    hire = proposal.model_copy(update={"category_gear_ids": {"holy-symbols": "amulet"}})

    with pytest.raises(Refusal, match="no gear category"):
        _ = engine.sign_on(draft, ally, HireAnswer(hire=hire))
