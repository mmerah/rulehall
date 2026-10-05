from typing import Self

from pydantic import Field, JsonValue, model_validator

from rulehall.core.validation import Frozen, Refusal, Slug, check_unique


class DecisionOption(Frozen):
    id: Slug
    name: str = Field(min_length=1)
    brief: str = ""
    sprite: str = ""


class ActionOption(DecisionOption):
    help: str = ""
    action_name: str = Field(min_length=1)
    args: dict[str, JsonValue] = Field(default_factory=dict)
    group: str = ""
    refusal: str = ""
    told_in_turn: bool = False
    needs_words: bool = False

    def with_words(self, text: str) -> Self:
        if not self.needs_words:
            if text:
                raise Refusal(f"{self.name} takes no words: send it alone")
            return self
        if not text:
            raise Refusal(f"{self.name} needs your words: type them, then send")
        return self.model_copy(update={"args": {**self.args, "words": text}})


class Decision(Frozen):
    kind: Slug
    # A prose-less segment replays into model history from this alone, so it can never be empty.
    prompt: str = Field(min_length=1)
    options: tuple[ActionOption, ...]
    allows_text: bool
    silent: bool = False

    @model_validator(mode="after")
    def _options_are_unambiguous(self) -> Self:
        check_unique("option ids", (option.id for option in self.options))
        return self


class PlayerInput(Frozen):
    option_id: Slug | None = None
    text: str = ""

    @model_validator(mode="after")
    def _answers_something(self) -> Self:
        if self.option_id is None and not self.text:
            raise ValueError("an answer is a chosen option, written text, or both")
        return self
