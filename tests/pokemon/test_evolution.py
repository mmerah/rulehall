from random import Random

from support.pokemon import ENGINE, started
from support.table import change, refused

from rulehall.engines.pokemon.battle.models import BattleResult
from rulehall.engines.pokemon.world import Mon, PokemonGame


def test_friendship_evolves_at_a_level_up_from_160_inside_the_region() -> None:
    for pack_id, evolved_id in (("johto", "crobat"), ("srd", "golbat")):
        draft = started().draft()
        _in(draft, pack_id)
        golbat = _joined(draft, "golbat", 21)
        golbat.friendship = 155

        _level_up(draft, golbat)

        assert golbat.friendship == 160
        assert golbat.species_id == evolved_id


def test_a_held_item_or_a_known_move_evolves_at_a_level_up() -> None:
    draft = started().draft()
    _in(draft, "sinnoh")
    sneasel = _joined(draft, "sneasel", 20)
    sneasel.item_id = "razor-claw"
    bonsly = _joined(draft, "bonsly", 10)
    bonsly.learn("mimic", bonsly.moves[0].move_id)

    _level_up(draft, sneasel)
    _level_up(draft, bonsly)

    assert sneasel.species_id == "weavile"
    assert sneasel.item_id is None
    assert bonsly.species_id == "sudowoodo"


def test_two_candidates_open_an_evolution_decision() -> None:
    draft = started().draft()
    _in(draft, "johto")
    eevee = _joined(draft, "eevee", 11)
    eevee.friendship = 160

    _level_up(draft, eevee)

    decision = draft.world.next_decision()
    assert decision is not None
    assert decision.kind == "evolution"
    assert [option.id for option in decision.options] == ["espeon", "umbreon"]
    umbreon = next(option for option in decision.options if option.id == "umbreon")
    _ = ENGINE.play_option(draft, umbreon, Random(0))
    assert eevee.species_id == "umbreon"
    assert draft.world.evolving == []
    assert draft.world.next_decision() is None


def test_the_linking_cord_needs_the_held_item_of_a_trade_evolution() -> None:
    draft = started().draft()
    _in(draft, "johto")
    onix = _joined(draft, "onix", 20)
    _ = change(ENGINE, draft, "gain_item", item_id="linking-cord")

    assert (
        refused(ENGINE, draft, "use_item", item_id="linking-cord", mon_id=onix.mon_id)
        == "Linking Cord does not evolve Onix"
    )
    onix.item_id = "metal-coat"
    _ = change(ENGINE, draft, "use_item", item_id="linking-cord", mon_id=onix.mon_id)
    assert onix.species_id == "steelix"
    assert onix.item_id is None


def test_an_evolution_follows_the_gender() -> None:
    draft = started().draft()
    _in(draft, "kalos")
    male = _joined(draft, "kirlia", 20)
    male.gender = "M"
    female = _joined(draft, "kirlia", 20)
    female.gender = "F"
    espurr = _joined(draft, "espurr", 25)
    espurr.gender = "F"
    _ = change(ENGINE, draft, "gain_item", item_id="dawn-stone")

    assert (
        refused(ENGINE, draft, "use_item", item_id="dawn-stone", mon_id=female.mon_id)
        == "Dawn Stone does not evolve Kirlia"
    )
    _ = change(ENGINE, draft, "use_item", item_id="dawn-stone", mon_id=male.mon_id)
    assert male.species_id == "gallade"
    _level_up(draft, espurr)
    assert espurr.species_id == "meowsticf"
    assert draft.world.next_decision() is None


def _in(draft: PokemonGame, pack_id: str) -> None:
    draft.pack_id = pack_id


def _joined(draft: PokemonGame, species_id: str, level: int) -> Mon:
    sheet = draft.world.player.require_sheet()
    mon = Mon.new(species_id, level, Random(0), sheet.mon_ids())
    sheet.team.append(mon)
    return mon


def _level_up(draft: PokemonGame, mon: Mon) -> None:
    mon.exp = (mon.level + 1) ** 3 - 1
    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey")
    assert draft.world.battle is not None
    setup = draft.world.battle.setup
    result = BattleResult(
        outcome="won", team=setup.team, fainted_foes=setup.foes, on_field=(setup.team[0].mon_id,)
    )
    _ = ENGINE.end_battle(draft, result)
