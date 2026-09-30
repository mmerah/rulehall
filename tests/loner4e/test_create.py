from pathlib import Path

import pytest
from support.game import ENGINE, loner_sheet
from support.table import LIBRARY, NO_SHIPPED, narrowed

from rulehall.core.creation import Picks
from rulehall.core.stores import Library
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.loner4e.rules import LUCK_MAX
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.packs import SRD_PACK
from rulehall.engines.sheet import PLAYER_ID


def test_a_created_character_plays_through_the_authored_load_path(tmp_path: Path) -> None:
    picks: Picks = {
        "concept": "A wandering scribe who counts doors",
        "goal": "Count every door in the old city",
        "motive": "The tally is the only thing that still makes sense",
        "nemesis": "The Door Wardens",
        "skill-1": "quiet-hands",
        "skill-2": "Hears Hinges Sing",
        "frailty": "never-walks-away",
        "gear-1": "pry-bar",
        "gear-2": "chalk-and-wire",
    }
    created = ENGINE.create_character(
        "Fen", "A wandering scribe with too many questions.", "masculine", SRD_PACK, picks
    )
    library = Library(tmp_path, tmp_path, NO_SHIPPED)
    library.write_character(created)
    character = library.read_character("fen", ENGINE.id, ENGINE.character_model)
    scenario = LIBRARY.read_scenario("whispering-vault", {ENGINE.id: ENGINE.scenario_model})
    state = ENGINE.begin("whispering-vault", scenario, character)
    state = narrowed(state, Loner4eGame)
    made = loner_sheet(state, PLAYER_ID)
    assert made.concept == "A wandering scribe who counts doors"
    assert made.tags == {
        "skill": ["Quiet Hands", "Hears Hinges Sing"],
        "frailty": ["Never Walks Away"],
        "gear": ["Pry Bar", "Chalk and Wire"],
    }
    assert made.luck.current == LUCK_MAX
    assert made.nemesis == "The Door Wardens"


def test_an_illegal_pick_set_is_refused_with_the_reason(tmp_path: Path) -> None:
    legal = _answered(SRD_PACK, {})
    with pytest.raises(Refusal, match="no creation step"):
        ENGINE.create_character("Fen", "", "masculine", SRD_PACK, {**legal, "class": "fighter"})
    with pytest.raises(Refusal, match="is unanswered"):
        ENGINE.create_character(
            "Fen",
            "",
            "masculine",
            SRD_PACK,
            {key: value for key, value in legal.items() if key != "gear-2"},
        )
    with pytest.raises(Refusal, match="is unanswered"):
        ENGINE.create_character("Fen", "", "masculine", SRD_PACK, {**legal, "concept": "  "})
    created = ENGINE.create_character("Fen", "", "masculine", SRD_PACK, legal)
    library = Library(tmp_path, tmp_path, NO_SHIPPED)
    library.write_character(created)
    with pytest.raises(Refusal, match="already exists"):
        library.write_character(created)


def _answered(pack_id: Slug, chosen: Picks) -> Picks:
    """Answers each step with its first option, so later steps appear as earlier ones land."""
    picks = dict(chosen)
    while step := next(
        (
            candidate
            for candidate in ENGINE.creation_steps(pack_id, picks)
            if candidate.id not in picks
        ),
        None,
    ):
        picks[step.id] = step.options[0].id if step.options else "Something written"
    return picks
