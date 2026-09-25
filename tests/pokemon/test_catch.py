from random import Random

import pytest
from support.pokemon import ENGINE, started
from support.table import change

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import Status
from rulehall.engines.pokemon.rules import ITEMS, catch_rate
from rulehall.engines.pokemon.world import Mon


@pytest.mark.parametrize(("hp", "status", "rate"), [(16, "", 54), (16, "par", 64), (1, "", 114)])
def test_the_catch_rate_follows_the_table(hp: int, status: Status, rate: int) -> None:
    pidgey = Mon.new("pidgey", 3, Random(0), ()).battler()
    assert pidgey.hp == 16
    foe = pidgey.model_copy(update={"hp": hp, "status": status})

    assert catch_rate(foe, ITEMS["poke-ball"].catch_bonus) == rate


def test_one_ball_each_turn() -> None:
    draft = started().draft()
    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey")
    battle = draft.world.battle
    assert battle is not None
    foe = battle.setup.foes[0]

    first = ENGINE.throw_ball(draft, "poke-ball", foe, Random(0))

    assert first.input_index == len(battle.inputs)
    with pytest.raises(Refusal):
        _ = ENGINE.throw_ball(draft, "poke-ball", foe, Random(0))
