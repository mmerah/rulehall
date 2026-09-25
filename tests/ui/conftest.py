from asyncio import get_running_loop
from collections.abc import Callable, Generator

import pytest
from nicegui import Client, core, ui
from nicegui.slot import Slot, get_task_id


@pytest.fixture
def page() -> Generator[Callable[[], Client]]:
    """A client whose slot the test enters from its own task, so built elements land in it."""
    client = Client(ui.page("/"))
    entered: list[int] = []

    def enter() -> Client:
        # A refreshable's background task asserts NiceGUI's loop is set; only `ui.run()` sets it.
        try:
            core.loop = get_running_loop()
        except RuntimeError:
            core.loop = None
        _ = client.__enter__()
        entered.append(get_task_id())
        return client

    yield enter
    for task_id in entered:
        _ = Slot.stacks.pop(task_id, None)
    if not client.is_deleted:
        client.delete()
    core.loop = None


@pytest.fixture
def notified(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every toast the page raises, in order."""
    messages: list[str] = []

    def notify(message: str, **_kwargs: object) -> None:
        messages.append(message)

    monkeypatch.setattr("rulehall.ui.widgets.ui.notify", notify)
    return messages
