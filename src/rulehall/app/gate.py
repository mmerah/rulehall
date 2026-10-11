from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic

from rulehall.core.validation import Refusal

IN_FLIGHT_HERE = "a turn is already running in this game"
IN_FLIGHT_ELSEWHERE = "another game is taking a turn: wait for that turn to end, then try again"


class Busy(Refusal):
    def __init__(self, *, elsewhere: bool) -> None:
        super().__init__(IN_FLIGHT_ELSEWHERE if elsewhere else IN_FLIGHT_HERE)
        self.elsewhere = elsewhere


@dataclass(slots=True)
class Gate[Holder]:
    admitted: Holder | None = field(default=None, repr=False)
    creating: int = 0
    active_at: float = field(default_factory=monotonic)

    @property
    def busy(self) -> bool:
        return self.admitted is not None or self.creating > 0

    def status(self) -> dict[str, bool | float]:
        idle_seconds = 0.0 if self.busy else monotonic() - self.active_at
        return {"busy": self.busy, "idle_seconds": idle_seconds}

    @contextmanager
    def creation(self) -> Generator[None]:
        self.creating += 1
        try:
            yield
        finally:
            self.creating -= 1
            self.active_at = monotonic()

    @contextmanager
    def admit(self, holder: Holder) -> Generator[None]:
        if self.admitted is not None:
            raise Busy(elsewhere=self.admitted is not holder)
        self.admitted = holder
        try:
            yield
        finally:
            self.admitted = None
            self.active_at = monotonic()
