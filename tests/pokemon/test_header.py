from support.showdown import CHARMANDER, PIKACHU, RATTATA, WILD_SETUP

from rulehall.engines.pokemon.battle.header import battle_header
from rulehall.engines.pokemon.battle.models import Ally, BattleSetup, DumpMon

TRAINER_SETUP = BattleSetup.model_validate(
    {
        **WILD_SETUP.model_dump(),
        "policy": "scripted",
        "foe_id": "rook",
        "foe_name": "Rook",
        "foe_avatar_id": "camper",
        "team": (PIKACHU, RATTATA),
        "foes": (RATTATA, PIKACHU),
        "weather": "rain",
        "terrain": "grassy",
        "edge": "foe-asleep",
    }
)


def test_the_header_follows_the_log_for_conditions_and_lines() -> None:
    log = (
        "|c|Rook|You will not win!",
        "|-fieldend|move: Grassy Terrain",
        "|upkeep",
        "|turn|2",
        "|c|Rook|Hot | bright.",
        "|-weather|none",
        "|turn|3",
    )

    header = battle_header(TRAINER_SETUP, (), (), log, None)

    assert header.foe.said == "Hot | bright."
    assert header.conditions == ()
    assert battle_header(TRAINER_SETUP, (), (), (*log, "|turn|4"), None).foe.said == ""
    assert [tag.name for tag in battle_header(TRAINER_SETUP, (), (), (), None).conditions] == [
        "rain",
        "grassy terrain",
    ]


def test_a_tag_header_splits_the_pips_and_shows_the_fielded_pokemon() -> None:
    ally = Ally(name="Mira", style="", avatar_id="lass", team=(CHARMANDER,))
    setup = TRAINER_SETUP.model_copy(update={"double": True, "ally": ally})
    raised = {"atk": 2, "def": 0, "spe": -1}
    p1 = (
        DumpMon(
            slot=2, hp=26, status="", pp=(56, 40), out=1, held=True, active=True, boosts=raised
        ),
        DumpMon(slot=0, hp=0, status="fnt", pp=(48, 64), out=1, held=True, active=True, boosts={}),
        DumpMon(slot=1, hp=15, status="", pp=(56,), out=0, held=True, active=False, boosts={}),
    )
    p2 = (DumpMon(slot=0, hp=10, status="", pp=(56,), out=1, held=True, active=True, boosts={}),)

    header = battle_header(setup, p1, p2, ("|c|Mira|Go!",), 0)

    assert header.player.pips == ("fainted", "reserve")
    assert header.ally is not None
    assert (header.ally.pips, header.ally.said) == (("able",), "Go!")
    assert header.foe.pips == ("able",)
    [charmander] = header.fielded
    assert [tag.name for tag in charmander.tags] == ["Lv8", "Atk +2", "Spe -1"]
    assert charmander.deciding
