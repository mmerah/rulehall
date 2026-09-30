import logging
from asyncio import Task, create_task, gather
from collections.abc import Coroutine, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Claims:
    held: set[str] = field(default_factory=set)

    @contextmanager
    def hold(self, key: str) -> Generator[bool]:
        # Synchronous: an await between the read and the write would let two callers both pay.
        won = key not in self.held
        self.held.add(key)
        try:
            yield won
        finally:
            if won:
                self.held.discard(key)


@dataclass(slots=True)
class BackgroundTasks:
    tasks: set[Task[None]] = field(default_factory=set)

    def start(self, work: Coroutine[object, object, None], failure: str) -> None:
        task = create_task(work)
        # Kept because asyncio can collect a task that nothing refers to.
        self.tasks.add(task)
        task.add_done_callback(partial(self._finished, failure))

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await gather(*tasks, return_exceptions=True)

    def _finished(self, failure: str, task: Task[None]) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and (failed := task.exception()) is not None:
            LOGGER.exception(failure, exc_info=failed)
