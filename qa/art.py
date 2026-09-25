"""Placeholder scene art for the QA server: a 16:9 gradient drawn offline, never a provider call.

Real generation needs a key and a network. The layout only needs a picture of the right shape.
"""

import struct
import zlib
from hashlib import sha1

from rulehall.app.illustration import ICON_RATIO, GeneratedImage, Illustrator

WIDTH = 960
HEIGHT = 540
ICON_SIDE = 256


async def generate_placeholder(
    _illustrator: Illustrator, prompt: str, ratio: str
) -> GeneratedImage:
    # Keyed off the prompt's hash, so a place keeps its own picture.
    width, height = (ICON_SIDE, ICON_SIDE) if ratio == ICON_RATIO else (WIDTH, HEIGHT)
    return GeneratedImage(data=gradient_png(prompt, width, height), suffix=".png")


def gradient_png(seed: str, width: int, height: int) -> bytes:
    digest = sha1(seed.encode(), usedforsecurity=False).digest()
    top = tuple(digest[0:3])
    bottom = tuple(digest[3:6])
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        blend = y / max(height - 1, 1)
        band = 26 if (y // 24) % 2 else 0
        pixel = bytes(
            min(255, int(top[c] * (1 - blend) + bottom[c] * blend) // 2 + band) for c in range(3)
        )
        rows += pixel * width
    return _png(width, height, bytes(rows))


def _png(width: int, height: int, raw: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        _chunk(name, body)
        for name, body in ((b"IHDR", header), (b"IDAT", zlib.compress(raw, 6)), (b"IEND", b""))
    )


def _chunk(name: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + name + body + struct.pack(">I", zlib.crc32(name + body))
