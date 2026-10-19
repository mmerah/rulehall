from rulehall.core.prompt import lines_of
from rulehall.core.validation import Refusal
from rulehall.engines.bases.maps.worldsmith import check_next as check_map_next
from rulehall.engines.bases.maps.worldsmith import check_opening as check_map_opening
from rulehall.engines.lite5e.data import srd
from rulehall.engines.lite5e.rules import (
    CHALLENGE_RATINGS,
    COMPANION_CR_CAP,
    ENCOUNTER_BUDGET,
    companion_cr_fits,
)
from rulehall.engines.lite5e.sheet import Lite5ePerson, level_pick_rules
from rulehall.engines.lite5e.world import Lite5eMapProposal, Lite5eRegionProposal, Lite5eWorld

XP_OF_CR = {block.challenge_rating: block.xp for block in srd().bestiary.stat_blocks.values()}
STAT_BLOCK_LINES = "\n".join(
    f"CR {rating}, {XP_OF_CR[rating]} XP each: "
    + ", ".join(
        block_id
        for block_id, block in srd().bestiary.stat_blocks.items()
        if block.challenge_rating == rating
    )
    for rating in CHALLENGE_RATINGS
)
BUDGET_LINES = "\n".join(
    f"party level {level}: low {budget['low']}, moderate {budget['moderate']}, "
    f"high {budget['high']}"
    for level, budget in ENCOUNTER_BUDGET.items()
)
WORLDSMITH_GUIDANCE = (
    "5E LITE AUTHORING\n"
    "Take every `stat_block_id` from STAT BLOCKS below. Never write a sheet, HP or conditions: "
    "code writes them.\n"
    "The budget is XP per party member. Multiply it by the party size. A group's XP is its stat "
    "block's XP times its `count`. Make most groups low or moderate.\n"
    f"{BUDGET_LINES}\n"
    "Write a few hostile groups and patrols in each region. The master can move a patrol with "
    "`meanwhile`.\n"
    "Put one or two people willing to sign on for pay in each settled region, so a lone player "
    "can hire help.\n"
    "STAT BLOCKS (id by challenge rating)\n"
    f"{STAT_BLOCK_LINES}"
)
CODE_ONLY_PERSON_FIELDS = (
    "alive",
    "sheet",
    "conditions",
    "stat_block_vitals",
    "portrait_id",
    "formation_row",
    "routed",
    "xp_paid",
    "stealth_total",
    "missed",
)
HIRE_KINDS = (
    "- a class companion: a class from {classes}, an SRD species, and a background. Give the "
    "picks you want, or leave them out for the defaults. Pick kinds: {kinds}.\n"
    "- a stat-block companion: the person keeps its own stat block and fights with it."
)


def check_opening(proposal: Lite5eMapProposal) -> None:
    check_map_opening(proposal)
    _check_lite_map(proposal)


def check_next(proposal: Lite5eRegionProposal, world: Lite5eWorld) -> None:
    check_map_next(proposal, world)
    _check_lite_map(proposal)
    if taken := sorted(set(proposal.goals) & set(world.goals)):
        raise Refusal(f"these goal ids are in use already: {taken}")


def hire_guidance_lines(world: Lite5eWorld) -> str:
    level = world.party_level()
    block_ids = srd().bestiary.stat_blocks
    fitting = [
        f"- {person.id}: {person.name}, {block_ids[person.stat_block_id].name}"
        f"{f', a group of {person.count}' if person.count > 1 else ''}"
        for person in world.at(world.current.id)
        if person.alive
        and person.known
        and person.id not in world.party_ids
        and companion_cr_fits(block_ids[person.stat_block_id].challenge_rating, level)
    ]
    kinds = "; ".join(
        f"{kind} ({rule.noun})"
        for kind, rule in level_pick_rules().items()
        if rule.replaces is None
    )
    return "\n".join(
        (
            "Two kinds of hire:",
            HIRE_KINDS.format(classes=", ".join(srd().character_options.classes), kinds=kinds),
            f"At party level {level}, a stat-block companion has CR {COMPANION_CR_CAP[level]} "
            "at most. Stat blocks here that fit:",
            lines_of(fitting),
        )
    )


def _check_lite_map(proposal: Lite5eMapProposal) -> None:
    entities = (*proposal.items.values(), *proposal.npcs.values())
    if strays := sorted(entity.id for entity in entities if entity.known and entity.find):
        raise Refusal(f"`find` is for hidden persons and items only, not {strays}")
    if strays := sorted(
        item.id for item in proposal.items.values() if not item.known and item.find is None
    ):
        raise Refusal(f"a hidden item needs `find`, the DC to search it out: {strays}")
    if strays := sorted(item.id for item in proposal.items.values() if item.opens is not None):
        raise Refusal(f"`opens` is set by code only, not on {strays}")
    if strays := sorted(
        f"{person.id}.{field}"
        for person in proposal.npcs.values()
        for field in CODE_ONLY_PERSON_FIELDS
        if getattr(person, field) != _default_person_field(field)
    ):
        raise Refusal(f"these person fields are set by code only: {strays}")
    if strays := sorted(item.id for item in proposal.items.values() if item.known and item.trap):
        raise Refusal(f"`trap` is for hidden items only, not {strays}")
    if strays := sorted(
        f"{from_id}->{way.to_id}"
        for from_id, ways in proposal.ways.items()
        for way in ways
        if way.lock is not None and not way.locked
    ):
        raise Refusal(f"`lock` is for locked ways only, not {strays}")
    if strays := sorted(
        f"{from_id}->{way.to_id}"
        for from_id, ways in proposal.ways.items()
        for way in ways
        if (back := proposal.find_way(way.to_id, from_id)) is not None
        and (back.locked, back.lock) != (way.locked, way.lock)
    ):
        raise Refusal(f"a way and its way back share `locked` and `lock`, not {strays}")
    for place in proposal.places.values():
        if loose := sorted(
            gear_id for gear_id in place.shop or () if not srd().is_magic_gear(gear_id)
        ):
            raise Refusal(
                f"the shop {place.id!r} sells SRD gear already: stock only magic items, not {loose}"
            )


def _default_person_field(field: str) -> object:
    return Lite5ePerson.model_fields[field].get_default(call_default_factory=True)
