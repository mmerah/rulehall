import binascii
import logging
from asyncio import Task, create_task, gather
from base64 import b64decode
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha1
from pathlib import Path
from typing import Self

from httpx import HTTPError

from rulehall.app.providers import post_bearer
from rulehall.config import MediaConfig, ProviderConfig, Settings
from rulehall.core.io import FileStore, publish
from rulehall.core.validation import Loose, Refusal, Slug, parse_json
from rulehall.core.views import NarratorView, Subject

LOGGER = logging.getLogger(__name__)

ICON_DIR = "icons"
SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
SCENE_RATIO = "16:9"
ICON_RATIO = "1:1"


@dataclass(slots=True)
class Claims:
    """Keys in generation now, so two callers never both pay for one image."""

    held: set[str] = field(default_factory=set)

    @contextmanager
    def hold(self, key: str) -> Generator[bool]:
        # Synchronous: an await between the read and the write would let two callers both pay.
        won = key not in self.held
        self.held.add(key)
        try:
            yield won
        finally:
            if won:
                self.held.discard(key)


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    suffix: str


@dataclass(frozen=True, slots=True)
class Illustrator:
    config: MediaConfig
    provider: ProviderConfig
    saves: Path
    icon_dirs: tuple[Path, ...]
    style: str
    portraits: bool
    claims: Claims = field(default_factory=Claims)
    tasks: set[Task[None]] = field(default_factory=set)

    @classmethod
    def open(
        cls,
        settings: Settings,
        store: FileStore,
        slug: str,
        *,
        style: str,
        icon_dirs: tuple[Path, ...],
        portraits: bool,
    ) -> Self:
        """Authored icons are shared between games. Drawn art stays with the save."""
        return cls(
            config=settings.media,
            provider=settings.providers.for_name(settings.media.provider),
            saves=store.media_dir(slug),
            icon_dirs=icon_dirs,
            style=style,
            portraits=portraits,
        )

    def configured(self, settings: Settings) -> Self:
        return replace(
            self,
            config=settings.media,
            provider=settings.providers.for_name(settings.media.provider),
        )

    def scene_art(self, scene: NarratorView) -> Path | None:
        return _existing(self.saves, scene_key(scene)) if self.config.enabled else None

    def icon(self, entity_id: Slug) -> Path | None:
        if not self.config.enabled:
            return None
        for directory in (*self.icon_dirs, self.saves / ICON_DIR):
            found = _existing(directory, entity_id)
            if found is not None:
                return found
        return None

    def illustrate_later(self, scene: NarratorView, player: Subject) -> None:
        task = create_task(self.illustrate(scene, player))
        # Kept because asyncio can collect a task that nothing refers to.
        self.tasks.add(task)
        task.add_done_callback(self._finished)

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await gather(*tasks, return_exceptions=True)

    async def illustrate(self, scene: NarratorView, player: Subject) -> None:
        if not self.config.enabled:
            return
        key = scene_key(scene)
        try:
            with self.claims.hold(key) as drawing:
                await self._drawn_icon(player)
                if drawing and _existing(self.saves, key) is None:
                    await self._draw(scene, key)
                # Outside the scene cache: a subject revealed later still needs its icon.
                for subject in scene.subjects:
                    await self._drawn_icon(subject)
        except (HTTPError, OSError, Refusal) as failed:
            LOGGER.warning("image generation failed: %s", failed)

    def _finished(self, task: Task[None]) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and (failed := task.exception()) is not None:
            LOGGER.exception("scene art failed", exc_info=failed)

    async def _draw(self, scene: NarratorView, key: str) -> None:
        generated = await self._generate(illustration_request(scene, self.style), SCENE_RATIO)
        publish(
            self.saves / f"{key}{generated.suffix}",
            lambda staged: staged.write_bytes(generated.data),
        )

    async def _drawn_icon(self, subject: Subject) -> Path | None:
        """The loser of the claim race gets no icon and does not wait."""
        found = self.icon(subject.id)
        if found is not None or not self.portraits:
            return found
        # An entity id is `[a-z0-9_-]+`, so the colon keeps icon claims off the scene keys.
        with self.claims.hold(f"icon:{subject.id}") as drawing:
            if not drawing:
                return None
            generated = await self._generate(_icon_request(subject, self.style), ICON_RATIO)
            # Authored directories stay authored: a drawn icon belongs to the save.
            path = self.saves / ICON_DIR / f"{subject.id}{generated.suffix}"
            publish(path, lambda staged: staged.write_bytes(generated.data))
            return path

    async def _generate(self, prompt: str, ratio: str) -> GeneratedImage:
        content = await post_bearer(
            self.provider,
            "/chat/completions",
            {
                "model": self.config.model,
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": ratio},
                "messages": [{"role": "user", "content": prompt}],
            },
            self.config.timeout,
        )
        url = parse_json(_ImageReply, content).url()
        if url is None:
            raise Refusal("image reply held no image")
        return _decode(url)


class _ImageUrl(Loose):
    url: str


class _Image(Loose):
    image_url: _ImageUrl


class _Message(Loose):
    images: tuple[_Image, ...] = ()


class _ImageChoice(Loose):
    message: _Message


class _ImageReply(Loose):
    choices: tuple[_ImageChoice, ...] = ()

    def url(self) -> str | None:
        images = self.choices[0].message.images if self.choices else ()
        return images[0].image_url.url if images else None


def scene_key(scene: NarratorView) -> str:
    """Hashed because `place_id` names a file."""
    return sha1(scene.place_id.encode(), usedforsecurity=False).hexdigest()[:12]


def illustration_request(scene: NarratorView, style: str) -> str:
    return (
        "Draw one wide view of this place, with no border. Use the eye level of a person who "
        "is there. Draw the place only. Do not draw people or creatures. "
        "Do not draw a comic panel.\n"
        f"The place: {scene.title} — {scene.situation}\n"
        f"{style}"
    )


def _icon_request(subject: Subject, style: str) -> str:
    return (
        f"Draw a portrait token of {subject.name} — {subject.brief}, with no border. "
        f"Put the subject alone in the centre and fill the square. Use a plain background. "
        f"Show only the items that the subject carries. {style}"
    )


def _decode(url: str) -> GeneratedImage:
    header, _, payload = url.partition(",")
    suffix = SUFFIXES.get(header.removeprefix("data:").removesuffix(";base64"))
    if suffix is None or not payload:
        raise Refusal(f"image reply is not a supported data uri: {header[:40]!r}")
    try:
        data = b64decode(payload)
    except binascii.Error as broken:
        raise Refusal(f"image reply is not base64: {broken}") from broken
    return GeneratedImage(data=data, suffix=suffix)


def _existing(directory: Path, stem: str) -> Path | None:
    """The reply names the format, so a cached file is found by stem rather than assumed png."""
    candidates = (directory / f"{stem}{suffix}" for suffix in SUFFIXES.values())
    return next((path for path in candidates if path.is_file()), None)
