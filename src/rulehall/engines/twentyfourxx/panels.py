from rulehall.core.play import PendingOption
from rulehall.core.views import Panel, PanelRow, Tag
from rulehall.engines.twentyfourxx.world import (
    UPGRADE_COST,
    WORK_AT,
    Crewmate,
    Gear,
    TwentyFourXXWorld,
)


def gear_rows(world: TwentyFourXXWorld, actor: Crewmate) -> tuple[PanelRow, ...]:
    if actor.sheet is None:
        return ()
    return tuple(
        PanelRow(
            name=item.name,
            brief="",
            tags=_mark_tags(item),
            options=(
                PendingOption(
                    id="stow",
                    name="Stow in the hold",
                    action_name="stow_item",
                    args={"item_id": key, "actor_id": actor.id},
                    refusal=world.ship_refusal(),
                ),
                PendingOption(
                    id="drop",
                    name="Drop",
                    action_name="drop_item",
                    args={"item_id": key, "actor_id": actor.id},
                ),
            ),
        )
        for key, item in actor.sheet.items.items()
    )


def crew_rows(world: TwentyFourXXWorld, member: Crewmate) -> tuple[PanelRow, ...]:
    if not member.hired:
        return ()
    let_go = PendingOption(
        id="let-go", name="Let go", action_name="let_go", args={"target_id": member.id}
    )
    return (*gear_rows(world, member), PanelRow(name="Hired crew", brief="", options=(let_go,)))


def ship_panel(world: TwentyFourXXWorld) -> Panel:
    functions = tuple(
        PanelRow(
            name=function.name,
            brief="",
            tags=_mark_tags(function),
            options=(
                PendingOption(
                    id="upgrade",
                    name=f"Upgrade (₡{UPGRADE_COST})",
                    action_name="ship_upgrade",
                    args={"function_id": key},
                    refusal=world.upgrade_refusal(),
                ),
            ),
        )
        for key, function in world.ship.items()
    )
    receivers = (
        (world.player, "Take it"),
        *((member, f"Give to {member.name}") for member in world.hired_party_members()),
    )
    held = tuple(
        PanelRow(
            name=item.name,
            brief="",
            tags=(Tag(name="in the hold"), *_mark_tags(item)),
            options=tuple(
                PendingOption(
                    id=f"retrieve-{crewmate.id}",
                    name=name,
                    action_name="retrieve_item",
                    args={"item_id": key, "actor_id": crewmate.id},
                    refusal=world.ship_refusal(),
                )
                for crewmate, name in receivers
            ),
        )
        for key, item in world.hold.items()
    )
    return Panel(title="Ship", rows=(*functions, *held))


def job_panel(world: TwentyFourXXWorld) -> tuple[Panel, ...]:
    if world.job:
        return (Panel(title="Job", rows=(PanelRow(name=world.job, brief=""),)),)
    if not (where := world.looked_at()):
        return ()
    # SRD: "Spend ₡1 to re-roll" any find, until a job is taken.
    look_again = PendingOption(
        id="look-again",
        name="Pay ₡1 and look again",
        action_name="find_again",
        args={"where": where},
        told_in_turn=True,
    )
    options = (look_again,) if world.player.require_sheet().credits >= 1 else ()
    row = PanelRow(name=f"{WORK_AT}{where}", brief="", options=options)
    return (Panel(title="Job", rows=(row,)),)


def _mark_tags(gear: Gear) -> tuple[Tag, ...]:
    return tuple(Tag(name=mark) for mark in gear.marks())
