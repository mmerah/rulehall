import pytest
from pydantic import BaseModel
from support.table import TWENTYFOURXX, game, narrowed, stub_worldsmith
from support.twentyfourxx import ENGINE, KESTREL, SABLE, SCENE_BASE, small_world

from rulehall.core.game import Check, WorldsmithRequest
from rulehall.core.log import LogEntry
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.packs import SRD_PACK
from rulehall.engines.twentyfourxx.engine import COMPLICATION, DEPARTURE, FLIGHT
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame

COMM = "comm"
CLIMBING_GEAR = "climbing-gear"
NIGHT_VISION_GOGGLES = "night-vision-goggles"
NEXT_FIELDS = {**SCENE_BASE, "present_ids": (KESTREL,), "hidden_ids": (SABLE,)}


def _twentyfourxx_game() -> tuple[AnyEngine, TwentyFourXXGame]:
    engine, state = game(TWENTYFOURXX)
    state = narrowed(state, TwentyFourXXGame)
    return engine, state


def test_the_shipped_game_begins_with_the_srd_pack_and_the_operators_gear() -> None:
    _, state = _twentyfourxx_game()
    assert state.pack_id == SRD_PACK
    world = state.world
    assert list(world.player.require_sheet().items) == [COMM, CLIMBING_GEAR, NIGHT_VISION_GOGGLES]
    assert world.scene.place_id == "docking-ring"


def test_master_sections_shows_hidden_entities() -> None:
    world = small_world()
    sections = dict(ENGINE.master_sections(world))
    assert "Sable" in sections["HIDDEN HERE (the player has not found these)"]


async def test_the_ship_stays_where_it_docked_unless_the_crew_flies_it() -> None:
    draft = small_world()
    draft.world.dock_here()
    handlers = ENGINE.request_handlers()

    async def go(kind: str, location: str) -> None:
        answer = {**NEXT_FIELDS, "location": location, "recap": "They moved on."}
        request = WorldsmithRequest(kind=kind, detail="Onward.")
        _ = await handlers[kind].write(draft, request, stub_worldsmith(answer))

    await go(DEPARTURE, "The outer moon")
    assert not draft.world.ship_here()
    await go(DEPARTURE, "The cargo station")
    assert draft.world.ship_here()
    await go(FLIGHT, "The outer moon")
    assert draft.world.ship_here()


async def test_install_next_appends_a_run_ends_brief_hindrances_and_returns_the_opened_fact() -> (
    None
):
    draft = small_world().draft()
    draft.world.player.require_sheet().hindrances.extend(["Brief: a burn", "Limping"])
    # A chapter with no exchanges yet is dropped, not appended to; give it one first.
    draft.chapters[-1].entries.append(LogEntry(words="They wait.", lines=()))
    chapters_before = len(draft.chapters)
    recap = "They leave the mess behind and press on toward what waits next."
    resolution = await ENGINE.request_handlers()[DEPARTURE].write(
        draft,
        WorldsmithRequest(kind=DEPARTURE, detail="Onward."),
        stub_worldsmith({**NEXT_FIELDS, "recap": recap}),
    )
    assert len(draft.chapters) == chapters_before + 1
    assert any(fact.card.startswith("New scene:") for fact in resolution.facts)
    assert draft.world.player.require_sheet().hindrances == ["Limping"]
    # `install_next` stamps the recap on the chapter being left, not the fresh one it opens.
    assert draft.chapters[-2].recap == recap
    assert draft.chapters[-1].recap == ""


async def test_the_arrival_cue_carries_neither_the_pursuit_nor_the_players_words() -> None:
    draft = small_world().draft()
    draft.chapters[-1].entries.append(LogEntry(words="They slip out to the fuel tender.", lines=()))
    resolution = await ENGINE.request_handlers()[DEPARTURE].write(
        draft,
        WorldsmithRequest(kind=DEPARTURE, detail="fly the tender out to the platform"),
        stub_worldsmith({**NEXT_FIELDS, "recap": "They fled."}),
    )
    assert resolution.narrator_cue is not None
    assert "fuel tender" not in resolution.narrator_cue
    assert "platform" not in resolution.narrator_cue
    assert "own ship" not in resolution.narrator_cue

    flight = await ENGINE.request_handlers()[FLIGHT].write(
        draft,
        WorldsmithRequest(kind=FLIGHT, detail="fly out to the platform"),
        stub_worldsmith({**NEXT_FIELDS, "recap": "They flew."}),
    )
    assert flight.narrator_cue is not None
    assert "own ship" in flight.narrator_cue


async def test_a_complication_that_names_a_new_location_is_refused() -> None:
    async def travelling[M: BaseModel](_prompt: Prompt, model: type[M], check: Check[M]) -> M:
        answer = model.model_validate(
            {**NEXT_FIELDS, "location": "The village", "recap": "A crew broke in."}
        )
        check(answer)
        return answer

    with pytest.raises(Refusal, match="a complication happens where the player is"):
        _ = await ENGINE.request_handlers()[COMPLICATION].write(
            small_world().draft(),
            WorldsmithRequest(kind=COMPLICATION, detail="A crew breaks in."),
            travelling,
        )
