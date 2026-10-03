from functools import cache
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run

VERSION_FILE = Path(__file__).with_name("VERSION")


@cache
def app_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
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
