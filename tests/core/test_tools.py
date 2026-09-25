from random import Random
from typing import Literal

import pytest
from pydantic import Field, JsonValue

from rulehall.core.facts import Fact
from rulehall.core.model import AnyGame, Game, ScenarioMeta
from rulehall.core.tools import Told, action, actions_of, tool, tools_of
from rulehall.core.validation import EngineId, Frozen, Refusal

type Kind = Literal["gear", "condition"]


class Word(Frozen):
    word: str = Field(description="One word the master fills in.")


class Marking:
    @tool
    def first(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        """The first tool the base publishes."""
        return [Fact(trace=f"base first {args.word}")]

    @tool
    def second(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        """The second tool the base publishes."""
        return [Fact(trace=f"base second {args.word}")]


class Adding(Marking):
    @tool
    def second(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        """The override's own description, not the base's."""
        return [Fact(trace=f"override second {args.word}")]

    @tool
    def third(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        """The tool the subclass adds."""
        return [Fact(trace=f"subclass third {args.word}")]


class Overriding(Marking):
    def second(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        return [Fact(trace=f"silent override {args.word}")]


class Acting(Marking):
    @tool
    @action
    def second(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        """Both marks: the master and the page call it."""
        return [Fact(trace=f"both second {args.word}")]

    @action
    def fourth(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        return [Fact(trace=f"page fourth {args.word}")]


class Aside(Frozen):
    note: Told = Field(description="A note the player reads.")


class Telling(Frozen):
    aside: Aside | None = Field(default=None, description="An optional aside.")
    lines: tuple[Told, ...] = Field(default=(), description="Lines the player reads.")
    plain: str = Field(default="", description="A text the player never reads.")


class Speaking:
    @tool
    def speak(self, _draft: AnyGame, _args: Telling, _rng: Random) -> list[Fact]:
        """Say something to the player."""
        return [Fact(trace="spoken")]


class Quiet:
    def touch(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        return [Fact(trace=args.word)]


def test_the_published_order_is_the_bases_tools_then_the_subclasss() -> None:
    published = tools_of(Adding(), _trusting)

    assert list(published) == ["first", "second", "third"]

    facts = published["second"].call(_draft(), {"word": "vest"}, Random(0))

    assert [fact.trace for fact in facts] == ["override second vest"]


def test_an_unmarked_override_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no @tool mark"):
        _ = tools_of(Overriding(), _trusting)


def test_a_method_with_no_description_is_refused_where_it_is_marked() -> None:
    with pytest.raises(ValueError, match="carries no description"):
        _ = tool(Quiet.touch)


def test_an_action_is_published_to_the_page_and_never_to_the_master() -> None:
    acting = Acting()

    assert list(tools_of(acting, _trusting)) == ["first", "second"]
    assert list(actions_of(acting)) == ["second", "fourth"]


def test_a_told_field_in_a_nested_model_or_a_tuple_is_checked_and_a_plain_one_is_not() -> None:
    speak = tools_of(Speaking(), _refusing_vex)["speak"]

    hidden: tuple[JsonValue, ...] = (
        {"aside": {"note": "Vex waits"}},
        {"lines": ["a door", "Vex waits"]},
    )
    for raw in hidden:
        with pytest.raises(Refusal, match="Vex"):
            _ = speak.call(_draft(), raw, Random(0))
    facts = speak.call(_draft(), {"plain": "Vex waits"}, Random(0))

    assert [fact.trace for fact in facts] == ["spoken"]


def _draft() -> AnyGame:
    return Game[Word](
        scenario_id="trial",
        character_id="player",
        scenario=ScenarioMeta(
            title="Trial", premise="A trial runs", backdrop="Plain.", scope="One trial"
        ),
        engine_id=EngineId("trial"),
        pack_id="srd",
        world=Word(word="nothing"),
    )


def _trusting(_draft: AnyGame, _texts: tuple[str, ...]) -> None:
    pass


def _refusing_vex(_draft: AnyGame, texts: tuple[str, ...]) -> None:
    if any("Vex" in text for text in texts):
        raise Refusal(f"this names Vex: {texts}")
