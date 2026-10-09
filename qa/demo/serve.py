"""The real app, on a fresh copy of the data, for the demo recording.

    uv run python qa/demo/serve.py /tmp/rulehall-demo/work [--live]

The settings come from `.env` like `uv run rulehall`. The saves start empty. The master, the
narrator and the worldsmith answer from `script.json`; `--live` asks the real AI roles instead.
"""

import logging
import shutil
from argparse import ArgumentParser
from pathlib import Path

from nicegui import ui
from roles import DemoRoles, DemoScript

from rulehall.app.runtime import Runtime
from rulehall.config import LOOPBACK_HOST, ServerConfig, read_settings
from rulehall.main import mount

PORT = 8190


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--live", action="store_true", help="ask the real AI roles")
    parsed = parser.parse_args()
    work = Path(parsed.work).resolve()
    if work.exists():
        shutil.rmtree(work)
    saves = work / "saves"
    saves.mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    read = read_settings()
    settings = read.model_copy(
        update={
            "saves_dir": saves,
            "scenarios_dir": work / "scenarios",
            "characters_dir": work / "characters",
            "packs_dir": work / "packs",
            "server": ServerConfig(port=PORT),
            "pokemon": read.pokemon.model_copy(update={"opponent": "scripted"}),
        }
    )
    mount(Runtime(settings, roles=None if parsed.live else DemoRoles(DemoScript.read())))
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
