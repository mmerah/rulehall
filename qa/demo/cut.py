"""Cut the recorded frames into docs/demo: uv run python qa/demo/cut.py /tmp/rulehall-demo.

Needs `ffmpeg` with libx264 and `gifski` on the PATH.
"""

import json
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
LONGEST = 119.8  # seconds; the README promises two minutes at most
PACE = 1.5  # the whole take plays this much faster than it was recorded


def main() -> None:
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rulehall-demo")
    frames = work / "frames"
    out = REPOSITORY_ROOT / "docs" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    master = work / "master.mp4"
    listing = frames / "list.txt"
    length = _write_listing(frames, listing)
    print(f"cut: {length:.1f}s before the cap")
    _ffmpeg(
        *("-f", "concat", "-safe", "0", "-i", str(listing)),
        *("-vf", "fps=60,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "12"),
        str(master),
    )
    end = min(length, LONGEST)
    _ffmpeg(
        *("-i", str(master), "-t", f"{end}"),
        *("-vf", f"fade=in:0:d=0.5,fade=out:st={end - 0.9}:d=0.9"),
        *("-c:v", "libx264", "-preset", "veryslow", "-crf", "22", "-pix_fmt", "yuv420p"),
        *("-movflags", "+faststart", "-an", str(out / "demo.mp4")),
    )
    gif_frames = work / "gif"
    gif_frames.mkdir(exist_ok=True)
    for old in gif_frames.glob("*.png"):
        old.unlink()
    _ffmpeg(
        *("-i", str(out / "demo.mp4"), "-vf", "fps=10,scale=800:-1:flags=lanczos"),
        str(gif_frames / "%05d.png"),
    )
    subprocess.run(
        [
            *("gifski", "--fps", "10", "--quality", "70", "--width", "800", "--quiet"),
            *("-o", str(out / "demo.gif"), *sorted(map(str, gif_frames.glob("*.png")))),
        ],
        check=True,
    )


def _write_listing(frames: Path, listing: Path) -> float:
    """An ffmpeg concat list: each frame lasts until the next, divided by its speed and PACE."""
    timeline = json.loads((frames / "frames.json").read_text())
    shots: list[tuple[float, str]] = timeline["frames"]
    speeds: list[tuple[float, float]] = timeline["speeds"]

    def played(start: float, stop: float) -> float:
        cuts = sorted({start, stop, *(at for at, _ in speeds if start < at < stop)})
        return sum((b - a) / _speed_at(speeds, a) / PACE for a, b in pairwise(cuts))

    lines: list[str] = []
    total = 0.0
    for index, (at, name) in enumerate(shots):
        until = shots[index + 1][0] if index + 1 < len(shots) else timeline["end"]
        duration = played(at, until)
        total += duration
        lines += [f"file '{frames / name}'", f"duration {duration:.5f}"]
    lines.append(f"file '{frames / shots[-1][1]}'")
    listing.write_text("\n".join(lines) + "\n")
    for scene, at in timeline["marks"]:
        print(f"  {scene:8s} at {played(shots[0][0], max(at, shots[0][0])):6.1f}s")
    return total


def _speed_at(speeds: list[tuple[float, float]], moment: float) -> float:
    factor = 1.0
    for at, speed in speeds:
        if at <= moment:
            factor = speed
    return factor


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


if __name__ == "__main__":
    main()
