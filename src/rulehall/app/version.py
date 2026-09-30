from functools import cache
from os import environ
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run


@cache
def app_version() -> str:
    if configured := environ.get("RULEHALL_VERSION"):
        return configured
    try:
        return run(
            ["git", "describe", "--tags", "--long", "--dirty"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            cwd=Path(__file__).parent,
        ).stdout.strip()
    except (CalledProcessError, FileNotFoundError, TimeoutExpired):
        return "dev"
