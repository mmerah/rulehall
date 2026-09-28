from rulehall.core.validation import Refusal
from rulehall.engines.hiring import HIRED, UNWRITTEN_CAST
from rulehall.engines.twentyfourxx.world import NewcomerProposal, TwentyFourXXWorld

WORLDSMITH_GUIDANCE = (
    "24XX AUTHORING\n"
    f"{UNWRITTEN_CAST}The player is an operator on a job in a hard science-fiction future. "
    "Write each scene as a work site, a station or a ship. Write the people who control "
    "these places. People the player left behind move on without them.\n\n"
    "Code files each `cast` entry under the slug of its name: Bray Kell is `bray-kell`. Name "
    "entries so in `present_ids` and `hidden_ids`. The crew's ship belongs to the rules: never "
    "file it in `cast`.\n\n"
    "A scene is one place. A scene ends when the player leaves the place. WHAT COMES NEXT holds "
    "the player's own words about where they go and what they are after. Build the scene the "
    "player asked for. When the player leaves, the new scene is the place they named: never "
    "short of it, and never back where they left. Only a complication keeps them in the same "
    "place. Give the player what they went to look for, or the reason they cannot "
    "have it. Never give the player silence. A complication changes that place. Keep what the "
    "brief does not move.\n\n"
    "Put something in `hidden_ids` when the scene has something worth finding. `hidden_ids` is not "
    "necessary. Never name a hidden entity in `title`, `situation` or `recap`. Never name a "
    "hidden entity in the `brief` or the sheet of anyone the player can see. The player reads "
    "all of that text, and a name there gives the player the find. A hidden entity can name "
    "itself. Write in `arc` what ties one hidden thing to another. THE SCENE NOW names who is "
    "hidden there. Never put an entry the player has met in `hidden_ids`. A hidden person's "
    "`brief` is what the player sees on meeting them. Put their secret in `arc`, never in the "
    "`brief`.\n\n"
    "Surprise the player. Turn an established fact against the player, or bring back something "
    "the player has stopped thinking about. Make the surprise from what exists. Never invent "
    "what the source would not hold."
)
COMPLICATING = (
    "The game master brings a complication into the scene the player is in: {brief}. Write the "
    "new situation as a new scene. You can keep the same `place_id`, and this is usual. Leave "
    "`location` empty: the player has not moved. Everyone here stays, unless the brief moves "
    "them. Change the situation. Do not change the player's answer to it. The player has not "
    "acted, so settle nothing for the player. Write in `recap` the scene as it was before it "
    "changed."
)
HIRING = (
    f"{HIRED}Choose the specialty, the origin and their options from ENGINE GUIDANCE for a "
    "character that a crew can hire for this work."
)
NEWCOMING = (
    "The player's operator is dead and no hired member lives. A new operator joins the crew "
    "and leads: {who}. They join in THE SCENE NOW, where the dead operator fell, and nowhere "
    "else. Write them from the player's words, and choose their specialty, "
    "origin and options from ENGINE GUIDANCE."
)

NEW_LOCATION = "no new `location`: a complication happens where the player is; leave it empty"
FLOWN = (
    "a new `place_id`: the crew flew away from {place_id}; land them at the place that WHAT "
    "COMES NEXT names"
)


def check_newcomer(proposal: NewcomerProposal, world: TwentyFourXXWorld) -> None:
    heard = world.model_copy(deep=True)
    heard.hear(proposal.name, proposal.brief)
    heard.refuse_unmet_names(proposal.name, proposal.brief)
    if any(proposal.name.casefold() == entry.name.casefold() for entry in world.cast.values()):
        raise Refusal(f"{proposal.name!r} is already in the cast: name a new operator")
