from asyncio import subprocess, timeout
from collections.abc import Sequence
from dataclasses import dataclass

from rulehall.app.spawn import child_environment, stop_process
from rulehall.core.validation import Refusal
from rulehall.engines.engine import AnyEngine

SIMULATOR_WAIT = 10.0
LINE_MAX = 1 << 20
STOPPED = "the battle simulator stopped"


@dataclass(slots=True)
class LineProcess:
    process: subprocess.Process

    async def send(self, lines: Sequence[str]) -> None:
        stdin = self.process.stdin
        assert stdin is not None
        try:
            stdin.write("".join(f"{line}\n" for line in lines).encode())
            await stdin.drain()
        except OSError as failed:
            raise Refusal(STOPPED) from failed

    async def receive(self) -> tuple[str, ...]:
        stdout = self.process.stdout
        assert stdout is not None
        lines: list[str] = []
        try:
            async with timeout(SIMULATOR_WAIT):
                while True:
                    raw = await stdout.readline()
                    if not raw:
                        raise Refusal(STOPPED)
                    if line := raw.decode().removesuffix("\n"):
                        lines.append(line)
                    elif lines:
                        return tuple(lines)
        except TimeoutError:
            raise Refusal(
                f"the battle simulator answered nothing in {SIMULATOR_WAIT:.0f}s"
            ) from None

    async def close(self) -> None:
        await stop_process(self.process)


async def start_process(engine: AnyEngine) -> LineProcess:
    command = engine.simulator_argv()
    try:
        process = await subprocess.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=child_environment(()),
            start_new_session=True,
            limit=LINE_MAX,
        )
    except OSError as failed:
        raise Refusal(f"{command[0]} is not installed") from failed
    return LineProcess(process)
