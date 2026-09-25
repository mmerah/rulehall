"""The real app with the real AI roles, on a fresh copy of the data, for the demo recording.

    uv run python qa/demo/serve.py /tmp/rulehall-demo/work

The settings come from `.env` like `uv run rulehall`. The saves start empty, except a played 24XX
save (`saves/silent-relay--kael.*`) that the relay scene shows when it exists.
"""

import logging
import shutil
import sys
from pathlib import Path

from nicegui import ui

from rulehall.app.runtime import Runtime
from rulehall.config import LOOPBACK_HOST, ServerConfig, read_settings
from rulehall.ui import theme
from rulehall.ui.app import mount

REPOSITORY_ROOT = Path(__file__).parents[2]
PORT = 8190
RELAY_SAVE = "silent-relay--kael"


def main() -> None:
    work = Path(sys.argv[1]).resolve()
    if work.exists():
        shutil.rmtree(work)
    for name in ("scenarios", "characters"):
        shutil.copytree(REPOSITORY_ROOT / name, work / name)
    saves = work / "saves"
    saves.mkdir()
    for played in (REPOSITORY_ROOT / "saves").glob(f"{RELAY_SAVE}.*"):
        copy = shutil.copytree if played.is_dir() else shutil.copy2
        copy(played, saves / played.name)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = read_settings().model_copy(
        update={
            "saves_dir": saves,
            "scenarios_dir": work / "scenarios",
            "characters_dir": work / "characters",
            "packs_dir": work / "packs",
            "server": ServerConfig(port=PORT),
        }
    )
    mount(Runtime(settings))
    theme.install()
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="Rulehall",
        host=LOOPBACK_HOST,
        port=PORT,
        reload=False,
        show=False,
        show_welcome_message=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
