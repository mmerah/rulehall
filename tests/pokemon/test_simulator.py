import json
from asyncio import sleep
from random import Random

import pytest
from pydantic import BaseModel, JsonValue, ValidationError
from support.pokemon import started
from support.showdown import (
    PIKACHU,
    RATTATA,
    WILD_SETUP,
    ScriptedSimulator,
    assessed,
    ended,
    moving,
    recorded,
)
from support.showdown import started as blocks_started

from rulehall.core.model import Check
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal, Slug, parse_json
from rulehall.core.views import Choice, Tag
from rulehall.engines.engine import Resolution
from rulehall.engines.pokemon.battle.models import (
    Ball,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
    Outcome,
    Throw,
)
from rulehall.engines.pokemon.battle.opponent import OpponentAnswer, check_command
from rulehall.engines.pokemon.battle.simulator import (
    Dump,
    DumpMon,
    ShowdownRun,
    SideRequest,
    as_dumped,
    assess_line,
    battle_result,
    choices_of,
    opponent_choice,
    packed,
    start_lines,
)
from rulehall.engines.pokemon.world import PokemonGame


class EndOnly:
    ended: BattleResult | None = None

    def end_battle(self, draft: PokemonGame, result: BattleResult) -> Resolution:
        self.ended = result
        draft.world.battle = None
        return Resolution((), None)

    def throw_ball(self, _draft: PokemonGame, _ball_id: Slug, _foe: Battler, _rng: Random) -> Throw:
        raise AssertionError("no throw in this test")


async def test_a_recorded_battle_plays_to_its_result() -> None:
    draft, rules = _wild(WILD_SETUP), EndOnly()
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded()), rules)
    while run.result is None:
        command = next(choice.command for choice in run.choices() if not choice.refusal)
        await run.choose(draft, command, Random(0))

    assert run.result.outcome == "won"
    assert run.result.fainted_foes == (RATTATA,)
    assert rules.ended is run.result
    assert run.resolution is not None
    assert draft.world.battle is None
    assert not [line for line in run.log if line.startswith(("||", "|split|", "|-status|"))]


async def test_a_resumed_battle_replays_its_inputs_and_waits_on_the_player() -> None:
    draft = _wild(WILD_SETUP)
    played = ScriptedSimulator(recorded())
    run = await ShowdownRun.start(draft, played, EndOnly())
    await run.choose(draft, "team 1", Random(0))
    await run.choose(draft, "move 1", Random(0))
    assert draft.world.battle is not None
    assert draft.world.battle.inputs == run.inputs

    resumed_draft = draft.commit().draft()
    replayed = ScriptedSimulator(recorded())
    resumed = await ShowdownRun.start(resumed_draft, replayed, EndOnly())

    assert resumed.inputs == run.inputs
    assert resumed.side_request == run.side_request
    assert replayed.sent == played.sent


async def test_the_choices_end_with_the_balls_and_the_way_out() -> None:
    balls = (Ball(item_id="poke-ball", name="Poké Ball", count=1),)
    draft = _wild(WILD_SETUP.model_copy(update={"balls": balls}))
    run = await ShowdownRun.start(draft, ScriptedSimulator(recorded()), EndOnly())
    await run.choose(draft, "team 1", Random(0))

    groups = [(choice.group, choice.command, choice.refusal) for choice in run.choices()]

    assert groups[-2:] == [("Balls", "ball poke-ball", ""), ("", "leave", "")]


async def test_the_model_opponent_thinks_at_the_request_and_its_choice_is_recorded() -> None:
    setup = BattleSetup.model_validate(
        {
            **WILD_SETUP.model_dump(),
            "kind": "trainer",
            "foe_id": "rook",
            "foe_name": "Rook",
            "foe_avatar_id": "camper",
            "foes": (RATTATA, PIKACHU),
        }
    )
    draft = started().draft()
    draft.world.battle = Battle(setup=setup, inputs=[">p1 team 1", ">p2 team 1"])
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
        answer = model.model_validate({"command": "move 1"})
        check(answer)
        return answer

    run = await ShowdownRun.start(draft, simulator, EndOnly(), opponent)
    await sleep(0)
    assert len(asked) == 1
    assert simulator.sent[-1] == assess_line()
    await run.choose(draft, "move 1", Random(0))

    assert len(asked) == 1
    assert run.inputs == [">p1 team 1", ">p2 team 1", ">p1 move 1", ">p2 move 1"]
    assert "Ember 14 to 18 HP" in asked[0].user
    assert run.result is not None and run.result.outcome == "won"


def test_an_answer_outside_the_choices_is_refused_with_the_choices() -> None:
    choices = (
        Choice(command="move 1", name="Tackle"),
        Choice(command="switch 2", name="Rattata", group="Switch"),
    )

    with pytest.raises(Refusal, match="pick one of: move 1, switch 2"):
        check_command(choices, OpponentAnswer(command="move 2"))


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

    assert choices_of(request, WILD_SETUP.team) == (Choice(command="move 1", name="Struggle"),)


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

    move, switch = choices_of(request, setup.team)

    assert move.tags == (Tag(name="Electric", colour="#f8d030"),)
    assert move.brief == "30/48 PP"
    assert switch.command == "switch 2"
    assert switch.tags == (Tag(name="Normal", colour="#a8a878"),)
    assert switch.group == "Switch"
    assert switch.brief == "HP 15/15"
    assert (
        choices_of(_request({"teamPreview": True, "side": side}), setup.team)[1].brief
        == "HP 5/15 par"
    )


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
        p1=(DumpMon(slot=0, hp=player_hp, status="", pp=(40, 60), out=1, held=True),),
        p2=(
            DumpMon(
                slot=0,
                hp=foe_hp,
                status="fnt" if foe_hp == 0 else "par",
                pp=(50,),
                out=1,
                held=True,
            ),
        ),
    )

    result = battle_result(WILD_SETUP, dump, outcome)

    assert result.outcome == expected
    assert result.team[0].hp == player_hp
    assert [move.pp for move in result.team[0].moves] == [40, 60]
    assert result.on_field == ("pikachu",)
    assert result.fainted_foes == ((RATTATA,) if foe_hp == 0 else ())
    if expected == "caught":
        assert result.caught is not None
        assert (result.caught.hp, result.caught.status) == (foe_hp, "par")
    else:
        assert result.caught is None


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
    kept = DumpMon(slot=0, hp=24, status="", pp=(48, 64), out=1, held=True)

    assert as_dumped(pikachu, kept).item_id == "oran-berry"
    assert as_dumped(pikachu, kept.model_copy(update={"held": False})).item_id is None


def test_the_start_lines_send_each_side_its_avatar() -> None:
    lines = start_lines(WILD_SETUP)

    assert json.loads(lines[1].removeprefix(">player p1 "))["avatar"] == "ethan"
    assert json.loads(lines[2].removeprefix(">player p2 "))["avatar"] == ""


def test_a_wild_battle_with_a_foe_avatar_is_refused() -> None:
    wild = WILD_SETUP.model_dump()

    with pytest.raises(ValidationError, match="only a trainer battle, has a foe_avatar_id"):
        _ = BattleSetup.model_validate({**wild, "foe_avatar_id": "camper"})


def _wild(setup: BattleSetup) -> PokemonGame:
    draft = started().draft()
    draft.world.battle = Battle(setup=setup)
    return draft


def _request(request: JsonValue) -> SideRequest:
    return parse_json(SideRequest, json.dumps(request))


def _side(*pokemon: tuple[str, bool]) -> JsonValue:
    return {
        "pokemon": [
            {"details": f"Rattata, L{level}", "condition": condition, "active": active}
            for level, (condition, active) in enumerate(pokemon, 1)
        ]
    }
