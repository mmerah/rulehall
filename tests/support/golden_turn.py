import json
from collections.abc import Callable
from functools import partial

from rulehall.core.model import AnyGame
from rulehall.core.play import Chapter, Exchange, SpokenLine
from rulehall.core.validation import EngineId
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.scenes.world import Scene
from support.table import Scripted, tool_call

NARRATION = "The flagstone lifts. Beyond the door, something shifts its weight and waits."

LISTENING = tool_call(
    "change_tags",
    actor_id="player",
    kind="condition",
    gained=["Listening"],
)


def _one_exchange(state: AnyGame, words: str, said: str) -> AnyGame:
    """One prior exchange at the starting scene: RECENT PLAY has to render it."""
    draft = state.draft()
    chapter = draft.log[0]
    chapter.exchanges.append(
        Exchange(words=words, lines=(SpokenLine(text=said),), context=chapter.context)
    )
    return draft.commit()


def _loner4e_behind(state: AnyGame) -> AnyGame:
    """One turn in the scene before this one: RECENT PLAY groups by scene, not title."""
    draft = state.draft()
    context = draft.log[-1].context
    draft.world.scenes.insert(
        0,
        Scene(
            place_id="vault-stair",
            location="The abbey of Saint Corvin",
            title="The Vault Stair",
            situation=(
                "A short flight of steps ends at an iron door, sealed, "
                "the abbey's dust undisturbed on its sill."
            ),
            here=[PLAYER_ID],
        ),
    )
    draft.log.insert(
        0,
        Chapter(
            title="The Vault Stair",
            context=context,
            exchanges=[
                Exchange(
                    words="I try the vault door.",
                    lines=(SpokenLine(text="The iron handle does not turn."),),
                    context=context,
                )
            ],
        ),
    )
    draft.log[-1].exchanges = [
        Exchange(
            words="I look for another way in.",
            lines=(SpokenLine(text="A flagstone by the wall sits proud of its neighbours."),),
            context=context,
        )
    ]
    return draft.commit()


_LONER4E_SCRIPT: tuple[Scripted, ...] = (
    tool_call(
        "ask",
        question="Does he hear what waits past the vault door without being heard?",
        helps=["Quiet Hands"],
    ),
    LISTENING,
    tool_call("close_scene", reason="resolved"),
    tool_call("direct", text="what waits past the door has weight, and it knows he is there"),
)

# The Loner script closes the scene, so the worldsmith writes the next one after the turn.
ARRIVALS: dict[EngineId, str] = {
    EngineId("loner4e"): json.dumps(
        {
            "place_id": "vault-door",
            "title": "The Vault Door",
            "situation": "An iron door at the foot of the stair, its seal crusted with old wax.",
            "recap": "He listened at the vault door and heard something waiting.",
            "goal": "Get past the vault door",
            "details": ["Crusted Wax Seal", "Cold Iron"],
        }
    )
}

_TUNNELGOONS_SCRIPT: tuple[Scripted, ...] = (
    tool_call("move", to_id="cellar"),
    tool_call(
        "roll",
        what="Wade through the flooded cellar",
        ability="skulker",
        difficulty=10,
        dangerous=True,
    ),
    tool_call("reveal", target_id="lurker"),
    tool_call("direct", text="the flooded dark has already noticed them, and it is close"),
)

_TWENTYFOURXX_SCRIPT: tuple[Scripted, ...] = (
    tool_call("join_party", target_id="vessa-rune"),
    tool_call("reveal", target_id="warden-six"),
    tool_call(
        "roll", what="Slip along the dark gantry", skill="Stealth", risk="a fall", committed=True
    ),
    tool_call("spend", amount=1, why="Harl's docking logs"),
    tool_call("direct", text="the gantry holds, but the watch above is turning their way"),
)

_POKEMON_SCRIPT: tuple[Scripted, ...] = (
    tool_call(
        "check",
        what="Spot what moves in the tall grass",
        skill="perception",
        difficulty="easy",
    ),
    tool_call("direct", text="Rook has seen the new trainer, and he wants a battle"),
)

SCRIPTS: dict[EngineId, tuple[tuple[Scripted, ...], Callable[[AnyGame], AnyGame]]] = {
    EngineId("loner4e"): (_LONER4E_SCRIPT, _loner4e_behind),
    EngineId("tunnelgoons"): (
        _TUNNELGOONS_SCRIPT,
        partial(
            _one_exchange,
            words="I look around the archway before going further.",
            said="Grix waves you toward the corridor, impatient.",
        ),
    ),
    EngineId("twentyfourxx"): (
        _TWENTYFOURXX_SCRIPT,
        partial(
            _one_exchange,
            words="I look around the docking ring before going further.",
            said="Vessa Rune watches you from the airlock.",
        ),
    ),
    EngineId("pokemon"): (
        _POKEMON_SCRIPT,
        partial(
            _one_exchange,
            words="I look along the harbour road before going further.",
            said="Rook waves at you from the tall grass.",
        ),
    ),
}
