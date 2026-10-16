from pathlib import Path
from random import Random

import pytest
from support.journey import into_wild_battle
from support.showdown import ScriptedSimulator, ended, moving, simulator_assets, started
from support.table import POKEMON, narrated, open_table

from rulehall.app.turn import BATTLE_WAIT
from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.journey.world import JourneyGame

__all__ = ["simulator_assets"]


class LowRandom(Random):
    def randint(self, a: int, b: int) -> int:
        return min(a, b)


@pytest.mark.usefixtures("simulator_assets")
async def test_a_wild_battle_hands_off_to_the_battle_screen_and_back(tmp_path: Path) -> None:
    table = await into_wild_battle(tmp_path, "You slip away from the Pidgey.")
    assert table.answers[-1] == BATTLE_WAIT
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup) + ended(battle.setup, foe_hp=10))

    async def start(_argv: tuple[str, ...]) -> ScriptedSimulator:
        return simulator

    table.session.start_transport = start
    await table.session.open_battle(ask_opponent=True)
    await table.session.battle_command("leave")

    assert table.state.world.battle is None
    assert table.state.log_entries()[-1].cause == "battle"
    assert simulator.closed


@pytest.mark.usefixtures("simulator_assets")
async def test_a_command_the_run_does_not_offer_is_refused_and_the_run_stays_open(
    tmp_path: Path,
) -> None:
    table = await into_wild_battle(tmp_path)
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup))

    async def start(_argv: tuple[str, ...]) -> ScriptedSimulator:
        return simulator

    table.session.start_transport = start
    await table.session.open_battle(ask_opponent=True)

    with pytest.raises(Refusal, match="not a choice now"):
        await table.session.battle_command("move 9")

    assert table.session.battle_run is not None
    assert not simulator.closed


@pytest.mark.usefixtures("simulator_assets")
async def test_a_caught_pokemon_joins_the_team(tmp_path: Path) -> None:
    table = await into_wild_battle(tmp_path, "The Pidgey is caught.")
    battle = table.state.world.battle
    assert battle is not None
    setup = battle.setup
    simulator = ScriptedSimulator(started(setup) + moving(setup) + ended(setup, foe_hp=10))

    async def start(_argv: tuple[str, ...]) -> ScriptedSimulator:
        return simulator

    table.session.start_transport = start
    await table.session.open_battle(ask_opponent=True)
    await table.session.battle_command("team 1")
    table.session.rng = LowRandom()
    await table.session.battle_command("ball poke-ball")

    assert len(table.state.world.player.require_sheet().team) == 2
    assert table.state.world.battle is None


@pytest.mark.usefixtures("simulator_assets")
async def test_a_save_with_a_caught_throw_ends_the_battle_on_reopen(tmp_path: Path) -> None:
    table = await into_wild_battle(tmp_path)
    battle = table.state.world.battle
    assert battle is not None
    setup = battle.setup
    draft = table.state.draft()
    _ = draft.world.throw_ball("poke-ball", setup.foes[0], LowRandom())
    table.session.save(table.session.engine.accept(draft))
    reopened = open_table(tmp_path, engine_id=POKEMON, state_type=JourneyGame)
    reopened.roles.answers.setdefault("narrator", []).append(narrated("The Pidgey is caught."))
    simulator = ScriptedSimulator(started(setup) + ended(setup, foe_hp=10))

    async def start(_argv: tuple[str, ...]) -> ScriptedSimulator:
        return simulator

    reopened.session.start_transport = start
    await reopened.session.open_battle(ask_opponent=True)

    assert reopened.state.world.battle is None
    assert len(reopened.state.world.player.require_sheet().team) == 2


@pytest.mark.usefixtures("simulator_assets")
async def test_a_battle_command_after_the_game_ended_is_refused(tmp_path: Path) -> None:
    table = await into_wild_battle(tmp_path)
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup))

    async def start(_argv: tuple[str, ...]) -> ScriptedSimulator:
        return simulator

    table.session.start_transport = start
    await table.session.open_battle(ask_opponent=True)
    table.state.world.evil_team.boss_beaten = True

    with pytest.raises(Refusal, match="the game is over"):
        await table.session.battle_command("leave")
