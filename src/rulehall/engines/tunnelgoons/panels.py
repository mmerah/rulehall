from rulehall.core.play import PendingDecision, PendingOption
from rulehall.engines.tunnelgoons.sheet import ABILITIES, Goon


def level_up_decision(actor: Goon) -> PendingDecision:
    prompt = f"Level up: {actor.name}. Raise one ability by 1. Raise Health or Inventory by 1."
    options = tuple(
        PendingOption(
            id=f"{ability}-{boost}",
            name=f"{ability.capitalize()} +1, {boost.capitalize()} +1",
            action_name="level_up",
            args={"ability": ability, "boost": boost},
        )
        for ability in ABILITIES
        for boost in ("health", "inventory")
    )
    return PendingDecision(kind="level-up", prompt=prompt, options=options, allows_text=False)
