from random import Random
from typing import Annotated, Literal

import pytest
from pydantic import Field

from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame
from rulehall.core.tools import PlayerFacing, action, marked_methods, player_facing_texts, tool
from rulehall.core.validation import Frozen, Refusal, Slug

type Kind = Literal["gear", "condition"]
Tag = Annotated[str, Field(max_length=12)]


class Word(Frozen):
    word: str = Field(description="One word the master fills in.")


class Slips(Frozen):
    target_id: Slug | None = None
    tags: tuple[Tag, ...] = ()
    tag: Tag = ""
    words: tuple[Word, ...] = ()


class Filed(Frozen):
    tags: dict[Kind, list[Tag]] = Field(default_factory=dict)


class Cast(Frozen):
    cast: dict[Slug, Filed] = Field(default_factory=dict)
    details: tuple[Tag, ...] = Field(default=(), max_length=2)


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
    note: PlayerFacing = Field(description="A note the player reads.")


class Telling(Frozen):
    aside: Aside | None = Field(default=None, description="An optional aside.")
    lines: tuple[PlayerFacing, ...] = Field(default=(), description="Lines the player reads.")
    plain: str = Field(default="", description="A text the player never reads.")


class Quiet:
    def touch(self, _draft: AnyGame, args: Word, _rng: Random) -> list[Fact]:
        return [Fact(trace=args.word)]


def test_the_published_order_is_the_bases_tools_then_the_subclasss() -> None:
    published = marked_methods(Adding(), "tool")

    assert list(published) == ["first", "second", "third"]
    assert published["second"].description == "The override's own description, not the base's."


def test_an_unmarked_override_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no @tool mark"):
        _ = marked_methods(Overriding(), "tool")


def test_a_method_with_no_description_is_refused_where_it_is_marked() -> None:
    with pytest.raises(ValueError, match="carries no description"):
        _ = tool(Quiet.touch)


def test_an_action_is_published_to_the_page_and_never_to_the_master() -> None:
    acting = Acting()

    assert list(marked_methods(acting, "tool")) == ["first", "second"]
    assert list(marked_methods(acting, "action")) == ["second", "fourth"]


def test_a_told_field_in_a_nested_model_or_a_tuple_is_read_and_a_plain_one_is_not() -> None:
    told = Telling(aside=Aside(note="Vex waits"), lines=("a door", "a bell"), plain="Vex hides")

    assert list(player_facing_texts(told)) == ["Vex waits", "a door", "a bell"]


def test_a_harmless_slip_is_mended_before_validation_and_a_real_error_still_refused() -> None:
    mended = parse_with_repairs(
        Slips, {"target_id": "null", "tags": "Cold Air", "words": [{"word": "fine"}]}
    )

    assert mended == Slips(tags=("Cold Air",), words=(Word(word="fine"),))
    assert parse_with_repairs(Slips, {"target_id": "None"}).target_id is None
    with pytest.raises(Refusal, match="target_id"):
        _ = parse_with_repairs(Slips, {"target_id": "Not An Id"})
    with pytest.raises(Refusal, match="tag"):
        _ = parse_with_repairs(Slips, {"tag": "Rats in a Barrel"})


def test_a_field_no_schema_names_is_dropped_at_every_depth_and_a_cast_key_is_kept() -> None:
    mended = parse_with_repairs(
        Cast,
        {"cast": {"rats": {"tags": {}, "alive": False}}, "details": [], "harm": True},
    )

    assert mended == Cast(cast={"rats": Filed()})
    with pytest.raises(Refusal, match="Rats"):
        _ = parse_with_repairs(Cast, {"cast": {"Rats": {}}})
