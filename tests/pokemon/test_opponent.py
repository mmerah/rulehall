import json
from pathlib import Path

from pydantic import JsonValue
from support.golden import FIXTURES, golden, masked
from support.showdown import PIKACHU, WILD_SETUP, assessed

from rulehall.core.validation import parse_json
from rulehall.core.views import BattleChoice
from rulehall.engines.pokemon.battle.assessment import Assessment
from rulehall.engines.pokemon.battle.models import BattleMove, Battler
from rulehall.engines.pokemon.battle.opponent import Offer, greedy_choice, render_opponent
from rulehall.engines.pokemon.battle.simulator import DUMPED, Dump

HIDDEN = Path(__file__).parent / "fixtures" / "hidden.txt"
TRAINER_CHARMANDER = Battler(
    mon_id="charmander",
    species_id="charmander",
    name="Charmander",
    level=12,
    nature="Hardy",
    ability="Blaze",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(
        BattleMove(move_id="scratch", name="Scratch", type="Normal", pp=56),
        BattleMove(move_id="ember", name="Ember", type="Fire", pp=40),
    ),
    hp=35,
)
BULBASAUR = Battler(
    mon_id="bulbasaur",
    species_id="bulbasaur",
    name="Bulbasaur",
    level=12,
    nature="Hardy",
    ability="Overgrow",
    gender="F",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(
        BattleMove(move_id="vinewhip", name="Vine Whip", type="Grass", pp=40),
        BattleMove(move_id="tackle", name="Tackle", type="Normal", pp=56),
        BattleMove(move_id="leechseed", name="Leech Seed", type="Grass", pp=16),
        BattleMove(move_id="growl", name="Growl", type="Normal", pp=64),
    ),
    hp=36,
)
TRAINER_RATTATA = Battler(
    mon_id="rattata",
    species_id="rattata",
    name="Rattata",
    level=8,
    nature="Hardy",
    ability="Guts",
    gender="F",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(
        BattleMove(move_id="tackle", name="Tackle", type="Normal", pp=56),
        BattleMove(move_id="quickattack", name="Quick Attack", type="Normal", pp=48),
    ),
    hp=25,
)
TRAINER_SETUP = WILD_SETUP.model_copy(
    update={
        "policy": "model",
        "foe_id": "rook",
        "foe_name": "Rook",
        "foe_avatar_id": "camper",
        "team": (TRAINER_CHARMANDER, PIKACHU),
        "foes": (BULBASAUR, TRAINER_RATTATA),
    }
)
BRONZOR = Battler(
    mon_id="bronzor",
    species_id="bronzor",
    name="Bronzor",
    level=10,
    nature="Hardy",
    ability="Levitate",
    gender="N",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    item_id="focus-sash",
    moves=(BattleMove(move_id="confusion", name="Confusion", type="Psychic", pp=40),),
    hp=34,
)
SANDSHREW = Battler(
    mon_id="sandshrew",
    species_id="sandshrew",
    name="Sandshrew",
    level=30,
    nature="Hardy",
    ability="Sand Veil",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(BattleMove(move_id="earthquake", name="Earthquake", type="Ground", pp=16),),
    hp=79,
)
HIDDEN_SETUP = TRAINER_SETUP.model_copy(update={"team": (BRONZOR,), "foes": (SANDSHREW,)})
CHOICES = (
    *(
        BattleChoice(command=f"move {number}", kind="move", name=name)
        for number, name in enumerate(("Vine Whip", "Tackle", "Leech Seed", "Growl"), 1)
    ),
    BattleChoice(command="switch 2", kind="switch", name="Rattata"),
)
LOG = (
    "|switch|p1a: Charmander|Charmander, L12, M|35/35",
    "|switch|p2a: Bulbasaur|Bulbasaur, L12, F|36/36",
    "|turn|1",
    "|move|p1a: Charmander|Ember|p2a: Bulbasaur",
    "|-supereffective|p2a: Bulbasaur",
    "|-damage|p2a: Bulbasaur|26/36",
    "|move|p2a: Bulbasaur|Leech Seed|p1a: Charmander",
    "|-start|p1a: Charmander|move: Leech Seed",
    "|-damage|p1a: Charmander|31/35|[from] Leech Seed|[of] p2a: Bulbasaur",
    "|turn|2",
)


def test_the_opponent_prompt_renders_unchanged() -> None:
    offers = (Offer(slot=0, mon_name="Bulbasaur", choices=CHOICES),)
    prompt = render_opponent(TRAINER_SETUP, "foe", _assessment(), offers, frozenset({0, 1}), LOG)

    golden(FIXTURES / "prompts" / "pokemon" / "opponent.txt", masked(prompt.text))


def test_greedy_takes_the_knockout_else_the_most_damage() -> None:
    assessment = _assessment()
    bulbasaur, *rest = assessment.team
    weakened = bulbasaur.model_copy(
        update={
            "moves": tuple(
                move.model_copy(
                    update={"hits": tuple(hit.model_copy(update={"hp": 4}) for hit in move.hits)}
                )
                for move in bulbasaur.moves
            )
        }
    )

    assert greedy_choice(assessment, CHOICES, 0) == "move 2"
    assert greedy_choice(assessment.model_copy(update={"team": (weakened, *rest)}), CHOICES, 0) == (
        "move 1"
    )


def test_a_foe_ability_and_item_not_revealed_yet_do_not_shape_the_damage() -> None:
    earthquake = BattleChoice(command="move 1", kind="move", name="Earthquake")
    offers = (Offer(slot=0, mon_name="Sandshrew", choices=(earthquake,)),)
    assessment = _assessment(HIDDEN.read_text().strip())

    prompt = render_opponent(HIDDEN_SETUP, "foe", assessment, offers, frozenset({0}), ())

    assert "- move 1: Earthquake (Ground, physical, 16/16 PP): Bronzor KO" in prompt.user
    assert "no effect" not in prompt.user
    assert "Focus Sash" not in prompt.user


def _assessment(line: str | None = None) -> Assessment:
    recorded = assessed()[0][1] if line is None else line
    dump = parse_json(Dump, recorded.removeprefix(DUMPED).removesuffix('"'))
    assert dump.assessment is not None
    return dump.assessment


def test_greedy_picks_each_slot_its_target_knockout_first() -> None:
    choices = tuple(
        BattleChoice(command=f"move 1 {target}", kind="move", name=f"Tackle at {name}")
        for target, name in (("1", "Pikachu"), ("2", "Charmander"), ("-2", "Pidgey"))
    )
    hurt = _doubles_assessment(charmander_hp=8)
    healthy = _doubles_assessment(charmander_hp=24)

    assert greedy_choice(hurt, choices, 0) == "move 1 2"
    assert greedy_choice(healthy, choices, 0) == "move 1 1"


def _doubles_assessment(*, charmander_hp: int) -> Assessment:
    shot: dict[str, JsonValue] = {
        "hits": [1, 1],
        "multiplier": 1,
        "shield": "",
        "endured": "",
        "one_hit_ko": False,
    }
    tackle: JsonValue = {
        "name": "Tackle",
        "type": "Normal",
        "category": "Physical",
        "priority": 0,
        "pp": 56,
        "maxpp": 56,
        "lock": "",
        "target": "normal",
        "hits": [
            {**shot, "target": 1, "name": "Pikachu", "hp": 22, "maxhp": 22, "damage": [9, 11]},
            {
                **shot,
                "target": 2,
                "name": "Charmander",
                "hp": charmander_hp,
                "maxhp": 26,
                "damage": [8, 9],
            },
        ],
    }
    own: dict[str, JsonValue] = {
        "species": "Rattata",
        "level": 5,
        "types": ["Normal"],
        "hp": 20,
        "maxhp": 20,
        "status": "",
        "boosts": {},
        "volatiles": [],
        "ability": "Guts",
        "item": "",
        "stats": [10, 10, 10, 10, 10],
        "speed": 10,
        "moves": [tackle],
        "threats": [],
    }
    assessment: JsonValue = {
        "turn": 1,
        "weather": None,
        "terrain": None,
        "rooms": [],
        "own_side": [],
        "foe_side": [],
        "team": [
            {**own, "slot": 1, "name": "Rattata", "position": 1},
            {**own, "slot": 2, "name": "Pidgey", "position": 2},
        ],
        "foes": [],
        "unseen": 0,
    }
    return parse_json(Assessment, json.dumps(assessment))
