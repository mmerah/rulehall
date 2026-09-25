from collections.abc import Iterable, Mapping

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
    "who is there. A scene ends when the player leaves the place, so a place farther on "
    "belongs to a later scene. Name in `location` the wider location the scene is in. `cast` "
    "holds the people and things of the adventure, not of the scene. Write who the player "
    "meets here. Write also who the player will meet farther in. List under `present` and "
    "`hidden` only who is here now. The opening also writes `arc`, in a few lines or in none."
)
CROSSING = (
    "The player is leaving {left} for the place in SCENE. The player asked for this: "
    '"{asked}"\n\n'
    "The narrator told the leaving already. Write the arrival. Give the distance and the time "
    "in the fewest words that make them real. End on what the player sees first. WHAT HAPPENED "
    "names everyone who travelled with the player. The player has not acted in the new place, "
    "so settle nothing."
)
COMPLICATING = (
    "The game master brings a complication into the scene the player is in: {brief}. Write the "
    "new situation as a new scene. You can keep the same `place_id`, and this is usual. Leave "
    "`location` empty: the player has not moved. Everyone here stays, unless the brief moves "
    "them. Change the situation. Do not change the player's answer to it. The player has not "
    "acted, so settle nothing for the player. Write in `recap` the scene as it was before it "
    "changed."
)
TURNING = (
    "The situation changes where the player stands. The player did nothing to cause the "
    "change. Write what arrives or changes, as the player sees it, from SCENE and WHAT "
    "HAPPENED. End on what the new situation asks of the player. The player has not answered "
    "it, so settle nothing."
)
MEANWHILE_NUDGE = (
    "Time has passed since the player last saw the people who are not with them. Let one of "
    "those people move on without the player, if the scene has room for it."
)


def check_opening[C: Person](proposal: SceneProposal[C]) -> None:
    """Every refusal is gathered, so the worldsmith's one retry sees them all."""
    everyone = proposal.cast
    present = _resolved_ids(proposal.present, everyone)
    hidden = _resolved_ids(proposal.hidden, everyone)
    needs = [] if proposal.location else ["a `location`: the wider location the scene is in"]
    needs += _placement_needs(proposal, everyone, (), present, hidden)
    needs += _cast_needs(proposal, {})
    read = "\n".join((proposal.title, proposal.situation))
    _refuse(needs + _leak_needs(read, everyone, (), present, hidden))


def check_next[C: Person](proposal: NextProposal[C], world: SceneWorld[C], *, moving: bool) -> None:
    """Every refusal is gathered, so the worldsmith's one retry sees them all."""
    everyone: Mapping[Slug, Thing] = {
        world.player.id: world.player,
        **world.merged_cast(proposal.cast),
    }
    followers = (world.player.id, *world.party)
    present = _resolved_ids(proposal.present, everyone)
    hidden = _resolved_ids(proposal.hidden, everyone)
    needs: list[str] = []
    if not moving and proposal.location not in ("", world.scene.location):
        needs.append(
            "no new `location`: a complication happens where the player is; leave it empty"
        )
    needs += _placement_needs(proposal, everyone, followers, present, hidden)
    if world.player.id in proposal.cast:
        needs.append("a cast that never rewrites the player")
    needs += _cast_needs(proposal, world.cast)
    read = "\n".join((proposal.title, proposal.situation, proposal.recap))
    _refuse(needs + _leak_needs(read, everyone, followers, present, hidden))


def _refuse(needs: list[str]) -> None:
    if needs:
        raise Refusal("the scene needs " + "; ".join(needs))


def _placement_needs[C: Person](
    proposal: SceneProposal[C],
    everyone: Mapping[Slug, Thing],
    followers: tuple[Slug, ...],
    present: list[Slug],
    hidden: list[Slug],
) -> list[str]:
    others = (*proposal.present, *proposal.hidden)
    needs: list[str] = []
    if named := sorted(name for name in others if resolved_id(name, everyone) in followers):
        needs.append(
            "a scene that does not list the player or the party; "
            f"they are put there by code: {named}"
        )
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
