from typing import Self

from pydantic import Field, JsonValue, model_validator

from rulehall.core.validation import Frozen, Slug, check_unique


class DecisionOption(Frozen):
    id: Slug
    name: str = Field(min_length=1)
    brief: str = ""
    sprite: str = ""


class ActionOption(DecisionOption):
    action_name: str = Field(min_length=1)
    args: dict[str, JsonValue] = Field(default_factory=dict)
    group: str = ""
    refusal: str = ""
    told_in_turn: bool = False


class Decision(Frozen):
    kind: Slug
    # A prose-less segment replays into model history from this alone, so it can never be empty.
    prompt: str = Field(min_length=1)
    options: tuple[ActionOption, ...]
    allows_text: bool

    @model_validator(mode="after")
    def _options_are_unambiguous(self) -> Self:
        check_unique("option ids", (option.id for option in self.options))
        return self


class PlayerInput(Frozen):
    option_id: Slug | None = None
    text: str = ""

    @model_validator(mode="after")
    def _answers_one_way(self) -> Self:
        if (self.option_id is None) == (not self.text):
            raise ValueError("an answer is either a chosen option or written text")
        return self
