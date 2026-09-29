import json

from pydantic import JsonValue
from support.golden import FIXTURES, golden, masked
from support.showdown import WILD_SETUP, assessed

from rulehall.core.validation import parse_json
from rulehall.core.views import BattleChoice
from rulehall.engines.pokemon.battle.opponent import (
    Assessment,
    Offer,
    greedy_choice,
    render_opponent,
)
from rulehall.engines.pokemon.battle.simulator import DUMPED, Dump

TRAINER_SETUP = WILD_SETUP.model_copy(
    update={
        "policy": "model",
        "foe_id": "rook",
        "foe_name": "Rook",
        "foe_avatar_id": "camper",
    }
)
CHOICES = (
    *(
        BattleChoice(command=f"move {number}", kind="move", name=name)
        for number, name in enumerate(("Vine Whip", "Tackle", "Leech Seed", "Growl"), 1)
    ),
    BattleChoice(command="switch 2", kind="switch", name="Rattata"),
)


def test_the_opponent_prompt_renders_unchanged() -> None:
    offers = (Offer(mon_name="Bulbasaur", choices=CHOICES),)
    prompt = render_opponent(TRAINER_SETUP, "foe", _assessment(), offers, frozenset({0, 1}))

    golden(FIXTURES / "prompts" / "pokemon" / "opponent.txt", masked(prompt.text))


def test_greedy_takes_the_knockout_else_the_most_damage() -> None:
    assessment = _assessment()
    charmander, *rest = assessment.foes
    weakened = charmander.model_copy(update={"percent": 8})

    assert greedy_choice(assessment, CHOICES, 0) == "move 2"
    assert greedy_choice(assessment.model_copy(update={"foes": (weakened, *rest)}), CHOICES, 0) == (
        "move 1"
    )


def _assessment() -> Assessment:
    line = assessed()[0][1]
    dump = parse_json(Dump, line.removeprefix(DUMPED).removesuffix('"'))
    assert dump.assessment is not None
    return dump.assessment


def test_greedy_picks_each_slot_its_target_knockout_first() -> None:
    choices = tuple(
        BattleChoice(command=f"move 1 {target}", kind="move", name=f"Tackle at {name}")
        for target, name in (("1", "Pikachu"), ("2", "Charmander"), ("-2", "Pidgey"))
    )
    hurt = _doubles_assessment(charmander_percent=30)
    healthy = _doubles_assessment(charmander_percent=90)

    assert greedy_choice(hurt, choices, 0) == "move 1 2"
    assert greedy_choice(healthy, choices, 0) == "move 1 1"


def _doubles_assessment(*, charmander_percent: int) -> Assessment:
    tackle: JsonValue = {
        "name": "Tackle",
        "type": "Normal",
        "pp": 56,
        "maxpp": 56,
        "disabled": False,
        "multihit": None,
        "target": "normal",
        "hits": [
            {"target": 1, "name": "Pikachu", "damage": [9, 11], "percent": [40, 45]},
            {"target": 2, "name": "Charmander", "damage": [8, 9], "percent": [30, 35]},
        ],
    }
    own: dict[str, JsonValue] = {
        "level": 5,
        "types": ["Normal"],
        "hp": 20,
        "maxhp": 20,
        "status": "",
        "boosts": {},
    }
    seen: dict[str, JsonValue] = {
        "level": 7,
        "types": [],
        "status": "",
        "active": True,
        "out": True,
        "boosts": {},
    }
    assessment: JsonValue = {
        "team": [
            {**own, "slot": 1, "name": "Rattata", "active": True, "moves": [tackle], "threats": []},
            {**own, "slot": 2, "name": "Pidgey", "active": True, "moves": [tackle], "threats": []},
        ],
        "foes": [
            {**seen, "name": "Pikachu", "percent": 100, "moves": []},
            {**seen, "name": "Charmander", "percent": charmander_percent, "moves": []},
        ],
    }
    return parse_json(Assessment, json.dumps(assessment))
