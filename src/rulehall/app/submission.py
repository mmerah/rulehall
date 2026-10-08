import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_urlsafe

from pydantic import BaseModel, JsonValue

from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.game import Check
from rulehall.core.tools import MasterTool, ToolSurface
from rulehall.core.validation import Refusal, decode

LOGGER = logging.getLogger(__name__)

SUBMIT = "submit"
SUBMIT_DESCRIPTION = (
    "Submit your complete answer. A refused draft comes back with what is wrong: fix it and "
    "submit again. An accepted draft ends your work."
)
ACCEPTED = "accepted: stop here and exit"
UNSUBMITTED = "You stopped with no accepted answer. Call `submit` now with your complete answer."
NO_SUBMISSION = "no answer is open for this call: stop here and exit"


@dataclass(slots=True)
class Submission[T: BaseModel]:
    model: type[T]
    check: Check[T]
    accepted: T | None = None

    @property
    def must_stop(self) -> bool:
        return self.accepted is not None

    @property
    def nudge(self) -> str:
        return UNSUBMITTED

    def published_tools(self) -> tuple[MasterTool, ...]:
        return (MasterTool(SUBMIT, SUBMIT_DESCRIPTION, self.model),)

    def call_tool(self, name: str, arguments: str | dict[str, JsonValue]) -> str:
        if self.accepted is not None:
            return ACCEPTED
        try:
            self.accepted = self._checked(name, arguments)
        except Refusal as refused:
            LOGGER.warning("the rules refused %s: %s", name, refused)
            raise
        return ACCEPTED

    def _checked(self, name: str, arguments: str | dict[str, JsonValue]) -> T:
        if name != SUBMIT:
            raise Refusal(f"{name!r} is not a tool now")
        answer = parse_with_repairs(
            self.model, decode(arguments) if isinstance(arguments, str) else arguments
        )
        self.check(answer)
        return answer


@dataclass(slots=True)
class Submissions:
    opened: dict[str, ToolSurface] = field(default_factory=dict)

    @contextmanager
    def open(self, surface: ToolSurface) -> Generator[str]:
        token = token_urlsafe(16)
        self.opened[token] = surface
        try:
            yield token
        finally:
            del self.opened[token]

    def find(self, token: str) -> ToolSurface | None:
        return self.opened.get(token)

    def require(self, token: str) -> ToolSurface:
        if (submission := self.find(token)) is None:
            raise Refusal(NO_SUBMISSION)
        return submission
