"""The real app, served with scripted roles in place of the AI. For UI checks, not for play.

    uv run python qa/server.py --port 8123 --work /tmp/rulehall-qa

The work directory gets copies of the shipped scenarios and characters, an empty saves folder,
and the `.env` the settings page writes. `/qa/log` lists every spawn the roles answered.
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from nicegui import app, ui

sys.path.insert(0, str(Path(__file__).parent))
from agents import ScriptedAgents
from art import generate_placeholder

from rulehall.app.illustration import Illustrator
from rulehall.app.launch import LaunchTarget
from rulehall.app.runtime import Runtime
from rulehall.app.session import GameService
from rulehall.config import LOOPBACK_HOST, MediaConfig, ServerConfig, Settings
from rulehall.ui import theme
from rulehall.ui.app import mount

REPOSITORY_ROOT = Path(__file__).parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--fresh", action="store_true", help="wipe the work directory first")
    parser.add_argument("--art", action="store_true", help="draw placeholder scene art offline")
    parsed = parser.parse_args()
    work: Path = parsed.work.resolve()
    if parsed.fresh and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    for name in ("scenarios", "characters"):
        if not (work / name).exists():
            shutil.copytree(REPOSITORY_ROOT / name, work / name)
    (work / "saves").mkdir(exist_ok=True)
    os.chdir(work)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if parsed.art:
        _draw_offline()
    settings = Settings(
        saves_dir=work / "saves",
        scenarios_dir=work / "scenarios",
        characters_dir=work / "characters",
        packs_dir=work / "packs",
        server=ServerConfig(port=parsed.port),
        # Only under `--art`: the default provider is what the settings scenario checks against.
        media=MediaConfig(enabled=True, provider="local") if parsed.art else MediaConfig(),
    )
    _seed_dice()
    agents = ScriptedAgents(delay=parsed.delay)
    # The built agents are passed so a reload, which rebuilds the runtime, keeps them.
    runtime = Runtime(settings, spawner=agents)
    agents.runtime = runtime
    mount(runtime)

    @app.get("/qa/log")
    def _log() -> list[dict[str, object]]:  # pyright: ignore[reportUnusedFunction]
        return [
            {
                "role": spoken.role,
                "answer": spoken.answer,
                "error": spoken.error,
                "calls": spoken.calls,
                "prompt": spoken.prompt,
            }
            for spoken in agents.log
        ]

    @app.get("/qa/faults")
    def _faults() -> dict[str, list[str]]:  # pyright: ignore[reportUnusedFunction]
        return {role: list(armed) for role, armed in agents.faults.items()}

    theme.install()
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="Rulehall (QA)",
        host=LOOPBACK_HOST,
        port=parsed.port,
        reload=False,
        show=False,
        show_welcome_message=False,
    )


def _draw_offline() -> None:
    """The real illustrator, with the provider call swapped for a gradient."""
    Illustrator._generate = generate_placeholder  # pyright: ignore[reportAttributeAccessIssue]


def _seed_dice() -> None:
    """The real runtime, with each game's dice seeded by its save slug, so QA numbers repeat."""
    open_game = Runtime._open  # pyright: ignore[reportPrivateUsage]

    def seeded(runtime: Runtime, target: LaunchTarget) -> GameService:
        session = open_game(runtime, target)
        session.rng.seed(target.slug)
        return session

    Runtime._open = seeded  # pyright: ignore[reportAttributeAccessIssue]


if __name__ in {"__main__", "__mp_main__"}:
    main()
