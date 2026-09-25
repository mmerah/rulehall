from asyncio import gather, sleep
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import SecretStr
from support.game import TARGET, initialized, with_entity
from support.table import offline_settings

from rulehall.app.illustration import (
    ICON_DIR,
    GeneratedImage,
    Illustrator,
    illustration_request,
    scene_key,
)
from rulehall.config import MediaConfig, ProviderConfig
from rulehall.core.io import FileStore
from rulehall.core.views import NarratorView
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner3e.world import Loner3eEntity, Loner3eGame

STYLE = "Painterly fantasy illustration, muted colours, no text or lettering."


def _illustrator(saves: Path, icon_dirs: tuple[Path, ...] = ()) -> Illustrator:
    return Illustrator(
        config=MediaConfig(enabled=True),
        provider=ProviderConfig(base_url="https://example.invalid/v1", api_key=SecretStr("test")),
        saves=saves,
        icon_dirs=icon_dirs,
        style=STYLE,
        portraits=True,
    )


def _placed(state: Loner3eGame, name: str, *, known: bool) -> Loner3eGame:
    return with_entity(
        state,
        Loner3eEntity(
            id=name.lower().replace(" ", "-"),
            name=name,
            brief=f"A {name.lower()}.",
            known=known,
            concept=name,
        ),
    )


def _scene(engine: AnyEngine, state: Loner3eGame) -> NarratorView:
    return engine.narrator_view(state)


def test_illustration_request_names_the_scene_and_nobody_in_it() -> None:
    engine, state = initialized()
    state = _placed(_placed(state, "Brass Warden", known=True), "Pale Watcher", known=False)
    request = illustration_request(_scene(engine, state), STYLE)
    assert state.world.scene.title in request
    assert "Brass Warden" not in request
    assert "Pale Watcher" not in request


async def test_concurrent_illustrations_of_one_scene_generate_it_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, state = initialized()
    scene = engine.narrator_view(state)
    player = engine.player_view(state).player
    prompts: list[str] = []

    async def _generate(_self: Illustrator, prompt: str, _ratio: str) -> GeneratedImage | None:
        prompts.append(prompt)
        await sleep(0)  # a real generation suspends; without this nothing can interleave
        return GeneratedImage(data=b"\x89PNG", suffix=".png")

    monkeypatch.setattr(Illustrator, "_generate", _generate)
    illustrator = _illustrator(tmp_path / "save.media")
    _ = await gather(
        illustrator.illustrate(scene, player),
        illustrator.illustrate(scene, player),
    )
    scene_prompts = [prompt for prompt in prompts if prompt.startswith("Draw one wide")]
    assert len(scene_prompts) == 1
    # Every other prompt is an icon: a repeat is a second bill for the same picture.
    assert len(prompts) == len(set(prompts))
    assert illustrator.claims.held == set()


async def test_a_subject_revealed_in_a_cached_scene_still_gets_an_icon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, state = initialized()
    player = engine.player_view(state).player

    async def _generate(_self: Illustrator, _prompt: str, _ratio: str) -> GeneratedImage | None:
        return GeneratedImage(data=b"\x89PNG", suffix=".png")

    monkeypatch.setattr(Illustrator, "_generate", _generate)
    illustrator = _illustrator(tmp_path / "save.media")
    await illustrator.illustrate(_scene(engine, state), player)
    assert illustrator.icon("brass-warden") is None

    revealed = _placed(state, "Brass Warden", known=True)
    await illustrator.illustrate(_scene(engine, revealed), player)

    assert illustrator.icon("brass-warden") is not None


async def test_an_engine_without_portraits_draws_the_scene_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, state = initialized()
    state = _placed(state, "Brass Warden", known=True)
    player = engine.player_view(state).player
    prompts: list[str] = []

    async def _generate(_self: Illustrator, prompt: str, _ratio: str) -> GeneratedImage | None:
        prompts.append(prompt)
        return GeneratedImage(data=b"\x89PNG", suffix=".png")

    monkeypatch.setattr(Illustrator, "_generate", _generate)
    illustrator = replace(_illustrator(tmp_path / "save.media"), portraits=False)
    await illustrator.illustrate(_scene(engine, state), player)

    assert len(prompts) == 1
    assert prompts[0].startswith("Draw one wide")
    assert illustrator.icon(player.id) is None
    assert illustrator.icon("brass-warden") is None


async def test_media_off_asks_for_no_art_and_hides_what_an_earlier_run_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, state = initialized()
    scene = _scene(engine, state)
    player = engine.player_view(state).player
    prompts: list[str] = []

    async def _generate(_self: Illustrator, prompt: str, _ratio: str) -> GeneratedImage | None:
        prompts.append(prompt)
        return GeneratedImage(data=b"\x89PNG", suffix=".png")

    monkeypatch.setattr(Illustrator, "_generate", _generate)
    off = Illustrator.open(
        offline_settings(tmp_path),
        FileStore(tmp_path),
        TARGET.slug,
        style=STYLE,
        icon_dirs=(),
        portraits=True,
    )

    await off.illustrate(scene, player)
    assert prompts == []
    (off.saves / ICON_DIR).mkdir(parents=True)
    (off.saves / ICON_DIR / f"{player.id}.png").write_bytes(b"")
    (off.saves / f"{scene_key(scene)}.png").write_bytes(b"")

    assert off.scene_art(scene) is None
    assert off.icon(player.id) is None
