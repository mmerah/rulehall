from support.golden import FIXTURES, golden, masked
from support.showdown import WILD_SETUP, assessed

from rulehall.core.validation import parse_json
from rulehall.core.views import BattleChoice
from rulehall.engines.pokemon.battle.opponent import Assessment, greedy_choice, render_opponent
from rulehall.engines.pokemon.battle.simulator import DUMPED, Dump

TRAINER_SETUP = WILD_SETUP.model_copy(
    update={
        "kind": "trainer",
        "policy": "model",
        "foe_id": "rook",
        "foe_name": "Rook",
        "foe_avatar_id": "camper",
    }
)
CHOICES = (
    *(
        BattleChoice(command=f"move {number}", name=name)
        for number, name in enumerate(("Vine Whip", "Tackle", "Leech Seed", "Growl"), 1)
    ),
    BattleChoice(command="switch 2", name="Rattata", group="Switch"),
)


def test_the_opponent_prompt_renders_unchanged() -> None:
    prompt = render_opponent(TRAINER_SETUP, _assessment(), CHOICES)

    golden(FIXTURES / "prompts" / "pokemon" / "opponent.txt", masked(prompt.text))


def test_greedy_takes_the_knockout_else_the_most_damage() -> None:
    assessment = _assessment()
    charmander, *rest = assessment.foes
    weakened = charmander.model_copy(update={"percent": 8})

    assert greedy_choice(assessment, CHOICES) == "move 2"
    assert greedy_choice(assessment.model_copy(update={"foes": (weakened, *rest)}), CHOICES) == (
        "move 1"
    )


def _assessment() -> Assessment:
    line = assessed()[0][1]
    dump = parse_json(Dump, line.removeprefix(DUMPED).removesuffix('"'))
    assert dump.assessment is not None
    return dump.assessment
