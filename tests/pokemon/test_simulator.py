import json
from asyncio import sleep
from random import Random

import pytest
from pydantic import BaseModel, JsonValue, ValidationError
from support.golden import FIXTURES, golden, masked
from support.pokemon import started
from support.showdown import (
    CHAMPIONS_SETUP,
    CHARIZARD,
    CHARMANDER,
    DOUBLES_SETUP,
    PIDGEY,
    PIKACHU,
    RATTATA,
    RECORDED_CHAMPIONS,
    RECORDED_DOUBLES,
    WILD_SETUP,
    ScriptedSimulator,
    StubBattleGame,
    StubBattleWorld,
    assessed,
    ended,
    moving,
    recorded,
)
from support.showdown import started as blocks_started

from rulehall.core.game import Check
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal, parse_json
from rulehall.core.views import BattleChoice, Tag
from rulehall.engines.pokemon.battle.choices import Hand, SeatRequest, SideRequest, opponent_choice
from rulehall.engines.pokemon.battle.models import (
    Ally,
    Ball,
    Battle,
    Battler,
    BattleSetup,
    DumpMon,
    Outcome,
)
from rulehall.engines.pokemon.battle.opponent import Offer, OpponentAnswer, check_commands
from rulehall.engines.pokemon.battle.simulator import (
    Dump,
    ShowdownRun,
    as_dumped,
    assess_line,
    battle_result,
    condition_lines,
    packed,
    start_lines,
)
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.journey.sheet import Mon
from rulehall.engines.pokemon.journey.world import PokemonGame
from rulehall.engines.pokemon.rules import stats
from rulehall.engines.pokemon.sprites import mon_sprite

TAG_SETUP = DOUBLES_SETUP.model_copy(
    update={
        "team": (PIKACHU, PIDGEY),
        "ally": Ally(name="Mira", style="", avatar_id="lass", team=(CHARMANDER, RATTATA)),
    }
)

# The tag side after `team 1, 3`: the two leads, then the player's bench, then the ally's.
TAG_ORDER = (PIKACHU, CHARMANDER, PIDGEY, RATTATA)


async def test_a_recorded_battle_plays_to_its_result() -> None:
    draft = _battling(WILD_SETUP)
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded()))
    while run.result is None:
        command = next(choice.command for choice in run.choices() if not choice.refusal)
        await run.choose(draft, command, Random(0))

    assert run.result.outcome == "won"
    assert [foe.mon_id for foe in run.result.fainted_foes()] == [RATTATA.mon_id]
    assert run.resolution is not None
    assert draft.world.battle is None
    assert not [line for line in run.log if line.startswith(("||", "|split|", "|-status|"))]


async def test_a_resumed_battle_replays_its_inputs_and_waits_on_the_player() -> None:
    draft = _battling(WILD_SETUP)
    played = ScriptedSimulator(recorded())
    run = await ShowdownRun.start(draft, played)
    await run.choose(draft, "team 1", Random(0))
    await run.choose(draft, "move 1", Random(0))
    assert draft.world.battle is not None
    assert draft.world.battle.inputs == run.inputs

    resumed_draft = draft.validated().draft()
    replayed = ScriptedSimulator(recorded())
    resumed = await ShowdownRun.start(resumed_draft, replayed)

    assert resumed.inputs == run.inputs
    assert resumed.side_request == run.side_request
    assert replayed.sent == played.sent


async def test_a_doubles_turn_takes_a_choice_and_a_target_for_each_slot() -> None:
    draft = _battling(DOUBLES_SETUP)
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded(RECORDED_DOUBLES)))
    assert [choice.command for choice in run.choices()] == ["team 1", "team 2", "leave"]
    await run.choose(draft, "team 1", Random(0))
    assert [(choice.command, choice.refusal) for choice in run.choices()][:2] == [
        ("team 1", "Picked for another Pokemon"),
        ("team 2", ""),
    ]
    for command in ("team 2", "move 1"):
        await run.choose(draft, command, Random(0))
    assert run.inputs[:2] == [">p1 team 1, 2", ">p2 team 1, 2"]

    assert [(choice.command, choice.name) for choice in run.choices()][:4] == [
        ("move 1 1", "Thunder Shock at Rattata"),
        ("move 1 2", "Thunder Shock at Pidgey"),
        ("move 1 -2", "Thunder Shock at your ally Charmander"),
        ("back", "Back"),
    ]
    for command in ("move 1 2", "move 1", "move 1 1"):
        await run.choose(draft, command, Random(0))
    assert run.inputs[2:4] == [">p1 move 1 2, move 1 1", ">p2 move 1 1, move 1 1"]
    for command in ("move 1", "move 1 1", "move 1", "move 1 1"):
        await run.choose(draft, command, Random(0))

    assert run.result is not None and run.result.outcome == "won"
    assert [foe.mon_id for foe in run.result.sent_out_foes] == ["rattata", "pidgey"]
    assert [foe.mon_id for foe in run.result.fainted_foes()] == ["rattata", "pidgey"]
    assert run.result.on_field_mon_ids == ("pikachu", "charmander")
    assert run.result.highlights == (
        "Charmander knocked out Rook's Pidgey with Scratch",
        "Pikachu knocked out Rook's Rattata with Thunder Shock",
    )


async def test_a_saved_doubles_battle_replays_its_inputs() -> None:
    draft = _battling(DOUBLES_SETUP)
    played = ScriptedSimulator(recorded(RECORDED_DOUBLES))
    run = await ShowdownRun.start(draft, played)
    for command in ("team 1", "team 2", "move 1", "move 1 2", "move 1", "move 1 1", "move 2"):
        await run.choose(draft, command, Random(0))

    replayed = ScriptedSimulator(recorded(RECORDED_DOUBLES))
    resumed = await ShowdownRun.start(draft.validated().draft(), replayed)

    assert resumed.inputs == run.inputs
    assert resumed.side_request == run.side_request
    assert replayed.sent == [line for line in played.sent if line != assess_line("p2")]


async def test_the_conditions_go_in_once_the_leads_are_out_and_replay_the_same() -> None:
    setup = WILD_SETUP.model_copy(update={"weather": "rain", "edge": "foe-asleep"})
    draft = _battling(setup)
    played = ScriptedSimulator(recorded())
    run = await ShowdownRun.start(draft, played)
    await run.choose(draft, "team 1", Random(0))

    (conditions,) = condition_lines(setup)
    assert played.sent[played.sent.index(">p2 team 1") + 1] == conditions
    assert "'raindance'" in conditions
    assert "setStatus('slp'" in conditions
    assert [fact.trace for fact in run.facts] == ["Rain falls", "Edge: the wild Rattata is asleep"]
    replayed = ScriptedSimulator(recorded())
    _ = await ShowdownRun.start(draft.validated().draft(), replayed)
    assert replayed.sent == played.sent


async def test_the_choices_end_with_the_balls_and_the_way_out() -> None:
    balls = (Ball(item_id="poke-ball", name="Poké Ball", count=1),)
    draft = _battling(WILD_SETUP.model_copy(update={"balls": balls}))
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded()))
    await run.choose(draft, "team 1", Random(0))

    kinds = [(choice.kind, choice.command, choice.refusal) for choice in run.choices()]

    assert kinds[-2:] == [("item", "ball poke-ball", ""), ("leave", "leave", "")]


async def test_the_model_opponent_thinks_at_the_request_and_its_choice_is_recorded() -> None:
    setup = BattleSetup.model_validate(
        {
            **WILD_SETUP.model_dump(),
            "policy": "model",
            "foe_id": "rook",
            "foe_name": "Rook",
            "foe_avatar_id": "camper",
            # Two a side, as in the recorded assessment.
            "team": (PIKACHU, CHARMANDER),
            "foes": (RATTATA, PIKACHU),
        }
    )
    draft = _battling(setup, [">p1 team 1", ">p2 team 1"])
    simulator = ScriptedSimulator(
        [
            *blocks_started(setup),
            *moving(setup),
            *assessed(),
            *ended(setup, foe_hp=0),
        ]
    )
    asked: list[Prompt] = []

    async def opponent[M: BaseModel](prompt: Prompt, model: type[M], check: Check[M]) -> M:
        asked.append(prompt)
        answer = model.model_validate({"commands": ("move 1",), "line": "You will not win!"})
        check(answer)
        return answer

    run = await ShowdownRun.start(draft, simulator, opponent)
    await sleep(0)
    assert len(asked) == 1
    assert simulator.sent[-1] == assess_line("p2")
    await run.choose(draft, "move 1", Random(0))

    assert len(asked) == 1
    assert run.inputs == [">p1 team 1", ">p2 team 1", ">p1 move 1", ">p2 move 1"]
    assert "the foe's Charmander's Ember: 53-69%, 2x super effective" in asked[0].user
    assert run.result is not None and run.result.outcome == "won"
    assert run.log[-2:] == ["|c|Rook|You will not win!", "|win|Kael"]


async def test_a_refused_model_opponent_falls_back_to_the_scripted_choice() -> None:
    setup = BattleSetup.model_validate(
        {
            **WILD_SETUP.model_dump(),
            "policy": "model",
            "foe_id": "rook",
            "foe_name": "Rook",
            "foe_avatar_id": "camper",
            "team": (PIKACHU, CHARMANDER),
            "foes": (RATTATA, PIKACHU),
        }
    )
    draft = _battling(setup, [">p1 team 1", ">p2 team 1"])
    simulator = ScriptedSimulator(
        [
            *blocks_started(setup),
            *moving(setup),
            *assessed(),
            *assessed(),
            *ended(setup, foe_hp=0),
        ]
    )

    async def opponent[M: BaseModel](_prompt: Prompt, _model: type[M], _check: Check[M]) -> M:
        raise Refusal("the opponent timed out")

    run = await ShowdownRun.start(draft, simulator, opponent)
    await sleep(0)
    await run.choose(draft, "move 1", Random(0))

    assert simulator.sent.count(assess_line("p2")) == 2
    assert run.inputs[-2:] == [">p1 move 1", ">p2 move 1"]
    assert run.result is not None and run.result.outcome == "won"
    assert not any(line.startswith("|c|Rook|") for line in run.log)


def test_an_answer_outside_the_choices_is_refused_with_the_choices() -> None:
    choices = (
        BattleChoice(command="move 1", kind="move", name="Tackle"),
        BattleChoice(command="switch 2", kind="switch", name="Rattata"),
    )
    offers = (Offer(slot=0, mon_name="Rattata", choices=choices, can_mega=False),)

    with pytest.raises(Refusal, match="pick one of: move 1, switch 2"):
        check_commands(offers, OpponentAnswer(commands=("move 2",)))


def test_the_opponent_never_picks_a_disabled_move() -> None:
    moves: list[JsonValue] = [
        {"move": "Tackle", "id": "tackle", "pp": 56, "maxpp": 56, "disabled": False},
        {"move": "Growl", "id": "growl", "pp": 64, "maxpp": 64, "disabled": True},
        {"move": "Quick Attack", "id": "quickattack", "pp": 48, "maxpp": 48, "disabled": False},
    ]
    request = _request({"active": [{"moves": moves}], "side": _side(("15/15", True))})

    picks = {opponent_choice(request, Random(seed)) for seed in range(20)}

    assert picks == {"move 1", "move 3"}


def test_a_forced_switch_sends_a_living_bench_member() -> None:
    side = _side(("0 fnt", True), ("0 fnt", False), ("12/15", False))
    request = _request({"forceSwitch": [True], "side": side})

    picks = {opponent_choice(request, Random(seed)) for seed in range(20)}

    assert picks == {"switch 3"}


def test_a_move_outside_the_setup_has_no_type_and_no_pp() -> None:
    struggle: JsonValue = {
        "move": "Struggle",
        "id": "struggle",
        "target": "randomNormal",
        "disabled": False,
    }
    request = _request({"active": [{"moves": [struggle]}], "side": _side(("3/24", True))})

    assert _seated(request, WILD_SETUP.team, frozenset({0})).choices(0, ()) == (
        BattleChoice(command="move 1", kind="move", name="Struggle"),
    )


def test_a_choice_carries_its_types_and_pp() -> None:
    thunder_shock: JsonValue = {
        "move": "Thunder Shock",
        "id": "thundershock",
        "pp": 30,
        "maxpp": 48,
    }
    side = _side(("24/24", True), ("15/15", False))
    request = _request({"active": [{"moves": [thunder_shock]}], "side": side})
    hurt = RATTATA.model_copy(update={"hp": 5, "status": "par"})
    setup = WILD_SETUP.model_copy(update={"team": (PIKACHU, hurt)})

    move, switch = _seated(request, setup.team, frozenset({0, 1})).choices(0, ())

    assert [tag.name for tag in move.tags] == ["Electric", "Special"]
    assert move.brief == "40 BP · 100%"
    assert [(meter.name, meter.current, meter.maximum) for meter in move.meters] == [("PP", 30, 48)]
    assert switch.command == "switch 2"
    assert switch.tags == (Tag(name="Normal", colour="#a8a878"),)
    assert switch.kind == "switch"
    assert [(meter.current, meter.maximum) for meter in switch.meters] == [(15, 15)]
    preview = _request({"teamPreview": True, "side": side})
    hurt_lead = _seated(preview, setup.team, frozenset({0, 1})).choices(0, ())[1]
    assert [(meter.current, meter.maximum) for meter in hurt_lead.meters] == [(5, 15)]
    assert hurt_lead.tags[-1].name == "PAR"


@pytest.mark.parametrize(
    ("outcome", "player_hp", "foe_hp", "expected"),
    [
        (None, 10, 0, "won"),
        (None, 0, 5, "lost"),
        (None, 0, 0, "lost"),
        ("fled", 10, 5, "fled"),
        ("caught", 10, 5, "caught"),
    ],
)
def test_each_outcome_reads_the_dump(
    outcome: Outcome | None, player_hp: int, foe_hp: int, expected: Outcome
) -> None:
    dump = Dump(
        p1=(
            DumpMon(
                slot=0,
                hp=player_hp,
                status="",
                pp=(40, 60),
                out=1,
                held=True,
                active=True,
                boosts={},
            ),
        ),
        p2=(
            DumpMon(
                slot=0,
                hp=foe_hp,
                status="fnt" if foe_hp == 0 else "par",
                pp=(50,),
                out=1,
                held=True,
                active=True,
                boosts={},
            ),
        ),
    )

    result = battle_result(WILD_SETUP, dump, outcome, ())

    assert result.outcome == expected
    assert result.team[0].hp == player_hp
    assert [move.pp for move in result.team[0].moves] == [40, 60]
    assert result.on_field_mon_ids == ("pikachu",)
    assert [foe.mon_id for foe in result.fainted_foes()] == (
        [RATTATA.mon_id] if foe_hp == 0 else []
    )
    if expected == "caught":
        assert result.caught is not None
        assert (result.caught.hp, result.caught.status) == (foe_hp, "par")
    else:
        assert result.caught is None


def test_the_sent_out_foes_keep_their_team_order_and_leave_out_the_bench() -> None:
    third = RATTATA.model_copy(update={"mon_id": "rattata-2"})
    setup = BattleSetup.model_validate(
        {
            **WILD_SETUP.model_dump(),
            "policy": "scripted",
            "foe_id": "rook",
            "foe_name": "Rook",
            "foe_avatar_id": "camper",
            "foes": (RATTATA, PIKACHU, third),
        }
    )
    # Showdown lists the active Pokemon first: the one switched in, then the lead it replaced.
    dump = Dump(
        p1=(
            DumpMon(
                slot=0, hp=10, status="", pp=(40, 60), out=1, held=True, active=True, boosts={}
            ),
        ),
        p2=(
            DumpMon(slot=1, hp=5, status="", pp=(40, 60), out=1, held=True, active=True, boosts={}),
            DumpMon(slot=0, hp=0, status="fnt", pp=(50,), out=1, held=True, active=True, boosts={}),
            DumpMon(slot=2, hp=15, status="", pp=(56,), out=0, held=True, active=False, boosts={}),
        ),
    )

    result = battle_result(setup, dump, "lost", ())

    assert [foe.mon_id for foe in result.sent_out_foes] == [RATTATA.mon_id, PIKACHU.mon_id]
    assert [foe.mon_id for foe in result.fainted_foes()] == [RATTATA.mon_id]


async def test_a_tag_battle_puts_both_teams_on_p1_and_the_ally_leads_second() -> None:
    draft = _battling(TAG_SETUP)
    simulator = ScriptedSimulator([*blocks_started(TAG_SETUP), *moving(TAG_SETUP)])
    run = await ShowdownRun.start(draft, simulator)
    team = json.loads(simulator.sent[1].removeprefix(">player p1 "))["team"]

    assert [mon.partition("|")[0] for mon in team.split("]")] == [
        "Pikachu",
        "Pidgey",
        "Charmander",
        "Rattata",
    ]
    assert [choice.command for choice in run.choices()] == ["team 1", "team 2", "leave"]
    await run.choose(draft, "team 2", Random(0))
    assert run.inputs == [">p1 team 2, 3", ">p2 team 1, 2"]


def test_a_tag_player_plays_their_slot_and_switches_only_to_their_own_pokemon() -> None:
    tackle: JsonValue = {"move": "Tackle", "id": "tackle", "pp": 56, "maxpp": 56}
    side = _tag_side("24/24", "18/18")
    request = _request({"active": [{"moves": [tackle]}, {"moves": [tackle]}], "side": side})
    player = _seated(request, TAG_ORDER, frozenset({0, 2}))
    ally = _seated(request, TAG_ORDER, frozenset({1, 3}), 1)

    assert (player.deciding_slots(), ally.deciding_slots()) == ((0,), (1,))
    assert [choice.command for choice in player.choices(0, ())] == ["move 1", "switch 3"]


def test_a_tag_player_keeps_their_slot_when_a_drag_brings_in_the_ally_pokemon() -> None:
    tackle: JsonValue = {"move": "Tackle", "id": "tackle", "pp": 56, "maxpp": 56}
    # A drag on the player's Pikachu brought in the ally's Rattata.
    pokemon = (("Rattata", True), ("Charmander", True), ("Pidgey", False), ("Pikachu", False))
    side: JsonValue = {
        "pokemon": [
            {"ident": f"p1: {name}", "details": name, "condition": "15/15", "active": active}
            for name, active in pokemon
        ]
    }
    request = _request({"active": [{"moves": [tackle]}, {"moves": [tackle]}], "side": side})
    dragged = (RATTATA, CHARMANDER, PIDGEY, PIKACHU)
    player = _seated(request, dragged, frozenset({2, 3}))

    assert player.deciding_slots() == (0,)
    choices = player.choices(0, ())
    assert [choice.command for choice in choices] == ["move 1", "switch 3", "switch 4"]
    assert choices[0].tags[0] == Tag(name="Normal", colour="#a8a878")
    assert _seated(request, dragged, frozenset({0, 1}), 1).deciding_slots() == (1,)


def test_a_tag_trainer_with_no_pokemon_left_leaves_the_slot_to_the_partner() -> None:
    fallen = _request({"forceSwitch": [True, False], "side": _tag_side("0 fnt", "0 fnt")})

    assert _seated(fallen, TAG_ORDER, frozenset({0, 2})).deciding_slots() == ()
    assert _seated(fallen, TAG_ORDER, frozenset({1, 3}), 1).deciding_slots() == (0,)


def test_a_tag_battle_result_leaves_out_the_ally_pokemon() -> None:
    dump = Dump(
        p1=(
            DumpMon(
                slot=0, hp=10, status="", pp=(40, 60), out=1, held=True, active=True, boosts={}
            ),
            DumpMon(
                slot=2, hp=0, status="fnt", pp=(50, 40), out=1, held=True, active=True, boosts={}
            ),
            DumpMon(slot=1, hp=18, status="", pp=(56,), out=0, held=True, active=False, boosts={}),
            DumpMon(slot=3, hp=15, status="", pp=(56,), out=0, held=True, active=False, boosts={}),
        ),
        p2=(
            DumpMon(slot=0, hp=0, status="fnt", pp=(56,), out=1, held=True, active=True, boosts={}),
            DumpMon(slot=1, hp=0, status="fnt", pp=(56,), out=1, held=True, active=True, boosts={}),
        ),
    )

    result = battle_result(TAG_SETUP, dump, None, ())

    assert result.outcome == "won"
    assert [battler.mon_id for battler in result.team] == ["pikachu", "pidgey"]
    assert result.on_field_mon_ids == ("pikachu",)


def test_a_packed_pokemon_carries_its_spread_item_and_friendship() -> None:
    pikachu = PIKACHU.model_copy(
        update={
            "item_id": "oran-berry",
            "ivs": (31, 0, 31, 31, 31, 30),
            "evs": (4, 0, 0, 252, 0, 252),
        }
    )

    assert packed(pikachu) == (
        "Pikachu|pikachu|oran-berry|Static|thundershock,growl|Hardy|4,0,0,252,0,252|M"
        "|31,0,31,31,31,30||7|70"
    )


def test_an_item_used_up_in_battle_is_gone_after_it() -> None:
    pikachu = PIKACHU.model_copy(update={"item_id": "oran-berry"})
    kept = DumpMon(slot=0, hp=24, status="", pp=(48, 64), out=1, held=True, active=True, boosts={})

    assert as_dumped(pikachu, kept).item_id == "oran-berry"
    assert as_dumped(pikachu, kept.model_copy(update={"held": False})).item_id is None


async def test_a_champions_battle_brings_four_of_six_and_each_side_mega_evolves_once() -> None:
    draft = StubBattleGame(StubBattleWorld(Battle(setup=CHAMPIONS_SETUP, inputs=[])))
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded(RECORDED_CHAMPIONS)))
    first = run.choices()
    assert [choice.command for choice in first] == [f"team {at}" for at in range(1, 7)] + ["leave"]
    assert {choice.group for choice in first[:6]} == {"Lead 1"}
    await run.choose(draft, "team 3", Random(0))
    assert run.choices()[2].refusal == "Picked: Lead 1"
    await run.choose(draft, "back", Random(0))
    for command in ("team 3", "team 1", "team 5", "team 2"):
        await run.choose(draft, command, Random(0))
    assert run.inputs[0] == ">p1 team 3, 1, 5, 2"
    assert run.dump is not None and (len(run.dump.p1), len(run.dump.p2)) == (4, 4)

    await run.choose(draft, "move 1", Random(0))
    assert "mega" not in [choice.command for choice in run.choices()]
    await run.choose(draft, "move 1 1", Random(0))
    assert "mega" in [choice.command for choice in run.choices()]
    await run.choose(draft, "mega", Random(0))
    assert [choice.name for choice in run.choices() if choice.kind == "mega"] == [
        "Mega Evolution: on"
    ]
    await run.choose(draft, "move 1", Random(0))

    assert run.inputs[2] == ">p1 move 1 1, move 1 mega"
    assert run.inputs[3].endswith(" mega")
    assert not [choice for choice in run.choices() if choice.kind == "mega"]
    charizard = next(mon for mon in run.header().fielded if mon.name == "Charizard")
    assert "Mega" in [tag.name for tag in charizard.tags]
    assert charizard.sprite == mon_sprite(dex().species["charizardmegay"])
    await run.choose(draft, "leave", Random(0))
    (result,) = draft.world.results
    assert len(result.team) == 4


async def test_the_model_opponent_picks_its_four_and_mega_evolves() -> None:
    setup = CHAMPIONS_SETUP.model_copy(update={"policy": "model"})
    draft = StubBattleGame(StubBattleWorld(Battle(setup=setup, inputs=[])))
    blocks = recorded(RECORDED_CHAMPIONS)
    # Turn 2 asks for one more assessment before the player forfeits.
    blocks.insert(10, blocks[6])
    answers = (
        ("team 1", "team 6", "team 3", "team 4"),
        ("move 2 2", "move 2 1 mega"),
        ("move 4", "move 1 1"),
    )
    asked: list[Prompt] = []

    async def opponent[M: BaseModel](prompt: Prompt, model: type[M], check: Check[M]) -> M:
        answer = model.model_validate({"commands": answers[len(asked)]})
        asked.append(prompt)
        check(answer)
        return answer

    run = await ShowdownRun.start(draft, ScriptedSimulator(blocks), opponent)
    for command in ("team 3", "team 1", "team 5", "team 2", "move 1", "move 1 1", "move 1"):
        await run.choose(draft, command, Random(0))
    await run.choose(draft, "leave", Random(0))

    assert run.inputs[1] == ">p2 team 1, 6, 3, 4"
    assert run.inputs[3] == ">p2 move 2 2, move 2 1 mega"
    golden(FIXTURES / "prompts" / "pokemon-champions" / "preview.txt", masked(asked[0].text))
    golden(FIXTURES / "prompts" / "pokemon-champions" / "opponent.txt", masked(asked[1].text))


def test_a_champions_battle_names_its_format_and_restores_nothing() -> None:
    lines = start_lines(CHAMPIONS_SETUP)

    assert json.loads(lines[0].removeprefix(">start "))["formatid"] == (
        f"{CHAMPIONS_SETUP.format_id}@@@!Open Team Sheets"
    )
    assert not [line for line in lines if line.startswith(">eval const states")]
    with pytest.raises(ValidationError, match="format_id"):
        _ = BattleSetup.model_validate({**CHAMPIONS_SETUP.model_dump(), "format_id": "gen9foo"})


def test_stat_points_give_the_stats_showdown_shows() -> None:
    charizard = dex().species["charizard"]

    shown = stats(charizard, 50, "Timid", CHARIZARD.ivs, CHARIZARD.evs, stat_points=True)

    assert shown == (155, 93, 98, 161, 105, 167)


def test_the_start_lines_send_each_side_its_avatar() -> None:
    lines = start_lines(WILD_SETUP)

    assert json.loads(lines[1].removeprefix(">player p1 "))["avatar"] == "ethan"
    assert json.loads(lines[2].removeprefix(">player p2 "))["avatar"] == ""


def test_a_wild_battle_with_a_foe_avatar_is_refused() -> None:
    wild = WILD_SETUP.model_dump()

    with pytest.raises(ValidationError, match="only a trainer battle, has a foe_avatar_id"):
        _ = BattleSetup.model_validate({**wild, "foe_avatar_id": "camper"})


def _battling(setup: BattleSetup, inputs: list[str] | None = None) -> PokemonGame:
    draft = started().draft()
    draft.world.player_sheet.team = [Mon.from_battler(mon, "met in a test") for mon in setup.team]
    draft.world.battle = Battle(setup=setup, inputs=inputs or [])
    return draft


def _seated(
    request: SideRequest, battlers: tuple[Battler, ...], hand: Hand, slot: int = 0
) -> SeatRequest:
    return SeatRequest(
        request=request,
        battlers=battlers,
        foe_side=request.side,
        hand=hand,
        slots=frozenset({slot}),
        spec=WILD_SETUP.format_spec(),
    )


def _request(request: JsonValue) -> SideRequest:
    return parse_json(SideRequest, json.dumps(request))


def _side(*pokemon: tuple[str, bool]) -> JsonValue:
    return {
        "pokemon": [
            {
                "ident": "p2: Rattata",
                "details": f"Rattata, L{level}",
                "condition": condition,
                "active": active,
            }
            for level, (condition, active) in enumerate(pokemon, 1)
        ]
    }


def _tag_side(lead: str, bench: str) -> JsonValue:
    # After `team 1, 3`: the two leads, then the player's bench, then the ally's.
    pokemon = (
        ("Pikachu", lead, True),
        ("Charmander", "26/26", True),
        ("Pidgey", bench, False),
        ("Rattata", "15/15", False),
    )
    return {
        "pokemon": [
            {"ident": f"p1: {name}", "details": name, "condition": condition, "active": active}
            for name, condition, active in pokemon
        ]
    }
