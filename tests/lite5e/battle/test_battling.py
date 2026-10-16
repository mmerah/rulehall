import re
from collections.abc import Sequence
from pathlib import Path
from random import Random

import pytest
from pydantic import BaseModel
from support.golden import FIXTURES, golden
from support.lite5e import GATE, ScriptedDice, hero, person, sheet_proposal, world
from support.table import open_table

from rulehall.core.facts import Fact
from rulehall.core.game import Check, RoleAnswer, ScenarioDescription
from rulehall.core.prompt import Prompt
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.lite5e.args import StartBattle
from rulehall.engines.lite5e.battle import battling
from rulehall.engines.lite5e.battle.aftermath import start_battle
from rulehall.engines.lite5e.battle.battling import Lite5eRun
from rulehall.engines.lite5e.battle.state import Battle, Fight
from rulehall.engines.lite5e.sheet import Lite5ePerson
from rulehall.engines.lite5e.world import Lite5eGame

LITE5E = EngineId("lite5e")
BANDITS = "bandits"
PLAYER_FIRST = 0
FOES_FIRST = 1


class Asked:
    def __init__(self) -> None:
        self.prompts: list[Prompt] = []

    def refusing(self) -> RoleAnswer:
        async def refused[M: BaseModel](prompt: Prompt, _model: type[M], _check: Check[M]) -> M:
            self.prompts.append(prompt)
            raise Refusal("the opponent answered nothing usable")

        return refused


async def test_a_refusal_from_choose_closes_the_run_and_a_new_run_opens_over_the_same_battle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_fight: Fight) -> list[Fact]:
        raise Refusal("the turn cannot end")

    table = open_table(tmp_path, engine_id=LITE5E, state_type=Lite5eGame)
    begun = table.state.draft()
    begun.world = _game(PLAYER_FIRST).world
    table.session.save(begun)
    await table.session.open_battle(ask_opponent=False)
    monkeypatch.setattr(battling, "end_turn", refused)

    with pytest.raises(Refusal, match="cannot end"):
        await table.session.battle_command("end")

    assert table.session.battle_run is None
    log = _battle(table.state).log()
    await table.session.open_battle(ask_opponent=False)
    run = table.session.battle_run
    assert run is not None
    assert list(run.log(table.state)) == log


async def test_after_the_battle_is_settled_the_run_reads_the_settled_battle() -> None:
    draft = _game(PLAYER_FIRST)
    run = Lite5eRun.start(draft, None)

    await run.choose(draft, "surrender", Random(1))

    assert draft.world.battle is None
    assert run.resolution is not None
    assert run.settled is not None
    assert run.resolution.facts[0].trace == "The party yields"
    assert run.facts(draft) == run.settled.facts
    view = run.view(draft)
    assert view.choices == ()
    assert [card.combatant_id for card in view.foes] == ["bandits-1", "bandits-2"]


async def test_a_refusal_from_the_opponent_falls_back_to_the_scripted_plans() -> None:
    draft = _game(FOES_FIRST)
    asked = Asked()
    run = Lite5eRun.start(draft, asked.refusing())

    await run.choose(draft, "next", Random(3))

    assert len(asked.prompts) == 1
    assert not run.thinking
    assert _battle(draft).turn_index == 1


async def test_a_reload_in_the_middle_of_a_block_plays_on_from_the_pending_plans() -> None:
    draft = _game(FOES_FIRST)
    await Lite5eRun.start(draft, None).choose(draft, "next", Random(3))
    assert "bandits-2" in _battle(draft).pending_plans
    asked = Asked()
    reopened = Lite5eRun.start(draft.draft(), asked.refusing())
    reloaded = draft.draft()

    await reopened.choose(reloaded, "next", Random(3))

    assert asked.prompts == []
    assert "bandits-2" not in _battle(reloaded).pending_plans


async def test_a_recorded_battle_keeps_its_fact_log() -> None:
    draft = _game(PLAYER_FIRST, count=1)
    run = Lite5eRun.start(draft, None)
    rng = Random(1)
    shown = 0
    while run.resolution is None:
        shown = len(run.facts(draft))
        commands = [choice.command for choice in run.view(draft).choices]
        await run.choose(draft, _scripted_command(commands), rng)

    told = [*run.facts(draft)[:shown], *run.resolution.facts]
    lines = [fact.card for fact in told if fact.told and fact.card]
    golden(FIXTURES / "battles" / "lite5e" / "victory.txt", "\n".join(lines) + "\n")


def _scripted_command(commands: Sequence[str]) -> str:
    for wanted in ("next", "target bandits", "act longsword"):
        found = next((command for command in commands if command.startswith(wanted)), None)
        if found is not None:
            return found
    return "end"


def _game(seed: int, *, count: int = 2) -> Lite5eGame:
    game = _keep(person(BANDITS, GATE, "bandit", count=count, hostile=True))
    args = StartBattle(foe_ids=(BANDITS,), opening="face_to_face")
    _ = start_battle(game.world, args, Random(seed))
    return game


def _keep(*npcs: Lite5ePerson) -> Lite5eGame:
    player = hero(sheet_proposal("fighter"))
    sheet = player.require_sheet()
    sheet.add_gear("longsword", 1)
    sheet.equipped_ids.append("longsword")
    return Lite5eGame(
        scenario_id="keep",
        character_id="hero",
        scenario_description=ScenarioDescription(
            title="The keep", premise="", backdrop="An old keep", scope="One night"
        ),
        engine_id=LITE5E,
        pack_id="srd",
        extra_pack_ids=(),
        world=world(*npcs, player=player),
    )


def _battle(state: Lite5eGame) -> Battle:
    assert state.world.battle is not None
    return state.world.battle


def test_a_battle_that_ends_at_its_opening_has_its_resolution_when_the_run_is_built() -> None:
    bandits = person(BANDITS, GATE, "bandit", count=2, hostile=True)
    bandits.routed = True
    bandits.xp_paid = True
    game = _keep(bandits)
    args = StartBattle(foe_ids=(BANDITS,), opening="face_to_face")
    _ = start_battle(game.world, args, ScriptedDice(1, 1, 10, 10))
    assert game.world.battle is not None

    run = Lite5eRun.start(game, None)

    assert run.resolution is not None
    assert game.world.battle is None


async def test_the_opponent_s_line_shows_in_the_battle_log() -> None:
    draft = _game(FOES_FIRST)

    async def speaking[M: BaseModel](prompt: Prompt, model: type[M], _check: Check[M]) -> M:
        commands = re.findall(r"^For .*:\n- (.+)$", prompt.user, re.MULTILINE)
        return model.model_validate({"commands": tuple(commands), "line": "You will fall here."})

    run = Lite5eRun.start(draft, speaking)
    await run.choose(draft, "next", Random(3))

    assert any(line.endswith(': "You will fall here."') for line in run.log(draft))
