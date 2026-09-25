from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, check_unique

type Cause = Literal["opening", "story", "battle"]


class Line(Frozen):
    speaker_id: Slug | None = Field(
        default=None,
        description="Exact id of the speaker. Null for narration.",
    )
    text: str = Field(
        min_length=1, description="One passage of narration, or only what the speaker says."
    )


class SpokenLine(Frozen):
    """Carries the speaker's name so chat and journal never resolve an id through state."""

    speaker_id: Slug | None = None
    speaker: str = ""
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _named_when_spoken(self) -> Self:
        if (self.speaker_id is None) != (not self.speaker):
            raise ValueError("a spoken line names its speaker; narration names nobody")
        return self

    @property
    def said(self) -> str:
        return f"{self.speaker}: {self.text}" if self.speaker else self.text


class Narration(Frozen):
    """The prose the player reads, split into narration and dialogue."""

    lines: tuple[Line, ...] = Field(description="All narration and dialogue, in order.")


class Debrief(Frozen):
    """A recap for a player coming back to the game: only what the player has read."""

    story_so_far: str = Field(
        description="The story from the start to now, in a few sentences. Tell it to the player."
    )
    current_aim: str = Field(description="What the player is trying to do now, in one sentence.")
    open_threads: tuple[str, ...] = Field(
        description=(
            "Each question, promise or problem that is still open, one sentence each. A thread "
            'can suggest a next step, for example "You could return to the smith with the ore."'
        )
    )
    last_beats: tuple[str, ...] = Field(
        description="The last things that happened, in order. Write each as a short bullet line."
    )

    def check(self) -> None:
        blank = [
            name
            for name, value in (
                ("story_so_far", (self.story_so_far,)),
                ("current_aim", (self.current_aim,)),
                ("open_threads", self.open_threads),
                ("last_beats", self.last_beats),
            )
            if not value or not all(line.strip() for line in value)
        ]
        if blank:
            raise Refusal(f"these fields are blank: {', '.join(blank)}")


class DecisionOption(Frozen):
    id: Slug
    name: str = Field(min_length=1)
    brief: str = ""
    sprite: str = ""


class PendingOption(DecisionOption):
    action_name: str = Field(min_length=1)
    args: dict[str, JsonValue] = Field(default_factory=dict)
    group: str = ""
    # Why it cannot be used now; empty when it can. It shows greyed and never runs.
    refusal: str = ""


class PendingDecision(Frozen):
    """One decision the game waits on; None at `Game.pending` means the composer is the only way."""

    kind: Slug
    # A prose-less segment replays into model history from this alone, so it can never be empty.
    prompt: str = Field(min_length=1)
    options: tuple[PendingOption, ...]
    # False where the SRD gives the player a pick and the options are that pick, whole.
    allows_text: bool

    @model_validator(mode="after")
    def _options_are_unambiguous(self) -> Self:
        check_unique("option ids", (option.id for option in self.options))
        return self


class Answer(Frozen):
    option_id: Slug | None = None
    text: str = ""

    @model_validator(mode="after")
    def _answers_one_way(self) -> Self:
        if (self.option_id is None) == (not self.text):
            raise ValueError("an answer is either a chosen option or written text")
        return self


class Refused(Frozen):
    """A master tool call the rules refused; `after_facts` places it among the turn's facts."""

    tool: str
    reason: str
    after_facts: int = Field(ge=0)


class Exchange(Frozen):
    words: str
    cause: Cause | None = None
    lines: tuple[SpokenLine, ...]
    # Every fact, told or not; `cards` picks the ones the player may see.
    facts: tuple[Fact, ...] = ()
    refused: tuple[Refused, ...] = ()
    # The suspending decision's prompt: the pause has to survive after `Game.pending` clears.
    decision: str = ""
    context: str = ""

    def transcript(self) -> str:
        return "\n".join(line.said for line in self.lines)


class Chapter(Mutable):
    """One scene or place as the player read it; `recap` is empty until the scene closes."""

    title: str
    context: str = ""
    recap: str = ""
    exchanges: list[Exchange] = Field(default_factory=list)
