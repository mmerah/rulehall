from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.play import PendingOption
from rulehall.core.tools import Told
from rulehall.core.validation import Frozen, Slug, check_unique
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner4e.rules import (
    ALTERS_THE_LOCATION,
    CHANGES_THE_GOAL,
    ENDS_THE_SCENE,
    SCENE_ID,
    UNTRAINED,
    CloseReason,
    StatusColumn,
    TagKind,
)
from rulehall.engines.loner4e.world import TagChange, Tags

PLAYER_OR_HERE = (
    f"`{PLAYER_ID}` for the protagonist, never their name, or the exact id of a living character "
    "here"
)
TWIST_NOTE = (
    "A twist interrupts the scene: {subject} / {action}. The pair is one beat: read it in what "
    "is already here, and develop it this turn. Read the room, then the table: if SETTLED and "
    "the sheet show pressure, land it hard; if the scene has been clean, it is a shift."
)
TWIST_ACTION_NOTES: dict[str, str] = {
    ENDS_THE_SCENE: "The scene is closing: develop the twist and direct.",
    CHANGES_THE_GOAL: "Call `drive` with `actor_id: scene` and the new goal.",
    ALTERS_THE_LOCATION: "Call `change_tags` with `actor_id: scene` and kind `detail`.",
}
DEFEATED = (
    "{name} is out of luck and lost the conflict. Tell now in `direct` what the defeat means: "
    "captured, disarmed, driven off, cornered or conceding. Defeat is not death."
)
MARK_ONLY = "The player picks only the lasting mark, never what the defeat means."
STILL_IN_IT = (
    "{name} is still in it: direct; the player's next words press on, change tack or break away"
)
TAKE_BREATHER = PendingOption(
    id="breather",
    name="Take the breather",
    brief="Say what you do with this quiet window.",
    action_name="take_breather",
)
RECOVER = PendingOption(
    id="recover",
    name="Recover",
    brief="Spend the quiet scene resting: it clears the newest box.",
    action_name="recover",
    told_in_turn=True,
)
RECOVERING = "Rest and recover from being {status}"
MOVE_ON = PendingOption(
    id="move-on",
    name="Move on",
    brief="Leave this scene; the dice say what comes next.",
    action_name="move_on",
)
END_HERE = PendingOption(id="end", name="End the adventure", action_name="confirm_end")
BREAK_AWAY = PendingOption(
    id="break-away",
    name="Break away",
    brief="Always allowed, never free: the story sets the price.",
    action_name="withdraw",
)
BROKE_AWAY = "the protagonist broke away: name the cost with `change_tags`"
STATUS_PROMPT = "Does this defeat leave a lasting mark?"
CONFLICT_MARKS = (
    "a Harm & Luck conflict is open: the protagonist gains no condition from it. Luck is the "
    "harm, and the player's Status pick after a defeat is the only lasting mark. Tell the hurt "
    "in `direct`."
)
DRAMATIC_CLOSES = (
    "`turning_point` closes a quiet scene only: close this dramatic scene as `resolved`, "
    "`blocked` or `abandoned`"
)
QUESTION_REQUIRED = "`question` is required: write the question"
QUIET_LASTS = (
    "a quiet scene lasts: it is the protagonist's pause to recover, plan or deepen a bond, and "
    "it neither resolves nor turns on the player's first turn in it. Later, the player's Move "
    "on or a turning point ends it. Call `direct` now."
)
MEANWHILE_UNSAID = "The Meanwhile is the worldsmith's: say nothing of it and call `direct` now."
MAY_END = "If this settles what the protagonist set out to do, call `end_adventure` now."
NO_MARK = PendingOption(
    id="none", name="No lasting mark", action_name="mark_status", args={"column": None}
)
ASK_ORACLE = PendingOption(
    id="ask",
    name="Ask the oracle",
    brief="Type one yes/no question.",
    action_name="ask_oracle",
)
SCENE_UNWRITTEN = Fact(
    told=True,
    trace="the next scene could not be written",
    card="The next scene could not be written. You are still where you were.",
)
LAST_WORDS = 'The player\'s last words: "{words}". '
ARRIVING = (
    "The player arrives in the place in SCENE. The narrator told the leaving already: tell only "
    "the arrival in the place SCENE describes, and end on what presses. The player has not "
    "acted here, so settle nothing."
)
MEANWHILE_CUE = (
    "Cut away from the protagonist: tell only what the Meanwhile card says moved, as the "
    "world's turn; the protagonist does not see it. Name nothing else in the cutaway."
)
PLAY_ON = PendingOption(id="play-on", name="Play on", action_name="play_on")
ENDING_PROMPT = "The adventure could end here: {why}. End it, or play on?"
GROWTH_PROMPT = "What did {name} learn?"
GROWTH = (
    "The player ended the adventure and said what {name} learned: write that growth once with "
    "`change_tags`, or with `drive` for a new nemesis or the concept reworded. Drop with "
    "`change_tags` `lost` any gear on the sheet that the story gave away or lost. Then direct."
)
GROWTH_WAITS = (
    "a new skill or frailty on the protagonist is the growth at the end of the adventure: it is "
    "written only after the player picks End it. Propose the end with `end_adventure`, or tell the "
    "change in `direct`"
)
CONCEPT_GROWS = (
    "the concept changes only in the growth, after the player picks End it. Call `direct` now."
)
GROWN = "the growth is one new skill or frailty, and it is written. Call `direct` now."
WRITE_LIVING_WORLD = PendingOption(
    id="living-world", name="Write the Living World", action_name="request_living_world"
)
UNWRITTEN_PROMPT = "The adventure is over, and the Living World is still to be written."
EPILOGUE = "The adventure is over. Tell WHAT HAPPENED as a short epilogue."
LIVING_WORLD_UNWRITTEN = Fact(
    told=True,
    trace="the living world could not be written",
    card="The Living World could not be written. Ask for it again.",
)
ARRIVING_QUIET = (
    "The protagonist has just arrived in SCENE to pursue their aim. Direct the arrival with "
    "your first result."
)


class CloseScene(Frozen):
    reason: CloseReason = Field(
        description="`resolved`: the goal is achieved or definitively failed. `blocked`: it "
        "cannot be pursued further here. `abandoned`: the protagonist commits to another course. "
        "`turning_point`: a quiet scene tips into urgency."
    )


class ChangeTags(TagChange):
    actor_id: Slug = Field(
        description=f"{PLAYER_OR_HERE}; a new id, such as `dock-guard`, brings in someone the "
        f"story just named; or `{SCENE_ID}`."
    )
    kind: TagKind | Literal["detail"] = Field(
        default_factory=lambda data: "detail" if data.get("actor_id") == SCENE_ID else "condition",
        description="`gear` for a thing taken or lost. `condition`, the default for a person, "
        "for a passing state such as `Poisoned`. `relationship` on an NPC for "
        "what the bond with the protagonist has become, such as `Uneasy Ally`. `detail`, the "
        "default for the scene, for a tag on the place, with `actor_id: scene` only.",
    )

    @model_validator(mode="after")
    def _a_change_the_actor_takes(self) -> Self:
        if (self.actor_id == SCENE_ID) != (self.kind == "detail"):
            raise ValueError("`detail` tags go with `actor_id: scene`, and only they do")
        if self.actor_id == PLAYER_ID and self.kind == "relationship":
            raise ValueError("a `relationship` tag goes on the NPC, never on the player")
        return self


class Drive(Frozen):
    actor_id: Slug = Field(description=f"{PLAYER_OR_HERE}, or `{SCENE_ID}` for the scene's goal.")
    goal: Told = Field(
        default="",
        description="What the character now wants, or what the protagonist is here for when "
        "`actor_id` is `scene`, in one line. Empty keeps the current goal.",
    )
    motive: Told = Field(
        default="",
        description="Why the character wants it, in one line. Empty keeps the current motive.",
    )
    nemesis: Told = Field(
        default="",
        description="Who or what is against the character. Empty keeps the current nemesis.",
    )
    concept: Told = Field(
        default="",
        description="The protagonist's concept rewritten by the growth, in one short phrase. "
        "Empty keeps it; the growth only.",
    )

    @model_validator(mode="after")
    def _a_drive_the_actor_takes(self) -> Self:
        if not (self.goal or self.motive or self.nemesis or self.concept):
            raise ValueError("give a goal, a motive, a nemesis or a concept")
        if self.actor_id == SCENE_ID and (
            self.motive or self.nemesis or self.concept or not self.goal
        ):
            raise ValueError("the scene takes a `goal` only")
        return self


class SpendLuck(Frozen):
    actor_id: Slug = Field(description=f"{PLAYER_OR_HERE}.")
    amount: int = Field(ge=1, description="The luck to spend. SPECIAL RULES prints the cost.")
    why: Told = Field(
        min_length=1, description="What the luck buys, in one line. The player reads this text."
    )


class Ask(Frozen):
    question: Told | None = Field(
        default=None,
        min_length=1,
        description="One closed question; yes is what the protagonist hopes. The player reads "
        "it. Leave it out when THE PLAYER ASKS is shown: the engine asks the player's question "
        "word for word.",
    )
    helps: Tags = Field(
        default=(),
        description="Exact tags here that bear on this moment and help.",
    )
    hinders: Tags = Field(
        default=(),
        description="Exact tags here that bear on this moment and hinder, and "
        f"`{UNTRAINED}` when the task needs expertise the protagonist lacks.",
    )
    against_id: Slug | None = Field(
        default=None,
        description="The id of the opponent in a Harm & Luck exchange; a new id, such as "
        "`dock-guard`, brings in an opponent the story just named. Null for one question or one "
        "key action. While a conflict is open, every ask is an exchange: null is against the "
        "opponent fought last.",
    )

    @model_validator(mode="after")
    def _each_tag_once_and_never_against_the_player(self) -> Self:
        check_unique("cited tags", [tag.casefold() for tag in (*self.helps, *self.hinders)])
        if UNTRAINED.casefold() in (tag.casefold() for tag in self.helps):
            raise ValueError(f"`{UNTRAINED}` hinders, never helps")
        if self.against_id in (PLAYER_ID, SCENE_ID):
            raise ValueError("`against_id` names an opponent, never the player or the scene")
        return self


class MarkStatus(Frozen):
    column: StatusColumn | None


class Fight(Frozen):
    opponent_id: Slug


class ConfirmEnd(Frozen):
    why: str = "the player chose to end it here"


class EndAdventure(Frozen):
    why: Told = Field(
        min_length=1,
        description="The sign that shows, in one line the player reads.",
    )
