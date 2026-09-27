from collections.abc import Iterable, Mapping, Sequence

from rulehall.core.prompt import Sections
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.entities import Person, Thing, leaked_names, named_unmet, required_needs
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld, resolved_id

OPENING_SECTIONS: Sections = (
    ("SCENES SO FAR", "(no scenes yet — write the opening)"),
    ("THE WHOLE CAST", "(no cast yet — write the people and things this scene needs)"),
    ("THE SCENE NOW", "(none yet)"),
)
OPENING = (
    "Write the opening scene of this adventure. Name the one place the player starts in. Name "
    "who is there. Name in `location` the wider location the scene is in. `cast` holds the "
    "people and things of the adventure, not of the scene. Write who the player meets here. "
    "Write also who the player will meet farther in. List under `present` only who is here "
    "now. The opening also writes `arc`, in a few lines or in none."
)


def check_opening[C: Person](proposal: SceneProposal[C]) -> None:
    everyone = proposal.cast
    present = _resolved_ids(proposal.present, everyone)
    hidden = _resolved_ids(proposal.hidden, everyone)
    gathered = [] if proposal.location else ["a `location`: the wider location the scene is in"]
    gathered += _placement_needs(proposal, everyone, present, hidden)
    gathered += _cast_needs(proposal, {})
    scanned = "\n".join((proposal.title, proposal.situation))
    _refuse(gathered + _leak_needs(scanned, everyone, (), present, hidden))


def check_next[C: Person](
    proposal: NextProposal[C], world: SceneWorld[C], *, needs: Sequence[str] = ()
) -> None:
    _refuse(next_needs(proposal, world, needs=needs))


def next_needs[C: Person](
    proposal: NextProposal[C], world: SceneWorld[C], *, needs: Sequence[str] = ()
) -> list[str]:
    everyone: Mapping[Slug, Thing] = {
        world.player.id: world.player,
        **world.merged_cast(proposal.cast),
    }
    followers = (world.player.id, *world.party)
    present = _resolved_ids(proposal.present, everyone)
    hidden = _resolved_ids(proposal.hidden, everyone)
    gathered = [*needs, *_placement_needs(proposal, everyone, present, hidden)]
    if world.player.id in proposal.cast:
        gathered.append("a cast that never rewrites the player")
    gathered += _cast_needs(proposal, world.cast)
    scanned = "\n".join((proposal.title, proposal.situation, proposal.recap))
    return gathered + _leak_needs(scanned, everyone, followers, present, hidden)


def _refuse(needs: list[str]) -> None:
    if needs:
        raise Refusal("the scene needs " + "; ".join(needs))


def _placement_needs[C: Person](
    proposal: SceneProposal[C],
    everyone: Mapping[Slug, Thing],
    present: list[Slug],
    hidden: list[Slug],
) -> list[str]:
    others = (*proposal.present, *proposal.hidden)
    needs: list[str] = []
    if stray := sorted(name for name in others if resolved_id(name, everyone) is None):
        needs.append(f"ids that exist; these name nobody: {stray}")
    if overlap := sorted(set(present) & set(hidden)):
        needs.append(f"nobody listed as both present and hidden: {overlap}")
    return needs


def _cast_needs[C: Person](proposal: SceneProposal[C], filed: Mapping[Slug, C]) -> list[str]:
    needs: list[str] = []
    if misfiled := [
        f"{entry.id!r} is filed under {key!r}"
        for key, entry in proposal.cast.items()
        if key != entry.id
    ]:
        needs.append("cast entries under their own id: " + "; ".join(misfiled))
    if broken := required_needs(proposal.cast, filed):
        needs.append(f"cast members as the worldsmith may write them: {broken}")
    return needs


def _leak_needs(
    read: str,
    everyone: Mapping[Slug, Thing],
    followers: tuple[Slug, ...],
    present: list[Slug],
    hidden: list[Slug],
) -> list[str]:
    needs: list[str] = []
    watched = [entry for entry in everyone.values() if not entry.known and entry.id not in present]
    scanned = (everyone[entity_id] for entity_id in (*present, *followers, *hidden))
    hidden_entries = [everyone[entity_id] for entity_id in hidden]
    leaked = leaked_names(read, scanned, hidden_entries) | set(named_unmet(read, watched))
    if named := sorted(leaked):
        needs.append(f"a scene that does not name what the player has not met: {named}")
    if met := sorted(
        entity_id for entity_id in set(hidden) - set(followers) if everyone[entity_id].known
    ):
        needs.append(f"a hidden list without {met}, whom the player has already met")
    return needs


def _resolved_ids(names: Iterable[str], everyone: Mapping[Slug, Thing]) -> list[Slug]:
    return [entity_id for name in names if (entity_id := resolved_id(name, everyone)) is not None]
