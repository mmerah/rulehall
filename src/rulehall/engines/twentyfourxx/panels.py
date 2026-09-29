from collections.abc import Mapping, Sequence

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.facts import notation
from rulehall.core.validation import Slug, slug
from rulehall.core.views import Panel, PanelRow, Tag
from rulehall.engines.panels import character_panel
from rulehall.engines.twentyfourxx.args import DefendHit, Roll
from rulehall.engines.twentyfourxx.rules import DEFAULT_DIE, HINDERED_DIE, LADDER, next_die
from rulehall.engines.twentyfourxx.sheet import Crewmate, CrewSheet, Gear, GearMark
from rulehall.engines.twentyfourxx.world import WORK_AT, TwentyFourXXWorld

SHEET_HELP = {
    "Specialty": "Your trade: it set your starting skills and gear.",
    "Origin": "Where you come from: it gave your traits, your body or your skill increases.",
    "Traits": "Your origin's gifts, such as wings or natural camouflage; use them in what you try.",
    "Skills": f"A skill that applies rolls its die, d{LADDER[0]} to d{LADDER[-1]}, and anything "
    f"else rolls a d{DEFAULT_DIE}; 5 or more succeeds.",
    "Credits": "Money (₡): most gear and upgrades cost ₡1, a ship upgrade ₡10, and a finished job "
    "pays each operator a d6.",
    "Hindrances": "Injuries and fears that slow you; when one bears on a roll, your die drops to "
    f"a d{HINDERED_DIE}.",
    "Gear": "What you carry: bulky items weigh on you, and an item can break to spare you a hit.",
}
SKILL_INCREASE_HELP = (
    f"Raises one skill a step: a new skill starts at {', then '.join(f'd{die}' for die in LADDER)}."
)
MARK_HELP: dict[GearMark, str] = {
    "bulky": "Takes much space; more than one bulky item can hinder your rolls.",
    "harmless": "Breaks with no hindrance left behind.",
    "broken": "Broken gear is useless until someone repairs it; a count such as 1/3 is the breaks "
    "taken so far.",
    "upgraded": "An upgrade bought for this item.",
}
BREAK_HELP = (
    "It breaks and takes the hit; gear leaves a brief hindrance that clears at the next scene."
)
JOB_HELP = "Paid work: when it ends, each operator earns a d6 in credits and you raise a skill."
IN_THE_HOLD = Tag(
    name="in the hold", help="Stowed in the ship's hold; take it back while you are at the ship."
)
MOVE_ON = ActionOption(
    id="move-on",
    name="Move on",
    help="Say where you go; a new scene opens.",
    action_name="move_on",
    needs_words=True,
)
NEWCOMER: Slug = "newcomer"
RAISE_PROMPT = "The job is done. Which skill do you raise? Pick one, or name a new one."
NEWCOMER_PROMPT = "{name} is dead. Who joins the crew? Describe them in your own words."
CANNOT_SUCCEED = "Cannot succeed without help."


def sheet_panel(world: TwentyFourXXWorld, sheet_help: Mapping[str, str]) -> Panel:
    player = world.player
    return character_panel(
        player.subject(), player.rows(), *gear_rows(world, player), sheet_help=sheet_help
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
                ActionOption(
                    id=f"stow-{actor.id}-{key}",
                    name="Stow in the hold",
                    action_name="stow_item",
                    args={"item_id": key, "actor_id": actor.id},
                    refusal=world.ship_refusal(),
                ),
                ActionOption(
                    id=f"drop-{actor.id}-{key}",
                    name="Drop",
                    action_name="drop_item",
                    args={"item_id": key, "actor_id": actor.id},
                ),
            ),
        )
        for key, item in actor.sheet.items.items()
    )


def crew_rows(world: TwentyFourXXWorld, member: Crewmate) -> tuple[PanelRow, ...]:
    if not member.has_sheet:
        return ()
    let_go = ActionOption(
        id=f"let-go-{member.id}",
        name="Let go",
        action_name="leave_party",
        args={"target_id": member.id},
    )
    hired = PanelRow(
        name="Hired crew",
        brief="",
        help="Hired to act like you: they roll their own skills and can help on your rolls.",
        options=(let_go,),
    )
    return (*gear_rows(world, member), hired)


def ship_panel(world: TwentyFourXXWorld) -> Panel:
    functions = tuple(
        PanelRow(
            name=function.name,
            brief="",
            tags=_mark_tags(function),
        )
        for function in world.ship.values()
    )
    receivers = (
        (world.player, "Take it"),
        *((member, f"Give to {member.name}") for member in world.hired_party_members()),
    )
    held = tuple(
        PanelRow(
            name=item.name,
            brief="",
            tags=(IN_THE_HOLD, *_mark_tags(item)),
            options=tuple(
                ActionOption(
                    id=f"retrieve-{key}-{crewmate.id}",
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
    return Panel(
        title="Ship",
        rows=(*functions, *held),
        help="Your crew's starship: seven functions that take upgrades for ₡10 each, and a hold "
        "for gear.",
    )


def job_panel(world: TwentyFourXXWorld) -> tuple[Panel, ...]:
    if world.job:
        shown = world.job
    elif where := world.work_found_at:
        shown = f"{WORK_AT}{where}"
    else:
        return ()
    return (Panel(title="Job", rows=(PanelRow(name=shown, brief=""),), help=JOB_HELP),)


def look_again_move(world: TwentyFourXXWorld) -> tuple[ActionOption, ...]:
    where = world.work_found_at
    if not where or world.player.require_sheet().credits < 1:
        return ()
    look_again = ActionOption(
        id="look-again",
        name="Pay ₡1 and look again",
        help=f"Spend ₡1 to roll again for work at {where}.",
        action_name="find_again",
        args={"where": where},
        told_in_turn=True,
    )
    return (look_again,)


def newcomer_decision(dead: Crewmate) -> Decision:
    return Decision(
        kind=NEWCOMER,
        prompt=NEWCOMER_PROMPT.format(name=dead.name),
        options=(),
        allows_text=True,
    )


def succession_decision(members: Sequence[Crewmate]) -> Decision:
    return Decision(
        kind="succession",
        prompt="Who leads now?",
        options=tuple(
            ActionOption(
                id=member.id,
                name=member.name,
                brief=member.brief,
                action_name="take_lead",
                args={"member_id": member.id},
            )
            for member in members
        ),
        allows_text=False,
    )


def raise_decision(sheet: CrewSheet) -> Decision:
    return Decision(
        kind="raise",
        prompt=RAISE_PROMPT,
        options=tuple(
            ActionOption(
                id=slug(skill, ()),
                name=f"{skill} d{die} → d{raised_die}",
                action_name="raise_skill",
                args={"skill": skill},
            )
            for skill, die in sheet.skills.items()
            if (raised_die := next_die(die)) is not None
        ),
        allows_text=True,
    )


def commit_decision(
    attempt: Roll, roll_line: str, actor: Crewmate, faces: tuple[int, ...]
) -> Decision:
    return Decision(
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
            ActionOption(
                id="commit",
                name="Commit",
                help="Roll these dice and take the risk as shown; to change the plan, type it "
                "instead.",
                action_name="roll",
                args={**attempt.model_dump(mode="json"), "committed": True},
            ),
        ),
        allows_text=True,
    )


def defence_decision(
    headline: str, hit: DefendHit, defender_id: Slug, defences: Sequence[tuple[Slug, Gear]]
) -> Decision:
    return Decision(
        kind="defence",
        prompt=f"{headline} Break gear or a ship function to make a brief hindrance, or take it.",
        options=(
            *(
                _defence(f"Break {gear.name}", BREAK_HELP, hit, defender_id, item_id)
                for item_id, gear in defences
            ),
            _defence("Take it", "Take the hit and what it leaves on you.", hit, defender_id, None),
        ),
        allows_text=False,
    )


def _mark_tags(gear: Gear) -> tuple[Tag, ...]:
    return tuple(Tag(name=label, help=MARK_HELP[mark]) for label, mark in gear.marks())


def _defence(
    name: str, help: str, hit: DefendHit, defender_id: Slug, item_id: Slug | None
) -> ActionOption:
    chosen = hit.model_copy(update={"choices": {**hit.choices, defender_id: item_id}})
    return ActionOption(
        id=item_id or "take-it",
        name=name,
        help=help,
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
