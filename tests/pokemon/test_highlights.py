from support.showdown import CHARMANDER, PIKACHU, RATTATA, WILD_SETUP, recorded

from rulehall.engines.pokemon.battle.highlights import battle_highlights
from rulehall.engines.pokemon.battle.models import Ally, Battle, BattleSetup
from rulehall.engines.pokemon.battle.simulator import read_update

TRAINER_SETUP = BattleSetup.model_validate(
    {
        **WILD_SETUP.model_dump(),
        "policy": "scripted",
        "foe_id": "misty",
        "foe_name": "Misty",
        "foe_avatar_id": "misty",
        "team": (PIKACHU, RATTATA),
        "foes": (RATTATA, PIKACHU),
    }
)


def test_the_recorded_battle_yields_its_knockout() -> None:
    log = [
        line
        for kind, *lines in recorded()
        if kind == "update"
        for line in read_update(lines, opening=False)[0]
    ]

    assert battle_highlights(Battle(setup=WILD_SETUP), log) == (
        "Pikachu knocked out the wild Rattata with Thunder Shock",
    )


def test_a_clutch_win_and_a_critical_knockout_lead_the_highlights() -> None:
    log = [
        "|switch|p1a: Pikachu|Pikachu, L7, M|24/24",
        "|switch|p2a: Rattata|Rattata, L3, F|15/15",
        "|move|p2a: Rattata|Tackle|p1a: Pikachu",
        "|-crit|p1a: Pikachu",
        "|-damage|p1a: Pikachu|0 fnt",
        "|faint|p1a: Pikachu",
        "|switch|p1a: Rattata|Rattata, L3, F|15/15",
        "|move|p1a: Rattata|Tackle|p2a: Rattata",
        "|-damage|p2a: Rattata|0 fnt",
        "|faint|p2a: Rattata",
        "|switch|p2a: Pikachu|Pikachu, L7, M|24/24",
        "|move|p2a: Pikachu|Thunder Shock|p1a: Rattata",
        "|-damage|p1a: Rattata|3/15",
        "|move|p1a: Rattata|Tackle|p2a: Pikachu",
        "|-damage|p2a: Pikachu|0 fnt",
        "|faint|p2a: Pikachu",
        "|win|Kael",
    ]

    assert battle_highlights(Battle(setup=TRAINER_SETUP), log) == (
        "Rattata won on 3 HP",
        "Rattata was the last Pokemon standing",
        "A critical hit from Misty's Rattata knocked out Pikachu",
    )


def test_an_ally_knockout_names_the_ally() -> None:
    ally = Ally(name="Mira", style="", avatar_id="lass", team=(CHARMANDER,))
    setup = TRAINER_SETUP.model_copy(update={"double": True, "ally": ally})
    log = [
        "|move|p1b: Charmander|Scratch|p2a: Rattata",
        "|-damage|p2a: Rattata|0 fnt",
    ]

    assert battle_highlights(Battle(setup=setup), log) == (
        "Mira's Charmander knocked out Misty's Rattata with Scratch",
    )
