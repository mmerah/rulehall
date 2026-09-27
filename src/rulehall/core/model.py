from collections.abc import Callable
from copy import deepcopy
from typing import Any, Protocol, Self

from pydantic import BaseModel, Field

from rulehall.core.facts import Fact
from rulehall.core.play import Chapter, Exchange, PendingDecision
from rulehall.core.prompt import Prompt
from rulehall.core.validation import (
    EngineHeader,
    EngineId,
    Frozen,
    Loose,
    Mutable,
    Refusal,
    Slug,
    parse,
)

type AnyScenario = Scenario[Any]
type AnyCharacter = Character[Any]
type AnyGame = Game[Any]
type Check[T] = Callable[[T], None]


class ScenarioDescription(Frozen):
    title: str
    premise: str
    backdrop: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    art_style: str = ""

    def check_drift(self, other: Self) -> None:
        fields = ScenarioDescription.model_fields
        if drifted := [name for name in fields if getattr(self, name) != getattr(other, name)]:
            raise Refusal(f"save scenario differs from the one on disk in: {', '.join(drifted)}")


class SheetHeader(Loose):
    name: str
    brief: str = ""


class CharacterHeader(EngineHeader):
    id: Slug
    sheet: SheetHeader


class Scenario[O: BaseModel](Frozen):
    description: ScenarioDescription
    engine_id: EngineId
    pack_id: Slug
    source: str = ""
    opening: O


class Character[S: BaseModel](Frozen):
    id: Slug
    engine_id: EngineId
    sheet: S


class RoleAnswer(Protocol):
    async def __call__[M: BaseModel](
        self, prompt: Prompt, model: type[M], check: Check[M], /
    ) -> M: ...


class WorldsmithRequest(Frozen):
    kind: Slug
    detail: str = ""
    target_id: Slug | None = None


class Game[W: BaseModel](Mutable):
    scenario_id: Slug
    character_id: Slug
    scenario_description: ScenarioDescription
    engine_id: EngineId
    pack_id: Slug
    source: str = ""
    pending: PendingDecision | None = None
    # `exclude=True` keeps it out of every save, so `restore` only refuses a hand-edited one.
    request: WorldsmithRequest | None = Field(default=None, exclude=True)
    directed: bool = Field(default=False, exclude=True)
    notes: list[str] = Field(default_factory=list)
    unnarrated: list[Fact] = Field(default_factory=list)
    log: list[Chapter] = Field(default_factory=list)
    world: W

    def note(self, text: str) -> None:
        self.notes.append(text)

    def exchanges(self) -> tuple[Exchange, ...]:
        return tuple(exchange for chapter in self.log for exchange in chapter.exchanges)

    def last_words(self) -> str:
        return next(
            (
                exchange.words
                for exchange in reversed(self.exchanges())
                if exchange.words and not exchange.by_option
            ),
            "",
        )

    def draft(self) -> Self:
        return deepcopy(self)

    def commit(self) -> Self:
        try:
            return parse(type(self), self)
        except Refusal as refused:
            raise Refusal(f"the state this leaves is invalid: {refused}") from refused
