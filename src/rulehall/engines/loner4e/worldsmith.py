from rulehall.core.validation import Refusal
from rulehall.engines.loner4e.rules import MEANWHILE_QUESTION
from rulehall.engines.loner4e.world import (
    LivingWorldProposal,
    Loner4eMeanwhileProposal,
    Loner4eWorld,
)
from rulehall.engines.scenes.worldsmith import next_needs

WORLDSMITH_GUIDANCE = (
    "LONER 4E AUTHORING\n"
    "Every character is a person, an object, a vehicle or a curse. "
    "Each character has a one-line `concept`, `tags` by kind, and luck of its own. "
    "The tag kinds are `skill`, `frailty` and `gear`. A `relationship` tag, such as `Uneasy "
    "Ally`, goes on the NPC, never on the player, and only once play has earned it. "
    "Luck shows how long a character holds out in a conflict. Luck is not health. "
    "Write a group of similar opponents, such as a squad or a mob, as one character: give it "
    "one `concept` and the `skill` tags its members share, and a `frailty` tied to their "
    "numbers, such as `Scatters When Leaderless`. Do not write the group as several characters. "
    "A living character can have a `goal`, a `motive` and a `nemesis`. An object, a vehicle "
    "and a curse have none of these. "
    "Every scene acts on the `goal` of the player, or brings the `nemesis` of the player "
    "nearer. A blank goal or motive on the player's sheet is fine: let the first scenes offer "
    "them. "
    "A place's tags go in `details`, never in a character's tags or in a cast entry under the "
    "id `scene`, which names the scene. "
    "The opposition's tags say what they are doing now, such as `Searching for the "
    "Protagonist`. "
    "Give a door or a storm the `skill` tags and the `frailty` tags that it resists with. "
    "Tags are free text. Use entries from the selected pack when they fit. Invent a tag for "
    "this scenario when the invented tag is clearer. Only a pack tag has a meaning that the "
    "game master can look up. An invented tag that does not show what it does needs one "
    "sentence in the `brief` of that character. The game master judges from that sentence "
    "whether the tag helps or hinders. "
    "Use the factions, the people and the monsters of a pack: file one into `cast` under a new "
    "id, copy its tags and its drives, and write a `brief` for this scene. Take names from the "
    "name lists of the pack when the setting has them.\n\n"
    "Loner has no pre-written story: the oracle discovers the world. Leave open what the "
    "oracle can answer. Write places, people, their tags and what they want, never a secret "
    "answer. Write in `arc` loose pressure only: what the opposition wants and the open "
    "threads, never a plot or a planned twist. A cast entry elsewhere is someone who may turn "
    "up, not a secret. Someone the player left behind stays behind until the "
    "story brings them back; a Meanwhile changes what they are doing. Surprise comes from the "
    "oracle, the twists and the transitions, not from you. WHAT THE PROTAGONIST CARRIES "
    "FORWARD, when shown, is what became of the world of the protagonist's past adventures: it "
    "stands."
)
OPENING_FRAME = (
    "Open in the middle of a tense moment: the protagonist has a goal, an obstacle in the way, "
    "and time pressing. When the source is only a prompt, write a premise and a web of people "
    "who may turn up, not a plot."
)
DRAMATIC = (
    "The scene closed ({reason}). {words}DRAMATIC: open on what is pressing. Something "
    "external has moved; the protagonist responds. Place it where the player was heading when "
    "the fiction allows."
)
TIPPED = (
    "The quiet scene tipped into urgency on those words: open on that action, still "
    "unresolved, so the player plays it."
)
MEANWHILE = (
    "MEANWHILE: the world's turn. Cut to whoever holds power, where the protagonist is not: "
    "what they do out of the protagonist's sight, never beside them; write their new tags in "
    f'`power`. The oracle said "{{ally}}" to "{MEANWHILE_QUESTION}". On a yes, also write in '
    "`ally` the new tags of the NPC most affected and let the next scene show what they did. "
    "On a no, allies hold: `ally` is null, and no ally moves under `power`. {then}"
)
MEANWHILE_TWIST = "The world's turn brought a twist: {twist}. Read it in what moved off screen."
MEANWHILE_DRAMATIC = "Then write the next scene in `scene`. {dramatic}"
MEANWHILE_QUIET = (
    "Then write no scene: leave `scene` null. The protagonist gets a quiet window and chooses "
    "its aim."
)
LIVING_WORLD = (
    "THE LIVING WORLD: the adventure ended: {why}. One line each; the player reads them, so "
    "name only what the player has met, and write no id in a line."
)
OFFSCREEN = "Off screen: {offscreen}. Let this scene show it where it touches the aim."
QUIET = (
    'QUIET: the protagonist has initiative and the world is receptive. Their aim: "{aim}". '
    "Write the place and the people for it. `goal` is that aim. Settle nothing: "
    "the oracle answers whether it works."
)


def check_meanwhile(
    proposal: Loner4eMeanwhileProposal, world: Loner4eWorld, follow_up: str
) -> None:
    moved = world.model_copy(deep=True)
    needs: list[str] = []
    if proposal.ally is not None and not world.frame.ally.startswith("yes"):
        needs.append("a null `ally`: the oracle said no, so allies hold")
    for update in proposal.updates:
        try:
            _ = moved.apply_offscreen_update(update)
        except Refusal as refused:
            needs.append(str(refused))
    scene = proposal.scene
    if (scene is not None) != (follow_up == "dramatic"):
        needs.append(f"a `scene` exactly when the follow-up is dramatic: it is {follow_up}")
    elif scene is not None:
        needs += next_needs(scene, moved)
    if needs:
        raise Refusal("the meanwhile needs " + "; ".join(needs))


def check_living_world(proposal: LivingWorldProposal, world: Loner4eWorld) -> None:
    _ = world.living_world_lines(proposal)
