from collections.abc import Mapping

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.views import Meter, Panel, PanelRow
from rulehall.engines.loner4e.rules import DOUBLES_PER_TWIST, SceneKind
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.loner4e.world import Loner4eWorld
from rulehall.engines.panels import character_panel
from rulehall.engines.sheet import Gauge

SHEET_HELP = {
    "Concept": "Who this character is, in one line; growing at an adventure's end can reword it.",
    "Skills": "What this character is good at: one that bears on a question tips the oracle's "
    "dice their way.",
    "Frailties": "Weak spots: one that bears on a question tips the oracle's dice against them.",
    "Gear": "What this character carries: an item that bears on a question tips the oracle's "
    "dice their way.",
    "Conditions": "Lasting states the story gave, such as a wound or a curse; one that bears on "
    "a question tips the oracle's dice.",
    "Relationships": "Ties to other people; one that bears on a question tips the oracle's dice.",
    "Goal": "What this character wants; reaching it, or losing it for good, can end the adventure.",
    "Motive": "Why this character wants their goal.",
    "Nemesis": "Who or what stands against this character.",
    "Luck": "How long this character holds out in a fight: each lost exchange costs some, and it "
    "refills when a fight starts or ends and in every quiet scene.",
    "Twist Counter": "Doubles on the oracle's dice outside a fight add one; at "
    f"{DOUBLES_PER_TWIST} a twist shakes up the scene.",
}
SCENE_HELP: dict[SceneKind, str] = {
    "dramatic": "A scene of pressure and risk around its goal; it ends when the goal is reached, "
    "blocked or given up, or when you move on.",
    "quiet": "A pause whose aim you chose: it lasts until you move on or it tips into danger.",
}
SCENE_GOAL_HELP = "What this scene is about; it closes once this is reached, blocked or given up."
PLACE_HELP = "What is true here; each detail can help or hinder when the oracle is asked."
CONFLICT_HELP = (
    "A Harm & Luck fight is on: every question is an exchange, and a side at 0 luck is beaten."
)
TAKE_BREATHER = ActionOption(
    id="breather",
    name="Take the breather",
    help="Type how you rest; luck refills.",
    action_name="take_breather",
    needs_words=True,
)
MOVE_ON = ActionOption(
    id="move-on",
    name="Move on",
    help="Leave this scene; the dice decide what kind of scene comes next.",
    action_name="move_on",
)
END_ADVENTURE = ActionOption(
    id="end",
    name="End",
    help="Offer to close the story here; you confirm before it ends.",
    action_name="offer_end",
)
BREAK_AWAY = ActionOption(
    id="break-away",
    name="Break away",
    help="Stop fighting; you always get away, but the story sets the price.",
    action_name="withdraw",
)
ASK_ORACLE = ActionOption(
    id="ask",
    name="Ask",
    help="Type a yes/no question for the dice.",
    action_name="ask_oracle",
    needs_words=True,
)
FIGHT_GROUP = "Fight"
ROLL_INSPIRATION = ActionOption(
    id="inspiration",
    name="Inspire",
    help="Roll a verb, an adjective and a noun for a question no yes or no can answer.",
    action_name="roll_inspiration",
    told_in_turn=True,
)
PLAY_ON = ActionOption(id="play-on", name="Play on", action_name="play_on")
ENDING_PROMPT = "The adventure could end here: {why}. End it, or play on?"
OWN_ENDING_PROMPT = "End the adventure here, or play on?"
PLAYER_ENDS = "the player chose to end it here"
GROWTH_PROMPT = "What did {name} learn?"
WRITE_LIVING_WORLD = ActionOption(
    id="living-world",
    name="Write the Living World",
    help="Try again to write what became of the people and places you met.",
    action_name="request_living_world",
)
UNWRITTEN_PROMPT = "The adventure is over, and the Living World is still to be written."


def sheet_panel(world: Loner4eWorld, sheet_help: Mapping[str, str]) -> Panel:
    player = world.player
    return character_panel(
        player.subject(),
        player.traits(),
        _meter_row("Luck", player.luck, sheet_help),
        _meter_row("Twist Counter", world.twist, sheet_help),
        sheet_help=sheet_help,
    )


def scene_panel(world: Loner4eWorld) -> Panel:
    frame = world.frame
    rows = [
        PanelRow(name="Goal", brief=frame.goal, help=SCENE_GOAL_HELP),
        PanelRow(name="The place", brief=", ".join(frame.details), help=PLACE_HELP),
    ]
    if world.opponent_ids:
        facing = ", ".join(
            f"{opponent.name}: luck {opponent.luck}"
            for opponent in map(world.require_entity, world.opponent_ids)
        )
        rows.append(PanelRow(name="Conflict", brief=facing, help=CONFLICT_HELP))
    return Panel(
        title=f"{frame.kind.capitalize()} scene", rows=tuple(rows), help=SCENE_HELP[frame.kind]
    )


def loner_moves(world: Loner4eWorld, *, played: bool) -> tuple[ActionOption, ...]:
    frame = world.frame
    if world.end_why:
        return ()
    if frame.breather:
        return (TAKE_BREATHER,)
    if not frame.open:
        return (END_ADVENTURE,)
    fights = tuple(
        _fight(other)
        for other in world.others()
        if other.alive and other.id not in world.opponent_ids
    )
    if world.opponent_ids:
        return (ASK_ORACLE, BREAK_AWAY, *fights)
    # A quiet scene moves on only once the player played there, so no loop refills luck.
    if frame.kind == "quiet" and not played:
        return (ASK_ORACLE, ROLL_INSPIRATION, *fights, END_ADVENTURE)
    return (ASK_ORACLE, ROLL_INSPIRATION, MOVE_ON, *fights, END_ADVENTURE)


def proposed_ending_decision(why: str) -> Decision:
    return _ending_decision(why, ENDING_PROMPT.format(why=why.rstrip(".")))


def own_ending_decision() -> Decision:
    return _ending_decision(PLAYER_ENDS, OWN_ENDING_PROMPT)


def growth_decision(name: str) -> Decision:
    return Decision(
        kind="growth", prompt=GROWTH_PROMPT.format(name=name), options=(), allows_text=True
    )


def living_world_decision() -> Decision:
    return Decision(
        kind="living-world",
        prompt=UNWRITTEN_PROMPT,
        options=(WRITE_LIVING_WORLD,),
        allows_text=False,
    )


def _ending_decision(why: str, prompt: str) -> Decision:
    end_it = ActionOption(
        id="end-it",
        name="End it",
        help="End the adventure here; your character then grows from what they lived.",
        action_name="confirm_end",
        args={"why": why},
    )
    return Decision(kind="ending", prompt=prompt, options=(end_it, PLAY_ON), allows_text=False)


def _fight(other: Loner4eEntity) -> ActionOption:
    return ActionOption(
        id=f"fight-{other.id}",
        name=f"Fight {other.name}",
        group=FIGHT_GROUP,
        help=f"Fight {other.name} in Harm & Luck: each lost exchange costs luck, and a side at 0 "
        "is beaten.",
        action_name="fight",
        args={"opponent_id": other.id},
    )


def _meter_row(name: str, gauge: Gauge, sheet_help: Mapping[str, str]) -> PanelRow:
    meter = Meter(name="", current=gauge.current, maximum=gauge.maximum)
    return PanelRow(name=name, brief="", help=sheet_help[name], meters=(meter,))
