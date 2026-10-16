import re
from random import Random

import pytest
from support.golden import FIXTURES, golden, masked
from support.lite5e_battle import bonus_plan_texts, fight, foe, member, plan_texts

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.opponent import (
    FoeOffer,
    OpponentAnswer,
    check_commands,
    render_opponent,
)
from rulehall.engines.lite5e.battle.state import told

OFFERS = (
    FoeOffer(
        combatant_id="goblins-1",
        name="Goblins 1",
        plans=("scimitar mira", "back, shortbow mira (disadvantage)"),
        bonus_plans=("nimble escape: back",),
    ),
    FoeOffer(combatant_id="wolf", name="Wolf", plans=("bite mira (advantage)",)),
)


def test_check_commands_takes_one_offered_plan_per_foe_with_an_offered_bonus_plan() -> None:
    answer = OpponentAnswer(commands=("scimitar mira; nimble escape: back", "bite mira"))

    check_commands(OFFERS, answer)


@pytest.mark.parametrize(
    ("commands", "refusal"),
    [
        (("scimitar mira",), "give 2 commands"),
        (("scimitar rook", "bite mira"), "not a plan for Goblins 1"),
        (("scimitar mira", "bite mira; nimble escape: back"), "not a bonus plan for Wolf"),
        (("scimitar mira; hide", "bite mira"), "not a bonus plan for Goblins 1"),
    ],
)
def test_check_commands_refuses_a_count_mismatch_and_a_plan_not_offered(
    commands: tuple[str, ...], refusal: str
) -> None:
    with pytest.raises(Refusal, match=refusal):
        check_commands(OFFERS, OpponentAnswer(commands=commands))


def test_the_opponent_prompt_renders_unchanged() -> None:
    mira = member("mira", weapon_ids=("longsword",))
    rook = member("rook", "rogue", weapon_ids=("shortbow",))
    played = fight(
        [(mira, "front"), (rook, "back")],
        [foe("bandits-1", "bandit", "back"), foe("bandits-2", "bandit"), foe("wolf", "wolf")],
        Random(0),
    )
    played.battle.round = 3
    played.battle.facts.extend(
        told(line)
        for line in (
            "Initiative: Wolf, Mira, Bandits 1, Bandits 2, Rook",
            "Round 1",
            "Wolf → Mira, Bite: 9: miss",
            "Round 2",
            "Wolf → Mira, Bite: 14: hit",
            "Round 3",
            "Mira → Wolf, Longsword: 7: miss",
        )
    )
    foes = played.battle.foes()
    offers = tuple(
        FoeOffer(
            combatant_id=each.combatant_id,
            name=each.name,
            plans=plan_texts(played, each),
            bonus_plans=bonus_plan_texts(played, each),
        )
        for each in foes
    )

    prompt = render_opponent(played, offers)

    golden(FIXTURES / "prompts" / "lite5e" / "opponent.txt", masked(prompt.text))


def test_recent_turns_show_the_members_health_bands_and_no_hp() -> None:
    mira = member("mira", weapon_ids=("longsword",))
    played = fight([(mira, "front")], [foe("wolf", "wolf")], Random(0))
    played.battle.facts.extend(
        told(line)
        for line in (
            "Round 1",
            "Mira: -5 HP → 7/12",
            "Mira: HP maximum -2 → 5/10",
            "Mira: Adrenaline Rush, temporary HP 3",
            "Mira: Relentless Endurance, stays up at 1 HP",
        )
    )
    offer = FoeOffer(
        combatant_id="wolf", name="Wolf", plans=plan_texts(played, played.battle.foes()[0])
    )

    recent = render_opponent(played, (offer,)).user.split("RECENT TURNS", 1)[1]

    assert "- Mira: hurt\n" in recent
    assert "- Mira: bloodied\n" in recent
    assert "- Mira: Adrenaline Rush, temporary HP\n" in recent
    assert "- Mira: Relentless Endurance, stays up\n" in recent
    assert not re.search(r"\d+/\d+|HP \d|\d+ HP", recent.split("THE CHOICES", 1)[0])
