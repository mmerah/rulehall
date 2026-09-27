from collections.abc import Sequence

from rulehall.core.facts import notation
from rulehall.core.play import PendingDecision, PendingOption
from rulehall.core.validation import Slug, slug
from rulehall.core.views import Panel, PanelRow, Tag
from rulehall.engines.twentyfourxx.args import DefendHit, Roll
from rulehall.engines.twentyfourxx.rules import raised
from rulehall.engines.twentyfourxx.sheet import Crewmate, CrewSheet, Gear
from rulehall.engines.twentyfourxx.world import UPGRADE_COST, WORK_AT, TwentyFourXXWorld

MOVE_ON = PendingOption(
    id="move-on",
    name="Move on",
    brief="Say where you go and move on.",
    action_name="move_on",
)
NEWCOMER: Slug = "newcomer"
RAISE_PROMPT = "The job is done. Which skill do you raise? Pick one, or name a new one."
NEWCOMER_PROMPT = "{name} is dead. Who joins the crew? Describe them in your own words."
CANNOT_SUCCEED = "Cannot succeed without help."


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
        id="let-go", name="Let go", action_name="leave_party", args={"target_id": member.id}
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


def newcomer_decision(dead: Crewmate) -> PendingDecision:
    return PendingDecision(
        kind=NEWCOMER,
        prompt=NEWCOMER_PROMPT.format(name=dead.name),
        options=(),
        allows_text=True,
    )


def succession_decision(members: Sequence[Crewmate]) -> PendingDecision:
    return PendingDecision(
        kind="succession",
        prompt="Who leads now?",
        options=tuple(
            PendingOption(
                id=member.id,
                name=member.name,
                brief=member.brief,
                action_name="take_lead",
                args={"actor_id": member.id},
            )
            for member in members
        ),
        allows_text=False,
    )


def raise_decision(sheet: CrewSheet) -> PendingDecision:
    return PendingDecision(
        kind="raise",
        prompt=RAISE_PROMPT,
        options=tuple(
            PendingOption(
                id=slug(skill, ()),
                name=f"{skill} d{die} → d{next_die}",
                action_name="raise_skill",
                args={"skill": skill},
            )
            for skill, die in sheet.skills.items()
            if (next_die := raised(die)) is not None
        ),
        allows_text=True,
    )


def commit_decision(
    attempt: Roll, roll_line: str, actor: Crewmate, faces: tuple[int, ...]
) -> PendingDecision:
    return PendingDecision(
        kind="risk",
        prompt=" ".join(
            part
            for part in (
                f"{roll_line}. Dice: {notation(faces)}, the highest counts.",
                *_burdens(actor),
                CANNOT_SUCCEED if max(faces) < 5 else "",
                "Commit, or revise in your own words.",
            )
            if part
        ),
        options=(
            PendingOption(
                id="commit",
                name="Commit",
                action_name="roll",
                args={**attempt.model_dump(mode="json"), "committed": True},
            ),
        ),
        allows_text=True,
    )


def defence_decision(
    headline: str, hit: DefendHit, defender_id: Slug, defences: Sequence[tuple[Slug, Gear]]
) -> PendingDecision:
    return PendingDecision(
        kind="defence",
        prompt=f"{headline} Break an item to turn it into a brief hindrance, or take it.",
        options=(
            *(
                _defence(f"Break {gear.name}", hit, defender_id, item_id)
                for item_id, gear in defences
            ),
            _defence("Take it", hit, defender_id, None),
        ),
        allows_text=False,
    )


def _mark_tags(gear: Gear) -> tuple[Tag, ...]:
    return tuple(Tag(name=mark) for mark in gear.marks())


def _defence(name: str, hit: DefendHit, defender_id: Slug, item_id: Slug | None) -> PendingOption:
    chosen = hit.model_copy(update={"choices": {**hit.choices, defender_id: item_id}})
    return PendingOption(
        id=item_id or "take-it",
        name=name,
        action_name="defend_hit",
        args=chosen.model_dump(mode="json"),
    )


def _burdens(actor: Crewmate) -> list[str]:
    sheet = actor.require_sheet()
    burdens: list[str] = []
    if sheet.hindrances:
        burdens.append(f"Hindrances: {', '.join(sheet.hindrances)}.")
    if (bulky := sum(item.bulky for item in sheet.items.values())) > 1:
        burdens.append(f"Carries {bulky} bulky items.")
    return burdens
