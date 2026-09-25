import re
from random import Random

import pytest
from support.table import change, refused
from support.tunnelgoons import (
    ENGINE,
    HALL,
    KEY,
    LANTERN,
    MANTIS,
    MIRA,
    ROPE,
    START,
    VAULT,
    small_world,
)

from rulehall.core.play import Exchange
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.rooms.world import Place, Prop, RegionProposal
from rulehall.engines.tunnelgoons.args import LevelUp, Roll
from rulehall.engines.tunnelgoons.world import Goon, GoonSheet, TunnelGoonsGame, TunnelGoonsWorld

TOTAL_RE = re.compile(r"(-?\d+) vs DS")


def _sheeted(*, brute: int = 0, skulker: int = 0, erudite: int = 0) -> GoonSheet:
    return GoonSheet(abilities={"brute": brute, "skulker": skulker, "erudite": erudite})


def _total(card: str) -> int:
    match = TOTAL_RE.search(card)
    assert match is not None
    return int(match.group(1))


def test_the_roll_adds_ability_and_items_and_penalizes_brute_and_skulker_over_inventory() -> None:
    draft = small_world().draft()
    world = draft.world
    world.player.require_sheet().abilities["skulker"] = 2
    world.player.require_sheet().inventory = 1  # carrying rope + torch (2) is 1 over
    facts = ENGINE.roll(
        draft,
        Roll(what="Sneak past", ability="skulker", item_ids=(ROPE,), difficulty=10),
        Random(1),
    )
    rolled = facts[1]
    dice = rolled.dice[0].rolled
    assert (
        _total(rolled.card) == sum(dice) + world.player.require_sheet().abilities["skulker"] + 1 - 1
    )


def test_a_what_naming_an_unmet_npc_is_refused(draft: TunnelGoonsGame) -> None:
    with pytest.raises(Refusal, match="names what the player has not met"):
        _ = ENGINE.tools["roll"].call(
            draft,
            {"what": "Listen for Robo Mantis", "ability": "skulker", "difficulty": 8},
            Random(0),
        )


def test_a_roll_against_an_npc_that_hits_can_slay_it(draft: TunnelGoonsGame) -> None:
    world = draft.world
    world.npcs[MANTIS].place_id = START
    world.npcs[MANTIS].known = True
    world.player.require_sheet().abilities["brute"] = 10  # min total 12 always beats DS 4
    _ = ENGINE.roll(
        draft,
        Roll(what="Smash it", ability="brute", target_id=MANTIS, dangerous=True),
        Random(3),
    )
    mantis = world.npcs[MANTIS]
    assert mantis.hp.current == 0
    assert not mantis.alive


def test_a_miss_against_an_npc_can_kill_the_player(draft: TunnelGoonsGame) -> None:
    world = draft.world
    world.npcs[MANTIS].place_id = START
    world.npcs[MANTIS].known = True
    world.npcs[MANTIS].hp.maximum = 20
    world.npcs[MANTIS].hp.current = 20  # max total 12 never beats DS 20
    world.player.require_sheet().abilities["brute"] = 0
    world.player.hp.current = 1
    _ = ENGINE.roll(
        draft,
        Roll(what="Smash it", ability="brute", target_id=MANTIS, dangerous=True),
        Random(4),
    )
    assert world.player.hp.current == 0
    assert not world.player.alive
    assert ENGINE.ending(draft) == "You died."


def test_dangerous_hurts_only_on_a_miss() -> None:
    draft = small_world().draft()
    world = draft.world
    world.player.require_sheet().abilities["erudite"] = 12  # min total 14 always beats DS 8
    before = world.player.hp.current
    _ = ENGINE.roll(
        draft,
        Roll(what="Cross the gap", ability="erudite", difficulty=8, dangerous=True),
        Random(0),
    )
    assert world.player.hp.current == before

    draft2 = small_world().draft()
    world2 = draft2.world
    world2.player.require_sheet().inventory = 0
    world2.items.update(
        {
            f"junk-{n}": Prop(
                id=f"junk-{n}",
                name=f"Junk {n}",
                brief="Clutter",
                known=True,
                holder_id=PLAYER_ID,
            )
            for n in range(11)
        }
    )  # carried (13) - inventory (0) = 13 penalty, always below any legal DS
    _ = ENGINE.roll(
        draft2,
        Roll(what="Cross the gap", ability="brute", difficulty=8, dangerous=True),
        Random(0),
    )
    assert world2.player.hp.current < world2.player.hp.maximum


def test_rest_heals_the_player(draft: TunnelGoonsGame, world: TunnelGoonsWorld) -> None:
    world.player.hp.current = 4
    _ = change(ENGINE, draft, "rest")
    assert world.player.hp.current == world.player.hp.maximum


def test_level_up_with_no_args_opens_the_six_option_decision(draft: TunnelGoonsGame) -> None:
    facts = ENGINE.level_up(draft, LevelUp(), Random(0))
    assert facts == []
    assert draft.pending is not None
    assert len(draft.pending.options) == 6


def test_level_up_with_both_raises_the_ability_and_the_boost_and_the_level() -> None:
    draft = small_world().draft()
    world = draft.world
    before = world.player.require_sheet().level
    _ = ENGINE.level_up(draft, LevelUp(ability="brute", boost="health"), Random(0))
    assert world.player.require_sheet().abilities["brute"] == 2
    assert world.player.require_sheet().level == before + 1


def test_level_up_passes_the_choice_on_to_a_hired_member() -> None:
    draft = small_world().draft()
    world = draft.world
    world.npcs[MIRA].sheet = _sheeted(brute=1, skulker=1, erudite=1)
    world.party.append(MIRA)

    _ = ENGINE.level_up(draft, LevelUp(ability="brute", boost="health"), Random(0))
    assert draft.pending is not None

    _ = ENGINE.level_up(draft, LevelUp(ability="skulker", boost="inventory"), Random(0))

    assert world.npcs[MIRA].require_sheet().level == 2
    assert world.npcs[MIRA].require_sheet().abilities["skulker"] == 2


def test_move_refuses_a_locked_way(world: TunnelGoonsWorld) -> None:
    world.visits.append(HALL)
    with pytest.raises(Refusal, match="locked"):
        _ = world.move(VAULT, ())


def test_move_reveals_the_destination_and_adds_a_visit(draft: TunnelGoonsGame) -> None:
    world = draft.world
    before = len(world.visits)
    _ = world.move(VAULT, ())
    assert world.current.id == VAULT
    assert world.places[VAULT].known
    assert len(world.visits) == before + 1


def test_two_moves_open_no_chapter_and_install_closes_with_the_recap(
    draft: TunnelGoonsGame,
) -> None:
    _ = draft.world.move(HALL, ())
    _ = draft.world.move(START, ())
    assert [chapter.title for chapter in draft.log] == ["Start"]
    draft.log[-1].exchanges.append(Exchange(words="Look around.", lines=()))

    region = RegionProposal[Goon](
        places={
            "beyond": Place(id="beyond", name="Beyond", brief="b", known=False, description="d")
        },
        start_id="beyond",
        recap="They walked to the hall and back, finding nothing.",
    )
    ENGINE.install(draft, region)

    assert [chapter.title for chapter in draft.log] == ["Start", "Start"]
    assert draft.log[0].recap == region.recap
    assert draft.log[1].recap == ""


def test_move_with_ids_brings_an_npc_here_and_refuses_one_standing_elsewhere() -> None:
    draft = small_world().draft()
    world = draft.world
    facts = change(ENGINE, draft, "move", to_id=VAULT, with_ids=[MIRA])
    assert world.npcs[MIRA].place_id == VAULT
    assert any("Mira" in fact.trace for fact in facts)

    elsewhere = small_world().draft()
    with pytest.raises(Refusal, match="not here"):
        _ = elsewhere.world.move(VAULT, (MANTIS,))


def test_move_item_to_the_player_to_an_npc_here_and_to_the_place(draft: TunnelGoonsGame) -> None:
    world = draft.world
    _ = change(ENGINE, draft, "move_item", item_id=LANTERN, to_id=MIRA)
    assert world.items[LANTERN].holder_id == MIRA

    _ = change(ENGINE, draft, "move_item", item_id=LANTERN, to_id=PLAYER_ID)
    assert world.items[LANTERN].holder_id == PLAYER_ID

    _ = change(ENGINE, draft, "move_item", item_id=LANTERN, to_id=START)
    assert world.items[LANTERN].holder_id == START


def test_kill_drops_an_npcs_items_loose(draft: TunnelGoonsGame, world: TunnelGoonsWorld) -> None:
    blade = "mira-blade"
    world.items[blade] = Prop(
        id=blade, name="Blade", brief="Mira's blade", known=True, holder_id=MIRA
    )

    _ = change(ENGINE, draft, "kill", target_id=MIRA)

    assert not world.npcs[MIRA].alive
    assert world.items[blade].holder_id == START


def test_reveal_only_what_is_here_and_unknown(draft: TunnelGoonsGame) -> None:
    world = draft.world
    assert "not here" in refused(ENGINE, draft, "reveal", target_id=KEY)
    assert "already" in refused(ENGINE, draft, "reveal", target_id=LANTERN)

    world.npcs[MANTIS].place_id = START
    _ = change(ENGINE, draft, "reveal", target_id=MANTIS)
    assert world.npcs[MANTIS].known


def test_action_roll_a_member_rolls_on_their_own_abilities_and_items() -> None:
    draft = small_world().draft()
    world = draft.world
    world.npcs[MIRA].sheet = _sheeted(skulker=2)
    world.party.append(MIRA)
    world.items[ROPE].holder_id = MIRA
    facts = ENGINE.roll(
        draft,
        Roll(what="Sneak past", ability="skulker", item_ids=(ROPE,), difficulty=10, actor_id=MIRA),
        Random(1),
    )
    rolled = facts[1]
    dice = rolled.dice[0].rolled
    assert _total(rolled.card) == sum(dice) + 2 + 1
    assert "Mira" in rolled.card


def test_a_members_miss_damages_them_and_kills_them_at_zero(draft: TunnelGoonsGame) -> None:
    world = draft.world
    world.npcs[MIRA].sheet = _sheeted()
    world.npcs[MIRA].hp.current = 1
    world.party.append(MIRA)
    _ = ENGINE.roll(
        draft,
        Roll(what="Leap the gap", ability="brute", difficulty=20, dangerous=True, actor_id=MIRA),
        Random(0),
    )
    assert world.npcs[MIRA].hp.current == 0
    assert not world.npcs[MIRA].alive
