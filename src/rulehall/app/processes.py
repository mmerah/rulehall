import os
import shutil
import signal
import sys
from asyncio import shield, subprocess
from collections.abc import Sequence
from contextlib import suppress
from subprocess import DEVNULL, run

from rulehall.core.validation import Refusal

# The child gets nothing else: the parent shell may hold keys no role may see.
# The names past TERM are Windows ones: the CLIs need them to start and to find their logins.
KEPT_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "TERM",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
)


def child_environment(secrets: Sequence[str]) -> dict[str, str]:
    return {name: os.environ[name] for name in (*KEPT_ENV, *secrets) if name in os.environ}


async def start_child(
    argv: Sequence[str], *, secrets: Sequence[str], cwd: str | None, stderr: int, limit: int
) -> subprocess.Process:
    env = child_environment(secrets)
    # PATHEXT finds the `.cmd` shim npm installs on Windows, which a bare name misses.
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is None:
        raise Refusal(f"{argv[0]} could not be started: it is not on the PATH")
    try:
        return await subprocess.create_subprocess_exec(
            executable,
            *argv[1:],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            cwd=cwd,
            env=env,
            start_new_session=True,
            limit=limit,
        )
    except OSError as failed:
        raise Refusal(f"{argv[0]} could not be started: {failed}") from failed


async def stop_process(process: subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        _kill_tree(process.pid)
    # Shielded: a second cancel would abandon the wait mid-reap.
    await shield(process.wait())


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        # Windows has no process groups; `/T` also kills the child a `.cmd` shim started.
        _ = run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=DEVNULL, stderr=DEVNULL)
    else:
        os.killpg(pid, signal.SIGKILL)
