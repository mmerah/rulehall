from pathlib import Path
from random import Random

from support.pokemon import ENGINE
from support.showdown import ScriptedSimulator, ended, moving, started
from support.table import POKEMON, narrated, open_table, play_turn, tool_call

from rulehall.app.turn import BATTLE_WAIT
from rulehall.engines.engine import AnyEngine
from rulehall.engines.pokemon.world import PokemonGame


class LowRandom(Random):
    def randint(self, a: int, b: int) -> int:
        return min(a, b)


async def test_a_wild_battle_hands_off_to_the_battle_screen_and_back(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame, rng=Random(1))
    _ = await play_turn(
        table,
        "I walk into the tall grass.",
        tool_call("start_wild_battle", species_id="pidgey"),
        tool_call("direct", text="A wild Pidgey flies at the player."),
        narration="A wild Pidgey bursts out of the grass.",
        then=(narrated("You slip away from the Pidgey."),),
    )
    assert table.answers[-1] == BATTLE_WAIT
    battle = table.state.world.battle
    assert battle is not None
    simulator = ScriptedSimulator(started(battle.setup) + ended(battle.setup, foe_hp=10))

    async def start(_engine: AnyEngine) -> ScriptedSimulator:
        return simulator

    table.service.start_transport = start
    await table.service.open_battle()
    await table.service.battle_command("leave")

    assert table.state.world.battle is None
    assert table.state.exchanges()[-1].cause == "battle"
    assert simulator.closed


async def test_a_caught_pokemon_joins_the_team(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame, rng=Random(1))
    _ = await play_turn(
        table,
        "I walk into the tall grass.",
        tool_call("start_wild_battle", species_id="pidgey"),
        tool_call("direct", text="A wild Pidgey flies at the player."),
        narration="A wild Pidgey bursts out of the grass.",
        then=(narrated("The Pidgey is caught."),),
    )
    battle = table.state.world.battle
    assert battle is not None
    setup = battle.setup
    simulator = ScriptedSimulator(started(setup) + moving(setup) + ended(setup, foe_hp=10))

    async def start(_engine: AnyEngine) -> ScriptedSimulator:
        return simulator

    table.service.start_transport = start
    await table.service.open_battle()
    await table.service.battle_command("team 1")
    table.service.rng = LowRandom()
    await table.service.battle_command("ball poke-ball")

    assert len(table.state.world.player.require_sheet().team) == 2
    assert table.state.world.battle is None


async def test_a_save_with_a_caught_throw_ends_the_battle_on_reopen(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame, rng=Random(1))
    _ = await play_turn(
        table,
        "I walk into the tall grass.",
        tool_call("start_wild_battle", species_id="pidgey"),
        tool_call("direct", text="A wild Pidgey flies at the player."),
        narration="A wild Pidgey bursts out of the grass.",
    )
    battle = table.state.world.battle
    assert battle is not None
    setup = battle.setup
    draft = table.state.draft()
    _ = ENGINE.throw_ball(draft, "poke-ball", setup.foes[0], LowRandom())
    table.service.save(table.service.engine.accept(draft))
    reopened = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    reopened.spawner.answers.setdefault("narrator", []).append(narrated("The Pidgey is caught."))
    simulator = ScriptedSimulator(started(setup) + ended(setup, foe_hp=10))

    async def start(_engine: AnyEngine) -> ScriptedSimulator:
        return simulator

    reopened.service.start_transport = start
    await reopened.service.open_battle()

    assert reopened.state.world.battle is None
    assert len(reopened.state.world.player.require_sheet().team) == 2
