from collections.abc import Iterable, Mapping

from rulehall.core.prompt import Sections
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.name_leaks import leaked_names, names_in
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld, find_resolved_id
from rulehall.engines.sheet import Entity, Person
from rulehall.engines.world import authoring_faults

OPENING_SECTIONS: Sections = (
    ("SCENES SO FAR", "(no scenes yet — write the opening)"),
    ("THE WHOLE CAST", "(no cast yet — write the people and things this scene needs)"),
    ("THE SCENE NOW", "(none yet)"),
)
OPENING = (
    "Write the opening scene of this adventure. Name the one place the player starts in. Name "
    "who is there. Name in `location` the wider location the scene is in. `cast` holds the "
    "people and things of the adventure, not of the scene. Write who the player meets here. "
    "Write also who the player will meet farther in. List under `present_ids` only who is here "
    "now. The opening also writes `arc`, in a few lines or in none."
)


def check_opening[P: Person](proposal: SceneProposal[P]) -> None:
    everyone = proposal.cast_with_hidden_unmet()
    present = _resolved_ids(proposal.present_ids, everyone)
    hidden = _resolved_ids(proposal.hidden_ids, everyone)
    gathered = [] if proposal.location else ["a `location`: the wider location the scene is in"]
    gathered += _placement_needs(proposal, everyone, present, hidden)
    gathered += _cast_needs(proposal, {})
    scanned = "\n".join((proposal.title, proposal.situation))
    _refuse(gathered + _leak_needs(scanned, everyone, (), present, hidden))


def check_next[P: Person](proposal: NextProposal[P], world: SceneWorld[P]) -> None:
    _refuse(next_needs(proposal, world))


def next_needs[P: Person](proposal: NextProposal[P], world: SceneWorld[P]) -> list[str]:
    everyone: Mapping[Slug, Entity] = {
        world.player.id: world.player,
        **world.merged_cast(proposal.cast_with_hidden_unmet()),
    }
    followers = (world.player.id, *world.party_ids)
    present = _resolved_ids(proposal.present_ids, everyone)
    hidden = _resolved_ids(proposal.hidden_ids, everyone)
    gathered = _placement_needs(proposal, everyone, present, hidden)
    if world.player.id in proposal.cast:
        gathered.append("a cast that never rewrites the player")
    gathered += _cast_needs(proposal, world.cast)
    scanned = "\n".join((proposal.title, proposal.situation, proposal.recap))
    return gathered + _leak_needs(scanned, everyone, followers, present, hidden)


def _refuse(needs: list[str]) -> None:
    if needs:
        raise Refusal("the scene needs " + "; ".join(needs))


def _placement_needs[P: Person](
    proposal: SceneProposal[P],
    everyone: Mapping[Slug, Entity],
    present: list[Slug],
    hidden: list[Slug],
) -> list[str]:
    others = (*proposal.present_ids, *proposal.hidden_ids)
    needs: list[str] = []
    if stray := sorted(name for name in others if find_resolved_id(name, everyone) is None):
        needs.append(f"ids that exist; these name nobody: {stray}")
    if overlap := sorted(set(present) & set(hidden)):
        needs.append(f"nobody listed as both present and hidden: {overlap}")
    return needs


def _cast_needs[P: Person](proposal: SceneProposal[P], filed: Mapping[Slug, P]) -> list[str]:
    needs: list[str] = []
    if misfiled := [
        f"{entry.id!r} is filed under {key!r}"
        for key, entry in proposal.cast.items()
        if key != entry.id
    ]:
        needs.append("cast entries under their own id: " + "; ".join(misfiled))
    if broken := authoring_faults(proposal.cast, filed):
        needs.append(f"cast members as the worldsmith may write them: {broken}")
    return needs


def _leak_needs(
    read: str,
    everyone: Mapping[Slug, Entity],
    followers: tuple[Slug, ...],
    present: list[Slug],
    hidden: list[Slug],
) -> list[str]:
    needs: list[str] = []
    watched = [entry for entry in everyone.values() if not entry.known and entry.id not in present]
    scanned = (everyone[entity_id] for entity_id in (*present, *followers, *hidden))
    hidden_entries = [everyone[entity_id] for entity_id in hidden]
    leaked = leaked_names(read, scanned, hidden_entries) | set(names_in(read, watched))
    if named := sorted(leaked):
        needs.append(f"a scene that does not name what the player has not met: {named}")
    if met := sorted(
        entity_id for entity_id in set(hidden) - set(followers) if everyone[entity_id].known
    ):
        needs.append(f"a hidden list without {met}, whom the player has already met")
    return needs


def _resolved_ids(names: Iterable[str], everyone: Mapping[Slug, Entity]) -> list[Slug]:
    return [
        entity_id for name in names if (entity_id := find_resolved_id(name, everyone)) is not None
    ]
