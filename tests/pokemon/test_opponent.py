from support.golden import FIXTURES, golden, masked
from support.showdown import WILD_SETUP, assessed

from rulehall.core.validation import parse_json
from rulehall.core.views import Choice
from rulehall.engines.pokemon.battle.opponent import render_opponent
from rulehall.engines.pokemon.battle.simulator import DUMPED, Dump

TRAINER_SETUP = WILD_SETUP.model_copy(
    update={"kind": "trainer", "foe_id": "rook", "foe_name": "Rook", "foe_avatar_id": "camper"}
)


def test_the_opponent_prompt_renders_unchanged() -> None:
    line = assessed()[0][1]
    dump = parse_json(Dump, line.removeprefix(DUMPED).removesuffix('"'))
    assert dump.assessment is not None
    choices = (
        *(
            Choice(command=f"move {number}", name=name)
            for number, name in enumerate(("Vine Whip", "Tackle", "Leech Seed", "Growl"), 1)
        ),
        Choice(command="switch 2", name="Rattata", group="Switch"),
    )

    prompt = render_opponent(TRAINER_SETUP, dump.assessment, choices)

    golden(FIXTURES / "prompts" / "pokemon" / "opponent.txt", masked(prompt.text))
