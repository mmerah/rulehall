from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import Protocol, TypeGuard

from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame, RoleAnswer
from rulehall.core.views import BattleChoice, BattleHeader
from rulehall.engines.engine import AnyEngine, Resolution


class Transport(Protocol):
    async def send(self, lines: Sequence[str]) -> None: ...
    async def receive(self) -> tuple[str, ...]: ...
    async def close(self) -> None: ...


class BattleRun[G](Protocol):
    @property
    def log(self) -> Sequence[str]: ...
    @property
    def facts(self) -> Sequence[Fact]: ...
    def props(self) -> Mapping[str, str | bool]: ...
    def header(self) -> BattleHeader: ...
    @property
    def resolution(self) -> Resolution | None: ...
    def choices(self) -> tuple[BattleChoice, ...]: ...
    async def choose(self, draft: G, command: str, rng: Random) -> None: ...
    async def close(self) -> None: ...


class Battling(ABC):
    battle_script: Path

    @abstractmethod
    def in_battle(self, state: AnyGame, /) -> bool: ...
    @abstractmethod
    def simulator_argv(self) -> tuple[str, ...]: ...
    @abstractmethod
    async def open_battle(
        self, draft: AnyGame, transport: Transport, opponent: RoleAnswer | None
    ) -> BattleRun[AnyGame]: ...


def in_battle(engine: AnyEngine, state: AnyGame) -> TypeGuard[Battling]:
    return isinstance(engine, Battling) and engine.in_battle(state)
