from asyncio import subprocess, timeout
from collections.abc import Sequence
from dataclasses import dataclass

from rulehall.app.processes import start_child, stop_process
from rulehall.core.validation import Refusal
from rulehall.engines.battles import Battling

SIMULATOR_WAIT = 10.0
LINE_MAX = 1 << 20
STOPPED = "the battle simulator stopped"


@dataclass(slots=True)
class BattleProcess:
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


async def start_battle_process(engine: Battling) -> BattleProcess:
    process = await start_child(
        engine.simulator_argv(), secrets=(), cwd=None, stderr=subprocess.DEVNULL, limit=LINE_MAX
    )
    return BattleProcess(process)
