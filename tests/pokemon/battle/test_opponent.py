import json
from pathlib import Path

import pytest
from pydantic import JsonValue
from support.golden import FIXTURES, golden, masked
from support.showdown import CHAMPIONS_SETUP, DOUBLES_SETUP, PIKACHU, WILD_SETUP, assessed

from rulehall.core.validation import Refusal, parse_json
from rulehall.engines.pokemon.battle.assessment import Assessment
from rulehall.engines.pokemon.battle.models import BattleMove, Battler
from rulehall.engines.pokemon.battle.opponent import (
    Offer,
    OpponentAnswer,
    check_commands,
    greedy_choice,
    opponent_system,
    render_opponent,
)
from rulehall.engines.pokemon.battle.preview import (
    matchup_score,
    preview_picks,
    render_preview,
    scripted_preview,
)
from rulehall.engines.pokemon.battle.simulator import DUMPED, Dump
from rulehall.engines.pokemon.battle.views import BattleChoice
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import stats

HIDDEN = Path(__file__).parent / "fixtures" / "hidden.txt"
ILLUSION = Path(__file__).parent / "fixtures" / "illusion.txt"
FAINTED_ILLUSION = Path(__file__).parent / "fixtures" / "illusion_fainted.txt"
BROKEN_ILLUSION = Path(__file__).parent / "fixtures" / "illusion_broken.txt"
HIDDEN_VOLATILES = Path(__file__).parent / "fixtures" / "hidden_volatiles.txt"
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
MACHAMP = Battler(
    mon_id="machamp",
    species_id="machamp",
    name="Machamp",
    level=30,
    nature="Hardy",
    ability="Guts",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    item_id="leftovers",
    moves=(BattleMove(move_id="closecombat", name="Close Combat", type="Fighting", pp=8),),
    hp=103,
)
ZOROARK = Battler(
    mon_id="zoroark",
    species_id="zoroark",
    name="Zoroark",
    level=30,
    nature="Hardy",
    ability="Illusion",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    item_id="choice-scarf",
    moves=(
        BattleMove(move_id="darkpulse", name="Dark Pulse", type="Dark", pp=24),
        BattleMove(move_id="nastyplot", name="Nasty Plot", type="Dark", pp=32),
    ),
    hp=85,
)
ALAKAZAM = Battler(
    mon_id="alakazam",
    species_id="alakazam",
    name="Alakazam",
    level=30,
    nature="Hardy",
    ability="Synchronize",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(
        BattleMove(move_id="calmmind", name="Calm Mind", type="Psychic", pp=32),
        BattleMove(move_id="psychic", name="Psychic", type="Psychic", pp=16),
    ),
    hp=82,
)
ILLUSION_SETUP = TRAINER_SETUP.model_copy(
    update={"team": (MACHAMP, ZOROARK, PIKACHU), "foes": (ALAKAZAM,)}
)
FAINTED_ILLUSION_SETUP = ILLUSION_SETUP.model_copy(
    update={"team": (PIKACHU, ZOROARK.model_copy(update={"hp": 1}), MACHAMP), "weather": "sand"}
)
BROKEN_ILLUSION_SETUP = ILLUSION_SETUP.model_copy(
    update={
        "foes": (
            ALAKAZAM.model_copy(
                update={
                    "moves": (
                        BattleMove(move_id="shadowball", name="Shadow Ball", type="Ghost", pp=24),
                    )
                }
            ),
        )
    }
)
HIDDEN_VOLATILES_SETUP = DOUBLES_SETUP.model_copy(
    update={
        "team": (
            MACHAMP.model_copy(update={"item_id": "metronome"}),
            MACHAMP.model_copy(
                update={
                    "mon_id": "hitmonlee",
                    "species_id": "hitmonlee",
                    "name": "Hitmonlee",
                    "ability": "Unburden",
                    "item_id": "sitrusberry",
                    "hp": 20,
                }
            ),
        )
    }
)
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
    offers = (Offer(slot=0, mon_name="Bulbasaur", choices=CHOICES, can_mega=False),)
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
    offers = (Offer(slot=0, mon_name="Sandshrew", choices=(earthquake,), can_mega=False),)
    assessment = _assessment(HIDDEN.read_text().strip())

    prompt = render_opponent(HIDDEN_SETUP, "foe", assessment, offers, frozenset({0}), ())

    assert "- move 1: Earthquake (Ground, physical, 16/16 PP): Bronzor KO" in prompt.user
    assert "no effect" not in prompt.user
    assert "Focus Sash" not in prompt.user


def test_a_foe_under_illusion_is_judged_as_the_pokemon_it_shows() -> None:
    assessment = _assessment(ILLUSION.read_text().strip())
    psychic = BattleChoice(command="move 2", kind="move", name="Psychic")
    offers = (Offer(slot=0, mon_name="Alakazam", choices=(psychic,), can_mega=False),)

    prompt = render_opponent(ILLUSION_SETUP, "foe", assessment, offers, frozenset({0}), ())

    machamp, pikachu = assessment.foes
    assert (machamp.name, pikachu.name, assessment.unseen) == ("Machamp", "Pikachu", 1)
    hardy = stats(dex().species["machamp"], 30, "Hardy", (16,) * 6, (0,) * 6)
    assert machamp.stats == hardy[1:]
    (hit,) = assessment.team[0].moves[1].hits
    assert (hit.name, hit.multiplier) == ("Machamp", 2)
    assert "Zoroark" not in prompt.text
    assert "Illusion" not in prompt.text


def test_a_disguised_foe_that_faints_without_a_hit_stays_the_pokemon_it_showed() -> None:
    assessment = _assessment(FAINTED_ILLUSION.read_text().strip())
    calm_mind = BattleChoice(command="move 1", kind="move", name="Calm Mind")
    offers = (Offer(slot=0, mon_name="Alakazam", choices=(calm_mind,), can_mega=False),)

    prompt = render_opponent(FAINTED_ILLUSION_SETUP, "foe", assessment, offers, frozenset({0}), ())

    machamp, pikachu = assessment.foes
    assert (machamp.name, pikachu.name, assessment.unseen) == ("Machamp", "Pikachu", 1)
    assert (machamp.position, pikachu.hp) == (1, 0)
    assert "Zoroark" not in prompt.text


def test_a_broken_illusion_shows_the_real_pokemon() -> None:
    assessment = _assessment(BROKEN_ILLUSION.read_text().strip())

    zoroark, machamp = assessment.foes
    assert (zoroark.name, machamp.name, assessment.unseen) == ("Zoroark", "Machamp", 1)
    assert zoroark.position == 1


def test_a_choice_lock_stays_hidden_until_the_choice_item_shows() -> None:
    assessment = _assessment(ILLUSION.read_text().strip())

    assert ZOROARK.item_id == "choice-scarf"
    assert assessment.foes[0].volatiles == ()


def test_an_item_or_ability_effect_stays_hidden_until_its_source_shows() -> None:
    assessment = _assessment(HIDDEN_VOLATILES.read_text().strip())

    machamp, hitmonlee = assessment.foes
    assert (machamp.item, machamp.volatiles) == (None, ())
    assert (hitmonlee.item, hitmonlee.ability, hitmonlee.volatiles) == ("", None, ())


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


@pytest.mark.parametrize(
    ("commands", "refusal"),
    [
        (("team 3", "team 3"), "the same Pokemon twice"),
        (("move 1 1 mega", "move 1 mega"), "only one of your Pokemon"),
        (("move 1 1", "move 1 mega"), "Garchomp cannot Mega Evolve"),
        (("switch 3 mega", "move 1"), "Charizard cannot Mega Evolve"),
    ],
)
def test_a_double_pick_or_a_mega_evolution_out_of_turn_is_refused(
    commands: tuple[str, str], refusal: str
) -> None:
    with pytest.raises(Refusal, match=refusal):
        check_commands(_mega_offers(), OpponentAnswer(commands=commands))


def test_the_pokemon_that_can_mega_evolve_does_it_with_its_move() -> None:
    check_commands(_mega_offers(), OpponentAnswer(commands=("move 1 1 mega", "move 1")))


def test_the_scripted_preview_brings_four_distinct_pokemon_its_leads_first() -> None:
    foes = tuple(dex().species[battler.species_id] for battler in CHAMPIONS_SETUP.team)

    picks = scripted_preview(CHAMPIONS_SETUP.foes, foes, frozenset(range(6)), 4, 2)

    assert picks == ("team 6", "team 1", "team 3", "team 4")


def test_the_preview_picks_bring_the_mega_stone_holder_even_on_a_low_score() -> None:
    foes = tuple(dex().species[n] for n in ("heatran", "charizard", "talonflame", "volcarona"))

    scores = [sum(matchup_score(own, foe) for foe in foes) for own in CHAMPIONS_SETUP.foes]

    picks = preview_picks(CHAMPIONS_SETUP.foes, foes, frozenset(range(6)), 3, 2)

    assert CHAMPIONS_SETUP.foes[0].item_id == "venusaurite"
    assert sorted(scores, reverse=True).index(scores[0]) >= len(picks)
    assert 0 in picks


def test_the_preview_asks_for_the_mega_stone_holder_only_when_one_is_in_hand() -> None:
    foes = tuple(dex().species[battler.species_id] for battler in CHAMPIONS_SETUP.team)
    picks = tuple(
        BattleChoice(command=f"team {at}", kind="switch", name=f"Pokemon {at}")
        for at in range(1, 7)
    )
    offers = tuple(
        Offer(slot=slot, mon_name=f"Pick {slot + 1}", choices=picks, can_mega=False)
        for slot in range(4)
    )
    holders = CHAMPIONS_SETUP.foes
    none = tuple(battler.model_copy(update={"holds_mega_stone": False}) for battler in holders)
    hand = frozenset(range(6))

    held = render_preview(CHAMPIONS_SETUP, "foe", offers, holders, hand, foes)
    unheld = render_preview(CHAMPIONS_SETUP, "foe", offers, none, hand, foes)

    assert held.user.count("bring one Pokemon that holds its Mega Stone") == 2
    assert "holds its Mega Stone" not in unheld.user


def test_an_open_sheet_names_the_items_and_moves_but_no_nature_or_stat_points() -> None:
    shown = opponent_system(CHAMPIONS_SETUP, "foe")
    closed = opponent_system(CHAMPIONS_SETUP.model_copy(update={"player_sheet_open": False}), "foe")

    assert "- Garchomp @ Life Orb; Rough Skin; moves: Dragon Claw, Earthquake" in shown
    assert "OPEN TEAM SHEETS" not in closed
    for battler in CHAMPIONS_SETUP.team:
        assert battler.nature not in shown
        assert ", ".join(map(str, battler.evs)) not in shown


def _mega_offers() -> tuple[Offer, Offer]:
    picks = tuple(
        BattleChoice(command=f"team {at}", kind="switch", name=f"Pokemon {at}") for at in (3, 4)
    )
    charizard = (
        BattleChoice(command="move 1 1", kind="move", name="Heat Wave"),
        BattleChoice(command="switch 3", kind="switch", name="Pelipper"),
        *picks,
    )
    garchomp = (BattleChoice(command="move 1", kind="move", name="Earthquake"), *picks)
    return (
        Offer(slot=0, mon_name="Charizard", choices=charizard, can_mega=True),
        Offer(slot=1, mon_name="Garchomp", choices=garchomp, can_mega=False),
    )
