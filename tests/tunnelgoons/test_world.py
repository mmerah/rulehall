import pytest
from support.tunnelgoons import small_world

from rulehall.core.validation import Refusal
from rulehall.engines.rooms.world import Prop
from rulehall.engines.tunnelgoons.world import (
    TunnelGoonsGame,
)

GHOST = "ghost"


def test_an_item_on_nothing_is_refused(draft: TunnelGoonsGame) -> None:
    draft.world.items["stray"] = Prop(
        id="stray", name="Stray", brief="Nobody's", known=True, holder_id=GHOST
    )
    with pytest.raises(Refusal, match="on nothing"):
        _ = draft.commit()


def test_the_player_levels_up_their_ability_and_health_with_no_name_prefix() -> None:
    world = small_world().world
    player = world.player
    sheet = player.require_sheet()
    before_ability = sheet.abilities["brute"]
    before_hp = player.hp.maximum

    facts = player.level("brute", "health")

    assert sheet.abilities["brute"] == before_ability + 1
    assert player.hp.maximum == before_hp + 1
    assert player.hp.current == before_hp + 1
    assert sheet.level == 2
    assert len(facts) == 1
    assert facts[0].card == "Level 2: Brute +1, Health +1"
    assert facts[0].trace == facts[0].card
