from collections.abc import Sequence

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.views import PanelRows, Score, Tag
from rulehall.engines.panels import gauge_row, score_block, tag_list, text_rows
from rulehall.engines.tunnelgoons.sheet import ABILITIES, Goon

SHEET_HELP = {
    "Brute": "Hitting things and feats of strength: added to the 2d6 on those rolls.",
    "Skulker": "Quiet movement, aiming and balance: added to the 2d6 on those rolls.",
    "Erudite": "Reading, noticing and talking: added to the 2d6 on those rolls.",
    "Inventory": "How many items you carry freely; each item over it takes 1 off Brute and "
    "Skulker rolls.",
    "Level": "Rises by one when an adventure ends, with +1 to an ability and to Health or "
    "Inventory.",
    "Health": "Damage comes off it and a night's rest refills it; at 0 a character dies.",
    "Items": "What you set out with: each item named in a roll it helps adds 1.",
}
ABILITIES_HELP = "Each one is added to the 2d6 on the rolls it fits."
ABILITY_NOTES = {"brute": "might", "skulker": "stealth", "erudite": "wits"}


def person_rows(goon: Goon, *, carried: int | None = None) -> PanelRows:
    sheet = goon.sheet
    if sheet is None:
        return text_rows("Health", SHEET_HELP["Health"], f"{goon.hp} (its Difficulty Score)")
    abilities = tuple(
        Score(
            name=ability.capitalize(),
            value=str(sheet.abilities[ability]),
            note=ABILITY_NOTES[ability],
            help=SHEET_HELP[ability.capitalize()],
        )
        for ability in ABILITIES
    )
    inventory = (
        text_rows("Inventory", SHEET_HELP["Inventory"], str(sheet.inventory))
        if carried is None or sheet.inventory == 0
        else (
            gauge_row("Inventory", SHEET_HELP["Inventory"], carried, sheet.inventory, look="pips"),
        )
    )
    return (
        gauge_row("Health", SHEET_HELP["Health"], goon.hp.current, goon.hp.maximum),
        *score_block("Abilities", ABILITIES_HELP, abilities),
        *inventory,
        *text_rows("Level", SHEET_HELP["Level"], str(sheet.level)),
    )


def item_rows(names: Sequence[str]) -> PanelRows:
    return tag_list("Items", SHEET_HELP["Items"], [Tag(name=name) for name in names])


def level_up_decision(actor: Goon) -> Decision:
    prompt = f"Level up: {actor.name}. Raise one ability by 1. Raise Health or Inventory by 1."
    options = tuple(
        ActionOption(
            id=f"{ability}-{boost}",
            name=f"{ability.capitalize()} +1, {boost.capitalize()} +1",
            action_name="level_up",
            args={"ability": ability, "boost": boost},
        )
        for ability in ABILITIES
        for boost in ("health", "inventory")
    )
    return Decision(kind="level-up", prompt=prompt, options=options, allows_text=False)
