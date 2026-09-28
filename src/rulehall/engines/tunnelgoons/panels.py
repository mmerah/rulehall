from rulehall.core.decisions import ActionOption, Decision
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
