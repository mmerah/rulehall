from rulehall.core.play import PendingOption
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow
from rulehall.engines.entities import Gauge
from rulehall.engines.loner4e.args import BREAK_AWAY, END_HERE, MOVE_ON, RECOVER
from rulehall.engines.loner4e.rules import STATUS_BOXES
from rulehall.engines.loner4e.world import Loner4eWorld
from rulehall.engines.panels import character_panel


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
