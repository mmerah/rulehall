from collections.abc import Callable
from pathlib import Path

from nicegui import Client, ui
from support.game import KEY
from support.table import LONER4E, ScriptedRoles, offline_settings

from rulehall.app.runtime import Runtime
from rulehall.ui.hall import Hall
from rulehall.ui.widgets import DICE_CLIP, SOUNDS_DIR


def test_an_unresumable_save_renders_no_play_button(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    _ = (tmp_path / f"{KEY.save_id}.json").write_bytes(b"\xff\xfe not text")
    runtime = Runtime(offline_settings(tmp_path), roles=ScriptedRoles())
    client = page()

    hall = Hall(runtime, LONER4E, KEY.character_id)
    hall.draw()

    elements = client.elements.values()
    assert hall.catalog.unresumable == (KEY.save_id,)
    assert not any(
        isinstance(element, ui.button) and element.text.startswith(("Start", "Continue"))
        for element in elements
    )
    assert any(
        isinstance(element, ui.label) and "cannot be resumed" in element.text
        for element in elements
    )


def test_each_clip_the_page_plays_has_a_wav_in_the_sounds_directory() -> None:
    present = {clip.stem for clip in SOUNDS_DIR.glob("*.wav")}

    assert DICE_CLIP in present
