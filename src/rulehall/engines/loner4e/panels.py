from rulehall.core.play import PendingDecision, PendingOption
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow
from rulehall.engines.entities import Gauge
from rulehall.engines.loner4e.rules import STATUS_BOXES, STATUS_TAGS
from rulehall.engines.loner4e.world import Loner4eWorld
from rulehall.engines.panels import character_panel

TAKE_BREATHER = PendingOption(
    id="breather",
    name="Take the breather",
    brief="Say what you do with this quiet window.",
    action_name="take_breather",
)
RECOVER = PendingOption(
    id="recover",
    name="Recover",
    brief="Spend the quiet scene resting: it clears the newest box.",
    action_name="recover",
    told_in_turn=True,
)
MOVE_ON = PendingOption(
    id="move-on",
    name="Move on",
    brief="Leave this scene; the dice say what comes next.",
    action_name="move_on",
)
END_HERE = PendingOption(id="end", name="End the adventure", action_name="confirm_end")
BREAK_AWAY = PendingOption(
    id="break-away",
    name="Break away",
    brief="Always allowed, never free: the story sets the price.",
    action_name="withdraw",
)
STATUS_PROMPT = "Does this defeat leave a lasting mark?"
NO_MARK = PendingOption(
    id="none", name="No lasting mark", action_name="mark_status", args={"column": None}
)
ASK_ORACLE = PendingOption(
    id="ask",
    name="Ask the oracle",
    brief="Type one yes/no question.",
    action_name="ask_oracle",
)
PLAY_ON = PendingOption(id="play-on", name="Play on", action_name="play_on")
ENDING_PROMPT = "The adventure could end here: {why}. End it, or play on?"
GROWTH_PROMPT = "What did {name} learn?"
WRITE_LIVING_WORLD = PendingOption(
    id="living-world", name="Write the Living World", action_name="request_living_world"
)
UNWRITTEN_PROMPT = "The adventure is over, and the Living World is still to be written."


def sheet_panel(world: Loner4eWorld) -> Panel:
    player = world.player
    boxes = Gauge(current=len(world.status.boxes), maximum=STATUS_BOXES)
    ending = PanelRow(name="The adventure", brief="", options=(END_HERE,))
    recovering = world.frame.breather and bool(world.status.boxes) and not world.end_why
    return character_panel(
        player.traits(),
        _meter_row("Luck", player.luck),
        _meter_row("Twist Counter", world.twist),
        _meter_row(
            "Status", boxes, brief=world.status.active, options=(RECOVER,) if recovering else ()
        ),
        *(() if world.end_why else (ending,)),
    )


def scene_panel(world: Loner4eWorld, *, played: bool) -> Panel:
    frame = world.frame
    # A quiet scene moves on only once the player played there, so no loop refills luck.
    idle = frame.kind == "quiet" and not played
    moving = (MOVE_ON,) if _playing(world) and not world.opponent_ids and not idle else ()
    rows = [
        PanelRow(name="Goal", brief=frame.goal, options=moving),
        PanelRow(name="The place", brief=", ".join(frame.details)),
    ]
    if world.opponent_ids:
        facing = ", ".join(
            f"{opponent.name}: luck {opponent.luck}"
            for opponent in map(world.require, world.opponent_ids)
        )
        rows.append(PanelRow(name="Conflict", brief=facing, options=(BREAK_AWAY,)))
    return Panel(title=f"{frame.kind.capitalize()} scene", rows=tuple(rows))


def here_panel(world: Loner4eWorld) -> Panel:
    rows = (
        other.subject().row(
            (_fight(other.id, other.name),)
            if _playing(world) and other.alive and other.id not in world.opponent_ids
            else ()
        )
        for other in world.others()
    )
    return Panel(title="Also here", rows=tuple(rows))


def ending_decision(why: str) -> PendingDecision:
    end_it = PendingOption(id="end-it", name="End it", action_name="confirm_end", args={"why": why})
    return PendingDecision(
        kind="ending",
        prompt=ENDING_PROMPT.format(why=why.rstrip(".")),
        options=(end_it, PLAY_ON),
        allows_text=False,
    )


def growth_decision(name: str) -> PendingDecision:
    return PendingDecision(
        kind="growth", prompt=GROWTH_PROMPT.format(name=name), options=(), allows_text=True
    )


def living_world_decision() -> PendingDecision:
    return PendingDecision(
        kind="living-world",
        prompt=UNWRITTEN_PROMPT,
        options=(WRITE_LIVING_WORLD,),
        allows_text=False,
    )


def status_mark_decision(marked_boxes: int) -> PendingDecision:
    options = tuple(
        PendingOption(
            id=column,
            name=column.capitalize(),
            brief=tags[marked_boxes],
            action_name="mark_status",
            args={"column": column},
        )
        for column, tags in STATUS_TAGS.items()
    )
    return PendingDecision(
        kind="status", prompt=STATUS_PROMPT, options=(*options, NO_MARK), allows_text=False
    )


def _playing(world: Loner4eWorld) -> bool:
    return world.frame.open and not world.end_why


def _fight(opponent_id: Slug, name: str) -> PendingOption:
    return PendingOption(
        id=f"fight-{opponent_id}",
        name="Fight",
        brief=f"Start a Harm & Luck conflict with {name}.",
        action_name="fight",
        args={"opponent_id": opponent_id},
    )


def _meter_row(
    name: str, gauge: Gauge, *, brief: str = "", options: tuple[PendingOption, ...] = ()
) -> PanelRow:
    meter = Meter(name="", current=gauge.current, maximum=gauge.maximum)
    return PanelRow(name=name, brief=brief, meters=(meter,), options=options)
