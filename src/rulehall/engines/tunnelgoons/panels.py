from rulehall.core.decisions import ActionOption, Decision
from rulehall.engines.tunnelgoons.sheet import ABILITIES, Goon


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
